// Gravity by a group walk of the tree: a workgroup is GROUP consecutive sorted particles (close together in
// space), and they walk the tree together. Each round pops up to GROUP nodes off a shared stack, one a thread: a
// node far enough from the whole group's bounding box (beyond its opening radius) goes onto the shared interaction
// list as a softened point mass plus quadrupole, a nearer one is opened (its children pushed), a particle goes on
// the list as itself. When the list fills, every thread sums it for its own particle. Node data is read once for
// the group instead of once a particle, which is what limits a per-particle walk (memory latency).
// Appends and pushes are placed by prefix sums, not atomics, so the order (and the float sums) are the same every
// run. Writes (ax, ay, phi_self, phi_central) per particle; phi_self counts each pair once per side.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read> child: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read> node: array<vec4<u32>>;   // NODE_WORDS / 4 = 4 vec4s a node
@group(0) @binding(5) var<storage, read_write> acc: array<vec4<f32>>;
@group(0) @binding(6) var<storage, read> todo_list: array<u32>;     // the particles to do (compact.wgsl)
@group(0) @binding(8) var<storage, read> todo_n: array<u32>;
@group(0) @binding(7) var<uniform> t: Tick;

const GROUP: u32 = 64u;
const LIST: u32 = 64u;
const STACK_CAP: u32 = 3072u;

var<workgroup> stack: array<u32, STACK_CAP>;
var<workgroup> sp: u32;
var<workgroup> count: u32;
var<workgroup> l_a: array<vec4<f32>, LIST>;   // (x, y relative to the group's first particle, pc; mass; sxx)
var<workgroup> l_b: array<vec2<f32>, LIST>;   // (sxy, syy)
var<workgroup> l_j: array<u32, LIST>;         // the particle's index, NONE for a node
var<workgroup> scan: array<u32, GROUP>;       // accepts in the low 16 bits, pushes in the high 16
var<workgroup> bmin: array<vec2<f32>, GROUP>;
var<workgroup> bmax: array<vec2<f32>, GROUP>;
var<workgroup> live: u32;

struct Sums {
    a: vec2<f32>,
    phi: f32,
}

// the list's first n entries acting on the particle at qr (relative position), skipping itself
fn sum_list(n: u32, qr: vec2<f32>, i: u32, s_in: Sums) -> Sums {
    var s = s_in;
    for (var k = 0u; k < n; k++) {
        if (l_j[k] == i) {
            continue;
        }
        let e = l_a[k];
        let qd = l_b[k];
        let d = e.xy - qr;
        let r2 = dot(d, d) + c.eps2;
        let ir = inverseSqrt(r2);
        let ir2 = ir * ir;
        let gm = c.g * e.z * ir;
        s.a += d * (gm * ir2);
        s.phi -= gm;
        if (l_j[k] != NONE) {
            continue;  // a particle: no quadrupole (every thread is at the same entry, so this branch is uniform)
        }
        // quadrupole: with A = d.S.d, T = tr S:
        // a += G/2 (-6 S d / R^5 + 15 A d / R^7 - 3 T d / R^5), phi -= G/2 (3A - T R^2) / R^5
        let sd = vec2<f32>(e.w * d.x + qd.x * d.y, qd.x * d.x + qd.y * d.y);
        let aa = dot(d, sd);
        let tr = e.w + qd.y;
        let ir5 = ir2 * ir2 * ir;
        s.a += (0.5 * c.g * ir5) * (-6.0 * sd + (15.0 * aa * ir2 - 3.0 * tr) * d);
        s.phi -= 0.5 * c.g * ir5 * (3.0 * aa - tr * r2);
    }
    return s;
}

// inclusive prefix sum of `scan` over the group (Hillis-Steele); every thread must call it
fn scan_group(li: u32) {
    for (var off = 1u; off < GROUP; off <<= 1u) {
        var t = 0u;
        if (li >= off) {
            t = scan[li - off];
        }
        workgroupBarrier();
        scan[li] += t;
        workgroupBarrier();
    }
}

