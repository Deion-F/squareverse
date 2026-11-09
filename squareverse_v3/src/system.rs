//! The star system view (phase 7): a star's planets, worked out from what it was born with rather than simulated or
//! stored, so a star shows the same system every time it is looked at, and it costs nothing until then.
//!
//! From the star's id (the dice), its mass at birth, the five element groups it was born with, its binary companion
//! (`init::binary_of`) and what it has become:
//! - **rocky planets** need Mg/Si: about 3 a star at solar Mg/Si (rising as its square root), inside the snow line
//!   (2.7 AU x M), spaced by factors 1.4 - 2.2;
//! - **gas giants** need iron-rich gas: chance 3% x 10^(2 [Fe/H]) x M (Fischer & Valenti 2005), at most 60%, from
//!   the snow line out; one in ten has migrated in as a hot Jupiter (sweeping the inner rocky planets away);
//! - **ice giants** need C/N/O: about 1.2 a star at solar C/N/O, beyond the giants;
//! - **a companion** clears the orbits between 0.3 and 3 of its separation (only orbits round one star well inside
//!   it, or round both well outside it, last);
//! - **after the star's life**: a giant swallows the planets inside its growing radius; round a white dwarf the
//!   survivors' orbits have widened by the mass the star lost; a supernova unbinds them (a rare small "pulsar
//!   planet" may form again); a black hole keeps none.
//!
//! The window draws the orbits (Kepler ellipses, the star at a focus) with the planets moving on them at years per
//! second, while the universe's clock runs at its own pace.

use std::time::Instant;

use egui::{Color32, RichText, Stroke};

use crate::rng::Rng;
use crate::sim::init::{Kind, SOLAR, binary_of, lifetime, main_sequence};
use crate::view::{Selected, ViewState, fe_h};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlanetKind {
    Rocky,
    IceGiant,
    GasGiant,
}

#[derive(Clone, Copy, Debug)]
pub struct Planet {
    pub kind: PlanetKind,
    /// Semi-major axis (AU), eccentricity, mass (Earth masses), and where on its orbit it is at time 0 (radians).
    pub a_au: f64,
    pub e: f64,
    pub mass_earth: f64,
    pub phase: f64,
}

#[derive(Clone, Copy, Debug)]
pub struct Companion {
    pub mass: f64,
    pub a_au: f64,
    pub e: f64,
}

#[derive(Clone, Debug)]
pub struct System {
    /// The star's mass at birth and now (Msun).
    pub birth_mass: f64,
    pub mass: f64,
    pub companion: Option<Companion>,
    pub planets: Vec<Planet>,
    /// What happened to the system, if anything.
    pub note: Option<&'static str>,
    pub snow_line_au: f64,
    /// The habitable zone (AU), from the star's luminosity on the main sequence; None after it.
    pub habitable_au: Option<(f64, f64)>,
}

fn poisson(rng: &mut Rng, mean: f64) -> u32 {
    let limit = (-mean).exp();
    let (mut k, mut p) = (0u32, rng.f64());
    while p > limit && k < 12 {
        k += 1;
        p *= rng.f64();
    }
    k
}

fn log_uniform(rng: &mut Rng, lo: f64, hi: f64) -> f64 {
    lo * (hi / lo).powf(rng.f64())
}

