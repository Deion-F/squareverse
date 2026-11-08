// Gas dynamics by SPH in 2D (Wendland C2 kernel, reach H, ~`gas_a.x` neighbours), for the particles whose step
// ends this sub-step (the force pass's list). Gas sorts into its own run of the particles and its own part of the
// tree (morton.wgsl), so the walks below only look there: `ctl[1] .. ctl[2]` is that run (`range_*`).
//
// `density`: the surface density Σ_i = Σ_j m_j W(r_ij, H_i), with H_i adapted towards sqrt(N m / (pi Σ)) (at most
// 25% a step; a second pass when it moved more than 5%).
// `force`: pressure and artificial viscosity (Monaghan 1997, signal speed form), the standard "density - energy"
// SPH equations with P = (gamma - 1) Σ u:
//   a_i  = -Σ_j m_j (P_i/Σ_i² ∇W(H_i) + P_j/Σ_j² ∇W(H_j) + Π_ij ∇W̄)
//   du_i = Σ_j m_j (P_i/Σ_i² v_ij·∇W(H_i) + ½ Π_ij v_ij·∇W̄)
// over neighbours within max(H_i, H_j) (nodes keep their largest H), so each pair is counted from both sides.
// Neighbours whose own step isn't ending use their last Σ and u. Writes (ax, ay, du/dt, signal speed) at 2i + 1.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> kin: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read_write> gas: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read> child: array<vec2<u32>>;
@group(0) @binding(6) var<storage, read> node: array<vec4<u32>>;
@group(0) @binding(7) var<storage, read> todo_list: array<u32>;
@group(0) @binding(8) var<storage, read_write> ctl: array<u32>;   // [0] listed, [1] .. [2] the gas run, [3] clock

const STACK: u32 = 96u;

fn rel(q: vec4<u32>) -> vec2<u32> {
    return vec2<u32>(q.x - c.origin_x, q.z - c.origin_y);
}

// distance from a point (hi words relative to the origin) to a node's box, pc
fn box_distance(p: vec2<u32>, r: u32) -> f32 {
    let b = node[NODE_VEC4 * r + 1u];   // (min x, min y, max x, max y)
    let dx = select(0u, b.x - p.x, p.x < b.x) + select(0u, p.x - b.z, p.x > b.z);
    let dy = select(0u, b.y - p.y, p.y < b.y) + select(0u, p.y - b.w, p.y > b.w);
    let d = vec2<f32>(f32(dx), f32(dy)) * c.unit_pc;
    return max(length(d) - 2.0 * c.unit_pc, 0.0);
}

// does the node hold any of the gas run?
fn holds_gas(r: u32, g0: u32, g1: u32) -> bool {
    let t = node[NODE_VEC4 * r + 3u];   // (syy, first, count, -)
    return t.y < g1 && t.y + t.z > g0;
}

@compute @workgroup_size(1)
fn range_reset() {
    ctl[1] = 0u;
    ctl[2] = 0u;
}

@compute @workgroup_size(256)
fn range_find(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n || kind_of(body[i]) != K_GAS) {
        return;
    }
    if (i == 0u || kind_of(body[i - 1u]) != K_GAS) {
        ctl[1] = i;
    }
    if (i + 1u == c.n || kind_of(body[i + 1u]) != K_GAS) {
        ctl[2] = i + 1u;
    }
}

// Σ at particle i with reach h
fn surface_density(i: u32, h: f32) -> f32 {
    let q = pos[i];
    let p = rel(q);
    let g0 = ctl[1];
    let g1 = ctl[2];
    var sigma = bitcast<f32>(body[i].x) * kernel_w(0.0, h);
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
            if (j == i || j < g0 || j >= g1) {
                continue;
            }
            let d = length(fx_delta2(pos[j], q) * c.unit_pc);
            sigma += bitcast<f32>(body[j].x) * kernel_w(d, h);
            continue;
        }
        if (!holds_gas(r, g0, g1) || box_distance(p, r) >= h || sp + 2u > STACK) {
            continue;
        }
        let ch = child[r];
        stack[sp] = ch.x;
        stack[sp + 1u] = ch.y;
        sp += 2u;
    }
    return sigma;
}

