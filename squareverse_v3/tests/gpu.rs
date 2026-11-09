//! GPU tests. They share one device; with no usable GPU they print why and pass without checking anything
//! (set SV_ALLOW_CPU=1 to run them on a software adapter such as llvmpipe instead).

use std::sync::{Mutex, OnceLock};

use squareverse::fixed::Fixed2;
use squareverse::gpu::Gpu;
use squareverse::headless;
use squareverse::sim::init::Initial;
use squareverse::sim::{Limit, Sim, SimConfig, State, Walk, reference, state_hash};
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

/// The phase-1 test disc (stars round a fixed central mass).
fn small(particles: u32, seed: u64) -> SimConfig {
    SimConfig { particles, seed, ..SimConfig::test_disc() }
}

fn run(g: &Gpu, sim: &mut Sim, steps: u32) {
    let mut timer = GpuTimer::new(&g.device, &g.queue, false);
    let mut left = steps;
    while left > 0 {
        let k = left.min(5);
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
    let a = headless::run(&g, small(20_000, 7), 20).unwrap();
    let b = headless::run(&g, small(20_000, 7), 20).unwrap();
    let c = headless::run(&g, small(20_000, 8), 20).unwrap();
    assert_eq!(a.state_hash, b.state_hash);
    assert_ne!(a.state_hash, c.state_hash);
}

#[test]
fn energy_holds_with_self_gravity() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // 250 Myr with block steps (2 Myr down to 0.125): the inner orbits go round ~8 times and the cold disc fragments
    // into clumps, whose close encounters cost energy. Measured 2026-11-07 over 250 Myr, seeds 1 / 2 / 3: block
    // steps (eta 0.025, eta_jerk 0.05; 2.55 force evaluations per particle per Myr) -1.3e-4 / -6.4e-5 / -4.5e-5;
    // the old fixed 0.25 Myr step (4 a Myr) 9e-6 / -3.6e-4 / 6.7e-5; fixed 0.125 (8 a Myr) ~1e-5
    let r = headless::run(&g, small(20_000, 1), 125).unwrap();
    eprintln!(
        "energy change over 250 Myr with self-gravity, block steps: {:.2e} (bins {:?}, {:.2} force evaluations per particle per Myr)",
        r.energy_rel_change, r.bin_counts, r.force_evals_per_myr
    );
    assert!(r.energy_rel_change.abs() < 3e-4, "{}", r.energy_rel_change);
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
        let cfg = SimConfig { central_mass: 0.0, theta, walk, ..SimConfig::test_disc() };
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
    let cfg = SimConfig { central_mass: 0.0, softening_pc: 0.01, dt_myr: period / 2_000.0, levels: 1, ..SimConfig::test_disc() };
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
    let cfg = SimConfig { particles: 20_000, seed: 2, central_mass: 0.0, ..SimConfig::test_disc() };
    let mut sim = Sim::new(&g, cfg).unwrap();
    let s0 = sim.read_state(&g).unwrap();
    let scale: f64 = s0.vel.iter().zip(&s0.mass).map(|(v, &m)| m as f64 * (v[0] as f64).hypot(v[1] as f64)).sum();
    let p0 = Sim::momentum(&s0);
    run(&g, &mut sim, 50);
    let p1 = Sim::momentum(&sim.read_state(&g).unwrap());
    let drift = (p1[0] - p0[0]).hypot(p1[1] - p0[1]) / scale;
    eprintln!("momentum change over 100 Myr: {drift:.2e} of the total |p|");
    assert!(drift < 1e-3, "{drift}");
}

