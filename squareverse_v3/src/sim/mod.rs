//! The simulation on the GPU. Phase 1: self-gravity by a Barnes-Hut tree, plus a central point mass (phase 2
//! makes it a super well), with block time steps.
//!
//! Time steps: the longest step is `dt_myr`; each particle takes dt / 2^bin (bin < `levels`), picked from its
//! acceleration, so the inner disc and close encounters take short steps and the slow outer disc long ones. A
//! step of dt is cut into 2^(levels - 1) sub-steps. Each sub-step:
//!
//! 1. `Open`: the opening half kick for particles whose step begins now; every particle drifts one sub-step;
//! 2. the tree: every `rebuild_every` sub-steps rebuilt (`Keys`, six `Sort` passes, `Build`: bounding box and
//!    48-bit Morton keys, radix sort, reorder into the other particle set, Karras radix tree, node moments), else
//!    `Refit` (the same tree, its moments recomputed for the new positions);
//! 3. `Force`: the tree walk for the particles whose step ends now, in up to `CHUNKS` slices;
//! 4. `Close`: their closing half kick, and each picks its next bin.
//!
//! Those are `Work` items. `encode_steps` runs whole steps (headless runs, tests); the window calls `advance`
//! each frame with a GPU time budget, which runs as many items as fit, so the frame rate holds and only the sim
//! slows (frames can fall between any two items, even between slices of one force pass). Every pass is
//! deterministic (integer atomics only) and where frames fall doesn't change the result: a seed gives the same
//! state on the same GPU and backend.

pub mod init;
pub mod reference;

use std::collections::VecDeque;

use anyhow::Result;
use serde::Serialize;
use wgpu::util::DeviceExt;

use crate::fixed::{Fixed2, TWO_32};
use crate::gpu::{AsyncRead, Gpu};
use crate::kernels::{Bind, DYN_STRIDE, Groups, Kernel, prelude, storage, uniform};
use crate::sort::{PASSES, RadixSort, Scan};
use crate::timing::GpuTimer;
use crate::units::G;
use init::Initial;

const NODE_WORDS: u64 = 16;
/// The force pass can be cut into at most this many slices.
pub const CHUNKS: u32 = 64;
/// Most time-step bins (the tick table has 2^(levels - 1) x CHUNKS entries).
pub const MAX_LEVELS: u32 = 8;

/// How the force pass walks the tree.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, clap::ValueEnum)]
pub enum Walk {
    /// 64 neighbouring particles walk together, sharing each node read (`shaders/force.wgsl`): more accurate.
    Group,
    /// One particle a thread (`shaders/force_particle.wgsl`): faster on the GPUs measured so far (the default).
    Particle,
}

impl Walk {
    /// The default walk. Measured 2026-11-06, 1M particles, theta 0.6: RTX 2070 Super on Vulkan, force pass 20.3 ms
    /// (particle) against 27.9 (group); Intel UHD 630 on DX12, 250k: 76 against 171 ms. The group walk is the more
    /// accurate at a given theta (median force error 5e-4 against 3e-3 at 0.6).
    pub fn for_gpu(_gpu: &Gpu) -> Self {
        Walk::Particle
    }

    fn workgroup(self) -> u32 {
        match self {
            Walk::Group => 64,     // force.wgsl GROUP
            Walk::Particle => 128, // force_particle.wgsl workgroup_size
        }
    }
}

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
    /// The longest time step (bin 0), Myr. A "step" (headless `--steps`, `encode_steps`) is one of these.
    pub dt_myr: f64,
    /// Time-step bins: bin b steps dt / 2^b, b < levels, so the shortest step is dt / 2^(levels - 1). 1: every
    /// particle steps dt (a plain leapfrog).
    pub levels: u32,
    /// Time-step accuracy: a particle steps at most sqrt(2 eta softening / |a|) ...
    pub eta: f64,
    /// ... and at most eta_jerk |a| / |da/dt| (da/dt over its last step; 0: off). The galaxy's pull dominates |a|,
    /// so this is what sees close encounters coming.
    pub eta_jerk: f64,
    /// The particles' softening (Plummer), pc.
    pub softening_pc: f64,
    /// Opening angle: a tree node acts as one mass (+ quadrupole) when its size / distance is below this.
    pub theta: f64,
    /// Nodes smaller than this many softening lengths act as one mass at any distance (unless they hold the
    /// particle): inside a dense clump that replaces most pairs with a few nodes. 0: off.
    pub open_small: f64,
    pub walk: Walk,
    /// Sub-steps between full tree rebuilds (sort + build); between them the tree is only refitted to the new
    /// positions. 1: rebuild every sub-step.
    pub rebuild_every: u32,
    /// Random speed spread, as a fraction of the circular speed.
    pub dispersion: f64,
    /// What `Sim::new` builds.
    pub scene: Scene,
    /// The galaxy (`Scene::Galaxy`).
    pub galaxy: init::GalaxyConfig,
    /// Softening of dark matter particles and of super wells, pc (stars and remnants use `softening_pc`). Large
    /// for dark matter, so its few heavy particles act as a smooth field and don't kick the stars about.
    pub dm_softening_pc: f64,
    pub well_softening_pc: f64,
    /// A super well swallows particles bound to it within this, pc.
    pub accretion_pc: f64,
}

