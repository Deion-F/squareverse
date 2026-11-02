"""Gravity: the cached external field (wells + global direction) and particle-mesh self-gravity."""

import functools
import math

import numpy as np

from . import config, kernels


def fade(rho, kinv):
    """Shares of the plain inverse-square pull and of its potential left at softened distance rho (a number or an
    array) when gravity reaches about 1 / kinv cells (kinv = 0: all the way). As kernels.fade."""
    e = np.exp(-rho * kinv)
    return e * (1.0 + rho * kinv), e


@functools.lru_cache(maxsize=4096)
def reach_for(strength, accel, kinv):
    """The distance (cells) at which a pull of `strength` (G x mass) drops to accel: strength / r^2, faded. (Asked
    for many times a tick for the same few wells, so the answers are kept.)"""
    r = math.sqrt(max(strength, 0.0) / accel)
    if kinv <= 0.0 or r <= 0.0:
        return r
    # solve ln(strength / accel) + ln(1 + r kinv) - r kinv - 2 ln r = 0 in u = ln r by Newton's method: the left
    # side falls and curves down in u, so from the unfaded distance (beyond the answer) it closes in from above
    c = math.log(strength / accel)
    u = math.log(r)
    for _ in range(30):
        r = math.exp(u)
        x = r * kinv
        g = c + math.log1p(x) - x - 2.0 * u
        step = g / (x / (1.0 + x) - x - 2.0)
        u -= step
        if abs(step) < 1e-9:
            break
    return math.exp(u)


def external_field(w, h, wells, gvec, wrap=False, kinv=0.0, gpu=None, key=None):
    """Acceleration (fx, fy) and potential phi for every cell, as flat float32 arrays.

    wells: [(x, y, strength, softening)] in cell units; negative strength repels.
    gvec: global gravity acceleration (gx, gy), or None. wrap: wells pull the shortest way round the borders.
    kinv: 1 / how far gravity reaches (0: all the way; see fade).
    gpu: work it out on that gpu.Gpu instead, which keeps it there for the ghosts under the name key.
    """
    gx, gy = gvec if gvec is not None else (0.0, 0.0)
    wells = np.array(wells, np.float64).reshape(-1, 4)
    # exact pull within a few softening lengths of each well (FIELD_NEAR to FIELD_NEAR_MAX cells); blended beyond
    near = np.clip(3.0 * wells[:, 3], config.FIELD_NEAR, config.FIELD_NEAR_MAX)
    fx = np.empty(w * h, np.float32)
    fy = np.empty(w * h, np.float32)
    phi = np.empty(w * h, np.float32)
    if gpu is not None:
        gpu.field(w, h, config.FIELD_BLOCK, wells, near, gx, gy, wrap, kinv, fx, fy, phi, key)
    else:
        kernels.field(w, h, config.FIELD_BLOCK, wells, near, gx, gy, fx, fy, phi, wrap, kinv)
    return fx, fy, phi


def fast_len(n):
    """The smallest length at least n whose only prime factors are 2, 3 and 5: the FFT is quick at those sizes, and
    can be several times slower at others (a 271-block mesh padded to 542 = 2 x 271 took 29 ms an update, 576 8 ms)."""
    best = 1 << max(0, (n - 1).bit_length())
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


def order_buckets(phi, rng, nb=config.ORDER_BUCKETS, cores=False):
    """Rank each cell's potential into nb equal-population buckets (lowest potential = bucket 0). cores: rank on all
    cores (the same result)."""
    if float(phi.max() - phi.min()) < 1e-9:
        return np.zeros(phi.size, np.uint16)
    sample = np.sort(phi[rng.integers(0, phi.size, 65536)])
    edges = sample[np.arange(1, nb) * sample.size // nb]
    if cores:
        out = np.empty(phi.size, np.uint16)
        kernels.bucketize(edges, phi, out)
        return out
    return np.searchsorted(edges, phi).astype(np.uint16)


class SelfGravity:
    """Particle-mesh gravity: bin mass into blocks, convolve with a softened 1/r kernel (faded with distance as
    fade() says) via FFT, and take the gradient. Particles read their block's acceleration. The grid is zero-padded
    so the edges don't interact (to at least twice its size, rounded up to a length the FFT is quick at: fast_len),
    unless the borders wrap: then the FFT's own periodicity is exactly what is wanted."""

    def __init__(self, w, h, block=config.SG_BLOCK, softening=config.SG_SOFTENING, wrap=False, kinv=0.0):
        self.w, self.h, self.block, self.wrap = w, h, block, wrap
        self.cw, self.ch = -(-w // block), -(-h // block)
        self.rho = np.zeros(self.cw * self.ch, np.float64)
        self.gx = np.zeros(self.cw * self.ch, np.float32)
        self.gy = np.zeros(self.cw * self.ch, np.float32)
        py, px = (self.ch, self.cw) if wrap else (fast_len(2 * self.ch), fast_len(2 * self.cw))
        iy = np.minimum(np.arange(py), py - np.arange(py))
        ix = np.minimum(np.arange(px), px - np.arange(px))
        r = block * np.hypot(iy[:, None], ix[None, :])
        rho = np.sqrt(r * r + (softening * block) ** 2)
        green = -fade(rho, kinv)[1] / rho
        self.green_hat = np.fft.rfft2(green)
        self._pad = np.zeros((py, px), np.float64)

    def update(self, mass, g, owner=None):
        """Recompute the field. Returns a bool mask of blocks whose acceleration changed by more than SG_WAKE.
        owner: leave out the particles that belong to stars (owner > 0); a star pulls as a whole."""
        ch, cw = self.ch, self.cw
        if owner is None:
            kernels.bin_mass(mass, self.w, self.h, self.block, cw, self.rho)
        else:
            kernels.bin_free_mass(mass, owner, self.w, self.h, self.block, cw, self.rho)
        self._pad[:ch, :cw] = self.rho.reshape(ch, cw)
        phi = np.fft.irfft2(np.fft.rfft2(self._pad) * self.green_hat, s=self._pad.shape)[:ch, :cw] * g
        if self.wrap:
            gx = (np.roll(phi, -1, axis=1) - np.roll(phi, 1, axis=1)) / (2 * self.block)
            gy = (np.roll(phi, -1, axis=0) - np.roll(phi, 1, axis=0)) / (2 * self.block)
        else:
            gy, gx = np.gradient(phi, self.block)
        gx = (-gx).astype(np.float32).ravel()
        gy = (-gy).astype(np.float32).ravel()
        changed = (np.abs(gx - self.gx) > config.SG_WAKE) | (np.abs(gy - self.gy) > config.SG_WAKE)
        self.gx, self.gy = gx, gy
        return changed

    def reset(self):
        self.gx[:] = 0.0
        self.gy[:] = 0.0
