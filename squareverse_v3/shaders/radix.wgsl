// Stable LSD radix sort of 48-bit keys (vec2: lo 32, hi 16) with u32 values, 8 bits a pass, 6 passes.
// Each pass: `local_sort` sorts each 256-element tile by the pass's digit (eight stable 1-bit splits in shared
// memory) and writes the tile's digit counts into `hist` (digit-major: hist[d * tiles + tile]); `hist` is then
// exclusive-scanned (scan.wgsl), which gives each (digit, tile) its first place in the output; `scatter` moves each
// element there. Everything is ordered by index, so the result is the same on every run.

struct Pass {
    n: u32,
    tiles: u32,
    row_groups: u32,   // workgroups per dispatch row
    index: u32,      // which pass: digit bits 8 x index
}

@group(0) @binding(0) var<uniform> p: Pass;
@group(0) @binding(1) var<storage, read> keys_in: array<vec2<u32>>;
@group(0) @binding(2) var<storage, read> vals_in: array<u32>;
@group(0) @binding(3) var<storage, read_write> keys_out: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read_write> vals_out: array<u32>;
@group(0) @binding(5) var<storage, read_write> hist: array<u32>;

const PAD: u32 = 0xFFFFFFFFu;

var<workgroup> sk: array<vec2<u32>, 256>;
var<workgroup> sv: array<u32, 256>;
var<workgroup> scan: array<u32, 256>;
var<workgroup> counts: array<atomic<u32>, 256>;
var<workgroup> sd: array<u32, 256>;
var<workgroup> start: array<u32, 256>;

fn digit(k: vec2<u32>) -> u32 {
    if (p.index < 4u) {
        return (k.x >> (8u * p.index)) & 255u;
    }
    return (k.y >> (8u * (p.index - 4u))) & 255u;
}

// keys_in / vals_in -> keys_out / vals_out (the tile sorted in place), counts -> hist
@compute @workgroup_size(256)
fn local_sort(@builtin(local_invocation_index) li: u32, @builtin(workgroup_id) wid: vec3<u32>) {
    let tile = wid.x + wid.y * p.row_groups;
    let i = tile * 256u + li;
    let real = i < p.n;
    atomicStore(&counts[li], 0u);
    var k = vec2<u32>(PAD, PAD);  // padding sorts last (digit 255, after the real 255s: the split is stable)
    var v = PAD;
    if (real) {
        k = keys_in[i];
        v = vals_in[i];
    }
    workgroupBarrier();
    if (real) {
        atomicAdd(&counts[digit(k)], 1u);
    }
    for (var b = 0u; b < 8u; b++) {
        let f = (digit(k) >> b) & 1u;
        scan[li] = 1u - f;
        workgroupBarrier();
        for (var off = 1u; off < 256u; off <<= 1u) {
            var t = 0u;
            if (li >= off) {
                t = scan[li - off];
            }
            workgroupBarrier();
            scan[li] += t;
            workgroupBarrier();
        }
        let zeros_before = scan[li] - (1u - f);
        let zeros = scan[255];
        var dst = zeros_before;
        if (f == 1u) {
            dst = zeros + li - zeros_before;
        }
        sk[dst] = k;
        sv[dst] = v;
        workgroupBarrier();
        k = sk[li];
        v = sv[li];
        workgroupBarrier();
    }
    if (real) {
        keys_out[i] = k;
        vals_out[i] = v;
    }
    if (tile < p.tiles) {
        hist[li * p.tiles + tile] = atomicLoad(&counts[li]);
    }
}

// keys_in / vals_in: the tile-sorted elements; hist: scanned. -> keys_out / vals_out, in order.
@compute @workgroup_size(256)
fn scatter(@builtin(local_invocation_index) li: u32, @builtin(workgroup_id) wid: vec3<u32>) {
    let tile = wid.x + wid.y * p.row_groups;
    let i = tile * 256u + li;
    let real = i < p.n;
    var k = vec2<u32>(PAD, PAD);
    var v = PAD;
    if (real) {
        k = keys_in[i];
        v = vals_in[i];
    }
    let d = digit(k);
    sd[li] = d;
    workgroupBarrier();
    if (li == 0u || sd[li - 1u] != d) {
        start[d] = li;
    }
    workgroupBarrier();
    if (real) {
        let dst = hist[d * p.tiles + tile] + li - start[d];
        keys_out[dst] = k;
        vals_out[dst] = v;
    }
}
