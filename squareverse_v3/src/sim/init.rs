//! Initial conditions: a disc of stars round a central point mass on near-circular orbits, with masses from the
//! IMF and main-sequence temperatures and luminosities for their colours. With `disc_mass` set, the particles'
//! masses are scaled so the disc weighs that much (each particle then stands for several stars: the plan's
//! "stars per particle"), keeping their IMF proportions.

use super::SimConfig;
use crate::fixed::Fixed2;
use crate::rng::Rng;
use crate::units::G;

/// Particle data as uploaded to the GPU (layouts in shaders/common.wgsl).
#[derive(Clone)]
pub struct Initial {
    pub pos: Vec<[u32; 4]>,
    /// (vx, vy, temperature K, luminosity Lsun)
    pub kin: Vec<[f32; 4]>,
    /// (mass f32 bits, id)
    pub body: Vec<[u32; 2]>,
}

impl Initial {
    pub fn with_capacity(n: usize) -> Self {
        Self { pos: Vec::with_capacity(n), kin: Vec::with_capacity(n), body: Vec::with_capacity(n) }
    }

    pub fn push(&mut self, p: Fixed2, v: [f64; 2], mass: f64, star: (f64, f64)) {
        let id = self.pos.len() as u32;
        self.pos.push(p.words());
        self.kin.push([v[0] as f32, v[1] as f32, star.0 as f32, star.1 as f32]);
        self.body.push([(mass as f32).to_bits(), id]);
    }

    pub fn len(&self) -> usize {
        self.pos.len()
    }

    pub fn is_empty(&self) -> bool {
        self.pos.is_empty()
    }
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

/// The disc scene (`SimConfig`).
pub fn build(cfg: &SimConfig) -> Initial {
    let n = cfg.particles as usize;
    let mut rng = Rng::new(cfg.seed);
    let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let (r2_in, r2_out) = (cfg.r_in_pc.powi(2), cfg.r_out_pc.powi(2));

    // star masses first, so they can be scaled to the disc mass
    let stars: Vec<f64> = (0..n).map(|_| kroupa_mass(&mut rng)).collect();
    let total: f64 = stars.iter().sum();
    let scale = if cfg.disc_mass > 0.0 && total > 0.0 { cfg.disc_mass / total } else { 1.0 };
    let disc = total * scale;

    let mut out = Initial::with_capacity(n);
    for &m in &stars {
        let r = (r2_in + rng.f64() * (r2_out - r2_in)).sqrt(); // even over the area
        let a = rng.f64() * std::f64::consts::TAU;
        let (c, s) = (a.cos(), a.sin());
        // circular speed: the softened central mass, plus the disc inside r as if it sat at the centre
        let s2 = r * r + cfg.central_softening_pc.powi(2);
        let inside = disc * ((r * r - r2_in) / (r2_out - r2_in)).max(0.0);
        let vc = (G * cfg.central_mass * r * r / (s2 * s2.sqrt()) + G * inside / r).sqrt();
        let (vr, vt) = (rng.normal() * cfg.dispersion * vc, vc * (1.0 + rng.normal() * cfg.dispersion));
        let p = center.offset_pc(r * c, r * s, cfg.box_pc);
        // counter-clockwise
        out.push(p, [vr * c - vt * s, vr * s + vt * c], m * scale, main_sequence(m));
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

    #[test]
    fn disc_weighs_what_it_is_told() {
        let cfg = SimConfig { particles: 10_000, disc_mass: 5e8, ..Default::default() };
        let init = build(&cfg);
        let m: f64 = init.body.iter().map(|b| f32::from_bits(b[0]) as f64).sum();
        assert!((m / 5e8 - 1.0).abs() < 1e-5, "{m}");
    }
}
