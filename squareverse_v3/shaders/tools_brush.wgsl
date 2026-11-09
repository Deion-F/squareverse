@group(0) @binding(1) var<uniform> e: Edit;
@group(0) @binding(2) var<storage, read_write> pos: array<vec4<u32>>;
@group(0) @binding(3) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read_write> body: array<vec2<u32>>;

@compute @workgroup_size(256)
fn brush(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let b = body[i];
    let k = kind_of(b);
    if (e.mode == 3u) {
        if ((b.y & ID_MASK) == e.target_id && k != K_GONE) {
            body[i] = vec2<u32>(bitcast<u32>(e.value), b.y);
        }
        return;
    }
    if (k == K_GONE || (e.kinds & (1u << k)) == 0u || length(fx_delta2(pos[i], e.point) * e.unit_pc) > e.radius_pc) {
        return;
    }
    if (e.mode == 0u) {
        let v = kin[i];
        kin[i] = vec4<f32>(v.xy + e.dv, v.zw);
    } else if (e.mode == 1u) {
        body[i] = vec2<u32>(0u, (K_GONE << KIND_SHIFT) | (b.y & ID_MASK));
        kin[i] = vec4<f32>(0.0);
    } else {
        pos[i] = fx_add2(pos[i], e.dpos / e.unit_pc);
    }
}
