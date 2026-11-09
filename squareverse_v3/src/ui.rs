//! The menu (behind the button in the bottom-right corner, or Tab), the status corners and the key list (H).
//! Conventions carried over from v2: an (i) beside each setting explains it, ⏴ ⏵ arrows give fine steps, every
//! setting has a key, rarely needed figures fold away under Advanced.

use egui::{Align2, Color32, RichText, Ui};

/// What the menu changes. The app reads it every frame and acts on the `*_requested` flags.
pub struct UiState {
    pub paused: bool,
    /// The speed follows the zoom (`view::suggested_speed`) until a speed is chosen.
    pub auto_speed: bool,
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
    /// The scene and the galaxy's Toomre Q for the next reset.
    pub scene: crate::sim::Scene,
    pub toomre_q: f64,
    pub show_dm: bool,
    pub show_gas: bool,
    /// Rings round the galaxies the finder found.
    pub show_rings: bool,
    pub reset_requested: bool,
    pub view_reset_requested: bool,
    pub fullscreen_requested: bool,
    /// The mouse's tool and its settings (phase 8).
    pub tool: Tool,
    pub tools: ToolSettings,
    /// Saving and loading: the name for a new preset, the presets found, and what was asked for.
    pub preset_name: String,
    pub presets: Vec<(String, std::path::PathBuf)>,
    pub save_requested: Option<std::path::PathBuf>,
    pub load_requested: Option<std::path::PathBuf>,
    /// A message for the status line, and until when.
    pub message: Option<(String, std::time::Instant)>,
}

/// What a click (or drag) in the view does.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tool {
    /// Pick a galaxy or a particle, and follow it.
    Select,
    /// Place a galaxy (built in balance) where clicked.
    Galaxy,
    /// Place a super well.
    Well,
    /// Pour a disc of gas.
    Gas,
    /// Drag to give everything under the brush a velocity.
    Kick,
    /// Delete everything under the brush.
    Delete,
    /// Drag to move everything under the brush.
    Move,
}

#[derive(Clone, Debug)]
pub struct ToolSettings {
    /// A new galaxy's mass as a share of the default (Milky Way-like) one, and its particles.
    pub galaxy_share: f64,
    pub galaxy_particles: u32,
    /// A new super well's mass, Msun.
    pub well_mass: f64,
    /// Gas poured: mass (Msun), the disc's radius (pc), temperature (K).
    pub gas_mass: f64,
    pub gas_radius_pc: f64,
    pub gas_temperature_k: f64,
    /// The brush's radius, pixels.
    pub brush_px: f64,
}

impl Default for ToolSettings {
    fn default() -> Self {
        Self { galaxy_share: 0.3, galaxy_particles: 30_000, well_mass: 1e7, gas_mass: 1e9, gas_radius_pc: 2_000.0, gas_temperature_k: 1e4, brush_px: 30.0 }
    }
}

impl UiState {
    pub fn new(particles: u32, seed: u64, fps_target: u32) -> Self {
        Self {
            paused: false,
            auto_speed: true,
            speed: SPEEDS.len() - 1,
            fps_target,
            brightness: crate::snapshot::default_look().brightness,
            exposure: crate::snapshot::default_look().exposure,
            square_px: crate::snapshot::default_look().square_px,
            menu_open: false,
            help_open: false,
            particles,
            seed,
            scene: crate::sim::Scene::Galaxy,
            toomre_q: 1.5,
            show_dm: false,
            show_gas: true,
            show_rings: true,
            reset_requested: false,
            view_reset_requested: false,
            fullscreen_requested: false,
            tool: Tool::Select,
            tools: ToolSettings::default(),
            preset_name: String::new(),
            presets: crate::save::list_presets(),
            save_requested: None,
            load_requested: None,
            message: None,
        }
    }
}

/// Sim speeds to choose from, Myr of sim time per second; `None` (the last): as fast as the frame budget allows.
pub const SPEEDS: [Option<f64>; 12] = [
    Some(0.5),
    Some(1.0),
    Some(2.0),
    Some(5.0),
    Some(10.0),
    Some(20.0),
    Some(50.0),
    Some(100.0),
    Some(200.0),
    Some(500.0),
    Some(1000.0),
    None,
];

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
    /// The redshift (expanding universe only), and the galaxies the finder last counted (None: finder off).
    pub redshift: Option<f64>,
    pub galaxies: Option<usize>,
    /// The speed the zoom suggests (Myr/s).
    pub auto_myr_s: f64,
}

/// The index of the listed speed nearest `myr_s`.
pub fn nearest_speed(myr_s: f64) -> usize {
    (0..SPEEDS.len() - 1).min_by(|&a, &b| {
        let d = |i: usize| (SPEEDS[i].unwrap_or(1.0) / myr_s).ln().abs();
        d(a).total_cmp(&d(b))
    }).unwrap_or(0)
}

