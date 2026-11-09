//! One frame drawn offscreen and saved as a PNG (headless `--snapshot`), so a run's picture can be checked
//! without a window. Same renderer as the window, default look, the view the window opens with.

use std::path::Path;

use anyhow::{Context, Result};

use crate::gpu::Gpu;
use crate::render::{Camera, Look, Renderer};
use crate::sim::Sim;
use crate::timing::GpuTimer;

pub const SIZE: (u32, u32) = (1280, 800);
const FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8UnormSrgb;

pub fn default_look() -> Look {
    Look { square_px: 1.0, brightness: 0.5, exposure: 1.0, show_dm: false, show_gas: true }
}

/// Saves the default view; `show_dm` also draws the dark matter.
pub fn save(gpu: &Gpu, sim: &Sim, path: &Path, show_dm: bool) -> Result<()> {
    let (w, h) = SIZE;
    let d = &gpu.device;
    let tex = d.create_texture(&wgpu::TextureDescriptor {
        label: Some("snapshot"),
        size: wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: FORMAT,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let view = tex.create_view(&Default::default());
    let row = (w * 4).div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT) * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
    let buf = d.create_buffer(&wgpu::BufferDescriptor {
        label: Some("snapshot"),
        size: (row * h) as u64,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::COPY_SRC,
        mapped_at_creation: false,
    });
    let mut renderer = Renderer::new(d, FORMAT);
    let camera = Camera { center_pc: sim.cfg.center_pc, px_per_pc: w.min(h) as f64 / (2.3 * sim.cfg.view_radius_pc()) };
    let mut timer = GpuTimer::new(d, &gpu.queue, false);
    let mut enc = d.create_command_encoder(&Default::default());
    renderer.draw(d, &gpu.queue, &mut enc, &view, SIZE, sim, &camera, &Look { show_dm, ..default_look() }, 0.0, &mut timer);
    enc.copy_texture_to_buffer(
        tex.as_image_copy(),
        wgpu::TexelCopyBufferInfo {
            buffer: &buf,
            layout: wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(row), rows_per_image: Some(h) },
        },
        wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
    );
    gpu.queue.submit([enc.finish()]);
    let data = gpu.read_buffer(&buf)?;
    let mut pixels = Vec::with_capacity((w * h * 4) as usize);
    for y in 0..h as usize {
        pixels.extend_from_slice(&data[y * row as usize..y * row as usize + w as usize * 4]);
    }
    let file = std::fs::File::create(path).with_context(|| format!("creating {}", path.display()))?;
    let mut enc = png::Encoder::new(std::io::BufWriter::new(file), w, h);
    enc.set_color(png::ColorType::Rgba);
    enc.set_depth(png::BitDepth::Eight);
    enc.write_header()?.write_image_data(&pixels)?;
    Ok(())
}
