//! Compute-shader plumbing: a `Kernel` is one WGSL module with an explicit bind group layout (so all its entry
//! points share one bind group), its pipelines by entry point, and dispatch helpers.

use std::collections::HashMap;

/// What a binding is, in binding order (binding 0 first).
#[derive(Clone, Copy)]
pub enum Bind {
    Uniform,
    Read,
    Write,
}

pub struct Kernel {
    pub layout: wgpu::BindGroupLayout,
    pipelines: HashMap<&'static str, wgpu::ComputePipeline>,
}

/// The WGSL every compute module starts with.
pub fn prelude() -> String {
    format!("{}\n{}\n", include_str!("../shaders/fixed.wgsl"), include_str!("../shaders/common.wgsl"))
}

impl Kernel {
    pub fn new(device: &wgpu::Device, label: &str, src: &str, binds: &[Bind], entries: &[&'static str]) -> Self {
        let layout_entries: Vec<wgpu::BindGroupLayoutEntry> = binds
            .iter()
            .enumerate()
            .map(|(i, b)| wgpu::BindGroupLayoutEntry {
                binding: i as u32,
                visibility: wgpu::ShaderStages::COMPUTE,
                ty: wgpu::BindingType::Buffer {
                    ty: match b {
                        Bind::Uniform => wgpu::BufferBindingType::Uniform,
                        Bind::Read => wgpu::BufferBindingType::Storage { read_only: true },
                        Bind::Write => wgpu::BufferBindingType::Storage { read_only: false },
                    },
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            })
            .collect();
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some(label),
            entries: &layout_entries,
        });
        let pl = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some(label),
            bind_group_layouts: &[Some(&layout)],
            ..Default::default()
        });
        let module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(label),
            source: wgpu::ShaderSource::Wgsl(src.into()),
        });
        let pipelines = entries
            .iter()
            .map(|&e| {
                let p = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                    label: Some(e),
                    layout: Some(&pl),
                    module: &module,
                    entry_point: Some(e),
                    compilation_options: Default::default(),
                    cache: None,
                });
                (e, p)
            })
            .collect();
        Self { layout, pipelines }
    }

    /// A bind group with `buffers[i]` at binding i.
    pub fn bind(&self, device: &wgpu::Device, label: &str, buffers: &[&wgpu::Buffer]) -> wgpu::BindGroup {
        let entries: Vec<wgpu::BindGroupEntry> = buffers
            .iter()
            .enumerate()
            .map(|(i, b)| wgpu::BindGroupEntry { binding: i as u32, resource: b.as_entire_binding() })
            .collect();
        device.create_bind_group(&wgpu::BindGroupDescriptor { label: Some(label), layout: &self.layout, entries: &entries })
    }

    pub fn run(&self, pass: &mut wgpu::ComputePass, entry: &str, bind: &wgpu::BindGroup, groups: Groups) {
        pass.set_pipeline(&self.pipelines[entry]);
        pass.set_bind_group(0, bind, &[]);
        pass.dispatch_workgroups(groups.x, groups.y, 1);
    }
}

pub const MAX_GROUPS_X: u32 = 65_535;

/// A dispatch's workgroups laid out in rows of at most 65,535.
#[derive(Clone, Copy, Debug)]
pub struct Groups {
    pub x: u32,
    pub y: u32,
}

impl Groups {
    /// Enough workgroups of `size` for `items`.
    pub fn for_items(items: u32, size: u32) -> Self {
        Self::count(items.div_ceil(size).max(1))
    }

    pub fn count(total: u32) -> Self {
        let x = total.clamp(1, MAX_GROUPS_X);
        Self { x, y: total.div_ceil(x).max(1) }
    }
}

pub fn storage(device: &wgpu::Device, label: &str, bytes: u64) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some(label),
        size: bytes.max(16),
        usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
}

pub fn uniform<T: bytemuck::Pod>(device: &wgpu::Device, label: &str, value: &T) -> wgpu::Buffer {
    use wgpu::util::DeviceExt;
    device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some(label),
        contents: bytemuck::bytes_of(value),
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
    })
}
