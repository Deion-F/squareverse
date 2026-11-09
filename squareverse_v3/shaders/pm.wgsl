// Long-range gravity on a mesh (TreePM, phase 5), over the whole periodic box, in comoving coordinates. The mesh
// has N x N cells (c.pm.x, a power of two up to 1024) over the box. Once a step of dt, at its end:
//
// 1. `clear`, `deposit`: each particle's mass goes to the 4 nearest cell centres (cloud in cell), as 64-bit
//    integers (two u32 words with carry; units of c.pm.w Msun), so the sum is the same in any order;
// 2. `to_field`: surface density Σ per cell, as complex numbers;
// 3. the 2D FFT: `fft_rows` then `fft_cols` (one workgroup a row or column, in workgroup memory);
// 4. `green`: the potential of the long-range part, φ_k = -2πG Σ_k / k · erfc(k r_s) (the 2D transform of
//    -G erf(r / 2 r_s) / r: gravity falls off as 1/r² in this 2D universe), the cloud-in-cell smoothing taken out
//    twice (deposit and read back); the force -ik φ_k packed as one complex field (gx + i gy), φ as another; k = 0
//    (the mean density) is left out, as in any periodic box;
// 5. the inverse FFT of both, then `interp`: each particle's long-range pull (and potential) from the 4 cells,
//    divided by a² (physical units; positions are comoving), into `pm_acc`;
// 6. `kick`: half a step of that pull (the long-range force is a kick-drift-kick on the longest step: half at the
//    end of each step, half at the start of the next, from the same forces).
//
// The tree does the short-range part, -G m erfc(r / 2 r_s) / r, and leaves out everything beyond r_cut
// (force_particle.wgsl). `cosmo_step` also lives here: the scale factor for the step about to run.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read_write> mesh: array<atomic<u32>>;   // 2 words a cell
@group(0) @binding(4) var<storage, read_write> field: array<vec2<f32>>;    // 2 fields of N² complex
@group(0) @binding(5) var<storage, read_write> pm_acc: array<vec4<f32>>;   // (gx, gy, φ, -) a particle
@group(0) @binding(6) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(7) var<storage, read> ctl: array<u32>;                  // [3]: steps of dt begun (the clock)
@group(0) @binding(8) var<storage, read_write> cosmo_out: array<f32>;      // (unit_pc, inv_unit_pc), cosmo vec4

const TWO32: f32 = 4294967296.0;
const MAXN: u32 = 1024u;
const PI: f32 = 3.14159265;

var<workgroup> buf: array<vec2<f32>, MAXN>;

fn cells() -> u32 {
    return u32(c.pm.x);
}

fn log2n() -> u32 {
    return 31u - countLeadingZeros(cells());
}

@compute @workgroup_size(256)
fn clear(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    let n = cells();
    if (i < 2u * n * n) {
        atomicStore(&mesh[i], 0u);
    }
}

fn add64(at: u32, x: f32) {
    let w = split64(x);
    let old = atomicAdd(&mesh[at], w.x);
    let carry = select(0u, 1u, old + w.x < old);
    atomicAdd(&mesh[at + 1u], w.y + carry);
}

// a position's lower cell (of the 4 round it) and where in it, 0..1, measured from cell centres
struct Cic {
    i0: vec2<u32>,
    t: vec2<f32>,
}

fn cic(q: vec4<u32>) -> Cic {
    let lg = log2n();
    let sh = 32u - lg;
    // half a cell back, so the cell index counts from the centres
    let x = q.x - (1u << (sh - 1u));
    let y = q.z - (1u << (sh - 1u));
    let mask = (1u << sh) - 1u;
    var r: Cic;
    r.i0 = vec2<u32>(x >> sh, y >> sh);
    r.t = vec2<f32>(f32(x & mask), f32(y & mask)) / f32(1u << sh);
    return r;
}

@compute @workgroup_size(256)
fn deposit(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let m = bitcast<f32>(body[i].x);
    if (m <= 0.0) {
        return;
    }
    let n = cells();
    let w = cic(pos[i]);
    let units = m / c.pm.w;
    let x1 = (w.i0.x + 1u) & (n - 1u);
    let y1 = (w.i0.y + 1u) & (n - 1u);
    add64(2u * (w.i0.y * n + w.i0.x), units * (1.0 - w.t.x) * (1.0 - w.t.y));
    add64(2u * (w.i0.y * n + x1), units * w.t.x * (1.0 - w.t.y));
    add64(2u * (y1 * n + w.i0.x), units * (1.0 - w.t.x) * w.t.y);
    add64(2u * (y1 * n + x1), units * w.t.x * w.t.y);
}

// comoving pc per cell
fn cell_pc() -> f32 {
    return c.cosmo_q.w * 4294967296.0 / c.pm.x;
}

@compute @workgroup_size(256)
fn to_field(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    let n = cells();
    if (i >= n * n) {
        return;
    }
    let lo = atomicLoad(&mesh[2u * i]);
    let hi = atomicLoad(&mesh[2u * i + 1u]);
    let d = cell_pc();
    let m = (f32(hi) * TWO32 + f32(lo)) * c.pm.w;
    field[i] = vec2<f32>(m / (d * d), 0.0);
}

fn bitrev(i: u32, bits: u32) -> u32 {
    return reverseBits(i) >> (32u - bits);
}

