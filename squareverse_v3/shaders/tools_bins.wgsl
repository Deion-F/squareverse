// records as tools_spawn.wgsl: the new particles start in the shortest step
@group(0) @binding(1) var<uniform> e: Edit;
@group(0) @binding(2) var<storage, read> rec: array<u32>;
@group(0) @binding(3) var<storage, read_write> bins: array<vec4<u32>>;
@group(0) @binding(4) var<storage, read_write> counts: array<atomic<u32>>;

@compute @workgroup_size(256)
fn spawn_b(@builtin(global_invocation_id) gid: vec3<u32>) {
    let k = flat_index(gid, c.row);
    if (k >= e.count) {
        return;
    }
    let s = rec[k * 23u];
    let old = bins[s].x;
    let nb = c.levels - 1u;
    bins[s] = vec4<u32>(nb, 0u, 0u, 0u);
    if (old != nb) {
        atomicSub(&counts[old], 1u);
        atomicAdd(&counts[nb], 1u);
    }
}