/// The starting scene.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, clap::ValueEnum)]
pub enum Scene {
    /// A galaxy in equilibrium: disc, bulge, dark matter halo and a central super well (`init::galaxy`).
    Galaxy,
    /// The phase-1 test disc: stars round a fixed central point mass (`init::build`).
    Disc,
}

impl Default for SimConfig {
    fn default() -> Self {
        let box_pc = 20_000_000.0; // 20 Mpc: the scale of the universe view
        Self {
            particles: 200_000,
            seed: 1,
            box_pc,
            center_pc: (box_pc / 2.0, box_pc / 2.0),
            central_mass: 0.0, // the galaxy has its own super well
            central_softening_pc: 50.0,
            disc_mass: 2e9,
            r_in_pc: 1_000.0,
            r_out_pc: 15_000.0,
            // 2 Myr down to 1/32: the outer disc wants ~2, the bulge's centre (orbits of a few Myr) the shortest.
            // With 5 levels (down to 0.125) the bulge swelled 590 -> 3,700 pc in 100 Myr and the energy rose 35%
            // (2026-11-08, 50k); with 7 it holds (984 -> 1,026 pc, energy within 0.8%)
            dt_myr: 2.0,
            levels: 7,
            eta: 0.025,
            // ~60 steps an orbit; 0.05 cost 290 against 170 GPU ms per Myr at 500k (RTX 2070 Super, 2026-11-08)
            // for the same energy behaviour in the smooth galaxy
            eta_jerk: 0.1,
            // about half the disc's particle spacing at 50k, and a stand-in for its thickness
            softening_pc: 50.0,
            theta: 0.6,
            open_small: 0.0,
            rebuild_every: 8,
            walk: Walk::Particle,
            dispersion: 0.1,
            scene: Scene::Galaxy,
            galaxy: init::GalaxyConfig::default(),
            // the halo is smooth on kpc scales; 300 pc let its heavy particles heat the disc (σ_R 65 -> 107 pc/Myr
            // at one scale length in 500 Myr, 100k), 1,000 kept it at 72 -> 73 (2026-11-08)
            dm_softening_pc: 1_000.0,
            well_softening_pc: 50.0,
            accretion_pc: 2.0,
        }
    }
}

impl SimConfig {
    /// The phase-1 test disc: stars round a fixed central point mass of 1e10 Msun, softening 20 pc, steps 2 Myr
    /// down to 0.125. The tests' scene.
    pub fn test_disc() -> Self {
        Self {
            scene: Scene::Disc,
            central_mass: 1e10,
            levels: 5,
            eta_jerk: 0.05,
            softening_pc: 20.0,
            well_softening_pc: 20.0,
            ..Self::default()
        }
    }

    /// The defaults for a scene.
    pub fn for_scene(scene: Scene) -> Self {
        match scene {
            Scene::Galaxy => Self::default(),
            Scene::Disc => Self::test_disc(),
        }
    }

    /// The sub-step (the shortest time step), Myr.
    pub fn dt_min(&self) -> f64 {
        self.dt_myr / (1u64 << (self.levels.clamp(1, MAX_LEVELS) - 1)) as f64
    }

