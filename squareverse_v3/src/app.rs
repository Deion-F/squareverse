//! The window: winit event loop, wgpu surface, the frame (sim steps, squares, tonemap, egui) and input.
//! Frames are paced to the 60 / 30 fps target. Each frame the sim gets a GPU time budget (the frame period less
//! the drawing, from the GPU timestamps) and runs as much of its work as fits (`Sim::advance`), capped by the menu's
//! speed; the particles are drawn moved on along their velocities to a smoothly running display clock, so motion
//! stays even while the sim advances in uneven bites.

use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseButton, MouseScrollDelta, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop, OwnedDisplayHandle};
use winit::keyboard::{Key, NamedKey};
use winit::window::{Fullscreen, Window, WindowId};

use crate::budget;
use crate::cli::Cli;
use crate::gpu::{Gpu, pick_adapter};
use crate::headless::config_from;
use crate::render::{Camera, Look, Renderer};
use crate::sim::{Limit, Sim, SimConfig};
use crate::timing::GpuTimer;
use crate::ui::{self, Hud, UiState};
use crate::view::{self, Selected, ViewState};

/// Spare particle slots the window keeps for its tools, as a share of the particles.
const SPARE_SHARE: f64 = 0.05;

pub fn run(cli: Cli) -> Result<()> {
    let event_loop = EventLoop::new().context("opening the event loop")?;
    let mut app = App { display: event_loop.owned_display_handle(), cli, running: None, error: None };
    event_loop.run_app(&mut app)?;
    app.error.map_or(Ok(()), Err)
}

struct App {
    cli: Cli,
    display: OwnedDisplayHandle,
    running: Option<Running>,
    error: Option<anyhow::Error>,
}

struct Running {
    window: Arc<Window>,
    gpu: Gpu,
    surface: wgpu::Surface<'static>,
    config: wgpu::SurfaceConfiguration,
    renderer: Renderer,
    sim: Sim,
    timer: GpuTimer,
    egui_ctx: egui::Context,
    egui_state: egui_winit::State,
    egui_renderer: egui_wgpu::Renderer,
    ui: UiState,
    camera: Camera,
    /// What is selected and followed (phase 6)
    view: ViewState,
    spare_share: f64,
    default_particles: u32,
    cursor: (f64, f64),
    dragging: bool,
    next_frame: Instant,
    redraw_pending: bool,
    fps: Rate,
    myr_rate: Rate,
    /// Sim time the speed cap still allows (Myr), the display clock, its rate (Myr a frame), and the drawing's GPU
    /// ms a frame (smoothed).
    allowance: f64,
    display_myr: f64,
    display_rate: f64,
    render_ms: f64,
    budget_ms: Option<f64>,
    /// Estimated GPU ms the sim overran its budget by last frame, taken off this frame's.
    overrun_ms: f64,
    /// 1 while frames arrive on time; shrinks when they come late (see `frame`).
    budget_scale: f64,
    /// For --exit-after-frames: GPU ms by pass summed over the timed frames, how many, and the longest one.
    gpu_totals: Vec<(&'static str, f64)>,
    timed_frames: u64,
    worst_gpu_ms: f64,
    /// Frames drawn, when they started, and the longest frame interval (for --exit-after-frames).
    frames: u64,
    started: Instant,
    last_frame: Option<Instant>,
    worst_ms: f64,
}

/// Events per second, smoothed over about half a second.
struct Rate {
    last: Option<Instant>,
    value: f64,
}

impl Rate {
    fn new() -> Self {
        Self { last: None, value: 0.0 }
    }

