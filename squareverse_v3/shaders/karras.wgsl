// The binary radix tree over the sorted keys (Karras 2012, "Maximizing parallelism in the construction of BVHs,
// octrees and k-d trees"): n - 1 internal nodes, node 0 the root, each built independently. Equal keys are told
// apart by index, so every key set gives a valid tree.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> keys: array<vec2<u32>>;
@group(0) @binding(2) var<storage, read_write> child: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read_write> parents: array<u32>;
@group(0) @binding(4) var<storage, read_write> counter: array<u32>;

// length of the common prefix of keys i and j (64-bit keys, then the index), -1 outside the array
fn delta(i: i32, j: i32) -> i32 {
    if (j < 0 || j >= i32(c.n)) {
        return -1;
    }
    let a = keys[i];
    let b = keys[j];
    let xh = a.y ^ b.y;
    if (xh != 0u) {
        return i32(countLeadingZeros(xh));
    }
    let xl = a.x ^ b.x;
    if (xl != 0u) {
        return 32 + i32(countLeadingZeros(xl));
    }
    return 64 + i32(countLeadingZeros(u32(i) ^ u32(j)));
}

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let iu = flat_index(gid, c.row);
    if (iu + 1u >= c.n) {
        return;
    }
    let i = i32(iu);
    // direction of the node's range
    var d = 1;
    if (delta(i, i + 1) < delta(i, i - 1)) {
        d = -1;
    }
    // upper bound on its length, then the exact other end
    let dmin = delta(i, i - d);
    var lmax = 2;
    while (delta(i, i + lmax * d) > dmin) {
        lmax *= 2;
    }
    var len = 0;
    for (var t = lmax / 2; t >= 1; t /= 2) {
        if (delta(i, i + (len + t) * d) > dmin) {
            len += t;
        }
    }
    let j = i + len * d;
    // where the range splits
    let dnode = delta(i, j);
    var s = 0;
    var t = len;
    loop {
        t = (t + 1) / 2;
        if (delta(i, i + (s + t) * d) > dnode) {
            s += t;
        }
        if (t <= 1) {
            break;
        }
    }
    let gamma = i + s * d + min(d, 0);
    let lo = min(i, j);
    let hi = max(i, j);
    var left = u32(gamma);
    var right = u32(gamma + 1);
    if (lo == gamma) {
        parents[c.n + left] = iu;
        left |= LEAF;
    } else {
        parents[left] = iu;
    }
    if (hi == gamma + 1) {
        parents[c.n + right] = iu;
        right |= LEAF;
    } else {
        parents[right] = iu;
    }
    child[iu] = vec2<u32>(left, right);
    counter[iu] = 0u;
    if (iu == 0u) {
        parents[0] = NONE;
    }
}
