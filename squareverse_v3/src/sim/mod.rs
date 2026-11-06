//! The simulation on the GPU. Phase 0: particles orbiting one point mass (`shaders/step.wgsl`), to prove the
//! fixed-point positions, the timing and the drawing; phase 1 replaces the point mass with the tree.

pub mod init;
pub mod reference;

use anyhow::Result;
use serde::Serialize;
use wgpu::util::DeviceExt;

use crate::fixed::{Fixed2, TWO_32};
use crate::gpu::Gpu;
use crate::timing::GpuTimer;
use crate::units::G;

pub const WORKGROUP: u32 = 256;
const MAX_GROUPS_X: u32 = 65_535;

#[derive(Clone, Debug, Serialize)]
pub struct SimConfig {
    pub particles: u32,
    pub seed: u64,
    /// The periodic box's side, pc.
    pub box_pc: f64,
    /// Where the point mass sits, pc from the box's origin.
    pub center_pc: (f64, f64),
    /// Msun.
    pub central_mass: f64,
    pub r_in_pc: f64,
    pub r_out_pc: f64,
    /// Myr per step.
    pub dt_myr: f64,
    pub softening_pc: f64,
    /// Random speed spread, as a fraction of the circular speed.
    pub dispersion: f64,
}

impl Default for SimConfig {
    fn default() -> Self {
        let box_pc = 20_000_000.0; // 20 Mpc: the scale of the universe view
        Self {
            particles: 200_000,
            seed: 1,
            box_pc,
            center_pc: (box_pc / 2.0, box_pc / 2.0),
            central_mass: 1e10,
            r_in_pc: 1_000.0,
            r_out_pc: 15_000.0,
            dt_myr: 0.25,
            softening_pc: 50.0,
            dispersion: 0.03,
        }
    }
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct StepParams {
    center: [u32; 4],
    unit_pc: f32,
    inv_unit_pc: f32,
    dt: f32,
    gm: f32,
    eps2: f32,
    n: u32,
    row: u32,
    _pad: u32,
}

/// Positions and velocities read back from the GPU.
pub struct State {
    pub pos: Vec<Fixed2>,
    pub vel: Vec<[f32; 2]>,
}

pub struct Sim {
    pub cfg: SimConfig,
    pub n: u32,
    pub pos: wgpu::Buffer,
    pub vel: wgpu::Buffer,
    /// (temperature, luminosity) per particle, for drawing.
    pub star: wgpu::Buffer,
    pub mass: Vec<f32>,
    pipeline: wgpu::ComputePipeline,
    bind: wgpu::BindGroup,
    groups: (u32, u32),
    pub time_myr: f64,
    pub steps: u64,
}

pub fn shader(device: &wgpu::Device, label: &str, body: &str) -> wgpu::ShaderModule {
    let src = format!("{}\n{}", include_str!("../../shaders/fixed.wgsl"), body);
    device.create_shader_module(wgpu::ShaderModuleDescriptor { label: Some(label), source: wgpu::ShaderSource::Wgsl(src.into()) })
}

impl Sim {
    pub fn new(gpu: &Gpu, cfg: SimConfig) -> Result<Self> {
        let d = &gpu.device;
        let init = init::build(&cfg);
        let n = cfg.particles;
        let storage = wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC | wgpu::BufferUsages::COPY_DST;
        let pos = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("pos"),
            contents: bytemuck::cast_slice(&init.pos),
            usage: storage | wgpu::BufferUsages::VERTEX,
        });
        let vel = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("vel"),
            contents: bytemuck::cast_slice(&init.vel),
            usage: storage,
        });
        let star = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("star"),
            contents: bytemuck::cast_slice(&init.star),
            usage: storage | wgpu::BufferUsages::VERTEX,
        });

        let groups_total = n.div_ceil(WORKGROUP).max(1);
        let gx = groups_total.min(MAX_GROUPS_X);
        let groups = (gx, groups_total.div_ceil(gx));
        let unit_pc = cfg.box_pc / TWO_32;
        let params = StepParams {
            center: Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc).words(),
            unit_pc: unit_pc as f32,
            inv_unit_pc: (1.0 / unit_pc) as f32,
            dt: cfg.dt_myr as f32,
            gm: (G * cfg.central_mass) as f32,
            eps2: cfg.softening_pc.powi(2) as f32,
            n,
            row: gx * WORKGROUP,
            _pad: 0,
        };
        let params_buf = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("step params"),
            contents: bytemuck::bytes_of(&params),
            usage: wgpu::BufferUsages::UNIFORM,
        });

        let module = shader(d, "step", include_str!("../../shaders/step.wgsl"));
        let pipeline = d.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("step"),
            layout: None,
            module: &module,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        let bind = d.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("step"),
            layout: &pipeline.get_bind_group_layout(0),
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: params_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: pos.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: vel.as_entire_binding() },
            ],
        });
        Ok(Self { cfg, n, pos, vel, star, mass: init.mass, pipeline, bind, groups, time_myr: 0.0, steps: 0 })
    }

    /// Records `k` steps into the encoder (one compute pass, timed as "step" when the timer has room).
    pub fn encode_steps(&mut self, encoder: &mut wgpu::CommandEncoder, k: u32, timer: &mut GpuTimer) {
        if k == 0 {
            return;
        }
        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
            label: Some("step"),
            timestamp_writes: timer.compute("step"),
        });
        pass.set_pipeline(&self.pipeline);
        pass.set_bind_group(0, &self.bind, &[]);
        for _ in 0..k {
            pass.dispatch_workgroups(self.groups.0, self.groups.1, 1);
        }
        drop(pass);
        self.steps += k as u64;
        self.time_myr += k as f64 * self.cfg.dt_myr;
    }

    pub fn read_state(&self, gpu: &Gpu) -> Result<State> {
        let pos: Vec<[u32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.pos)?).to_vec();
        let vel: Vec<[f32; 2]> = bytemuck::cast_slice(&gpu.read_buffer(&self.vel)?).to_vec();
        Ok(State { pos: pos.into_iter().map(Fixed2::from_words).collect(), vel })
    }

    /// Total energy (kinetic + potential in the point mass's softened field), Msun pc^2 / Myr^2.
    pub fn energy(&self, s: &State) -> f64 {
        let center = Fixed2::from_pc(self.cfg.center_pc.0, self.cfg.center_pc.1, self.cfg.box_pc);
        let (gm, eps2) = (G * self.cfg.central_mass, self.cfg.softening_pc.powi(2));
        s.pos
            .iter()
            .zip(&s.vel)
            .zip(&self.mass)
            .map(|((p, v), &m)| {
                let (dx, dy) = p.delta_pc(center, self.cfg.box_pc);
                let v2 = (v[0] as f64).powi(2) + (v[1] as f64).powi(2);
                m as f64 * (0.5 * v2 - gm / (dx * dx + dy * dy + eps2).sqrt())
            })
            .sum()
    }
}

/// FNV-1a over the position and velocity words: equal runs give equal hashes.
pub fn state_hash(s: &State) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    let mut eat = |w: u32| {
        for b in w.to_le_bytes() {
            h ^= b as u64;
            h = h.wrapping_mul(0x0100_0000_01b3);
        }
    };
    for (p, v) in s.pos.iter().zip(&s.vel) {
        p.words().iter().for_each(|&w| eat(w));
        eat(v[0].to_bits());
        eat(v[1].to_bits());
    }
    h
}
