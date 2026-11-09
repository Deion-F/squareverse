//! Initial conditions: a disc of stars round a central point mass on near-circular orbits, with masses from the
//! IMF and main-sequence temperatures and luminosities for their colours. With `disc_mass` set, the particles'
//! masses are scaled so the disc weighs that much (each particle then stands for several stars: the plan's
//! "stars per particle"), keeping their IMF proportions. `galaxy` builds the phase-2 galaxy in equilibrium.

use serde::Serialize;

use super::SimConfig;
use crate::fixed::Fixed2;
use crate::rng::Rng;
use crate::units::G;

/// The kind is kept in the top bits of a particle's id word (shaders/common.wgsl K_*).
pub const KIND_SHIFT: u32 = 28;
pub const ID_MASK: u32 = (1 << KIND_SHIFT) - 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u32)]
pub enum Kind {
    Star = 0,
    DarkMatter = 1,
    Well = 2,
    WhiteDwarf = 3,
    NeutronStar = 4,
    BlackHole = 5,
    Gone = 6,
    Gas = 7,
}

/// Mass fractions (He, C/N/O, Mg/Si, Fe) of solar and primordial matter; hydrogen is the rest. Solar after Asplund
/// et al. (2009), the elements this sim doesn't follow (Ne, S, ...) counted with C/N/O.
pub const SOLAR: [f32; 4] = [0.27, 0.0105, 0.0015, 0.0013];
pub const SOLAR_Z: f64 = 0.0133;
pub const PRIMORDIAL: [f32; 4] = [0.245, 0.0, 0.0, 0.0];

/// Elements at metallicity z (in units of solar): helium rises 1.5x as fast as the metals (ΔY / ΔZ).
pub fn elements(z: f64) -> [f32; 4] {
    let zz = z.max(0.0);
    [
        (PRIMORDIAL[0] as f64 + 1.5 * SOLAR_Z * zz).min(0.4) as f32,
        (SOLAR[1] as f64 * zz) as f32,
        (SOLAR[2] as f64 * zz) as f32,
        (SOLAR[3] as f64 * zz) as f32,
    ]
}

/// Particle data as uploaded to the GPU (layouts in shaders/common.wgsl).
#[derive(Clone)]
pub struct Initial {
    pub pos: Vec<[u32; 4]>,
    /// (vx, vy, temperature K, luminosity Lsun)
    pub kin: Vec<[f32; 4]>,
    /// (mass f32 bits, kind << KIND_SHIFT | id)
    pub body: Vec<[u32; 2]>,
    /// (birth time Myr, the star's mass Msun (0: no stellar evolution), mass at birth, well number as f32 bits)
    pub about: Vec<[f32; 4]>,
    /// Gas: (u, Σ, H, -), (hydro ax, ay, du/dt, signal speed); zeros for the rest.
    pub gas: Vec<[f32; 8]>,
    /// Element mass fractions (He, C/N/O, Mg/Si, Fe).
    pub chem: Vec<[f32; 4]>,
    /// Super wells (numbered 0 .. wells - 1).
    pub wells: u32,
    /// Each star particle is one star (true) or a population.
    pub single_stars: bool,
}

impl Initial {
    pub fn with_capacity(n: usize) -> Self {
        Self {
            pos: Vec::with_capacity(n),
            kin: Vec::with_capacity(n),
            body: Vec::with_capacity(n),
            about: Vec::with_capacity(n),
            gas: Vec::with_capacity(n),
            chem: Vec::with_capacity(n),
            wells: 0,
            single_stars: true,
        }
    }

    /// A star particle of fixed colour (no stellar evolution).
    pub fn push(&mut self, p: Fixed2, v: [f64; 2], mass: f64, star: (f64, f64)) {
        self.push_kind(p, v, mass, star, Kind::Star, [0.0, 0.0, mass as f32, 0.0]);
    }

