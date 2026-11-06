// Kick-drift-kick leapfrog, split around the force pass: `kick_drift` (half kick with last step's
// acceleration, then drift), the tree is rebuilt and forces found, then `kick` (the second half kick).

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read_write> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read> acc: array<vec4<f32>>;   // (ax, ay, phi_self, phi_central)

@compute @workgroup_size(256)
fn kick_drift(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let k = kin[i];
    let v = k.xy + acc[i].xy * (0.5 * c.dt);
    kin[i] = vec4<f32>(v, k.zw);
    pos[i] = fx_add2(pos[i], v * (c.dt * c.inv_unit_pc));
}

@compute @workgroup_size(256)
fn kick(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let k = kin[i];
    kin[i] = vec4<f32>(k.xy + acc[i].xy * (0.5 * c.dt), k.zw);
}
