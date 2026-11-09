// resolution.wgsl: the lists of free slots and of gas to split.

@group(0) @binding(1) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(2) var<storage, read_write> flags: array<u32>;
@group(0) @binding(3) var<storage, read_write> lists: array<u32>;   // free slots (n), then gas to split (n)
@group(0) @binding(4) var<storage, read_write> res_n: array<u32>;   // how many of each
@group(0) @binding(5) var<storage, read> gas: array<vec4<f32>>;

fn is_free(i: u32) -> bool {
    return kind_of(body[i]) == K_GONE;
}

fn too_heavy(i: u32) -> bool {
    return kind_of(body[i]) == K_GAS && c.gas_f.z > 0.0 && bitcast<f32>(body[i].x) > c.gas_f.z * c.gas_f.w;
}

@compute @workgroup_size(256)
fn flag_free(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i < c.n) {
        flags[i] = select(0u, 1u, is_free(i));
    }
}

@compute @workgroup_size(256)
fn scatter_free(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let f = is_free(i);
    if (f) {
        lists[flags[i]] = i;
    }
    if (i == c.n - 1u) {
        res_n[0] = flags[i] + select(0u, 1u, f);
    }
}

@compute @workgroup_size(256)
fn flag_split(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i < c.n) {
        flags[i] = select(0u, 1u, too_heavy(i));
    }
}

@compute @workgroup_size(256)
fn scatter_split(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let f = too_heavy(i);
    if (f) {
        lists[c.n + flags[i]] = i;
    }
    if (i == c.n - 1u) {
        res_n[1] = flags[i] + select(0u, 1u, f);
    }
}