#[test]
fn gpu_matches_the_cpu_reference_across_the_box_edge() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // centred on the box's corner, so the disc straddles the wrap on both axes, and every step carries between
    // the lo and hi words (a hi unit is 0.0047 pc here). The disc is all but massless, so the central mass alone
    // moves it, as in the CPU reference.
    let cfg = SimConfig {
        particles: 5_000,
        seed: 3,
        center_pc: (0.0, 0.0),
        disc_mass: 1e-3,
        dt_myr: 0.25,
        levels: 1,
        ..SimConfig::test_disc()
    };
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
fn block_steps_follow_a_fine_fixed_step() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // the central mass alone (the disc all but massless): block steps of 2 Myr down to 0.125 against the CPU
    // reference stepping everyone at 0.125 Myr, over 40 Myr (the inner edge goes round more than once)
    let cfg = SimConfig { particles: 5_000, seed: 4, disc_mass: 1e-3, ..SimConfig::test_disc() };
    let mut sim = Sim::new(&g, cfg.clone()).unwrap();
    let start = sim.read_state(&g).unwrap();
    let mut pos = start.pos.clone();
    let mut vel: Vec<[f64; 2]> = start.vel.iter().map(|v| [v[0] as f64, v[1] as f64]).collect();
    let counts = sim.read_counts(&g).unwrap();
    run(&g, &mut sim, 20);
    let end = sim.read_state(&g).unwrap();
    let fine = SimConfig { dt_myr: cfg.dt_min(), levels: 1, ..cfg.clone() };
    reference::steps(&fine, &mut pos, &mut vel, 20 * sim.sub_steps());
    let mut errs: Vec<f64> = end
        .pos
        .iter()
        .zip(&pos)
        .map(|(a, b)| {
            let (dx, dy) = a.delta_pc(*b, cfg.box_pc);
            dx.hypot(dy)
        })
        .collect();
    let (median, worst) = (percentile(&mut errs, 0.5), percentile(&mut errs, 1.0));
    eprintln!("block steps vs a fixed 0.125 Myr step after 40 Myr: median {median:.2e} pc, worst {worst:.2e} pc (bins at start {counts:?})");
    assert!(counts.iter().filter(|&&c| c > 0).count() >= 3, "the disc should spread over several bins: {counts:?}");
    assert_eq!(counts.iter().map(|&c| c as u64).sum::<u64>(), 5_000);
    assert!(worst < 5.0 && median < 0.5, "median {median}, worst {worst}");
}

#[test]
fn frames_falling_anywhere_change_nothing() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // the same 3 steps run whole, and as the window would with a tiny budget: one item (or one force slice) a frame
    let cfg = SimConfig { rebuild_every: 3, ..small(20_000, 9) };
    let mut whole = Sim::new(&g, cfg.clone()).unwrap();
    run(&g, &mut whole, 3);
    let mut sliced = Sim::new(&g, cfg).unwrap();
    let mut timer = GpuTimer::new(&g.device, &g.queue, false);
    let mut frames = 0;
    while sliced.steps < 3 {
        let mut enc = g.device.create_command_encoder(&Default::default());
        sliced.advance(&mut enc, &mut timer, Limit { budget_ms: 1e-9, new_sub_steps: 1 });
        g.queue.submit([enc.finish()]);
        sliced.after_submit();
        g.wait().unwrap();
        sliced.collect(None);
        frames += 1;
    }
    let (a, b) = (whole.read_state(&g).unwrap(), sliced.read_state(&g).unwrap());
    eprintln!("3 steps whole and over {frames} frames");
    assert!(frames > 3 * 16 * 4, "{frames}");
    assert_eq!(state_hash(&a), state_hash(&b));
}

#[test]
fn hash_sees_one_changed_word() {
    let s = |x: u64| State {
        pos: vec![Fixed2 { x, y: 5 }],
        vel: vec![[1.0, 2.0]],
        mass: vec![1.0],
        acc: vec![[0.0; 4]],
        kind: vec![0],
        star: vec![[5772.0, 1.0]],
        about: vec![[0.0; 4]],
        gas: vec![[0.0; 4]],
        chem: vec![[0.0; 4]],
    };
    assert_ne!(state_hash(&s(1)), state_hash(&s(2)));
}

/// Diagnostic, run on demand: `cargo test --release --test gpu -- --ignored --nocapture clump_force_table`.
/// Self-gravity force error against direct summation in the disc after 100 Myr (clumps formed), for the small-node
/// rule (`open_small`), with the force pass's GPU time.
#[test]
#[ignore]
fn clump_force_table() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    for open_small in [0.0, 0.25, 0.5, 1.0] {
        let cfg = SimConfig { open_small, ..small(20_000, 1) };
        let mut sim = Sim::new(&g, cfg.clone()).unwrap();
        run(&g, &mut sim, 50);
        let s = sim.read_state(&g).unwrap();
        let mut errs = Vec::new();
        let mut errs_dense = Vec::new();
        for i in 0..s.pos.len() {
            let tree = [s.acc[i][0] as f64, s.acc[i][1] as f64];
            let c = reference::central_accel(&cfg, s.pos[i]);
            let selfg = [tree[0] - c[0], tree[1] - c[1]];
            if i % 37 != 0 && selfg[0].hypot(selfg[1]) < 0.5 {
                continue;
            }
            let direct = reference::direct_accel(&cfg, &s.pos, &s.mass, i);
            let e = (selfg[0] - direct[0]).hypot(selfg[1] - direct[1]) / direct[0].hypot(direct[1]);
            if i % 37 == 0 {
                errs.push(e);
            }
            if direct[0].hypot(direct[1]) >= 0.5 {
                errs_dense.push(e);
            }
        }
        let (m, p) = (percentile(&mut errs, 0.5), percentile(&mut errs, 0.99));
        let (md, pd) = (percentile(&mut errs_dense, 0.5), percentile(&mut errs_dense, 0.99));
        eprintln!(
            "open_small {open_small}: all median {m:.2e} p99 {p:.2e} ({}); strong self-gravity (clumps) median {md:.2e} p99 {pd:.2e} ({})",
            errs.len(),
            errs_dense.len()
        );
    }
}

