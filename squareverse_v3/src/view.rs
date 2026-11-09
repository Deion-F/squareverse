//! Joining the views (phase 6): picking a galaxy or a particle with the mouse, following it and zooming to it, the
//! panel about what is selected, the galaxy marks drawn when zoomed out, and the speed the zoom suggests. All of it
//! only reads the sim (the finder's list, and `Sim::pick` / `Sim::track_id`), so looking changes nothing in the
//! physics.

use egui::{Align2, Color32, RichText, Stroke};

use crate::fixed::Fixed2;
use crate::render::Camera;
use crate::sim::init::{Kind, SOLAR, binary_of};
use crate::sim::{Galaxy, Sim, Tracked};

#[derive(Clone, Debug, Default)]
pub enum Selected {
    #[default]
    None,
    /// A galaxy from the finder: where it was and how it moved when last found (sim Myr).
    Galaxy { galaxy: Galaxy, found_myr: f64 },
    /// A particle, by id (the sim follows it: `Sim::track_id`).
    Particle(u32),
}

pub struct ViewState {
    pub selected: Selected,
    /// The camera keeps the selection in the middle (dragging the view stops it).
    pub follow: bool,
    /// Zooming smoothly towards this many pixels a pc.
    pub zoom_to: Option<f64>,
    /// Where the left button went down (a click is a press and release in about the same place).
    pub press: Option<(f64, f64)>,
    /// The star system view is open (phase 7), and its clock and zoom.
    pub system_open: bool,
    pub sys: crate::system::SystemView,
    /// The speed the zoom suggests, Myr/s, smoothed.
    pub suggested_myr_s: f64,
    /// When the finder's list was last taken in.
    seen_galaxies_myr: f64,
}

impl Default for ViewState {
    fn default() -> Self {
        Self {
            selected: Selected::None,
            follow: false,
            zoom_to: None,
            press: None,
            system_open: false,
            sys: Default::default(),
            suggested_myr_s: 10.0,
            seen_galaxies_myr: -1.0,
        }
    }
}

/// The speed a view suggests: the time it takes things to cross a fraction of it. About 10 Myr/s on a whole galaxy
/// (a rotation in ~20 s), ~0.5 on a galaxy's centre, ~1,000 on the whole universe. `half_width_pc` is comoving.
pub fn suggested_speed(half_width_pc: f64) -> f64 {
    (half_width_pc / 1_500.0).clamp(0.02, 2_000.0)
}

/// Zoom (px / pc) that fits a radius (pc) in a viewport.
pub fn fit(radius_pc: f64, viewport: (f64, f64)) -> f64 {
    viewport.0.min(viewport.1) / (2.4 * radius_pc.max(1e-6))
}

impl ViewState {
    pub fn clear(&mut self, sim: &mut Sim) {
        self.selected = Selected::None;
        self.follow = false;
        self.zoom_to = None;
        self.system_open = false;
        sim.track_id = None;
        sim.tracked = None;
    }

    /// A click at `px`: the nearest galaxy mark within reach, else a particle (asked of the GPU; the answer comes
    /// in `frame`).
    pub fn click(&mut self, sim: &mut Sim, camera: &Camera, px: (f64, f64), viewport: (f64, f64), with_dm: bool, rings: bool) {
        let a = sim.scale_factor();
        let mut best: Option<(f64, &Galaxy)> = None;
        let candidates = if rings { ringed(sim) } else { Vec::new() };
        for g in candidates {
            let (sx, sy) = screen_of(camera, g.center_pc, viewport, sim.cfg.box_pc);
            let reach = (g.radius_pc / a * camera.px_per_pc).max(10.0);
            let d = (sx - px.0).hypot(sy - px.1);
            // only marks too small to click particles in
            if d < reach && reach < 60.0 && best.is_none_or(|(bd, _)| d < bd) {
                best = Some((d, g));
            }
        }
        if let Some((_, g)) = best {
            let g = g.clone();
            sim.track_id = None;
            self.zoom_to = Some(fit(3.0 * g.radius_pc.max(1_000.0) / a, viewport));
            self.selected = Selected::Galaxy { found_myr: sim.galaxies_myr, galaxy: g };
            self.follow = true;
            return;
        }
        let w = camera.world_at(px, viewport);
        let box_pc = sim.cfg.box_pc;
        sim.pick(Fixed2::from_pc(w.0, w.1, box_pc), 10.0 / camera.px_per_pc * a, with_dm);
    }

