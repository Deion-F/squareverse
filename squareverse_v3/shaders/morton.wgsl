// The particles' bounding box (relative to the tree origin, hi words) and their 48-bit Morton keys over it:
// 24 bits a side, so a galaxy 30 kpc across is cut into cells ~2 mpc wide. Keys are (lo 32 bits, hi 16 bits);
// values are the particle's index before sorting.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> bbox: array<atomic<u32>, 4>;  // min x, min y, max x, max y
@group(0) @binding(3) var<storage, read_write> keys: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read_write> vals: array<u32>;

var<workgroup> wmin: array<vec2<u32>, 256>;
var<workgroup> wmax: array<vec2<u32>, 256>;

fn rel(q: vec4<u32>) -> vec2<u32> {
    return vec2<u32>(q.x - c.origin_x, q.z - c.origin_y);
}

@compute @workgroup_size(1)
fn bbox_reset() {
    atomicStore(&bbox[0], NONE);
    atomicStore(&bbox[1], NONE);
    atomicStore(&bbox[2], 0u);
    atomicStore(&bbox[3], 0u);
}

@compute @workgroup_size(256)
fn bbox_reduce(@builtin(global_invocation_id) gid: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    let i = flat_index(gid, c.row);
    var mn = vec2<u32>(NONE);
    var mx = vec2<u32>(0u);
    if (i < c.n) {
        let r = rel(pos[i]);
        mn = r;
        mx = r;
    }
    wmin[li] = mn;
    wmax[li] = mx;
    workgroupBarrier();
    for (var s = 128u; s > 0u; s >>= 1u) {
        if (li < s) {
            wmin[li] = min(wmin[li], wmin[li + s]);
            wmax[li] = max(wmax[li], wmax[li + s]);
        }
        workgroupBarrier();
    }
    if (li == 0u) {
        atomicMin(&bbox[0], wmin[0].x);
        atomicMin(&bbox[1], wmin[0].y);
        atomicMax(&bbox[2], wmax[0].x);
        atomicMax(&bbox[3], wmax[0].y);
    }
}

// 16 bits spread to the even bits of 32
fn spread(v: u32) -> u32 {
    var x = v & 0xFFFFu;
    x = (x | (x << 8u)) & 0x00FF00FFu;
    x = (x | (x << 4u)) & 0x0F0F0F0Fu;
    x = (x | (x << 2u)) & 0x33333333u;
    x = (x | (x << 1u)) & 0x55555555u;
    return x;
}

// One axis quantised to 24 bits over [lo, lo + 2^bits): hi-word offset, refined by the lo word when the box is small.
fn quantise(hi: u32, lo_word: u32, lo: u32, bits: u32) -> u32 {
    let d = hi - lo;
    if (bits >= 24u) {
        return d >> (bits - 24u);
    }
    let s = 24u - bits;
    return (d << s) | (lo_word >> (32u - s));
}

@compute @workgroup_size(256)
fn keys_main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let mn = vec2<u32>(atomicLoad(&bbox[0]), atomicLoad(&bbox[1]));
    let mx = vec2<u32>(atomicLoad(&bbox[2]), atomicLoad(&bbox[3]));
    let ext = max(mx.x - mn.x, mx.y - mn.y);
    let bits = 32u - countLeadingZeros(ext);  // ext < 2^bits
    let q = pos[i];
    let r = rel(q);
    let qx = quantise(r.x, q.y, mn.x, bits);
    let qy = quantise(r.y, q.w, mn.y, bits);
    let lo = spread(qx) | (spread(qy) << 1u);
    let hi = spread(qx >> 16u) | (spread(qy >> 16u) << 1u);
    keys[i] = vec2<u32>(lo, hi);
    vals[i] = i;
}
