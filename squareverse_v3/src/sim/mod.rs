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

pub mod cosmo;
pub mod init;
pub mod reference;

use std::collections::VecDeque;

use anyhow::Result;
use serde::Serialize;
use wgpu::util::DeviceExt;

use crate::fixed::{Fixed2, TWO_32};
use crate::gpu::{AsyncRead, Gpu};
use crate::kernels::{Bind, DYN_STRIDE, Groups, Kernel, prelude, storage, uniform};
use bytemuck::Zeroable;
use crate::sort::{PASSES, RadixSort, Scan};
use crate::timing::GpuTimer;
use crate::units::G;
use init::Initial;

const NODE_WORDS: u64 = 20;
/// The force pass can be cut into at most this many slices.
pub const CHUNKS: u32 = 64;
/// Most time-step bins (the tick table has 2^(levels - 1) x CHUNKS entries).
pub const MAX_LEVELS: u32 = 8;

/// How the force pass walks the tree.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, serde::Deserialize, clap::ValueEnum)]
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

#[derive(Clone, Debug, Serialize, serde::Deserialize)]
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
    /// Gas physics (phase 3).
    pub gas: GasConfig,
    /// Super wells (phase 4).
    pub wells: WellConfig,
    /// Mesh gravity for the long range (TreePM, shaders/pm.wgsl): cells a side, a power of two up to 1024 (0: none,
    /// the tree does everything, fine while the particles keep well inside the box).
    pub pm_cells: u32,
    /// The expanding universe (`Scene::Universe`); None: a static box.
    pub cosmology: Option<cosmo::Cosmology>,
    /// The galaxy finder (shaders/finder.wgsl).
    pub finder: FinderConfig,
    /// Spare particle slots kept for the window's tools (new galaxies, wells, gas), as a share of the particles:
    /// massless (K_GONE) particles parked at the centre, which cost no forces.
    #[serde(default)]
    pub spare_share: f64,
    /// Steps of dt already run (a saved universe carries on from here; 0 for a new one).
    #[serde(default)]
    pub start_steps: u64,
}

/// The galaxy finder: friends of friends every `every_myr` (0: off).
#[derive(Clone, Debug, Serialize, serde::Deserialize)]
pub struct FinderConfig {
    pub every_myr: f64,
    /// Particles closer than this (physical pc) are friends; 0: 0.2 of the dark matter's mean spacing, comoving
    /// (the universe).
    pub link_pc: f64,
    /// Dark matter takes part (halos); else only stars, gas and wells (the visible galaxies).
    pub dark_matter: bool,
    /// Smaller groups aren't listed.
    pub min_members: u32,
}

impl Default for FinderConfig {
    fn default() -> Self {
        // 300 pc links the discs at the default counts; 1.5 kpc cost the finder ~1 s at 500k, 500 pc ~0.45 s
        // (2026-11-09, RTX 2070 Super), so it runs every 200 Myr, spread over frames
        Self { every_myr: 200.0, link_pc: 300.0, dark_matter: false, min_members: 32 }
    }
}

/// Super wells: accretion, feedback, dynamical friction, mergers, and new ones from direct collapse (wells_env.wgsl).
#[derive(Clone, Debug, Serialize, serde::Deserialize)]
pub struct WellConfig {
    /// Bondi accretion from the nearest gas, capped at Eddington (M / `salpeter_myr` a Myr).
    pub bondi: bool,
    pub salpeter_myr: f64,
    /// The share of accreted mc² that heats the gas (radiative 0.1 x coupling 0.15).
    pub agn_efficiency: f64,
    /// Chandrasekhar dynamical friction from the field within `surroundings_pc`, for wells too light to feel it.
    pub friction: bool,
    pub surroundings_pc: f64,
    /// Two wells closer than this and bound merge, pc.
    pub merge_pc: f64,
    /// Dense, metal-poor, massive gas becomes a seed well: metallicity under this (solar = 1), hydrogen density
    /// over this (cm^-3), the gas particle's mass over this (Msun).
    pub direct_collapse: bool,
    pub collapse_max_metallicity: f64,
    pub collapse_density_cm3: f64,
    pub collapse_min_mass: f64,
}

impl Default for WellConfig {
    fn default() -> Self {
        Self {
            bondi: true,
            salpeter_myr: 45.0,
            agn_efficiency: 0.015,
            friction: true,
            surroundings_pc: 500.0,
            merge_pc: 100.0,
            direct_collapse: true,
            collapse_max_metallicity: 1e-3,
            collapse_density_cm3: 10.0,
            collapse_min_mass: 1e4,
        }
    }
}

/// Gas: SPH, cooling, star formation and feedback (shaders/hydro.wgsl, integrate.wgsl, evolve.wgsl, feedback*.wgsl).
#[derive(Clone, Debug, Serialize, serde::Deserialize)]
pub struct GasConfig {
    /// SPH neighbours wanted within a particle's kernel reach.
    pub neighbours: f64,
    /// Artificial viscosity alpha (Monaghan 1997).
    pub viscosity: f64,
    /// A gas particle's step stays under courant H / (signal speed).
    pub courant: f64,
    pub gamma: f64,
    /// Cooling and heating (Koyama & Inutsuka below 10^4 K, collisional ionisation equilibrium above).
    pub cooling: bool,
    /// Lowest temperature, K (a Jeans floor also applies).
    pub floor_k: f64,
    /// The disc's half-thickness, pc: a 2D surface density Σ stands for a density Σ / 2 z0.
    pub thickness_pc: f64,
    pub star_formation: bool,
    /// Star formation: least hydrogen density (cm^-3), most temperature (K), efficiency per free-fall time.
    pub sf_density_cm3: f64,
    pub sf_max_k: f64,
    pub sf_efficiency: f64,
    /// Stars give back mass, elements and supernova energy (10^51 erg each) to the nearest gas within this, pc.
    pub feedback: bool,
    pub feedback_radius_pc: f64,
    /// The kernel's largest reach, pc (a lone particle's would otherwise grow without end).
    pub max_reach_pc: f64,
    /// Adaptive resolution (shaders/resolution.wgsl): thin hot gas particles lighter than `merge_below` x the
    /// starting mean mass merge in pairs, and any heavier than `split_above` x it split in two (0: off).
    pub merge_below: f64,
    pub split_above: f64,
}

impl Default for GasConfig {
    fn default() -> Self {
        Self {
            neighbours: 24.0,
            viscosity: 1.0,
            courant: 0.3,
            gamma: 5.0 / 3.0,
            cooling: true,
            floor_k: 100.0,
            thickness_pc: 100.0,
            star_formation: true,
            sf_density_cm3: 0.1,
            sf_max_k: 1.5e4,
            sf_efficiency: 0.01,
            feedback: true,
            feedback_radius_pc: 500.0,
            max_reach_pc: 3_000.0,
            merge_below: 0.5,
            split_above: 4.0,
        }
    }
}

/// The starting scene.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, serde::Deserialize, clap::ValueEnum)]
pub enum Scene {
    /// A galaxy in equilibrium: disc, bulge, dark matter halo and a central super well (`init::galaxy`).
    Galaxy,
    /// The phase-1 test disc: stars round a fixed central point mass (`init::build`).
    Disc,
    /// The early universe: near-smooth dark matter and gas over the periodic box, expanding (`init::universe`).
    Universe,
    /// Two Milky Way-like galaxies on a collision course (a parabolic orbit, pericentre 25 kpc).
    Pair,
    /// A group: one large galaxy, three medium ones and twenty dwarfs within ~600 kpc, falling together.
    Group,
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
            gas: GasConfig::default(),
            wells: WellConfig::default(),
            pm_cells: 0,
            cosmology: None,
            finder: FinderConfig::default(),
            spare_share: 0.0,
            start_steps: 0,
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

    /// The early universe: 20 Mpc (comoving) from redshift 30, mesh gravity for the long range, steps of 20 Myr
    /// down to 1.25. Each particle is ~10^7 - 10^8 Msun, so star particles are populations.
    pub fn universe() -> Self {
        let mut gas = GasConfig { feedback_radius_pc: 5_000.0, max_reach_pc: 1_000_000.0, ..GasConfig::default() };
        gas.floor_k = 30.0;
        Self {
            scene: Scene::Universe,
            dt_myr: 20.0,
            levels: 5,
            // physical; comoving (4 and 8 kpc) until a = 0.25
            softening_pc: 1_000.0,
            dm_softening_pc: 2_000.0,
            well_softening_pc: 1_000.0,
            // wells grow by Bondi accretion only: swallowing whole 10^7 Msun gas particles made them ~10% of their
            // halos by z = 1 (2026-11-08)
            accretion_pc: 0.0,
            pm_cells: 512,
            cosmology: Some(cosmo::Cosmology::default()),
            gas,
            wells: WellConfig { surroundings_pc: 5_000.0, merge_pc: 2_000.0, ..WellConfig::default() },
            // halos: dark matter linked at 0.2 of its mean spacing
            finder: FinderConfig { every_myr: 100.0, link_pc: 0.0, dark_matter: true, min_members: 32 },
            ..Self::default()
        }
    }

