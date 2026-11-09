// Parameters shared by the particle and tree passes (src/sim/mod.rs `Common`). Prepended after fixed.wgsl.

struct Common {
    center: vec4<u32>,   // the central point mass, fixed point
    n: u32,              // particles
    row: u32,            // invocations per row of workgroups (dispatches wider than 65,535 groups)
    origin_x: u32,       // the tree's origin, hi words: positions are taken relative to it, so the
    origin_y: u32,       // particles' region never straddles the wrap (until phase 5's periodic gravity)
    theta: f32,          // opening angle
    eps2: f32,           // particles' softening^2, pc^2
    g: f32,              // G, pc^3 / (Msun Myr^2)
    unit_pc: f32,        // parsecs per hi unit
    inv_unit_pc: f32,
    dt: f32,             // the longest step (bin 0), Myr
    gm_c: f32,           // G x the central mass
    eps2_c: f32,         // the central mass's softening^2
    levels: u32,         // time-step bins: bin b steps dt / 2^b, b < levels
    dt_min: f32,         // the sub-step: dt / 2^(levels - 1)
    eta_eps: f32,        // 2 eta softening: a particle wants steps of at most sqrt(eta_eps / |a|)
    eta_jerk: f32,       // and at most eta_jerk |a| / |da/dt| (0: off)
    open_small: f32,     // nodes smaller than this (pc) act as one mass at any distance, unless they hold the particle
    _spare: u32,
    acc_r2: f32,         // a super well swallows bound particles nearer than this, pc^2
    single_stars: u32,   // 1: each star particle is one star (its mass changes at death), 0: a population
    eps2_kind: array<vec4<f32>, 2>,   // softening^2 by kind (K_*), pc^2; a pair uses the larger of its two
    gas_a: vec4<f32>,    // SPH: neighbours wanted, viscosity alpha, Courant factor, gamma
    gas_b: vec4<f32>,    // star formation: least density (Msun/pc^3), most temperature (K), efficiency per free fall, disc half-thickness z0 (pc)
    gas_c: vec4<f32>,    // temperature floor (K), cooling on (1/0), feedback search radius (pc), least kernel reach H (pc)
    gas_d: vec4<f32>,    // supernova energy (Msun pc^2/Myr^2), star formation on, feedback on, -
    wells_a: vec4<f32>,  // wells: merge distance (pc), surroundings radius (pc), AGN efficiency (of mc²), Salpeter time (Myr)
    wells_b: vec4<f32>,  // Bondi accretion on, dynamical friction on, direct collapse on, its largest metallicity (solar)
    wells_c: vec4<f32>,  // direct collapse: least density (Msun/pc^3), least mass (Msun); -, -
}

// Particle kinds, in the top 4 bits of body.y (the id below them).
const KIND_SHIFT: u32 = 28u;
const ID_MASK: u32 = 0x0FFFFFFFu;
const K_STAR: u32 = 0u;
const K_DM: u32 = 1u;     // dark matter
const K_WELL: u32 = 2u;   // super well (black hole)
const K_WD: u32 = 3u;     // white dwarf
const K_NS: u32 = 4u;     // neutron star
const K_BH: u32 = 5u;     // stellar black hole
const K_GONE: u32 = 6u;   // swallowed: massless, not drawn
const K_GAS: u32 = 7u;    // gas (SPH)

// Softening classes: each sorts into its own part of the tree (morton.wgsl), 0 stars and the rest, 1 gas, 2 dark matter.
fn class_of(kind: u32) -> u32 {
    if (kind == K_DM) {
        return 2u;
    }
    if (kind == K_GAS) {
        return 1u;
    }
    return 0u;
}

// Gas: (u, Σ, H, metallicity / solar) and (hydro ax, ay, du/dt, signal speed) per particle, in `gas` at 2i and 2i + 1. u is the
// internal energy per mass, (pc/Myr)^2; Σ the surface density, Msun/pc^2; H the kernel's reach, pc. The pressure
// (2D) is (gamma - 1) Σ u. Temperature: mean molecular mass 0.6 when ionised, 1.27 when neutral.
const U_TO_K_IONISED: f32 = 46.3;    // K per (pc/Myr)^2 at mu 0.6, gamma 5/3
const U_TO_K_NEUTRAL: f32 = 98.0;    // at mu 1.27

fn gas_temperature(u: f32) -> f32 {
    let ti = u * U_TO_K_IONISED;
    if (ti >= 1e4) {
        return ti;
    }
    return min(u * U_TO_K_NEUTRAL, 1e4);
}