/// The system of a star: its id, its mass at birth (Msun), its elements at birth (He, C/N/O, Mg/Si, Fe mass
/// fractions), what it is now (`Kind` as u32), its mass now and its age (Myr).
pub fn system_of(id: u32, birth_mass: f64, chem: [f32; 4], kind: u32, mass_now: f64, age_myr: f64) -> System {
    let m = birth_mass.max(0.08);
    let mut rng = Rng::new(0x5157_e3a7_0000_0000 ^ id as u64);
    let feh = fe_h(chem);
    let mgsi = (chem[2] as f64 / SOLAR[2] as f64).max(0.0);
    let cno = (chem[1] as f64 / SOLAR[1] as f64).max(0.0);
    let snow = 2.7 * m;
    let massive = m > 8.0;
    let mut planets = Vec::new();

    // rocky planets inside the snow line
    let rocky = poisson(&mut rng, if massive { 0.3 } else { 3.0 * mgsi.min(2.0).sqrt() * m.clamp(0.1, 1.5).powf(0.3) });
    let mut a = log_uniform(&mut rng, 0.05, 0.4) * m.cbrt();
    for _ in 0..rocky {
        if a > snow {
            break;
        }
        let top = (10.0 * mgsi).clamp(0.1, 10.0);
        planets.push(Planet { kind: PlanetKind::Rocky, a_au: a, e: (rng.normal() * 0.04).abs().min(0.3), mass_earth: log_uniform(&mut rng, 0.05, top), phase: rng.f64() * std::f64::consts::TAU });
        a *= 1.4 + 0.8 * rng.f64();
    }
    // gas giants from the snow line out
    let p_giant = (0.03 * 10f64.powf(2.0 * feh) * m).min(0.6);
    let mut outer = snow;
    if !massive && rng.f64() < p_giant {
        let count = 1 + (rng.f64() < 0.35) as u32 + (rng.f64() < 0.15) as u32;
        let mut ag = snow * (1.0 + 2.0 * rng.f64());
        for k in 0..count {
            let mass = log_uniform(&mut rng, 30.0, 3_000.0) * m.min(2.0);
            let e = (rng.normal() * 0.15).abs().min(0.7);
            if k == 0 && rng.f64() < 0.1 {
                // a hot Jupiter: it migrated in, and the rocky planets in its way were scattered or eaten
                let hot = log_uniform(&mut rng, 0.03, 0.1);
                planets.retain(|p| p.a_au > 4.0 * hot && p.a_au > 0.3);
                planets.push(Planet { kind: PlanetKind::GasGiant, a_au: hot, e: 0.01, mass_earth: mass, phase: rng.f64() * std::f64::consts::TAU });
                continue;
            }
            planets.push(Planet { kind: PlanetKind::GasGiant, a_au: ag, e, mass_earth: mass, phase: rng.f64() * std::f64::consts::TAU });
            outer = ag;
            ag *= 1.6 + 1.2 * rng.f64();
        }
    }
    // ice giants beyond them
    let ice = if massive { 0 } else { poisson(&mut rng, 1.2 * cno.min(2.0).powf(0.7)) };
    let mut ai = outer * (1.6 + 1.0 * rng.f64());
    for _ in 0..ice {
        planets.push(Planet { kind: PlanetKind::IceGiant, a_au: ai, e: (rng.normal() * 0.05).abs().min(0.3), mass_earth: log_uniform(&mut rng, 8.0, 25.0), phase: rng.f64() * std::f64::consts::TAU });
        ai *= 1.5 + 0.8 * rng.f64();
    }

    // the companion clears the orbits it would make unstable
    let b = binary_of(id, birth_mass as f32);
    let companion = (b[3] > 0.0).then(|| {
        let mc = b[0] as f64 * m;
        let p_yr = 10f64.powf(b[1] as f64) / 365.25;
        Companion { mass: mc, a_au: (p_yr * p_yr * (m + mc)).cbrt(), e: b[2] as f64 }
    });
    if let Some(c) = companion {
        planets.retain(|p| p.a_au < 0.3 * c.a_au * (1.0 - c.e) || p.a_au > 3.0 * c.a_au * (1.0 + c.e));
    }

    // what the star's life has done since
    let life = lifetime(m);
    let mut note = None;
    let mut habitable = None;
    if kind == Kind::Star as u32 {
        let f = age_myr / life;
        if f > 0.9 {
            // a giant: its radius grows to ~1 AU x M^0.7 by the end
            let r = (f - 0.9) / 0.1 * m.powf(0.7);
            let before = planets.len();
            planets.retain(|p| p.a_au * (1.0 - p.e) > r);
            if planets.len() < before {
                note = Some("The star has swollen into a giant and swallowed its inner planets.");
            }
        } else {
            let l = main_sequence(m).1;
            habitable = Some((0.95 * l.sqrt(), 1.67 * l.sqrt()));
        }
    } else if kind == Kind::WhiteDwarf as u32 {
        let reach = 1.5 * m.powf(0.7);
        planets.retain(|p| p.a_au * (1.0 - p.e) > reach);
        let widen = m / mass_now.max(0.1);
        for p in &mut planets {
            p.a_au *= widen;
        }
        note = Some("A white dwarf: its giant phase swallowed the inner planets; the rest drifted out as it lost mass.");
    } else if kind == Kind::NeutronStar as u32 {
        planets.clear();
        if rng.f64() < 0.02 {
            planets.push(Planet { kind: PlanetKind::Rocky, a_au: log_uniform(&mut rng, 0.2, 0.5), e: 0.0, mass_earth: log_uniform(&mut rng, 0.02, 4.0), phase: rng.f64() * std::f64::consts::TAU });
            note = Some("A neutron star: the supernova scattered its planets, and a small one formed again from the debris.");
        } else {
            note = Some("A neutron star: the supernova scattered its planets.");
        }
    } else if kind == Kind::BlackHole as u32 || kind == Kind::Well as u32 {
        planets.clear();
        note = Some("A black hole: nothing of its planets is left.");
    }
    planets.sort_by(|a, b| a.a_au.total_cmp(&b.a_au));
    System { birth_mass: m, mass: mass_now, companion, planets, note, snow_line_au: snow, habitable_au: habitable }
}

