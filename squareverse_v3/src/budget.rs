//! How many particles a machine gets by default. Targets (user, 2026-11-06): 60 fps on the desktop (RTX 2070
//! Super), and on the laptop (Ryzen 5 5650U, integrated Radeon) 60 fps if possible, never below a stable 30.
//!
//! Phase 1 (self-gravity, 2026-11-06, per-particle walk, theta 0.6, a full step a frame): RTX 2070 Super on Vulkan
//! 12.2 ms a step at 500k (23 ms at 1M); Intel UHD 630 on DX12 36 ms at 100k. The laptop's integrated Radeon was
//! slower than the UHD 630 at compute in phase 0, so integrated GPUs start at 50k until it is measured. Adaptive
//! steps and spreading a step over several frames (PLAN_V3.md phase 1) are what will raise these.

use crate::gpu::Gpu;

pub fn default_particles(gpu: &Gpu) -> u32 {
    let name = gpu.summary.name.to_lowercase();
    match gpu.adapter.get_info().device_type {
        wgpu::DeviceType::DiscreteGpu => 500_000,
        wgpu::DeviceType::IntegratedGpu => 50_000,
        wgpu::DeviceType::Cpu => 5_000,
        // reached through a translation layer (WSL's D3D12 OpenGL shows up as "Other"): be careful
        _ if name.contains("nvidia") || name.contains("geforce") || name.contains("radeon rx") => 250_000,
        _ => 50_000,
    }
}
