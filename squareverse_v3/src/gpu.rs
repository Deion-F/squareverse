//! Opening the GPU: pick the best adapter (discrete before integrated, never a software one unless asked), open a
//! device with timestamp queries where the adapter has them, and small helpers for reading buffers back.

use std::sync::Arc;
use std::sync::atomic::{AtomicU8, Ordering};

use anyhow::{Context, Result, anyhow, bail};
use serde::Serialize;

/// What the report and the HUD say about the adapter in use.
#[derive(Clone, Debug, Serialize)]
pub struct AdapterSummary {
    pub name: String,
    pub backend: String,
    pub kind: String,
    pub driver: String,
}

pub struct Gpu {
    pub instance: wgpu::Instance,
    pub adapter: wgpu::Adapter,
    pub device: wgpu::Device,
    pub queue: wgpu::Queue,
    pub summary: AdapterSummary,
    pub timestamps: bool,
}

/// Under WSL the GPU is reachable only through Mesa's D3D12 driver (OpenGL), which Mesa doesn't pick by itself;
/// with an NVIDIA GPU passed through, prefer it over an integrated one. Must run before any other thread starts.
pub fn prepare_platform() {
    if !std::path::Path::new("/dev/dxg").exists() {
        return;
    }
    let set = |k: &str, v: &str| {
        if std::env::var_os(k).is_none() {
            // SAFETY: called first thing in main, before any thread exists.
            unsafe { std::env::set_var(k, v) };
        }
    };
    set("GALLIUM_DRIVER", "d3d12");
    set("EGL_LOG_LEVEL", "fatal");
    if std::path::Path::new("/usr/lib/wsl/lib/libcuda.so").exists() {
        set("MESA_D3D12_DEFAULT_ADAPTER_NAME", "NVIDIA");
    }
}

/// The instance options: from the environment (WGPU_BACKEND etc.), plus DX12's shader compiler: DXC from
/// dxcompiler.dll beside the exe when it is there (vendor/dxc, copied by build.rs), instead of the slow FXC.
pub fn instance_descriptor(display: Option<Box<dyn wgpu::wgt::WgpuHasDisplayHandle>>) -> wgpu::InstanceDescriptor {
    let mut desc = match display {
        Some(d) => wgpu::InstanceDescriptor::new_with_display_handle_from_env(d),
        None => wgpu::InstanceDescriptor::new_without_display_handle_from_env(),
    };
    if std::env::var_os("WGPU_DX12_COMPILER").is_none()
        && let Some(dxc) = dxc_beside_exe()
    {
        desc.backend_options.dx12.shader_compiler = wgpu::Dx12Compiler::DynamicDxc { dxc_path: dxc };
    }
    desc
}

fn dxc_beside_exe() -> Option<String> {
    if !cfg!(windows) {
        return None;
    }
    let path = std::env::current_exe().ok()?.parent()?.join("dxcompiler.dll");
    path.exists().then(|| path.to_string_lossy().into_owned())
}

pub fn summary(adapter: &wgpu::Adapter) -> AdapterSummary {
    let i = adapter.get_info();
    AdapterSummary {
        name: i.name.clone(),
        backend: format!("{:?}", i.backend),
        kind: format!("{:?}", i.device_type),
        driver: format!("{} {}", i.driver, i.driver_info).trim().to_string(),
    }
}

fn rank(adapter: &wgpu::Adapter) -> (u8, u8) {
    let i = adapter.get_info();
    let kind = match i.device_type {
        wgpu::DeviceType::DiscreteGpu => 4,
        wgpu::DeviceType::IntegratedGpu => 3,
        wgpu::DeviceType::VirtualGpu | wgpu::DeviceType::Other => 2,
        wgpu::DeviceType::Cpu => 0,
    };
    // Vulkan first: it compiled our shaders in ~2 s, where DX12 with its built-in compiler (FXC) took ~170 s
    // (measured 2026-11-06; with DXC beside the exe, `instance_descriptor`, DX12 is fast too). Except on Intel:
    // a UHD 630 (driver 26.20.100.7642) crashes the process on Vulkan and runs fine on DX12.
    // Set WGPU_BACKEND to override.
    let intel = i.vendor == 0x8086;
    let backend = match i.backend {
        wgpu::Backend::Vulkan if !intel => 3,
        wgpu::Backend::Dx12 | wgpu::Backend::Metal => 2,
        wgpu::Backend::Vulkan => 1,
        wgpu::Backend::Gl => 1,
        _ => 0,
    };
    (kind, backend)
}

pub fn is_software(adapter: &wgpu::Adapter) -> bool {
    let i = adapter.get_info();
    let name = i.name.to_lowercase();
    i.device_type == wgpu::DeviceType::Cpu
        || ["llvmpipe", "lavapipe", "softpipe", "swiftshader", "microsoft basic render"]
            .iter()
            .any(|s| name.contains(s))
}

pub fn list_adapters(instance: &wgpu::Instance) -> Vec<wgpu::Adapter> {
    pollster::block_on(instance.enumerate_adapters(wgpu::Backends::all()))
}