/// Diagnostic, run on demand: `cargo test --release --test gpu -- --ignored --nocapture force_accuracy_table`.
/// Force error against direct summation for a range of opening angles (Gaussian cluster, 20k particles).
#[test]
#[ignore]
fn force_accuracy_table() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    for theta in [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0] {
        let cfg = SimConfig { central_mass: 0.0, theta, ..SimConfig::test_disc() };
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

/// Half-mass radius (pc) of the particles of one part, about the galaxy's centre.
fn half_mass_radius(cfg: &SimConfig, s: &State, parts: &[u8], part: u8) -> f64 {
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let mut rs: Vec<(f64, f64)> = (0..s.pos.len())
        .filter(|&i| parts[i] == part)
        .map(|i| {
            let (dx, dy) = s.pos[i].delta_pc(c, cfg.box_pc);
            (dx.hypot(dy), s.mass[i] as f64)
        })
        .collect();
    rs.sort_by(|a, b| a.0.total_cmp(&b.0));
    let total: f64 = rs.iter().map(|r| r.1).sum();
    let mut acc = 0.0;
    for (r, m) in rs {
        acc += m;
        if acc >= 0.5 * total {
            return r;
        }
    }
    0.0
}

/// Diagnostic, run on demand: `cargo test --release --test gpu -- --ignored --nocapture galaxy_diagnostics`.
#[test]
#[ignore]
fn galaxy_diagnostics() {
    use squareverse::sim::init;
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let env = |k: &str, d: f64| std::env::var(k).ok().and_then(|v| v.parse().ok()).unwrap_or(d);
    let mut cfg = SimConfig { particles: env("SV_N", 50_000.0) as u32, seed: 1, ..Default::default() };
    cfg.galaxy.toomre_q = env("SV_Q", cfg.galaxy.toomre_q);
    cfg.softening_pc = env("SV_EPS", cfg.softening_pc);
    cfg.well_softening_pc = env("SV_EPS_WELL", cfg.well_softening_pc);
    cfg.levels = env("SV_LEVELS", cfg.levels as f64) as u32;
    cfg.dt_myr = env("SV_DT", cfg.dt_myr);
    cfg.galaxy.bulge_scale_pc = env("SV_BULGE_A", cfg.galaxy.bulge_scale_pc);
    let span: f64 = env("SV_STEPS", 50.0);
    eprintln!("softening {} well {} levels {} dt {} bulge a {}", cfg.softening_pc, cfg.well_softening_pc, cfg.levels, cfg.dt_myr, cfg.galaxy.bulge_scale_pc);
    let (_, parts) = init::galaxy(&cfg);
    let mut sim = Sim::new(&g, cfg.clone()).unwrap();
    let s = sim.read_state(&g).unwrap();
    let curve = init::radial_pull(&cfg, &s);
    for r in [500.0, 1000.0, 2000.0, 4000.0, 6000.0, 8000.0, 10000.0, 13000.0, 20000.0, 30000.0] {
        let gr = curve.iter().min_by(|a, b| (a.0 - r).abs().total_cmp(&(b.0 - r).abs())).unwrap();
        eprintln!("R {:6.0} pc: v_c {:6.1} pc/Myr", gr.0, (gr.0 * gr.1).max(0.0).sqrt());
    }
    let mut t = 0;
    for steps in [0u32, 5, (span as u32 / 2).saturating_sub(5), span as u32 - span as u32 / 2] {
        run(&g, &mut sim, steps);
        t += steps;
        let s = sim.read_state(&g).unwrap();
        let k: f64 = s.vel.iter().zip(&s.mass).map(|(v, &m)| 0.5 * m as f64 * ((v[0] as f64).powi(2) + (v[1] as f64).powi(2))).sum();
        let w: f64 = s.acc.iter().zip(&s.mass).map(|(a, &m)| m as f64 * (0.5 * a[2] as f64 + a[3] as f64)).sum();
        let mut kinds = [0u32; 8];
        s.kind.iter().for_each(|&k| kinds[k as usize] += 1);
        eprintln!(
            "t {:5} Myr: K {k:.3e} W {w:.3e} 2K/|W| {:.3} E {:.4e}; half-mass R disc {:.0} bulge {:.0} halo {:.0}; kinds {:?}; bins {:?}",
            t as f64 * cfg.dt_myr,
            2.0 * k / w.abs(),
            k + w,
            half_mass_radius(&cfg, &s, &parts, init::PART_DISC),
            half_mass_radius(&cfg, &s, &parts, init::PART_BULGE),
            half_mass_radius(&cfg, &s, &parts, init::PART_HALO),
            kinds,
            sim.read_counts(&g).unwrap()
        );
    }
}

#[test]
fn galaxy_has_a_flat_rotation_curve_and_holds_together() {
    use squareverse::sim::init;
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let cfg = SimConfig { particles: 30_000, seed: 2, ..Default::default() };
    let mut sim = Sim::new(&g, cfg.clone()).unwrap();
    let s0 = sim.read_state(&g).unwrap();
    let a = init::galaxy_stats(&cfg, &s0, 0.0);
    // flat from 4 to 16 kpc: within 10% of the mean (measured 2026-11-08: 221 - 229 pc/Myr at 100k)
    let vs: Vec<f64> = a.rotation_curve.iter().filter(|(r, _)| (4_000.0..=16_000.0).contains(r)).map(|p| p.1).collect();
    let mean = vs.iter().sum::<f64>() / vs.len() as f64;
    eprintln!("rotation curve {:?}", a.rotation_curve);
    assert!(vs.iter().all(|v| (v / mean - 1.0).abs() < 0.1), "{vs:?}");
    // 100 Myr: every part keeps its size (measured 2026-11-08 over 2 Gyr at 100k: disc +2%)
    let e0 = sim.energy(&s0);
    run(&g, &mut sim, 50);
    let s1 = sim.read_state(&g).unwrap();
    let b = init::galaxy_stats(&cfg, &s1, sim.time_myr());
    let de = (sim.energy(&s1) - e0) / e0.abs();
    eprintln!("half-mass radii {:?} -> {:?}, energy change {de:.2e}, kinds {:?}", a.half_mass_pc, b.half_mass_pc, b.kinds);
    for k in 0..3 {
        assert!((b.half_mass_pc[k] / a.half_mass_pc[k] - 1.0).abs() < 0.12, "part {k}: {:?} -> {:?}", a.half_mass_pc, b.half_mass_pc);
    }
    assert!(de.abs() < 5e-3, "{de}");
}

#[test]
fn stars_live_die_and_leave_remnants() {
    use squareverse::sim::init::{Initial, Kind};
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let cfg = SimConfig { central_mass: 0.0, ..SimConfig::test_disc() };
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let mut init = Initial::with_capacity(4);
    // (star mass, age Myr): a 20 Msun star lives ~5.6 Myr, a 7 Msun one ~77, the Sun ~10 Gyr, 40 Msun ~3
    let stars = [(20.0f64, 10.0f64), (7.0, 1_000.0), (1.0, 4_600.0), (40.0, 50.0)];
    for (k, &(m, age)) in stars.iter().enumerate() {
        let p = c.offset_pc(1_000.0 * k as f64, 0.0, cfg.box_pc);
        init.push_kind(p, [0.0, 0.0], m, (5000.0, 1.0), Kind::Star, [-age as f32, m as f32, m as f32, 0.0]);
    }
    let sim = Sim::from_initial(&g, cfg, &init).unwrap();
    let s = sim.read_state(&g).unwrap();
    eprintln!("kinds {:?}, masses {:?}, (T, L) {:?}", s.kind, s.mass, s.star);
    // a single star's black hole is a (stellar-mass) super well
    assert_eq!(s.kind, vec![Kind::NeutronStar as u32, Kind::WhiteDwarf as u32, Kind::Star as u32, Kind::Well as u32]);
    // single stars: the remnant's mass (white dwarf 0.109 m + 0.394, neutron star 1.4, black hole m / 4)
    assert!((s.mass[0] - 1.4).abs() < 1e-4 && (s.mass[1] - (0.109 * 7.0 + 0.394)).abs() < 1e-4 && s.mass[2] == 1.0);
    assert!((s.mass[3] - 10.0).abs() < 1e-4);
    assert!(s.star[2][0] > 5_000.0 && s.star[2][0] < 6_500.0, "the Sun's temperature {}", s.star[2][0]);
    assert!(s.star[0][1] == 0.0 && s.star[1][1] > 0.0 && s.star[1][1] < 0.03);
}

#[test]
fn a_well_swallows_what_comes_close_and_keeps_the_momentum() {
    use squareverse::sim::init::{Initial, Kind};
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let cfg = SimConfig { central_mass: 0.0, accretion_pc: 2.0, ..SimConfig::test_disc() };
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let mut init = Initial::with_capacity(3);
    init.push_well(c, [1.0, 0.0], 1e6);
    // one star 1 pc away moving slowly (bound): swallowed; one 1 pc away much faster than escape: not; one far away
    let sun = |init: &mut Initial, dx: f64, v: [f64; 2]| {
        init.push_kind(c.offset_pc(dx, 0.0, cfg.box_pc), v, 1.0, (5772.0, 1.0), Kind::Star, [0.0, 1.0, 1.0, 0.0]);
    };
    sun(&mut init, 1.0, [0.0, 20.0]);
    sun(&mut init, -1.0, [0.0, 3_000.0]);
    sun(&mut init, 500.0, [0.0, 0.0]);
    let p0 = Sim::momentum(&{
        let mut sim = Sim::from_initial(&g, cfg.clone(), &init).unwrap();
        let s = sim.read_state(&g).unwrap();
        run(&g, &mut sim, 0);
        s
    });
    let mut sim = Sim::from_initial(&g, cfg, &init).unwrap();
    // the first step's evolution pass does the swallowing
    let mut timer = GpuTimer::new(&g.device, &g.queue, false);
    let mut enc = g.device.create_command_encoder(&Default::default());
    sim.advance(&mut enc, &mut timer, Limit { budget_ms: 1e-9, new_sub_steps: 1 });
    g.queue.submit([enc.finish()]);
    g.wait().unwrap();
    let s = sim.read_state(&g).unwrap();
    let p1 = Sim::momentum(&s);
    eprintln!("kinds {:?}, masses {:?}, momentum {p0:?} -> {p1:?}", s.kind, s.mass);
    assert_eq!(s.kind, vec![Kind::Well as u32, Kind::Gone as u32, Kind::Star as u32, Kind::Star as u32]);
    assert!((s.mass[0] - 1e6 - 1.0).abs() < 0.01 && s.mass[1] == 0.0);
    assert!((p1[0] - p0[0]).abs() < 1e-2 * p0[0].abs() && (p1[1] - p0[1]).abs() < 1e-3 * 3_000.0, "{p0:?} {p1:?}");
}

/// A Gaussian blob (sigma 300 pc) of gas at `t_k`, 1e6 Msun in all, no central mass.
fn gas_blob(cfg: &SimConfig, n: usize, t_k: f64) -> squareverse::sim::init::Initial {
    gas_blob_of(cfg, n, t_k, 1e6)
}

fn gas_blob_of(cfg: &SimConfig, n: usize, t_k: f64, total: f64) -> squareverse::sim::init::Initial {
    use squareverse::sim::init::{Initial, SOLAR};
    let mut rng = squareverse::rng::Rng::new(11);
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let mut init = Initial::with_capacity(n);
    init.single_stars = false;
    for _ in 0..n {
        let (x, y) = (rng.normal() * 300.0, rng.normal() * 300.0);
        init.push_gas(c.offset_pc(x, y, cfg.box_pc), [0.0, 0.0], total / n as f64, t_k, 60.0, SOLAR);
    }
    init
}

#[test]
fn hot_gas_expands_and_keeps_its_energy() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let lv: u32 = std::env::var("SV_LEVELS").ok().and_then(|v| v.parse().ok()).unwrap_or(8);
    let dt: f64 = std::env::var("SV_DT").ok().and_then(|v| v.parse().ok()).unwrap_or(2.0);
    let mut cfg = SimConfig { central_mass: 0.0, levels: lv, dt_myr: dt, ..SimConfig::test_disc() };
    cfg.gas.cooling = false;
    cfg.gas.star_formation = false;
    cfg.gas.feedback = false;
    let mut sim = Sim::from_initial(&g, cfg.clone(), &gas_blob(&cfg, 4_000, 1e5)).unwrap();
    let s0 = sim.read_state(&g).unwrap();
    let (e0, p0) = (sim.energy(&s0), Sim::momentum(&s0));
    let r = |s: &State| -> f64 {
        let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
        s.pos.iter().map(|p| {
            let (dx, dy) = p.delta_pc(c, cfg.box_pc);
            dx.hypot(dy)
        }).sum::<f64>() / s.pos.len() as f64
    };
    run(&g, &mut sim, 5);
    let s1 = sim.read_state(&g).unwrap();
    let (e1, p1) = (sim.energy(&s1), Sim::momentum(&s1));
    let de = (e1 - e0) / e0.abs();
    let scale: f64 = s1.vel.iter().zip(&s1.mass).map(|(v, &m)| m as f64 * (v[0] as f64).hypot(v[1] as f64)).sum();
    let dp = (p1[0] - p0[0]).hypot(p1[1] - p0[1]) / scale.max(1e-9);
    eprintln!("gas blob over 10 Myr: mean radius {:.0} -> {:.0} pc, energy change {de:.2e}, momentum {dp:.2e} of the total |p|", r(&s0), r(&s1));
    // the pressure pushes it apart
    assert!(r(&s1) > 1.05 * r(&s0));
    assert!(de.abs() < 0.02, "{de}");
    assert!(dp < 1e-3, "{dp}");
}

