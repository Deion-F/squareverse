//! How many particles a machine gets by default. Targets (user, 2026-11-06): 60 fps on the desktop (RTX 2070
//! Super), and on the laptop (Ryzen 5 5650U, integrated Radeon) 60 fps if possible, never below a stable 30.
//!
//! These figures are provisional, picked from the adapter type; phase 1 measures the real cost per particle on
//! both machines and replaces this with a measured budget (and the sim speed adapts within a frame).

use crate::gpu::Gpu;

pub fn default_particles(gpu: &Gpu) -> u32 {
    let name = gpu.summary.name.to_lowercase();
    match gpu.adapter.get_info().device_type {
        wgpu::DeviceType::DiscreteGpu => 1_000_000,
        wgpu::DeviceType::IntegratedGpu => 250_000,
        wgpu::DeviceType::Cpu => 30_000,
        // reached through a translation layer (WSL's D3D12 OpenGL shows up as "Other"): be careful
        _ if name.contains("nvidia") || name.contains("geforce") || name.contains("radeon rx") => 500_000,
        _ => 200_000,
    }
}
