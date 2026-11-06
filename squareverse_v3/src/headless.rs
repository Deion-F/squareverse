//! Runs without a window and reports what happened as JSON: the adapter, timings (wall clock and GPU timestamps),
//! conserved totals and a hash of the final state. This is what the helper agents and the tests drive.

use std::time::Instant;

use anyhow::Result;
use serde::Serialize;

use crate::cli::Cli;
use crate::gpu::{AdapterSummary, Gpu};
use crate::sim::{Sim, SimConfig, state_hash};
use crate::timing::GpuTimer;

const WARMUP_STEPS: u32 = 10;
const BATCH: u32 = 50;

#[derive(Serialize)]
pub struct Report {
    pub version: &'static str,
    pub adapter: AdapterSummary,
    pub gpu_timestamps: bool,
    pub config: SimConfig,
    pub steps: u64,
    pub sim_time_myr: f64,
    /// Wall-clock ms per step, waiting for the GPU after every batch of `BATCH` steps.
    pub wall_ms_per_step: f64,
    /// GPU ms per step from timestamps (the median batch), if the adapter has them.
    pub gpu_ms_per_step: Option<f64>,
    pub energy_initial: f64,
    pub energy_final: f64,
    pub energy_rel_change: f64,
    pub state_hash: String,
}

pub fn config_from(cli: &Cli, gpu: &Gpu) -> SimConfig {
    let mut cfg = SimConfig {
        particles: cli.particles.unwrap_or_else(|| crate::budget::default_particles(gpu)),
        seed: cli.seed,
        ..Default::default()
    };
    if let Some(dt) = cli.dt {
        cfg.dt_myr = dt;
    }
    cfg
}

/// Runs `steps` steps (plus a warm-up the report leaves out of the timings, not out of the physics).
pub fn run(gpu: &Gpu, cfg: SimConfig, steps: u32) -> Result<Report> {
    run_with(gpu, cfg, steps, None)
}

/// As `run`, and if `snapshot` is given, draws the final state into that PNG file.
pub fn run_with(gpu: &Gpu, cfg: SimConfig, steps: u32, snapshot: Option<&std::path::Path>) -> Result<Report> {
    let mut sim = Sim::new(gpu, cfg)?;
    let mut timer = GpuTimer::new(&gpu.device, &gpu.queue, gpu.timestamps);
    let e0 = sim.energy(&sim.read_state(gpu)?);

    let submit = |sim: &mut Sim, timer: &mut GpuTimer, k: u32| -> Result<()> {
        timer.begin();
        let mut enc = gpu.device.create_command_encoder(&Default::default());
        sim.encode_steps(&mut enc, k, timer);
        timer.resolve(&mut enc);
        gpu.queue.submit([enc.finish()]);
        timer.after_submit();
        gpu.wait()?;
        timer.collect();
        Ok(())
    };

    submit(&mut sim, &mut timer, WARMUP_STEPS)?; // pipelines compile and caches warm here
    let mut gpu_ms = Vec::new();
    let start = Instant::now();
    let mut left = steps;
    while left > 0 {
        let k = left.min(BATCH);
        submit(&mut sim, &mut timer, k)?;
        if let Some(ms) = timer.ms("step") {
            gpu_ms.push(ms / k as f64);
        }
        left -= k;
    }
    let wall = start.elapsed().as_secs_f64() * 1e3;
    let state = sim.read_state(gpu)?;
    let e1 = sim.energy(&state);
    gpu_ms.sort_by(f64::total_cmp);
    if let Some(path) = snapshot {
        crate::snapshot::save(gpu, &sim, path)?;
    }
    Ok(Report {
        version: env!("CARGO_PKG_VERSION"),
        adapter: gpu.summary.clone(),
        gpu_timestamps: timer.enabled(),
        steps: sim.steps,
        sim_time_myr: sim.time_myr,
        wall_ms_per_step: if steps > 0 { wall / steps as f64 } else { 0.0 },
        gpu_ms_per_step: gpu_ms.get(gpu_ms.len() / 2).copied(),
        energy_initial: e0,
        energy_final: e1,
        energy_rel_change: (e1 - e0) / e0.abs(),
        state_hash: format!("{:016x}", state_hash(&state)),
        config: sim.cfg,
    })
}

pub fn main(cli: &Cli) -> Result<()> {
    let gpu = Gpu::headless(cli.adapter.as_deref(), cli.allow_cpu)?;
    let cfg = config_from(cli, &gpu);
    let report = run_with(&gpu, cfg, cli.steps, cli.snapshot.as_deref())?;
    let json = serde_json::to_string_pretty(&report)?;
    match &cli.report {
        Some(path) => std::fs::write(path, json + "\n")?,
        None => println!("{json}"),
    }
    Ok(())
}
