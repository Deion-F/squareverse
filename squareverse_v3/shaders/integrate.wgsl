// Kick-drift-kick leapfrog with block time steps, split around the force pass. Each sub-step: `kick_drift` (the
// opening half kick for particles whose step begins now, then every particle drifts one sub-step), the tree is
// refitted or rebuilt and forces found for the particles whose step ends now, then `kick` (their closing half
// kick, and each picks its next bin). A particle's step is dt / 2^bin; it wants at most sqrt(2 eta eps / |a|)
// (GADGET's criterion), and at most eta_jerk |a| / |da/dt|, da/dt from the change in a over its last step: the
// galaxy's pull dominates |a|, so only the change sees a close encounter coming. It may move to a shorter step at the end of any step, to a longer one only where that
// step's boundaries line up with now. `counts` keeps how many particles each bin holds.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read_write> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read> acc: array<vec4<f32>>;   // (ax, ay, phi_self, phi_central)
@group(0) @binding(4) var<storage, read_write> bins: array<vec4<u32>>;   // (bin, ax, ay at the last step's end, -)
@group(0) @binding(5) var<storage, read_write> counts: array<atomic<u32>>;
@group(0) @binding(6) var<uniform> t: Tick;

fn bin_dt(b: u32) -> f32 {
    return c.dt / f32(1u << b);
}

// the lowest bin whose step is no longer than `want` Myr
fn bin_for(want: f32) -> u32 {
    let ratio = c.dt / want;
    if (!(ratio > 1.0)) {
        return 0u;
    }
    return u32(min(ceil(log2(ratio)), f32(c.levels - 1u)));
}

// the bin the acceleration asks for
fn wanted_bin(a: vec2<f32>) -> u32 {
    return bin_for(sqrt(c.eta_eps / max(length(a), 1e-30)));
}

@compute @workgroup_size(256)
fn kick_drift(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let k = kin[i];
    var v = k.xy;
    let b = bins[i].x;
    if (bin_starts(c.levels, b, t.s)) {
        v += acc[i].xy * (0.5 * bin_dt(b));
        kin[i] = vec4<f32>(v, k.zw);
    }
    pos[i] = fx_add2(pos[i], v * (c.dt_min * c.inv_unit_pc));
}

@compute @workgroup_size(256)
fn kick(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let st = bins[i];
    let b = st.x;
    if (!bin_ends(c.levels, b, t.s)) {
        return;
    }
    let a = acc[i].xy;
    let k = kin[i];
    kin[i] = vec4<f32>(k.xy + a * (0.5 * bin_dt(b)), k.zw);
    var want = wanted_bin(a);
    let da = length(a - bitcast<vec2<f32>>(st.yz));
    if (c.eta_jerk > 0.0 && da > 0.0) {
        want = max(want, bin_for(c.eta_jerk * bin_dt(b) * length(a) / da));
    }
    var nb = want;
    if (want < b) {
        // longer steps only as far as their boundaries line up with the end of this sub-step
        let te = t.s + 1u;
        nb = b;
        loop {
            if (nb <= want || (te & (bin_period(c.levels, nb - 1u) - 1u)) != 0u) {
                break;
            }
            nb -= 1u;
        }
    }
    bins[i] = vec4<u32>(nb, bitcast<vec2<u32>>(a), 0u);
    if (nb != b) {
        atomicSub(&counts[b], 1u);
        atomicAdd(&counts[nb], 1u);
    }
}

// the first bins, from the first forces (counts must start at zero)
@compute @workgroup_size(256)
fn init_bins(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let a = acc[i].xy;
    let b = wanted_bin(a);
    bins[i] = vec4<u32>(b, bitcast<vec2<u32>>(a), 0u);
    atomicAdd(&counts[b], 1u);
}