#[test]
fn hot_gas_cools() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // 8 levels (down to 1/64 Myr): 1e6 K gas wants steps of ~0.03 Myr
    let mut cfg = SimConfig { central_mass: 0.0, levels: 8, ..SimConfig::test_disc() };
    cfg.gas.star_formation = false;
    cfg.gas.feedback = false;
    // 1e6 K gas at ~1 Msun/pc^2 (n ~ 0.2 cm^-3): cooling time ~1 Myr
    let mut sim = Sim::from_initial(&g, cfg.clone(), &gas_blob(&cfg, 4_000, 1e6)).unwrap();
    run(&g, &mut sim, 10);
    let s = sim.read_state(&g).unwrap();
    let mut t: Vec<f64> = s.star.iter().map(|x| x[0] as f64).collect();
    let median = percentile(&mut t, 0.5);
    eprintln!("gas blob at 1e6 K after 20 Myr of cooling: median {median:.0} K, coolest {:.0} K", t[0]);
    assert!(median < 2e4, "{median}");
    assert!(t[0] >= 99.0, "below the floor: {}", t[0]);
}

#[test]
fn gas_forms_stars_that_grow_richer_in_metals() {
    use squareverse::sim::init;
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let cfg = SimConfig { particles: 30_000, seed: 3, ..Default::default() };
    let mut sim = Sim::new(&g, cfg.clone()).unwrap();
    let a = init::galaxy_stats(&cfg, &sim.read_state(&g).unwrap(), 0.0);
    run(&g, &mut sim, 75);
    let s = sim.read_state(&g).unwrap();
    let b = init::galaxy_stats(&cfg, &s, sim.time_myr());
    // stars born in the first and second half of the run: the later ones richer in metals
    let z_of = |i: usize| (s.chem[i][1] + s.chem[i][2] + s.chem[i][3]) as f64 / init::SOLAR_Z;
    let born: Vec<usize> = (0..s.pos.len()).filter(|&i| s.about[i][3].to_bits() == init::PART_NEW as u32).collect();
    let half = sim.time_myr() / 2.0;
    let mean = |early: bool| {
        let v: Vec<f64> = born.iter().filter(|&&i| ((s.about[i][0] as f64) < half) == early).map(|&i| z_of(i)).collect();
        v.iter().sum::<f64>() / v.len().max(1) as f64
    };
    let (z_early, z_late) = (mean(true), mean(false));
    eprintln!(
        "150 Myr: {} stars born ({:.2e} Msun), gas metallicity {:.3} -> {:.3}, new stars {z_early:.3} (first half) -> {z_late:.3} (second), \
         gas half-mass radius {:.0} -> {:.0} pc, temperatures {:?} K",
        b.new_stars, b.new_star_mass, a.gas_metallicity, b.gas_metallicity, a.gas_half_mass_pc, b.gas_half_mass_pc, b.gas_temperature_k
    );
    assert!(b.new_stars > 20, "{}", b.new_stars);
    assert!(b.gas_metallicity > a.gas_metallicity * 1.02);
    assert!(z_late > z_early, "{z_early} {z_late}");
    // no blow-out, no collapse
    assert!((b.gas_half_mass_pc / a.gas_half_mass_pc - 1.0).abs() < 0.3, "{} {}", a.gas_half_mass_pc, b.gas_half_mass_pc);
    assert!(b.gas_temperature_k[2] < 1e7);
}

