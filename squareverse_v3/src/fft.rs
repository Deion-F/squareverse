//! A small complex FFT (radix 2, in place) on the CPU: the universe's starting conditions use it, and the tests
//! check the GPU's (shaders/pm.wgsl) against it.

use std::f64::consts::TAU;

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct C64 {
    pub re: f64,
    pub im: f64,
}

#[allow(clippy::should_implement_trait)]
impl C64 {
    pub const fn new(re: f64, im: f64) -> Self {
        Self { re, im }
    }
    pub fn mul(self, o: Self) -> Self {
        Self::new(self.re * o.re - self.im * o.im, self.re * o.im + self.im * o.re)
    }
    pub fn add(self, o: Self) -> Self {
        Self::new(self.re + o.re, self.im + o.im)
    }
    pub fn sub(self, o: Self) -> Self {
        Self::new(self.re - o.re, self.im - o.im)
    }
    pub fn scale(self, s: f64) -> Self {
        Self::new(self.re * s, self.im * s)
    }
}

/// In place, length a power of two. Forward: X_k = Σ x_j e^(-2πi jk/n); inverse: with e^(+...) and divided by n.
pub fn fft(a: &mut [C64], inverse: bool) {
    let n = a.len();
    assert!(n.is_power_of_two(), "FFT length must be a power of two");
    let bits = n.trailing_zeros();
    if bits == 0 {
        return;
    }
    for i in 0..n {
        let j = i.reverse_bits() >> (usize::BITS - bits);
        if i < j {
            a.swap(i, j);
        }
    }
    let sign = if inverse { 1.0 } else { -1.0 };
    let mut len = 2;
    while len <= n {
        let half = len / 2;
        for k in 0..half {
            let ang = sign * TAU * k as f64 / len as f64;
            let w = C64::new(ang.cos(), ang.sin());
            for s in (0..n).step_by(len) {
                let t = w.mul(a[s + k + half]);
                let u = a[s + k];
                a[s + k] = u.add(t);
                a[s + k + half] = u.sub(t);
            }
        }
        len *= 2;
    }
    if inverse {
        let s = 1.0 / n as f64;
        a.iter_mut().for_each(|x| *x = x.scale(s));
    }
}

/// 2D, row-major n x n: rows, then columns.
pub fn fft2(a: &mut [C64], n: usize, inverse: bool) {
    assert_eq!(a.len(), n * n);
    for row in a.chunks_mut(n) {
        fft(row, inverse);
    }
    let mut col = vec![C64::default(); n];
    for x in 0..n {
        for y in 0..n {
            col[y] = a[y * n + x];
        }
        fft(&mut col, inverse);
        for y in 0..n {
            a[y * n + x] = col[y];
        }
    }
}

/// The wavenumber of FFT index i on an n-point grid over length l (negative in the upper half).
pub fn wavenumber(i: usize, n: usize, l: f64) -> f64 {
    let m = if i < n / 2 { i as f64 } else { i as f64 - n as f64 };
    TAU * m / l
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_and_known_transform() {
        let n = 64;
        let mut a: Vec<C64> = (0..n).map(|i| C64::new((i as f64 * 0.3).sin(), (i as f64 * 0.1).cos())).collect();
        let orig = a.clone();
        fft(&mut a, false);
        // the DC term is the sum
        let sum = orig.iter().fold(C64::default(), |s, x| s.add(*x));
        assert!((a[0].re - sum.re).abs() < 1e-9 && (a[0].im - sum.im).abs() < 1e-9);
        // a direct DFT at k = 5
        let k = 5;
        let d = orig.iter().enumerate().fold(C64::default(), |s, (j, x)| {
            let ang = -TAU * (j * k) as f64 / n as f64;
            s.add(x.mul(C64::new(ang.cos(), ang.sin())))
        });
        assert!((a[k].re - d.re).abs() < 1e-9 && (a[k].im - d.im).abs() < 1e-9);
        fft(&mut a, true);
        for (x, y) in a.iter().zip(&orig) {
            assert!((x.re - y.re).abs() < 1e-12 && (x.im - y.im).abs() < 1e-12);
        }
    }
}
