// With the particles' reorder (gather.wgsl): their gas records (2 vec4 each) and element mass fractions.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> perm: array<u32>;
@group(0) @binding(2) var<storage, read> gas_a: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read> chem_a: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read_write> gas_b: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> chem_b: array<vec4<f32>>;

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let j = perm[i];
    gas_b[2u * i] = gas_a[2u * j];
    gas_b[2u * i + 1u] = gas_a[2u * j + 1u];
    chem_b[i] = chem_a[j];
}
