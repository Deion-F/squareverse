// Once a step of dt, at its start (every particle's step ends there, so velocities are in step): stellar
// evolution, and super wells swallowing what comes too close. Prepended with fixed.wgsl and common.wgsl.
//
// Stellar evolution, from fitting formulas (no star interiors): main-sequence lifetime 10 Gyr x m^-2.5 (at least
// 3 Myr); the last tenth of it a giant (cooler, much brighter); then a remnant by the star's mass: under 8 Msun a
// white dwarf (0.109 m + 0.394 Msun, cooling and fading), 8 - 25 a neutron star (1.4 Msun), above that a black hole
// (m / 4). A particle carries one star's mass (about.y; 0: no evolution) for its colour. If it is one star
// (`single_stars`), its mass becomes the remnant's at death; if it is a population of many stars, it loses mass
// smoothly as its stars die, the fraction returned by a Kroupa population by age a, 0.046 ln(a / 0.276 Myr + 1)
// (Jungwiert et al. 2001). The returned mass just leaves for now; phase 3 gives it back as gas.
//
// Super wells: a particle (single stars only, see `swallow`) within the accretion radius of a well and bound to it (relative kinetic energy below
// G M / r) is swallowed: its mass and momentum are added to the well with integer atomics (64 bits from two words,
// so the sum is the same in any order), and it becomes K_GONE (massless, not drawn).

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read_write> body: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read> about: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> clock: array<u32>;          // [0]: steps of dt begun
@group(0) @binding(6) var<storage, read_write> wells: array<u32>;          // each well's particle index
@group(0) @binding(7) var<storage, read_write> sink: array<atomic<u32>>;   // per well: mass, px, py (lo, hi each)

const SINK_WORDS: u32 = 6u;
const SINK_SCALE: f32 = 1024.0;   // fixed-point units per Msun (and per Msun pc / Myr)
const TWO32: f32 = 4294967296.0;

fn lifetime(m: f32) -> f32 {
    return max(1e4 * pow(m, -2.5), 3.0);
}

// main-sequence (temperature K, luminosity Lsun), as src/sim/init.rs main_sequence
fn main_sequence(m: f32) -> vec2<f32> {
    var l: f32;
    if (m < 0.43) {
        l = 0.23 * pow(m, 2.3);
    } else if (m < 2.0) {
        l = pow(m, 4.0);
    } else if (m < 55.0) {
        l = 1.4 * pow(m, 3.5);
    } else {
        l = 32000.0 * m;
    }
    var r: f32;
    if (m < 1.0) {
        r = pow(m, 0.8);
    } else {
        r = pow(m, 0.57);
    }
    return vec2<f32>(5772.0 * pow(l / (r * r), 0.25), l);
}

fn remnant_kind(m: f32) -> u32 {
    if (m < 8.0) {
        return K_WD;
    }
    if (m < 25.0) {
        return K_NS;
    }
    return K_BH;
}

fn remnant_mass(m: f32) -> f32 {
    if (m < 8.0) {
        return 0.109 * m + 0.394;
    }
    if (m < 25.0) {
        return 1.4;
    }
    return 0.25 * m;
}

@compute @workgroup_size(256)
fn evolve(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let mt = about[i];
    let b = body[i];
    let kind = kind_of(b);
    if (mt.y <= 0.0 || kind == K_GONE || kind == K_DM || kind == K_WELL) {
        return;
    }
    let m = mt.y;
    let age = f32(clock[0]) * c.dt - mt.x;
    let life = lifetime(m);
    var k = K_STAR;
    var tl: vec2<f32>;
    if (age < life) {
        let ms = main_sequence(m);
        let f = max(age, 0.0) / life;
        if (f < 0.9) {
            tl = vec2<f32>(ms.x, ms.y * (1.0 + 0.5 * f));
        } else {
            // a giant: swelling, cooling and brightening
            let g = (f - 0.9) / 0.1;
            tl = vec2<f32>(min(ms.x, 4800.0 - 1300.0 * g), ms.y * (1.5 + 60.0 * g));
        }
    } else {
        k = remnant_kind(m);
        let since = age - life;
        if (k == K_WD) {
            tl = vec2<f32>(max(25000.0 * pow(1.0 + since / 50.0, -0.35), 3000.0), 0.03 * pow(1.0 + since / 10.0, -1.2));
        } else {
            tl = vec2<f32>(5000.0, 0.0);   // neutron stars and black holes: not seen
        }
    }
    var mass: f32;
    if (c.single_stars == 1u) {
        mass = select(mt.z, mt.z * remnant_mass(m) / m, k != K_STAR);
    } else {
        mass = mt.z * (1.0 - min(0.046 * log(max(age, 0.0) / 0.276 + 1.0), 0.5));
    }
    body[i] = vec2<u32>(bitcast<u32>(mass), (k << KIND_SHIFT) | (b.y & ID_MASK));
    let v = kin[i];
    kin[i] = vec4<f32>(v.xy, tl);
}