    /// Each frame: takes in a pick's answer and new finder lists, and moves the camera (follow, zoom).
    pub fn frame(&mut self, sim: &mut Sim, camera: &mut Camera, viewport: (f64, f64), display_myr: f64) {
        let a = sim.scale_factor();
        if let Some(answer) = sim.picked.take() {
            match answer {
                Some(id) => {
                    self.selected = Selected::Particle(id);
                    sim.track_id = Some(id);
                    self.follow = true;
                    // close enough to see its neighbourhood (2 kpc across), unless already closer
                    let close = fit(1_000.0 / a, viewport);
                    self.zoom_to = (camera.px_per_pc < close).then_some(close);
                }
                None => self.clear(sim),
            }
        }
        // a new list from the finder: find the selected galaxy in it again (the nearest to where it should be)
        if sim.galaxies_myr != self.seen_galaxies_myr {
            self.seen_galaxies_myr = sim.galaxies_myr;
            if let Selected::Galaxy { galaxy, found_myr } = &self.selected {
                let expect = moved(galaxy, sim.galaxies_myr - found_myr, a, sim.cfg.box_pc);
                let reach = (3.0 * galaxy.radius_pc).max(20_000.0) / a;
                let again = sim
                    .galaxies
                    .iter()
                    .map(|g| (dist(g.center_pc, expect, sim.cfg.box_pc), g))
                    .filter(|(d, _)| *d < reach)
                    .min_by(|x, y| x.0.total_cmp(&y.0));
                if let Some((_, g)) = again {
                    self.selected = Selected::Galaxy { galaxy: g.clone(), found_myr: sim.galaxies_myr };
                }
            }
        }
        if self.follow
            && let Some(c) = self.center(sim, display_myr)
        {
            // jump straight there when far, glide when near
            let d = (c.0 - camera.center_pc.0).hypot(c.1 - camera.center_pc.1) * camera.px_per_pc;
            let k = if d > 200.0 { 1.0 } else { 0.35 };
            camera.center_pc.0 += k * (c.0 - camera.center_pc.0);
            camera.center_pc.1 += k * (c.1 - camera.center_pc.1);
        }
        if let Some(z) = self.zoom_to {
            let ratio = z / camera.px_per_pc;
            camera.px_per_pc *= ratio.powf(0.12);
            if (ratio.ln()).abs() < 0.01 {
                camera.px_per_pc = z;
                self.zoom_to = None;
            }
        }
        let half = viewport.0.max(viewport.1) / 2.0 / camera.px_per_pc;
        let want = suggested_speed(half);
        self.suggested_myr_s *= (want / self.suggested_myr_s).powf(0.1);
    }

    /// Where the selection is now (comoving pc from the box's origin).
    pub fn center(&self, sim: &Sim, display_myr: f64) -> Option<(f64, f64)> {
        let a = sim.scale_factor();
        match &self.selected {
            Selected::None => None,
            Selected::Galaxy { galaxy, found_myr } => Some(moved(galaxy, display_myr - found_myr, a, sim.cfg.box_pc)),
            Selected::Particle(_) => sim.tracked.map(|t| {
                let (x, y) = t.pos.to_pc(sim.cfg.box_pc);
                let dt = display_myr - sim.pos_time_myr();
                (x + t.vel[0] as f64 * dt / a, y + t.vel[1] as f64 * dt / a)
            }),
        }
    }
}

fn moved(g: &Galaxy, dt: f64, a: f64, box_pc: f64) -> (f64, f64) {
    Fixed2::from_pc(g.center_pc.0, g.center_pc.1, box_pc).offset_pc(g.velocity[0] * dt / a, g.velocity[1] * dt / a, box_pc).to_pc(box_pc)
}

fn dist(p: (f64, f64), q: (f64, f64), box_pc: f64) -> f64 {
    let (dx, dy) = Fixed2::from_pc(p.0, p.1, box_pc).delta_pc(Fixed2::from_pc(q.0, q.1, box_pc), box_pc);
    dx.hypot(dy)
}