pub const KEYS: &[(&str, &str)] = &[
    ("Tab", "open / close the menu"),
    ("H", "this list of keys"),
    ("Space", "pause / run"),
    ("[ / ]", "slower / faster (sim time per second)"),
    ("A", "speed by zoom on / off"),
    ("O", "galaxy rings on / off"),
    ("1 - 7", "tools: select, galaxy, super well, gas, kick, delete, move"),
    ("F5 / F9", "quick save / quick load"),
    ("Click", "select a galaxy (its ring) or a particle; it is followed"),
    ("Esc", "close the key list / menu / star system, else clear the selection"),
    ("R", "reset the universe"),
    ("D", "show / hide the dark matter"),
    ("G", "show / hide the gas"),
    ("F", "frame-rate target 60 / 30 fps"),
    ("Home", "reset the view"),
    ("F11", "fullscreen"),
    ("Wheel", "zoom at the cursor"),
    ("Drag", "move the view (left or right button)"),
];

fn info(ui: &mut Ui, text: &str) {
    ui.label(RichText::new("(i)").weak()).on_hover_text(text);
}

fn corners(ui: &Ui, hud: &Hud, fps_target: u32) {
    let ctx = ui.ctx();
    let mono = |s: String| RichText::new(s).monospace().color(Color32::from_gray(210));
    egui::Area::new(egui::Id::unique("status")).anchor(Align2::LEFT_TOP, [8.0, 6.0]).interactable(false).show(ctx, |ui| {
        let z = hud.redshift.map_or(String::new(), |z| format!("   z = {z:.2}"));
        let gals = hud.galaxies.map_or(String::new(), |n| format!("   {n} galaxies"));
        ui.label(mono(format!(
            "{} particles   t = {:.1} Myr{z}{gals}   {:.1} Myr/s   {:.0} / {} fps",
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

fn tools(ui: &mut Ui, st: &mut UiState) {
    ui.horizontal_wrapped(|ui| {
        for (t, name) in [
            (Tool::Select, "Select"),
            (Tool::Galaxy, "Galaxy"),
            (Tool::Well, "Super well"),
            (Tool::Gas, "Gas"),
            (Tool::Kick, "Kick"),
            (Tool::Delete, "Delete"),
            (Tool::Move, "Move"),
        ] {
            ui.selectable_value(&mut st.tool, t, name);
        }
        info(
            ui,
            "What a click in the view does. Select: pick a galaxy (its ring, when small) or a particle, and follow it. \
             Galaxy, Super well, Gas: place one where you click (moving with what is followed, if anything). Kick: \
             drag to give everything under the brush a velocity (the longer the drag, the faster). Delete: click or \
             drag to remove everything under the brush. Move: drag what is under the brush. The tools act between \
             steps; new particles go into spare slots kept for them (5% of the particles).",
        );
    });
    let t = &mut st.tools;
    match st.tool {
        Tool::Galaxy => {
            ui.horizontal(|ui| {
                ui.label("Mass");
                ui.add(egui::Slider::new(&mut t.galaxy_share, 0.02..=2.0).logarithmic(true).suffix(" x Milky Way"));
            });
            ui.horizontal(|ui| {
                ui.label("Particles");
                ui.add(egui::DragValue::new(&mut t.galaxy_particles).range(2_000..=500_000).speed(500));
            });
        }
        Tool::Well => {
            ui.horizontal(|ui| {
                ui.label("Mass");
                ui.add(egui::Slider::new(&mut t.well_mass, 1e3..=1e10).logarithmic(true).suffix(" Msun"));
            });
        }
        Tool::Gas => {
            ui.horizontal(|ui| {
                ui.label("Mass");
                ui.add(egui::Slider::new(&mut t.gas_mass, 1e5..=1e11).logarithmic(true).suffix(" Msun"));
            });
            ui.horizontal(|ui| {
                ui.label("Radius");
                ui.add(egui::Slider::new(&mut t.gas_radius_pc, 50.0..=50_000.0).logarithmic(true).suffix(" pc"));
            });
            ui.horizontal(|ui| {
                ui.label("Temperature");
                ui.add(egui::Slider::new(&mut t.gas_temperature_k, 100.0..=1e7).logarithmic(true).suffix(" K"));
            });
        }
        Tool::Kick | Tool::Delete | Tool::Move => {
            ui.horizontal(|ui| {
                ui.label("Brush");
                ui.add(egui::Slider::new(&mut t.brush_px, 3.0..=300.0).logarithmic(true).suffix(" px"));
            });
        }
        Tool::Select => {}
    }
}

fn saves(ui: &mut Ui, st: &mut UiState) {
    ui.horizontal(|ui| {
        if ui.button("Quick save (F5)").clicked() {
            st.save_requested = Some(crate::save::quick_path());
        }
        if ui.button("Quick load (F9)").clicked() {
            st.load_requested = Some(crate::save::quick_path());
        }
        info(ui, "Saves the whole universe as it is (every particle, the settings and the clock), and loads it back to carry on.");
    });
    ui.horizontal(|ui| {
        ui.add(egui::TextEdit::singleline(&mut st.preset_name).hint_text("preset name").desired_width(150.0));
        if ui.add_enabled(!st.preset_name.trim().is_empty(), egui::Button::new("Save as preset")).clicked() {
            st.save_requested = Some(crate::save::preset_path(&st.preset_name));
        }
        info(ui, "Keeps the universe as it is now as a preset, in the presets folder, to start from again later (listed below).");
    });
    if !st.presets.is_empty() {
        egui::ScrollArea::vertical().max_height(120.0).show(ui, |ui| {
            for (name, path) in &st.presets {
                ui.horizontal(|ui| {
                    if ui.small_button("Load").clicked() {
                        st.load_requested = Some(path.clone());
                    }
                    ui.label(name);
                });
            }
        });
    }
}

pub fn show(ui: &mut Ui, st: &mut UiState, hud: &Hud) {
    corners(ui, hud, st.fps_target);
    if let Some((m, until)) = &st.message {
        if std::time::Instant::now() < *until {
            egui::Area::new(egui::Id::unique("message")).anchor(Align2::CENTER_TOP, [0.0, 30.0]).interactable(false).show(ui.ctx(), |ui| {
                ui.label(RichText::new(m).color(Color32::from_rgb(255, 220, 140)));
            });
        } else {
            st.message = None;
        }
    }
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
                ui.checkbox(&mut st.auto_speed, "Speed by zoom (A)");
                if st.auto_speed {
                    ui.label(format!("{:.2} Myr/s", hud.auto_myr_s));
                }
                info(
                    ui,
                    "The zoom suggests the speed: about 10 Myr/s on a whole galaxy (a rotation in ~20 s), slower closer \
                     in, up to ~2,000 Myr/s on the whole universe. Choosing a speed below turns it off.",
                );
            });
            ui.horizontal(|ui| {
                ui.label("Speed");
                let mut i = st.speed as u32;
                let before = i;
                if ui.add(egui::Button::new("⏴").small()).clicked() {
                    i = i.saturating_sub(1);
                }
                ui.add(egui::Slider::new(&mut i, 0..=(SPEEDS.len() - 1) as u32).show_value(false));
                if ui.add(egui::Button::new("⏵").small()).clicked() {
                    i = (i + 1).min(SPEEDS.len() as u32 - 1);
                }
                if i != before {
                    st.auto_speed = false;
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
                ui.label("Scene");
                ui.selectable_value(&mut st.scene, crate::sim::Scene::Galaxy, "Galaxy");
                ui.selectable_value(&mut st.scene, crate::sim::Scene::Pair, "Pair");
                ui.selectable_value(&mut st.scene, crate::sim::Scene::Group, "Group");
                ui.selectable_value(&mut st.scene, crate::sim::Scene::Universe, "Universe");
                ui.selectable_value(&mut st.scene, crate::sim::Scene::Disc, "Test disc");
                info(
                    ui,
                    "What the next reset makes. Galaxy: a disc of stars, a bulge, a dark matter halo and a super well \
                     at the centre, in balance. Pair: two such galaxies on a collision course. Group: 24 galaxies \
                     (one large, three medium, twenty dwarfs) falling together. Universe: the early universe, 20 Mpc \
                     across from redshift 30: dark matter and gas, nearly smooth, collapse into the cosmic web and \
                     its galaxies as space expands. Test disc: stars round a fixed central mass (the phase-1 test \
                     scene).",
                );
            });
            if st.scene == crate::sim::Scene::Galaxy {
                ui.horizontal(|ui| {
                    ui.label("Toomre Q");
                    ui.add(egui::Slider::new(&mut st.toomre_q, 0.6..=3.0).step_by(0.1));
                    info(
                        ui,
                        "How much random motion the disc's stars have, against their own gravity (for the next reset). \
                         Under ~1 the disc breaks into clumps; ~1 - 1.5 it grows spiral arms; 2 and up it stays smooth.",
                    );
                });
            }
            ui.horizontal(|ui| {
                ui.label("Seed");
                ui.add(egui::DragValue::new(&mut st.seed));
                info(ui, "The same seed always makes the same universe.");
            });
            if ui.button("Reset (R)").clicked() {
                st.reset_requested = true;
            }

            ui.separator();
            ui.heading("Tools");
            tools(ui, st);

            ui.separator();
            ui.heading("Saves and presets");
            saves(ui, st);

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
                ui.checkbox(&mut st.show_dm, "Dark matter (D)");
                info(ui, "Draws the dark matter particles, dim violet. They are normally unseen, as in the real sky.");
                ui.checkbox(&mut st.show_gas, "Gas (G)");
                info(
                    ui,
                    "Draws the gas, coloured by temperature: cold gas dim blue, gas near 10,000 K the pink of glowing \
                     hydrogen, hot gas (a million degrees and more, from supernovae) blue-white. Brighter where denser.",
                );
            });
            ui.horizontal(|ui| {
                ui.checkbox(&mut st.show_rings, "Galaxy rings (O)");
                info(
                    ui,
                    "Rings round the galaxies the galaxy finder found (those with stars, at most 300, the most stars \
                     first), while they are small on screen; click one to follow it. They fade out as you zoom in.",
                );
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