/// One step of dt (the wells' passes run at its start, so two steps: the second one's start).
fn wells_cfg() -> SimConfig {
    let mut cfg = SimConfig { central_mass: 0.0, levels: 8, ..SimConfig::test_disc() };
    cfg.gas.cooling = false;
    cfg.gas.star_formation = false;
    cfg.gas.feedback = false;
    cfg
}

#[test]
fn a_well_feeds_on_gas_at_most_at_eddington_and_heats_it() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let cfg = wells_cfg();
    // 1e8 Msun of gas (2.5e4 a particle), a 1e5 Msun well: Eddington (4.4% of its mass a step) is below a quarter of a
    // gas particle, so the cap can show
    let mut init = gas_blob_of(&cfg, 4_000, 1e4, 1e8);
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    init.push_well(c, [0.0, 0.0], 1e5);
    let mut sim = Sim::from_initial(&g, cfg.clone(), &init).unwrap();
    run(&g, &mut sim, 3);
    let s = sim.read_state(&g).unwrap();
    let m = s.mass[4_000] as f64;
    let hottest = s.star[..4_000].iter().map(|x| x[0]).fold(0.0f32, f32::max);
    // accretion at the starts of the 2nd and 3rd steps (none at 0): at most (1 + 2/45)^2
    eprintln!("well 1e5 -> {m:.4e} Msun in 6 Myr (Eddington allows {:.4e}), hottest gas {hottest:.3e} K", 1e5 * (1.0 + 2.0 / 45.0f64).powi(2));
    assert!(m > 1e5 * 1.01 && m <= 1e5 * (1.0 + 2.0 / 45.0f64).powi(2) * 1.001, "{m}");
    assert!(hottest > 1e5, "{hottest}");
}