    /// How far out the scene reaches (the window's first view shows about this radius), pc.
    pub fn view_radius_pc(&self) -> f64 {
        match self.scene {
            Scene::Galaxy => self.galaxy.disc_scale_pc * self.galaxy.disc_cut,
            Scene::Disc => self.r_out_pc,
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
    levels: u32,
    dt_min: f32,
    eta_eps: f32,
    eta_jerk: f32,
    open_small: f32,
    n_wells: u32,
    acc_r2: f32,
    single_stars: u32,
    eps2_kind: [[f32; 4]; 2],
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Tick {
    s: u32,
    start: u32,
    _a: u32,
    _b: u32,
}

/// Particle state read back from the GPU, in id order.
pub struct State {
    pub pos: Vec<Fixed2>,
    pub vel: Vec<[f32; 2]>,
    pub mass: Vec<f32>,
    /// (ax, ay, phi_self, phi_central) from each particle's last force pass.
    pub acc: Vec<[f32; 4]>,
    /// Kind (`init::Kind` as u32), (temperature K, luminosity Lsun), and the `about` record (birth time Myr, star
    /// mass, mass at birth, well number bits).
    pub kind: Vec<u32>,
    pub star: Vec<[f32; 2]>,
    pub about: Vec<[f32; 4]>,
}

/// One piece of a sub-step (see the module comment). Frames can fall between any two.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Work {
    Open,
    Keys,
    Sort(u32),
    Build,
    Refit,
    /// Stellar evolution and super wells swallowing, at the start of each step of dt (`evolve.wgsl`).
    Evolve,
    /// The list of particles whose step ends this sub-step.
    Compact,
    /// Force slices `from .. to` of the list (of up to `CHUNKS`).
    Force { from: u32, to: u32 },
    Close,
}

/// The stages GPU time is split into (timer labels).
pub const STAGES: [&str; 7] = ["integrate", "sort", "build", "refit", "compact", "force", "evolve"];
const FORCE: usize = 5;
/// A force dispatch costs at least one tree walk's latency however few particles it has (the GPU isn't full):
/// measured 2026-11-07 on the RTX 2070 Super, 2.2 of 10.7 ms at 500k, 4.5 of 21.5 at 1M.
const FORCE_FLOOR: f64 = 0.2;

impl Work {
    fn label(self) -> &'static str {
        match self {
            Work::Open | Work::Close => "integrate",
            Work::Keys | Work::Sort(_) => "sort",
            Work::Build => "build",
            Work::Refit => "refit",
            Work::Compact => "compact",
            Work::Evolve => "evolve",
            Work::Force { .. } => "force",
        }
    }
}

/// How much a frame may do (`Sim::advance`).
#[derive(Clone, Copy, Debug)]
pub struct Limit {
    /// Estimated GPU ms; the first item always runs, so the sim always moves, and an item starts when four fifths
    /// of it fit, so a frame can overrun by up to a quarter of an item (`advance` returns the estimate actually spent).
    pub budget_ms: f64,
    /// How many new sub-steps may be started.
    pub new_sub_steps: u32,
}

/// The bind groups that read or write one particle set.
struct SetBinds {
    integrate: wgpu::BindGroup,
    morton: wgpu::BindGroup,
    /// this set -> the other one
    gather: wgpu::BindGroup,
    gather_step: wgpu::BindGroup,
    evolve: wgpu::BindGroup,
    compact: wgpu::BindGroup,
    moments: wgpu::BindGroup,
    force: wgpu::BindGroup,
}

struct Kernels {
    integrate: Kernel,
    morton: Kernel,
    gather: Kernel,
    gather_step: Kernel,
    evolve: Kernel,
    compact: Kernel,
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
    acc: [wgpu::Buffer; 2],
    _bins: [wgpu::Buffer; 2],
    about: [wgpu::Buffer; 2],
    n_wells: u32,
    /// particles in each bin (u32 x MAX_LEVELS)
    counts: wgpu::Buffer,
    /// which particle set is current
    cur: usize,
    sort: RadixSort,
    flag_scan: Scan,
    k: Kernels,
    sets: [SetBinds; 2],
    karras: wgpu::BindGroup,
    groups: Groups,
    /// workgroups in a force slice, and how many slices
    chunk_groups: u32,
    chunks: u32,
    /// sub-steps in a step: 2^(levels - 1)
    subs: u32,
    /// the sub-step under way (0 .. subs) and what is left of it
    sub: u32,
    queue: VecDeque<Work>,
    /// sub-steps finished, and drifted (one ahead while a sub-step is under way)
    sub_done: u64,
    sub_drifted: u64,
    /// steps (of dt) finished
    pub steps: u64,
    /// the bin counts as last read back (for the cost estimates and the HUD)
    pub bin_counts: [u32; MAX_LEVELS as usize],
    counts_read: AsyncRead,
    /// estimated GPU ms per unit of work, by `STAGES` label (force: a full pass)
    rates: [f64; 7],
    _buffers: Vec<wgpu::Buffer>,
}

fn begin<'e>(encoder: &'e mut wgpu::CommandEncoder, timer: &mut GpuTimer, label: &'static str, units: f64) -> wgpu::ComputePass<'e> {
    encoder.begin_compute_pass(&wgpu::ComputePassDescriptor { label: Some(label), timestamp_writes: timer.compute_units(label, units) })
}

fn module(body: &str) -> String {
    format!("{}{}", prelude(), body)
}

impl Sim {
    pub fn new(gpu: &Gpu, cfg: SimConfig) -> Result<Self> {
        match cfg.scene {
            Scene::Disc => {
                let init = init::build(&cfg);
                Self::from_initial(gpu, cfg, &init)
            }
            Scene::Galaxy => {
                // positions first; the velocities come from the forces they give (`init::galaxy_velocities`)
                let (init, parts) = init::galaxy(&cfg);
                let sim = Self::from_initial(gpu, cfg, &init)?;
                let s = sim.read_state(gpu)?;
                let kin = init::galaxy_velocities(&sim.cfg, &init, &parts, &s);
                sim.write_kin(gpu, &kin)?;
                Ok(sim)
            }
        }
    }

