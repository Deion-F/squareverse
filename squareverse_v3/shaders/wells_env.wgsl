// Super wells and their surroundings, once a step of dt, one workgroup a well (at most MAX_WELLS):
//
// `surroundings`:
// * Bondi accretion from the nearest gas particle: mdot = 4 pi G² M² rho / (c_s² + v²)^(3/2), rho = Σ / 2 z0, capped
//   at Eddington (M / t_Salpeter, 45 Myr for 10% radiative efficiency) and at a quarter of that particle a step.
//   The mass leaves the gas particle (through feedback.wgsl's deposit, as a negative mass) with its momentum.
// * AGN feedback: wells_a.z (radiative x coupling efficiency, 0.1 x 0.15) of mdot c² heats that same gas particle.
// * Dynamical friction (Chandrasekhar, Maxwellian field) from the stars and dark matter within wells_a.y pc, for a
//   well too light for the tree to give it properly: weighted by (1 - M / 50 m), m the field particles' mean mass.
//   ln Λ = 3; the kick never reverses the well's speed relative to the field.
// Mergers: wells_merge.wgsl.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read_write> body: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read> gas: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read> child: array<vec2<u32>>;
@group(0) @binding(6) var<storage, read> node: array<vec4<u32>>;
@group(0) @binding(7) var<storage, read_write> wsink: array<atomic<u32>>;
@group(0) @binding(8) var<storage, read_write> deposit: array<atomic<u32>>;

const MAX_WELLS: u32 = 256u;
const STACK: u32 = 96u;
const TWO32: f32 = 4294967296.0;
const MASS_SCALE: f32 = 1048576.0;
const C2: f32 = 9.4e10;   // c², (pc/Myr)²

fn well_count() -> u32 {
    return min(atomicLoad(&wsink[0]), MAX_WELLS);
}

fn rel(q: vec4<u32>) -> vec2<u32> {
    return vec2<u32>(q.x - c.origin_x, q.z - c.origin_y);
}

fn box_distance(p: vec2<u32>, r: u32) -> f32 {
    return box_distance_to(p, node[NODE_VEC4 * r + 1u]);
}

fn add64(at: u32, x: f32) {
    let w = split64(x);
    let old = atomicAdd(&deposit[at], w.x);
    let carry = select(0u, 1u, old + w.x < old);
    atomicAdd(&deposit[at + 1u], w.y + carry);
}

// erf, Abramowitz & Stegun 7.1.26
fn erf_approx(x: f32) -> f32 {
    let t = 1.0 / (1.0 + 0.3275911 * x);
    let y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * exp(-x * x);
    return y;
}

const FRONT: u32 = 192u;

var<workgroup> w_index: u32;      // the well's particle (NONE: none in this workgroup)
var<workgroup> front: array<u32, FRONT>;
var<workgroup> n_front: u32;
var<workgroup> part_m: array<f32, 64>;
var<workgroup> part_n: array<f32, 64>;
var<workgroup> part_mv: array<vec2<f32>, 64>;
var<workgroup> part_mv2: array<f32, 64>;
var<workgroup> part_gd: array<f32, 64>;
var<workgroup> part_gj: array<u32, 64>;

