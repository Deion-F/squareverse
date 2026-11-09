// Once a step of dt, at its start (every particle's step ends there, so velocities are in step): star formation,
// stellar evolution and what stars give back (`emit`, spread to the gas by feedback.wgsl), and super wells
// swallowing what comes too close. Prepended with fixed.wgsl and common.wgsl.
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
@group(0) @binding(4) var<storage, read_write> about: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> ctl: array<u32>;            // [3]: steps of dt begun (the clock)
// [0] how many wells, [1 + w] well w's particle index (wells.wgsl lists them each step), then from WELL_SINK what
// each swallowed: mass, px, py (lo, hi each)
@group(0) @binding(6) var<storage, read_write> wsink: array<atomic<u32>>;
@group(0) @binding(7) var<storage, read> gas: array<vec4<f32>>;            // (u, Σ, H, metallicity) at 2i
// what each star gives back this step: (mass, energy, new He, new C/N/O), (new Mg/Si, new Fe, -, -)
@group(0) @binding(8) var<storage, read_write> emit: array<vec4<f32>>;

const MAX_WELLS: u32 = 64u;
const WELL_SINK: u32 = 65u;

fn well_count() -> u32 {
    return min(atomicLoad(&wsink[0]), MAX_WELLS);
}
const SINK_WORDS: u32 = 6u;
const PART_NEW: u32 = 5u;   // about.w of stars born in the run
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

fn hash(x: u32) -> u32 {
    let v = x * 747796405u + 2891336453u;
    let w = ((v >> ((v >> 28u) + 4u)) ^ v) * 277803737u;
    return (w >> 22u) ^ w;
}

// a uniform number in [0, 1) from a particle's id, the clock and a stream number: the same every run
fn random01(id: u32, k: u32) -> f32 {
    return f32(hash(id ^ hash(ctl[3] * 4u + k)) >> 8u) / 16777216.0;
}

// a star mass from the Kroupa IMF (slope 1.3 from 0.08 to 0.5 Msun, 2.3 to 100), as src/sim/init.rs kroupa_mass
fn kroupa(u1: f32, u2: f32) -> f32 {
    var a = 1.3;
    var lo = 0.08;
    var hi = 0.5;
    if (u1 >= 0.7611) {
        a = 2.3;
        lo = 0.5;
        hi = 100.0;
    }
    let e = 1.0 - a;
    return pow(pow(lo, e) + u2 * (pow(hi, e) - pow(lo, e)), 1.0 / e);
}

// the share of [a0, a1] (Myr) that falls in [lo, hi]
fn overlap(a0: f32, a1: f32, lo: f32, hi: f32) -> f32 {
    return max(min(a1, hi) - max(a0, lo), 0.0);
}

// type Ia supernovae per Msun formed, by age: 1.3e-3 in all, delay time ∝ 1/t from 100 Myr to 13.7 Gyr
fn ia_count(age: f32) -> f32 {
    return 1.3e-3 * log(clamp(age, 100.0, 13700.0) / 100.0) / log(137.0);
}

// Gas that is dense (above gas_b.x Msun/pc^3, Σ over a disc 2 z0 thick) and cool (below gas_b.y K, or within 3x
// of the dense gas's equation of state, common.wgsl eos_u) turns into a
// star particle with chance 1 - exp(-eff dt / t_ff), t_ff = sqrt(3 pi / (32 G rho)) (a set efficiency per free-fall
// time, as Kennicutt-Schmidt). It keeps its mass and elements; its star's mass is drawn from the IMF.
fn form_star(i: u32, b: vec2<u32>) {
    let g = gas[2u * i];
    let rho = g.y / (2.0 * c.gas_b.w);
    // cool enough: under the set temperature, or on (or near) the dense gas's equation of state
    if (rho < c.gas_b.x || g.x > max(u_of_temperature(c.gas_b.y), 3.0 * eos_u(g.y))) {
        return;
    }
    let tff = sqrt(3.0 * 3.14159265 / (32.0 * c.g * rho));
    let id = b.y & ID_MASK;
    if (random01(id, 0u) >= 1.0 - exp(-c.gas_b.z * c.dt / tff)) {
        return;
    }
    // direct collapse: dense, metal-poor and massive enough, it becomes a seed super well instead (wells_b.z on,
    // metallicity under wells_b.w solar, density over wells_c.x, mass over wells_c.y)
    if (c.wells_b.z > 0.5 && g.w < c.wells_b.w && rho > c.wells_c.x && bitcast<f32>(b.x) >= c.wells_c.y) {
        body[i] = vec2<u32>(b.x, (K_WELL << KIND_SHIFT) | id);
        about[i] = vec4<f32>(f32(ctl[3]) * c.dt, 0.0, bitcast<f32>(b.x), 0.0);
        let v = kin[i];
        kin[i] = vec4<f32>(v.xy, 5000.0, 0.0);
        return;
    }
    let m = kroupa(random01(id, 1u), random01(id, 2u));
    body[i] = vec2<u32>(b.x, (K_STAR << KIND_SHIFT) | id);
    about[i] = vec4<f32>(f32(ctl[3]) * c.dt, m, bitcast<f32>(b.x), bitcast<f32>(PART_NEW));
    let v = kin[i];
    kin[i] = vec4<f32>(v.xy, main_sequence(m));
}

