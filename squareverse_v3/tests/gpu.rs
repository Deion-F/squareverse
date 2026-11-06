//! GPU tests. They share one device; with no usable GPU they print why and pass without checking anything
//! (set SV_ALLOW_CPU=1 to run them on a software adapter such as llvmpipe instead).

use std::sync::{Mutex, OnceLock};

use squareverse::fixed::Fixed2;
use squareverse::gpu::Gpu;
use squareverse::headless;
use squareverse::sim::init::Initial;
use squareverse::sim::{Sim, SimConfig, State, Walk, reference, state_hash};
use squareverse::timing::GpuTimer;
use squareverse::units::G;

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

fn run(g: &Gpu, sim: &mut Sim, steps: u32) {
    let mut timer = GpuTimer::new(&g.device, &g.queue, false);
    let mut left = steps;
    while left > 0 {
        let k = left.min(100);
        let mut enc = g.device.create_command_encoder(&Default::default());
        sim.encode_steps(&mut enc, k, &mut timer);
        g.queue.submit([enc.finish()]);
        g.wait().unwrap();
        left -= k;
    }
}

fn percentile(v: &mut [f64], p: f64) -> f64 {
    v.sort_by(f64::total_cmp);
    v[((v.len() - 1) as f64 * p).round() as usize]
}

#[test]
fn same_seed_gives_the_same_universe() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let a = headless::run(&g, small(20_000, 7), 200).unwrap();
    let b = headless::run(&g, small(20_000, 7), 200).unwrap();
    let c = headless::run(&g, small(20_000, 8), 200).unwrap();
    assert_eq!(a.state_hash, b.state_hash);
    assert_ne!(a.state_hash, c.state_hash);
}

#[test]
fn energy_holds_with_self_gravity() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // 250 Myr: the inner orbits go round ~8 times. The cold disc fragments into clumps; at 0.25 Myr steps their close
    // encounters cost 1e-4 - 4e-4 of the energy by 500 Myr (it varies by seed), at 0.125 Myr ~3e-6: adaptive steps
    // will handle it (PLAN_V3.md phase 1)
    let cfg = SimConfig { dt_myr: 0.125, ..small(20_000, 1) };
    let r = headless::run(&g, cfg, 2_000).unwrap();
    eprintln!("energy change over 2,000 steps with self-gravity: {:.2e}", r.energy_rel_change);
    assert!(r.energy_rel_change.abs() < 5e-5, "{}", r.energy_rel_change);
}

/// A Gaussian cluster (sigma 1 kpc) of equal masses: its field doesn't cancel the way a uniform disc's does.
fn cluster(cfg: &SimConfig, n: usize, seed: u64) -> Initial {
    let mut rng = squareverse::rng::Rng::new(seed);
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let mut init = Initial::with_capacity(n);
    for _ in 0..n {
        let (x, y) = (rng.normal() * 1_000.0, rng.normal() * 1_000.0);
        init.push(c.offset_pc(x, y, cfg.box_pc), [0.0, 0.0], 1e4, (5772.0, 1.0));
    }
    init
}

#[test]
fn tree_forces_match_direct_summation() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // measured 2026-11-06 with quadrupoles: particle walk 0.6 -> median 3.1e-3, p99 2.0e-2; 0.3 -> 3.3e-4, 2.3e-3;
    // group walk (more conservative) 0.6 -> 5.0e-4, 7.9e-3; 0.3 -> 4.3e-5, 5.6e-4
    for (walk, theta, median_max, p99_max) in [
        (Walk::Particle, 0.6, 5e-3, 3e-2),
        (Walk::Particle, 0.3, 1e-3, 5e-3),
        (Walk::Group, 0.6, 1e-3, 1.5e-2),
        (Walk::Group, 0.3, 1e-4, 1.5e-3),
    ] {
        let cfg = SimConfig { central_mass: 0.0, theta, walk, ..Default::default() };
        let sim = Sim::from_initial(&g, cfg.clone(), &cluster(&cfg, 20_000, 5)).unwrap();
        let s = sim.read_state(&g).unwrap();
        let mut errs = Vec::new();
        for i in (0..s.pos.len()).step_by(67) {
            let tree = [s.acc[i][0] as f64, s.acc[i][1] as f64];
            let direct = reference::direct_accel(&cfg, &s.pos, &s.mass, i);
            errs.push((tree[0] - direct[0]).hypot(tree[1] - direct[1]) / direct[0].hypot(direct[1]));
        }
        let median = percentile(&mut errs, 0.5);
        let p99 = percentile(&mut errs, 0.99);
        eprintln!("{walk:?} walk, theta {theta}: force error median {median:.2e}, 99th percentile {p99:.2e} ({} particles)", errs.len());
        assert!(median < median_max && p99 < p99_max, "{walk:?} theta {theta}: median {median}, p99 {p99}");
    }
}