// One workgroup a well: the tree near it is cut into up to FRONT pieces (`front`, by the first thread), each of
// the 64 threads walks some of them, and the first thread adds up what they found. (One thread a well walked the
// ~10^4 particles within 500 pc of a galaxy's centre alone: 13 - 19 ms at 500k, 2026-11-09.)
@compute @workgroup_size(64)
fn surroundings(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let w = wg.x;
    let reach = c.wells_a.y;
    if (li == 0u) {
        w_index = NONE;
        n_front = 0u;
        if (w < well_count()) {
            let i0 = atomicLoad(&wsink[1u + w]);
            if (kind_of(body[i0]) == K_WELL) {
                w_index = i0;
            }
        }
        if (w_index != NONE && c.n > 1u) {
            // breadth first from the root, opening what reaches the well, until the pieces are many enough
            let p0 = rel(pos[w_index]);
            front[0] = 0u;
            var nf = 1u;
            var opened = true;
            while (opened && nf < 160u) {
                opened = false;
                var k = 0u;
                let before = nf;
                while (k < nf && nf + 1u < FRONT) {
                    let r = front[k];
                    if ((r & LEAF) == 0u && box_distance(p0, r) < reach) {
                        let ch = child[r];
                        front[k] = ch.x;
                        front[nf] = ch.y;
                        nf += 1u;
                        opened = true;
                    }
                    k += 1u;
                    if (k >= before) {
                        break;
                    }
                }
            }
            n_front = nf;
        }
    }
    let i = workgroupUniformLoad(&w_index);
    if (i == NONE) {
        return;
    }
    let q = pos[i];
    let p = rel(q);
    // the field (stars, remnants, dark matter) within reach, and the nearest gas
    var m_env = 0.0;
    var n_env = 0.0;
    var mv = vec2<f32>(0.0);
    var mv2 = 0.0;
    var gas_j = NONE;
    var gas_d = reach;
    var stack: array<u32, STACK>;
    let nf = n_front;
    for (var f = li; f < nf; f += 64u) {
        stack[0] = front[f];
        var sp = 1u;
        while (sp > 0u) {
            sp -= 1u;
            let r = stack[sp];
            if ((r & LEAF) != 0u) {
                let j = r & ~LEAF;
                if (j == i) {
                    continue;
                }
                let d = length(fx_delta2(pos[j], q) * c.unit_pc);
                if (d >= reach) {
                    continue;
                }
                let bj = body[j];
                let k = kind_of(bj);
                if (k == K_GAS) {
                    if (d < gas_d) {
                        gas_d = d;
                        gas_j = j;
                    }
                } else if (k != K_WELL && k != K_GONE) {
                    let m = bitcast<f32>(bj.x);
                    let v = kin[j].xy;
                    m_env += m;
                    n_env += 1.0;
                    mv += m * v;
                    mv2 += m * dot(v, v);
                }
                continue;
            }
            if (box_distance(p, r) >= reach || sp + 2u > STACK || bitcast<f32>(node[NODE_VEC4 * r + 2u].x) <= 0.0) {
                continue;
            }
            let ch = child[r];
            stack[sp] = ch.x;
            stack[sp + 1u] = ch.y;
            sp += 2u;
        }
    }
    part_m[li] = m_env;
    part_n[li] = n_env;
    part_mv[li] = mv;
    part_mv2[li] = mv2;
    part_gd[li] = gas_d;
    part_gj[li] = gas_j;
    workgroupBarrier();
    if (li != 0u) {
        return;
    }
    // the sums, in a fixed order (the same every run); the nearest gas, ties to the lower index
    m_env = 0.0;
    n_env = 0.0;
    mv = vec2<f32>(0.0);
    mv2 = 0.0;
    gas_d = reach;
    gas_j = NONE;
    for (var t = 0u; t < 64u; t++) {
        m_env += part_m[t];
        n_env += part_n[t];
        mv += part_mv[t];
        mv2 += part_mv2[t];
        if (part_gj[t] != NONE && (part_gd[t] < gas_d || (part_gd[t] == gas_d && part_gj[t] < gas_j))) {
            gas_d = part_gd[t];
            gas_j = part_gj[t];
        }
    }
    let bw = body[i];
    var mw = bitcast<f32>(bw.x);
    var vw = kin[i].xy;

    let dt = c.dt;
    // Bondi accretion, Eddington-capped, and the AGN's heat
    if (c.wells_b.x > 0.5 && gas_j != NONE) {
        let g = gas[2u * gas_j];
        let mg = bitcast<f32>(body[gas_j].x);
        let rho = gas_rho(g.y);
        let cs2 = c.gas_a.w * (c.gas_a.w - 1.0) * g.x;
        let vg = kin[gas_j].xy;
        let dv = vg - vw;
        let s2 = cs2 + dot(dv, dv);
        let bondi = 4.0 * 3.14159265 * c.g * c.g * mw * mw * rho / max(s2 * sqrt(s2), 1e-12);
        let mdot = min(bondi, mw / c.wells_a.w);
        let dm = min(mdot * dt, 0.25 * mg);
        if (dm > 0.0) {
            let at = 12u * gas_j;
            add64(at, -dm * MASS_SCALE);
            add64(at + 2u, c.wells_a.z * dm * C2);
            vw = (mw * vw + dm * vg) / (mw + dm);
            mw += dm;
        }
    }
    // dynamical friction, for a well the particles can't drag properly themselves
    if (c.wells_b.y > 0.5 && m_env > 0.0 && n_env >= 8.0) {
        let mean_v = mv / m_env;
        let sigma2 = max(0.5 * (mv2 / m_env - dot(mean_v, mean_v)), 1e-6);   // per axis
        let v = vw - mean_v;
        let speed = length(v);
        let weight = clamp(1.0 - mw / (50.0 * m_env / n_env), 0.0, 1.0);
        if (speed > 1e-6 && weight > 0.0) {
            let rho = gas_rho(m_env / (3.14159265 * reach * reach));
            let x = speed / sqrt(2.0 * sigma2);
            let f = erf_approx(x) - 1.1283792 * x * exp(-x * x);
            let a = 4.0 * 3.14159265 * c.g * c.g * mw * rho * 3.0 * f / (speed * speed);
            vw -= v / speed * min(a * dt * weight, speed);
        }
    }
    body[i] = vec2<u32>(bitcast<u32>(mw), bw.y);
    let k = kin[i];
    kin[i] = vec4<f32>(vw, k.zw);
}
