//! How many particles a machine gets by default. Targets (user, 2026-11-06): 60 fps on the desktop (RTX 2070
//! Super), and on the laptop (Ryzen 5 5650U, integrated Radeon) 60 fps if possible, never below a stable 30.
//!
//! Phase 1 (self-gravity, 2026-11-06, per-particle walk, theta 0.6, a full step a frame): RTX 2070 Super on Vulkan
//! 12.2 ms a step at 500k (23 ms at 1M); Intel UHD 630 on DX12 36 ms at 100k. The laptop's integrated Radeon on
//! Vulkan: 20.3 ms a step headless at 100k; in the window 50k holds 60 fps, 75k gives 50.8, 100k 39.6, so integrated
//! GPUs stay at 50k (measured 2026-11-06, PLAN_V3.md laptop results, phase 1).
//!
//! Since 2026-11-07 the window's frame budget (`Sim::advance`) holds the frame rate at any count, so the sim slows
//! instead; these defaults are now about sim speed. RTX 2070 Super, 60 fps: 500k at 15 Myr/s, 1M at 7.4, 4M at 1.8.
//! The integrated default waits for the laptop's phase 1b check (PLAN_V3.md).

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
