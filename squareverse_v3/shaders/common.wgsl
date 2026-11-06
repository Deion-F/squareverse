// Parameters shared by the particle and tree passes (src/gravity.rs `Common`). Prepended after fixed.wgsl.

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
    dt: f32,             // Myr
    gm_c: f32,           // G x the central mass
    eps2_c: f32,         // the central mass's softening^2
}

// Particle arrays: pos vec4<u32> (fixed point), kin vec4<f32> (vx, vy, temperature K, luminosity Lsun),
// body vec2<u32> (mass f32 bits, id). Node records: NODE_WORDS u32s a node: centre of mass (4, fixed point),
// box (4: min x, min y, max x, max y, hi words relative to the origin), mass, opening radius^2, and the second
// moments about the centre of mass sxx, sxy, syy (Msun pc^2) for the quadrupole (all f32 bits), one word spare.
// `parents`: internal node k's parent at k, particle j's at n + j.
const NODE_WORDS: u32 = 16u;

const NONE: u32 = 0xFFFFFFFFu;
const LEAF: u32 = 0x80000000u;   // a child reference with this bit set is a particle (leaf), else an internal node

fn flat_index(gid: vec3<u32>, row: u32) -> u32 {
    return gid.x + gid.y * row;
}