    fn tick(&mut self, now: Instant, events: f64) {
        if let Some(last) = self.last {
            let dt = (now - last).as_secs_f64().max(1e-6);
            let a = (dt / 0.5).min(1.0);
            self.value += a * (events / dt - self.value);
        }
        self.last = Some(now);
    }
}

fn home_camera(cfg: &SimConfig, size: (u32, u32)) -> Camera {
    Camera { center_pc: cfg.center_pc, px_per_pc: size.0.min(size.1).max(1) as f64 / (2.3 * cfg.view_radius_pc()) }
}

impl Running {
    fn new(event_loop: &ActiveEventLoop, cli: &Cli, display: &OwnedDisplayHandle) -> Result<Self> {
        let mut attrs = Window::default_attributes()
            .with_title("Squareverse")
            .with_inner_size(winit::dpi::LogicalSize::new(1280.0, 800.0));
        if cli.fullscreen {
            attrs = attrs.with_fullscreen(Some(Fullscreen::Borderless(None)));
        }
        let window = Arc::new(event_loop.create_window(attrs).context("opening the window")?);

        let instance = wgpu::Instance::new(crate::gpu::instance_descriptor(Some(Box::new(display.clone()))));
        let surface = instance.create_surface(window.clone()).context("making the window's surface")?;
        let adapter = pick_adapter(&instance, cli.adapter.as_deref(), cli.allow_cpu, Some(&surface))?;
        let gpu = Gpu::open(instance, adapter)?;
        log::info!("GPU: {} ({})", gpu.summary.name, gpu.summary.backend);

        let size = window.inner_size();
        let caps = surface.get_capabilities(&gpu.adapter);
        // a plain (non-sRGB) surface: egui expects one, and the tonemap pass encodes sRGB itself
        let format = caps.formats.iter().copied().find(|f| !f.is_srgb()).unwrap_or(caps.formats[0]);
        let mut config = surface
            .get_default_config(&gpu.adapter, size.width.max(1), size.height.max(1))
            .context("the window's surface isn't supported by this GPU")?;
        config.format = format;
        config.present_mode = wgpu::PresentMode::Fifo; // always available; pacing below handles 30 fps
        config.desired_maximum_frame_latency = 2;
        surface.configure(&gpu.device, &config);

        let renderer = Renderer::new(&gpu.device, format);
        let default_particles = budget::default_particles(&gpu);
        // the window keeps spare slots for the tools
        let cfg = SimConfig { spare_share: cli.spares.unwrap_or(SPARE_SHARE), ..config_from(cli, &gpu) };
        let sim = Sim::new(&gpu, cfg)?;
        let timer = GpuTimer::new(&gpu.device, &gpu.queue, gpu.timestamps);

        let egui_ctx = egui::Context::default();
        let egui_state = egui_winit::State::new(
            egui_ctx.clone(),
            egui::ViewportId::ROOT,
            &window,
            Some(window.scale_factor() as f32),
            window.theme(),
            Some(gpu.device.limits().max_texture_dimension_2d as usize),
        );
        let egui_renderer = egui_wgpu::Renderer::new(&gpu.device, format, Default::default());

        let camera = home_camera(&sim.cfg, (config.width, config.height));
        let mut ui = UiState::new(sim.cfg.particles, sim.cfg.seed, cli.fps);
        ui.scene = sim.cfg.scene;
        ui.toomre_q = sim.cfg.galaxy.toomre_q;
        ui.show_dm = cli.show_dm;
        match cli.speed.as_deref() {
            None | Some("auto") => {}
            Some("max") => ui.auto_speed = false,
            Some(v) => {
                if let Ok(x) = v.parse::<f64>() {
                    ui.auto_speed = false;
                    ui.speed = ui::nearest_speed(x);
                }
            }
        }
        Ok(Self {
            window,
            gpu,
            surface,
            config,
            renderer,
            sim,
            timer,
            egui_ctx,
            egui_state,
            egui_renderer,
            ui,
            camera,
            view: ViewState::default(),
            spare_share: cli.spares.unwrap_or(SPARE_SHARE),
            default_particles,
            cursor: (0.0, 0.0),
            dragging: false,
            next_frame: Instant::now(),
            redraw_pending: false,
            fps: Rate::new(),
            myr_rate: Rate::new(),
            allowance: 0.0,
            display_myr: 0.0,
            display_rate: 0.0,
            render_ms: 0.0,
            budget_ms: None,
            overrun_ms: 0.0,
            budget_scale: 1.0,
            gpu_totals: Vec::new(),
            timed_frames: 0,
            worst_gpu_ms: 0.0,
            frames: 0,
            started: Instant::now(),
            last_frame: None,
            worst_ms: 0.0,
        })
    }

