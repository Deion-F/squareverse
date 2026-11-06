//! The menu (behind the button in the bottom-right corner, or Tab), the status corners and the key list (H).
//! Conventions carried over from v2: an (i) beside each setting explains it, ⏴ ⏵ arrows give fine steps, every
//! setting has a key, rarely needed figures fold away under Advanced.

use egui::{Align2, Color32, RichText, Ui};

/// What the menu changes. The app reads it every frame and acts on the `*_requested` flags.
pub struct UiState {
    pub paused: bool,
    pub steps_per_frame: u32,
    pub fps_target: u32,
    pub brightness: f32,
    pub exposure: f32,
    pub square_px: f32,
    pub menu_open: bool,
    pub help_open: bool,
    /// Particles and seed for the next reset.
    pub particles: u32,
    pub seed: u64,
    pub reset_requested: bool,
    pub view_reset_requested: bool,
    pub fullscreen_requested: bool,
}

impl UiState {
    pub fn new(particles: u32, seed: u64, fps_target: u32) -> Self {
        Self {
            paused: false,
            steps_per_frame: 4,
            fps_target,
            brightness: crate::snapshot::default_look().brightness,
            exposure: crate::snapshot::default_look().exposure,
            square_px: crate::snapshot::default_look().square_px,
            menu_open: false,
            help_open: false,
            particles,
            seed,
            reset_requested: false,
            view_reset_requested: false,
            fullscreen_requested: false,
        }
    }
}