    pub fn push_kind(&mut self, p: Fixed2, v: [f64; 2], mass: f64, star: (f64, f64), kind: Kind, about: [f32; 4]) {
        let id = self.pos.len() as u32;
        assert!(id <= ID_MASK, "too many particles for the id bits");
        self.pos.push(p.words());
        self.kin.push([v[0] as f32, v[1] as f32, star.0 as f32, star.1 as f32]);
        self.body.push([(mass as f32).to_bits(), (kind as u32) << KIND_SHIFT | id]);
        self.about.push(about);
        self.gas.push([0.0; 8]);
        self.chem.push(SOLAR);
    }

    /// Sets the elements of the particle just added.
    pub fn set_chem(&mut self, chem: [f32; 4]) {
        *self.chem.last_mut().expect("a particle") = chem;
    }

    /// A gas particle at temperature `t_k` (K), its kernel reach first guessed as `h` pc.
    pub fn push_gas(&mut self, p: Fixed2, v: [f64; 2], mass: f64, t_k: f64, h: f64, chem: [f32; 4]) {
        let u = if t_k >= 1e4 { t_k / 46.3 } else { t_k / 98.0 };
        self.push_kind(p, v, mass, (t_k, 0.0), Kind::Gas, [0.0, 0.0, mass as f32, f32::from_bits(PART_GAS as u32)]);
        let z = (chem[1] + chem[2] + chem[3]) as f64 / SOLAR_Z;
        *self.gas.last_mut().expect("just pushed") = [u as f32, 0.0, h as f32, z as f32, 0.0, 0.0, 0.0, 0.0];
        self.set_chem(chem);
    }

