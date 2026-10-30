"""Starting scenes (F1-F4, or --preset). Each takes a World and an optional particle count."""

import numpy as np

from . import config


def _ring(world, cx, cy, r_in, r_out, count, masses, mass_p, strength):
    """count particles spread evenly over an annulus, on circular orbits around a well of `strength` at (cx, cy)."""
    rng = world.rng
    r = np.sqrt(rng.uniform(r_in ** 2, r_out ** 2, count))
    a = rng.uniform(0, 2 * np.pi, count)
    xs, ys = cx + r * np.cos(a), cy + r * np.sin(a)
    soft = config.WELL_SOFTENING
    v = np.sqrt(strength * r * r / (r * r + soft * soft) ** 1.5) * rng.normal(1.0, 0.05, count)
    vxs, vys = -np.sin(a) * v, np.cos(a) * v
    return world.place_many(np.round(xs), np.round(ys), rng.choice(masses, count, p=mass_p), vxs, vys)


def rain(world, count=None):
    """Mixed masses fill the top of the world and fall under down-gravity; heavy ones sink through light ones."""
    world.reset()
    world.set_gravity(0)
    w, h = world.w, world.h
    count = count or int(w * h * 0.35)
    rng = world.rng
    world.place_many(rng.integers(0, w, count), rng.integers(0, h * 2 // 3, count),
                     rng.choice([1, 4, 16, 64], count, p=[0.55, 0.3, 0.12, 0.03]))


def disk(world, count=None):
    """A dust disk orbiting a central well."""
    world.reset()
    w, h = world.w, world.h
    strength = config.WELL_STRENGTH * 3
    world.add_well(world.pw / 2, world.ph / 2, strength)
    s = min(w, h)
    count = count or int(np.pi * ((0.47 * s) ** 2 - (0.2 * s) ** 2) * 0.25)
    _ring(world, w / 2, h / 2, 0.2 * s, 0.47 * s, count, [1, 4, 16], [0.7, 0.25, 0.05], strength)


def cloud(world, count=None):
    """A slowly turning cloud with self-gravity and merging on: it collapses into clumps that grow by accretion."""
    world.reset()
    world.sg_on = True
    world.merge_on = True
    w, h = world.w, world.h
    rng = world.rng
    count = count or int(w * h * 0.25)
    r = 0.42 * min(w, h) * np.sqrt(rng.uniform(0, 1, count))
    a = rng.uniform(0, 2 * np.pi, count)
    spin = 0.004
    xs, ys = w / 2 + r * np.cos(a), h / 2 + r * np.sin(a)
    vxs = -np.sin(a) * r * spin + rng.normal(0, 0.05, count)
    vys = np.cos(a) * r * spin + rng.normal(0, 0.05, count)
    world.place_many(np.round(xs), np.round(ys), 1, vxs, vys)


def binary(world, count=None):
    """Two wells with a shared ring of particles around them."""
    world.reset()
    w, h = world.w, world.h
    strength = config.WELL_STRENGTH * 2
    world.add_well(world.pw * 0.38, world.ph / 2, strength)
    world.add_well(world.pw * 0.62, world.ph / 2, strength)
    s = min(w, h)
    count = count or int(np.pi * ((0.46 * s) ** 2 - (0.3 * s) ** 2) * 0.5)
    _ring(world, w / 2, h / 2, 0.3 * s, 0.46 * s, count, [1, 4, 16, 64], [0.6, 0.28, 0.1, 0.02], 2 * strength)


def empty(world, count=None):
    world.reset()


PRESETS = {"rain": rain, "disk": disk, "cloud": cloud, "binary": binary, "empty": empty}