/// Figures shown in the corners and under Advanced.
pub struct Hud {
    pub particles: u32,
    pub sim_time_myr: f64,
    pub dt_myr: f64,
    pub steps_per_s: f64,
    pub fps: f64,
    pub adapter: String,
    pub backend: String,
    pub gpu_ms: Vec<(&'static str, f64)>,
    pub timestamps: bool,
    pub default_particles: u32,
}

pub const KEYS: &[(&str, &str)] = &[
    ("Tab", "open / close the menu"),
    ("H", "this list of keys"),
    ("Space", "pause / run"),
    ("[ / ]", "slower / faster (steps per frame)"),
    ("R", "reset the universe"),
    ("F", "frame-rate target 60 / 30 fps"),
    ("Home", "reset the view"),
    ("F11", "fullscreen"),
    ("Wheel", "zoom at the cursor"),
    ("Drag", "move the view (left or right button)"),
    ("Esc", "close the key list / menu"),
];

fn info(ui: &mut Ui, text: &str) {
    ui.label(RichText::new("(i)").weak()).on_hover_text(text);
}

/// ⏴ value ⏵ with a slider; the arrows step by `step`. (Repeat while held, as in v2: phase 8 menu polish.)
fn stepper(ui: &mut Ui, value: &mut u32, range: std::ops::RangeInclusive<u32>, step: u32) {
    let (lo, hi) = (*range.start(), *range.end());
    if ui.add(egui::Button::new("⏴").small()).clicked() {
        *value = value.saturating_sub(step).max(lo);
    }
    ui.add(egui::Slider::new(value, range).logarithmic(true));
    if ui.add(egui::Button::new("⏵").small()).clicked() {
        *value = (*value + step).min(hi);
    }
}

fn corners(ui: &Ui, hud: &Hud, fps_target: u32) {
    let ctx = ui.ctx();
    let mono = |s: String| RichText::new(s).monospace().color(Color32::from_gray(210));
    egui::Area::new(egui::Id::unique("status")).anchor(Align2::LEFT_TOP, [8.0, 6.0]).interactable(false).show(ctx, |ui| {
        ui.label(mono(format!(
            "{} particles   t = {:.1} Myr   {:.0} steps/s   {:.0} / {} fps",
            group(hud.particles as u64),
            hud.sim_time_myr,
            hud.steps_per_s,
            hud.fps,
            fps_target
        )));
    });
    egui::Area::new(egui::Id::unique("gpu")).anchor(Align2::RIGHT_TOP, [-8.0, 6.0]).interactable(false).show(ctx, |ui| {
        let total: f64 = hud.gpu_ms.iter().map(|(_, ms)| ms).sum();
        let gpu = if hud.timestamps { format!("GPU {total:.2} ms") } else { "GPU time n/a".into() };
        ui.label(mono(format!("{}   {gpu}", hud.adapter)));
    });
}

pub fn group(n: u64) -> String {
    let s = n.to_string();
    let mut out = String::new();
    for (i, c) in s.chars().enumerate() {
        if i > 0 && (s.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    out
}

pub fn show(ui: &mut Ui, st: &mut UiState, hud: &Hud) {
    corners(ui, hud, st.fps_target);
    let ctx = ui.ctx().clone();

    egui::Area::new(egui::Id::unique("menu button")).anchor(Align2::RIGHT_BOTTOM, [-10.0, -10.0]).show(&ctx, |ui| {
        let label = if st.menu_open { "Close menu (Tab)" } else { "Menu (Tab)" };
        if ui.button(label).clicked() {
            st.menu_open = !st.menu_open;
        }
    });

    if st.help_open {
        egui::Window::new("Keys").collapsible(false).resizable(false).anchor(Align2::CENTER_CENTER, [0.0, 0.0]).show(&ctx, |ui| {
            egui::Grid::new("keys").num_columns(2).striped(true).show(ui, |ui| {
                for (k, what) in KEYS {
                    ui.label(RichText::new(*k).strong());
                    ui.label(*what);
                    ui.end_row();
                }
            });
            if ui.button("Close (H)").clicked() {
                st.help_open = false;
            }
        });
    }

    if !st.menu_open {
        return;
    }
    egui::Window::new("Squareverse")
        .anchor(Align2::RIGHT_BOTTOM, [-10.0, -44.0])
        .collapsible(false)
        .resizable(false)
        .default_width(380.0)
        .show(&ctx, |ui| {
            ui.heading("Simulation");
            ui.horizontal(|ui| {
                let label = if st.paused { "Paused (Space)" } else { "Running (Space)" };
                ui.toggle_value(&mut st.paused, label);
                info(ui, "Stops and starts the clock. The view can still be moved and zoomed while paused.");
            });
            ui.horizontal(|ui| {
                ui.label("Speed");
                stepper(ui, &mut st.steps_per_frame, 1..=64, 1);
                info(ui, "Steps the simulation takes each frame ([ and ]). More steps: time runs faster, each frame costs more.");
            });
            ui.label(
                RichText::new(format!(
                    "{:.2} Myr a step, {:.2} Myr a frame",
                    hud.dt_myr,
                    hud.dt_myr * st.steps_per_frame as f64
                ))
                .weak(),
            );
            ui.horizontal(|ui| {
                ui.label("Particles");
                ui.add(egui::DragValue::new(&mut st.particles).range(1_000..=16_000_000).speed(1_000));
                if ui.small_button("default").clicked() {
                    st.particles = hud.default_particles;
                }
                info(ui, &format!(
                    "How many particles the next reset makes. The default ({}) is picked for this GPU so it holds its \
                     frame rate; more costs frame rate.",
                    group(hud.default_particles as u64)
                ));
            });
            ui.horizontal(|ui| {
                ui.label("Seed");
                ui.add(egui::DragValue::new(&mut st.seed));
                info(ui, "The same seed always makes the same universe.");
            });
            if ui.button("Reset (R)").clicked() {
                st.reset_requested = true;
            }

            ui.separator();
            ui.heading("Display");
            ui.horizontal(|ui| {
                ui.label("Frame rate");
                ui.selectable_value(&mut st.fps_target, 60, "60 fps");
                ui.selectable_value(&mut st.fps_target, 30, "30 fps");
                info(ui, "The frame-rate target (F). 30 fps suits weaker machines, such as laptops with integrated graphics.");
            });
            ui.horizontal(|ui| {
                ui.label("Brightness");
                ui.add(egui::Slider::new(&mut st.brightness, 0.005..=5.0).logarithmic(true));
                info(ui, "How much light each star adds. Lower it when many stars fall on one pixel and it washes out.");
            });
            ui.horizontal(|ui| {
                ui.label("Exposure");
                ui.add(egui::Slider::new(&mut st.exposure, 0.05..=20.0).logarithmic(true));
                info(ui, "Brightens or darkens the whole picture after the light is added up.");
            });
            ui.horizontal(|ui| {
                ui.label("Square size");
                ui.add(egui::Slider::new(&mut st.square_px, 1.0..=6.0).step_by(1.0).suffix(" px"));
                info(ui, "How many pixels across each particle is drawn.");
            });
            ui.horizontal(|ui| {
                if ui.button("Reset view (Home)").clicked() {
                    st.view_reset_requested = true;
                }
                if ui.button("Fullscreen (F11)").clicked() {
                    st.fullscreen_requested = true;
                }
            });

            ui.separator();
            egui::CollapsingHeader::new("Advanced").default_open(false).show(ui, |ui| {
                ui.label(format!("GPU: {} ({})", hud.adapter, hud.backend));
                if hud.timestamps {
                    egui::Grid::new("gpu ms").num_columns(2).show(ui, |ui| {
                        for (pass, ms) in &hud.gpu_ms {
                            ui.label(*pass);
                            ui.label(format!("{ms:.3} ms"));
                            ui.end_row();
                        }
                    });
                } else {
                    ui.label(RichText::new("This GPU doesn't report timestamps, so no GPU times.").weak());
                }
                if ui.button("Keys (H)").clicked() {
                    st.help_open = true;
                }
            });
        });
}
