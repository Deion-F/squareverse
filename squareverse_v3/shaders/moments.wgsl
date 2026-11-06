// Each internal node's mass, centre of mass (fixed point), bounding box and opening radius, from the leaves up:
// a thread starts at each leaf and climbs; at each node the first of its two children to arrive stops, the second
// combines both and goes on. Who arrives second varies, but what it computes doesn't, so the result is the same
// every run. Node records are written and read with atomics so the climbing threads see each other's results.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read> child: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read> parents: array<u32>;
@group(0) @binding(5) var<storage, read_write> counter: array<atomic<u32>>;
@group(0) @binding(6) var<storage, read_write> node: array<atomic<u32>>;

struct Body {
    com: vec4<u32>,
    m: f32,
    s: vec3<f32>,   // second moments about the centre of mass: xx, xy, yy
    first: u32,     // its particles: the first one's index and how many
    count: u32,
    bmin: vec2<u32>,
    bmax: vec2<u32>,
}

fn rel(q: vec4<u32>) -> vec2<u32> {
    return vec2<u32>(q.x - c.origin_x, q.z - c.origin_y);
}

fn load(r: u32) -> Body {
    var b: Body;
    if ((r & LEAF) != 0u) {
        let j = r & ~LEAF;
        b.com = pos[j];
        b.m = bitcast<f32>(body[j].x);
        b.bmin = rel(b.com);
        b.bmax = b.bmin;
        b.s = vec3<f32>(0.0);
        b.first = j;
        b.count = 1u;
        return b;
    }
    let o = NODE_WORDS * r;
    b.com = vec4<u32>(atomicLoad(&node[o]), atomicLoad(&node[o + 1u]), atomicLoad(&node[o + 2u]), atomicLoad(&node[o + 3u]));
    b.bmin = vec2<u32>(atomicLoad(&node[o + 4u]), atomicLoad(&node[o + 5u]));
    b.bmax = vec2<u32>(atomicLoad(&node[o + 6u]), atomicLoad(&node[o + 7u]));
    b.m = bitcast<f32>(atomicLoad(&node[o + 8u]));
    b.s = vec3<f32>(bitcast<f32>(atomicLoad(&node[o + 10u])), bitcast<f32>(atomicLoad(&node[o + 11u])),
                    bitcast<f32>(atomicLoad(&node[o + 12u])));
    b.first = atomicLoad(&node[o + 13u]);
    b.count = atomicLoad(&node[o + 14u]);
    return b;
}

// a child's second moments moved to the parent's centre of mass (parallel axis)
fn shifted(b: Body, com: vec4<u32>) -> vec3<f32> {
    let d = fx_delta2(b.com, com) * c.unit_pc;
    return b.s + b.m * vec3<f32>(d.x * d.x, d.x * d.y, d.y * d.y);
}

// before a refit (moments again over the same tree, without Karras, which otherwise zeroes the counters)
@compute @workgroup_size(256)
fn reset(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i + 1u < c.n) {
        atomicStore(&counter[i], 0u);
    }
}

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n || c.n < 2u) {
        return;
    }
    var k = parents[c.n + i];
    loop {
        if (k == NONE) {
            break;
        }
        if (atomicAdd(&counter[k], 1u) == 0u) {
            break;  // the other child isn't done yet; its thread carries on from here
        }
        let ch = child[k];
        let a = load(ch.x);
        let b = load(ch.y);
        let m = a.m + b.m;
        var w = 0.5;
        if (m > 0.0) {
            w = b.m / m;
        }
        let com = fx_add2(a.com, fx_delta2(b.com, a.com) * w);
        let sm = shifted(a, com) + shifted(b, com);
        let bmin = min(a.bmin, b.bmin);
        let bmax = max(a.bmax, b.bmax);
        // opening radius: size / theta + how far the centre of mass is from the box's centre (Salmon & Warren)
        let ext = bmax - bmin;
        let size = f32(max(ext.x, ext.y)) + 1.0;
        let cr = rel(com);
        let off = vec2<f32>(f32(cr.x - bmin.x), f32(cr.y - bmin.y)) - 0.5 * vec2<f32>(ext);
        let open = (size / c.theta + length(off)) * c.unit_pc;
        let o = NODE_WORDS * k;
        atomicStore(&node[o], com.x);
        atomicStore(&node[o + 1u], com.y);
        atomicStore(&node[o + 2u], com.z);
        atomicStore(&node[o + 3u], com.w);
        atomicStore(&node[o + 4u], bmin.x);
        atomicStore(&node[o + 5u], bmin.y);
        atomicStore(&node[o + 6u], bmax.x);
        atomicStore(&node[o + 7u], bmax.y);
        atomicStore(&node[o + 8u], bitcast<u32>(m));
        atomicStore(&node[o + 9u], bitcast<u32>(open * open));
        atomicStore(&node[o + 10u], bitcast<u32>(sm.x));
        atomicStore(&node[o + 11u], bitcast<u32>(sm.y));
        atomicStore(&node[o + 12u], bitcast<u32>(sm.z));
        atomicStore(&node[o + 13u], min(a.first, b.first));
        atomicStore(&node[o + 14u], a.count + b.count);
        k = parents[k];
    }
}