    fn size(&self) -> (u32, u32) {
        (self.config.width, self.config.height)
    }

    fn resize(&mut self, w: u32, h: u32) {
        if w > 0 && h > 0 {
            self.config.width = w;
            self.config.height = h;
            self.surface.configure(&self.gpu.device, &self.config);
        }
    }

    fn reset(&mut self) -> Result<()> {
        let base = if self.ui.scene == self.sim.cfg.scene { self.sim.cfg.clone() } else { SimConfig::for_scene(self.ui.scene) };
        let mut cfg = SimConfig { particles: self.ui.particles, seed: self.ui.seed, ..base };
        cfg.galaxy.toomre_q = self.ui.toomre_q;
        cfg.spare_share = self.spare_share;
        self.sim = Sim::new(&self.gpu, cfg)?;
        self.view = ViewState::default();
        self.display_myr = 0.0;
        self.display_rate = 0.0;
        self.allowance = 0.0;
        Ok(())
    }

    fn key(&mut self, key: &Key) {
        let ui = &mut self.ui;
        match key {
            Key::Named(NamedKey::Tab) => ui.menu_open = !ui.menu_open,
            Key::Named(NamedKey::Space) => ui.paused = !ui.paused,
            Key::Named(NamedKey::Home) => ui.view_reset_requested = true,
            Key::Named(NamedKey::F11) => ui.fullscreen_requested = true,
            Key::Named(NamedKey::F5) => ui.save_requested = Some(crate::save::quick_path()),
            Key::Named(NamedKey::F9) => ui.load_requested = Some(crate::save::quick_path()),
            Key::Named(NamedKey::Escape) => {
                if ui.help_open {
                    ui.help_open = false;
                } else if ui.menu_open {
                    ui.menu_open = false;
                } else if self.view.system_open {
                    self.view.system_open = false;
                } else {
                    self.view.clear(&mut self.sim);
                }
            }
            Key::Character(c) => match c.to_lowercase().as_str() {
                "h" => ui.help_open = !ui.help_open,
                "d" => ui.show_dm = !ui.show_dm,
                "g" => ui.show_gas = !ui.show_gas,
                "r" => ui.reset_requested = true,
                "f" => ui.fps_target = if ui.fps_target == 60 { 30 } else { 60 },
                "[" => {
                    ui.speed = if ui.auto_speed { ui::nearest_speed(self.view.suggested_myr_s) } else { ui.speed }.saturating_sub(1);
                    ui.auto_speed = false;
                }
                "]" => {
                    ui.speed = (if ui.auto_speed { ui::nearest_speed(self.view.suggested_myr_s) } else { ui.speed } + 1).min(ui::SPEEDS.len() - 1);
                    ui.auto_speed = false;
                }
                "a" => ui.auto_speed = !ui.auto_speed,
                "1" => ui.tool = ui::Tool::Select,
                "2" => ui.tool = ui::Tool::Galaxy,
                "3" => ui.tool = ui::Tool::Well,
                "4" => ui.tool = ui::Tool::Gas,
                "5" => ui.tool = ui::Tool::Kick,
                "6" => ui.tool = ui::Tool::Delete,
                "7" => ui.tool = ui::Tool::Move,
                _ => {}
            },
            _ => {}
        }
    }

    fn say(&mut self, msg: String) {
        self.ui.message = Some((msg, Instant::now() + Duration::from_secs(4)));
    }

    /// The velocity of what is followed (new things placed move with it).
    fn followed_velocity(&self) -> [f64; 2] {
        if !self.view.follow {
            return [0.0; 2];
        }
        match &self.view.selected {
            Selected::Galaxy { galaxy, .. } => galaxy.velocity,
            Selected::Particle(_) => self.sim.tracked.map_or([0.0; 2], |t| [t.vel[0] as f64, t.vel[1] as f64]),
            Selected::None => [0.0; 2],
        }
    }