/// Orbital period, years, round a central mass (Msun).
pub fn period_yr(a_au: f64, central: f64) -> f64 {
    (a_au.powi(3) / central.max(1e-3)).sqrt()
}

/// Position on a Kepler ellipse (AU, the focus at the origin) after `t` years.
pub fn orbit_at(a: f64, e: f64, phase: f64, period: f64, t: f64) -> (f64, f64) {
    let mean = (phase + std::f64::consts::TAU * t / period.max(1e-9)).rem_euclid(std::f64::consts::TAU);
    let mut ecc = mean;
    for _ in 0..8 {
        ecc -= (ecc - e * ecc.sin() - mean) / (1.0 - e * ecc.cos());
    }
    (a * (ecc.cos() - e), a * (1.0 - e * e).sqrt() * ecc.sin())
}

/// The view's own clock and zoom.
pub struct SystemView {
    pub years: f64,
    pub years_per_s: f64,
    pub zoom: f64,
    last: Option<Instant>,
    for_id: Option<u32>,
}

impl Default for SystemView {
    fn default() -> Self {
        Self { years: 0.0, years_per_s: 1.0, zoom: 1.0, last: None, for_id: None }
    }
}

fn blackbody(t: f64) -> Color32 {
    // Tanner Helland's fit, as in squares.wgsl, in sRGB
    let x = t.clamp(1000.0, 40000.0) / 100.0;
    let (r, g, b) = if x <= 66.0 {
        (255.0, 99.47 * x.ln() - 161.12, if x <= 19.0 { 0.0 } else { 138.52 * (x - 10.0).ln() - 305.04 })
    } else {
        (329.7 * (x - 60.0).powf(-0.1332), 288.12 * (x - 60.0).powf(-0.0755), 255.0)
    };
    Color32::from_rgb(r.clamp(0.0, 255.0) as u8, g.clamp(0.0, 255.0) as u8, b.clamp(0.0, 255.0) as u8)
}

fn kind_label(k: PlanetKind) -> &'static str {
    match k {
        PlanetKind::Rocky => "rocky",
        PlanetKind::IceGiant => "ice giant",
        PlanetKind::GasGiant => "gas giant",
    }
}