fn u_of_temperature(t: f32) -> f32 {
    if (t >= 1e4) {
        return t / U_TO_K_IONISED;
    }
    return t / U_TO_K_NEUTRAL;
}

// The most internal energy a gas particle of kernel reach h may hold: hotter, its sound speed would want a step
// shorter than the shortest one (Courant, signal speed ~2 c_s, with a margin of 2). Supernova heat beyond it is
// lost (feedback_apply.wgsl); the hydro itself isn't capped.
fn u_ceiling(h: f32) -> f32 {
    let cmax = c.gas_a.z * h / (4.0 * c.dt_min);
    return cmax * cmax / (c.gas_a.w * (c.gas_a.w - 1.0));
}

// Dense gas (above the star formation density) sits on an effective equation of state, P ∝ rho^(4/3) from 8,000 K
// at the threshold (Schaye & Dalla Vecchia 2008): it stands for the unresolved cold and warm phases, and keeps the
// gas from collapsing into clumps the kernel can't resolve (without it the disc's gas fragmented into ~40 massive
// clumps within 300 Myr, 2026-11-08). Returns that floor's u (0 below the threshold).
fn eos_u(sigma: f32) -> f32 {
    let rho = sigma / (2.0 * c.gas_b.w);
    if (rho <= c.gas_b.x) {
        return 0.0;
    }
    return u_of_temperature(8000.0) * pow(rho / c.gas_b.x, 1.0 / 3.0);
}

// the Wendland C2 kernel in 2D, reach H: W = 7 / (pi H^2) (1 - q)^4 (1 + 4q), q = r / H < 1
fn kernel_w(r: f32, h: f32) -> f32 {
    let q = r / h;
    if (q >= 1.0) {
        return 0.0;
    }
    let a = 1.0 - q;
    return 2.2281692 / (h * h) * a * a * a * a * (1.0 + 4.0 * q);
}

// dW/dr
fn kernel_dw(r: f32, h: f32) -> f32 {
    let q = r / h;
    if (q >= 1.0) {
        return 0.0;
    }
    let a = 1.0 - q;
    return -2.2281692 / (h * h * h) * 20.0 * q * a * a * a;
}

fn kind_of(b: vec2<u32>) -> u32 {
    return b.y >> KIND_SHIFT;
}

fn eps2_of(k: u32) -> f32 {
    return c.eps2_kind[k >> 2u][k & 3u];
}

// Per dispatch (a dynamic-offset uniform): which sub-step of the longest step this is, and where a force-pass
// slice starts.
struct Tick {
    s: u32,       // 0 .. 2^(levels - 1) - 1
    start: u32,   // the slice's first particle
    _a: u32,
    _b: u32,
}

// Block time steps: a particle in bin b takes steps of 2^(levels - 1 - b) sub-steps, aligned to multiples of that.
fn bin_period(levels: u32, b: u32) -> u32 {
    return 1u << (levels - 1u - b);
}

// does a step of bin b begin at the start of sub-step s?
fn bin_starts(levels: u32, b: u32, s: u32) -> bool {
    return (s & (bin_period(levels, b) - 1u)) == 0u;
}

// does a step of bin b end at the end of sub-step s?
fn bin_ends(levels: u32, b: u32, s: u32) -> bool {
    return ((s + 1u) & (bin_period(levels, b) - 1u)) == 0u;
}

// Particle arrays: pos vec4<u32> (fixed point), kin vec4<f32> (vx, vy, temperature K, luminosity Lsun),
// body vec2<u32> (mass f32 bits, kind << KIND_SHIFT | id), about vec4<f32> (birth time Myr, the star's mass Msun
// (0: no stellar evolution), the particle's mass at birth, the super well's number as f32 bits for wells).
// Node records: NODE_WORDS u32s a node: centre of mass (4, fixed point), box (4: min x, min y, max x, max y, hi
// words relative to the origin), mass, opening radius^2, and the second moments about the centre of mass sxx, sxy,
// syy (Msun pc^2) for the quadrupole (all f32 bits), then the node's particles: the first one's index and how many
// (a node covers a contiguous run of the sorted particles), the largest softening^2 among them, and the largest gas
// smoothing length H among them (pc; 0 without gas), then 3 spare words.
// `parents`: internal node k's parent at k, particle j's at n + j.
const NODE_WORDS: u32 = 20u;
const NODE_VEC4: u32 = 5u;

const NONE: u32 = 0xFFFFFFFFu;
const LEAF: u32 = 0x80000000u;   // a child reference with this bit set is a particle (leaf), else an internal node

fn flat_index(gid: vec3<u32>, row: u32) -> u32 {
    return gid.x + gid.y * row;
}
