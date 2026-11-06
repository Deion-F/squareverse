// Exclusive prefix sum of u32s in place, 1,024 a workgroup (256 threads x 4). Longer arrays go in levels:
// `scan_blocks` scans each block and writes its total to `sums`; the sums are scanned the same way (recursively);
// `add_blocks` adds each block's scanned total back.

struct Level {
    n: u32,
    row_groups: u32,
    _a: u32,
    _b: u32,
}

@group(0) @binding(0) var<uniform> l: Level;
@group(0) @binding(1) var<storage, read_write> data: array<u32>;
@group(0) @binding(2) var<storage, read_write> sums: array<u32>;

var<workgroup> s: array<u32, 256>;

@compute @workgroup_size(256)
fn scan_blocks(@builtin(local_invocation_index) li: u32, @builtin(workgroup_id) wid: vec3<u32>) {
    let blk = wid.x + wid.y * l.row_groups;
    let base = blk * 1024u + li * 4u;
    var v: array<u32, 4>;
    var t = 0u;
    for (var k = 0u; k < 4u; k++) {
        var x = 0u;
        if (base + k < l.n) {
            x = data[base + k];
        }
        v[k] = t;   // exclusive within the thread's four
        t += x;
    }
    s[li] = t;
    workgroupBarrier();
    for (var off = 1u; off < 256u; off <<= 1u) {
        var y = 0u;
        if (li >= off) {
            y = s[li - off];
        }
        workgroupBarrier();
        s[li] += y;
        workgroupBarrier();
    }
    let before = s[li] - t;
    for (var k = 0u; k < 4u; k++) {
        if (base + k < l.n) {
            data[base + k] = before + v[k];
        }
    }
    if (li == 255u) {
        sums[blk] = s[255];
    }
}

@compute @workgroup_size(256)
fn add_blocks(@builtin(local_invocation_index) li: u32, @builtin(workgroup_id) wid: vec3<u32>) {
    let blk = wid.x + wid.y * l.row_groups;
    let add = sums[blk];
    let base = blk * 1024u + li * 4u;
    for (var k = 0u; k < 4u; k++) {
        if (base + k < l.n) {
            data[base + k] += add;
        }
    }
}