    /// A tool used from `press` to `release` (pixels).
    fn use_tool(&mut self, press: (f64, f64), release: (f64, f64)) -> Result<()> {
        use crate::sim::init::{self, Initial};
        use crate::sim::{ALL_KINDS, Brush};
        let size = self.size();
        let vp = (size.0 as f64, size.1 as f64);
        let a = self.sim.scale_factor();
        let (p0, p1) = (self.camera.world_at(press, vp), self.camera.world_at(release, vp));
        let box_pc = self.sim.cfg.box_pc;
        let at = crate::fixed::Fixed2::from_pc(p0.0, p0.1, box_pc);
        let brush = self.ui.tools.brush_px / self.camera.px_per_pc * a;
        let drag = [(p1.0 - p0.0) * a, (p1.1 - p0.1) * a];
        let v = self.followed_velocity();
        let t = self.ui.tools.clone();
        let placed = |what: &str, n: usize, want: usize| {
            if n < want { format!("{what}: only {n} of {want} particles fitted (the spare slots ran out)") } else { format!("{what}: {n} particles") }
        };
        let msg = match self.ui.tool {
            ui::Tool::Select => return Ok(()),
            ui::Tool::Galaxy => {
                let cfg = &self.sim.cfg;
                let seed = self.frames ^ 0x9a1a;
                let tpl = crate::sim::galaxy_template(&self.gpu, cfg, init::scaled_galaxy(t.galaxy_share), t.galaxy_particles, seed)?;
                let centre = crate::fixed::Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, box_pc);
                let angle = (seed % 628) as f64 / 100.0;
                let g = init::place(&[tpl], centre, box_pc, &[init::Placement { template: 0, center_pc: p0, velocity: v, angle, mirror: seed.is_multiple_of(2) }]);
                let n = self.sim.spawn(&self.gpu, &g)?;
                placed("galaxy", n, g.len())
            }
            ui::Tool::Well => {
                let mut w = Initial::with_capacity(1);
                w.push_well(at, v, t.well_mass);
                let n = self.sim.spawn(&self.gpu, &w)?;
                if n == 1 { format!("super well of {:.1e} Msun", t.well_mass) } else { "no spare slot left for a super well".into() }
            }
            ui::Tool::Gas => {
                let m = if self.sim.gas_ref_mass > 0.0 { self.sim.gas_ref_mass } else { (t.gas_mass / 2_000.0).max(1.0) };
                let count = (t.gas_mass / m).round().clamp(20.0, 100_000.0) as usize;
                let mut rng = crate::rng::Rng::new(self.frames);
                let mut g = Initial::with_capacity(count);
                let h = (24.0 * t.gas_radius_pc * t.gas_radius_pc / count as f64).sqrt().max(1.0);
                for _ in 0..count {
                    let (r, ang) = (t.gas_radius_pc * rng.f64().sqrt(), rng.f64() * std::f64::consts::TAU);
                    g.push_gas(at.offset_pc(r * ang.cos() / a, r * ang.sin() / a, box_pc), v, t.gas_mass / count as f64, t.gas_temperature_k, h, init::elements(1.0));
                }
                let n = self.sim.spawn(&self.gpu, &g)?;
                placed("gas", n, count)
            }
            ui::Tool::Kick => {
                let dv = [drag[0] / 20.0, drag[1] / 20.0];
                self.sim.brush(&self.gpu, at, brush, ALL_KINDS, Brush::Kick(dv))?;
                format!("kicked by {:.0} km/s", dv[0].hypot(dv[1]) / 1.0227)
            }
            ui::Tool::Delete => {
                self.sim.brush(&self.gpu, crate::fixed::Fixed2::from_pc(p1.0, p1.1, box_pc), brush, ALL_KINDS, Brush::Delete)?;
                "deleted".into()
            }
            ui::Tool::Move => {
                self.sim.brush(&self.gpu, at, brush, ALL_KINDS, Brush::Move(drag))?;
                "moved".into()
            }
        };
        self.say(msg);
        Ok(())
    }

