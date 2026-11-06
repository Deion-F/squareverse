//! The window: winit event loop, wgpu surface, the frame (sim steps, squares, tonemap, egui) and input.
//! Frames are paced to the 60 / 30 fps target; the sim takes the menu's steps per frame.

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
use crate::sim::{Sim, SimConfig};
use crate::timing::GpuTimer;
use crate::ui::{self, Hud, UiState};

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
    default_particles: u32,
    cursor: (f64, f64),
    dragging: bool,
    next_frame: Instant,
    redraw_pending: bool,
    fps: Rate,
    steps_rate: Rate,
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
    Camera { center_pc: cfg.center_pc, px_per_pc: size.0.min(size.1).max(1) as f64 / (2.3 * cfg.r_out_pc) }
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

        let instance =
            wgpu::Instance::new(wgpu::InstanceDescriptor::new_with_display_handle_from_env(Box::new(display.clone())));
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
        let cfg = config_from(cli, &gpu);
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
        let ui = UiState::new(sim.cfg.particles, sim.cfg.seed, cli.fps);
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
            default_particles,
            cursor: (0.0, 0.0),
            dragging: false,
            next_frame: Instant::now(),
            redraw_pending: false,
            fps: Rate::new(),
            steps_rate: Rate::new(),
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
        let cfg = SimConfig { particles: self.ui.particles, seed: self.ui.seed, ..self.sim.cfg.clone() };
        self.sim = Sim::new(&self.gpu, cfg)?;
        Ok(())
    }

    fn key(&mut self, key: &Key) {
        let ui = &mut self.ui;
        match key {
            Key::Named(NamedKey::Tab) => ui.menu_open = !ui.menu_open,
            Key::Named(NamedKey::Space) => ui.paused = !ui.paused,
            Key::Named(NamedKey::Home) => ui.view_reset_requested = true,
            Key::Named(NamedKey::F11) => ui.fullscreen_requested = true,
            Key::Named(NamedKey::Escape) => {
                if ui.help_open {
                    ui.help_open = false;
                } else {
                    ui.menu_open = false;
                }
            }
            Key::Character(c) => match c.to_lowercase().as_str() {
                "h" => ui.help_open = !ui.help_open,
                "r" => ui.reset_requested = true,
                "f" => ui.fps_target = if ui.fps_target == 60 { 30 } else { 60 },
                "[" => ui.steps_per_frame = ui.steps_per_frame.saturating_sub(1).max(1),
                "]" => ui.steps_per_frame = (ui.steps_per_frame + 1).min(64),
                _ => {}
            },
            _ => {}
        }
    }

    fn apply_requests(&mut self) -> Result<()> {
        if std::mem::take(&mut self.ui.reset_requested) {
            self.reset()?;
        }
        if std::mem::take(&mut self.ui.view_reset_requested) {
            self.camera = home_camera(&self.sim.cfg, self.size());
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
        let steps = if self.ui.paused { 0 } else { self.ui.steps_per_frame };
        self.fps.tick(now, 1.0);
        if let Some(last) = self.last_frame {
            // the first second is start-up (shader compiles, window mapping): leave it out of the worst frame
            if (now - self.started).as_secs_f64() > 1.0 {
                self.worst_ms = self.worst_ms.max((now - last).as_secs_f64() * 1e3);
            }
        } else {
            self.started = now;
        }
        self.last_frame = Some(now);
        self.frames += 1;
        self.steps_rate.tick(now, steps as f64);

        self.timer.begin();
        let mut enc = self.gpu.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("frame") });
        self.sim.encode_steps(&mut enc, steps, &mut self.timer);
        let look = Look { square_px: self.ui.square_px, brightness: self.ui.brightness, exposure: self.ui.exposure };
        self.renderer.draw(
            &self.gpu.device,
            &self.gpu.queue,
            &mut enc,
            &target,
            size,
            &self.sim,
            &self.camera,
            &look,
            &mut self.timer,
        );

        let hud = Hud {
            particles: self.sim.n,
            sim_time_myr: self.sim.time_myr,
            dt_myr: self.sim.cfg.dt_myr,
            steps_per_s: self.steps_rate.value,
            fps: self.fps.value,
            adapter: self.gpu.summary.name.clone(),
            backend: self.gpu.summary.backend.clone(),
            gpu_ms: self.timer.last.clone(),
            timestamps: self.timer.enabled(),
            default_particles: self.default_particles,
        };
        let raw = self.egui_state.take_egui_input(&self.window);
        let out = self.egui_ctx.run_ui(raw, |ui| ui::show(ui, &mut self.ui, &hud));
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
        self.window.pre_present_notify();
        self.gpu.queue.present(frame);
        let _ = self.gpu.device.poll(wgpu::PollType::Poll);
        self.timer.collect();
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
                    println!(
                        "{{\"adapter\": \"{}\", \"backend\": \"{}\", \"particles\": {}, \"frames\": {}, \"fps\": {:.1}, \"fps_target\": {}, \"worst_frame_ms\": {:.1}, \"gpu_ms\": {:?}}}",
                        r.gpu.summary.name,
                        r.gpu.summary.backend,
                        r.sim.n,
                        r.frames,
                        (r.frames - 1) as f64 / secs.max(1e-9),
                        r.ui.fps_target,
                        r.worst_ms,
                        r.timer.last
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
            WindowEvent::MouseInput { state, button: MouseButton::Left | MouseButton::Right, .. } => {
                r.dragging = state == ElementState::Pressed && !consumed;
            }
            WindowEvent::CursorMoved { position, .. } => {
                let p = (position.x, position.y);
                if r.dragging {
                    r.camera.drag(p.0 - r.cursor.0, p.1 - r.cursor.1);
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