/// The best adapter: `name` keeps only those whose name contains it (any case); software adapters only with
/// `allow_cpu`; with a surface, only adapters that can draw to it.
pub fn pick_adapter(
    instance: &wgpu::Instance,
    name: Option<&str>,
    allow_cpu: bool,
    surface: Option<&wgpu::Surface>,
) -> Result<wgpu::Adapter> {
    let all = list_adapters(instance);
    let mut found: Vec<wgpu::Adapter> = all
        .into_iter()
        .filter(|a| allow_cpu || !is_software(a))
        .filter(|a| name.is_none_or(|n| a.get_info().name.to_lowercase().contains(&n.to_lowercase())))
        .filter(|a| surface.is_none_or(|s| a.is_surface_supported(s)))
        .collect();
    found.sort_by_key(|a| std::cmp::Reverse(rank(a)));
    found.into_iter().next().ok_or_else(|| {
        anyhow!(
            "no usable GPU adapter{}{} (see --list-adapters; --allow-cpu permits software ones)",
            name.map(|n| format!(" matching \"{n}\"")).unwrap_or_default(),
            if surface.is_some() { " that can draw to the window" } else { "" }
        )
    })
}

impl Gpu {
    pub fn open(instance: wgpu::Instance, adapter: wgpu::Adapter) -> Result<Self> {
        let timestamps = adapter.features().contains(wgpu::Features::TIMESTAMP_QUERY);
        let mut features = wgpu::Features::empty();
        if timestamps {
            features |= wgpu::Features::TIMESTAMP_QUERY;
        }
        let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("squareverse"),
            required_features: features,
            required_limits: adapter.limits(),
            ..Default::default()
        }))
        .context("opening the GPU device")?;
        let summary = summary(&adapter);
        Ok(Self { instance, adapter, device, queue, summary, timestamps })
    }

    /// A device with no window (headless runs and tests).
    pub fn headless(name: Option<&str>, allow_cpu: bool) -> Result<Self> {
        let instance = wgpu::Instance::new(instance_descriptor(None));
        let adapter = pick_adapter(&instance, name, allow_cpu, None)?;
        Self::open(instance, adapter)
    }

    pub fn wait(&self) -> Result<()> {
        self.device
            .poll(wgpu::PollType::Wait { submission_index: None, timeout: None })
            .map(|_| ())
            .map_err(|e| anyhow!("GPU wait failed: {e:?}"))
    }

    /// Copies a buffer (which must have COPY_SRC) back to the CPU, waiting for the GPU.
    pub fn read_buffer(&self, buffer: &wgpu::Buffer) -> Result<Vec<u8>> {
        let size = buffer.size();
        let staging = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("readback"),
            size,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut enc = self.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("readback") });
        enc.copy_buffer_to_buffer(buffer, 0, &staging, 0, size);
        self.queue.submit([enc.finish()]);
        let (tx, rx) = std::sync::mpsc::channel();
        staging.slice(..).map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
        self.wait()?;
        match rx.recv() {
            Ok(Ok(())) => {}
            Ok(Err(e)) => bail!("mapping the readback buffer failed: {e:?}"),
            Err(_) => bail!("the readback never finished"),
        }
        let data = staging.slice(..).get_mapped_range().map_err(|e| anyhow!("{e:?}"))?.to_vec();
        staging.unmap();
        Ok(data)
    }
}

/// Reads a small buffer back without stalling: `copy` records the copy (skipped while the last read is still
/// in flight), `after_submit` starts the mapping, `take` returns the bytes once they are there (a frame or so later).
pub struct AsyncRead {
    buf: wgpu::Buffer,
    state: Arc<AtomicU8>,
    copied: bool,
}

const READ_IDLE: u8 = 0;
const READ_MAPPING: u8 = 1;
const READ_MAPPED: u8 = 2;

impl AsyncRead {
    pub fn new(device: &wgpu::Device, label: &str, size: u64) -> Self {
        let buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(label),
            size,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Self { buf, state: Arc::new(AtomicU8::new(READ_IDLE)), copied: false }
    }

    /// Copies `src` for reading back, unless a read is still under way; returns whether it copied.
    pub fn copy(&mut self, encoder: &mut wgpu::CommandEncoder, src: &wgpu::Buffer) -> bool {
        if !self.copied && self.state.load(Ordering::Acquire) == READ_IDLE {
            encoder.copy_buffer_to_buffer(src, 0, &self.buf, 0, self.buf.size());
            self.copied = true;
            return true;
        }
        false
    }

    pub fn after_submit(&mut self) {
        if !std::mem::take(&mut self.copied) {
            return;
        }
        self.state.store(READ_MAPPING, Ordering::Release);
        let state = self.state.clone();
        self.buf.slice(..).map_async(wgpu::MapMode::Read, move |r| {
            state.store(if r.is_ok() { READ_MAPPED } else { READ_IDLE }, Ordering::Release);
        });
    }

    pub fn take(&mut self) -> Option<Vec<u8>> {
        if self.state.load(Ordering::Acquire) != READ_MAPPED {
            return None;
        }
        let data = self.buf.slice(..).get_mapped_range().ok().map(|d| d.to_vec());
        self.buf.unmap();
        self.state.store(READ_IDLE, Ordering::Release);
        data
    }
}
