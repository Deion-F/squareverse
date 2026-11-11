// SPH density for gas particle i (hydro.wgsl `density`, and beside the gravity walk in force_particle.wgsl): the
// surface density Σ_i = Σ_j m_j W(r_ij, H_i), with H_i adapted towards sqrt(N m / (pi Σ)) (at most 25% a step; a
// second walk when it moved more than 5%). Needs `c`, `pos`, `body`, `child`, `node`, `gas` (read-write) and `ctl`
// ([1] .. [2] the gas run) in the module that includes it. Walks only the gas's part of the tree.

const DENSITY_STACK: u32 = 96u;

// does the node hold any of the gas run?
fn holds_gas(r: u32, g0: u32, g1: u32) -> bool {
    let t = node[NODE_VEC4 * r + 4u];   // (first, count, largest H, -)
    return t.x < g1 && t.x + t.y > g0;
}

// Σ at particle i with reach h
fn surface_density(i: u32, h: f32) -> f32 {
    let q = pos[i];
    let p = vec2<u32>(q.x - c.origin_x, q.z - c.origin_y);
    let g0 = ctl[1];
    let g1 = ctl[2];
    var sigma = bitcast<f32>(body[i].x) * kernel_w(0.0, h);
    var stack: array<u32, DENSITY_STACK>;
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
        if (!holds_gas(r, g0, g1) || box_distance_to(p, node[NODE_VEC4 * r + 3u]) >= h || sp + 2u > DENSITY_STACK) {
            continue;
        }
        let ch = child[r];
        stack[sp] = ch.x;
        stack[sp + 1u] = ch.y;
        sp += 2u;
    }
    return sigma;
}

// Σ and H for gas particle i, into gas[2i]
fn gas_density(i: u32) {
    let g = gas[2u * i];
    let m = bitcast<f32>(body[i].x);
    var h = clamp(g.z, c.gas_c.w * sqrt(c.cosmo.z), c.gas_f.x);
    var sigma = surface_density(i, h);
    // at least half the gravity softening (finer isn't resolved, and dense clumps' reach shrinking to ~1 pc let the
    // Courant step fall under the shortest one: cooling gas blew the disc apart, 2026-11-08), at most 3 kpc (a lone
    // particle's reach would otherwise grow without end)
    let want = clamp(clamp(sqrt(c.gas_a.x * m / (3.14159265 * max(sigma, 1e-12))), 0.8 * h, 1.25 * h), c.gas_c.w * sqrt(c.cosmo.z), c.gas_f.x);
    if (abs(want / h - 1.0) > 0.05) {
        h = want;
        sigma = surface_density(i, h);
    }
    gas[2u * i] = vec4<f32>(g.x, sigma, h, g.w);
}
