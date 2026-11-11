// Gravity, one particle a thread (`Walk::Particle`; the group walk is force.wgsl): walk the tree from the root; a
// node far enough away (beyond its opening radius) acts as a softened point mass at its centre of mass plus its
// quadrupole, a nearer one is opened; particles act one by one. Plus the central point mass. Only for the particles
// whose time step ends this sub-step. A pair is softened by the larger of the two kinds' softenings (a node: its
// largest). Faster than the group walk on the GPUs measured (2026-11-06). Writes (ax, ay, phi_self, phi_central)
// per particle; phi_self counts each pair once per side, so the self-gravity energy is half its mass-weighted sum.
// With mesh gravity (pm.wgsl) the walk gives only the short-range part: each pull times common.wgsl short_range,
// and nodes beyond short_cut() left out.
//
// Each workgroup has SLOTS threads for gravity and SLOTS more beside them for the gas's SPH density (density.wgsl)
// of the same stretch of the list: a short list's walks are all latency, and the two kinds overlap instead of
// following one another (hydro.wgsl then only adds the pressure forces). Nothing in one reads what the other writes.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read> child: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read> node: array<vec4<u32>>;   // NODE_VEC4 vec4s a node
@group(0) @binding(5) var<storage, read_write> acc: array<vec4<f32>>;
@group(0) @binding(6) var<storage, read> todo_list: array<u32>;     // the particles to do (compact.wgsl)
@group(0) @binding(8) var<storage, read> ctl: array<u32>;         // [0] the list's length, [1] .. [2] the gas run
@group(0) @binding(7) var<uniform> t: Tick;
@group(0) @binding(9) var<storage, read_write> gas: array<vec4<f32>>;   // (u, Σ, H, -) at 2i (density.wgsl)

// gravity slots a workgroup (src/sim/mod.rs `Walk::workgroup`)
const SLOTS: u32 = 128u;

const STACK: u32 = 96u;
// A short list leaves most of the GPU idle while each walk takes its time: then SPLIT threads share a particle's
// walk (the largest power of two up to SPLIT_MAX with list x SPLIT within SPLIT_SLOTS threads). Every thread
// follows the chain of nodes that hold the particle down from the root; what hangs off the chain at level l (the
// other child, or the chain's last node if the walk doesn't open it) is walked by thread l mod SPLIT. The threads'
// sums meet in `part`, and the first adds them in order. The same nodes and particles act as in one walk; only
// the order of the sums differs. A slice of the pass then covers slots, SPLIT a particle.
const SPLIT_MAX: u32 = 16u;
const SPLIT_SLOTS: u32 = 32768u;
var<workgroup> part: array<vec4<f32>, SLOTS>;

fn split() -> u32 {
    var s = SPLIT_MAX;
    while (s > 1u && ctl[0] * s > min(c.n, SPLIT_SLOTS)) {
        s /= 2u;
    }
    return s;
}

// does the walk open node r (as `walk` decides)?
fn opens(r: u32, i: u32, q: vec4<u32>) -> bool {
    if (c.pm.x > 0.0 && box_distance_to(vec2<u32>(q.x - c.origin_x, q.z - c.origin_y), node[NODE_VEC4 * r + 3u]) > short_cut()) {
        return false;
    }
    let d = fx_delta2(node[NODE_VEC4 * r], q) * c.unit_pc;
    let open2 = bitcast<f32>(node[NODE_VEC4 * r + 1u].y);
    var far = dot(d, d) > open2;
    if (far && open2 <= 0.0) {
        let run = node[NODE_VEC4 * r + 4u];
        far = i - run.x >= run.y;
    }
    return !far;
}

