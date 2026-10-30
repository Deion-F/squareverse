"""Physics invariants of the v2 engine. Run from squareverse_v2/:  python -m pytest tests"""

import numpy as np
import pytest

from sv import config
from sv.presets import cloud, rain
from sv.world import World


def make_world(seed=1, pw=200, ph=160, cell=2):
    return World(pw, ph, cell, seed=seed)


def check_consistent(w):
    assert (w.quad.sum(axis=1)[w.mass > 0] == w.mass[w.mass > 0]).all(), "children must sum to mass"
    assert w.mass.max() <= config.MAX_MASS


def run(w, ticks):
    for _ in range(ticks):
        w.step()


def test_mass_conserved_with_merge_and_split():
    w = make_world()
    w.merge_on = w.split_on = True
    w.add_well(100, 80, 400.0)            # strong well: fast impacts, so splits really happen
    rng = np.random.default_rng(0)
    w.place_many(rng.integers(0, w.w, 3000), rng.integers(0, w.h, 3000), rng.choice([1, 4, 16], 3000))
    m0, n0 = w.total_mass(), w.particle_count()
    merges = splits = 0
    for _ in range(400):
        w.step()
        merges += w.stats[2]
        splits += w.stats[3]
    check_consistent(w)
    assert merges > 0 and splits > 0
    assert w.total_mass() == m0
    assert w.particle_count() == n0 - merges + splits


def test_particle_count_stable_without_merge_split():
    w = make_world()
    rain(w)
    n0 = w.particle_count()
    run(w, 200)
    assert w.particle_count() == n0
    check_consistent(w)


def test_pile_falls_asleep():
    w = make_world()
    w.set_gravity(0)
    rng = np.random.default_rng(0)
    w.place_many(rng.integers(0, w.w, 3000), rng.integers(0, w.h // 2, 3000), 1)
    run(w, 400)
    assert w.awake_count() == 0


def test_heavy_sinks_below_light():
    w = make_world()
    w.set_gravity(0)
    # a layer of heavy particles resting on top of a thicker layer of light ones
    xs, ys = np.meshgrid(np.arange(w.w), np.arange(w.h - 30, w.h))
    w.place_many(xs.ravel(), ys.ravel(), 1)
    xs, ys = np.meshgrid(np.arange(w.w), np.arange(w.h - 40, w.h - 30))
    w.place_many(xs.ravel(), ys.ravel(), 16)
    before = mean_depth(w, 16)
    run(w, 600)
    assert mean_depth(w, 16) > before + 8


def mean_depth(w, m):
    return (np.nonzero(w.mass == m)[0] // w.w).mean()


def test_seeded_runs_are_deterministic():
    states = []
    for _ in range(2):
        w = make_world(seed=7)
        cloud(w)
        run(w, 100)
        states.append((w.mass.copy(), w.kin.copy()))
    assert (states[0][0] == states[1][0]).all()
    assert (states[0][1] == states[1][1]).all()


def test_well_pulls_particle_in():
    w = make_world()
    w.add_well(100, 80, config.WELL_STRENGTH)
    w.place_many([10], [40], [1])
    closest = 40.0
    for _ in range(150):                  # it falls through the well and swings out again: track the closest pass
        w.step()
        i = np.nonzero(w.mass)[0][0]
        closest = min(closest, np.hypot(i % w.w - 50, i // w.w - 40))
    assert closest < 5


def test_circular_orbit_holds():
    w = World(400, 400, 2, seed=1)
    strength = 180.0
    w.add_well(200, 200, strength)
    r = 60.0
    soft = config.WELL_SOFTENING
    v = np.sqrt(strength * r * r / (r * r + soft * soft) ** 1.5)
    w.place_many([100 + r], [100], [1], [0.0], [v])
    for _ in range(600):
        w.step()
        i = np.nonzero(w.mass)[0][0]
        assert abs(np.hypot(i % w.w - 100, i // w.w - 100) - r) < 4


@pytest.mark.parametrize("cell", [1, 4])
def test_set_cell_resamples(cell):
    w = make_world()
    rain(w)
    w.set_cell(cell)
    assert w.w == 200 // cell
    check_consistent(w)
    run(w, 5)
