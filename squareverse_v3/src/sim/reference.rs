//! CPU versions of the GPU passes in f64, to check the shaders against (they agree closely, not bit for bit).

use super::SimConfig;
use crate::fixed::Fixed2;
use crate::units::G;

/// `k` kick-drift-kick steps in the central mass's field alone (no self-gravity).
pub fn steps(cfg: &SimConfig, pos: &mut [Fixed2], vel: &mut [[f64; 2]], k: u32) {
    let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let (gm, eps2, dt, b) = (G * cfg.central_mass, cfg.central_softening_pc.powi(2), cfg.dt_myr, cfg.box_pc);
    let accel = |p: Fixed2| {
        let (dx, dy) = p.delta_pc(center, b);
        let s2 = dx * dx + dy * dy + eps2;
        let f = -gm / (s2 * s2.sqrt());
        [f * dx, f * dy]
    };
    for (p, v) in pos.iter_mut().zip(vel.iter_mut()) {
        for _ in 0..k {
            let a = accel(*p);
            v[0] += a[0] * dt * 0.5;
            v[1] += a[1] * dt * 0.5;
            *p = p.offset_pc(v[0] * dt, v[1] * dt, b);
            let a = accel(*p);
            v[0] += a[0] * dt * 0.5;
            v[1] += a[1] * dt * 0.5;
        }
    }
}

/// The self-gravity acceleration on particle i by direct summation over all the others (softened as on the GPU).
pub fn direct_accel(cfg: &SimConfig, pos: &[Fixed2], mass: &[f32], i: usize) -> [f64; 2] {
    let eps2 = cfg.softening_pc.powi(2);
    let mut a = [0.0; 2];
    for (j, (p, &m)) in pos.iter().zip(mass).enumerate() {
        if j == i {
            continue;
        }
        let (dx, dy) = p.delta_pc(pos[i], cfg.box_pc);
        let s2 = dx * dx + dy * dy + eps2;
        let f = G * m as f64 / (s2 * s2.sqrt());
        a[0] += f * dx;
        a[1] += f * dy;
    }
    a
}

/// The central mass's acceleration on a particle.
pub fn central_accel(cfg: &SimConfig, p: Fixed2) -> [f64; 2] {
    let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let (dx, dy) = p.delta_pc(center, cfg.box_pc);
    let s2 = dx * dx + dy * dy + cfg.central_softening_pc.powi(2);
    let f = -G * cfg.central_mass / (s2 * s2.sqrt());
    [f * dx, f * dy]
}