    /// Replaces every particle's (vx, vy, temperature, luminosity), given in id order.
    pub fn write_kin(&self, gpu: &Gpu, kin_by_id: &[[f32; 4]]) -> Result<()> {
        let body: Vec<[u32; 2]> = bytemuck::cast_slice(&gpu.read_buffer(&self.body[self.cur])?).to_vec();
        let sorted: Vec<[f32; 4]> = body.iter().map(|b| kin_by_id[(b[1] & init::ID_MASK) as usize]).collect();
        gpu.queue.write_buffer(&self.kin[self.cur], 0, bytemuck::cast_slice(&sorted));
        gpu.wait()
    }

    /// From given particles (tests and other scenes); `cfg.particles` is taken from them.
    pub fn from_initial(gpu: &Gpu, mut cfg: SimConfig, init: &Initial) -> Result<Self> {
        let d = &gpu.device;
        let n = init.len() as u32;
        anyhow::ensure!(n >= 1, "a universe needs at least one particle");
        anyhow::ensure!((1..=MAX_LEVELS).contains(&cfg.levels), "time-step levels must be 1 to {MAX_LEVELS}");
        cfg.particles = n;
        let levels = cfg.levels;
        let subs = 1u32 << (levels - 1);
        let groups = Groups::for_items(n, 256);
        let wg = cfg.walk.workgroup();
        let force_groups = Groups::for_items(n, wg);
        // a slice of k chunks dispatches Groups::count(k * chunk_groups): its rows are as long as the full pass's
        // whenever it has more than one, so one `row` serves every slice
        let force_row = force_groups.x * wg;
        let chunk = n.div_ceil(CHUNKS).div_ceil(wg) * wg;
        let chunks = n.div_ceil(chunk);

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
        let body = [make("body 0", bytemuck::cast_slice(&init.body), true), make("body 1", bytemuck::cast_slice(&init.body), true)];
        let acc = [storage(d, "acc 0", n as u64 * 16), storage(d, "acc 1", n as u64 * 16)];
        let bins = [storage(d, "bins 0", n as u64 * 16), storage(d, "bins 1", n as u64 * 16)];
        let about = [make("about 0", bytemuck::cast_slice(&init.about), false), make("about 1", bytemuck::cast_slice(&init.about), false)];
        // stellar evolution's clock, the wells' particle indices and what they swallowed (evolve.wgsl)
        let clock = storage(d, "clock", 16);
        let wells = storage(d, "wells", init.wells.max(1) as u64 * 4);
        let sink = storage(d, "sink", init.wells.max(1) as u64 * 6 * 4);
        let counts = storage(d, "bin counts", MAX_LEVELS as u64 * 4);
        // the list of particles whose step ends this sub-step (compact.wgsl)
        let flags = storage(d, "active flags", n as u64 * 4);
        let active = storage(d, "active", n as u64 * 4);
        let active_n = storage(d, "active count", 16);
        let flag_scan = Scan::new(d, &flags, n);
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
        let common_with_row = |row: u32| Common {
            center: center.words(),
            n,
            row,
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
            levels,
            dt_min: cfg.dt_min() as f32,
            eta_eps: (2.0 * cfg.eta * cfg.softening_pc) as f32,
            eta_jerk: cfg.eta_jerk as f32,
            open_small: (cfg.open_small * cfg.softening_pc) as f32,
            n_wells: init.wells,
            acc_r2: cfg.accretion_pc.powi(2) as f32,
            single_stars: init.single_stars as u32,
            eps2_kind: {
                let (st, dm, w) = (cfg.softening_pc.powi(2) as f32, cfg.dm_softening_pc.powi(2) as f32, cfg.well_softening_pc.powi(2) as f32);
                // K_STAR, K_DM, K_WELL, K_WD | K_NS, K_BH, K_GONE, -
                [[st, dm, w, st], [st, st, st, st]]
            },
        };
        let common = uniform(d, "common", &common_with_row(groups.x * 256));
        // the force pass's workgroups have their own size, so its rows have their own length
        let force_common = uniform(d, "common (force)", &common_with_row(force_row));
        // the tick table: entry s * CHUNKS + j is sub-step s, force slice from chunk j
        let mut ticks = vec![0u8; (subs * CHUNKS) as usize * DYN_STRIDE as usize];
        for s in 0..subs {
            for j in 0..CHUNKS {
                let at = (s * CHUNKS + j) as usize * DYN_STRIDE as usize;
                let t = Tick { s, start: j * chunk, _a: 0, _b: 0 };
                ticks[at..at + 16].copy_from_slice(bytemuck::bytes_of(&t));
            }
        }
        let tick = d.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("ticks"),
            contents: &ticks,
            usage: wgpu::BufferUsages::UNIFORM,
        });