#[test]
fn bound_wells_merge_keeping_mass_and_momentum() {
    use squareverse::sim::init::{Initial, Kind};
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    // one fixed step for all (block steps sample the pair's strong pull at different rates, so momentum drifts)
    let cfg = SimConfig { levels: 1, dt_myr: 0.05, ..wells_cfg() };
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let mut init = Initial::with_capacity(3);
    init.push_well(c.offset_pc(-25.0, 0.0, cfg.box_pc), [0.0, -5.0], 2e6);
    init.push_well(c.offset_pc(25.0, 0.0, cfg.box_pc), [3.0, 10.0], 1e6);
    init.push_well(c.offset_pc(5_000.0, 0.0, cfg.box_pc), [0.0, 0.0], 1e6);   // far away: stays
    let mut sim = Sim::from_initial(&g, cfg, &init).unwrap();
    let p0 = Sim::momentum(&sim.read_state(&g).unwrap());
    run(&g, &mut sim, 2);
    let s = sim.read_state(&g).unwrap();
    let p1 = Sim::momentum(&s);
    eprintln!("kinds {:?}, masses {:?}, momentum {p0:?} -> {p1:?}", s.kind, s.mass);
    assert_eq!(s.kind, vec![Kind::Well as u32, Kind::Gone as u32, Kind::Well as u32]);
    assert!((s.mass[0] - 3e6).abs() < 1.0);
    assert!((p1[0] - p0[0]).hypot(p1[1] - p0[1]) < 1e-3 * 2e7, "{p0:?} {p1:?}");
}