@compute @workgroup_size(256)
fn density(@builtin(global_invocation_id) gid: vec3<u32>) {
    let k = flat_index(gid, c.row);
    if (k >= ctl[0]) {
        return;
    }
    let i = todo_list[k];
    if (kind_of(body[i]) != K_GAS) {
        return;
    }
    let g = gas[2u * i];
    let m = bitcast<f32>(body[i].x);
    var h = max(g.z, c.gas_c.w);
    var sigma = surface_density(i, h);
    // at least half the gravity softening (finer isn't resolved, and dense clumps' reach shrinking to ~1 pc let the
    // Courant step fall under the shortest one: cooling gas blew the disc apart, 2026-11-08), at most 3 kpc (a lone
    // particle's reach would otherwise grow without end)
    let want = clamp(clamp(sqrt(c.gas_a.x * m / (3.14159265 * max(sigma, 1e-12))), 0.8 * h, 1.25 * h), c.gas_c.w, 3000.0);
    if (abs(want / h - 1.0) > 0.05) {
        h = want;
        sigma = surface_density(i, h);
    }
    gas[2u * i] = vec4<f32>(g.x, sigma, h, g.w);
}

@compute @workgroup_size(256)
fn force(@builtin(global_invocation_id) gid: vec3<u32>) {
    let k = flat_index(gid, c.row);
    if (k >= ctl[0]) {
        return;
    }
    let i = todo_list[k];
    if (kind_of(body[i]) != K_GAS) {
        return;
    }
    let gm1 = c.gas_a.w - 1.0;
    let gi = gas[2u * i];
    let hi = max(gi.z, 1.0);
    let fi = gm1 * gi.x / max(gi.y, 1e-12);   // P / Σ²
    let ci = sqrt(c.gas_a.w * gm1 * max(gi.x, 0.0));
    let vi = kin[i].xy;
    let q = pos[i];
    let p = rel(q);
    let g0 = ctl[1];
    let g1 = ctl[2];
    var a = vec2<f32>(0.0);
    var du = 0.0;
    var vsig = ci;
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
            if (j == i || j < g0 || j >= g1) {
                continue;
            }
            let gj = gas[2u * j];
            let hj = max(gj.z, 1.0);
            let d = fx_delta2(q, pos[j]) * c.unit_pc;   // x_i - x_j
            let dist = length(d);
            if (dist >= max(hi, hj) || dist <= 0.0) {
                continue;
            }
            let rhat = d / dist;
            let mj = bitcast<f32>(body[j].x);
            let fj = gm1 * gj.x / max(gj.y, 1e-12);
            let cj = sqrt(c.gas_a.w * gm1 * max(gj.x, 0.0));
            let w = dot(vi - kin[j].xy, rhat);
            let dwi = kernel_dw(dist, hi);
            let dwj = kernel_dw(dist, hj);
            let dwm = 0.5 * (dwi + dwj);
            var visc = 0.0;
            if (w < 0.0) {
                let vs = ci + cj - 3.0 * w;
                visc = -c.gas_a.y * vs * w / (0.5 * (gi.y + gj.y));
                vsig = max(vsig, vs);
            } else {
                vsig = max(vsig, ci + cj);
            }
            a -= mj * (fi * dwi + fj * dwj + visc * dwm) * rhat;
            du += mj * (fi * dwi + 0.5 * visc * dwm) * w;
            continue;
        }
        if (!holds_gas(r, g0, g1) || sp + 2u > STACK) {
            continue;
        }
        let reach = max(hi, bitcast<f32>(node[NODE_VEC4 * r + 4u].x));   // the node's largest H
        if (box_distance(p, r) >= reach) {
            continue;
        }
        let ch = child[r];
        stack[sp] = ch.x;
        stack[sp + 1u] = ch.y;
        sp += 2u;
    }
    gas[2u * i + 1u] = vec4<f32>(a, du, vsig);
}
