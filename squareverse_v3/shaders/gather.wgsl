// Reorders the particles into key order (from set A into set B), so the tree's leaf i is particle i and nearby
// particles sit next to each other in memory.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> perm: array<u32>;
@group(0) @binding(2) var<storage, read> pos_a: array<vec4<u32>>;
@group(0) @binding(3) var<storage, read> kin_a: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read> body_a: array<vec2<u32>>;
@group(0) @binding(5) var<storage, read_write> pos_b: array<vec4<u32>>;
@group(0) @binding(6) var<storage, read_write> kin_b: array<vec4<f32>>;
@group(0) @binding(7) var<storage, read_write> body_b: array<vec2<u32>>;

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let j = perm[i];
    pos_b[i] = pos_a[j];
    kin_b[i] = kin_a[j];
    body_b[i] = body_a[j];
}
