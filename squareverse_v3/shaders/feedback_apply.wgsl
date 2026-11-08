// Each gas particle takes in what feedback.wgsl gave it: mass (its velocity kept), energy as heat, and elements,
// mixed into its own. A particle heated this way moves at once to a step its new sound speed allows (it is the
// start of a step of dt, where every step ends, so it may).

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(2) var<storage, read_write> body: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read_write> gas: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read_write> chem: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> deposit: array<atomic<u32>>;
@group(0) @binding(6) var<storage, read_write> bins: array<vec4<u32>>;
@group(0) @binding(7) var<storage, read_write> counts: array<atomic<u32>>;

const TWO32: f32 = 4294967296.0;
const MASS_SCALE: f32 = 1048576.0;

fn take64(at: u32) -> f32 {
    let lo = atomicLoad(&deposit[at]);
    let hi = bitcast<i32>(atomicLoad(&deposit[at + 1u]));
    atomicStore(&deposit[at], 0u);
    atomicStore(&deposit[at + 1u], 0u);
    return f32(hi) * TWO32 + f32(lo);
}

@compute @workgroup_size(256)
fn apply(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let at = 12u * i;
    let dm = take64(at) / MASS_SCALE;
    let de = take64(at + 2u);
    let dz = vec4<f32>(take64(at + 4u), take64(at + 6u), take64(at + 8u), take64(at + 10u)) / MASS_SCALE;
    if ((dm <= 0.0 && de <= 0.0) || kind_of(body[i]) != K_GAS) {
        return;
    }
    let b = body[i];
    let m = bitcast<f32>(b.x);
    let m1 = m + dm;
    body[i] = vec2<u32>(bitcast<u32>(m1), b.y);
    chem[i] = (chem[i] * m + dz) / m1;
    let g = gas[2u * i];
    let u = min((g.x * m + de) / m1, max(u_ceiling(g.z), g.x));
    gas[2u * i] = vec4<f32>(u, g.yzw);
    let k = kin[i];
    kin[i] = vec4<f32>(k.xy, gas_temperature(u), k.w);
    // a step its sound speed allows (signal speed ~ 2 c_s)
    let cs = sqrt(c.gas_a.w * (c.gas_a.w - 1.0) * u);
    let want_dt = c.gas_a.z * g.z / max(2.0 * cs, 1e-3);
    let ratio = c.dt / want_dt;
    var want = 0u;
    if (ratio > 1.0) {
        want = u32(min(ceil(log2(ratio)), f32(c.levels - 1u)));
    }
    let st = bins[i];
    if (want > st.x) {
        bins[i] = vec4<u32>(want, st.yzw);
        atomicSub(&counts[st.x], 1u);
        atomicAdd(&counts[want], 1u);
    }
}