#[test]
fn dynamical_friction_slows_a_light_well() {
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let speed = |friction: bool| {
        let mut cfg = wells_cfg();
        cfg.wells.friction = friction;
        // a wide field at rest, nearly static over the test (free fall ~50 Myr): 20k particles of 5e5 Msun evenly
        // over 5 kpc; a 5e6 Msun well (10 field particles, too light for the tree to drag it properly) at 30 pc/Myr
        let mut rng = squareverse::rng::Rng::new(5);
        let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
        let mut init = squareverse::sim::init::Initial::with_capacity(20_001);
        init.single_stars = false;
        for _ in 0..20_000 {
            let (r, a) = (5_000.0 * rng.f64().sqrt(), rng.f64() * std::f64::consts::TAU);
            init.push(c.offset_pc(r * a.cos(), r * a.sin(), cfg.box_pc), [0.0, 0.0], 5e5, (5772.0, 1.0));
        }
        init.push_well(c, [30.0, 0.0], 5e6);
        let mut sim = Sim::from_initial(&g, cfg, &init).unwrap();
        run(&g, &mut sim, 4);
        let v = sim.read_state(&g).unwrap().vel[20_000];
        (v[0] as f64).hypot(v[1] as f64)
    };
    let (with, without) = (speed(true), speed(false));
    // Chandrasekhar: 4 pi G² M rho ln Λ / v² x 0.6 (its weight) ~1.6 pc/Myr², at 3 step starts
    eprintln!("well moving at 30 pc/Myr through a field at rest, after 8 Myr: {with:.1} with friction, {without:.1} without");
    assert!(with < without - 3.0, "{with} {without}");
}

#[test]
fn dense_primordial_gas_collapses_into_wells() {
    use squareverse::sim::init::{Initial, Kind, PRIMORDIAL};
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let mut cfg = wells_cfg();
    cfg.gas.star_formation = true;
    cfg.gas.cooling = true;
    let mut rng = squareverse::rng::Rng::new(13);
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let mut init = Initial::with_capacity(2_000);
    init.single_stars = false;
    // 4e7 Msun of metal-free gas in a Gaussian of sigma 150 pc: ~40 hydrogen atoms / cm^3 at the centre
    for _ in 0..2_000 {
        init.push_gas(c.offset_pc(rng.normal() * 150.0, rng.normal() * 150.0, cfg.box_pc), [0.0, 0.0], 2e4, 1e4, 30.0, PRIMORDIAL);
    }
    let mut sim = Sim::from_initial(&g, cfg, &init).unwrap();
    run(&g, &mut sim, 4);
    let s = sim.read_state(&g).unwrap();
    let count = |k: Kind| s.kind.iter().filter(|&&x| x == k as u32).count();
    let born_stars = (0..s.kind.len()).filter(|&i| s.kind[i] == Kind::Star as u32).count();
    eprintln!("after 8 Myr: {} wells, {} merged away, {born_stars} stars", count(Kind::Well), count(Kind::Gone));
    // a few gas particles the new wells have eaten below the collapse mass may still form stars
    assert!(count(Kind::Well) + count(Kind::Gone) >= 3);
    assert!(born_stars <= 2, "metal-free gas this dense and massive should collapse to wells, not stars: {born_stars}");
}

