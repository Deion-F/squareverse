// resolution.wgsl: splitting, positions and the particles' records.

@group(0) @binding(1) var<storage, read_write> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read_write> body: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read_write> about: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read> lists: array<u32>;
@group(0) @binding(6) var<storage, read> res_n: array<u32>;
@group(0) @binding(7) var<storage, read> gas: array<vec4<f32>>;

@compute @workgroup_size(256)
fn split_a(@builtin(global_invocation_id) gid: vec3<u32>) {
    let k = flat_index(gid, c.row);
    if (k >= min(res_n[0], res_n[1])) {
        return;
    }
    let p = lists[c.n + k];
    let s = lists[k];
    let b = body[p];
    let m = 0.5 * bitcast<f32>(b.x);
    let ang = 6.2831853 * hash01((b.y & ID_MASK) ^ 0x51u);
    let off = vec2<f32>(cos(ang), sin(ang)) * (0.25 * gas[2u * p].z) * c.inv_unit_pc;
    let q = pos[p];
    pos[p] = fx_add2(q, off);
    pos[s] = fx_add2(q, -off);
    kin[s] = kin[p];
    body[p] = vec2<u32>(bitcast<u32>(m), b.y);
    body[s] = vec2<u32>(bitcast<u32>(m), (K_GAS << KIND_SHIFT) | (body[s].y & ID_MASK));
    about[p] = vec4<f32>(about[p].xy, m, about[p].w);
    about[s] = about[p];
}
