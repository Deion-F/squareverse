// 64-bit fixed-point positions, one (hi, lo) pair of u32 words per axis; a particle is vec4<u32>(x_hi, x_lo, y_hi, y_lo).
// The box is 2^32 "hi units" across and wraps (u32 arithmetic wraps). Mirrors src/fixed.rs.

const INV_2_32: f32 = 2.3283064e-10;
const BELOW_2_32: f32 = 4294967040.0; // the largest f32 under 2^32

// a - b along one axis, in hi units, the short way round the box. Exact in integers, then one rounding to f32.
fn fx_delta(a_hi: u32, a_lo: u32, b_hi: u32, b_lo: u32) -> f32 {
    let borrow = select(0u, 1u, a_lo < b_lo);
    let hi = a_hi - b_hi - borrow;
    let lo = a_lo - b_lo;
    if (hi == 0u) {
        return f32(lo) * INV_2_32;
    }
    if (hi == 0xFFFFFFFFu && lo != 0u) {
        // small and negative: -(2^32 - lo) without losing lo's precision against the -1
        return -f32(0u - lo) * INV_2_32;
    }
    return f32(bitcast<i32>(hi)) + f32(lo) * INV_2_32;
}

fn fx_delta2(a: vec4<u32>, b: vec4<u32>) -> vec2<f32> {
    return vec2<f32>(fx_delta(a.x, a.y, b.x, b.y), fx_delta(a.z, a.w, b.z, b.w));
}

// (hi, lo) moved by d hi units (either sign), with carry / borrow between the words.
fn fx_add(hi: u32, lo: u32, d: f32) -> vec2<u32> {
    let m = abs(d);
    let mh = floor(m);
    let ml = u32(min((m - mh) * 4294967296.0, BELOW_2_32));
    let mhu = u32(mh);
    if (d >= 0.0) {
        let nlo = lo + ml;
        let carry = select(0u, 1u, nlo < lo);
        return vec2<u32>(hi + mhu + carry, nlo);
    }
    let borrow = select(0u, 1u, lo < ml);
    return vec2<u32>(hi - mhu - borrow, lo - ml);
}

fn fx_add2(q: vec4<u32>, d: vec2<f32>) -> vec4<u32> {
    let x = fx_add(q.x, q.y, d.x);
    let y = fx_add(q.z, q.w, d.y);
    return vec4<u32>(x, y);
}
