// resolution.wgsl: splitting, the gas records, elements and time steps.

@group(0) @binding(1) var<storage, read_write> gas: array<vec4<f32>>;
@group(0) @binding(2) var<storage, read_write> chem: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read_write> bins: array<vec4<u32>>;
@group(0) @binding(4) var<storage, read_write> acc: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> counts: array<atomic<u32>>;
@group(0) @binding(6) var<storage, read> lists: array<u32>;
@group(0) @binding(7) var<storage, read> res_n: array<u32>;

@compute @workgroup_size(256)
fn split_b(@builtin(global_invocation_id) gid: vec3<u32>) {
    let k = flat_index(gid, c.row);
    if (k >= min(res_n[0], res_n[1])) {
        return;
    }
    let p = lists[c.n + k];
    let s = lists[k];
    let g = gas[2u * p];
    let half = vec4<f32>(g.x, 0.5 * g.y, g.z * 0.70710678, g.w);
    gas[2u * p] = half;
    gas[2u * s] = half;
    gas[2u * s + 1u] = gas[2u * p + 1u];
    chem[s] = chem[p];
    acc[s] = acc[p];
    let old = bins[s].x;
    let nb = bins[p];
    bins[s] = nb;
    if (old != nb.x) {
        atomicSub(&counts[old], 1u);
        atomicAdd(&counts[nb.x], 1u);
    }
}