#[test]
fn two_bodies_keep_their_orbit() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let (m, d) = (1e6, 100.0); // two 1e6 Msun bodies 100 pc apart
    let v = (G * 2.0 * m / d).sqrt() / 2.0; // each moves at half the relative circular speed
    let period = std::f64::consts::TAU * d / (2.0 * v);
    let cfg = SimConfig { central_mass: 0.0, softening_pc: 0.01, dt_myr: period / 2_000.0, ..Default::default() };
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let mut init = Initial::with_capacity(2);
    init.push(c.offset_pc(-d / 2.0, 0.0, cfg.box_pc), [0.0, -v], m, (5772.0, 1.0));
    init.push(c.offset_pc(d / 2.0, 0.0, cfg.box_pc), [0.0, v], m, (5772.0, 1.0));
    let mut sim = Sim::from_initial(&g, cfg.clone(), &init).unwrap();
    let e0 = sim.energy(&sim.read_state(&g).unwrap());
    run(&g, &mut sim, 20_000); // ten orbits
    let s = sim.read_state(&g).unwrap();
    let (dx, dy) = s.pos[1].delta_pc(s.pos[0], cfg.box_pc);
    let sep = dx.hypot(dy);
    let de = (sim.energy(&s) - e0) / e0.abs();
    eprintln!("two bodies after 10 orbits: separation {sep:.4} pc (from {d}), energy change {de:.2e}");
    assert!((sep / d - 1.0).abs() < 0.01, "{sep}");
    assert!(de.abs() < 1e-4, "{de}");
}

#[test]
fn momentum_holds_without_the_central_mass() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // a self-gravitating disc with nothing in the middle: it falls in on itself, but its total momentum should stay
    let cfg = SimConfig { particles: 20_000, seed: 2, central_mass: 0.0, ..Default::default() };
    let mut sim = Sim::new(&g, cfg).unwrap();
    let s0 = sim.read_state(&g).unwrap();
    let scale: f64 = s0.vel.iter().zip(&s0.mass).map(|(v, &m)| m as f64 * (v[0] as f64).hypot(v[1] as f64)).sum();
    let p0 = Sim::momentum(&s0);
    run(&g, &mut sim, 400);
    let p1 = Sim::momentum(&sim.read_state(&g).unwrap());
    let drift = (p1[0] - p0[0]).hypot(p1[1] - p0[1]) / scale;
    eprintln!("momentum change over 400 steps: {drift:.2e} of the total |p|");
    assert!(drift < 1e-3, "{drift}");
}

#[test]
fn gpu_matches_the_cpu_reference_across_the_box_edge() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // centred on the box's corner, so the disc straddles the wrap on both axes, and every step carries between
    // the lo and hi words (a hi unit is 0.0047 pc here). The disc is all but massless, so the central mass alone
    // moves it, as in the CPU reference.
    let cfg = SimConfig { particles: 5_000, seed: 3, center_pc: (0.0, 0.0), disc_mass: 1e-3, ..Default::default() };
    let steps = 20;
    let mut sim = Sim::new(&g, cfg.clone()).unwrap();
    let start = sim.read_state(&g).unwrap();
    let mut pos = start.pos.clone();
    let mut vel: Vec<[f64; 2]> = start.vel.iter().map(|v| [v[0] as f64, v[1] as f64]).collect();
    run(&g, &mut sim, steps);
    let end = sim.read_state(&g).unwrap();
    reference::steps(&cfg, &mut pos, &mut vel, steps);

    let mut worst: f64 = 0.0;
    let mut crossed = 0;
    for ((p_gpu, p_cpu), p0) in end.pos.iter().zip(&pos).zip(&start.pos) {
        let (dx, dy) = p_gpu.delta_pc(*p_cpu, cfg.box_pc);
        worst = worst.max(dx.hypot(dy));
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
    let s = |x: u64| State { pos: vec![Fixed2 { x, y: 5 }], vel: vec![[1.0, 2.0]], mass: vec![1.0], acc: vec![[0.0; 4]] };
    assert_ne!(state_hash(&s(1)), state_hash(&s(2)));
}

/// Diagnostic, run on demand: `cargo test --release --test gpu -- --ignored --nocapture force_accuracy_table`.
/// Force error against direct summation for a range of opening angles (Gaussian cluster, 20k particles).
#[test]
#[ignore]
fn force_accuracy_table() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    for theta in [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0] {
        let cfg = SimConfig { central_mass: 0.0, theta, ..Default::default() };
        let sim = Sim::from_initial(&g, cfg.clone(), &cluster(&cfg, 20_000, 5)).unwrap();
        let s = sim.read_state(&g).unwrap();
        let mut errs = Vec::new();
        for i in (0..s.pos.len()).step_by(67) {
            let direct = reference::direct_accel(&cfg, &s.pos, &s.mass, i);
            let (ex, ey) = (s.acc[i][0] as f64 - direct[0], s.acc[i][1] as f64 - direct[1]);
            errs.push(ex.hypot(ey) / direct[0].hypot(direct[1]));
        }
        let (m, p) = (percentile(&mut errs, 0.5), percentile(&mut errs, 0.99));
        eprintln!("theta {theta:.1}: median {m:.2e}, 99th percentile {p:.2e}");
    }
}
