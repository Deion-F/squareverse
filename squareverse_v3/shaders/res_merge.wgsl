// resolution.wgsl: merging.

@group(0) @binding(1) var<storage, read_write> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read_write> body: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read_write> gas: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> chem: array<vec4<f32>>;
@group(0) @binding(6) var<storage, read> ctl: array<u32>;   // [1] .. [2]: the gas's run (hydro.wgsl)

fn light(i: u32) -> bool {
    return kind_of(body[i]) == K_GAS && bitcast<f32>(body[i].x) < c.gas_f.y * c.gas_f.w && thin_hot(gas[2u * i]);
}

@compute @workgroup_size(256)
fn merge(@builtin(global_invocation_id) gid: vec3<u32>) {
    let g0 = ctl[1];
    let g1 = ctl[2];
    let i = g0 + 2u * flat_index(gid, c.row);
    let j = i + 1u;
    if (c.gas_f.y <= 0.0 || j >= g1 || !light(i) || !light(j)) {
        return;
    }
    let gi = gas[2u * i];
    let gj = gas[2u * j];
    let d = fx_delta2(pos[j], pos[i]) * c.unit_pc;
    if (length(d) >= max(gi.z, gj.z)) {
        return;
    }
    let mi = bitcast<f32>(body[i].x);
    let mj = bitcast<f32>(body[j].x);
    let m = mi + mj;
    let vi = kin[i];
    let vj = kin[j];
    let v = (mi * vi.xy + mj * vj.xy) / m;
    let dv = vi.xy - vj.xy;
    let u = (mi * gi.x + mj * gj.x + 0.5 * mi * mj / m * dot(dv, dv)) / m;
    pos[i] = fx_add2(pos[i], d * (mj / m) * c.inv_unit_pc);
    kin[i] = vec4<f32>(v, gas_temperature(u), vi.w);
    body[i] = vec2<u32>(bitcast<u32>(m), body[i].y);
    let z = (mi * gi.w + mj * gj.w) / m;
    gas[2u * i] = vec4<f32>(u, gi.y, max(gi.z, gj.z), z);
    chem[i] = (mi * chem[i] + mj * chem[j]) / m;
    body[j] = vec2<u32>(0u, (K_GONE << KIND_SHIFT) | (body[j].y & ID_MASK));
    kin[j] = vec4<f32>(0.0);
}