/// Screen pixel of a point in the box, taking the nearest copy across the periodic edge.
pub fn screen_of(camera: &Camera, p: (f64, f64), viewport: (f64, f64), box_pc: f64) -> (f64, f64) {
    // the particles are drawn at their copy nearest the camera (squares.wgsl), so the marks must be too
    let wrap = |d: f64| d - box_pc * (d / box_pc).round();
    let (dx, dy) = (wrap(p.0 - camera.center_pc.0), wrap(p.1 - camera.center_pc.1));
    (viewport.0 / 2.0 + dx * camera.px_per_pc, viewport.1 / 2.0 - dy * camera.px_per_pc)
}

/// The galaxies that get a ring: those with stars (the finder's halos without any are left out), at most
/// `MAX_RINGS`, the most stars first.
pub const MAX_RINGS: usize = 300;

pub fn ringed(sim: &Sim) -> Vec<&Galaxy> {
    let mut v: Vec<&Galaxy> = sim.galaxies.iter().filter(|g| g.stars > 0.0).collect();
    v.sort_by(|a, b| b.stars.total_cmp(&a.stars));
    v.truncate(MAX_RINGS);
    v
}

/// Circles round the galaxies the finder found (`ringed`), while they are small on screen (they fade out as you zoom
/// in), the selected one brighter. Off with the menu's "Galaxy rings" (O).
pub fn draw_marks(ctx: &egui::Context, camera: &Camera, viewport: (f64, f64), sim: &Sim, view: &ViewState, ppp: f32, show: bool) {
    if sim.galaxies.is_empty() || !show {
        return;
    }
    let a = sim.scale_factor();
    let painter = ctx.layer_painter(egui::LayerId::background());
    let selected = match &view.selected {
        Selected::Galaxy { galaxy, .. } => Some(galaxy.center_pc),
        _ => None,
    };
    for g in ringed(sim) {
        let r_px = (g.radius_pc / a * camera.px_per_pc).max(4.0);
        let fade = (1.0 - (r_px - 30.0) / 60.0).clamp(0.0, 1.0);
        let is_sel = selected.is_some_and(|c| dist(c, g.center_pc, sim.cfg.box_pc) < 1.0);
        if fade <= 0.0 && !is_sel {
            continue;
        }
        let (x, y) = screen_of(camera, g.center_pc, viewport, sim.cfg.box_pc);
        if x < -50.0 || y < -50.0 || x > viewport.0 + 50.0 || y > viewport.1 + 50.0 {
            continue;
        }
        let alpha = if is_sel { 200 } else { (90.0 * fade) as u8 };
        let colour = if is_sel { Color32::from_rgba_unmultiplied(255, 220, 120, alpha) } else { Color32::from_rgba_unmultiplied(150, 190, 255, alpha) };
        let at = egui::pos2(x as f32 / ppp, y as f32 / ppp);
        painter.circle_stroke(at, (1.4 * r_px) as f32 / ppp + 3.0, Stroke::new(1.0, colour));
    }
}

fn kind_name(k: u32) -> &'static str {
    match k {
        k if k == Kind::Star as u32 => "Star",
        k if k == Kind::DarkMatter as u32 => "Dark matter",
        k if k == Kind::Well as u32 => "Super well",
        k if k == Kind::WhiteDwarf as u32 => "White dwarf",
        k if k == Kind::NeutronStar as u32 => "Neutron star",
        k if k == Kind::BlackHole as u32 => "Black hole",
        k if k == Kind::Gas as u32 => "Gas",
        _ => "Gone",
    }
}

fn mass(m: f64) -> String {
    if m >= 1e4 { format!("{m:.2e} Msun") } else { format!("{m:.3} Msun") }
}

/// [Fe/H] from the iron mass fraction.
pub fn fe_h(chem: [f32; 4]) -> f64 {
    ((chem[3] as f64).max(1e-12) / SOLAR[3] as f64).log10()
}

/// What the selection panel asks for.
#[derive(Default)]
pub struct PanelActions {
    pub clear: bool,
    pub zoom: bool,
}