        use Bind::{DynUniform as T, Read as R, Uniform as U, Write as W};
        let k = Kernels {
            integrate: Kernel::new(
                d,
                "integrate",
                &module(include_str!("../../shaders/integrate.wgsl")),
                &[U, W, W, R, W, W, T],
                &["kick_drift", "kick", "init_bins"],
            ),
            morton: Kernel::new(
                d,
                "morton",
                &module(include_str!("../../shaders/morton.wgsl")),
                &[U, R, W, W, W, R],
                &["bbox_reset", "bbox_reduce", "keys_main"],
            ),
            gather: Kernel::new(d, "gather", &module(include_str!("../../shaders/gather.wgsl")), &[U, R, R, R, R, W, W, W], &["main"]),
            gather_step: Kernel::new(
                d,
                "gather step",
                &module(include_str!("../../shaders/gather_step.wgsl")),
                &[U, R, R, R, W, W, R, W],
                &["main"],
            ),
            evolve: Kernel::new(
                d,
                "evolve",
                &module(include_str!("../../shaders/evolve.wgsl")),
                &[U, R, W, W, R, W, W, W],
                &["evolve", "tick_clock", "find_wells", "swallow", "swallow_apply"],
            ),
            compact: Kernel::new(d, "compact", &module(include_str!("../../shaders/compact.wgsl")), &[U, R, W, W, W, T], &["flag", "scatter"]),
            karras: Kernel::new(d, "karras", &module(include_str!("../../shaders/karras.wgsl")), &[U, R, W, W, W], &["main"]),
            moments: Kernel::new(
                d,
                "moments",
                &module(include_str!("../../shaders/moments.wgsl")),
                &[U, R, R, R, R, W, W],
                &["reset", "main"],
            ),
            force: Kernel::new(
                d,
                "force",
                &module(match cfg.walk {
                    Walk::Group => include_str!("../../shaders/force.wgsl"),
                    Walk::Particle => include_str!("../../shaders/force_particle.wgsl"),
                }),
                &[U, R, R, R, R, W, R, T, R],
                &["main"],
            ),
        };
        let sort = RadixSort::new(d, n);
        let set = |s: usize| {
            let o = 1 - s;
            SetBinds {
                integrate: k.integrate.bind(d, "integrate", &[&common, &pos[s], &kin[s], &acc[s], &bins[s], &counts, &tick]),
                morton: k.morton.bind(d, "morton", &[&common, &pos[s], &bbox, &sort.keys[0], &sort.vals[0], &body[s]]),
                gather: k.gather.bind(d, "gather", &[&common, &sort.vals[0], &pos[s], &kin[s], &body[s], &pos[o], &kin[o], &body[o]]),
                gather_step: k.gather_step.bind(
                    d,
                    "gather step",
                    &[&common, &sort.vals[0], &acc[s], &bins[s], &acc[o], &bins[o], &about[s], &about[o]],
                ),
                evolve: k.evolve.bind(d, "evolve", &[&common, &pos[s], &kin[s], &body[s], &about[s], &clock, &wells, &sink]),
                compact: k.compact.bind(d, "compact", &[&common, &bins[s], &flags, &active, &active_n, &tick]),
                moments: k.moments.bind(d, "moments", &[&common, &pos[s], &body[s], &child, &parents, &counter, &node]),
                force: k.force.bind(d, "force", &[&force_common, &pos[s], &body[s], &child, &node, &acc[s], &active, &tick, &active_n]),
            }
        };
        let sets = [set(0), set(1)];
        let karras = k.karras.bind(d, "karras", &[&common, &sort.keys[0], &child, &parents, &counter]);

