// records: 23 words a new particle: its slot, pos (4), kin (4), body (2), about (4), gas (4), chem (4)
@group(0) @binding(1) var<uniform> e: Edit;
@group(0) @binding(2) var<storage, read> rec: array<u32>;
@group(0) @binding(3) var<storage, read_write> pos: array<vec4<u32>>;
@group(0) @binding(4) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> body: array<vec2<u32>>;
@group(0) @binding(6) var<storage, read_write> about: array<vec4<f32>>;
@group(0) @binding(7) var<storage, read_write> gas: array<vec4<f32>>;
@group(0) @binding(8) var<storage, read_write> chem: array<vec4<f32>>;
@group(0) @binding(9) var<storage, read_write> acc: array<vec4<f32>>;

const REC: u32 = 23u;

fn f(at: u32) -> f32 {
    return bitcast<f32>(rec[at]);
}

fn v4(at: u32) -> vec4<f32> {
    return vec4<f32>(f(at), f(at + 1u), f(at + 2u), f(at + 3u));
}

@compute @workgroup_size(256)
fn spawn_a(@builtin(global_invocation_id) gid: vec3<u32>) {
    let k = flat_index(gid, c.row);
    if (k >= e.count) {
        return;
    }
    let r = k * REC;
    let s = rec[r];
    let id = body[s].y & ID_MASK;   // the slot keeps its id
    pos[s] = vec4<u32>(rec[r + 1u], rec[r + 2u], rec[r + 3u], rec[r + 4u]);
    kin[s] = v4(r + 5u);
    body[s] = vec2<u32>(rec[r + 9u], (rec[r + 10u] & ~ID_MASK) | id);
    about[s] = v4(r + 11u);
    gas[2u * s] = v4(r + 15u);
    gas[2u * s + 1u] = vec4<f32>(0.0);
    chem[s] = v4(r + 19u);
    acc[s] = vec4<f32>(0.0);
}
