"""Starting scenes (F1-F4, or --preset). Each takes a World and an optional particle count. Rain fills the window's
rectangle; the space scenes are round universes reaching past the window (World.set_round), sized to the window."""

import numpy as np

from . import config
from .gravity import fade


def _ring(world, cx, cy, r_in, r_out, count, masses, mass_p, strength):
    """count particles spread evenly over an annulus, on circular orbits around a pull of `strength` (G x mass) at
    (cx, cy)."""
    rng = world.rng
    r = np.sqrt(rng.uniform(r_in ** 2, r_out ** 2, count))
    a = rng.uniform(0, 2 * np.pi, count)
    xs, ys = cx + r * np.cos(a), cy + r * np.sin(a)
    soft = config.WELL_SOFTENING
    rho = np.sqrt(r * r + soft * soft)
    v = np.sqrt(strength * r * r / rho ** 3 * fade(rho, world.kinv)[0]) * rng.normal(1.0, 0.05, count)
    vxs, vys = -np.sin(a) * v, np.cos(a) * v
    return world.place_many(np.round(xs), np.round(ys), rng.choice(masses, count, p=mass_p), vxs, vys)


def rain(world, count=None):
    """Mixed masses fill the top of the world and fall under down-gravity; heavy ones sink through light ones."""
    world.set_round(False)
    world.reset()
    world.set_gravity(0)
    w, h = world.w, world.h
    count = count or int(w * h * 0.35)
    rng = world.rng
    world.place_many(rng.integers(0, w, count), rng.integers(0, h * 2 // 3, count),
                     rng.choice([1, 4, 16, 64], count, p=[0.55, 0.3, 0.12, 0.03]))


def _spread_masses(rng, count, total):
    """count particle masses spread evenly over orders of magnitude (log-uniform, from 1 up to at most MAX_MASS),
    adding up to about total."""
    u = rng.uniform(0, 1, count)
    lo, hi = 1.0, float(config.MAX_MASS)
    for _ in range(40):                              # the top mass that makes them add up to the total
        top = (lo + hi) / 2
        if np.floor((top + 1) ** u).sum() < total:
            lo = top
        else:
            hi = top
    return np.minimum(np.floor((hi + 1) ** u), config.MAX_MASS).astype(np.int64)


def disk(world, count=None):
    """A heavy dust disk of every mass from 1 to thousands (DISK_MASS in all) turning with the clockwise global
    orbit in a round universe, held together by its own gravity (no central well), gravity reaching DISK_REACH."""
    world.set_round(True)
    world.reset()
    world.set_reach(config.DISK_REACH)               # tuned for it: reaching everywhere it runs twice as slowly
    world.set_orbit(1)
    world.set_self_gravity(True)
    w, h = world.w, world.h
    rng = world.rng
    s = min(world.vw, world.vh)
    count = count or int(np.pi * ((0.47 * s) ** 2 - (0.2 * s) ** 2) * config.DISK_FILL)
    r = np.sqrt(rng.uniform((0.2 * s) ** 2, (0.47 * s) ** 2, count))
    a = rng.uniform(0, 2 * np.pi, count)
    xs, ys = np.round(w / 2 + r * np.cos(a)).astype(np.int64), np.round(h / 2 + r * np.sin(a)).astype(np.int64)
    _, first = np.unique(ys * w + xs, return_index=True)   # one particle per cell, so the masses add up
    r, a, xs, ys = r[first], a[first], xs[first], ys[first]
    v = world.orbit_speed * r                        # already turning with the universe
    world.place_many(xs, ys, _spread_masses(rng, xs.size, config.DISK_MASS), -np.sin(a) * v, np.cos(a) * v)


def cloud(world, count=None):
    """A slowly turning cloud with self-gravity and merging on: it collapses into clumps that grow by accretion."""
    world.set_round(True)
    world.reset()
    world.sg_on = True
    world.merge_on = True
    w, h = world.w, world.h
    rng = world.rng
    count = count or int(world.vw * world.vh * 0.25)
    r = 0.42 * min(world.vw, world.vh) * np.sqrt(rng.uniform(0, 1, count))
    a = rng.uniform(0, 2 * np.pi, count)
    spin = 0.004
    xs, ys = w / 2 + r * np.cos(a), h / 2 + r * np.sin(a)
    vxs = -np.sin(a) * r * spin + rng.normal(0, 0.05, count)
    vys = np.cos(a) * r * spin + rng.normal(0, 0.05, count)
    world.place_many(np.round(xs), np.round(ys), 1, vxs, vys)


def binary(world, count=None):
    """Two stars orbiting each other, with a shared ring of particles around them."""
    world.set_round(True)
    world.reset()
    w, h = world.w, world.h
    a = world.vh * 0.09                               # each star's distance from the centre (cells)
    r = 0.03 * min(world.vw, world.vh)                # each star's radius (cells)
    mass = 30000.0                                    # under the collapse mass: stars are made of particles
    strength = world.g_scale * config.G * mass
    soft = config.STAR_SOFTENING * r
    # circular mutual orbit around the centre: v^2 / a = the other's pull across d = 2a
    d = 2 * a
    rho = np.sqrt(d * d + soft * soft)
    v = np.sqrt(strength * d / rho ** 3 * fade(rho, world.kinv)[0] * a)
    # clockwise on screen, the same way as the ring
    world.add_star(world.pw / 2 - a * world.cell, world.ph / 2, r * world.cell, mass=mass, vy=-v)
    world.add_star(world.pw / 2 + a * world.cell, world.ph / 2, r * world.cell, mass=mass, vy=v)
    s = min(world.vw, world.vh)
    count = count or int(np.pi * ((0.47 * s) ** 2 - (0.36 * s) ** 2) * 0.12)
    # light enough that the stars, which feel it, keep orbiting each other
    _ring(world, w / 2, h / 2, 0.36 * s, 0.47 * s, count, [1, 2, 4], [0.6, 0.3, 0.1], 2 * strength)


def systems(world, count=None):
    """A super well in the middle with SYSTEM_CENTRE_STARS stars orbiting it, and SYSTEM_OTHERS more scattered at
    random round it with SYSTEM_OTHER_STARS each: the stable orbits of SYSTEM_* (pour-mass stars SYSTEM_STAR_RADIUS
    across in radius, SYSTEM_ORBIT out round SYSTEM_WELL wells), each star set off at the circular speed with its
    well taking the opposite momentum (World.add_star(orbit=True)). Systems are at least SYSTEM_SPACING x the orbit
    apart (centre to centre), their stars inside the edge, and placed where their pulls on the middle one roughly
    cancel (SYSTEM_BALANCE), so they don't disturb each other at once - gravity reaching everywhere, they do after
    twenty seconds or so. In a universe too small for that it is all scaled down (lengths x k, masses x k^2, which
    keeps the tides and orbits alike), down to SYSTEM_MIN_SCALE, and then the systems are closer together."""
    world.set_round(True)
    world.reset()
    rng = world.rng
    c = world.cell
    cx, cy = world.w / 2, world.h / 2
    room = min(world.w, world.h) / 2 - config.SYSTEM_EDGE   # how far out a star may reach (cells)
    spacing = config.SYSTEM_SPACING
    size = config.SYSTEM_ORBIT + config.SYSTEM_STAR_RADIUS          # how far a system's stars reach (cells)
    k = min(1.0, room / (spacing * config.SYSTEM_ORBIT + size))
    if k < config.SYSTEM_MIN_SCALE:                  # smaller stars wouldn't hold together: closer systems instead
        k = config.SYSTEM_MIN_SCALE
        spacing = max(1.5, (room / k - size) / config.SYSTEM_ORBIT)
    orbit, star_r = config.SYSTEM_ORBIT * k, config.SYSTEM_STAR_RADIUS * k

    def system(x, y, stars):
        world.add_super_well(x * c, y * c, config.SYSTEM_WELL * k * k)
        a0 = rng.uniform(0, 2 * np.pi)
        for a in a0 + 2 * np.pi * np.arange(stars) / stars:
            world.add_star((x + orbit * np.cos(a)) * c, (y + orbit * np.sin(a)) * c, star_r * c,
                           config.SYSTEM_POUR, orbit=True)

    system(cx, cy, config.SYSTEM_CENTRE_STARS)
    near, far = spacing * orbit, max(spacing * orbit, room - size * k)
    n = rng.integers(config.SYSTEM_OTHERS[0], config.SYSTEM_OTHERS[1] + 1)
    best, best_pull = None, np.inf
    for _ in range(2000):                            # random spots clear of each other whose pulls on the middle
        r = np.sqrt(rng.uniform(near ** 2, far ** 2, n))     # one roughly cancel (else it drags the middle one's
        a = rng.uniform(0, 2 * np.pi, n)                     # stars off their orbits: its well responds less)
        xs, ys = r * np.cos(a), r * np.sin(a)
        if np.hypot(xs[:, None] - xs, ys[:, None] - ys)[np.triu_indices(n, 1)].min(initial=np.inf) < near:
            continue
        pull = np.hypot((xs / r ** 3).sum(), (ys / r ** 3).sum()) * near ** 2
        if pull < best_pull:
            best, best_pull = (xs, ys), pull
        if pull < config.SYSTEM_BALANCE:
            break
    if best is not None:
        for x, y in zip(*best):
            system(cx + x, cy + y, rng.integers(config.SYSTEM_OTHER_STARS[0], config.SYSTEM_OTHER_STARS[1] + 1))


def empty(world, count=None):
    world.reset()


PRESETS = {"rain": rain, "disk": disk, "cloud": cloud, "binary": binary, "systems": systems, "empty": empty}