@compute @workgroup_size(256)
fn evolve(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    emit[2u * i] = vec4<f32>(0.0);
    emit[2u * i + 1u] = vec4<f32>(0.0);
    let mt = about[i];
    let b = body[i];
    let kind = kind_of(b);
    if (kind == K_GAS) {
        if (c.gas_d.y > 0.5 && ctl[3] > 0u) {
            form_star(i, b);
        }
        return;
    }
    if (mt.y <= 0.0 || kind == K_GONE || kind == K_DM || kind == K_WELL) {
        return;
    }
    let m = mt.y;
    let age = f32(ctl[3]) * c.dt - mt.x;
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
    let old_mass = bitcast<f32>(b.x);
    body[i] = vec2<u32>(bitcast<u32>(mass), (k << KIND_SHIFT) | (b.y & ID_MASK));
    let v = kin[i];
    kin[i] = vec4<f32>(v.xy, tl);

    // what goes back to the gas this step (none at the clock's first tick: that is the start state)
    if (ctl[3] == 0u || c.gas_d.z < 0.5) {
        return;
    }
    let dm = max(old_mass - mass, 0.0);
    var energy = 0.0;
    var fe_ia = 0.0;
    if (c.single_stars == 1u) {
        if (kind == K_STAR && k != K_STAR && m >= 8.0) {
            energy = c.gas_d.x;   // its core-collapse supernova
        }
    } else {
        // core-collapse supernovae, 0.0118 per Msun formed (Kroupa, 8 - 100 Msun), spread over ages 3 - 40 Myr
        energy = mt.z * 0.0118 / 37.0 * overlap(age - c.dt, age, 3.0, 40.0) * c.gas_d.x;
        let n_ia = mt.z * (ia_count(age) - ia_count(age - c.dt));
        energy += n_ia * c.gas_d.x;
        fe_ia = 0.7 * n_ia;
    }
    // new elements in what is given back: early (core collapse) rich in O, Mg, Si, some Fe; later (AGB) C, N
    var fresh: vec4<f32>;
    if (age < 40.0 || (c.single_stars == 1u && m >= 8.0)) {
        fresh = vec4<f32>(0.08, 0.0715, 0.0275, 0.011) * dm;
    } else {
        fresh = vec4<f32>(0.05, 0.02, 0.0, 0.0) * dm;
    }
    emit[2u * i] = vec4<f32>(dm, energy, fresh.x, fresh.y);
    emit[2u * i + 1u] = vec4<f32>(fresh.z, fresh.w + fe_ia, 0.0, 0.0);
}

@compute @workgroup_size(1)
fn tick_clock() {
    ctl[3] += 1u;
}

// adds x (scaled to fixed point; may be negative) to the 64-bit sum in words (at, at + 1)
fn add64(at: u32, x: f32) {
    let v = x * SINK_SCALE;
    let hi = floor(v / TWO32);
    let lo = u32(v - hi * TWO32);
    let old = atomicAdd(&wsink[WELL_SINK + at], lo);
    let carry = select(0u, 1u, old + lo < old);
    atomicAdd(&wsink[WELL_SINK + at + 1u], bitcast<u32>(i32(hi)) + carry);
}

fn read64(at: u32) -> f32 {
    let lo = atomicLoad(&wsink[WELL_SINK + at]);
    let hi = bitcast<i32>(atomicLoad(&wsink[WELL_SINK + at + 1u]));
    return (f32(hi) * TWO32 + f32(lo)) / SINK_SCALE;
}

@compute @workgroup_size(256)
fn swallow(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n || well_count() == 0u) {
        return;
    }
    let b = body[i];
    let kind = kind_of(b);
    // a population particle stands for ~10^5 - 10^6 stars spread over the softening length: a well can't take it
    // whole (real stars are torn apart only within ~1e-5 pc of a well). It took ~500 of them in 2 Gyr (100k,
    // 2026-11-08), growing 4e6 -> 5e8 Msun. Single stars only, for now (phase 3 adds gas, phase 4 wells)
    if (kind == K_WELL || kind == K_GONE || kind == K_DM || (c.single_stars == 0u && kind != K_GAS)) {
        return;
    }
    let q = pos[i];
    let v = kin[i].xy;
    // the nearest well that has it
    var best = NONE;
    var best_r2 = c.acc_r2;
    for (var w = 0u; w < well_count(); w++) {
        let j = atomicLoad(&wsink[1u + w]);
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
    if (w >= well_count()) {
        return;
    }
    let at = w * SINK_WORDS;
    let dm = read64(at);
    if (dm > 0.0) {
        let j = atomicLoad(&wsink[1u + w]);
        let b = body[j];
        let m = bitcast<f32>(b.x);
        let k = kin[j];
        let v = (m * k.xy + vec2<f32>(read64(at + 2u), read64(at + 4u))) / (m + dm);
        body[j] = vec2<u32>(bitcast<u32>(m + dm), b.y);
        kin[j] = vec4<f32>(v, k.zw);
    }
    for (var x = 0u; x < SINK_WORDS; x++) {
        atomicStore(&wsink[WELL_SINK + at + x], 0u);
    }
}