    fn apply_requests(&mut self) -> Result<()> {
        if std::mem::take(&mut self.ui.reset_requested) {
            self.reset()?;
        }
        if std::mem::take(&mut self.ui.view_reset_requested) {
            self.camera = home_camera(&self.sim.cfg, self.size());
        }
        if let Some(path) = self.ui.save_requested.take() {
            let name = path.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
            let msg = match crate::save::save(&self.gpu, &self.sim, &path, &name) {
                Ok(()) => format!("saved {}", path.display()),
                Err(e) => format!("could not save: {e:#}"),
            };
            self.ui.presets = crate::save::list_presets();
            self.say(msg);
        }
        if let Some(path) = self.ui.load_requested.take() {
            match crate::save::load(&self.gpu, &path) {
                Ok(sim) => {
                    self.sim = sim;
                    self.view = ViewState::default();
                    self.ui.scene = self.sim.cfg.scene;
                    self.display_myr = self.sim.pos_time_myr();
                    self.display_rate = 0.0;
                    self.allowance = 0.0;
                    self.camera = home_camera(&self.sim.cfg, self.size());
                    self.say(format!("loaded {}", path.display()));
                }
                Err(e) => self.say(format!("could not load: {e:#}")),
            }
        }
        if std::mem::take(&mut self.ui.fullscreen_requested) {
            let full = self.window.fullscreen().is_some();
            self.window.set_fullscreen(if full { None } else { Some(Fullscreen::Borderless(None)) });
        }
        Ok(())
    }

