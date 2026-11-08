//! The menu (behind the button in the bottom-right corner, or Tab), the status corners and the key list (H).
//! Conventions carried over from v2: an (i) beside each setting explains it, ⏴ ⏵ arrows give fine steps, every
//! setting has a key, rarely needed figures fold away under Advanced.

use egui::{Align2, Color32, RichText, Ui};

/// What the menu changes. The app reads it every frame and acts on the `*_requested` flags.
pub struct UiState {
    pub paused: bool,
    /// Index into `SPEEDS`.
    pub speed: usize,
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
            speed: SPEEDS.len() - 1,
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

/// Sim speeds to choose from, Myr of sim time per second; `None` (the last): as fast as the frame budget allows.
pub const SPEEDS: [Option<f64>; 10] =
    [Some(0.5), Some(1.0), Some(2.0), Some(5.0), Some(10.0), Some(20.0), Some(50.0), Some(100.0), Some(200.0), None];

pub fn speed_name(speed: Option<f64>) -> String {
    match speed {
        Some(v) => format!("{v} Myr/s"),
        None => "max".into(),
    }
}

/// Figures shown in the corners and under Advanced.
pub struct Hud {
    pub particles: u32,
    pub sim_time_myr: f64,
    pub dt_myr: f64,
    pub dt_min_myr: f64,
    /// Sim time per second achieved.
    pub myr_per_s: f64,
    /// Particles in each time-step bin (bin b steps dt / 2^b).
    pub bin_counts: Vec<u32>,
    pub evals_per_myr: f64,
    /// The sim's GPU budget a frame, ms (None: no timestamps, one sub-step a frame).
    pub budget_ms: Option<f64>,
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
    ("[ / ]", "slower / faster (sim time per second)"),
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

fn corners(ui: &Ui, hud: &Hud, fps_target: u32) {
    let ctx = ui.ctx();
    let mono = |s: String| RichText::new(s).monospace().color(Color32::from_gray(210));
    egui::Area::new(egui::Id::unique("status")).anchor(Align2::LEFT_TOP, [8.0, 6.0]).interactable(false).show(ctx, |ui| {
        ui.label(mono(format!(
            "{} particles   t = {:.1} Myr   {:.1} Myr/s   {:.0} / {} fps",
            group(hud.particles as u64),
            hud.sim_time_myr,
            hud.myr_per_s,
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
                let mut i = st.speed as u32;
                if ui.add(egui::Button::new("⏴").small()).clicked() {
                    i = i.saturating_sub(1);
                }
                ui.add(egui::Slider::new(&mut i, 0..=(SPEEDS.len() - 1) as u32).show_value(false));
                if ui.add(egui::Button::new("⏵").small()).clicked() {
                    i = (i + 1).min(SPEEDS.len() as u32 - 1);
                }
                st.speed = i as usize;
                ui.label(speed_name(SPEEDS[st.speed]));
                info(
                    ui,
                    "Sim time per second of real time ([ and ]). \"max\" runs as much as each frame's GPU budget allows: \
                     the frame rate holds and the sim slows instead when there is a lot to do.",
                );
            });
            ui.label(RichText::new(format!("now {:.1} Myr/s", hud.myr_per_s)).weak());
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
                ui.label(match hud.budget_ms {
                    Some(b) => format!("Sim GPU budget {b:.1} ms a frame"),
                    None => "No GPU timestamps: one sub-step a frame".into(),
                });
                ui.label(format!(
                    "Time steps {:.3} - {:.2} Myr, {:.2} force evaluations per particle per Myr",
                    hud.dt_min_myr, hud.dt_myr, hud.evals_per_myr
                ));
                let total: u64 = hud.bin_counts.iter().map(|&c| c as u64).sum::<u64>().max(1);
                egui::Grid::new("bins").num_columns(2).show(ui, |ui| {
                    for (b, &c) in hud.bin_counts.iter().enumerate() {
                        ui.label(format!("step {:.3} Myr", hud.dt_myr / (1u64 << b) as f64));
                        ui.label(format!("{:.1}%", 100.0 * c as f64 / total as f64));
                        ui.end_row();
                    }
                });
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
