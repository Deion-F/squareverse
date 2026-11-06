//! The simulation on the GPU. Phase 1: self-gravity by a Barnes-Hut tree rebuilt every step, plus a central
//! point mass (phase 2 makes it a super well). A step:
//!
//! 1. `kick_drift` (half kick with last step's acceleration, drift) on particle set A;
//! 2. bounding box and 48-bit Morton keys, radix sort (`src/sort.rs`), gather A into set B in key order;
//! 3. the Karras radix tree over the sorted keys, node moments from the leaves up, forces by walking the tree;
//! 4. `kick` (second half kick) on B, which becomes the current set.
//!
//! Every pass is deterministic (integer atomics only), so a seed gives the same state on the same GPU and backend.

pub mod init;
pub mod reference;

use anyhow::Result;
use serde::Serialize;
use wgpu::util::DeviceExt;

use crate::fixed::{Fixed2, TWO_32};
use crate::gpu::Gpu;
use crate::kernels::{Bind, Groups, Kernel, prelude, storage, uniform};
use crate::sort::RadixSort;
use crate::timing::GpuTimer;
use crate::units::G;
use init::Initial;

const NODE_WORDS: u64 = 16;
const FORCE_GROUP: u32 = 128;

#[derive(Clone, Debug, Serialize)]
pub struct SimConfig {
    pub particles: u32,
    pub seed: u64,
    /// The periodic box's side, pc.
    pub box_pc: f64,
    /// Where the central mass sits, pc from the box's origin.
    pub center_pc: (f64, f64),
    /// Msun (0: none).
    pub central_mass: f64,
    pub central_softening_pc: f64,
    /// The disc's total mass, Msun (0: the particles keep their single-star IMF masses).
    pub disc_mass: f64,
    pub r_in_pc: f64,
    pub r_out_pc: f64,
    /// Myr per step.
    pub dt_myr: f64,
    /// The particles' softening (Plummer), pc.
    pub softening_pc: f64,
    /// Opening angle: a tree node acts as one mass when its size / distance is below this.
    pub theta: f64,
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
            central_softening_pc: 50.0,
            disc_mass: 2e9,
            r_in_pc: 1_000.0,
            r_out_pc: 15_000.0,
            dt_myr: 0.25,
            softening_pc: 20.0,
            theta: 0.6,
            dispersion: 0.1,
        }
    }
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Common {
    center: [u32; 4],
    n: u32,
    row: u32,
    origin_x: u32,
    origin_y: u32,
    theta: f32,
    eps2: f32,
    g: f32,
    unit_pc: f32,
    inv_unit_pc: f32,
    dt: f32,
    gm_c: f32,
    eps2_c: f32,
}

/// Particle state read back from the GPU, in id order.
pub struct State {
    pub pos: Vec<Fixed2>,
    pub vel: Vec<[f32; 2]>,
    pub mass: Vec<f32>,
    /// (ax, ay, phi_self, phi_central) from the last force pass.
    pub acc: Vec<[f32; 4]>,
}

/// The bind groups that read or write one particle set.
struct SetBinds {
    integrate: wgpu::BindGroup,
    morton: wgpu::BindGroup,
    /// this set -> the other one
    gather: wgpu::BindGroup,
    moments: wgpu::BindGroup,
    force: wgpu::BindGroup,
}

struct Kernels {
    integrate: Kernel,
    morton: Kernel,
    gather: Kernel,
    karras: Kernel,
    moments: Kernel,
    force: Kernel,
}

pub struct Sim {
    pub cfg: SimConfig,
    pub n: u32,
    pos: [wgpu::Buffer; 2],
    kin: [wgpu::Buffer; 2],
    body: [wgpu::Buffer; 2],
    acc: wgpu::Buffer,
    /// which particle set is current
    cur: usize,
    sort: RadixSort,
    k: Kernels,
    sets: [SetBinds; 2],
    karras: wgpu::BindGroup,
    groups: Groups,
    force_groups: Groups,
    _buffers: Vec<wgpu::Buffer>,
    pub time_myr: f64,
    pub steps: u64,
}

fn module(body: &str) -> String {
    format!("{}{}", prelude(), body)
}

impl Sim {
    pub fn new(gpu: &Gpu, cfg: SimConfig) -> Result<Self> {
        let init = init::build(&cfg);
        Self::from_initial(gpu, cfg, &init)
    }

