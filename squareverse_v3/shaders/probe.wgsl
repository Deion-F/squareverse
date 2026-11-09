// Picking and following particles for the window (phase 6), read-only on the particles, so the physics can't tell
// whether anyone is looking. Prepended with fixed.wgsl only.
//
// - `pick_near`, `pick_id`: the particle nearest a point within a radius (stars, gas and wells; dark matter too if
//   asked): the least distance first (atomicMin on its f32 bits, which order like the floats for positive ones),
//   then the least id among those at it, so ties go the same way every time;
// - `track`: everything about the particle with a given id (its index changes with every sort).

struct Probe {
    point: vec4<u32>,   // fixed point
    n: u32,
    row: u32,
    unit_pc: f32,
    radius_pc: f32,
    target_id: u32,
    with_dm: u32,
    _a: u32,
    _b: u32,
}

@group(0) @binding(0) var<uniform> p: Probe;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read> kin: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read> about: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read> chem: array<vec4<f32>>;
@group(0) @binding(6) var<storage, read> gas: array<vec4<f32>>;
// [0] least distance bits, [1] its least id, [2] 1 if found, [3] -, then the tracked particle: pos (4), kin (4),
// body (2), about (4), chem (4), gas (4), found (1)
@group(0) @binding(7) var<storage, read_write> out: array<atomic<u32>>;

const NONE: u32 = 0xFFFFFFFFu;
const ID_MASK: u32 = 0x0FFFFFFFu;

fn index(gid: vec3<u32>) -> u32 {
    return gid.x + gid.y * p.row;
}

fn pickable(i: u32) -> bool {
    let k = body[i].y >> 28u;
    return k != 6u && (k != 1u || p.with_dm != 0u) && bitcast<f32>(body[i].x) > 0.0;
}

fn dist(i: u32) -> f32 {
    return length(fx_delta2(pos[i], p.point) * p.unit_pc);
}

@compute @workgroup_size(1)
fn reset() {
    atomicStore(&out[0], NONE);
    atomicStore(&out[1], NONE);
    atomicStore(&out[2], 0u);
    atomicStore(&out[26], 0u);
}

@compute @workgroup_size(256)
fn pick_near(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = index(gid);
    if (i >= p.n || !pickable(i)) {
        return;
    }
    let d = dist(i);
    if (d < p.radius_pc) {
        atomicMin(&out[0], bitcast<u32>(d));
    }
}

@compute @workgroup_size(256)
fn pick_id(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = index(gid);
    if (i >= p.n || !pickable(i)) {
        return;
    }
    let best = atomicLoad(&out[0]);
    if (best != NONE && bitcast<u32>(dist(i)) == best) {
        atomicMin(&out[1], body[i].y & ID_MASK);
        atomicStore(&out[2], 1u);
    }
}

@compute @workgroup_size(256)
fn track(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = index(gid);
    if (i >= p.n || (body[i].y & ID_MASK) != p.target_id) {
        return;
    }
    let q = pos[i];
    let k = kin[i];
    let a = about[i];
    let ch = chem[i];
    let g = gas[2u * i];
    let w = array<u32, 22>(
        q.x, q.y, q.z, q.w,
        bitcast<u32>(k.x), bitcast<u32>(k.y), bitcast<u32>(k.z), bitcast<u32>(k.w),
        body[i].x, body[i].y,
        bitcast<u32>(a.x), bitcast<u32>(a.y), bitcast<u32>(a.z), bitcast<u32>(a.w),
        bitcast<u32>(ch.x), bitcast<u32>(ch.y), bitcast<u32>(ch.z), bitcast<u32>(ch.w),
        bitcast<u32>(g.x), bitcast<u32>(g.y), bitcast<u32>(g.z), bitcast<u32>(g.w),
    );
    for (var j = 0u; j < 22u; j++) {
        atomicStore(&out[4u + j], w[j]);
    }
    atomicStore(&out[26], 1u);
}
