// The particles whose step ends this sub-step, as a list (in key order, so neighbours stay together): `flag`
// marks them, the flags are prefix-summed in place (src/sort.rs Scan), `scatter` writes each one's index at its
// place and the last thread the count. The force pass then runs over the list, so its threads are all busy and the
// idle ones fall in whole workgroups at the end.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> bins: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> flags: array<u32>;
@group(0) @binding(3) var<storage, read_write> todo_list: array<u32>;
@group(0) @binding(4) var<storage, read_write> todo_n: array<u32>;
@group(0) @binding(5) var<uniform> t: Tick;
@group(0) @binding(6) var<storage, read> body: array<vec2<u32>>;

// whose step ends now (swallowed, merged and spare particles, K_GONE, need no forces)
fn listed(i: u32) -> bool {
    return bin_ends(c.levels, bins[i].x, t.s) && kind_of(body[i]) != K_GONE;
}

@compute @workgroup_size(256)
fn flag(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    flags[i] = select(0u, 1u, listed(i));
}

@compute @workgroup_size(256)
fn scatter(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let ends = listed(i);
    if (ends) {
        todo_list[flags[i]] = i;
    }
    if (i == c.n - 1u) {
        todo_n[0] = flags[i] + select(0u, 1u, ends);
    }
}
