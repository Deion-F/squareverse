//! A CPU version of the GPU step in f64, to check the shader against (tests only care that they agree closely;
//! the GPU works in f32 so they are not bit-identical).

use super::SimConfig;
use crate::fixed::Fixed2;
use crate::units::G;

pub fn steps(cfg: &SimConfig, pos: &mut [Fixed2], vel: &mut [[f64; 2]], k: u32) {
    let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let (gm, eps2, dt, b) = (G * cfg.central_mass, cfg.softening_pc.powi(2), cfg.dt_myr, cfg.box_pc);
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