/// The panel about the selection (top left, under the status line).
pub fn panel(ctx: &egui::Context, view: &mut ViewState, sim: &Sim, now_myr: f64) -> PanelActions {
    let mut act = PanelActions::default();
    if matches!(view.selected, Selected::None) {
        return act;
    }
    egui::Window::new("Selected").anchor(Align2::LEFT_TOP, [8.0, 30.0]).collapsible(true).resizable(false).default_width(260.0).show(ctx, |ui| {
        match &view.selected {
            Selected::Galaxy { galaxy: g, .. } => {
                ui.label(RichText::new(if g.dark > 0.0 { "Halo (galaxy finder)" } else { "Galaxy (galaxy finder)" }).strong());
                ui.label(format!("{} particles, {}", crate::ui::group(g.members as u64), mass(g.mass)));
                ui.label(format!("stars {}   gas {}", mass(g.stars), mass(g.gas)));
                if g.dark > 0.0 {
                    ui.label(format!("dark matter {}", mass(g.dark)));
                }
                if g.wells > 0.0 {
                    ui.label(format!("super wells {}", mass(g.wells)));
                }
                ui.label(format!("size (rms) {:.1} kpc, moving {:.0} km/s", g.radius_pc / 1000.0, g.velocity[0].hypot(g.velocity[1]) / 1.0227));
            }
            Selected::Particle(id) => match sim.tracked.filter(|t| t.id == *id) {
                None => {
                    ui.label(format!("particle {id}: looking..."));
                }
                Some(t) => particle_info(ui, &t, now_myr, sim.cfg.cosmology.is_some()),
            },
            Selected::None => {}
        }
        ui.horizontal(|ui| {
            ui.checkbox(&mut view.follow, "Follow");
            if ui.button("Zoom to it").clicked() {
                act.zoom = true;
            }
            if let Selected::Particle(_) = view.selected
                && sim.tracked.is_some_and(|t| [Kind::Star as u32, Kind::WhiteDwarf as u32, Kind::NeutronStar as u32, Kind::BlackHole as u32].contains(&t.kind))
                && ui.button("Star system").clicked()
            {
                view.system_open = true;
            }
            if ui.button("Clear (Esc)").clicked() {
                act.clear = true;
            }
        });
    });
    act
}

fn particle_info(ui: &mut egui::Ui, t: &Tracked, now_myr: f64, universe: bool) {
    ui.label(RichText::new(format!("{} #{}", kind_name(t.kind), t.id)).strong());
    let k = t.kind;
    if k == Kind::Gas as u32 {
        let temp = t.star[0];
        ui.label(format!("{} at {:.3e} K", mass(t.mass as f64), temp));
        ui.label(format!("surface density {:.2} Msun/pc², kernel reach {:.0} pc", t.gas[1], t.gas[2]));
        ui.label(format!("metallicity {:.3} solar", t.gas[3]));
        return;
    }
    if k == Kind::DarkMatter as u32 || k == Kind::Well as u32 {
        ui.label(mass(t.mass as f64));
        return;
    }
    let star_mass = t.about[1];
    let population = (t.mass - star_mass).abs() > 0.01 * t.mass.max(1e-6) && k == Kind::Star as u32;
    if population {
        ui.label(format!("a population of stars, {}", mass(t.mass as f64)));
        ui.label(format!("drawn as one of its stars: {star_mass:.2} Msun"));
    } else {
        ui.label(mass(t.mass as f64));
        if star_mass > 0.0 && k != Kind::Star as u32 {
            ui.label(format!("born as a {star_mass:.2} Msun star"));
        }
    }
    if t.star[1] > 0.0 {
        ui.label(format!("surface {:.0} K, {:.3e} Lsun", t.star[0], t.star[1]));
    }
    let age = now_myr - t.about[0] as f64;
    if !universe || age > 0.0 {
        ui.label(format!("age {:.0} Myr, [Fe/H] {:+.2}", age, fe_h(t.chem)));
    }
    if star_mass > 0.0 {
        let b = binary_of(t.id, star_mass);
        if b[3] > 0.0 {
            ui.label(format!("born with a companion: q {:.2}, period 10^{:.1} days, e {:.2}", b[0], b[1], b[2]));
        } else {
            ui.label("born single");
        }
    }
}
