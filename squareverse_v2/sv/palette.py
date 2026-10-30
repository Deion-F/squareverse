"""Colour lookup tables for the render kernel (numpy only, so the World works without a display)."""

import numpy as np

from . import config, kernels

# mass colour stops on a log scale from mass 1 to MAX_MASS: light sand -> orange -> red -> violet -> blue -> white
MASS_STOPS = [
    (0.00, (232, 212, 160)),
    (0.18, (214, 138, 88)),
    (0.38, (196, 72, 72)),
    (0.58, (150, 80, 176)),
    (0.80, (70, 110, 214)),
    (1.00, (225, 240, 255)),
]
HEAT_STOPS = [(0.0, (40, 40, 60)), (0.3, (170, 40, 40)), (0.65, (250, 180, 40)), (1.0, (255, 255, 230))]


def _gradient(stops, t):
    pos = np.array([p for p, _ in stops])
    cols = np.array([c for _, c in stops], np.float64)
    return np.stack([np.interp(t, pos, cols[:, c]) for c in range(3)], axis=1)


def mass_lut(max_mass=config.MAX_MASS):
    m = np.arange(max_mass + 1, dtype=np.float64)
    t = np.log(np.maximum(m, 1.0)) / np.log(max_mass)
    return _gradient(MASS_STOPS, t).astype(np.int32)


def heat_lut():
    return _gradient(HEAT_STOPS, np.linspace(0.0, 1.0, 256)).astype(np.uint8)


def shade_mul():
    """Per-shade brightness multipliers (x/256), the same 0.86-1.14 spread as sand.py."""
    s = np.arange(kernels.N_SHADES)
    return (256 * (0.86 + 0.28 * s / (kernels.N_SHADES - 1))).astype(np.int32)
