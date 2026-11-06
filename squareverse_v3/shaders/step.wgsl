// Phase-0 workload: every particle orbits one fixed point mass (softened), kick-drift-kick leapfrog.
// It exists to prove the pipeline (fixed-point drift across the box edge, timing, drawing); phase 1 replaces the
// point mass with the tree. Prepended with fixed.wgsl.

struct Params {
    center: vec4<u32>,   // the point mass, fixed point
    unit_pc: f32,        // parsecs per hi unit (box / 2^32)
    inv_unit_pc: f32,
    dt: f32,             // Myr
    gm: f32,             // G x mass, pc^3 / Myr^2
    eps2: f32,           // softening^2, pc^2
    n: u32,
    row: u32,            // invocations per row of workgroups (for dispatches wider than 65535 groups)
    _pad: u32,
}

@group(0) @binding(0) var<uniform> p: Params;
@group(0) @binding(1) var<storage, read_write> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> vel: array<vec2<f32>>;

fn accel(q: vec4<u32>) -> vec2<f32> {
    let r = fx_delta2(q, p.center) * p.unit_pc;
    let s2 = dot(r, r) + p.eps2;
    return -p.gm * r / (s2 * sqrt(s2));
}

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x + gid.y * p.row;
    if (i >= p.n) {
        return;
    }
    var q = pos[i];
    var v = vel[i];
    let half = 0.5 * p.dt;
    v += accel(q) * half;
    q = fx_add2(q, v * (p.dt * p.inv_unit_pc));
    v += accel(q) * half;
    pos[i] = q;
    vel[i] = v;
}
