// With the particles' reorder (gather.wgsl): their last accelerations, time-step bins and `about` records, which particles between
// steps still need.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> perm: array<u32>;
@group(0) @binding(2) var<storage, read> acc_a: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read> bins_a: array<vec4<u32>>;
@group(0) @binding(4) var<storage, read_write> acc_b: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> bins_b: array<vec4<u32>>;
@group(0) @binding(6) var<storage, read> about_a: array<vec4<f32>>;
@group(0) @binding(7) var<storage, read_write> about_b: array<vec4<f32>>;

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let j = perm[i];
    acc_b[i] = acc_a[j];
    bins_b[i] = bins_a[j];
    about_b[i] = about_a[j];
}