/// The star system window, for the selected (followed) star, when asked for from the selection panel.
pub fn window(ctx: &egui::Context, view: &mut ViewState, sim: &crate::sim::Sim, now_myr: f64) {
    if !view.system_open {
        return;
    }
    let Selected::Particle(id) = view.selected else { return };
    let Some(t) = sim.tracked.filter(|t| t.id == id) else { return };
    let birth = if t.about[1] > 0.0 { t.about[1] as f64 } else { t.mass as f64 };
    let sys = system_of(id, birth, t.chem, t.kind, t.mass as f64, now_myr - t.about[0] as f64);
    let sv = &mut view.sys;
    if sv.for_id != Some(id) {
        *sv = SystemView { for_id: Some(id), ..SystemView::default() };
    }
    let now = Instant::now();
    if let Some(last) = sv.last {
        sv.years += (now - last).as_secs_f64() * sv.years_per_s;
    }
    sv.last = Some(now);
    let mut open = true;
    egui::Window::new(format!("Star system #{id}")).open(&mut open).default_size([520.0, 600.0]).show(ctx, |ui| {
        ui.label(format!(
            "{:.2} Msun at birth{}, [Fe/H] {:+.2}; snow line {:.1} AU",
            sys.birth_mass,
            if (sys.mass - sys.birth_mass).abs() > 1e-3 { format!(", {:.2} now", sys.mass) } else { String::new() },
            fe_h(t.chem),
            sys.snow_line_au
        ));
        if let Some(c) = sys.companion {
            ui.label(format!("companion {:.2} Msun at {:.3} AU (e {:.2})", c.mass, c.a_au, c.e));
        }
        if let Some(n) = sys.note {
            ui.label(RichText::new(n).italics());
        }
        ui.horizontal(|ui| {
            ui.label("Years a second");
            ui.add(egui::Slider::new(&mut sv.years_per_s, 0.01..=1000.0).logarithmic(true));
            ui.label("Zoom");
            ui.add(egui::Slider::new(&mut sv.zoom, 0.05..=50.0).logarithmic(true));
        });
        ui.label(RichText::new(format!("{:.2} years", sv.years)).weak());
        // the picture
        let outer = sys
            .planets
            .iter()
            .map(|p| p.a_au * (1.0 + p.e))
            .chain(sys.companion.map(|c| c.a_au * (1.0 + c.e)))
            .fold(0.5f64, f64::max);
        let (resp, painter) = ui.allocate_painter(egui::vec2(ui.available_width().max(300.0), 380.0), egui::Sense::hover());
        let rect = resp.rect;
        painter.rect_filled(rect, 4.0, Color32::from_rgb(4, 4, 10));
        let mid = rect.center();
        let scale = sv.zoom * (rect.width().min(rect.height()) as f64 * 0.45) / outer;
        let to = |x: f64, y: f64| egui::pos2(mid.x + (x * scale) as f32, mid.y - (y * scale) as f32);
        let central = sys.mass + sys.companion.map_or(0.0, |c| c.mass);
        // the habitable zone
        if let Some((lo, hi)) = sys.habitable_au {
            painter.circle_stroke(mid, (0.5 * (lo + hi) * scale) as f32, Stroke::new(((hi - lo) * scale) as f32, Color32::from_rgba_unmultiplied(40, 120, 60, 40)));
        }
        let star_px = (3.0 + 2.0 * (t.star[1].max(1e-4) as f64).log10().clamp(-3.0, 4.0) / 2.0).max(2.0) as f32;
        let colour = if t.kind == Kind::WhiteDwarf as u32 { Color32::from_rgb(200, 210, 255) } else { blackbody(t.star[0] as f64) };
        match sys.companion {
            Some(c) => {
                let p = period_yr(c.a_au, sys.mass + c.mass);
                let (x, y) = orbit_at(c.a_au, c.e, 0.0, p, sv.years);
                let q = c.mass / (sys.mass + c.mass);
                painter.circle_filled(to(-q * x, -q * y), star_px, colour);
                let (tc, lc) = main_sequence(c.mass);
                let cpx = (3.0 + 2.0 * lc.max(1e-4).log10().clamp(-3.0, 4.0) / 2.0).max(2.0) as f32;
                painter.circle_filled(to((1.0 - q) * x, (1.0 - q) * y), cpx, blackbody(tc));
            }
            None => {
                painter.circle_filled(mid, star_px, colour);
            }
        }
        for p in &sys.planets {
            // the orbit
            let pts: Vec<egui::Pos2> = (0..=96)
                .map(|k| {
                    let ecc = k as f64 / 96.0 * std::f64::consts::TAU;
                    to(p.a_au * (ecc.cos() - p.e), p.a_au * (1.0 - p.e * p.e).sqrt() * ecc.sin())
                })
                .collect();
            painter.add(egui::Shape::line(pts, Stroke::new(1.0, Color32::from_gray(45))));
            let (x, y) = orbit_at(p.a_au, p.e, p.phase, period_yr(p.a_au, central), sv.years);
            let (c, r) = match p.kind {
                PlanetKind::Rocky => (Color32::from_rgb(170, 130, 100), 2.0 + p.mass_earth.cbrt() as f32),
                PlanetKind::IceGiant => (Color32::from_rgb(110, 190, 220), 4.0),
                PlanetKind::GasGiant => (Color32::from_rgb(220, 180, 130), 5.0 + (p.mass_earth / 300.0).cbrt() as f32),
            };
            painter.rect_filled(egui::Rect::from_center_size(to(x, y), egui::vec2(r, r)), 0.0, c);
        }
        egui::Grid::new("planets").striped(true).show(ui, |ui| {
            ui.label(RichText::new("planet").strong());
            ui.label(RichText::new("a (AU)").strong());
            ui.label(RichText::new("year").strong());
            ui.label(RichText::new("mass (Earths)").strong());
            ui.label(RichText::new("e").strong());
            ui.end_row();
            for p in &sys.planets {
                let hz = sys.habitable_au.is_some_and(|(lo, hi)| p.a_au > lo && p.a_au < hi);
                ui.label(format!("{}{}", kind_label(p.kind), if hz { " (habitable zone)" } else { "" }));
                ui.label(format!("{:.3}", p.a_au));
                let yr = period_yr(p.a_au, central);
                ui.label(if yr < 1.0 { format!("{:.0} days", yr * 365.25) } else { format!("{yr:.1} years") });
                ui.label(format!("{:.2}", p.mass_earth));
                ui.label(format!("{:.2}", p.e));
                ui.end_row();
            }
        });
        if sys.planets.is_empty() {
            ui.label("No planets.");
        }
    });
    if !open {
        view.system_open = false;
    }
    ctx.request_repaint();
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sim::init::elements;

    #[test]
    fn the_same_star_has_the_same_planets() {
        let a = system_of(12345, 1.0, elements(1.0), Kind::Star as u32, 1.0, 4600.0);
        let b = system_of(12345, 1.0, elements(1.0), Kind::Star as u32, 1.0, 4600.0);
        assert_eq!(a.planets.len(), b.planets.len());
        for (p, q) in a.planets.iter().zip(&b.planets) {
            assert_eq!(p.a_au, q.a_au);
            assert_eq!(p.mass_earth, q.mass_earth);
        }
    }

    #[test]
    fn metals_make_giants_and_rock() {
        let count = |z: f64, k: PlanetKind| -> usize {
            (0..4000u32).map(|id| system_of(id, 1.0, elements(z), Kind::Star as u32, 1.0, 1000.0).planets.iter().filter(|p| p.kind == k).count()).sum()
        };
        let (rich, poor) = (count(2.0, PlanetKind::GasGiant), count(0.3, PlanetKind::GasGiant));
        eprintln!("gas giants per 4000 stars: [Fe/H] +0.3 {rich}, -0.5 {poor}");
        assert!(rich > 3 * poor.max(1));
        assert!(count(1.0, PlanetKind::Rocky) > 4 * count(0.01, PlanetKind::Rocky));
        // primordial gas makes no planets at all
        assert_eq!((0..500u32).map(|id| system_of(id, 1.0, elements(0.0), Kind::Star as u32, 1.0, 100.0).planets.len()).sum::<usize>(), 0);
    }

    #[test]
    fn a_white_dwarf_keeps_only_widened_outer_planets() {
        for id in 0..300u32 {
            let young = system_of(id, 2.0, elements(1.5), Kind::Star as u32, 2.0, 10.0);
            let wd = system_of(id, 2.0, elements(1.5), Kind::WhiteDwarf as u32, 0.61, 2000.0);
            assert!(wd.planets.len() <= young.planets.len());
            for p in &wd.planets {
                assert!(p.a_au > 1.5 * 2f64.powf(0.7) * 2.0 / 0.61 * (1.0 - p.e) * 0.99);
            }
            let ns = system_of(id, 15.0, elements(1.5), Kind::NeutronStar as u32, 1.4, 20.0);
            assert!(ns.planets.len() <= 1);
        }
    }

    #[test]
    fn kepler_orbit_comes_back() {
        let (x0, y0) = orbit_at(1.0, 0.3, 0.5, 1.0, 0.0);
        let (x1, y1) = orbit_at(1.0, 0.3, 0.5, 1.0, 1.0);
        assert!((x0 - x1).abs() < 1e-9 && (y0 - y1).abs() < 1e-9);
        // perihelion at a (1 - e)
        let (xp, yp) = orbit_at(2.0, 0.5, 0.0, 1.0, 0.0);
        assert!(((xp * xp + yp * yp).sqrt() - 1.0).abs() < 1e-9);
    }
}
