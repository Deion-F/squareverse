"""Gravity: the cached external field (wells + global direction) and particle-mesh self-gravity."""

import numpy as np

from . import config, kernels


def external_field(w, h, wells, gvec):
    """Acceleration (fx, fy) and potential phi for every cell, as flat float32 arrays.

    wells: [(x, y, strength, softening)] in cell units; negative strength repels.
    gvec: global gravity acceleration (gx, gy), or None.
    """
    gx, gy = gvec if gvec is not None else (0.0, 0.0)
    wells = np.array(wells, np.float64).reshape(-1, 4)
    fx = np.empty(w * h, np.float32)
    fy = np.empty(w * h, np.float32)
    phi = np.empty(w * h, np.float32)
    kernels.field(w, h, wells, gx, gy, fx, fy, phi)
    return fx, fy, phi


def order_buckets(phi, rng, nb=config.ORDER_BUCKETS):
    """Rank each cell's potential into nb equal-population buckets (lowest potential = bucket 0)."""
    if float(phi.max() - phi.min()) < 1e-9:
        return np.zeros(phi.size, np.uint16)
    sample = np.sort(phi[rng.integers(0, phi.size, 65536)])
    edges = sample[np.arange(1, nb) * sample.size // nb]
    return np.searchsorted(edges, phi).astype(np.uint16)


class SelfGravity:
    """Particle-mesh gravity: bin mass into blocks, convolve with a softened 1/r kernel via FFT on a zero-padded
    grid (so the edges don't wrap around), and take the gradient. Particles read their block's acceleration."""

    def __init__(self, w, h, block=config.SG_BLOCK, softening=config.SG_SOFTENING):
        self.w, self.h, self.block = w, h, block
        self.cw, self.ch = -(-w // block), -(-h // block)
        self.rho = np.zeros(self.cw * self.ch, np.float64)
        self.gx = np.zeros(self.cw * self.ch, np.float32)
        self.gy = np.zeros(self.cw * self.ch, np.float32)
        py, px = 2 * self.ch, 2 * self.cw
        iy = np.minimum(np.arange(py), py - np.arange(py))
        ix = np.minimum(np.arange(px), px - np.arange(px))
        r = block * np.hypot(iy[:, None], ix[None, :])
        green = -1.0 / np.sqrt(r * r + (softening * block) ** 2)
        self.green_hat = np.fft.rfft2(green)
        self._pad = np.zeros((py, px), np.float64)

    def update(self, mass, g):
        """Recompute the field. Returns a bool mask of blocks whose acceleration changed by more than SG_WAKE."""
        ch, cw = self.ch, self.cw
        kernels.bin_mass(mass, self.w, self.h, self.block, cw, self.rho)
        self._pad[:ch, :cw] = self.rho.reshape(ch, cw)
        phi = np.fft.irfft2(np.fft.rfft2(self._pad) * self.green_hat, s=self._pad.shape)[:ch, :cw] * g
        gy, gx = np.gradient(phi, self.block)
        gx = (-gx).astype(np.float32).ravel()
        gy = (-gy).astype(np.float32).ravel()
        changed = (np.abs(gx - self.gx) > config.SG_WAKE) | (np.abs(gy - self.gy) > config.SG_WAKE)
        self.gx, self.gy = gx, gy
        return changed

    def reset(self):
        self.gx[:] = 0.0
        self.gy[:] = 0.0