    fn frame(&mut self) -> Result<()> {
        let now = Instant::now();
        let period = Duration::from_secs_f64(1.0 / self.ui.fps_target as f64);
        self.next_frame += period;
        if self.next_frame < now {
            self.next_frame = now;
        }
        self.redraw_pending = false;
        self.apply_requests()?;

        let frame = match self.surface.get_current_texture() {
            wgpu::CurrentSurfaceTexture::Success(t) | wgpu::CurrentSurfaceTexture::Suboptimal(t) => t,
            wgpu::CurrentSurfaceTexture::Timeout | wgpu::CurrentSurfaceTexture::Occluded => return Ok(()),
            _ => {
                self.surface.configure(&self.gpu.device, &self.config);
                return Ok(());
            }
        };
        let target = frame.texture.create_view(&Default::default());
        let size = self.size();
        self.fps.tick(now, 1.0);
        if let Some(last) = self.last_frame {
            // frames arriving late (work the timestamps don't see, such as the gaps between passes): shrink the
            // sim's budget quickly; on time: let it grow back slowly
            let interval = (now - last).as_secs_f64();
            if !self.ui.paused && interval > 1.08 / self.ui.fps_target as f64 {
                self.budget_scale = (self.budget_scale * 0.85).max(0.1);
            } else {
                self.budget_scale = (self.budget_scale + 0.005).min(1.0);
            }
            // the first second is start-up (shader compiles, window mapping): leave it out of the worst frame
            if (now - self.started).as_secs_f64() > 1.0 {
                self.worst_ms = self.worst_ms.max((now - last).as_secs_f64() * 1e3);
            }
        } else {
            self.started = now;
        }
        self.last_frame = Some(now);
        self.frames += 1;

        self.timer.begin();
        let mut enc = self.gpu.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("frame") });
        let before = self.sim.pos_time_myr();
        if !self.ui.paused {
            let fps = self.ui.fps_target as f64;
            let dt_min = self.sim.cfg.dt_min();
            let speed = if self.ui.auto_speed { Some(self.view.suggested_myr_s) } else { ui::SPEEDS[self.ui.speed] };
            let new_sub_steps = match speed {
                Some(speed) => {
                    self.allowance = (self.allowance + speed / fps).min(4.0 * speed / fps + dt_min);
                    (self.allowance / dt_min).floor() as u32
                }
                None => u32::MAX,
            };
            // the sim's share of the frame: what the drawing leaves of 85% of the period
            self.budget_ms = self.timer.enabled().then(|| (self.budget_scale * (850.0 / fps - self.render_ms)).max(1.0));
            // what the frame may spend: the budget less last frame's overrun (frames queue two deep, so one long
            // GPU frame followed by a short one still presents on time)
            let base = self.budget_ms;
            self.budget_ms = base.map(|b| (b - self.overrun_ms).max(0.25 * b));
            let limit = match self.budget_ms {
                Some(b) => Limit { budget_ms: b, new_sub_steps },
                None => Limit { budget_ms: f64::INFINITY, new_sub_steps: new_sub_steps.min(1) },
            };
            let spent = self.sim.advance(&mut enc, &mut self.timer, limit);
            self.overrun_ms = match self.budget_ms {
                Some(b) => (spent - b).max(0.0),
                None => 0.0,
            };
            self.budget_ms = base;
        }
        // picking and following (read-only passes)
        self.sim.encode_probe(&self.gpu.queue, &mut enc);
        let advanced = self.sim.pos_time_myr() - before;
        self.allowance = (self.allowance - advanced).max(0.0);
        self.myr_rate.tick(now, advanced);
        // the display clock: runs at the sim's average pace, pulled gently towards the sim's time
        let sim_t = self.sim.pos_time_myr();
        self.display_rate += 0.1 * (advanced - self.display_rate);
        self.display_myr += self.display_rate + 0.1 * (sim_t - self.display_myr);
        let reach = (4.0 * self.display_rate).max(self.sim.cfg.dt_min());
        self.display_myr = self.display_myr.clamp(sim_t - reach, sim_t + reach);
        let viewport = (size.0 as f64, size.1 as f64);
        self.view.frame(&mut self.sim, &mut self.camera, viewport, self.display_myr);
        // comoving positions: a peculiar velocity v moves a particle v / a across the box
        let extrap = (self.display_myr - sim_t) / self.sim.scale_factor();
        let look = Look {
            square_px: self.ui.square_px,
            brightness: self.ui.brightness,
            exposure: self.ui.exposure,
            show_dm: self.ui.show_dm,
            show_gas: self.ui.show_gas,
        };
        self.renderer.draw(
            &self.gpu.device,
            &self.gpu.queue,
            &mut enc,
            &target,
            size,
            &self.sim,
            &self.camera,
            &look,
            extrap,
            &mut self.timer,
        );

        let hud = Hud {
            particles: self.sim.n,
            sim_time_myr: self.display_myr.max(0.0),
            dt_myr: self.sim.cfg.dt_myr,
            dt_min_myr: self.sim.cfg.dt_min(),
            myr_per_s: self.myr_rate.value,
            bin_counts: self.sim.bin_counts[..self.sim.cfg.levels as usize].to_vec(),
            evals_per_myr: self.sim.evals_per_myr(&self.sim.bin_counts),
            budget_ms: self.budget_ms,
            fps: self.fps.value,
            adapter: self.gpu.summary.name.clone(),
            backend: self.gpu.summary.backend.clone(),
            // per stage, summed over the frame's passes
            gpu_ms: self.timer.labels().into_iter().map(|l| (l, self.timer.ms(l).unwrap_or(0.0))).collect(),
            timestamps: self.timer.enabled(),
            default_particles: self.default_particles,
            redshift: self.sim.cfg.cosmology.as_ref().map(|_| self.sim.redshift()),
            galaxies: (self.sim.cfg.finder.every_myr > 0.0 && self.sim.galaxies_myr > 0.0).then_some(self.sim.galaxies.len()),
            auto_myr_s: self.view.suggested_myr_s,
        };
        let raw = self.egui_state.take_egui_input(&self.window);
        let mut actions = view::PanelActions::default();
        let (tool, brush_px, cursor) = (self.ui.tool, self.ui.tools.brush_px, self.cursor);
        let press = self.view.press;
        let (sim, camera, vstate, display_myr) = (&self.sim, &self.camera, &mut self.view, self.display_myr);
        let out = self.egui_ctx.run_ui(raw, |ui| {
            ui::show(ui, &mut self.ui, &hud);
            let ctx = ui.ctx().clone();
            view::draw_marks(&ctx, camera, viewport, sim, vstate, ctx.pixels_per_point());
            actions = view::panel(&ctx, vstate, sim, display_myr);
            crate::system::window(&ctx, vstate, sim, display_myr);
            // the brush under the cursor, and a drag's arrow
            let ppp = ctx.pixels_per_point() as f64;
            let painter = ctx.layer_painter(egui::LayerId::background());
            let at = |p: (f64, f64)| egui::pos2((p.0 / ppp) as f32, (p.1 / ppp) as f32);
            if matches!(tool, ui::Tool::Kick | ui::Tool::Delete | ui::Tool::Move) {
                let centre = if tool == ui::Tool::Delete { cursor } else { press.unwrap_or(cursor) };
                painter.circle_stroke(at(centre), (brush_px / ppp) as f32, egui::Stroke::new(1.0, egui::Color32::from_rgba_unmultiplied(255, 200, 120, 140)));
                if let Some(p) = press
                    && tool != ui::Tool::Delete
                {
                    painter.arrow(at(p), at(cursor) - at(p), egui::Stroke::new(1.5, egui::Color32::from_rgb(255, 200, 120)));
                }
            }
        });
        if actions.clear {
            self.view.clear(&mut self.sim);
        }
        if actions.zoom {
            let a = self.sim.scale_factor();
            self.view.zoom_to = match &self.view.selected {
                Selected::Galaxy { galaxy, .. } => Some(view::fit(3.0 * galaxy.radius_pc.max(1_000.0) / a, viewport)),
                Selected::Particle(_) => Some(view::fit(1_000.0 / a, viewport)),
                Selected::None => None,
            };
            self.view.follow = true;
        }
        self.egui_state.handle_platform_output(&self.window, out.platform_output);
        let jobs = self.egui_ctx.tessellate(out.shapes, out.pixels_per_point);
        let screen = egui_wgpu::ScreenDescriptor { size_in_pixels: [size.0, size.1], pixels_per_point: out.pixels_per_point };
        for (id, deltas) in &out.textures_delta.set {
            for delta in deltas {
                self.egui_renderer.update_texture(&self.gpu.device, &self.gpu.queue, *id, delta);
            }
        }
        let extra = self.egui_renderer.update_buffers(&self.gpu.device, &self.gpu.queue, &mut enc, &jobs, &screen);
        {
            let mut pass = enc
                .begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("ui"),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &target,
                        depth_slice: None,
                        resolve_target: None,
                        ops: wgpu::Operations { load: wgpu::LoadOp::Load, store: wgpu::StoreOp::Store },
                    })],
                    depth_stencil_attachment: None,
                    timestamp_writes: self.timer.render("ui"),
                    occlusion_query_set: None,
                    multiview_mask: None,
                })
                .forget_lifetime();
            self.egui_renderer.render(&mut pass, &jobs, &screen);
        }
        for id in &out.textures_delta.free {
            self.egui_renderer.free_texture(id);
        }
        self.timer.resolve(&mut enc);
        self.gpu.queue.submit(extra.into_iter().chain([enc.finish()]));
        self.timer.after_submit();
        self.sim.after_submit();
        self.window.pre_present_notify();
        self.gpu.queue.present(frame);
        let _ = self.gpu.device.poll(wgpu::PollType::Poll);
        let timed = self.timer.collect();
        self.sim.collect(timed.then_some(&self.timer));
        if timed {
            let render: f64 = ["draw", "tonemap", "ui"].iter().filter_map(|l| self.timer.ms(l)).sum();
            self.render_ms += 0.2 * (render - self.render_ms);
            let mut total = 0.0;
            for &(label, ms) in &self.timer.last {
                total += ms;
                match self.gpu_totals.iter_mut().find(|(l, _)| *l == label) {
                    Some(e) => e.1 += ms,
                    None => self.gpu_totals.push((label, ms)),
                }
            }
            self.timed_frames += 1;
            if (now - self.started).as_secs_f64() > 1.0 {
                self.worst_gpu_ms = self.worst_gpu_ms.max(total);
            }
        }
        Ok(())
    }
}