        // first guesses of GPU ms per unit (a little pessimistic: a laptop's integrated GPU); measurements replace them
        let per = n as f64;
        let rates = [3e-6 * per, 1.5e-5 * per, 2e-5 * per, 1.5e-5 * per, 1e-5 * per, 2e-4 * per, 1e-5 * per];
        let mut sim = Self {
            cfg,
            n,
            pos,
            kin,
            body,
            acc,
            _bins: bins,
            counts,
            cur: 0,
            sort,
            flag_scan,
            k,
            sets,
            karras,
            groups,
            chunk_groups: chunk / wg,
            chunks,
            subs,
            sub: 0,
            queue: VecDeque::new(),
            sub_done: 0,
            sub_drifted: 0,
            steps: 0,
            bin_counts: [0; MAX_LEVELS as usize],
            counts_read: AsyncRead::new(d, "bin counts read", MAX_LEVELS as u64 * 4),
            rates,
            about,
            n_wells: init.wells,
            _buffers: vec![bbox, child, parents, counter, node, common, force_common, tick, flags, active, active_n, clock, wells, sink],
        };
        // the first forces, for every particle (they all start in bin 0, and at the last sub-step every bin's step
        // ends), then everyone's first bin
        let mut enc = d.create_command_encoder(&Default::default());
        let mut timer = GpuTimer::new(d, &gpu.queue, false);
        // the stars' state at the start (no clock tick: the first step's evolution runs again at the same time)
        sim.encode_evolve(&mut enc, &mut timer, false);
        let last = sim.subs - 1;
        let first = [Work::Build, Work::Compact, Work::Force { from: 0, to: sim.chunks }];
        for w in [Work::Keys].into_iter().chain((0..PASSES).map(Work::Sort)).chain(first) {
            sim.encode_item(&mut enc, &mut timer, w, last);
        }
        {
            let mut pass = begin(&mut enc, &mut timer, "integrate", 1.0);
            sim.k.integrate.run_at(&mut pass, "init_bins", &sim.sets[sim.cur].integrate, &[0], sim.groups);
        }
        gpu.queue.submit([enc.finish()]);
        Ok(sim)
    }

    fn tick_offset(&self, s: u32, chunk: u32) -> u32 {
        ((s * CHUNKS + chunk) as u64 * DYN_STRIDE) as u32
    }

    /// Stellar evolution, then super wells swallowing (and, with `tick`, the clock moves on a step).
    fn encode_evolve(&mut self, encoder: &mut wgpu::CommandEncoder, timer: &mut GpuTimer, tick: bool) {
        let mut pass = begin(encoder, timer, "evolve", 1.0);
        let (b, g) = (&self.sets[self.cur].evolve, self.groups);
        self.k.evolve.run(&mut pass, "evolve", b, g);
        if self.n_wells > 0 {
            self.k.evolve.run(&mut pass, "find_wells", b, g);
            self.k.evolve.run(&mut pass, "swallow", b, g);
            self.k.evolve.run(&mut pass, "swallow_apply", b, Groups::for_items(self.n_wells, 64));
        }
        if tick {
            self.k.evolve.run(&mut pass, "tick_clock", b, Groups { x: 1, y: 1 });
        }
    }

    /// The work of the next sub-step.
    fn plan(&mut self) {
        if self.sub == 0 {
            self.queue.push_back(Work::Evolve);
        }
        self.queue.push_back(Work::Open);
        if (self.sub_done + 1).is_multiple_of(self.cfg.rebuild_every.max(1) as u64) {
            self.queue.push_back(Work::Keys);
            self.queue.extend((0..PASSES).map(Work::Sort));
            self.queue.push_back(Work::Build);
        } else {
            self.queue.push_back(Work::Refit);
        }
        self.queue.push_back(Work::Compact);
        self.queue.push_back(Work::Force { from: 0, to: self.chunks });
        self.queue.push_back(Work::Close);
    }

    /// The share of the particles whose step ends at sub-step s (from the last bin counts read; 1 until there are some).
    fn ending_share(&self, s: u32) -> f64 {
        let total: u64 = self.bin_counts.iter().map(|&c| c as u64).sum();
        if total == 0 {
            return 1.0;
        }
        let ending: u64 = (0..self.cfg.levels)
            .filter(|&b| (s + 1).is_multiple_of(1 << (self.cfg.levels - 1 - b)))
            .map(|b| self.bin_counts[b as usize] as u64)
            .sum();
        ending as f64 / total as f64
    }

    /// The share of the force list's slots `from .. to` that hold particles (estimated from the bin counts).
    fn busy(&self, from: u32, to: u32) -> f64 {
        let listed = self.ending_share(self.sub) * self.chunks as f64;
        (listed.min(to as f64) - from as f64).clamp(0.0, (to - from) as f64) / self.chunks as f64
    }

    /// Work units of an item, for the timer (a force slice: its busy share of a full pass).
    fn units(&self, w: Work) -> f64 {
        match w {
            Work::Force { from, to } => self.busy(from, to),
            _ => 1.0,
        }
    }

    /// Estimated GPU ms (a force slice: at least `FORCE_FLOOR` of a full pass, unless it holds no particles).
    fn estimate(&self, w: Work) -> f64 {
        match w {
            Work::Force { from, to } => {
                let busy = self.busy(from, to);
                if busy <= 0.0 { 0.02 } else { self.rates[FORCE] * busy.max(FORCE_FLOOR) }
            }
            _ => self.rates[STAGES.iter().position(|&l| l == w.label()).expect("a stage label")],
        }
    }

    fn encode_item(&mut self, encoder: &mut wgpu::CommandEncoder, timer: &mut GpuTimer, w: Work, s: u32) {
        let units = self.units(w);
        let mut pass = begin(encoder, timer, w.label(), units);
        let (c, g) = (self.cur, self.groups);
        let tick = self.tick_offset(s, 0);
        match w {
            Work::Open => self.k.integrate.run_at(&mut pass, "kick_drift", &self.sets[c].integrate, &[tick], g),
            Work::Close => self.k.integrate.run_at(&mut pass, "kick", &self.sets[c].integrate, &[tick], g),
            Work::Keys => {
                self.k.morton.run(&mut pass, "bbox_reset", &self.sets[c].morton, Groups { x: 1, y: 1 });
                self.k.morton.run(&mut pass, "bbox_reduce", &self.sets[c].morton, g);
                self.k.morton.run(&mut pass, "keys_main", &self.sets[c].morton, g);
            }
            Work::Sort(p) => self.sort.encode_pass(&mut pass, p),
            Work::Build => {
                self.k.gather.run(&mut pass, "main", &self.sets[c].gather, g);
                self.k.gather_step.run(&mut pass, "main", &self.sets[c].gather_step, g);
                self.k.karras.run(&mut pass, "main", &self.karras, g);
                self.cur = 1 - c;
                self.k.moments.run(&mut pass, "main", &self.sets[self.cur].moments, g);
            }
            Work::Refit => {
                self.k.moments.run(&mut pass, "reset", &self.sets[c].moments, g);
                self.k.moments.run(&mut pass, "main", &self.sets[c].moments, g);
            }
            Work::Compact => {
                self.k.compact.run_at(&mut pass, "flag", &self.sets[c].compact, &[tick], g);
                self.flag_scan.encode(&mut pass);
                self.k.compact.run_at(&mut pass, "scatter", &self.sets[c].compact, &[tick], g);
            }
            Work::Force { from, to } => {
                let groups = Groups::count((to - from) * self.chunk_groups);
                self.k.force.run_at(&mut pass, "main", &self.sets[c].force, &[self.tick_offset(s, from)], groups);
            }
            Work::Evolve => {
                drop(pass);
                self.encode_evolve(encoder, timer, true);
            }
        }
    }

    /// Runs one item of the current sub-step (planning the next sub-step first if none is under way).
    fn step_item(&mut self, encoder: &mut wgpu::CommandEncoder, timer: &mut GpuTimer, w: Work) {
        self.encode_item(encoder, timer, w, self.sub);
        match w {
            Work::Open => self.sub_drifted += 1,
            Work::Close => {
                self.sub_done += 1;
                self.sub += 1;
                if self.sub == self.subs {
                    self.sub = 0;
                    self.steps += 1;
                }
            }
            _ => {}
        }
    }

    /// Records as much work as fits the limit (always at least one item); returns the estimated GPU ms. Also
    /// records a read-back of the bin counts (call `after_submit` and `collect` around the submit).
    pub fn advance(&mut self, encoder: &mut wgpu::CommandEncoder, timer: &mut GpuTimer, limit: Limit) -> f64 {
        let mut spent = 0.0;
        let mut new_subs = limit.new_sub_steps;
        loop {
            if self.queue.is_empty() {
                if new_subs == 0 {
                    break;
                }
                new_subs -= 1;
                self.plan();
            }
            let w = self.queue[0];
            let est = self.estimate(w);
            if let Work::Force { from, to } = w {
                // the longest slice that fits; with nothing spent yet, at least what costs no more than the floor
                let floor = self.rates[FORCE] * FORCE_FLOOR;
                // an item may start when four fifths of it fit (the window takes any overrun off the next frame)
                let room = if spent == 0.0 { (1.25 * limit.budget_ms).max(floor) } else { 1.25 * (limit.budget_ms - spent) };
                let k = (1..=to - from).rev().find(|&k| self.estimate(Work::Force { from, to: from + k }) <= room).unwrap_or(0);
                let k = if spent == 0.0 { k.max(1) } else { k };
                if k == 0 {
                    break;
                }
                let part = Work::Force { from, to: from + k };
                spent += self.estimate(part);
                self.step_item(encoder, timer, part);
                if from + k < to {
                    self.queue[0] = Work::Force { from: from + k, to };
                    break;
                }
                self.queue.pop_front();
            } else {
                if spent > 0.0 && est > 1.25 * (limit.budget_ms - spent) {
                    break;
                }
                self.queue.pop_front();
                self.step_item(encoder, timer, w);
                spent += est;
            }
        }
        self.counts_read.copy(encoder, &self.counts);
        spent
    }

    pub fn after_submit(&mut self) {
        self.counts_read.after_submit();
    }

    /// Picks up the bin counts once read back, and the GPU times of the last timed frame (call after polling).
    pub fn collect(&mut self, timer: Option<&GpuTimer>) {
        if let Some(data) = self.counts_read.take() {
            let c: &[u32] = bytemuck::cast_slice(&data);
            self.bin_counts.copy_from_slice(c);
        }
        if let Some(t) = timer {
            for (i, label) in STAGES.iter().enumerate().filter(|&(i, _)| i != FORCE) {
                if let Some((ms, units)) = t.rate(label)
                    && units > 1e-6
                {
                    self.rates[i] += 0.3 * (ms / units - self.rates[i]);
                }
            }
            // force passes: a full pass costs ms / max(busy, floor share)
            let (mut ms_sum, mut units) = (0.0, 0.0);
            for ((label, ms), &busy) in t.last.iter().zip(&t.last_units) {
                if *label == "force" && busy > 0.0 {
                    ms_sum += ms;
                    units += busy.max(FORCE_FLOOR);
                }
            }
            if units > 0.0 {
                self.rates[FORCE] += 0.3 * (ms_sum / units - self.rates[FORCE]);
            }
        }
    }

    /// Records `k` whole steps (of dt) into the encoder, finishing a step under way first.
    pub fn encode_steps(&mut self, encoder: &mut wgpu::CommandEncoder, k: u32, timer: &mut GpuTimer) {
        // a step under way counts as the first of the k
        let target = self.steps + k as u64;
        while self.steps < target {
            if self.queue.is_empty() {
                self.plan();
            }
            let w = self.queue.pop_front().expect("planned");
            self.step_item(encoder, timer, w);
        }
    }

    /// Sim time of the finished sub-steps, Myr.
    pub fn time_myr(&self) -> f64 {
        self.sub_done as f64 * self.cfg.dt_min()
    }

    /// Sim time of the positions as they are now (a sub-step ahead of `time_myr` while one is under way), Myr.
    pub fn pos_time_myr(&self) -> f64 {
        self.sub_drifted as f64 * self.cfg.dt_min()
    }

    /// Sub-steps in a step of dt.
    pub fn sub_steps(&self) -> u32 {
        self.subs
    }

    /// Force evaluations per particle per Myr with the given bin counts (bin b steps 2^b times per dt).
    pub fn evals_per_myr(&self, counts: &[u32]) -> f64 {
        let total: f64 = counts.iter().map(|&c| c as f64).sum();
        let evals: f64 = counts.iter().enumerate().map(|(b, &c)| c as f64 * (1u64 << b) as f64).sum();
        if total > 0.0 { evals / total / self.cfg.dt_myr } else { 0.0 }
    }

    fn about_buffer(&self) -> &wgpu::Buffer {
        &self.about[self.cur]
    }

    /// The current (mass bits, kind << 28 | id) (vertex buffer: vec2<u32> each).
    pub fn body_buffer(&self) -> &wgpu::Buffer {
        &self.body[self.cur]
    }

    /// The current positions (vertex buffer: vec4<u32> each).
    pub fn pos_buffer(&self) -> &wgpu::Buffer {
        &self.pos[self.cur]
    }

    /// The current (vx, vy, temperature, luminosity) (vertex buffer: vec4<f32> each).
    pub fn kin_buffer(&self) -> &wgpu::Buffer {
        &self.kin[self.cur]
    }

    /// The bin counts, waiting for the GPU.
    pub fn read_counts(&self, gpu: &Gpu) -> Result<Vec<u32>> {
        Ok(bytemuck::cast_slice(&gpu.read_buffer(&self.counts)?)[..self.cfg.levels as usize].to_vec())
    }

    /// The state, in id order. Velocities are synchronised (every particle's step ended at the same time) only
    /// between steps of dt, which is where `encode_steps` leaves the sim.
    pub fn read_state(&self, gpu: &Gpu) -> Result<State> {
        let pos: Vec<[u32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.pos[self.cur])?).to_vec();
        let kin: Vec<[f32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.kin[self.cur])?).to_vec();
        let body: Vec<[u32; 2]> = bytemuck::cast_slice(&gpu.read_buffer(&self.body[self.cur])?).to_vec();
        let about: Vec<[f32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(self.about_buffer())?).to_vec();
        let acc: Vec<[f32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.acc[self.cur])?).to_vec();
        let n = self.n as usize;
        let mut s = State {
            pos: vec![Fixed2 { x: 0, y: 0 }; n],
            vel: vec![[0.0; 2]; n],
            mass: vec![0.0; n],
            acc: vec![[0.0; 4]; n],
            kind: vec![0; n],
            star: vec![[0.0; 2]; n],
            about: vec![[0.0; 4]; n],
        };
        for i in 0..n {
            let id = (body[i][1] & init::ID_MASK) as usize;
            s.pos[id] = Fixed2::from_words(pos[i]);
            s.vel[id] = [kin[i][0], kin[i][1]];
            s.mass[id] = f32::from_bits(body[i][0]);
            s.acc[id] = acc[i];
            s.kind[id] = body[i][1] >> init::KIND_SHIFT;
            s.star[id] = [kin[i][2], kin[i][3]];
            s.about[id] = about[i];
        }
        Ok(s)
    }

    /// Total energy: kinetic + the central mass's potential + half the self-gravity potential (from the tree, at
    /// each particle's last force pass, so exact between steps of dt), Msun pc^2 / Myr^2.
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