@compute @workgroup_size(1)
fn tick_clock() {
    clock[0] += 1u;
}

// each well's index in the (sorted) particle arrays
@compute @workgroup_size(256)
fn find_wells(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n || kind_of(body[i]) != K_WELL) {
        return;
    }
    let w = bitcast<u32>(about[i].w);
    if (w < c.n_wells) {
        wells[w] = i;
    }
}

// adds x (scaled to fixed point; may be negative) to the 64-bit sum in words (at, at + 1)
fn add64(at: u32, x: f32) {
    let v = x * SINK_SCALE;
    let hi = floor(v / TWO32);
    let lo = u32(v - hi * TWO32);
    let old = atomicAdd(&sink[at], lo);
    let carry = select(0u, 1u, old + lo < old);
    atomicAdd(&sink[at + 1u], bitcast<u32>(i32(hi)) + carry);
}

fn read64(at: u32) -> f32 {
    let lo = atomicLoad(&sink[at]);
    let hi = bitcast<i32>(atomicLoad(&sink[at + 1u]));
    return (f32(hi) * TWO32 + f32(lo)) / SINK_SCALE;
}

@compute @workgroup_size(256)
fn swallow(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n || c.n_wells == 0u) {
        return;
    }
    let b = body[i];
    let kind = kind_of(b);
    // a population particle stands for ~10^5 - 10^6 stars spread over the softening length: a well can't take it
    // whole (real stars are torn apart only within ~1e-5 pc of a well). It took ~500 of them in 2 Gyr (100k,
    // 2026-11-08), growing 4e6 -> 5e8 Msun. Single stars only, for now (phase 3 adds gas, phase 4 wells)
    if (kind == K_WELL || kind == K_GONE || kind == K_DM || c.single_stars == 0u) {
        return;
    }
    let q = pos[i];
    let v = kin[i].xy;
    // the nearest well that has it
    var best = NONE;
    var best_r2 = c.acc_r2;
    for (var w = 0u; w < c.n_wells; w++) {
        let j = wells[w];
        let d = fx_delta2(pos[j], q) * c.unit_pc;
        let r2 = dot(d, d);
        let dv = v - kin[j].xy;
        let mw = bitcast<f32>(body[j].x);
        if (r2 < best_r2 && 0.5 * dot(dv, dv) < c.g * mw * inverseSqrt(max(r2, 1e-6))) {
            best = w;
            best_r2 = r2;
        }
    }
    if (best == NONE) {
        return;
    }
    let m = bitcast<f32>(b.x);
    add64(best * SINK_WORDS, m);
    add64(best * SINK_WORDS + 2u, m * v.x);
    add64(best * SINK_WORDS + 4u, m * v.y);
    body[i] = vec2<u32>(0u, (K_GONE << KIND_SHIFT) | (b.y & ID_MASK));
    kin[i] = vec4<f32>(0.0, 0.0, 3000.0, 0.0);
}

// one thread a well: take in what it swallowed (mass, and momentum so its velocity changes)
@compute @workgroup_size(64)
fn swallow_apply(@builtin(global_invocation_id) gid: vec3<u32>) {
    let w = gid.x;
    if (w >= c.n_wells) {
        return;
    }
    let at = w * SINK_WORDS;
    let dm = read64(at);
    if (dm > 0.0) {
        let j = wells[w];
        let b = body[j];
        let m = bitcast<f32>(b.x);
        let k = kin[j];
        let v = (m * k.xy + vec2<f32>(read64(at + 2u), read64(at + 4u))) / (m + dm);
        body[j] = vec2<u32>(bitcast<u32>(m + dm), b.y);
        kin[j] = vec4<f32>(v, k.zw);
    }
    for (var x = 0u; x < SINK_WORDS; x++) {
        atomicStore(&sink[at + x], 0u);
    }
}