impl ApplicationHandler for App {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.running.is_some() {
            return;
        }
        match Running::new(event_loop, &self.cli, &self.display) {
            Ok(r) => self.running = Some(r),
            Err(e) => {
                self.error = Some(e);
                event_loop.exit();
            }
        }
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: WindowId, event: WindowEvent) {
        let Some(r) = &mut self.running else { return };
        let consumed = r.egui_state.on_window_event(&r.window, &event).consumed;
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::Resized(s) => r.resize(s.width, s.height),
            WindowEvent::RedrawRequested => {
                if let Err(e) = r.frame() {
                    self.error = Some(e);
                    event_loop.exit();
                } else if self.cli.exit_after_frames.is_some_and(|n| r.frames >= n) {
                    let secs = r.last_frame.map_or(0.0, |l| (l - r.started).as_secs_f64());
                    // GPU ms a frame by pass: the mean over every timed frame
                    let per_frame: Vec<String> = r
                        .gpu_totals
                        .iter()
                        .map(|(l, ms)| format!("\"{l}\": {:.2}", ms / r.timed_frames.max(1) as f64))
                        .collect();
                    println!(
                        "{{\"adapter\": \"{}\", \"backend\": \"{}\", \"particles\": {}, \"frames\": {}, \"fps\": {:.1}, \"fps_target\": {}, \"worst_frame_ms\": {:.1}, \"sim_myr\": {:.1}, \"myr_per_s\": {:.2}, \"gpu_ms_mean\": {{{}}}, \"gpu_ms_worst_frame\": {:.1}, \"bin_counts\": {:?}, \"sim_budget_ms\": {:.1}}}",
                        r.gpu.summary.name,
                        r.gpu.summary.backend,
                        r.sim.n,
                        r.frames,
                        (r.frames - 1) as f64 / secs.max(1e-9),
                        r.ui.fps_target,
                        r.worst_ms,
                        r.sim.pos_time_myr(),
                        r.sim.pos_time_myr() / secs.max(1e-9),
                        per_frame.join(", "),
                        r.worst_gpu_ms,
                        &r.sim.bin_counts[..r.sim.cfg.levels as usize],
                        r.budget_ms.unwrap_or(0.0)
                    );
                    event_loop.exit();
                }
            }
            WindowEvent::KeyboardInput { event, .. } if !consumed && event.state == ElementState::Pressed => {
                r.key(&event.logical_key);
            }
            WindowEvent::MouseWheel { delta, .. } if !consumed => {
                let lines = match delta {
                    MouseScrollDelta::LineDelta(_, y) => y as f64,
                    MouseScrollDelta::PixelDelta(p) => p.y / 40.0,
                };
                let size = r.size();
                r.camera.zoom_at(1.2f64.powf(lines), r.cursor, (size.0 as f64, size.1 as f64));
            }
            WindowEvent::MouseInput { state, button, .. } if matches!(button, MouseButton::Left | MouseButton::Right) => {
                let pressed = state == ElementState::Pressed;
                r.dragging = pressed && !consumed;
                if button == MouseButton::Left {
                    if pressed && !consumed {
                        r.view.press = Some(r.cursor);
                    } else if !pressed {
                        // a click: pressed and let go in about the same place
                        if let Some(p) = r.view.press.take() {
                            let click = (p.0 - r.cursor.0).hypot(p.1 - r.cursor.1) < 4.0;
                            if r.ui.tool == ui::Tool::Select {
                                if click {
                                    let size = r.size();
                                    let dm = r.ui.show_dm;
                                    r.view.click(&mut r.sim, &r.camera, r.cursor, (size.0 as f64, size.1 as f64), dm);
                                }
                            } else if let Err(e) = r.use_tool(p, r.cursor) {
                                r.say(format!("{e:#}"));
                            }
                        }
                    }
                }
            }
            WindowEvent::CursorMoved { position, .. } => {
                let p = (position.x, position.y);
                // with a tool that drags (kick, move), the left button doesn't move the view
                let tool_drag = matches!(r.ui.tool, ui::Tool::Kick | ui::Tool::Move | ui::Tool::Delete) && r.view.press.is_some();
                if r.dragging && !tool_drag {
                    r.camera.drag(p.0 - r.cursor.0, p.1 - r.cursor.1);
                    // moving the view by hand stops following
                    if r.view.press.is_none_or(|q| (q.0 - p.0).hypot(q.1 - p.1) >= 4.0) {
                        r.view.follow = false;
                        r.view.zoom_to = None;
                    }
                }
                r.cursor = p;
            }
            _ => {}
        }
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        let Some(r) = &mut self.running else { return };
        if Instant::now() >= r.next_frame && !r.redraw_pending {
            r.redraw_pending = true;
            r.window.request_redraw();
        }
        event_loop.set_control_flow(ControlFlow::WaitUntil(r.next_frame));
    }
}
