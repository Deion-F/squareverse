// The galaxy finder (friends of friends): particles closer than the linking length (c.finder.x pc, physical, or
// comoving if c.finder.w is set) are in
// the same group; dark matter takes part if c.finder.y is set (the universe: halos), else only stars, gas and wells
// (placed galaxies, whose halos overlap). Every group's label ends as its lowest particle index:
//
// - `init`: each linked particle its own label;
// - `link` (repeated, each round in slices the window can spread over frames): each takes the lowest label among its neighbours (a tree walk), and hooks its old label's
//   particle to it too, so whole chains merge in a few rounds (as Shiloach & Vishkin);
// - `jump`: label = label of label (pointer jumping);
// - `next_round`: after each round; a round that changed no label leaves a fixed point, so the rounds after it
//   return at once (the result is the same);
// - `count`, `assign`: groups of at least c.finder.z particles get a slot in `groups` (up to MAX_GROUPS);
// - `sums`: each slot's totals: members, mass, centre of mass (relative to its first particle), momentum, and the
//   mass in stars, gas and wells (64-bit integer sums, so any order gives the same result).
//
// It runs once every few steps (src/sim/mod.rs `Work::Find`); its result goes to the CPU (`Sim::galaxies`). Nothing
// in the physics depends on it.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read> child: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read> node: array<vec4<u32>>;
@group(0) @binding(5) var<storage, read_write> label: array<atomic<u32>>;
@group(0) @binding(6) var<storage, read_write> gidx: array<atomic<u32>>;      // per root: members, then its slot
@group(0) @binding(7) var<storage, read_write> groups: array<atomic<u32>>;    // [0] slots used, then GROUP_WORDS a slot, then CHANGED, LAST
@group(0) @binding(8) var<storage, read> kin: array<vec4<f32>>;
@group(0) @binding(9) var<uniform> t: Tick;   // `link` runs in slices of the particles, from t.start

const STACK: u32 = 96u;
const MAX_GROUPS: u32 = 4096u;
const GROUP_WORDS: u32 = 26u;
const HAS_SLOT: u32 = 0x80000000u;
// after the slots: whether this round has changed a label so far (1/0), and whether the last round did
const CHANGED: u32 = 1u + MAX_GROUPS * GROUP_WORDS;
const LAST: u32 = CHANGED + 1u;
const TWO32: f32 = 4294967296.0;
const MASS_SCALE: f32 = 1024.0;   // units per Msun
const MOMENT_SCALE: f32 = 64.0;   // units per Msun kpc, and per Msun pc / Myr

fn linked(i: u32) -> bool {
    let k = kind_of(body[i]);
    if (k == K_GONE || bitcast<f32>(body[i].x) <= 0.0) {
        return false;
    }
    return k != K_DM || c.finder.y > 0.5;
}

fn rel(q: vec4<u32>) -> vec2<u32> {
    return vec2<u32>(q.x - c.origin_x, q.z - c.origin_y);
}

@compute @workgroup_size(256)
fn init(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i < CHANGED) {
        atomicStore(&groups[i], 0u);
    }
    if (i == CHANGED) {
        atomicStore(&groups[CHANGED], 0u);
        atomicStore(&groups[LAST], 1u);   // the first round runs
    }
    if (i >= c.n) {
        return;
    }
    atomicStore(&label[i], select(NONE, i, linked(i)));
    atomicStore(&gidx[i], 0u);
}

// the lowest label among particle i's friends and its own (`own`). A function of its own, so that only the linked
// particles' threads set up its stack (an entry point's locals are set up by every thread it runs).
fn lowest_label(i: u32, own: u32) -> u32 {
    let q = pos[i];
    let p = rel(q);
    let b = c.finder.x * select(1.0, c.cosmo.x, c.finder.w > 0.5);   // comoving in the universe
    var best = own;
    var stack: array<u32, STACK>;
    var sp = 0u;
    if (c.n > 1u) {
        stack[0] = 0u;
        sp = 1u;
    }
    while (sp > 0u) {
        sp -= 1u;
        let r = stack[sp];
        if ((r & LEAF) != 0u) {
            let j = r & ~LEAF;
            if (j == i) {
                continue;
            }
            let lj = atomicLoad(&label[j]);
            if (lj < best && dot(fx_delta2(pos[j], q), fx_delta2(pos[j], q)) * c.unit_pc * c.unit_pc < b * b) {
                best = lj;
            }
            continue;
        }
        let bx = node[NODE_VEC4 * r + 3u];
        // (massless nodes hold only spare and swallowed slots; without dark matter linked, its own part of the tree
        // is left out: dark matter sorts last, so a node whose first particle is dark matter holds nothing else)
        let run = node[NODE_VEC4 * r + 4u];   // (first particle, count, -, -)
        if (box_distance_to(p, bx) >= b || sp + 2u > STACK || bitcast<f32>(node[NODE_VEC4 * r + 1u].x) <= 0.0
            || (c.finder.y < 0.5 && kind_of(body[run.x]) == K_DM)) {
            continue;
        }
        // a node wholly within b: all of it is linked to this particle, so one label from it does (the rest follow
        // over the rounds, through this particle); without this, dense centres cost thousands of pairs a particle
        let fx = max(abs(bitcast<i32>(p.x - bx.x)), abs(bitcast<i32>(p.x - bx.z)));
        let fy = max(abs(bitcast<i32>(p.y - bx.y)), abs(bitcast<i32>(p.y - bx.w)));
        if (length(vec2<f32>(f32(fx), f32(fy)) * c.unit_pc) + 2.0 * c.unit_pc < b) {
            let first = run.x;
            if (linked(first)) {
                best = min(best, atomicLoad(&label[first]));
                continue;
            }
        }
        let ch = child[r];
        stack[sp] = ch.x;
        stack[sp + 1u] = ch.y;
        sp += 2u;
    }
    return best;
}