    /// The defaults for a scene.
    pub fn for_scene(scene: Scene) -> Self {
        match scene {
            Scene::Galaxy => Self::default(),
            Scene::Disc => Self::test_disc(),
            Scene::Universe => Self::universe(),
            Scene::Pair | Scene::Group => Self { scene, ..Self::default() },
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
            Scene::Universe => self.box_pc / 2.0,
            Scene::Pair => 90_000.0,
            Scene::Group => 450_000.0,
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
    _spare: u32,
    acc_r2: f32,
    single_stars: u32,
    eps2_kind: [[f32; 4]; 2],
    gas_a: [f32; 4],
    gas_b: [f32; 4],
    gas_c: [f32; 4],
    gas_d: [f32; 4],
    wells_a: [f32; 4],
    wells_b: [f32; 4],
    wells_c: [f32; 4],
    pm: [f32; 4],
    cosmo_p: [f32; 4],
    cosmo_q: [f32; 4],
    gas_e: [f32; 4],
    gas_f: [f32; 4],
    finder: [f32; 4],
    cosmo: [f32; 4],
}

/// Byte offsets in `Common` of what changes each step in an expanding universe (pm.wgsl cosmo_step writes them).
const COMMON_UNIT_AT: u64 = 44;
const COMMON_COSMO_AT: u64 = std::mem::size_of::<Common>() as u64 - 16;

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
    /// Gas (u, Σ, H, -) (zeros for the rest), and element mass fractions (He, C/N/O, Mg/Si, Fe).
    pub gas: Vec<[f32; 4]>,
    pub chem: Vec<[f32; 4]>,
    /// The long-range pull (gx, gy, φ, -) from the mesh at the last step's end (zeros without mesh gravity).
    pub pm: Vec<[f32; 4]>,
}

/// One piece of a sub-step (see the module comment). Frames can fall between any two.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Work {
    Open,
    Keys,
    Sort(u32),
    Build,
    Refit,
    /// At the start of each step of dt, in three parts: stellar evolution and star formation, and the well list
    /// (`evolve.wgsl`, 0); the wells swallowing, feeding, dragged and merging (1); feedback into the gas, its
    /// merging and splitting, and the clock (2).
    Evolve(u8),
    /// Gas: SPH density, then pressure forces, for the listed gas (hydro.wgsl).
    Gas,
    /// The list of particles whose step ends this sub-step.
    Compact,
    /// Force slices `from .. to` of the list (of up to `CHUNKS`).
    Force { from: u32, to: u32 },
    Close,
    /// Mesh gravity at the end of a step of dt, and its closing half kick (pm.wgsl).
    Pm,
    /// The galaxy finder (finder.wgsl), every few steps, at a step's start, in `FIND_PARTS` parts (start, the
    /// linking rounds, the sums), so the window can spread it over frames.
    Find(u8),
}

/// The stages GPU time is split into (timer labels).
pub const STAGES: [&str; 12] = ["integrate", "sort", "build", "refit", "compact", "force", "evolve", "gas", "pm", "find", "wells", "feedback"];
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
            Work::Evolve(0) => "evolve",
            Work::Evolve(1) => "wells",
            Work::Evolve(_) => "feedback",
            Work::Gas => "gas",
            Work::Force { .. } => "force",
            Work::Pm => "pm",
            Work::Find(_) => "find",
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
    gather_gas: wgpu::BindGroup,
    wells_list: wgpu::BindGroup,
    wells_env: wgpu::BindGroup,
    wells_merge: wgpu::BindGroup,
    hydro: wgpu::BindGroup,
    spread: wgpu::BindGroup,
    apply: wgpu::BindGroup,
    evolve: wgpu::BindGroup,
    compact: wgpu::BindGroup,
    moments: wgpu::BindGroup,
    force: wgpu::BindGroup,
    pm: wgpu::BindGroup,
    finder: wgpu::BindGroup,
    probe: wgpu::BindGroup,
    brush: wgpu::BindGroup,
    res_lists: wgpu::BindGroup,
    res_merge: wgpu::BindGroup,
    res_split_a: wgpu::BindGroup,
    res_split_b: wgpu::BindGroup,
}

struct Kernels {
    integrate: Kernel,
    morton: Kernel,
    gather: Kernel,
    gather_step: Kernel,
    gather_gas: Kernel,
    wells_list: Kernel,
    wells_env: Kernel,
    wells_merge: Kernel,
    hydro: Kernel,
    spread: Kernel,
    apply: Kernel,
    evolve: Kernel,
    compact: Kernel,
    karras: Kernel,
    moments: Kernel,
    force: Kernel,
    pm: Kernel,
    finder: Kernel,
    probe: Kernel,
    brush: Kernel,
    spawn: Kernel,
    spawn_bins: Kernel,
    res_lists: Kernel,
    res_merge: Kernel,
    res_split_a: Kernel,
    res_split_b: Kernel,
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
    gas: [wgpu::Buffer; 2],
    chem: [wgpu::Buffer; 2],
    /// any gas particles at the start (the gas passes run only then)
    has_gas: bool,
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
    rates: [f64; 12],
    /// the shared parameters (two copies: the force pass's rows differ), and where pm.wgsl cosmo_step leaves a
    /// step's scale factor
    common: [wgpu::Buffer; 2],
    cosmo_out: wgpu::Buffer,
    pm_acc: wgpu::Buffer,
    /// the galaxy finder's slots (finder.wgsl), their read-back, and the galaxies last found (heaviest first)
    found: wgpu::Buffer,
    groups_read: AsyncRead,
    pub galaxies: Vec<Galaxy>,
    /// when the galaxies were found (sim Myr)
    pub galaxies_myr: f64,
    find_pending: Option<f64>,
    /// picking and following particles (probe.wgsl): its parameters and results, a pick waiting to be sent and one
    /// sent and waiting to come back, the particle followed, and what was last seen of it
    probe_params: wgpu::Buffer,
    probe_out: wgpu::Buffer,
    edit_params: wgpu::Buffer,
    probe_read: AsyncRead,
    pick_request: Option<(Fixed2, f64, bool)>,
    pick_in_flight: bool,
    /// the last pick's answer (Some(None): nothing there), taken by the window
    pub picked: Option<Option<u32>>,
    pub track_id: Option<u32>,
    pub tracked: Option<Tracked>,
    bins_buf: [wgpu::Buffer; 2],
    single_stars: bool,
    /// The gas particles' mean mass at the start (Msun; 0 without gas).
    pub gas_ref_mass: f64,
    _buffers: Vec<wgpu::Buffer>,
}

/// A particle followed in the window (`Sim::track_id`).
#[derive(Clone, Copy, Debug)]
pub struct Tracked {
    pub id: u32,
    pub pos: Fixed2,
    pub vel: [f32; 2],
    pub kind: u32,
    pub mass: f32,
    /// (temperature K, luminosity Lsun)
    pub star: [f32; 2],
    pub about: [f32; 4],
    pub chem: [f32; 4],
    pub gas: [f32; 4],
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct ProbeParams {
    point: [u32; 4],
    n: u32,
    row: u32,
    unit_pc: f32,
    radius_pc: f32,
    target_id: u32,
    with_dm: u32,
    _a: [u32; 2],
}

const PROBE_WORDS: u64 = 27;

/// A tool's edit (shaders/tools.wgsl `Edit`).
#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct EditParams {
    point: [u32; 4],
    unit_pc: f32,
    radius_pc: f32,
    mode: u32,
    kinds: u32,
    dv: [f32; 2],
    dpos: [f32; 2],
    target_id: u32,
    value: f32,
    count: u32,
    _a: u32,
}

/// What a brush does to the particles within its radius (`Sim::brush`).
#[derive(Clone, Copy, Debug)]
pub enum Brush {
    /// Adds this velocity, pc / Myr.
    Kick([f64; 2]),
    Delete,
    /// Moves them by this much, pc.
    Move([f64; 2]),
}

/// Kinds a brush touches, as a bit mask (bit k: `init::Kind` k).
pub const ALL_KINDS: u32 = 0xBF; // all but K_GONE

/// A galaxy (or, with dark matter linked, a halo) as the finder sees it.
#[derive(Clone, Debug, Serialize)]
pub struct Galaxy {
    pub members: u32,
    /// Centre of mass in the box (comoving pc, 0 .. box), and mean velocity (pc / Myr).
    pub center_pc: (f64, f64),
    pub velocity: [f64; 2],
    /// Msun: in all, and in stars (and remnants), gas, super wells and dark matter.
    pub mass: f64,
    pub stars: f64,
    pub gas: f64,
    pub wells: f64,
    pub dark: f64,
    /// The mass-weighted rms distance of its members from the centre, pc (physical).
    pub radius_pc: f64,
}