    /// A super well; numbered in the order added.
    pub fn push_well(&mut self, p: Fixed2, v: [f64; 2], mass: f64) {
        let w = self.wells;
        self.wells += 1;
        self.push_kind(p, v, mass, (5000.0, 0.0), Kind::Well, [0.0, 0.0, mass as f32, f32::from_bits(w)]);
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

/// A galaxy (`Scene::Galaxy`): masses Msun, lengths pc, ages Myr. The defaults are roughly the Milky Way's.
#[derive(Clone, Debug, Serialize)]
pub struct GalaxyConfig {
    /// Exponential disc: mass, scale length, cut at this many scale lengths.
    pub disc_mass: f64,
    pub disc_scale_pc: f64,
    pub disc_cut: f64,
    /// Toomre Q of the disc's stars: below ~1 it breaks up, ~1 - 1.5 grows spiral arms, 2+ stays smooth.
    pub toomre_q: f64,
    /// Bulge (Plummer in projection, Σ ∝ (1 + R²/a²)^-2): mass, scale, cut at this many scales.
    pub bulge_mass: f64,
    pub bulge_scale_pc: f64,
    pub bulge_cut: f64,
    /// Dark matter halo, Σ ∝ 1 / sqrt(R² + core²) out to `halo_radius_pc`: in 2D with 1/r² gravity this gives a
    /// flat rotation curve (as Mestel's disc), the way an isothermal sphere does in 3D.
    pub halo_mass: f64,
    pub halo_core_pc: f64,
    pub halo_radius_pc: f64,
    /// The central super well.
    pub well_mass: f64,
    /// Gas disc (exponential): mass, scale length, cut at this many scale lengths, starting temperature (K).
    pub gas_mass: f64,
    pub gas_scale_pc: f64,
    pub gas_cut: f64,
    pub gas_temperature_k: f64,
    /// Metallicity (solar = 1) at 8 kpc, falling by `metal_gradient` dex per kpc outwards; stars were born with
    /// 0.04 dex less for each Gyr of their age.
    pub metallicity: f64,
    pub metal_gradient: f64,
    /// Shares of the particles (the rest are disc stars).
    pub halo_share: f64,
    pub bulge_share: f64,
    pub gas_share: f64,
    /// Star ages: the disc's spread evenly over 0 .. `disc_age_myr`, the bulge's around `bulge_age_myr` (± 10%).
    pub disc_age_myr: f64,
    pub bulge_age_myr: f64,
}

impl Default for GalaxyConfig {
    fn default() -> Self {
        Self {
            disc_mass: 4e10,
            disc_scale_pc: 2_600.0,
            disc_cut: 5.0,
            toomre_q: 1.5,
            bulge_mass: 1e10,
            // 600 pc swelled to ~1,000 within 100 Myr even with 7 step levels (2026-11-08)
            bulge_scale_pc: 1_000.0,
            bulge_cut: 10.0,
            halo_mass: 3.5e11,
            halo_core_pc: 3_000.0,
            halo_radius_pc: 40_000.0,
            well_mass: 4e6,
            gas_mass: 1e10,
            gas_scale_pc: 5_200.0,
            gas_cut: 4.0,
            gas_temperature_k: 1e4,
            metallicity: 1.0,
            metal_gradient: 0.06,
            halo_share: 0.4,
            bulge_share: 0.1,
            gas_share: 0.1,
            disc_age_myr: 10_000.0,
            bulge_age_myr: 10_000.0,
        }
    }
}

/// Which part of the galaxy each particle belongs to (by id; also in about.w's bits, except for wells, whose
/// about.w is their number).
pub const PART_DISC: u8 = 0;
pub const PART_BULGE: u8 = 1;
pub const PART_HALO: u8 = 2;
pub const PART_WELL: u8 = 3;
pub const PART_GAS: u8 = 4;
/// Stars born during the run (evolve.wgsl PART_NEW).
pub const PART_NEW: u8 = 5;

/// Metallicity (solar = 1) of the galaxy's gas at radius r pc.
fn metallicity_at(g: &GalaxyConfig, r: f64) -> f64 {
    g.metallicity * 10f64.powf(-g.metal_gradient * (r / 1_000.0 - 8.0))
}

/// The share of a Kroupa population's mass its dead stars have given back by `age` Myr (Jungwiert et al. 2001),
/// as shaders/evolve.wgsl.
pub fn returned_fraction(age: f64) -> f64 {
    (0.046 * (age.max(0.0) / 0.276 + 1.0).ln()).min(0.5)
}

/// The mean of the Kroupa IMF over 0.08 - 100 Msun.
fn kroupa_mean(rng: &mut Rng) -> f64 {
    (0..20_000).map(|_| kroupa_mass(rng)).sum::<f64>() / 20_000.0
}

/// Positions (velocities zero) and stars of the galaxy, and each particle's part. `galaxy_velocities` gives the
/// velocities once the GPU has the forces.
pub fn galaxy(cfg: &SimConfig) -> (Initial, Vec<u8>) {
    let g = &cfg.galaxy;
    let n = cfg.particles.max(10) as usize;
    let mut rng = Rng::new(cfg.seed);
    let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let n_halo = (n as f64 * g.halo_share).round() as usize;
    let n_bulge = (n as f64 * g.bulge_share).round() as usize;
    let n_gas = if g.gas_mass > 0.0 { (n as f64 * g.gas_share).round() as usize } else { 0 };
    let n_disc = n - 1 - n_halo - n_bulge - n_gas;
    let star_mass = (g.disc_mass + g.bulge_mass) / (n_disc + n_bulge) as f64;
    let mean_star = kroupa_mean(&mut rng);
    let mut out = Initial::with_capacity(n);
    // stars per particle ~1 or less: each particle is one star; else a population with one star's colour
    out.single_stars = star_mass < 1.5 * mean_star;
    let mut parts = Vec::with_capacity(n);
    let place = |rng: &mut Rng, r: f64| {
        let a = rng.f64() * std::f64::consts::TAU;
        center.offset_pc(r * a.cos(), r * a.sin(), cfg.box_pc)
    };

    out.push_well(center, [0.0, 0.0], g.well_mass);
    parts.push(PART_WELL);

    let stars = |out: &mut Initial, parts: &mut Vec<u8>, rng: &mut Rng, count: usize, mass: f64, part: u8| {
        for _ in 0..count {
            let r = match part {
                PART_DISC => loop {
                    // R e^(-R/h): the sum of two exponentials
                    let r = -g.disc_scale_pc * (rng.f64().max(1e-300) * rng.f64().max(1e-300)).ln();
                    if r < g.disc_cut * g.disc_scale_pc {
                        break r;
                    }
                },
                _ => loop {
                    let u = rng.f64();
                    let r = g.bulge_scale_pc * (u / (1.0 - u)).sqrt();
                    if r < g.bulge_cut * g.bulge_scale_pc {
                        break r;
                    }
                },
            };
            let age = match part {
                PART_DISC => rng.f64() * g.disc_age_myr,
                _ => g.bulge_age_myr * (0.9 + 0.2 * rng.f64()),
            };
            let m_star = kroupa_mass(rng);
            let (mass, birth_mass) = if out.single_stars {
                (m_star, m_star)
            } else {
                // its present mass is `mass`: at birth it had what its dead stars have given back since
                (mass, mass / (1.0 - returned_fraction(age)))
            };
            let about = [-age as f32, m_star as f32, birth_mass as f32, f32::from_bits(part as u32)];
            out.push_kind(place(rng, r), [0.0, 0.0], mass, main_sequence(m_star), Kind::Star, about);
            out.set_chem(elements(metallicity_at(g, r) * 10f64.powf(-0.04 * age / 1_000.0)));
            parts.push(part);
        }
    };
    stars(&mut out, &mut parts, &mut rng, n_disc, g.disc_mass / n_disc.max(1) as f64, PART_DISC);
    stars(&mut out, &mut parts, &mut rng, n_bulge, g.bulge_mass / n_bulge.max(1) as f64, PART_BULGE);

    // the gas disc, its kernel reach first guessed from its surface density
    let m_gas = g.gas_mass / n_gas.max(1) as f64;
    for _ in 0..n_gas {
        let r = loop {
            let r = -g.gas_scale_pc * (rng.f64().max(1e-300) * rng.f64().max(1e-300)).ln();
            if r < g.gas_cut * g.gas_scale_pc {
                break r;
            }
        };
        let sd = surface_density(g, PART_GAS, r).max(1e-3);
        let h = (24.0 * m_gas / (std::f64::consts::PI * sd)).sqrt().clamp(10.0, 3_000.0);
        out.push_gas(place(&mut rng, r), [0.0, 0.0], m_gas, g.gas_temperature_k, h, elements(metallicity_at(g, r)));
    }
    parts.resize(parts.len() + n_gas, PART_GAS);

    let (rc, rh) = (g.halo_core_pc, g.halo_radius_pc);
    let span = (rh * rh + rc * rc).sqrt() - rc;
    for _ in 0..n_halo {
        // M(<R) ∝ sqrt(R² + rc²) - rc
        let s = rng.f64() * span + rc;
        let r = (s * s - rc * rc).max(0.0).sqrt();
        let m = g.halo_mass / n_halo.max(1) as f64;
        let about = [0.0, 0.0, m as f32, f32::from_bits(PART_HALO as u32)];
        out.push_kind(place(&mut rng, r), [0.0, 0.0], m, (5000.0, 0.0), Kind::DarkMatter, about);
    }
    parts.resize(parts.len() + n_halo, PART_HALO);
    (out, parts)
}

/// Surface density of a part at radius r, Msun / pc².
fn surface_density(g: &GalaxyConfig, part: u8, r: f64) -> f64 {
    use std::f64::consts::PI;
    match part {
        PART_DISC => {
            let h = g.disc_scale_pc;
            let x = g.disc_cut;
            let norm = 1.0 - (1.0 + x) * (-x).exp(); // the share of an untruncated disc inside the cut
            if r < x * h { g.disc_mass / (2.0 * PI * h * h * norm) * (-r / h).exp() } else { 0.0 }
        }
        PART_GAS => {
            let h = g.gas_scale_pc;
            let x = g.gas_cut;
            let norm = 1.0 - (1.0 + x) * (-x).exp();
            if r < x * h { g.gas_mass / (2.0 * PI * h * h * norm) * (-r / h).exp() } else { 0.0 }
        }
        PART_BULGE => {
            let a = g.bulge_scale_pc;
            let x2 = g.bulge_cut * g.bulge_cut;
            let norm = x2 / (1.0 + x2);
            if r < g.bulge_cut * a { g.bulge_mass * a * a / (PI * (a * a + r * r).powi(2) * norm) } else { 0.0 }
        }
        _ => {
            let (rc, rh) = (g.halo_core_pc, g.halo_radius_pc);
            let span = (rh * rh + rc * rc).sqrt() - rc;
            if r < rh { g.halo_mass / (2.0 * PI * span * (r * r + rc * rc).sqrt()) } else { 0.0 }
        }
    }
}

/// The circular speed curve v_c(R) from the forces the particles feel: the inward acceleration averaged in rings
/// (log-spaced from 10 pc), v_c² = R g. Returns (R, g) samples.
pub fn radial_pull(cfg: &SimConfig, s: &super::State) -> Vec<(f64, f64)> {
    let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let rmax = cfg.galaxy.halo_radius_pc.max(cfg.view_radius_pc()) * 1.05;
    let (rmin, bins) = (10.0f64, 160usize);
    let lr = (rmax / rmin).ln();
    let mut sum = vec![0.0f64; bins];
    let mut cnt = vec![0u32; bins];
    for (p, a) in s.pos.iter().zip(&s.acc) {
        let (dx, dy) = p.delta_pc(center, cfg.box_pc);
        let r = dx.hypot(dy);
        if r < rmin || r >= rmax {
            continue;
        }
        let b = (((r / rmin).ln() / lr) * bins as f64) as usize;
        sum[b.min(bins - 1)] += -(a[0] as f64 * dx + a[1] as f64 * dy) / r;
        cnt[b.min(bins - 1)] += 1;
    }
    let mut out: Vec<(f64, f64)> = (0..bins)
        .filter(|&b| cnt[b] >= 4)
        .map(|b| (rmin * ((b as f64 + 0.5) / bins as f64 * lr).exp(), sum[b] / cnt[b] as f64))
        .collect();
    // a light running mean
    let raw = out.clone();
    for i in 1..out.len().saturating_sub(1) {
        out[i].1 = (raw[i - 1].1 + 2.0 * raw[i].1 + raw[i + 1].1) / 4.0;
    }
    out
}

fn interp(curve: &[(f64, f64)], r: f64) -> f64 {
    if curve.is_empty() {
        return 0.0;
    }
    if r <= curve[0].0 {
        return curve[0].1;
    }
    for w in curve.windows(2) {
        if r <= w[1].0 {
            let t = (r.ln() - w[0].0.ln()) / (w[1].0.ln() - w[0].0.ln());
            return w[0].1 + t * (w[1].1 - w[0].1);
        }
    }
    curve[curve.len() - 1].1
}

/// Velocities for the galaxy from the forces its particles feel (`s`, read after the first force pass), in id
/// order, as (vx, vy, temperature, luminosity):
/// * bulge and halo: no rotation, isotropic dispersion from the Jeans equation, Σσ²(R) = ∫_R^∞ Σ g dR';
/// * disc: σ_R from Toomre Q (σ_R = Q 3.36 G Σ / κ), σ_φ = σ_R κ / 2Ω, and the mean rotation from the circular
///   speed less the asymmetric drift, v̄_φ² = v_c² + σ_R² (1 - κ²/4Ω² + d ln(Σ σ_R²) / d ln R);
/// * then the whole is set at rest (its total momentum taken out).
pub fn galaxy_velocities(cfg: &SimConfig, init: &Initial, parts: &[u8], s: &super::State) -> Vec<[f32; 4]> {
    let g = &cfg.galaxy;
    let pull = radial_pull(cfg, s);
    let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    // a log grid for the profiles
    let (rmin, rmax, k) = (5.0f64, g.halo_radius_pc * 1.02, 1200usize);
    let grid: Vec<f64> = (0..k).map(|i| rmin * (rmax / rmin).powf(i as f64 / (k - 1) as f64)).collect();
    let gr: Vec<f64> = grid.iter().map(|&r| interp(&pull, r).max(0.0)).collect();
    // Jeans: Σσ² from the outside in (trapezoids)
    let jeans = |part: u8| -> Vec<f64> {
        let mut acc = vec![0.0; k];
        for i in (0..k - 1).rev() {
            let (a, b) = (grid[i], grid[i + 1]);
            let fa = surface_density(g, part, a) * gr[i];
            let fb = surface_density(g, part, b) * gr[i + 1];
            acc[i] = acc[i + 1] + 0.5 * (fa + fb) * (b - a);
        }
        (0..k)
            .map(|i| {
                let sd = surface_density(g, part, grid[i]);
                if sd > 0.0 { (acc[i] / sd).max(0.0) } else { 0.0 }
            })
            .collect()
    };
    let sig2_bulge = jeans(PART_BULGE);
    let sig2_halo = jeans(PART_HALO);
    // the disc
    let vc: Vec<f64> = grid.iter().zip(&gr).map(|(r, g)| (r * g).sqrt()).collect();
    let dlog = |f: &dyn Fn(usize) -> f64, i: usize| -> f64 {
        let (a, b) = (i.saturating_sub(1), (i + 1).min(k - 1));
        (f(b).max(1e-30).ln() - f(a).max(1e-30).ln()) / (grid[b].ln() - grid[a].ln())
    };
    let kappa: Vec<f64> = (0..k)
        .map(|i| {
            let om = vc[i] / grid[i];
            (2.0 * om * om * (1.0 + dlog(&|j| vc[j], i))).max(0.0).sqrt()
        })
        .collect();
    let sig_r: Vec<f64> = (0..k)
        .map(|i| {
            let s = g.toomre_q * 3.36 * G * surface_density(g, PART_DISC, grid[i]) / kappa[i].max(1e-9);
            s.min(0.5 * vc[i])
        })
        .collect();
    let disc_rot: Vec<(f64, f64, f64)> = (0..k)
        .map(|i| {
            let om = (vc[i] / grid[i]).max(1e-12);
            let ratio = (kappa[i] / (2.0 * om)).clamp(0.0, 1.0); // σ_φ / σ_R
            let slope = dlog(&|j| surface_density(g, PART_DISC, grid[j]) * sig_r[j] * sig_r[j], i);
            let vphi2 = vc[i] * vc[i] + sig_r[i] * sig_r[i] * (1.0 - ratio * ratio + slope);
            (vphi2.max(0.0).sqrt(), sig_r[i], sig_r[i] * ratio)
        })
        .collect();
    let at = |v: &[f64], r: f64| -> f64 {
        let i = grid.partition_point(|&x| x < r).clamp(1, k - 1);
        let t = ((r.max(rmin)).ln() - grid[i - 1].ln()) / (grid[i].ln() - grid[i - 1].ln());
        v[i - 1] + t.clamp(0.0, 1.0) * (v[i] - v[i - 1])
    };

    let mut rng = Rng::new(cfg.seed ^ 0x5eed_7e10_c17e_5000);
    let n = init.len();
    let mut kin = vec![[0.0f32; 4]; n];
    let (mut p, mut m_tot) = ([0.0f64; 2], 0.0f64);
    for id in 0..n {
        let (dx, dy) = s.pos[id].delta_pc(center, cfg.box_pc);
        let r = dx.hypot(dy).max(1e-3);
        let (ux, uy) = (dx / r, dy / r);
        let (vr, vphi) = match parts[id] {
            PART_DISC => {
                let i = grid.partition_point(|&x| x < r).clamp(1, k - 1);
                let (rot, sr, sp) = disc_rot[i];
                (rng.normal() * sr, rot + rng.normal() * sp)
            }
            PART_BULGE => {
                let sg = at(&sig2_bulge, r).sqrt();
                (rng.normal() * sg, rng.normal() * sg)
            }
            PART_HALO => {
                let sg = at(&sig2_halo, r).sqrt();
                (rng.normal() * sg, rng.normal() * sg)
            }
            // gas: cold, on circular orbits (its pressure support is a few km/s against ~230)
            PART_GAS => (0.0, at(&vc, r)),
            _ => (0.0, 0.0),
        };
        // counter-clockwise
        let v = [vr * ux - vphi * uy, vr * uy + vphi * ux];
        let m = s.mass[id] as f64;
        p = [p[0] + m * v[0], p[1] + m * v[1]];
        m_tot += m;
        kin[id] = [v[0] as f32, v[1] as f32, s.star[id][0], s.star[id][1]];
    }
    let v0 = [p[0] / m_tot, p[1] / m_tot];
    for k in &mut kin {
        k[0] -= v0[0] as f32;
        k[1] -= v0[1] as f32;
    }
    kin
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

/// Figures to judge a galaxy by (headless report, tests).
#[derive(Clone, Debug, Serialize)]
pub struct GalaxyStats {
    /// Half-mass radius of the disc, bulge and halo, pc.
    pub half_mass_pc: [f64; 3],
    /// The disc's radial velocity dispersion, pc / Myr, in rings round 1, 2 and 3 disc scale lengths.
    pub disc_sigma_r: [f64; 3],
    /// The circular speed v_c = sqrt(R g), pc / Myr, at these radii (pc).
    pub rotation_curve: Vec<(f64, f64)>,
    /// Particles by kind (star, dark matter, well, white dwarf, neutron star, black hole, swallowed, gas).
    pub kinds: [u32; 8],
    /// The central well's mass, Msun.
    pub well_mass: f64,
    /// Gas: mass, mass above 10^5 K, and its metallicity (mass-weighted, solar = 1).
    pub gas_mass: f64,
    pub hot_gas_mass: f64,
    pub gas_metallicity: f64,
    /// Stars born in the run: how many, their mass, and their metallicity (solar = 1).
    pub new_stars: u32,
    pub new_star_mass: f64,
    pub new_star_metallicity: f64,
    /// Kennicutt-Schmidt: per 1 kpc ring out to 16 kpc, (gas Σ Msun/pc², star formation Msun/yr/kpc² from the stars
    /// born in the last 50 Myr). Observed: 2.5e-4 (Σ / 1 Msun pc⁻²)^1.4 (Kennicutt 1998).
    pub kennicutt_schmidt: Vec<(f64, f64)>,
    /// The gas's half-mass radius (pc), and its temperature (K) at the 10th, 50th and 90th percentile by mass.
    pub gas_half_mass_pc: f64,
    pub gas_temperature_k: [f64; 3],
}

pub fn galaxy_stats(cfg: &SimConfig, s: &super::State, now_myr: f64) -> GalaxyStats {
    let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
    let part = |i: usize| if s.kind[i] == Kind::Well as u32 { PART_WELL } else { s.about[i][3].to_bits() as u8 };
    let mut half = [0.0; 3];
    for (k, h) in half.iter_mut().enumerate() {
        let mut rs: Vec<(f64, f64)> = (0..s.pos.len())
            .filter(|&i| part(i) == k as u8 && s.kind[i] != Kind::Gone as u32)
            .map(|i| {
                let (dx, dy) = s.pos[i].delta_pc(center, cfg.box_pc);
                (dx.hypot(dy), s.mass[i] as f64)
            })
            .collect();
        rs.sort_by(|a, b| a.0.total_cmp(&b.0));
        let total: f64 = rs.iter().map(|r| r.1).sum();
        let mut acc = 0.0;
        for (r, m) in rs {
            acc += m;
            if acc >= 0.5 * total {
                *h = r;
                break;
            }
        }
    }
    let h = cfg.galaxy.disc_scale_pc;
    let mut sig = [0.0; 3];
    for (k, out) in sig.iter_mut().enumerate() {
        let r0 = (k + 1) as f64 * h;
        let vr: Vec<f64> = (0..s.pos.len())
            .filter(|&i| part(i) == PART_DISC)
            .filter_map(|i| {
                let (dx, dy) = s.pos[i].delta_pc(center, cfg.box_pc);
                let r = dx.hypot(dy);
                ((r - r0).abs() < 0.25 * h).then(|| (s.vel[i][0] as f64 * dx + s.vel[i][1] as f64 * dy) / r)
            })
            .collect();
        if !vr.is_empty() {
            let mean = vr.iter().sum::<f64>() / vr.len() as f64;
            *out = (vr.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / vr.len() as f64).sqrt();
        }
    }
    let pull = radial_pull(cfg, s);
    let rotation_curve = [1_000.0, 2_000.0, 4_000.0, 8_000.0, 12_000.0, 16_000.0, 24_000.0]
        .iter()
        .map(|&r| (r, (r * interp(&pull, r)).max(0.0).sqrt()))
        .collect();
    let mut kinds = [0u32; 8];
    for &k in &s.kind {
        kinds[(k as usize).min(7)] += 1;
    }
    let well_mass = (0..s.pos.len()).filter(|&i| s.kind[i] == Kind::Well as u32).map(|i| s.mass[i] as f64).sum();
    let z_of = |i: usize| (s.chem[i][1] + s.chem[i][2] + s.chem[i][3]) as f64 / SOLAR_Z;
    let (mut gas_mass, mut hot, mut gz) = (0.0, 0.0, 0.0);
    let (mut new_stars, mut new_mass, mut nz) = (0u32, 0.0, 0.0);
    for i in 0..s.pos.len() {
        let m = s.mass[i] as f64;
        if s.kind[i] == Kind::Gas as u32 {
            gas_mass += m;
            gz += m * z_of(i);
            if s.star[i][0] > 1e5 {
                hot += m;
            }
        } else if s.about[i][3].to_bits() == PART_NEW as u32 && s.kind[i] != Kind::Well as u32 {
            new_stars += 1;
            new_mass += m;
            nz += m * z_of(i);
        }
    }
    let mut rings = vec![(0.0f64, 0.0f64); 16];
    for i in 0..s.pos.len() {
        let (dx, dy) = s.pos[i].delta_pc(center, cfg.box_pc);
        let k = (dx.hypot(dy) / 1_000.0) as usize;
        if k >= rings.len() {
            continue;
        }
        if s.kind[i] == Kind::Gas as u32 {
            rings[k].0 += s.mass[i] as f64;
        } else if s.about[i][3].to_bits() == PART_NEW as u32 && (now_myr - s.about[i][0] as f64) < 50.0 {
            rings[k].1 += s.about[i][2] as f64; // the mass it was born with
        }
    }
    let kennicutt_schmidt = rings
        .iter()
        .enumerate()
        .map(|(k, &(gas, born))| {
            let area_pc2 = std::f64::consts::PI * (((k + 1) * 1_000) as f64).powi(2) - std::f64::consts::PI * ((k * 1_000) as f64).powi(2);
            // Msun per 50 Myr per pc² -> Msun / yr / kpc²: x 1e6 pc²/kpc² / 5e7 yr
            (gas / area_pc2, born / area_pc2 * 1e6 / 5e7)
        })
        .collect();
    let mut gr: Vec<(f64, f64)> = Vec::new();
    let mut gt: Vec<(f64, f64)> = Vec::new();
    for i in 0..s.pos.len() {
        if s.kind[i] == Kind::Gas as u32 {
            let (dx, dy) = s.pos[i].delta_pc(center, cfg.box_pc);
            gr.push((dx.hypot(dy), s.mass[i] as f64));
            gt.push((s.star[i][0] as f64, s.mass[i] as f64));
        }
    }
    let quantile = |v: &mut Vec<(f64, f64)>, q: f64| -> f64 {
        v.sort_by(|a, b| a.0.total_cmp(&b.0));
        let total: f64 = v.iter().map(|x| x.1).sum();
        let mut acc = 0.0;
        for &(x, m) in v.iter() {
            acc += m;
            if acc >= q * total {
                return x;
            }
        }
        0.0
    };
    let gas_half_mass_pc = quantile(&mut gr, 0.5);
    let gas_temperature_k = [quantile(&mut gt, 0.1), quantile(&mut gt, 0.5), quantile(&mut gt, 0.9)];
    GalaxyStats {
        gas_half_mass_pc,
        gas_temperature_k,
        kennicutt_schmidt,
        half_mass_pc: half,
        disc_sigma_r: sig,
        rotation_curve,
        kinds,
        well_mass,
        gas_mass,
        hot_gas_mass: hot,
        gas_metallicity: if gas_mass > 0.0 { gz / gas_mass } else { 0.0 },
        new_stars,
        new_star_mass: new_mass,
        new_star_metallicity: if new_mass > 0.0 { nz / new_mass } else { 0.0 },
    }
}
