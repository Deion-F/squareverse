//! Positions are 64-bit fixed point per axis over a periodic box: 0 .. 2^64 covers the box once and wraps around
//! (integer overflow is the periodic boundary). Over a 20 Mpc box one unit is ~1e-12 pc, the same everywhere.
//!
//! On the GPU an axis is two u32 words (hi, lo), so a particle's position is a `vec4<u32>` (x_hi, x_lo, y_hi, y_lo);
//! `shaders/fixed.wgsl` has the same operations as here. Differences between positions are taken in integers (exact)
//! and only then turned into floats, so precision is relative to the separation, not to the box.

pub const TWO_32: f64 = 4_294_967_296.0;
pub const TWO_64: f64 = 18_446_744_073_709_551_616.0;

/// A position in the box as one u64 per axis.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Fixed2 {
    pub x: u64,
    pub y: u64,
}

impl Fixed2 {
    /// From parsecs (any value; wrapped into the box).
    pub fn from_pc(x: f64, y: f64, box_pc: f64) -> Self {
        Self { x: axis_from_pc(x, box_pc), y: axis_from_pc(y, box_pc) }
    }

    /// Parsecs from the box's origin, 0 .. box_pc.
    pub fn to_pc(self, box_pc: f64) -> (f64, f64) {
        (self.x as f64 / TWO_64 * box_pc, self.y as f64 / TWO_64 * box_pc)
    }

    /// The GPU layout: (x_hi, x_lo, y_hi, y_lo).
    pub fn words(self) -> [u32; 4] {
        [(self.x >> 32) as u32, self.x as u32, (self.y >> 32) as u32, self.y as u32]
    }

    pub fn from_words(w: [u32; 4]) -> Self {
        Self { x: ((w[0] as u64) << 32) | w[1] as u64, y: ((w[2] as u64) << 32) | w[3] as u64 }
    }

    /// The shortest separation self - other in parsecs, across the wrap if that is shorter.
    pub fn delta_pc(self, other: Self, box_pc: f64) -> (f64, f64) {
        (axis_delta_pc(self.x, other.x, box_pc), axis_delta_pc(self.y, other.y, box_pc))
    }

    /// Moved by (dx, dy) parsecs.
    pub fn offset_pc(self, dx: f64, dy: f64, box_pc: f64) -> Self {
        Self { x: axis_offset(self.x, dx, box_pc), y: axis_offset(self.y, dy, box_pc) }
    }
}

pub fn axis_from_pc(x: f64, box_pc: f64) -> u64 {
    let f = (x / box_pc).rem_euclid(1.0);
    (f * TWO_64) as u64 // saturates at u64::MAX if f rounds up to 1
}

pub fn axis_delta_pc(a: u64, b: u64, box_pc: f64) -> f64 {
    a.wrapping_sub(b) as i64 as f64 / TWO_64 * box_pc
}

pub fn axis_offset(a: u64, d_pc: f64, box_pc: f64) -> u64 {
    let units = d_pc / box_pc * TWO_64;
    if units >= 0.0 { a.wrapping_add(units.round() as u64) } else { a.wrapping_sub((-units).round() as u64) }
}

#[cfg(test)]
mod tests {
    use super::*;

    const BOX: f64 = 20_000_000.0;

    #[test]
    fn round_trip_keeps_sub_au_precision() {
        for &x in &[0.0, 1.0, 12_345.678_9, BOX / 2.0, BOX - 1e-3] {
            let p = Fixed2::from_pc(x, x, BOX);
            let (bx, _) = p.to_pc(BOX);
            // f64 itself limits this to ~1e-16 of the box (2e-9 pc): far below an AU (4.8e-6 pc)
            assert!((bx - x).abs() < 1e-8, "{x} -> {bx}");
            assert_eq!(Fixed2::from_words(p.words()), p);
        }
    }

    #[test]
    fn wraps_at_the_box_edge() {
        let p = Fixed2::from_pc(-1.0, BOX + 2.0, BOX);
        let (x, y) = p.to_pc(BOX);
        assert!((x - (BOX - 1.0)).abs() < 1e-6 && (y - 2.0).abs() < 1e-6);
        // the separation across the edge is the short way round
        let a = Fixed2::from_pc(BOX - 3.0, 0.0, BOX);
        let b = Fixed2::from_pc(4.0, 0.0, BOX);
        let (dx, _) = a.delta_pc(b, BOX);
        assert!((dx + 7.0).abs() < 1e-6, "{dx}");
    }

    #[test]
    fn small_separations_are_exact_far_from_the_origin() {
        let a = Fixed2::from_pc(BOX * 0.73, BOX * 0.31, BOX);
        let b = a.offset_pc(1e-6, -2e-6, BOX); // a fifth and two fifths of an AU
        let (dx, dy) = b.delta_pc(a, BOX);
        let unit = BOX / TWO_64; // 1.1e-12 pc
        assert!((dx - 1e-6).abs() <= unit && (dy + 2e-6).abs() <= unit, "{dx} {dy}");
    }
}
