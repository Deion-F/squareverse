// Super wells and their surroundings, once a step of dt, one thread a well (at most MAX_WELLS):
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
    let b = node[NODE_VEC4 * r + 1u];
    let dx = select(0u, b.x - p.x, p.x < b.x) + select(0u, p.x - b.z, p.x > b.z);
    let dy = select(0u, b.y - p.y, p.y < b.y) + select(0u, p.y - b.w, p.y > b.w);
    return max(length(vec2<f32>(f32(dx), f32(dy)) * c.unit_pc) - 2.0 * c.unit_pc, 0.0);
}

fn add64(at: u32, x: f32) {
    let hi = floor(x / TWO32);
    let lo = u32(x - hi * TWO32);
    let old = atomicAdd(&deposit[at], lo);
    let carry = select(0u, 1u, old + lo < old);
    atomicAdd(&deposit[at + 1u], bitcast<u32>(i32(hi)) + carry);
}

// erf, Abramowitz & Stegun 7.1.26
fn erf_approx(x: f32) -> f32 {
    let t = 1.0 / (1.0 + 0.3275911 * x);
    let y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * exp(-x * x);
    return y;
}

@compute @workgroup_size(64)
fn surroundings(@builtin(global_invocation_id) gid: vec3<u32>) {
    let w = gid.x;
    if (w >= well_count()) {
        return;
    }
    let i = atomicLoad(&wsink[1u + w]);
    let bw = body[i];
    if (kind_of(bw) != K_WELL) {
        return;
    }
    var mw = bitcast<f32>(bw.x);
    let q = pos[i];
    let p = rel(q);
    var vw = kin[i].xy;
    let reach = c.wells_a.y;
    // the field (stars, remnants, dark matter) within reach, and the nearest gas
    var m_env = 0.0;
    var n_env = 0.0;
    var mv = vec2<f32>(0.0);
    var mv2 = 0.0;
    var gas_j = NONE;
    var gas_d = reach;
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
        if (box_distance(p, r) >= reach || sp + 2u > STACK) {
            continue;
        }
        let ch = child[r];
        stack[sp] = ch.x;
        stack[sp + 1u] = ch.y;
        sp += 2u;
    }

    let dt = c.dt;
    // Bondi accretion, Eddington-capped, and the AGN's heat
    if (c.wells_b.x > 0.5 && gas_j != NONE) {
        let g = gas[2u * gas_j];
        let mg = bitcast<f32>(body[gas_j].x);
        let rho = g.y / (2.0 * c.gas_b.w);
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
            let rho = m_env / (3.14159265 * reach * reach) / (2.0 * c.gas_b.w);
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
