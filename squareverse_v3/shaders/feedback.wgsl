// What stars give back (evolve.wgsl `emit`: mass, supernova energy, new elements) goes to the nearest gas particle
// within gas_c.z pc (none near: it is lost). Sums are 64-bit integer atomics, so the result doesn't depend on the
// order threads arrive in. The material comes with the star's birth elements plus what it made. Putting a whole
// supernova's energy into one neighbour heats it far above 10^6 K, so it doesn't radiate the energy away at once at
// this resolution (as stochastic thermal feedback, Dalla Vecchia & Schaye 2012). feedback_apply.wgsl takes it in.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read> chem: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read> emit: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read> child: array<vec2<u32>>;
@group(0) @binding(6) var<storage, read> node: array<vec4<u32>>;
@group(0) @binding(7) var<storage, read> ctl: array<u32>;
// per particle, 6 sums of 2 words: mass, energy, He, C/N/O, Mg/Si, Fe
@group(0) @binding(8) var<storage, read_write> deposit: array<atomic<u32>>;

const STACK: u32 = 96u;
const TWO32: f32 = 4294967296.0;
const MASS_SCALE: f32 = 1048576.0;   // fixed-point units per Msun

fn rel(q: vec4<u32>) -> vec2<u32> {
    return vec2<u32>(q.x - c.origin_x, q.z - c.origin_y);
}

fn box_distance(p: vec2<u32>, r: u32) -> f32 {
    return box_distance_to(p, node[NODE_VEC4 * r + 3u]);
}

fn add64(at: u32, x: f32) {
    let w = split64(x);
    let old = atomicAdd(&deposit[at], w.x);
    let carry = select(0u, 1u, old + w.x < old);
    atomicAdd(&deposit[at + 1u], w.y + carry);
}

// The nearest gas particle within the search radius to q (NONE: none). A function of its own, so that only the
// threads that search set up its stack (an entry point's locals are set up by every thread it runs).
fn nearest_gas(q: vec4<u32>) -> u32 {
    let g0 = ctl[1];
    let g1 = ctl[2];
    let p = rel(q);
    var best = NONE;
    var best_d = c.gas_c.z;
    var stack: array<u32, STACK>;
    var sp = 0u;
    if (c.n > 1u && g1 > g0) {
        stack[0] = 0u;
        sp = 1u;
    }
    while (sp > 0u) {
        sp -= 1u;
        let r = stack[sp];
        if ((r & LEAF) != 0u) {
            let j = r & ~LEAF;
            if (j < g0 || j >= g1) {
                continue;
            }
            let d = length(fx_delta2(pos[j], q) * c.unit_pc);
            if (d < best_d) {
                best_d = d;
                best = j;
            }
            continue;
        }
        let t = node[NODE_VEC4 * r + 4u];   // (first particle, count, -, -)
        if (t.x >= g1 || t.x + t.y <= g0 || box_distance(p, r) >= best_d || sp + 2u > STACK) {
            continue;
        }
        let ch = child[r];
        stack[sp] = ch.x;
        stack[sp + 1u] = ch.y;
        sp += 2u;
    }
    return best;
}

@compute @workgroup_size(256)
fn spread(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let e0 = emit[2u * i];
    if (e0.x <= 0.0 && e0.y <= 0.0) {
        return;
    }
    let e1 = emit[2u * i + 1u];
    let best = nearest_gas(pos[i]);
    if (best == NONE) {
        return;
    }
    // the star's birth elements in what it sheds, plus what it made
    let made = e0.z + e0.w + e1.x + e1.y;
    let base = max(e0.x - made, 0.0);
    let born = chem[i];
    let at = 12u * best;
    add64(at, e0.x * MASS_SCALE);
    add64(at + 2u, e0.y);
    add64(at + 4u, (born.x * base + e0.z) * MASS_SCALE);
    add64(at + 6u, (born.y * base + e0.w) * MASS_SCALE);
    add64(at + 8u, (born.z * base + e1.x) * MASS_SCALE);
    add64(at + 10u, (born.w * base + e1.y) * MASS_SCALE);
}