    /// From given particles (tests and other scenes); `cfg.particles` is taken from them.
    pub fn from_initial(gpu: &Gpu, mut cfg: SimConfig, init: &Initial) -> Result<Self> {
        let d = &gpu.device;
        let n = init.len() as u32;
        anyhow::ensure!(n >= 1, "a universe needs at least one particle");
        cfg.particles = n;
        let groups = Groups::for_items(n, 256);
        let force_groups = Groups::for_items(n, FORCE_GROUP);
        let force_row = force_groups.x * FORCE_GROUP;

        let usage = wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC | wgpu::BufferUsages::COPY_DST;
        let make = |label: &str, bytes: &[u8], vertex: bool| {
            d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some(label),
                contents: bytes,
                usage: if vertex { usage | wgpu::BufferUsages::VERTEX } else { usage },
            })
        };
        let pos = [make("pos 0", bytemuck::cast_slice(&init.pos), true), make("pos 1", bytemuck::cast_slice(&init.pos), true)];
        let kin = [make("kin 0", bytemuck::cast_slice(&init.kin), true), make("kin 1", bytemuck::cast_slice(&init.kin), true)];
        let body = [make("body 0", bytemuck::cast_slice(&init.body), false), make("body 1", bytemuck::cast_slice(&init.body), false)];
        let acc = storage(d, "acc", n as u64 * 16);
        let bbox = storage(d, "bbox", 16);
        let internal = n.saturating_sub(1).max(1) as u64;
        let child = storage(d, "child", internal * 8);
        let parents = storage(d, "parents", 2 * n as u64 * 4);
        let counter = storage(d, "counter", internal * 4);
        let node = storage(d, "node", internal * NODE_WORDS * 4);

        let unit_pc = cfg.box_pc / TWO_32;
        let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
        // the tree's origin: half a box from the centre, so the particles' region doesn't straddle the wrap
        let origin = center.offset_pc(-cfg.box_pc / 2.0, -cfg.box_pc / 2.0, cfg.box_pc).words();
        let common = uniform(
            d,
            "common",
            &Common {
                center: center.words(),
                n,
                row: groups.x * 256,
                origin_x: origin[0],
                origin_y: origin[2],
                theta: cfg.theta as f32,
                eps2: cfg.softening_pc.powi(2) as f32,
                g: G as f32,
                unit_pc: unit_pc as f32,
                inv_unit_pc: (1.0 / unit_pc) as f32,
                dt: cfg.dt_myr as f32,
                gm_c: (G * cfg.central_mass) as f32,
                eps2_c: cfg.central_softening_pc.powi(2) as f32,
            },
        );
        // the force pass runs 128 to a group: its row must be the same length
        let force_common = uniform(
            d,
            "common (force)",
            &Common {
                center: center.words(),
                n,
                row: force_row,
                origin_x: origin[0],
                origin_y: origin[2],
                theta: cfg.theta as f32,
                eps2: cfg.softening_pc.powi(2) as f32,
                g: G as f32,
                unit_pc: unit_pc as f32,
                inv_unit_pc: (1.0 / unit_pc) as f32,
                dt: cfg.dt_myr as f32,
                gm_c: (G * cfg.central_mass) as f32,
                eps2_c: cfg.central_softening_pc.powi(2) as f32,
            },
        );

        use Bind::{Read as R, Uniform as U, Write as W};
        let k = Kernels {
            integrate: Kernel::new(d, "integrate", &module(include_str!("../../shaders/integrate.wgsl")), &[U, W, W, R], &["kick_drift", "kick"]),
            morton: Kernel::new(
                d,
                "morton",
                &module(include_str!("../../shaders/morton.wgsl")),
                &[U, R, W, W, W],
                &["bbox_reset", "bbox_reduce", "keys_main"],
            ),
            gather: Kernel::new(d, "gather", &module(include_str!("../../shaders/gather.wgsl")), &[U, R, R, R, R, W, W, W], &["main"]),
            karras: Kernel::new(d, "karras", &module(include_str!("../../shaders/karras.wgsl")), &[U, R, W, W, W], &["main"]),
            moments: Kernel::new(d, "moments", &module(include_str!("../../shaders/moments.wgsl")), &[U, R, R, R, R, W, W], &["main"]),
            force: Kernel::new(d, "force", &module(include_str!("../../shaders/force.wgsl")), &[U, R, R, R, R, W], &["main"]),
        };
        let sort = RadixSort::new(d, n);
        let set = |s: usize| {
            let o = 1 - s;
            SetBinds {
                integrate: k.integrate.bind(d, "integrate", &[&common, &pos[s], &kin[s], &acc]),
                morton: k.morton.bind(d, "morton", &[&common, &pos[s], &bbox, &sort.keys[0], &sort.vals[0]]),
                gather: k.gather.bind(d, "gather", &[&common, &sort.vals[0], &pos[s], &kin[s], &body[s], &pos[o], &kin[o], &body[o]]),
                moments: k.moments.bind(d, "moments", &[&common, &pos[s], &body[s], &child, &parents, &counter, &node]),
                force: k.force.bind(d, "force", &[&force_common, &pos[s], &body[s], &child, &node, &acc]),
            }
        };
        let sets = [set(0), set(1)];
        let karras = k.karras.bind(d, "karras", &[&common, &sort.keys[0], &child, &parents, &counter]);

        let mut sim = Self {
            cfg,
            n,
            pos,
            kin,
            body,
            acc,
            cur: 0,
            sort,
            k,
            sets,
            karras,
            groups,
            force_groups,
            _buffers: vec![bbox, child, parents, counter, node, common, force_common],
            time_myr: 0.0,
            steps: 0,
        };
        // the first step's half kick needs forces
        let mut enc = d.create_command_encoder(&Default::default());
        {
            let mut pass = enc.begin_compute_pass(&Default::default());
            sim.encode_forces(&mut pass);
        }
        gpu.queue.submit([enc.finish()]);
        Ok(sim)
    }

    /// Sort the current set into the other one, build the tree and find the forces; the other set becomes current.
    fn encode_forces(&mut self, pass: &mut wgpu::ComputePass) {
        let (s, o) = (self.cur, 1 - self.cur);
        let g = self.groups;
        self.k.morton.run(pass, "bbox_reset", &self.sets[s].morton, Groups { x: 1, y: 1 });
        self.k.morton.run(pass, "bbox_reduce", &self.sets[s].morton, g);
        self.k.morton.run(pass, "keys_main", &self.sets[s].morton, g);
        self.sort.encode(pass);
        self.k.gather.run(pass, "main", &self.sets[s].gather, g);
        self.k.karras.run(pass, "main", &self.karras, g);
        self.k.moments.run(pass, "main", &self.sets[o].moments, g);
        self.k.force.run(pass, "main", &self.sets[o].force, self.force_groups);
        self.cur = o;
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
        for _ in 0..k {
            self.k.integrate.run(&mut pass, "kick_drift", &self.sets[self.cur].integrate, self.groups);
            self.encode_forces(&mut pass);
            self.k.integrate.run(&mut pass, "kick", &self.sets[self.cur].integrate, self.groups);
        }
        drop(pass);
        self.steps += k as u64;
        self.time_myr += k as f64 * self.cfg.dt_myr;
    }

    /// The current positions (vertex buffer: vec4<u32> each).
    pub fn pos_buffer(&self) -> &wgpu::Buffer {
        &self.pos[self.cur]
    }

    /// The current (vx, vy, temperature, luminosity) (vertex buffer: vec4<f32> each).
    pub fn kin_buffer(&self) -> &wgpu::Buffer {
        &self.kin[self.cur]
    }

    pub fn read_state(&self, gpu: &Gpu) -> Result<State> {
        let pos: Vec<[u32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.pos[self.cur])?).to_vec();
        let kin: Vec<[f32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.kin[self.cur])?).to_vec();
        let body: Vec<[u32; 2]> = bytemuck::cast_slice(&gpu.read_buffer(&self.body[self.cur])?).to_vec();
        let acc: Vec<[f32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.acc)?).to_vec();
        let n = self.n as usize;
        let mut s = State {
            pos: vec![Fixed2 { x: 0, y: 0 }; n],
            vel: vec![[0.0; 2]; n],
            mass: vec![0.0; n],
            acc: vec![[0.0; 4]; n],
        };
        for i in 0..n {
            let id = body[i][1] as usize;
            s.pos[id] = Fixed2::from_words(pos[i]);
            s.vel[id] = [kin[i][0], kin[i][1]];
            s.mass[id] = f32::from_bits(body[i][0]);
            s.acc[id] = acc[i];
        }
        Ok(s)
    }

    /// Total energy: kinetic + the central mass's potential + half the self-gravity potential (from the tree, at
    /// the positions of the last force pass), Msun pc^2 / Myr^2.
    pub fn energy(&self, s: &State) -> f64 {
        s.vel
            .iter()
            .zip(&s.mass)
            .zip(&s.acc)
            .map(|((v, &m), a)| {
                let v2 = (v[0] as f64).powi(2) + (v[1] as f64).powi(2);
                m as f64 * (0.5 * v2 + a[3] as f64 + 0.5 * a[2] as f64)
            })
            .sum()
    }

    /// Total momentum, Msun pc / Myr.
    pub fn momentum(s: &State) -> [f64; 2] {
        s.vel.iter().zip(&s.mass).fold([0.0; 2], |p, (v, &m)| [p[0] + m as f64 * v[0] as f64, p[1] + m as f64 * v[1] as f64])
    }
}

/// FNV-1a over the position and velocity words in id order: equal runs give equal hashes.
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