const MAX_GROUPS: usize = 4096;
/// The finder's parts: its start, `FIND_ROUNDS` linking rounds of `FIND_SLICES` slices each, the sums.
const FIND_ROUNDS: u8 = 8;
const FIND_SLICES: u8 = 16;
const FIND_PARTS: u8 = 2 + FIND_ROUNDS * FIND_SLICES;
const GROUP_WORDS: usize = 26;

/// Galaxies from the finder's slots (finder.wgsl layout), heaviest first; `a` the scale factor they were found at.
fn parse_groups(words: &[u32], box_pc: f64, a: f64) -> Vec<Galaxy> {
    let n = (words[0] as usize).min(MAX_GROUPS);
    let sum = |at: usize| ((words[at + 1] as i32 as i64) << 32 | words[at] as i64) as f64;
    let mut out: Vec<Galaxy> = (0..n)
        .map(|k| {
            let at = 1 + k * GROUP_WORDS;
            let root = Fixed2::from_words([words[at + 2], words[at + 3], words[at + 4], words[at + 5]]);
            let mass = sum(at + 6) / 1024.0;
            let (mx, my) = (sum(at + 8) / 64.0, sum(at + 10) / 64.0);
            let c = root.offset_pc(mx / mass.max(1e-30) * 1000.0 / a, my / mass.max(1e-30) * 1000.0 / a, box_pc);
            Galaxy {
                members: words[at],
                center_pc: c.to_pc(box_pc),
                velocity: [sum(at + 12) / 64.0 / mass.max(1e-30), sum(at + 14) / 64.0 / mass.max(1e-30)],
                mass,
                stars: sum(at + 16) / 1024.0,
                gas: sum(at + 18) / 1024.0,
                wells: sum(at + 20) / 1024.0,
                dark: sum(at + 22) / 1024.0,
                // <r²> about the root, less the centre's offset from it, in kpc²
                radius_pc: ((sum(at + 24) / 64.0 / mass.max(1e-30)) - (mx * mx + my * my) / mass.max(1e-30).powi(2)).max(0.0).sqrt() * 1000.0,
            }
        })
        .collect();
    out.sort_by(|a, b| b.mass.total_cmp(&a.mass));
    out
}

fn begin<'e>(encoder: &'e mut wgpu::CommandEncoder, timer: &mut GpuTimer, label: &'static str, units: f64) -> wgpu::ComputePass<'e> {
    encoder.begin_compute_pass(&wgpu::ComputePassDescriptor { label: Some(label), timestamp_writes: timer.compute_units(label, units) })
}

fn module(body: &str) -> String {
    format!("{}{}", prelude(), body)
}

fn tools(body: &str) -> String {
    format!("{}{}\n{}", prelude(), include_str!("../../shaders/tools.wgsl"), body)
}

fn resolution(body: &str) -> String {
    format!("{}{}\n{}", prelude(), include_str!("../../shaders/resolution.wgsl"), body)
}

