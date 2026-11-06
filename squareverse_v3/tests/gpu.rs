//! GPU tests. They share one device; with no usable GPU they print why and pass without checking anything
//! (set SV_ALLOW_CPU=1 to run them on a software adapter such as llvmpipe instead).

use std::sync::{Mutex, OnceLock};

use squareverse::fixed::Fixed2;
use squareverse::gpu::Gpu;
use squareverse::headless;
use squareverse::sim::{Sim, SimConfig, reference, state_hash};
use squareverse::timing::GpuTimer;

fn gpu() -> Option<&'static Mutex<Gpu>> {
    static GPU: OnceLock<Option<Mutex<Gpu>>> = OnceLock::new();
    GPU.get_or_init(|| {
        squareverse::gpu::prepare_platform();
        let allow_cpu = std::env::var_os("SV_ALLOW_CPU").is_some();
        match Gpu::headless(None, allow_cpu) {
            Ok(g) => {
                eprintln!("GPU tests on {} ({})", g.summary.name, g.summary.backend);
                Some(Mutex::new(g))
            }
            Err(e) => {
                eprintln!("GPU tests skipped: {e}");
                None
            }
        }
    })
    .as_ref()
}

fn small(particles: u32, seed: u64) -> SimConfig {
    SimConfig { particles, seed, ..Default::default() }
}

#[test]
fn same_seed_gives_the_same_universe() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap();
    let a = headless::run(&g, small(20_000, 7), 200).unwrap();
    let b = headless::run(&g, small(20_000, 7), 200).unwrap();
    let c = headless::run(&g, small(20_000, 8), 200).unwrap();
    assert_eq!(a.state_hash, b.state_hash);
    assert_ne!(a.state_hash, c.state_hash);
}

#[test]
fn energy_holds_on_orbits() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap();
    // 500 Myr: the inner orbits go round ~17 times, the outer ones not quite once
    let r = headless::run(&g, small(20_000, 1), 2_000).unwrap();
    eprintln!("energy change over 2,000 steps: {:.2e}", r.energy_rel_change);
    assert!(r.energy_rel_change.abs() < 1e-5, "{}", r.energy_rel_change);
}

#[test]
fn gpu_matches_the_cpu_reference_across_the_box_edge() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap();
    // centred on the box's corner, so the disc straddles the wrap on both axes, and every step carries between
    // the lo and hi words (a hi unit is 0.0047 pc here)
    let cfg = SimConfig { particles: 5_000, seed: 3, center_pc: (0.0, 0.0), ..Default::default() };
    let steps = 20;
    let mut sim = Sim::new(&g, cfg.clone()).unwrap();
    let start = sim.read_state(&g).unwrap();
    let mut pos = start.pos.clone();
    let mut vel: Vec<[f64; 2]> = start.vel.iter().map(|v| [v[0] as f64, v[1] as f64]).collect();

    let mut timer = GpuTimer::new(&g.device, &g.queue, false);
    let mut enc = g.device.create_command_encoder(&Default::default());
    sim.encode_steps(&mut enc, steps, &mut timer);
    g.queue.submit([enc.finish()]);
    let end = sim.read_state(&g).unwrap();
    reference::steps(&cfg, &mut pos, &mut vel, steps);

    let mut worst: f64 = 0.0;
    let mut crossed = 0;
    for ((p_gpu, p_cpu), p0) in end.pos.iter().zip(&pos).zip(&start.pos) {
        let (dx, dy) = p_gpu.delta_pc(*p_cpu, cfg.box_pc);
        worst = worst.max(dx.hypot(dy));
        // crossed the wrap: its x or y words went from near the top of the box to near the bottom or back
        let jump = |a: u64, b: u64| (a > u64::MAX / 4 * 3 && b < u64::MAX / 4) || (b > u64::MAX / 4 * 3 && a < u64::MAX / 4);
        if jump(p0.x, p_gpu.x) || jump(p0.y, p_gpu.y) {
            crossed += 1;
        }
    }
    eprintln!("GPU vs CPU after {steps} steps: worst {worst:.2e} pc, {crossed} particles crossed the box edge");
    assert!(crossed > 50, "too few particles crossed the edge to test it: {crossed}");
    // a lost carry or borrow would be off by a whole hi unit (0.0047 pc) or the box
    assert!(worst < 1e-3, "worst {worst} pc");
}

#[test]
fn hash_sees_one_changed_word() {
    let s = |x: u64| squareverse::sim::State { pos: vec![Fixed2 { x, y: 5 }], vel: vec![[1.0, 2.0]] };
    assert_ne!(state_hash(&s(1)), state_hash(&s(2)));
}