@compute @workgroup_size(256)
fn link(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = t.start + flat_index(gid, c.row);
    if (i >= c.n || atomicLoad(&groups[LAST]) == 0u) {
        return;
    }
    let own = atomicLoad(&label[i]);
    if (own == NONE) {
        return;
    }
    let best = lowest_label(i, own);
    if (best < own) {
        atomicMin(&label[i], best);
        atomicMin(&label[own], best);
        changed();
    }
}

fn changed() {
    if (atomicLoad(&groups[CHANGED]) == 0u) {
        atomicStore(&groups[CHANGED], 1u);
    }
}

@compute @workgroup_size(1)
fn next_round() {
    atomicStore(&groups[LAST], atomicLoad(&groups[CHANGED]));
    atomicStore(&groups[CHANGED], 0u);
}

@compute @workgroup_size(256)
fn jump(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n || atomicLoad(&groups[LAST]) == 0u) {
        return;
    }
    let l = atomicLoad(&label[i]);
    if (l == NONE) {
        return;
    }
    let ll = atomicLoad(&label[l]);
    if (ll < l) {
        atomicMin(&label[i], ll);
        changed();
    }
}

@compute @workgroup_size(256)
fn count(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let l = atomicLoad(&label[i]);
    if (l != NONE) {
        atomicAdd(&gidx[l], 1u);
    }
}

@compute @workgroup_size(256)
fn assign(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    if (atomicLoad(&label[i]) != i) {
        return;
    }
    let members = atomicLoad(&gidx[i]);
    if (f32(members) < c.finder.z) {
        atomicStore(&gidx[i], 0u);
        return;
    }
    let slot = atomicAdd(&groups[0], 1u);
    if (slot >= MAX_GROUPS) {
        atomicStore(&gidx[i], 0u);
        return;
    }
    atomicStore(&gidx[i], HAS_SLOT | slot);
    let at = 1u + slot * GROUP_WORDS;
    let q = pos[i];
    atomicStore(&groups[at + 1u], i);
    atomicStore(&groups[at + 2u], q.x);
    atomicStore(&groups[at + 3u], q.y);
    atomicStore(&groups[at + 4u], q.z);
    atomicStore(&groups[at + 5u], q.w);
}

fn add64(at: u32, xf: f32) {
    let w = split64(round(xf));   // rounded, not cut: cutting biased the centres by half a unit a particle
    let old = atomicAdd(&groups[at], w.x);
    let carry = select(0u, 1u, old + w.x < old);
    atomicAdd(&groups[at + 1u], w.y + carry);
}

// per slot: members, root, root position (4), then 2-word sums: mass (1/1024 Msun), mass x offset (x, y; 1/64 Msun
// kpc), momentum (x, y; 1/64 Msun pc/Myr), star mass, gas mass, well mass, dark matter mass (1/1024 Msun), mass x offset² (1/64 Msun kpc², for the size)
@compute @workgroup_size(256)
fn sums(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let l = atomicLoad(&label[i]);
    if (l == NONE) {
        return;
    }
    let s = atomicLoad(&gidx[l]);
    if ((s & HAS_SLOT) == 0u) {
        return;
    }
    let at = 1u + (s & ~HAS_SLOT) * GROUP_WORDS;
    let root = vec4<u32>(atomicLoad(&groups[at + 2u]), atomicLoad(&groups[at + 3u]), atomicLoad(&groups[at + 4u]), atomicLoad(&groups[at + 5u]));
    let m = bitcast<f32>(body[i].x);
    let d = fx_delta2(pos[i], root) * (c.unit_pc / 1000.0);   // kpc, physical
    atomicAdd(&groups[at], 1u);
    add64(at + 6u, m * MASS_SCALE);
    add64(at + 8u, m * d.x * MOMENT_SCALE);
    add64(at + 10u, m * d.y * MOMENT_SCALE);
    add64(at + 24u, m * dot(d, d) * MOMENT_SCALE);
    let v = kin[i].xy;
    add64(at + 12u, m * v.x * MOMENT_SCALE);
    add64(at + 14u, m * v.y * MOMENT_SCALE);
    let k = kind_of(body[i]);
    if (k == K_GAS) {
        add64(at + 18u, m * MASS_SCALE);
    } else if (k == K_WELL) {
        add64(at + 20u, m * MASS_SCALE);
    } else if (k == K_DM) {
        add64(at + 22u, m * MASS_SCALE);
    } else {
        add64(at + 16u, m * MASS_SCALE);
    }
}