impl Sim {
    pub fn new(gpu: &Gpu, cfg: SimConfig) -> Result<Self> {
        match cfg.scene {
            Scene::Disc => {
                let init = init::build(&cfg);
                Self::from_initial(gpu, cfg, &init)
            }
            Scene::Universe => {
                let init = init::universe(&cfg);
                Self::from_initial(gpu, cfg, &init)
            }
            Scene::Pair | Scene::Group => {
                let init = placed_galaxies(gpu, &cfg)?;
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
        // (spare slots, past the end, keep standing still)
        let sorted: Vec<[f32; 4]> = body.iter().map(|b| kin_by_id.get((b[1] & init::ID_MASK) as usize).copied().unwrap_or([0.0; 4])).collect();
        gpu.queue.write_buffer(&self.kin[self.cur], 0, bytemuck::cast_slice(&sorted));
        gpu.wait()
    }

    /// From given particles (tests and other scenes); `cfg.particles` is taken from them.
    pub fn from_initial(gpu: &Gpu, mut cfg: SimConfig, init: &Initial) -> Result<Self> {
        // spare slots for the tools, as many as are missing (a saved universe already has its own)
        let with_spares;
        let init = if cfg.spare_share > 0.0 {
            let have = init.body.iter().filter(|b| b[1] >> init::KIND_SHIFT == init::Kind::Gone as u32).count();
            let want = (cfg.spare_share * (init.len() - have) as f64) as usize;
            let mut more = init.clone();
            let at = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
            for _ in have..want {
                more.push_kind(at, [0.0, 0.0], 0.0, (0.0, 0.0), init::Kind::Gone, [0.0; 4]);
            }
            with_spares = more;
            &with_spares
        } else {
            init
        };
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
        let gas = [make("gas 0", bytemuck::cast_slice(&init.gas), false), make("gas 1", bytemuck::cast_slice(&init.gas), false)];
        let chem = [make("chem 0", bytemuck::cast_slice(&init.chem), false), make("chem 1", bytemuck::cast_slice(&init.chem), false)];
        // the wells' particle indices and what they swallowed (evolve.wgsl), what stars give back and where it
        // goes (feedback.wgsl)
        anyhow::ensure!(init.wells <= 256, "at most 256 super wells");
        // [0] how many wells, [1 ..= 256] their indices (wells_list.wgsl), then 6 sums a well (evolve.wgsl swallow)
        let wsink = storage(d, "wells and sink", (257 + 256 * 6) * 4);
        let emit = storage(d, "emit", n as u64 * 32);
        let deposit = storage(d, "deposit", n as u64 * 48);
        let counts = storage(d, "bin counts", MAX_LEVELS as u64 * 4);
        // the list of particles whose step ends this sub-step (compact.wgsl)
        let flags = storage(d, "active flags", n as u64 * 4);
        let active = storage(d, "active", n as u64 * 4);
        // [0] the list's length, [1] .. [2] the gas's run of the sorted particles, [3] the clock (steps of dt begun)
        let active_n = storage(d, "control", 16);
        let flag_scan = Scan::new(d, &flags, n);
        let bbox = storage(d, "bbox", 16);
        let internal = n.saturating_sub(1).max(1) as u64;
        let child = storage(d, "child", internal * 8);
        let parents = storage(d, "parents", 2 * n as u64 * 4);
        let counter = storage(d, "counter", internal * 4);
        let node = storage(d, "node", internal * NODE_WORDS * 4);
        let pm_side = cfg.pm_cells.max(1) as u64;
        let mesh = storage(d, "pm mesh", 2 * pm_side * pm_side * 4);
        let field = storage(d, "pm field", 2 * pm_side * pm_side * 8);
        let pm_acc = storage(d, "pm acc", n as u64 * 16);
        let cosmo_out = storage(d, "cosmo", 32);
        let label = storage(d, "finder labels", n as u64 * 4);
        let gidx = storage(d, "finder roots", n as u64 * 4);
        let found = storage(d, "finder groups", ((1 + MAX_GROUPS * GROUP_WORDS) * 4) as u64);
        let probe_out = storage(d, "probe", PROBE_WORDS * 4);
        let probe_params = uniform(d, "probe parameters", &ProbeParams::zeroed());
        let edit_params = uniform(d, "edit parameters", &EditParams::zeroed());
        // gas merging and splitting (resolution.wgsl): free slots and gas to split, and how many of each
        let lists = storage(d, "resolution lists", 2 * n as u64 * 4);
        let res_n = storage(d, "resolution counts", 16);

        let unit_pc = cfg.box_pc / TWO_32;
        let center = Fixed2::from_pc(cfg.center_pc.0, cfg.center_pc.1, cfg.box_pc);
        // mesh gravity: cells, the split scale (1.25 cells) and cut (4.5 r_s), and a mass unit giving the whole
        // box 2^40 units (64-bit cell sums)
        let pm_cells = cfg.pm_cells;
        anyhow::ensure!(pm_cells == 0 || (pm_cells.is_power_of_two() && (16..=1024).contains(&pm_cells)), "mesh cells: a power of two, 16 to 1024");
        if pm_cells > 0 {
            cfg.walk = Walk::Particle; // the short-range cut is in the particle walk
        }
        let total_mass: f64 = init.body.iter().map(|b| f32::from_bits(b[0]) as f64).sum();
        let r_s = 1.25 * cfg.box_pc / pm_cells.max(1) as f64;
        // the start's scale factor (a step's own comes from pm.wgsl cosmo_step)
        let (t_start, a0) = match &cfg.cosmology {
            Some(cm) => {
                let t0 = cm.t_of_a(cm.a_start());
                (t0, cm.a_of_t(t0 + cfg.start_steps as f64 * cfg.dt_myr))
            }
            None => (0.0, 1.0),
        };
        // the gas particles' mean mass at the start: merging and splitting keep near it
        let (gm, gc) = init.body.iter().filter(|b| b[1] >> init::KIND_SHIFT == init::Kind::Gas as u32).fold((0.0f64, 0u32), |(m, c), b| (m + f32::from_bits(b[0]) as f64, c + 1));
        let gas_ref_mass = if gc > 0 { gm / gc as f64 } else { 0.0 };
        // the finder's linking length: in the universe 0.2 of the dark matter's mean spacing, comoving
        let n_dm = init.body.iter().filter(|b| b[1] >> init::KIND_SHIFT == init::Kind::DarkMatter as u32).count();
        let link_pc = if cfg.finder.link_pc > 0.0 { cfg.finder.link_pc } else { 0.2 * cfg.box_pc / (n_dm.max(1) as f64).sqrt() };
        let soft0 = cfg.cosmology.as_ref().map_or(1.0, |cm| (a0 / cm.soft_comoving_until_a).min(1.0).powi(2));
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
            unit_pc: (unit_pc * a0) as f32,
            inv_unit_pc: (1.0 / (unit_pc * a0)) as f32,
            dt: cfg.dt_myr as f32,
            gm_c: (G * cfg.central_mass) as f32,
            eps2_c: cfg.central_softening_pc.powi(2) as f32,
            levels,
            dt_min: cfg.dt_min() as f32,
            eta_eps: (2.0 * cfg.eta * cfg.softening_pc) as f32,
            eta_jerk: cfg.eta_jerk as f32,
            open_small: (cfg.open_small * cfg.softening_pc) as f32,
            _spare: 0,
            acc_r2: cfg.accretion_pc.powi(2) as f32,
            single_stars: init.single_stars as u32,
            eps2_kind: {
                let (st, dm, w) = (cfg.softening_pc.powi(2) as f32, cfg.dm_softening_pc.powi(2) as f32, cfg.well_softening_pc.powi(2) as f32);
                // K_STAR, K_DM, K_WELL, K_WD | K_NS, K_BH, K_GONE, -
                [[st, dm, w, st], [st, st, st, st]]
            },
            gas_a: [cfg.gas.neighbours as f32, cfg.gas.viscosity as f32, cfg.gas.courant as f32, cfg.gas.gamma as f32],
            // 1 hydrogen atom / cm^3 = 1 / 40.7 Msun / pc^3 (X 0.71)
            gas_b: [
                (cfg.gas.sf_density_cm3 / 40.7 / 0.71) as f32,
                cfg.gas.sf_max_k as f32,
                cfg.gas.sf_efficiency as f32,
                cfg.gas.thickness_pc as f32,
            ],
            gas_c: [cfg.gas.floor_k as f32, cfg.gas.cooling as u32 as f32, cfg.gas.feedback_radius_pc as f32, (0.5 * cfg.softening_pc) as f32],
            // 10^51 erg = 5.26e7 Msun (pc/Myr)^2
            gas_d: [5.26e7, cfg.gas.star_formation as u32 as f32, cfg.gas.feedback as u32 as f32, 0.0],
            wells_a: [
                cfg.wells.merge_pc as f32,
                cfg.wells.surroundings_pc as f32,
                cfg.wells.agn_efficiency as f32,
                cfg.wells.salpeter_myr as f32,
            ],
            wells_b: [
                cfg.wells.bondi as u32 as f32,
                cfg.wells.friction as u32 as f32,
                cfg.wells.direct_collapse as u32 as f32,
                cfg.wells.collapse_max_metallicity as f32,
            ],
            wells_c: [(cfg.wells.collapse_density_cm3 / 40.7 / 0.71) as f32, cfg.wells.collapse_min_mass as f32, 0.0, 0.0],
            pm: [pm_cells as f32, r_s as f32, (4.5 * r_s) as f32, (total_mass.max(1.0) / 2f64.powi(40)) as f32],
            cosmo_p: match &cfg.cosmology {
                Some(cm) => [cm.h0_per_myr() as f32, cm.omega_m as f32, cm.omega_l as f32, t_start as f32],
                None => [0.0; 4],
            },
            cosmo_q: match &cfg.cosmology {
                Some(cm) => [cm.soft_comoving_until_a as f32, cm.uv_background as u32 as f32, cm.z_reion as f32, unit_pc as f32],
                None => [0.0, 0.0, 0.0, unit_pc as f32],
            },
            gas_e: match &cfg.cosmology {
                Some(cm) => [
                    cm.sheet_pc as f32,
                    (cm.sigma_mean() * cm.baryon_share) as f32,
                    1.0,
                    (cm.self_shield_cm3 / 40.7 / 0.71) as f32,
                ],
                None => [0.0; 4],
            },
            gas_f: [cfg.gas.max_reach_pc as f32, cfg.gas.merge_below as f32, cfg.gas.split_above as f32, gas_ref_mass as f32],
            finder: [link_pc as f32, cfg.finder.dark_matter as u32 as f32, cfg.finder.min_members as f32, cfg.cosmology.is_some() as u32 as f32],
            cosmo: [a0 as f32, cfg.cosmology.as_ref().map_or(0.0, |cm| cm.hubble(a0)) as f32, soft0 as f32, (1.0 / a0) as f32],
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
                &[U, W, W, R, W, W, T, W, R, R],
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
                &[U, R, W, W, W, W, W, R, W],
                &["evolve", "tick_clock", "swallow", "swallow_apply"],
            ),
            wells_list: Kernel::new(d, "wells list", &module(include_str!("../../shaders/wells_list.wgsl")), &[U, R, W, W], &["flag", "scatter"]),
            wells_env: Kernel::new(
                d,
                "wells",
                &module(include_str!("../../shaders/wells_env.wgsl")),
                &[U, R, W, W, R, R, R, W, W],
                &["surroundings"],
            ),
            wells_merge: Kernel::new(d, "wells merge", &module(include_str!("../../shaders/wells_merge.wgsl")), &[U, R, W, W, W, W], &["merge"]),
            gather_gas: Kernel::new(d, "gather gas", &module(include_str!("../../shaders/gather_gas.wgsl")), &[U, R, R, R, W, W], &["main"]),
            hydro: Kernel::new(
                d,
                "hydro",
                &module(include_str!("../../shaders/hydro.wgsl")),
                &[U, R, R, R, W, R, R, R, W],
                &["range_reset", "range_find", "density", "force"],
            ),
            spread: Kernel::new(d, "feedback", &module(include_str!("../../shaders/feedback.wgsl")), &[U, R, R, R, R, R, R, R, W], &["spread"]),
            apply: Kernel::new(
                d,
                "feedback apply",
                &module(include_str!("../../shaders/feedback_apply.wgsl")),
                &[U, W, W, W, W, W, W, W],
                &["apply"],
            ),
            compact: Kernel::new(d, "compact", &module(include_str!("../../shaders/compact.wgsl")), &[U, R, W, W, W, T, R], &["flag", "scatter"]),
            karras: Kernel::new(d, "karras", &module(include_str!("../../shaders/karras.wgsl")), &[U, R, W, W, W], &["main"]),
            moments: Kernel::new(
                d,
                "moments",
                &module(include_str!("../../shaders/moments.wgsl")),
                &[U, R, R, R, R, W, W, R],
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
            pm: Kernel::new(
                d,
                "pm",
                &module(include_str!("../../shaders/pm.wgsl")),
                &[U, R, R, W, W, W, W, R, W],
                &["clear", "deposit", "to_field", "fft_rows", "fft_cols", "ifft_rows", "ifft_cols", "green", "interp", "kick", "cosmo_step"],
            ),
            finder: Kernel::new(
                d,
                "finder",
                &module(include_str!("../../shaders/finder.wgsl")),
                &[U, R, R, R, R, W, W, W, R, T],
                &["init", "link", "jump", "count", "assign", "sums"],
            ),
            probe: Kernel::new(
                d,
                "probe",
                &format!("{}\n{}", include_str!("../../shaders/fixed.wgsl"), include_str!("../../shaders/probe.wgsl")),
                &[U, R, R, R, R, R, R, W],
                &["reset", "pick_near", "pick_id", "track"],
            ),
            brush: Kernel::new(d, "brush", &tools(include_str!("../../shaders/tools_brush.wgsl")), &[U, U, W, W, W], &["brush"]),
            spawn: Kernel::new(d, "spawn", &tools(include_str!("../../shaders/tools_spawn.wgsl")), &[U, U, R, W, W, W, W, W, W, W], &["spawn_a"]),
            spawn_bins: Kernel::new(d, "spawn bins", &tools(include_str!("../../shaders/tools_bins.wgsl")), &[U, U, R, W, W], &["spawn_b"]),
            res_lists: Kernel::new(d, "resolution lists", &resolution(include_str!("../../shaders/res_lists.wgsl")), &[U, R, W, W, W, R], &[
                "flag_free",
                "scatter_free",
                "flag_split",
                "scatter_split",
            ]),
            res_merge: Kernel::new(d, "merge", &resolution(include_str!("../../shaders/res_merge.wgsl")), &[U, W, W, W, W, W, R], &["merge"]),
            res_split_a: Kernel::new(d, "split a", &resolution(include_str!("../../shaders/res_split_a.wgsl")), &[U, W, W, W, W, R, R, R], &["split_a"]),
            res_split_b: Kernel::new(d, "split b", &resolution(include_str!("../../shaders/res_split_b.wgsl")), &[U, W, W, W, W, W, R, R], &["split_b"]),
        };
        let sort = RadixSort::new(d, n);
        let set = |s: usize| {
            let o = 1 - s;
            SetBinds {
                integrate: k.integrate.bind(
                    d,
                    "integrate",
                    &[&common, &pos[s], &kin[s], &acc[s], &bins[s], &counts, &tick, &gas[s], &chem[s], &body[s]],
                ),
                gather_gas: k.gather_gas.bind(d, "gather gas", &[&common, &sort.vals[0], &gas[s], &chem[s], &gas[o], &chem[o]]),
                wells_list: k.wells_list.bind(d, "wells list", &[&common, &body[s], &flags, &wsink]),
                wells_merge: k.wells_merge.bind(d, "wells merge", &[&common, &pos[s], &kin[s], &body[s], &acc[s], &wsink]),
                wells_env: k.wells_env.bind(d, "wells", &[&common, &pos[s], &kin[s], &body[s], &gas[s], &child, &node, &wsink, &deposit]),
                hydro: k.hydro.bind(d, "hydro", &[&common, &pos[s], &kin[s], &body[s], &gas[s], &child, &node, &active, &active_n]),
                spread: k.spread.bind(d, "feedback", &[&common, &pos[s], &body[s], &chem[s], &emit, &child, &node, &active_n, &deposit]),
                apply: k.apply.bind(d, "feedback apply", &[&common, &kin[s], &body[s], &gas[s], &chem[s], &deposit, &bins[s], &counts]),
                morton: k.morton.bind(d, "morton", &[&common, &pos[s], &bbox, &sort.keys[0], &sort.vals[0], &body[s]]),
                gather: k.gather.bind(d, "gather", &[&common, &sort.vals[0], &pos[s], &kin[s], &body[s], &pos[o], &kin[o], &body[o]]),
                gather_step: k.gather_step.bind(
                    d,
                    "gather step",
                    &[&common, &sort.vals[0], &acc[s], &bins[s], &acc[o], &bins[o], &about[s], &about[o]],
                ),
                evolve: k.evolve.bind(d, "evolve", &[&common, &pos[s], &kin[s], &body[s], &about[s], &active_n, &wsink, &gas[s], &emit]),
                compact: k.compact.bind(d, "compact", &[&common, &bins[s], &flags, &active, &active_n, &tick, &body[s]]),
                moments: k.moments.bind(d, "moments", &[&common, &pos[s], &body[s], &child, &parents, &counter, &node, &gas[s]]),
                force: k.force.bind(d, "force", &[&force_common, &pos[s], &body[s], &child, &node, &acc[s], &active, &tick, &active_n]),
                pm: k.pm.bind(d, "pm", &[&common, &pos[s], &body[s], &mesh, &field, &pm_acc, &kin[s], &active_n, &cosmo_out]),
                finder: k.finder.bind(d, "finder", &[&common, &pos[s], &body[s], &child, &node, &label, &gidx, &found, &kin[s], &tick]),
                brush: k.brush.bind(d, "brush", &[&common, &edit_params, &pos[s], &kin[s], &body[s]]),
                probe: k.probe.bind(d, "probe", &[&probe_params, &pos[s], &body[s], &kin[s], &about[s], &chem[s], &gas[s], &probe_out]),
                res_lists: k.res_lists.bind(d, "resolution lists", &[&common, &body[s], &flags, &lists, &res_n, &gas[s]]),
                res_merge: k.res_merge.bind(d, "merge", &[&common, &pos[s], &kin[s], &body[s], &gas[s], &chem[s], &active_n]),
                res_split_a: k.res_split_a.bind(d, "split a", &[&common, &pos[s], &kin[s], &body[s], &about[s], &lists, &res_n, &gas[s]]),
                res_split_b: k.res_split_b.bind(d, "split b", &[&common, &gas[s], &chem[s], &bins[s], &acc[s], &counts, &lists, &res_n]),
            }
        };
        let sets = [set(0), set(1)];
        let karras = k.karras.bind(d, "karras", &[&common, &sort.keys[0], &child, &parents, &counter]);

        // first guesses of GPU ms per unit (a little pessimistic: a laptop's integrated GPU); measurements replace them
        let per = n as f64;
        let cfg_start_steps = cfg.start_steps;
        let sim_ctl = active_n.clone();
        let rates = [3e-6 * per, 1.5e-5 * per, 2e-5 * per, 1.5e-5 * per, 1e-5 * per, 2e-4 * per, 1e-5 * per, 1e-4 * per, 1e-5 * per + 2.0, 1e-3 * per, 1e-5 * per, 1e-5 * per];
        let mut sim = Self {
            cfg,
            n,
            pos,
            kin,
            body,
            acc,
            _bins: bins.clone(),
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
            gas,
            chem,
            has_gas: init.body.iter().any(|b| b[1] >> init::KIND_SHIFT == init::Kind::Gas as u32),
            common: [common, force_common],
            cosmo_out,
            pm_acc,
            groups_read: AsyncRead::new(d, "finder read", found.size()),
            found,
            galaxies: Vec::new(),
            galaxies_myr: 0.0,
            find_pending: None,
            probe_read: AsyncRead::new(d, "probe read", PROBE_WORDS * 4),
            probe_params,
            probe_out,
            edit_params,
            bins_buf: bins.clone(),
            single_stars: init.single_stars,
            gas_ref_mass,
            pick_request: None,
            pick_in_flight: false,
            picked: None,
            track_id: None,
            tracked: None,
            _buffers: vec![label, gidx, lists, res_n, bbox, child, parents, counter, node, tick, flags, active, active_n, wsink, emit, deposit, mesh, field],
        };
        // the clock (steps of dt begun), for a universe carried on from a save
        let start = cfg_start_steps;
        gpu.queue.write_buffer(&sim_ctl, 12, bytemuck::bytes_of(&(start as u32)));
        sim.steps = start;
        sim.sub_done = start * sim.subs as u64;
        sim.sub_drifted = sim.sub_done;
        // the first forces, for every particle (they all start in bin 0, and at the last sub-step every bin's step
        // ends), then everyone's first bin
        let mut enc = d.create_command_encoder(&Default::default());
        let mut timer = GpuTimer::new(d, &gpu.queue, false);
        // the stars' state at the start (no clock tick: the first step's evolution runs again at the same time); a
        // saved universe has its stars' state already, and only lists its wells
        sim.encode_evolve(&mut enc, &mut timer, false, start == 0);
        let last = sim.subs - 1;
        let first = [Work::Build, Work::Compact, Work::Force { from: 0, to: sim.chunks }, Work::Gas];
        for w in [Work::Keys].into_iter().chain((0..PASSES).map(Work::Sort)).chain(first) {
            sim.encode_item(&mut enc, &mut timer, w, last);
        }
        {
            let mut pass = begin(&mut enc, &mut timer, "integrate", 1.0);
            sim.k.integrate.run_at(&mut pass, "init_bins", &sim.sets[sim.cur].integrate, &[0], sim.groups);
        }
        // the first long-range forces (no kick: the first step's opening half kick uses them)
        if sim.cfg.pm_cells > 0 {
            let mut pass = begin(&mut enc, &mut timer, "pm", 1.0);
            sim.encode_pm(&mut pass, false);
        }
        gpu.queue.submit([enc.finish()]);
        Ok(sim)
    }

    fn tick_offset(&self, s: u32, chunk: u32) -> u32 {
        ((s * CHUNKS + chunk) as u64 * DYN_STRIDE) as u32
    }

    /// The start of a step of dt (with `tick`; without, only the stars' state and the well list, for the start):
    /// star formation and stellar evolution, the well list, wells swallowing, accreting, dragged and merging, what
    /// stars and wells give the gas, and the clock moves on.
    fn encode_evolve(&mut self, encoder: &mut wgpu::CommandEncoder, timer: &mut GpuTimer, tick: bool, stars: bool) {
        if tick {
            for part in 0..3 {
                self.encode_evolve_part(encoder, timer, part);
            }
            return;
        }
        let mut pass = begin(encoder, timer, "evolve", 1.0);
        let g = self.groups;
        let set = &self.sets[self.cur];
        if stars {
            self.k.evolve.run(&mut pass, "evolve", &set.evolve, g);
        }
        self.k.wells_list.run(&mut pass, "flag", &set.wells_list, g);
        self.flag_scan.encode(&mut pass);
        self.k.wells_list.run(&mut pass, "scatter", &set.wells_list, g);
    }

    /// One part of `Work::Evolve`.
    fn encode_evolve_part(&mut self, encoder: &mut wgpu::CommandEncoder, timer: &mut GpuTimer, part: u8) {
        let g = self.groups;
        if part == 0 {
            let mut pass = begin(encoder, timer, "evolve", 1.0);
            let set = &self.sets[self.cur];
            if self.cfg.pm_cells > 0 {
                // the long-range forces' opening half kick (from the last step's end)
                self.k.pm.run(&mut pass, "kick", &set.pm, g);
            }
            self.k.evolve.run(&mut pass, "evolve", &set.evolve, g);
            self.k.wells_list.run(&mut pass, "flag", &set.wells_list, g);
            self.flag_scan.encode(&mut pass);
            self.k.wells_list.run(&mut pass, "scatter", &set.wells_list, g);
            return;
        }
        let one = Groups { x: 1, y: 1 };
        if part == 1 {
            let mut pass = begin(encoder, timer, "wells", 1.0);
            let set = &self.sets[self.cur];
            self.wells_part(&mut pass, set, g);
            return;
        }
        let mut pass = begin(encoder, timer, "feedback", 1.0);
        let set = &self.sets[self.cur];
        if self.has_gas {
            // what stars gave back, and wells took, goes to the gas (the tree is the last sub-step's)
            self.k.spread.run(&mut pass, "spread", &set.spread, g);
            self.k.apply.run(&mut pass, "apply", &set.apply, g);
            if self.cfg.gas.merge_below > 0.0 || self.cfg.gas.split_above > 0.0 {
                // adaptive resolution: thin hot light gas merges, heavy gas splits into free slots
                self.k.res_merge.run(&mut pass, "merge", &set.res_merge, Groups::for_items(self.n.div_ceil(2), 256));
                for (flag, scatter) in [("flag_free", "scatter_free"), ("flag_split", "scatter_split")] {
                    self.k.res_lists.run(&mut pass, flag, &set.res_lists, g);
                    self.flag_scan.encode(&mut pass);
                    self.k.res_lists.run(&mut pass, scatter, &set.res_lists, g);
                }
                self.k.res_split_a.run(&mut pass, "split_a", &set.res_split_a, g);
                self.k.res_split_b.run(&mut pass, "split_b", &set.res_split_b, g);
            }
        }
        self.k.evolve.run(&mut pass, "tick_clock", &set.evolve, one);
        if self.cfg.cosmology.is_some() {
            // this step's scale factor, into both copies of the shared parameters
            self.k.pm.run(&mut pass, "cosmo_step", &set.pm, one);
            drop(pass);
            for c in &self.common {
                encoder.copy_buffer_to_buffer(&self.cosmo_out, 0, c, COMMON_UNIT_AT, 8);
                encoder.copy_buffer_to_buffer(&self.cosmo_out, 8, c, COMMON_COSMO_AT, 16);
            }
        }
    }

    /// The wells swallowing, feeding, dragged and merging.
    fn wells_part(&self, pass: &mut wgpu::ComputePass, set: &SetBinds, g: Groups) {
        let one = Groups { x: 1, y: 1 };
        self.k.evolve.run(pass, "swallow", &set.evolve, g);
        let wells = Groups { x: 4, y: 1 }; // 256 wells, 64 a workgroup
        self.k.evolve.run(pass, "swallow_apply", &set.evolve, wells);
        self.k.wells_env.run(pass, "surroundings", &set.wells_env, Groups { x: 256, y: 1 });
        self.k.wells_merge.run(pass, "merge", &set.wells_merge, one);
    }

    /// The galaxy finder (finder.wgsl): `FIND_ROUNDS` rounds of linking (each with two pointer jumps), then the
    /// groups' sums.
    fn encode_find(&self, pass: &mut wgpu::ComputePass) {
        for part in 0..FIND_PARTS {
            self.encode_find_part(pass, part);
        }
    }

    fn encode_find_part(&self, pass: &mut wgpu::ComputePass, part: u8) {
        let set = &self.sets[self.cur];
        let (f, g) = (&self.k.finder, self.groups);
        let t0 = self.tick_offset(0, 0);
        if part == 0 {
            f.run_at(pass, "init", &set.finder, &[t0], Groups::for_items(self.n.max(1 + (MAX_GROUPS * GROUP_WORDS) as u32), 256));
        } else if part + 1 < FIND_PARTS {
            // a slice of a linking round: CHUNKS / FIND_SLICES of the force pass's chunks, then (after the last) the
            // pointer jumps
            let slice = (part - 1) % FIND_SLICES;
            let per = CHUNKS / FIND_SLICES as u32;
            let chunk = self.chunk_groups * self.cfg.walk.workgroup();
            f.run_at(pass, "link", &set.finder, &[self.tick_offset(0, slice as u32 * per)], Groups::for_items(per * chunk, 256));
            if slice + 1 == FIND_SLICES {
                f.run_at(pass, "jump", &set.finder, &[t0], g);
                f.run_at(pass, "jump", &set.finder, &[t0], g);
            }
        } else {
            for e in ["count", "assign", "sums"] {
                f.run_at(pass, e, &set.finder, &[t0], g);
            }
        }
    }

    /// Runs the galaxy finder now and waits for its result (headless runs and tests; the window's comes every
    /// `finder.every_myr` through `collect`).
    pub fn find_galaxies(&mut self, gpu: &Gpu) -> Result<&[Galaxy]> {
        let mut enc = gpu.device.create_command_encoder(&Default::default());
        {
            let mut pass = enc.begin_compute_pass(&Default::default());
            self.encode_find(&mut pass);
        }
        gpu.queue.submit([enc.finish()]);
        let words: Vec<u32> = bytemuck::cast_slice(&gpu.read_buffer(&self.found)?).to_vec();
        self.galaxies = parse_groups(&words, self.cfg.box_pc, self.scale_factor());
        self.galaxies_myr = self.pos_time_myr();
        Ok(&self.galaxies)
    }

    /// Whether each star particle is one star (else a population).
    pub fn single_stars(&self) -> bool {
        self.single_stars
    }

    /// Whether the sim is between steps of dt (where the tools may change it).
    pub fn at_step_boundary(&self) -> bool {
        self.queue.is_empty() && self.sub == 0
    }

    /// Records the rest of the step under way, if any (the tools wait for the step's end).
    pub fn finish_step(&mut self, encoder: &mut wgpu::CommandEncoder, timer: &mut GpuTimer) {
        while !self.at_step_boundary() {
            if self.queue.is_empty() {
                self.plan();
            }
            let w = self.queue.pop_front().expect("planned");
            self.step_item(encoder, timer, w);
        }
    }

    fn edit_params(&self, point: Fixed2, radius_pc: f64) -> EditParams {
        EditParams {
            point: point.words(),
            unit_pc: (self.cfg.box_pc / TWO_32 * self.scale_factor()) as f32,
            radius_pc: radius_pc as f32,
            ..EditParams::zeroed()
        }
    }

    fn run_edit(&mut self, gpu: &Gpu, params: EditParams, f: impl FnOnce(&Self, &mut wgpu::ComputePass)) -> Result<()> {
        let mut enc = gpu.device.create_command_encoder(&Default::default());
        let mut timer = GpuTimer::new(&gpu.device, &gpu.queue, false);
        self.finish_step(&mut enc, &mut timer);
        gpu.queue.write_buffer(&self.edit_params, 0, bytemuck::bytes_of(&params));
        {
            let mut pass = enc.begin_compute_pass(&Default::default());
            f(self, &mut pass);
        }
        gpu.queue.submit([enc.finish()]);
        gpu.wait()
    }

    /// Kicks, deletes or moves the particles of `kinds` (bit mask, `ALL_KINDS`) within `radius_pc` (physical) of
    /// `point`, at the end of the step under way (which it finishes first).
    pub fn brush(&mut self, gpu: &Gpu, point: Fixed2, radius_pc: f64, kinds: u32, what: Brush) -> Result<()> {
        let mut p = self.edit_params(point, radius_pc);
        p.kinds = kinds;
        match what {
            Brush::Kick(v) => p.dv = [v[0] as f32, v[1] as f32],
            Brush::Delete => p.mode = 1,
            Brush::Move(d) => {
                p.mode = 2;
                p.dpos = [d[0] as f32, d[1] as f32];
            }
        }
        self.run_edit(gpu, p, |sim, pass| sim.k.brush.run(pass, "brush", &sim.sets[sim.cur].brush, sim.groups))
    }

    /// Gives the particle with this id a new mass (at the end of the step under way).
    pub fn set_mass(&mut self, gpu: &Gpu, id: u32, mass: f64) -> Result<()> {
        let mut p = self.edit_params(Fixed2 { x: 0, y: 0 }, 0.0);
        p.mode = 3;
        p.target_id = id;
        p.value = mass as f32;
        self.run_edit(gpu, p, |sim, pass| sim.k.brush.run(pass, "brush", &sim.sets[sim.cur].brush, sim.groups))
    }

    /// Adds particles (made as for a new universe: `Initial`, ids ignored) into free slots, at the end of the step
    /// under way. Returns how many fitted (the spare slots can run out).
    pub fn spawn(&mut self, gpu: &Gpu, add: &Initial) -> Result<usize> {
        let body: Vec<[u32; 2]> = bytemuck::cast_slice(&gpu.read_buffer(&self.body[self.cur])?).to_vec();
        let free: Vec<u32> = (0..self.n).filter(|&i| body[i as usize][1] >> init::KIND_SHIFT == init::Kind::Gone as u32).collect();
        let count = free.len().min(add.len());
        if count == 0 {
            return Ok(0);
        }
        let mut rec: Vec<u32> = Vec::with_capacity(count * 23);
        for (k, &slot) in free.iter().take(count).enumerate() {
            rec.push(slot);
            rec.extend_from_slice(&add.pos[k]);
            rec.extend(add.kin[k].iter().map(|v| v.to_bits()));
            rec.extend_from_slice(&add.body[k]);
            rec.extend(add.about[k].iter().map(|v| v.to_bits()));
            rec.extend(add.gas[k][..4].iter().map(|v| v.to_bits()));
            rec.extend(add.chem[k].iter().map(|v| v.to_bits()));
        }
        if add.body.iter().take(count).any(|b| b[1] >> init::KIND_SHIFT == init::Kind::Gas as u32) {
            self.has_gas = true;
        }
        let d = &gpu.device;
        let records = d.create_buffer_init(&wgpu::util::BufferInitDescriptor { label: Some("spawn"), contents: bytemuck::cast_slice(&rec), usage: wgpu::BufferUsages::STORAGE });
        let mut p = self.edit_params(Fixed2 { x: 0, y: 0 }, 0.0);
        p.count = count as u32;
        let s = self.cur;
        let common = &self.common[0];
        let a = self.k.spawn.bind(
            d,
            "spawn",
            &[common, &self.edit_params, &records, &self.pos[s], &self.kin[s], &self.body[s], &self.about[s], &self.gas[s], &self.chem[s], &self.acc[s]],
        );
        let b = self.k.spawn_bins.bind(d, "spawn bins", &[common, &self.edit_params, &records, &self.bins_buf[s], &self.counts]);
        // the slots were found in the current order: finish the step first, then look again if it sorted
        let mut enc = d.create_command_encoder(&Default::default());
        let mut timer = GpuTimer::new(d, &gpu.queue, false);
        let was = self.cur;
        self.finish_step(&mut enc, &mut timer);
        if self.cur != was || !self.at_step_boundary() {
            gpu.queue.submit([enc.finish()]);
            gpu.wait()?;
            return self.spawn(gpu, add);
        }
        gpu.queue.write_buffer(&self.edit_params, 0, bytemuck::bytes_of(&p));
        {
            let mut pass = enc.begin_compute_pass(&Default::default());
            let g = Groups::for_items(count as u32, 256);
            self.k.spawn.run(&mut pass, "spawn_a", &a, g);
            self.k.spawn_bins.run(&mut pass, "spawn_b", &b, g);
        }
        gpu.queue.submit([enc.finish()]);
        gpu.wait()?;
        Ok(count)
    }

    /// Asks for the particle nearest `point` within `radius_pc` (dark matter too if `with_dm`); the answer comes to
    /// `picked` a frame or two later (after `encode_probe`, a submit, and `collect`).
    pub fn pick(&mut self, point: Fixed2, radius_pc: f64, with_dm: bool) {
        self.pick_request = Some((point, radius_pc, with_dm));
    }

    /// Records the picking and following passes asked for (the window calls it each frame, after `advance`). They
    /// only read the particles.
    pub fn encode_probe(&mut self, queue: &wgpu::Queue, encoder: &mut wgpu::CommandEncoder) {
        let pick = if self.pick_in_flight { None } else { self.pick_request };
        if pick.is_none() && self.track_id.is_none() {
            return;
        }
        let (point, radius, dm) = pick.unwrap_or((Fixed2 { x: 0, y: 0 }, 0.0, false));
        let params = ProbeParams {
            point: point.words(),
            n: self.n,
            row: self.groups.x * 256,
            unit_pc: (self.cfg.box_pc / TWO_32 * self.scale_factor()) as f32,
            radius_pc: radius as f32,
            target_id: self.track_id.unwrap_or(u32::MAX),
            with_dm: dm as u32,
            _a: [0; 2],
        };
        queue.write_buffer(&self.probe_params, 0, bytemuck::bytes_of(&params));
        {
            let mut pass = encoder.begin_compute_pass(&Default::default());
            let (k, b) = (&self.k.probe, &self.sets[self.cur].probe);
            k.run(&mut pass, "reset", b, Groups { x: 1, y: 1 });
            if pick.is_some() {
                k.run(&mut pass, "pick_near", b, self.groups);
                k.run(&mut pass, "pick_id", b, self.groups);
            }
            if self.track_id.is_some() {
                k.run(&mut pass, "track", b, self.groups);
            }
        }
        if self.probe_read.copy(encoder, &self.probe_out) && pick.is_some() {
            self.pick_request = None;
            self.pick_in_flight = true;
        }
    }

    fn take_probe(&mut self, words: &[u32]) {
        if self.pick_in_flight {
            self.pick_in_flight = false;
            self.picked = Some((words[2] != 0).then_some(words[1]));
        }
        if words[26] != 0 {
            let w = &words[4..26];
            let f = |i: usize| f32::from_bits(w[i]);
            self.tracked = Some(Tracked {
                id: w[9] & init::ID_MASK,
                pos: Fixed2::from_words([w[0], w[1], w[2], w[3]]),
                vel: [f(4), f(5)],
                kind: w[9] >> init::KIND_SHIFT,
                mass: f(8),
                star: [f(6), f(7)],
                about: [f(10), f(11), f(12), f(13)],
                chem: [f(14), f(15), f(16), f(17)],
                gas: [f(18), f(19), f(20), f(21)],
            });
        } else if self.track_id.is_some() {
            self.tracked = None;
        }
    }

    /// Picks and tracks now, waiting for the GPU (tests).
    pub fn probe_now(&mut self, gpu: &Gpu) -> Result<()> {
        let mut enc = gpu.device.create_command_encoder(&Default::default());
        self.encode_probe(&gpu.queue, &mut enc);
        gpu.queue.submit([enc.finish()]);
        self.probe_read.after_submit();
        gpu.wait()?;
        if let Some(data) = self.probe_read.take() {
            let words: Vec<u32> = bytemuck::cast_slice(&data).to_vec();
            self.take_probe(&words);
        }
        Ok(())
    }

    /// Mesh gravity: the long-range pull of every particle into `pm_acc`, and with `kick` the closing half kick.
    fn encode_pm(&self, pass: &mut wgpu::ComputePass, kick: bool) {
        let set = &self.sets[self.cur];
        let side = self.cfg.pm_cells;
        let cells = Groups::for_items(side * side, 256);
        let pm = &self.k.pm;
        pm.run(pass, "clear", &set.pm, Groups::for_items(2 * side * side, 256));
        pm.run(pass, "deposit", &set.pm, self.groups);
        pm.run(pass, "to_field", &set.pm, cells);
        pm.run(pass, "fft_rows", &set.pm, Groups { x: side, y: 1 });
        pm.run(pass, "fft_cols", &set.pm, Groups { x: side, y: 1 });
        pm.run(pass, "green", &set.pm, cells);
        pm.run(pass, "ifft_rows", &set.pm, Groups { x: side, y: 2 });
        pm.run(pass, "ifft_cols", &set.pm, Groups { x: side, y: 2 });
        pm.run(pass, "interp", &set.pm, self.groups);
        if kick {
            pm.run(pass, "kick", &set.pm, self.groups);
        }
    }

    /// The work of the next sub-step.
    fn plan(&mut self) {
        if self.sub == 0 {
            self.queue.extend([Work::Evolve(0), Work::Evolve(1), Work::Evolve(2)]);
            let every = (self.cfg.finder.every_myr / self.cfg.dt_myr).round() as u64;
            if self.cfg.finder.every_myr > 0.0 && self.steps.is_multiple_of(every.max(1)) {
                self.queue.extend((0..FIND_PARTS).map(Work::Find));
            }
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
        if self.has_gas {
            self.queue.push_back(Work::Gas);
        }
        self.queue.push_back(Work::Close);
        if self.sub + 1 == self.subs && self.cfg.pm_cells > 0 {
            self.queue.push_back(Work::Pm);
        }
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
            Work::Find(_) => 1.0 / FIND_PARTS as f64,
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
            _ => self.units(w) * self.rates[STAGES.iter().position(|&l| l == w.label()).expect("a stage label")],
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
                self.k.gather_gas.run(&mut pass, "main", &self.sets[c].gather_gas, g);
                self.k.karras.run(&mut pass, "main", &self.karras, g);
                self.cur = 1 - c;
                self.k.moments.run(&mut pass, "main", &self.sets[self.cur].moments, g);
                // where the gas's run of the sorted particles now is
                self.k.hydro.run(&mut pass, "range_reset", &self.sets[self.cur].hydro, Groups { x: 1, y: 1 });
                self.k.hydro.run(&mut pass, "range_find", &self.sets[self.cur].hydro, g);
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
            Work::Evolve(part) => {
                drop(pass);
                self.encode_evolve_part(encoder, timer, part);
            }
            Work::Pm => self.encode_pm(&mut pass, true),
            Work::Find(part) => self.encode_find_part(&mut pass, part),
            Work::Gas => {
                let hg = g;
                self.k.hydro.run(&mut pass, "density", &self.sets[c].hydro, hg);
                self.k.hydro.run(&mut pass, "force", &self.sets[c].hydro, hg);
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
                // with mesh gravity the step ends after its long-range forces (`Work::Pm`)
                if self.sub == self.subs && self.cfg.pm_cells == 0 {
                    self.sub = 0;
                    self.steps += 1;
                }
            }
            Work::Pm => {
                self.sub = 0;
                self.steps += 1;
            }
            Work::Find(part) if part + 1 == FIND_PARTS => self.find_pending = Some(self.pos_time_myr()),
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
        if self.find_pending.is_some() {
            self.groups_read.copy(encoder, &self.found);
        }
        spent
    }

    pub fn after_submit(&mut self) {
        self.counts_read.after_submit();
        self.groups_read.after_submit();
        self.probe_read.after_submit();
    }

    /// Picks up the bin counts once read back, and the GPU times of the last timed frame (call after polling).
    pub fn collect(&mut self, timer: Option<&GpuTimer>) {
        if let Some(data) = self.counts_read.take() {
            let c: &[u32] = bytemuck::cast_slice(&data);
            self.bin_counts.copy_from_slice(c);
        }
        if let Some(data) = self.probe_read.take() {
            let words: Vec<u32> = bytemuck::cast_slice(&data).to_vec();
            self.take_probe(&words);
        }
        if let Some(data) = self.groups_read.take() {
            let words: &[u32] = bytemuck::cast_slice(&data);
            self.galaxies = parse_groups(words, self.cfg.box_pc, self.scale_factor());
            self.galaxies_myr = self.find_pending.take().unwrap_or(self.galaxies_myr);
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

    /// The scale factor and redshift now (1 and 0 in a static box).
    pub fn scale_factor(&self) -> f64 {
        match &self.cfg.cosmology {
            Some(cm) => cm.a_of_t(cm.t_of_a(cm.a_start()) + self.pos_time_myr()),
            None => 1.0,
        }
    }

    pub fn redshift(&self) -> f64 {
        1.0 / self.scale_factor() - 1.0
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
        let gas: Vec<[f32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.gas[self.cur])?).to_vec();
        let chem: Vec<[f32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.chem[self.cur])?).to_vec();
        let acc: Vec<[f32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.acc[self.cur])?).to_vec();
        let pm: Vec<[f32; 4]> = bytemuck::cast_slice(&gpu.read_buffer(&self.pm_acc)?).to_vec();
        let n = self.n as usize;
        let mut s = State {
            pos: vec![Fixed2 { x: 0, y: 0 }; n],
            vel: vec![[0.0; 2]; n],
            mass: vec![0.0; n],
            acc: vec![[0.0; 4]; n],
            kind: vec![0; n],
            star: vec![[0.0; 2]; n],
            about: vec![[0.0; 4]; n],
            gas: vec![[0.0; 4]; n],
            chem: vec![[0.0; 4]; n],
            pm: vec![[0.0; 4]; n],
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
            s.gas[id] = gas[2 * i];
            s.chem[id] = chem[i];
            s.pm[id] = pm[i];
        }
        Ok(s)
    }

    /// Total energy: kinetic + the gas's internal energy + the central mass's potential + half the self-gravity
    /// potential (from the tree and the mesh, at each particle's last force pass, so exact between steps of dt),
    /// Msun pc^2 / Myr^2. With mesh gravity the potential has the periodic box's arbitrary zero, and each particle's
    /// share of its own mesh potential is in it (a constant while masses don't change).
    pub fn energy(&self, s: &State) -> f64 {
        (0..s.vel.len())
            .map(|i| {
                let (v, m, a) = (s.vel[i], s.mass[i] as f64, s.acc[i]);
                let v2 = (v[0] as f64).powi(2) + (v[1] as f64).powi(2);
                let u = if s.kind[i] == init::Kind::Gas as u32 { s.gas[i][0] as f64 } else { 0.0 };
                m * (0.5 * v2 + u + a[3] as f64 + 0.5 * (a[2] as f64 + s.pm[i][2] as f64))
            })
            .sum()
    }

    /// Total momentum, Msun pc / Myr.
    pub fn momentum(s: &State) -> [f64; 2] {
        s.vel.iter().zip(&s.mass).fold([0.0; 2], |p, (v, &m)| [p[0] + m as f64 * v[0] as f64, p[1] + m as f64 * v[1] as f64])
    }
}

/// One galaxy alone in equilibrium (positions, then velocities from its own forces), for `placed_galaxies`.
pub fn galaxy_template(gpu: &Gpu, cfg: &SimConfig, galaxy: init::GalaxyConfig, particles: u32, seed: u64) -> Result<Initial> {
    let tc = SimConfig { scene: Scene::Galaxy, particles, seed, galaxy, finder: FinderConfig { every_myr: 0.0, ..cfg.finder.clone() }, spare_share: 0.0, start_steps: 0, ..cfg.clone() };
    let (mut init, parts) = init::galaxy(&tc);
    let sim = Sim::from_initial(gpu, tc.clone(), &init)?;
    let s = sim.read_state(gpu)?;
    let kin = init::galaxy_velocities(&tc, &init, &parts, &s);
    init.kin = kin;
    Ok(init)
}

/// The placed-galaxy scenes (`Scene::Pair`, `Scene::Group`): galaxies built one by one, then put together. Their
/// halos reach 40 kpc x sqrt(mass / Milky Way's).
fn placed_galaxies(gpu: &Gpu, cfg: &SimConfig) -> Result<Initial> {
    use init::{Placement, place, scaled_galaxy};
    let n = cfg.particles as f64;
    let c = cfg.center_pc;
    let center = Fixed2::from_pc(c.0, c.1, cfg.box_pc);
    match cfg.scene {
        Scene::Pair => {
            let t = galaxy_template(gpu, cfg, init::GalaxyConfig::default(), (n / 2.0) as u32, cfg.seed)?;
            // a parabolic orbit of two 4.1e11 Msun point masses from 120 kpc apart, pericentre 25 kpc
            let m = { let g = init::GalaxyConfig::default(); g.disc_mass + g.bulge_mass + g.halo_mass + g.gas_mass };
            let (d, rp) = (120_000.0f64, 25_000.0f64);
            let v = (2.0 * G * 2.0 * m / d).sqrt();
            let vt = (2.0 * G * 2.0 * m * rp).sqrt() / d;
            let vr = (v * v - vt * vt).sqrt();
            let half = |s: f64| Placement { template: 0, center_pc: (c.0 + s * d / 2.0, c.1), velocity: [-s * vr / 2.0, s * vt / 2.0], angle: if s > 0.0 { 0.6 } else { 0.0 }, mirror: s > 0.0 };
            Ok(place(&[t], center, cfg.box_pc, &[half(-1.0), half(1.0)]))
        }
        _ => {
            // particles by sqrt(mass): large 1, medium 0.3 (x3), dwarfs 0.05 (x20, two templates)
            let sizes: [(f64, usize); 4] = [(1.0, 1), (0.3, 3), (0.05, 10), (0.05, 10)];
            let weight: f64 = sizes.iter().map(|&(f, k)| f.sqrt() * k as f64).sum();
            let mut templates = Vec::new();
            for (i, &(f, _)) in sizes.iter().enumerate() {
                let p = (n * f.sqrt() / weight) as u32;
                templates.push(galaxy_template(gpu, cfg, scaled_galaxy(f), p.max(2_000), cfg.seed + i as u64)?);
            }
            let mut rng = crate::rng::Rng::new(cfg.seed ^ 0x6a09_e667);
            let total_mass: f64 = sizes.iter().map(|&(f, k)| 4.1e11 * f * k as f64).sum();
            let radius = 600_000.0;
            // half the virial speed: the group falls together
            let sigma = 0.5 * (G * total_mass / radius).sqrt() / std::f64::consts::SQRT_2;
            let mut placed: Vec<Placement> = Vec::new();
            for (t, &(f, k)) in sizes.iter().enumerate() {
                for _ in 0..k {
                    let gap = 60_000.0 * f.sqrt().max(0.4);
                    let at = loop {
                        let (r, a) = if t == 0 { (0.0, 0.0) } else { (radius * rng.f64().sqrt(), rng.f64() * std::f64::consts::TAU) };
                        let p = (c.0 + r * a.cos(), c.1 + r * a.sin());
                        if placed.iter().all(|q| (q.center_pc.0 - p.0).hypot(q.center_pc.1 - p.1) > gap) {
                            break p;
                        }
                    };
                    placed.push(Placement {
                        template: t,
                        center_pc: at,
                        velocity: if t == 0 { [0.0; 2] } else { [rng.normal() * sigma, rng.normal() * sigma] },
                        angle: rng.f64() * std::f64::consts::TAU,
                        mirror: rng.f64() < 0.5,
                    });
                }
            }
            Ok(place(&templates, center, cfg.box_pc, &placed))
        }
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
