// The super wells, listed in sorted order each step (so wells can be born, by direct collapse, and merge): `flag`
// marks them, the flags are prefix-summed (src/sort.rs Scan), `scatter` writes each well's index at its place, at
// most MAX_WELLS, and the count at [0].

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(2) var<storage, read_write> flags: array<u32>;
@group(0) @binding(3) var<storage, read_write> wsink: array<atomic<u32>>;

const MAX_WELLS: u32 = 256u;

@compute @workgroup_size(256)
fn flag(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    flags[i] = select(0u, 1u, kind_of(body[i]) == K_WELL);
}

@compute @workgroup_size(256)
fn scatter(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let well = kind_of(body[i]) == K_WELL;
    if (well && flags[i] < MAX_WELLS) {
        atomicStore(&wsink[1u + flags[i]], i);
    }
    if (i == c.n - 1u) {
        atomicStore(&wsink[0], flags[i] + select(0u, 1u, well));
    }
}
