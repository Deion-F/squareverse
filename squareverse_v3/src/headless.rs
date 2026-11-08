//! Runs without a window and reports what happened as JSON: the adapter, timings (wall clock and GPU timestamps),
//! conserved totals and a hash of the final state. This is what the helper agents and the tests drive.

use std::time::Instant;

use anyhow::Result;
use serde::Serialize;

use crate::cli::Cli;
use crate::gpu::{AdapterSummary, Gpu};
use crate::sim::{Sim, SimConfig, state_hash};
use crate::timing::GpuTimer;

const WARMUP_STEPS: u32 = 2;

#[derive(Serialize)]
pub struct Report {
    pub version: &'static str,
    pub adapter: AdapterSummary,
    pub gpu_timestamps: bool,
    pub config: SimConfig,
    /// Steps of dt (each 2^(levels - 1) sub-steps).
    pub steps: u64,
    pub sim_time_myr: f64,
    /// Wall-clock ms per step, waiting for the GPU after each one.
    pub wall_ms_per_step: f64,
    /// GPU ms per step from timestamps (the median step), if the adapter has them.
    pub gpu_ms_per_step: Option<f64>,
    /// The same per Myr of sim time: what the frame budget buys.
    pub gpu_ms_per_myr: Option<f64>,
    /// GPU ms per step by stage (medians over steps).
    pub gpu_ms_by_stage: std::collections::BTreeMap<String, f64>,
    /// Particles in each time-step bin at the end (bin b steps dt / 2^b).
    pub bin_counts: Vec<u32>,
    /// Force evaluations per particle per Myr with those bins (a fixed step of dt_min would be 1 / dt_min).
    pub force_evals_per_myr: f64,
    /// The galaxy's figures at the start and the end (galaxy scene).
    pub galaxy_start: Option<crate::sim::init::GalaxyStats>,
    pub galaxy_end: Option<crate::sim::init::GalaxyStats>,
    pub energy_initial: f64,
    pub energy_final: f64,
    pub energy_rel_change: f64,
    pub state_hash: String,
}

pub fn config_from(cli: &Cli, gpu: &Gpu) -> SimConfig {
    let mut cfg = SimConfig {
        particles: cli.particles.unwrap_or_else(|| crate::budget::default_particles(gpu)),
        seed: cli.seed,
        ..SimConfig::for_scene(cli.scene.unwrap_or(crate::sim::Scene::Galaxy))
    };
    if let Some(q) = cli.toomre_q {
        cfg.galaxy.toomre_q = q;
    }
    if let Some(dt) = cli.dt {
        cfg.dt_myr = dt;
    }
    if let Some(e) = cli.dm_softening {
        cfg.dm_softening_pc = e;
    }
    let g = &mut cfg.galaxy;
    for (v, f) in [(cli.disc_mass, &mut g.disc_mass), (cli.bulge_mass, &mut g.bulge_mass), (cli.halo_mass, &mut g.halo_mass), (cli.well_mass, &mut g.well_mass)] {
        if let Some(v) = v {
            *f = v;
        }
    }
    cfg.gas.feedback &= !cli.no_feedback;
    cfg.gas.cooling &= !cli.no_cooling;
    cfg.gas.star_formation &= !cli.no_star_formation;
    if let Some(m) = cli.gas_mass {
        cfg.galaxy.gas_mass = m;
    }
    if let Some(h) = cli.halo_share {
        cfg.galaxy.halo_share = h;
    }
    if let Some(e) = cli.softening {
        cfg.softening_pc = e;
    }
    if let Some(t) = cli.theta {
        cfg.theta = t;
    }
    if let Some(o) = cli.open_small {
        cfg.open_small = o;
    }
    cfg.walk = cli.walk.unwrap_or_else(|| crate::sim::Walk::for_gpu(gpu));
    if let Some(r) = cli.rebuild_every {
        cfg.rebuild_every = r;
    }
    if let Some(l) = cli.levels {
        cfg.levels = l;
    }
    if let Some(e) = cli.eta {
        cfg.eta = e;
    }
    if let Some(e) = cli.eta_jerk {
        cfg.eta_jerk = e;
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
    let s0 = sim.read_state(gpu)?;
    let e0 = sim.energy(&s0);
    let galaxy = sim.cfg.scene == crate::sim::Scene::Galaxy;
    let galaxy_start = galaxy.then(|| crate::sim::init::galaxy_stats(&sim.cfg, &s0, 0.0));

    // one step a submit, so the timer sees all of its passes
    let submit = |sim: &mut Sim, timer: &mut GpuTimer| -> Result<()> {
        timer.begin();
        let mut enc = gpu.device.create_command_encoder(&Default::default());
        sim.encode_steps(&mut enc, 1, timer);
        timer.resolve(&mut enc);
        gpu.queue.submit([enc.finish()]);
        timer.after_submit();
        gpu.wait()?;
        timer.collect();
        Ok(())
    };

    for _ in 0..WARMUP_STEPS {
        submit(&mut sim, &mut timer)?; // pipelines compile and caches warm here
    }
    let mut gpu_ms = Vec::new();
    let mut stages: std::collections::BTreeMap<String, Vec<f64>> = Default::default();
    let start = Instant::now();
    for _ in 0..steps {
        submit(&mut sim, &mut timer)?;
        if timer.enabled() && !timer.last.is_empty() {
            let mut total = 0.0;
            for label in timer.labels() {
                let ms = timer.ms(label).unwrap_or(0.0);
                stages.entry(label.to_string()).or_default().push(ms);
                total += ms;
            }
            gpu_ms.push(total);
        }
    }
    let wall = start.elapsed().as_secs_f64() * 1e3;
    if std::env::var_os("SV_DEBUG_PASSES").is_some() {
        for ((l, ms), u) in timer.last.iter().zip(&timer.last_units) {
            eprintln!("{l:10} {ms:8.3} ms  units {u:.4}");
        }
    }
    let state = sim.read_state(gpu)?;
    let e1 = sim.energy(&state);
    let bin_counts = sim.read_counts(gpu)?;
    gpu_ms.sort_by(f64::total_cmp);
    if let Some(path) = snapshot {
        crate::snapshot::save(gpu, &sim, path)?;
    }
    let per_step = gpu_ms.get(gpu_ms.len() / 2).copied();
    Ok(Report {
        version: env!("CARGO_PKG_VERSION"),
        adapter: gpu.summary.clone(),
        gpu_timestamps: timer.enabled(),
        steps: sim.steps,
        sim_time_myr: sim.time_myr(),
        wall_ms_per_step: if steps > 0 { wall / steps as f64 } else { 0.0 },
        gpu_ms_per_step: per_step,
        gpu_ms_per_myr: per_step.map(|ms| ms / sim.cfg.dt_myr),
        gpu_ms_by_stage: stages
            .into_iter()
            .map(|(k, mut v)| {
                v.sort_by(f64::total_cmp);
                (k, v[v.len() / 2])
            })
            .collect(),
        force_evals_per_myr: sim.evals_per_myr(&bin_counts),
        bin_counts,
        galaxy_start,
        galaxy_end: galaxy.then(|| crate::sim::init::galaxy_stats(&sim.cfg, &state, sim.time_myr())),
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