// the FFT of `buf` in place (after a bit-reversed load), sign -1 forward, +1 inverse
fn fft_buf(li: u32, sign: f32) {
    let n = cells();
    let lg = log2n();
    for (var s = 1u; s <= lg; s++) {
        let half = 1u << (s - 1u);
        for (var b = li; b < n / 2u; b += 256u) {
            let k = b & (half - 1u);
            let i = ((b >> (s - 1u)) << s) + k;
            let j = i + half;
            let ang = sign * PI * f32(k) / f32(half);
            let w = vec2<f32>(cos(ang), sin(ang));
            let v = buf[j];
            let t = vec2<f32>(w.x * v.x - w.y * v.y, w.x * v.y + w.y * v.x);
            let u = buf[i];
            buf[i] = u + t;
            buf[j] = u - t;
        }
        workgroupBarrier();
    }
}

// one row a workgroup (x: the row, y: which field); `inverse` also divides by N
fn rows(wg: vec3<u32>, li: u32, sign: f32, scale: f32) {
    let n = cells();
    let lg = log2n();
    let base = wg.y * n * n + wg.x * n;
    for (var i = li; i < n; i += 256u) {
        buf[bitrev(i, lg)] = field[base + i];
    }
    workgroupBarrier();
    fft_buf(li, sign);
    for (var i = li; i < n; i += 256u) {
        field[base + i] = buf[i] * scale;
    }
}

fn cols(wg: vec3<u32>, li: u32, sign: f32, scale: f32) {
    let n = cells();
    let lg = log2n();
    let base = wg.y * n * n + wg.x;
    for (var i = li; i < n; i += 256u) {
        buf[bitrev(i, lg)] = field[base + i * n];
    }
    workgroupBarrier();
    fft_buf(li, sign);
    for (var i = li; i < n; i += 256u) {
        field[base + i * n] = buf[i] * scale;
    }
}

@compute @workgroup_size(256)
fn fft_rows(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    rows(wg, li, -1.0, 1.0);
}

@compute @workgroup_size(256)
fn fft_cols(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    cols(wg, li, -1.0, 1.0);
}

@compute @workgroup_size(256)
fn ifft_rows(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    rows(wg, li, 1.0, 1.0 / c.pm.x);
}

@compute @workgroup_size(256)
fn ifft_cols(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_index) li: u32) {
    cols(wg, li, 1.0, 1.0 / c.pm.x);
}

fn sinc(x: f32) -> f32 {
    if (abs(x) < 1e-4) {
        return 1.0;
    }
    return sin(x) / x;
}

@compute @workgroup_size(256)
fn green(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    let n = cells();
    if (i >= n * n) {
        return;
    }
    let ix = i % n;
    let iy = i / n;
    let mx = select(f32(ix), f32(ix) - f32(n), ix >= n / 2u);
    let my = select(f32(iy), f32(iy) - f32(n), iy >= n / 2u);
    let d = cell_pc();
    let l = d * f32(n);
    let kv = vec2<f32>(mx, my) * (2.0 * PI / l);
    let k = length(kv);
    if (k <= 0.0) {
        field[i] = vec2<f32>(0.0);
        field[n * n + i] = vec2<f32>(0.0);
        return;
    }
    let w = sinc(0.5 * kv.x * d) * sinc(0.5 * kv.y * d);
    let w2 = w * w;
    let rho = field[i];
    let gk = -2.0 * PI * c.g / k * erfc_approx(k * c.pm.y) / (w2 * w2);
    let phi = rho * gk;
    // g = -ik φ; (gx + i gy) as one field: -i kx φ + i (-i ky φ) = φ (ky - i kx)
    let f1 = vec2<f32>(phi.x * kv.y + phi.y * kv.x, phi.y * kv.y - phi.x * kv.x);
    field[i] = f1;
    field[n * n + i] = phi;
}

fn boundary_scale() -> f32 {
    return scale_factor(c.cosmo_p.w + f32(ctl[3]) * c.dt);
}

@compute @workgroup_size(256)
fn interp(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let n = cells();
    let w = cic(pos[i]);
    let x1 = (w.i0.x + 1u) & (n - 1u);
    let y1 = (w.i0.y + 1u) & (n - 1u);
    let c00 = w.i0.y * n + w.i0.x;
    let c10 = w.i0.y * n + x1;
    let c01 = y1 * n + w.i0.x;
    let c11 = y1 * n + x1;
    let a = (1.0 - w.t.x) * (1.0 - w.t.y);
    let b = w.t.x * (1.0 - w.t.y);
    let cc = (1.0 - w.t.x) * w.t.y;
    let dd = w.t.x * w.t.y;
    let g = field[c00] * a + field[c10] * b + field[c01] * cc + field[c11] * dd;
    let p = field[n * n + c00].x * a + field[n * n + c10].x * b + field[n * n + c01].x * cc + field[n * n + c11].x * dd;
    let s = boundary_scale();
    pm_acc[i] = vec4<f32>(g / (s * s), p / s, 0.0);
}

// half a step of the long-range pull
@compute @workgroup_size(256)
fn kick(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let k = kin[i];
    kin[i] = vec4<f32>(k.xy + pm_acc[i].xy * (0.5 * c.dt), k.zw);
}

// the step about to run (after evolve.wgsl tick_clock): its scale factor and Hubble rate at its middle, for every
// pass (src/sim/mod.rs copies these into the shared parameters)
@compute @workgroup_size(1)
fn cosmo_step() {
    let t = c.cosmo_p.w + (f32(ctl[3]) - 0.5) * c.dt;
    let a = scale_factor(t);
    cosmo_out[0] = c.cosmo_q.w * a;
    cosmo_out[1] = 1.0 / (c.cosmo_q.w * a);
    cosmo_out[2] = a;
    cosmo_out[3] = hubble(a);
    let soft = min(1.0, a / max(c.cosmo_q.x, 1e-6));
    cosmo_out[4] = select(1.0, soft * soft, c.cosmo_q.x > 0.0);
    cosmo_out[5] = 1.0 / a;
}