#[test]
fn stellar_black_holes_become_wells_and_merge() {
    use squareverse::sim::init::{Initial, Kind};
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let cfg = wells_cfg();
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let mut init = Initial::with_capacity(3);
    // two 40 Msun stars, 50 Myr old (they lived ~3 Myr): 10 Msun black holes, 0.5 pc apart, at rest: bound
    for dx in [-0.25, 0.25] {
        init.push_kind(c.offset_pc(dx, 0.0, cfg.box_pc), [0.0, 0.0], 40.0, (5000.0, 1.0), Kind::Star, [-50.0, 40.0, 40.0, 0.0]);
    }
    init.push(c.offset_pc(3_000.0, 0.0, cfg.box_pc), [0.0, 0.0], 1.0, (5772.0, 1.0)); // a bystander
    let mut sim = Sim::from_initial(&g, cfg, &init).unwrap();
    let s0 = sim.read_state(&g).unwrap();
    run(&g, &mut sim, 1);
    let s1 = sim.read_state(&g).unwrap();
    eprintln!("kinds {:?} -> {:?}, masses {:?} -> {:?}", s0.kind, s1.kind, s0.mass, s1.mass);
    assert_eq!(&s0.kind[..2], &[Kind::Well as u32, Kind::Well as u32]);
    assert_eq!(&s1.kind[..2], &[Kind::Well as u32, Kind::Gone as u32]);
    assert!((s1.mass[0] - 20.0).abs() < 1e-3, "{}", s1.mass[0]);
}

#[test]
fn white_dwarfs_in_close_binaries_go_off_as_type_ia() {
    use squareverse::sim::init::{Initial, Kind, binary_of, lifetime};
    let Some(g) = gpu() else { return };
    let g = g.lock().unwrap_or_else(|e| e.into_inner());
    let cfg = wells_cfg();
    let c = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    // 3,000 single 5 Msun stars (they live 179 Myr: white dwarfs). Those whose companion (by binary_of) is close and
    // 1 - 5 Msun are set to reach its lifetime 1 Myr into the run; the rest are 500 Myr old (the shader's binary_of
    // must give the same companions as the CPU's)
    let m = 5.0f32;
    let mut init = Initial::with_capacity(3_000);
    let mut expect = Vec::new();
    for id in 0..3_000u32 {
        let b = binary_of(id, m);
        let m2 = (b[0] * m) as f64;
        // the shader's rule: a companion, log P < 1.5, m2 >= 1, outliving the white dwarf's star
        let tight = b[3] > 0.5 && b[1] < 1.5 && m2 >= 1.0 && lifetime(m2) > lifetime(m as f64);
        // near the rule's edges float rounding on the GPU could tip it: those stay young (still stars)
        let edge = b[3] > 0.5 && ((b[1] - 1.5).abs() < 0.05 || (m2 - 1.0).abs() < 0.05 || (m2 - m as f64).abs() < 0.05);
        let age = if edge { 100.0 } else if tight { lifetime(m2) - 1.0 } else { 500.0 };
        expect.push(tight && !edge);
        let p = c.offset_pc(10.0 * (id % 60) as f64, 10.0 * (id / 60) as f64, cfg.box_pc);
        init.push_kind(p, [0.0, 0.0], m as f64, (5000.0, 1.0), Kind::Star, [-age as f32, m, m, 0.0]);
    }
    let mut sim = Sim::from_initial(&g, cfg, &init).unwrap();
    run(&g, &mut sim, 2); // the evolution passes at 0 and 2 Myr
    let s = sim.read_state(&g).unwrap();
    let gone: Vec<bool> = s.kind.iter().map(|&k| k == Kind::Gone as u32).collect();
    let n_tight = expect.iter().filter(|&&t| t).count();
    let wrong = gone.iter().zip(&expect).filter(|(a, b)| a != b).count();
    eprintln!("{n_tight} of 3,000 white dwarfs in close binaries with 1 - 5 Msun companions; {wrong} disagree with binary_of");
    assert!(n_tight > 20, "{n_tight}");
    assert_eq!(wrong, 0);
    assert!(s.kind.iter().zip(&expect).all(|(&k, &t)| t || k == Kind::WhiteDwarf as u32 || k == Kind::Star as u32));
}