@compute @workgroup_size(64)
fn main(@builtin(local_invocation_index) li: u32, @builtin(workgroup_id) wid: vec3<u32>) {
    // a slice of the list of particles whose step ends this sub-step, from t.start
    let group = wid.x + wid.y * (c.row / GROUP);
    let first = t.start + group * GROUP;
    let todo = todo_n[0];
    if (li == 0u) {
        live = select(0u, 1u, first < todo);
    }
    if (workgroupUniformLoad(&live) == 0u) {
        return;
    }
    let real = first + li < todo;
    var i = NONE;
    if (real) {
        i = todo_list[first + li];
    }
    // the group's particles' sorted indices run from gimin to gimax (the list keeps their order)
    let gimin = todo_list[first];
    let gimax = todo_list[min(first + GROUP, todo) - 1u];
    let qref = pos[gimin];
    var q = qref;
    if (real) {
        q = pos[i];
    }
    let qr = fx_delta2(q, qref) * c.unit_pc;

    // the group's bounding box
    bmin[li] = qr;
    bmax[li] = qr;
    workgroupBarrier();
    for (var s = GROUP / 2u; s > 0u; s >>= 1u) {
        if (li < s) {
            bmin[li] = min(bmin[li], bmin[li + s]);
            bmax[li] = max(bmax[li], bmax[li + s]);
        }
        workgroupBarrier();
    }
    let gmin = bmin[0];
    let gmax = bmax[0];
    if (li == 0u) {
        stack[0] = 0u;
        sp = select(0u, 1u, c.n > 1u);
        count = 0u;
    }

    var sums: Sums;
    sums.a = vec2<f32>(0.0);
    sums.phi = 0.0;
    loop {
        let s = workgroupUniformLoad(&sp);
        if (s == 0u) {
            break;
        }
        let take = min(s, GROUP);
        let base = s - take;
        var r = NONE;
        if (li < take) {
            r = stack[base + li];
        }
        // classify this thread's node
        var ea = vec4<f32>(0.0);
        var eb = vec2<f32>(0.0);
        var ej = NONE;
        var ch = vec2<u32>(0u);
        var accept = 0u;
        var open = 0u;
        if (r != NONE) {
            if ((r & LEAF) != 0u) {
                let j = r & ~LEAF;
                ea = vec4<f32>(fx_delta2(pos[j], qref) * c.unit_pc, bitcast<f32>(body[j].x), 0.0);
                ej = j;
                accept = 1u;
            } else {
                let extra = node[4u * r + 2u];  // (mass, opening radius^2, sxx, sxy)
                let tail = node[4u * r + 3u];   // (syy, first particle, count, -)
                let cr = fx_delta2(node[4u * r], qref) * c.unit_pc;
                let gap = max(max(gmin - cr, cr - gmax), vec2<f32>(0.0));
                let open2 = bitcast<f32>(extra.y);
                // radius 0: a node under the softening scale, far enough unless it may hold one of the group
                let holds = tail.y <= gimax && gimin < tail.y + tail.z;
                if (dot(gap, gap) > open2 && (open2 > 0.0 || !holds)) {
                    ea = vec4<f32>(cr, bitcast<f32>(extra.x), bitcast<f32>(extra.z));
                    eb = vec2<f32>(bitcast<f32>(extra.w), bitcast<f32>(tail.x));
                    accept = 1u;
                } else {
                    ch = child[r];
                    open = 1u;
                }
            }
        }
        scan[li] = accept | ((2u * open) << 16u);
        workgroupBarrier();
        scan_group(li);
        let incl = scan[li];
        let total = scan[GROUP - 1u];
        var pushes = total >> 16u;
        // no room on the stack (very rare): this round's near nodes act as single masses instead of opening
        let full = base + pushes > STACK_CAP;
        workgroupBarrier();
        if (full) {
            if (open == 1u) {
                let extra = node[4u * r + 2u];
                ea = vec4<f32>(fx_delta2(node[4u * r], qref) * c.unit_pc, bitcast<f32>(extra.x), bitcast<f32>(extra.z));
                eb = vec2<f32>(bitcast<f32>(extra.w), bitcast<f32>(node[4u * r + 3u].x));
                accept = 1u;
                open = 0u;
            }
            scan[li] = accept;
            workgroupBarrier();
            scan_group(li);
            pushes = 0u;
        }
        let incl2 = scan[li];
        let accepts = scan[GROUP - 1u] & 0xFFFFu;
        let acc_at = (incl2 & 0xFFFFu) - accept;
        let push_at = (incl >> 16u) - 2u * open;
        // make room on the list first if this round's accepts don't fit
        let n_list = workgroupUniformLoad(&count);
        var at = n_list;
        if (n_list + accepts > LIST) {
            sums = sum_list(n_list, qr, i, sums);
            at = 0u;
            workgroupBarrier();
        }
        if (accept == 1u) {
            l_a[at + acc_at] = ea;
            l_b[at + acc_at] = eb;
            l_j[at + acc_at] = ej;
        }
        if (open == 1u) {
            stack[base + push_at] = ch.x;
            stack[base + push_at + 1u] = ch.y;
        }
        workgroupBarrier();
        if (li == 0u) {
            count = at + accepts;
            sp = base + pushes;
        }
    }
    sums = sum_list(workgroupUniformLoad(&count), qr, i, sums);

    if (real) {
        // the central mass
        let dc = fx_delta2(c.center, q) * c.unit_pc;
        let s2c = dot(dc, dc) + c.eps2_c;
        let invc = inverseSqrt(s2c);
        acc[i] = vec4<f32>(sums.a + dc * (c.gm_c * invc * invc * invc), sums.phi, -c.gm_c * invc);
    }
}