// The pull of the tree on particle i (at q), (ax, ay, phi): all of it (threads 1), or this thread's share. A
// function of its own: an entry point's local arrays are set up (zeroed) by every thread it runs, even those that
// return at once, and on a short list that was most of the pass (525k galaxy: 464 -> 419 GPU ms a step, 2026-11-11).
fn walk(i: u32, q: vec4<u32>, eps2_i: f32, threads: u32, mine: u32) -> vec3<f32> {
    let p = vec2<u32>(q.x - c.origin_x, q.z - c.origin_y);
    let cut = short_cut();
    let mesh = c.pm.x > 0.0;
    var a = vec2<f32>(0.0);
    var phi = 0.0;
    var stack: array<u32, STACK>;
    var sp = 0u;
    if (threads == 1u) {
        stack[0] = 0u;
        sp = 1u;
    } else {
        // down the chain of nodes that hold the particle, taking what hangs off it at this thread's levels
        var r = 0u;
        var level = 0u;
        loop {
            var hangs = r;
            var next = NONE;
            if (opens(r, i, q)) {
                let ch = node[NODE_VEC4 * r + 1u].zw;
                var first: bool;   // is the particle under the first child?
                if ((ch.x & LEAF) != 0u) {
                    first = (ch.x & ~LEAF) == i;
                } else {
                    let run = node[NODE_VEC4 * ch.x + 4u];
                    first = i - run.x < run.y;
                }
                hangs = select(ch.x, ch.y, first);
                let holder = select(ch.y, ch.x, first);
                if ((holder & LEAF) == 0u) {
                    next = holder;
                }
            }
            if (level % threads == mine) {
                stack[sp] = hangs;
                sp += 1u;
            }
            if (next == NONE) {
                break;
            }
            r = next;
            level += 1u;
        }
    }
    while (sp > 0u) {
        sp -= 1u;
        let r = stack[sp];
        var m: f32;
        var d: vec2<f32>;
        var eps2: f32;
        if ((r & LEAF) != 0u) {
            let j = r & ~LEAF;
            if (j == i) {
                continue;
            }
            let bj = body[j];
            m = bitcast<f32>(bj.x);
            eps2 = max(eps2_i, eps2_of(kind_of(bj)));
            d = fx_delta2(pos[j], q) * c.unit_pc;
            if (mesh && dot(d, d) > cut * cut) {
                continue;
            }
        } else {
            if (mesh && box_distance_to(p, node[NODE_VEC4 * r + 3u]) > cut) {
                continue;
            }
            let head = node[NODE_VEC4 * r + 1u];   // (mass, opening radius^2, the two children)
            d = fx_delta2(node[NODE_VEC4 * r], q) * c.unit_pc;
            let open2 = bitcast<f32>(head.y);
            var far = dot(d, d) > open2;
            if (far && open2 <= 0.0) {
                // radius 0: a node under the softening scale, far enough unless it holds this particle
                let run = node[NODE_VEC4 * r + 4u];   // (first particle, count, -, -)
                far = i - run.x >= run.y;
            }
            if (!far && sp + 2u <= STACK) {
                stack[sp] = head.z;
                stack[sp + 1u] = head.w;
                sp += 2u;
                continue;
            }
            let quad = node[NODE_VEC4 * r + 2u];   // (sxx, sxy, syy, largest softening^2)
            m = bitcast<f32>(head.x);
            eps2 = max(eps2_i, bitcast<f32>(quad.w));
            // the quadrupole (planar masses, 3D force law): with d from the particle to the centre of mass,
            // A = d.S.d, T = tr S: a += G/2 (-6 S d / R^5 + 15 A d / R^7 - 3 T d / R^5), phi -= G/2 (3A - T R^2) / R^5
            let sxx = bitcast<f32>(quad.x);
            let sxy = bitcast<f32>(quad.y);
            let syy = bitcast<f32>(quad.z);
            let r2 = dot(d, d) + eps2;
            let ir = inverseSqrt(r2);
            let ir2 = ir * ir;
            let ir5 = ir2 * ir2 * ir;
            let sd = vec2<f32>(sxx * d.x + sxy * d.y, sxy * d.x + syy * d.y);
            let aa = dot(d, sd);
            let tr = sxx + syy;
            var fq = vec2<f32>(1.0);
            if (mesh) {
                fq = short_range(sqrt(dot(d, d)));
            }
            a += (0.5 * c.g * ir5 * fq.x) * (-6.0 * sd + (15.0 * aa * ir2 - 3.0 * tr) * d);
            phi -= 0.5 * c.g * ir5 * (3.0 * aa - tr * r2) * fq.y;
        }
        let s2 = dot(d, d) + eps2;
        let inv = inverseSqrt(s2);
        let gm = c.g * m * inv;
        var f = vec2<f32>(1.0);
        if (mesh) {
            f = short_range(sqrt(dot(d, d)));
        }
        a += d * (gm * inv * inv * f.x);
        phi -= gm * f.y;
    }
    return vec3<f32>(a, phi);
}

@compute @workgroup_size(256)   // 2 x SLOTS
fn main(@builtin(workgroup_id) wid: vec3<u32>, @builtin(local_invocation_index) lid: u32) {
    // a slice of the list of particles whose step ends this sub-step, from t.start: SPLIT slots a particle (c.row
    // counts slots)
    let first = t.start + (wid.x + wid.y * (c.row / SLOTS)) * SLOTS;
    let gravity = lid < SLOTS;
    let slot = first + lid;
    let threads = split();
    let k = slot / threads;
    let mine = slot % threads;   // which of the particle's threads this is (they sit side by side in the workgroup)
    let valid = gravity && k < ctl[0];
    var i = 0u;
    var q = vec4<u32>(0u);
    var sum = vec3<f32>(0.0);
    if (valid) {
        i = todo_list[k];
        q = pos[i];
        let eps2_i = eps2_of(kind_of(body[i]));
        if (c.n > 1u) {
            sum = walk(i, q, eps2_i, threads, mine);
        }
        part[lid] = vec4<f32>(sum, 0.0);
    } else if (!gravity) {
        // the gas density of list entry first + lid - SLOTS
        let kg = slot - SLOTS;
        if (kg < ctl[0]) {
            let ig = todo_list[kg];
            if (kind_of(body[ig]) == K_GAS) {
                gas_density(ig);
            }
        }
    }
    workgroupBarrier();
    if (!valid || mine != 0u) {
        return;
    }
    if (threads > 1u) {
        sum = vec3<f32>(0.0);
        for (var s = 0u; s < threads; s++) {
            sum += part[lid + s].xyz;
        }
    }
    var a = sum.xy;
    let phi = sum.z;
    // the central mass
    let dc = fx_delta2(c.center, q) * c.unit_pc;
    let s2c = dot(dc, dc) + c.eps2_c;
    let invc = inverseSqrt(s2c);
    a += dc * (c.gm_c * invc * invc * invc);
    acc[i] = vec4<f32>(a, phi, -c.gm_c * invc);
}
