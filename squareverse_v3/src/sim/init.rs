//! Initial conditions for the phase-0 scene: stars on near-circular orbits round one point mass, with masses from
//! the IMF and main-sequence temperatures and luminosities for their colours.

use super::SimConfig;
use crate::fixed::Fixed2;
use crate::rng::Rng;
use crate::units::G;

/// Particle data as uploaded to the GPU.
pub struct Initial {
    pub pos: Vec<[u32; 4]>,
    pub vel: Vec<[f32; 2]>,
    /// (surface temperature K, luminosity Lsun) per particle, for drawing.
    pub star: Vec<[f32; 2]>,
    pub mass: Vec<f32>,
}

/// A star mass (Msun) from the Kroupa IMF: slope 1.3 from 0.08 to 0.5, 2.3 from 0.5 to 100.
pub fn kroupa_mass(rng: &mut Rng) -> f64 {
    // number in each part (integral of the broken power law, continuous at 0.5)
    fn part(a: f64, lo: f64, hi: f64) -> f64 {
        (hi.powf(1.0 - a) - lo.powf(1.0 - a)) / (1.0 - a)
    }
    let low = part(1.3, 0.08, 0.5);
    let high = 0.5 * part(2.3, 0.5, 100.0); // x 0.5^(2.3 - 1.3) for continuity
    let (a, lo, hi): (f64, f64, f64) = if rng.f64() * (low + high) < low { (1.3, 0.08, 0.5) } else { (2.3, 0.5, 100.0) };
    let u = rng.f64();
    let e = 1.0 - a;
    (lo.powf(e) + u * (hi.powf(e) - lo.powf(e))).powf(1.0 / e)
}

/// Main-sequence surface temperature (K) and luminosity (Lsun) for a mass, from simple power laws.
pub fn main_sequence(m: f64) -> (f64, f64) {
    let l = if m < 0.43 { 0.23 * m.powf(2.3) } else if m < 2.0 { m.powi(4) } else if m < 55.0 { 1.4 * m.powf(3.5) } else { 32_000.0 * m };
    let r = if m < 1.0 { m.powf(0.8) } else { m.powf(0.57) }; // radius, Rsun
    let t = 5772.0 * (l / (r * r)).powf(0.25);
    (t, l)
}

pub fn build(cfg: &SimConfig) -> Initial {
    let n = cfg.particles as usize;
    let mut rng = Rng::new(cfg.seed);
    let gm = G * cfg.central_mass;
    let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let (r2_in, r2_out) = (cfg.r_in_pc.powi(2), cfg.r_out_pc.powi(2));
    let mut out = Initial {
        pos: Vec::with_capacity(n),
        vel: Vec::with_capacity(n),
        star: Vec::with_capacity(n),
        mass: Vec::with_capacity(n),
    };
    for _ in 0..n {
        let r = (r2_in + rng.f64() * (r2_out - r2_in)).sqrt(); // even over the area
        let a = rng.f64() * std::f64::consts::TAU;
        let (c, s) = (a.cos(), a.sin());
        let s2 = r * r + cfg.softening_pc.powi(2);
        let vc = (gm * r * r / (s2 * s2.sqrt())).sqrt(); // circular speed in the softened potential
        let (vr, vt) = (rng.normal() * cfg.dispersion * vc, vc * (1.0 + rng.normal() * cfg.dispersion));
        let p = center.offset_pc(r * c, r * s, cfg.box_pc);
        out.pos.push(p.words());
        // counter-clockwise
        out.vel.push([(vr * c - vt * s) as f32, (vr * s + vt * c) as f32]);
        let m = kroupa_mass(&mut rng);
        let (t, l) = main_sequence(m);
        out.star.push([t as f32, l as f32]);
        out.mass.push(m as f32);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn imf_mean_and_range() {
        let mut rng = Rng::new(3);
        let ms: Vec<f64> = (0..200_000).map(|_| kroupa_mass(&mut rng)).collect();
        let mean = ms.iter().sum::<f64>() / ms.len() as f64;
        assert!(ms.iter().all(|&m| (0.08..=100.0).contains(&m)));
        // the Kroupa IMF over 0.08 - 100 Msun has a mean near 0.6 Msun
        assert!((0.45..0.8).contains(&mean), "mean {mean}");
    }

    #[test]
    fn the_sun_is_the_sun() {
        let (t, l) = main_sequence(1.0);
        assert!((t - 5772.0).abs() < 1.0 && (l - 1.0).abs() < 1e-9);
        let (t_hot, _) = main_sequence(20.0);
        let (t_cool, _) = main_sequence(0.2);
        assert!(t_hot > 20_000.0 && t_cool < 4_000.0, "{t_hot} {t_cool}");
    }
}
