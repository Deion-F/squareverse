//! The expanding universe (phase 5): a flat universe of matter and a cosmological constant, a(t) in closed form, and
//! the linear growth of structure in this sim's 2D sheet, which the early-universe start (`init::universe`) uses to
//! set its first displacements.
//!
//! The 2D universe is a sheet standing for a slab `sheet_pc` (comoving) thick: its surface density is the mean
//! matter density times that. Gravity falls off as 1/r², so a ripple of wavenumber k in the sheet grows as
//! δ'' + 2H δ' = 2πG Σ k δ (a thin sheet's response) rather than 4πG ρ δ as in 3D: the two agree at k = 2 / sheet,
//! larger ripples grow slower and smaller ones faster. The start is set backwards from a chosen spectrum today
//! through this growth, so the web that forms has the chosen scale.

use serde::Serialize;

use crate::units::{G, KM_S};

#[derive(Clone, Debug, Serialize, serde::Deserialize)]
pub struct Cosmology {
    /// Hubble constant, km/s/Mpc.
    pub h0: f64,
    pub omega_m: f64,
    pub omega_l: f64,
    /// The share of the matter that is gas (baryons).
    pub baryon_share: f64,
    /// Redshift at the start.
    pub z_start: f64,
    /// The 2D sheet stands for a slab this thick, comoving pc.
    pub sheet_pc: f64,
    /// Softening is fixed in comoving pc until the scale factor reaches this, then fixed in physical pc.
    pub soft_comoving_until_a: f64,
    /// A UV background after reionisation keeps thin gas at 10^4 K.
    pub uv_background: bool,
    pub z_reion: f64,
    /// Gas denser than this (hydrogen atoms per cm³) shields itself from the UV background.
    pub self_shield_cm3: f64,
    /// The spectrum today, Δ²(k) = amplitude x² / (1 + x^1.5), x = k / k0, k0 = 2π / `peak_pc`: the variance of
    /// the density per ln k.
    pub amplitude: f64,
    pub peak_pc: f64,
}

impl Default for Cosmology {
    fn default() -> Self {
        Self {
            h0: 70.0,
            omega_m: 0.3,
            omega_l: 0.7,
            baryon_share: 0.16,
            z_start: 30.0,
            sheet_pc: 1_000_000.0,
            soft_comoving_until_a: 0.25,
            uv_background: true,
            z_reion: 8.0,
            self_shield_cm3: 0.01,
            amplitude: 1.5,
            peak_pc: 4_000_000.0,
        }
    }
}

impl Cosmology {
    /// H0 in 1/Myr.
    pub fn h0_per_myr(&self) -> f64 {
        self.h0 * KM_S / 1e6
    }

    /// The critical density today, Msun / pc³.
    pub fn rho_crit(&self) -> f64 {
        3.0 * self.h0_per_myr().powi(2) / (8.0 * std::f64::consts::PI * G)
    }

    /// The sheet's mean surface density of matter (comoving), Msun / pc².
    pub fn sigma_mean(&self) -> f64 {
        self.omega_m * self.rho_crit() * self.sheet_pc
    }

    /// The scale factor at cosmic time t (Myr), as shaders/common.wgsl scale_factor.
    pub fn a_of_t(&self, t: f64) -> f64 {
        (self.omega_m / self.omega_l).powf(1.0 / 3.0) * (1.5 * self.omega_l.sqrt() * self.h0_per_myr() * t.max(1e-3)).sinh().powf(2.0 / 3.0)
    }

    /// Cosmic time (Myr) at scale factor a.
    pub fn t_of_a(&self, a: f64) -> f64 {
        let x = (a.powi(3) * self.omega_l / self.omega_m).sqrt();
        x.asinh() / (1.5 * self.omega_l.sqrt() * self.h0_per_myr())
    }

    /// H(a), 1/Myr.
    pub fn hubble(&self, a: f64) -> f64 {
        self.h0_per_myr() * (self.omega_m / a.powi(3) + self.omega_l).sqrt()
    }

    pub fn a_start(&self) -> f64 {
        1.0 / (1.0 + self.z_start)
    }

    /// The spectrum today at comoving wavenumber k (1/pc): variance per ln k.
    pub fn delta2_today(&self, k: f64) -> f64 {
        let x = k * self.peak_pc / std::f64::consts::TAU;
        self.amplitude * x * x / (1.0 + x.powf(1.5))
    }

    /// Linear growth in the sheet at comoving k (1/pc): (D(a) / D(1), dln D / dln a at a). Integrates
    /// g = dln D / dln a, g' = s - (2 + dln H / dln a) g - g², s = 2πG Σ k / (a³ H²), from deep in matter domination
    /// (where D ∝ a^p, p² + p/2 = s).
    pub fn growth(&self, k: f64, a: f64) -> (f64, f64) {
        let (om, ol) = (self.omega_m, self.omega_l);
        let s_of = |la: f64| {
            let aa = la.exp();
            let e2 = om / aa.powi(3) + ol;
            // 2πG Σ k / a³ over H0² E²; 2πG Σ_mean = 0.75 Ω_m H0² sheet
            0.75 * om * self.sheet_pc * k / aa.powi(3) / e2
        };
        let dlnh = |la: f64| {
            let aa = la.exp();
            -1.5 * om / aa.powi(3) / (om / aa.powi(3) + ol)
        };
        let deriv = |la: f64, g: f64| s_of(la) - (2.0 + dlnh(la)) * g - g * g;
        let la0 = (1e-3f64).ln();
        let s0 = s_of(la0);
        let mut g = (-0.5 + (0.25 + 4.0 * s0).sqrt()) / 2.0;
        let steps = 4000;
        let h = -la0 / steps as f64;
        let la_target = a.ln();
        let (mut ln_d, mut ln_d_at, mut g_at) = (0.0, 0.0, g);
        let mut la = la0;
        for _ in 0..steps {
            if la <= la_target && la + h > la_target {
                // the requested a falls in this step: take the values at its start (h is ~0.002 in ln a)
                ln_d_at = ln_d;
                g_at = g;
            }
            let k1 = deriv(la, g);
            let k2 = deriv(la + 0.5 * h, g + 0.5 * h * k1);
            let k3 = deriv(la + 0.5 * h, g + 0.5 * h * k2);
            let k4 = deriv(la + h, g + h * k3);
            let g1 = g + h / 6.0 * (k1 + 2.0 * k2 + 2.0 * k3 + k4);
            ln_d += 0.5 * h * (g + g1);
            g = g1;
            la += h;
        }
        if la_target >= 0.0 {
            return (1.0, g);
        }
        ((ln_d_at - ln_d).exp(), g_at)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn age_and_growth() {
        let c = Cosmology::default();
        // the age today: 13.47 Gyr for Ω_m 0.3, h 0.7
        let t0 = c.t_of_a(1.0);
        assert!((t0 - 13_470.0).abs() < 100.0, "age {t0}");
        assert!((c.a_of_t(t0) - 1.0).abs() < 1e-6);
        // where the sheet matches 3D (k sheet = 2), growth is ΛCDM's: D(a = 0.1) / D(1) ≈ 0.128 (Ω_m 0.3)
        let (d, f) = c.growth(2.0 / c.sheet_pc, 0.1);
        assert!((d - 0.128).abs() < 0.01, "D {d}");
        assert!((f - 0.99).abs() < 0.03, "f {f}");
        // smaller ripples grow faster
        let (d_small, _) = c.growth(20.0 / c.sheet_pc, 0.1);
        assert!(d_small < d / 10.0);
    }
}
