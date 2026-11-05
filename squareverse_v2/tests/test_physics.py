"""Physics invariants of the v2 engine. Run from squareverse_v2/:  python -m pytest tests"""

import math

import numpy as np
import pytest

from sv import config, kernels
from sv.gravity import fade
from sv.presets import cloud, rain
from sv.world import World


def make_world(seed=1, pw=200, ph=160, cell=2):
    w = World(pw, ph, cell, seed=seed)
    w.collapse_on = False                 # tests that need collapse switch it on themselves
    return w


def check_consistent(w):
    assert (w.quad.sum(axis=1)[w.mass > 0] == w.mass[w.mass > 0]).all(), "children must sum to mass"
    assert w.mass.max() <= config.MAX_MASS


def dense_patch(w, x0=40, y0=30, factor=1.3):
    """A 15 x 15 block of particles of one rung, as near `factor` x as dense as puts it inside its own horizon (it
    collapses at 1: World.collapse_check) as rungs allow - rounded up over 1, down under it. Returns its mass."""
    xs, ys = np.meshgrid(np.arange(x0, x0 + 15), np.arange(y0, y0 + 15))
    rings = np.bincount(np.hypot(xs - x0 - 7, ys - y0 - 7).astype(np.int64).ravel())
    _, one = w.collapse_check(x0 + 7, y0 + 7, rings)          # how near a block of mass-1 particles comes
    k = math.log2(factor / one)
    m = int(min(config.MAX_MASS, 2 ** (math.ceil(k) if factor >= 1 else math.floor(k))))
    w.place_many(xs.ravel(), ys.ravel(), m)
    return 225 * m


def run(w, ticks):
    for _ in range(ticks):
        w.step()


def test_mass_conserved_with_merge_and_split():
    w = make_world()
    w.merge_on = w.split_on = True
    w.add_well(100, 80, 200000.0)         # heavy well: fast impacts, so splits really happen
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
    w.merge_on = w.split_on = False
    n0 = w.particle_count()
    run(w, 200)
    assert w.particle_count() == n0
    check_consistent(w)


def test_pile_falls_asleep():
    w = make_world()
    w.set_gravity(0)
    rng = np.random.default_rng(0)
    w.place_many(rng.integers(0, w.w, 3000), rng.integers(0, w.h // 2, 3000), 1)
    run(w, 800)                           # merged grains sink through the light ones first
    assert w.awake_count() == 0


def test_heavy_sinks_below_light():
    w = make_world()
    w.merge_on = w.split_on = False
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
    w.add_well(100, 80, 30000.0)
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
    w.add_well(200, 200, strength / config.G)
    r = 60.0
    rho = math.hypot(r, config.WELL_SOFTENING)
    v = np.sqrt(strength * r * r / rho ** 3 * fade(rho, w.kinv)[0])
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


def test_resize_keeps_scene_centred_and_moves_wells():
    w = make_world()
    w.add_well(100, 80, 50.0)
    w.place_many([50], [40], [7])
    w.resize(300, 240)                    # grow by 100 x 80 px = 50 x 40 cells, no gravity: centred
    assert (w.w, w.h) == (150, 120)
    i = np.nonzero(w.mass)[0]
    assert i.size == 1 and (i[0] % w.w, i[0] // w.w) == (75, 60) and w.mass[i[0]] == 7
    assert (w.wells[0].x, w.wells[0].y) == (75.0, 60.0)
    w.resize(200, 160)
    assert np.nonzero(w.mass)[0].tolist() == [40 * w.w + 50]
    run(w, 5)


def test_resize_pins_scene_to_gravity_side():
    w = make_world()
    w.set_gravity(0)                      # down: the floor stays at the bottom edge
    w.place_many([10], [w.h - 1], [1])
    w.resize(200, 260)
    i = np.nonzero(w.mass)[0][0]
    assert (i % w.w, i // w.w) == (10, w.h - 1)


def test_random_mass_brush():
    w = make_world()
    for _ in range(20):
        w.brush(100, 80, 40, (3, 9))
    masses = w.mass[w.mass > 0]
    assert masses.size > 200
    assert set(np.unique(masses)) == {4, 8}          # the rungs in the range (masses come in rungs)
    check_consistent(w)


def test_sized_well_weighs_its_brush_area_and_is_as_big_as_its_mass():
    w = make_world()                      # 2 px cells
    small = w.add_sized_well(100, 80, 24)
    big = w.add_sized_well(100, 80, 48, pour_mass=64)
    ranged = w.add_sized_well(100, 80, 24, pour_mass=(1, 9))
    assert small.radius == pytest.approx(12) and w.well_radius_px(small) == pytest.approx(24)   # pour 1: the brush
    assert small.mass == pytest.approx(np.pi * 144 * config.WELL_DENSITY)
    assert big.mass == pytest.approx(small.mass * 4 * 64)
    assert ranged.mass == pytest.approx(small.mass * 5)   # a pour range counts as its middle
    assert big.radius == pytest.approx(24 * 8)            # 64x heavier per area: 8x wider (size follows mass)
    assert small.pull() == pytest.approx(config.G * small.mass)


def test_super_well_swallows_particles_and_conserves_mass():
    w = make_world()
    w.merge_on = w.split_on = False
    w.add_super_well(100, 80, 50000)
    rng = np.random.default_rng(0)
    w.place_many(rng.integers(30, 70, 300), rng.integers(20, 60, 300), rng.choice([1, 4], 300))
    before = w.total_mass() + w.super_mass()
    run(w, 400)
    assert w.super_mass() > 50000
    assert w.total_mass() + w.super_mass() == before
    assert not w.mass[w.hole > 0].any()       # nothing sits inside the core


def test_collapse_on_by_default():
    assert World(200, 160, 2).collapse_on


def test_the_lightest_super_well_follows_gravity_scale():
    w = make_world()
    t = w.lightest_super_mass()
    w.scale_gravity(2.0)
    assert w.lightest_super_mass() == pytest.approx(t / 2)   # (twice the pull: half the mass for the same horizon)
    w.add_super_well(50, 50)
    assert w.wells[0].mass == pytest.approx(t / 2)


def test_dense_mass_collapses_into_super_well():
    w = make_world()
    w.merge_on = w.split_on = False
    w.collapse_on = True
    before = dense_patch(w)
    run(w, config.COLLAPSE_EVERY)
    supers = [wl for wl in w.wells if wl.is_super]
    assert len(supers) == 1 and abs(supers[0].x - 47) < 3 and abs(supers[0].y - 37) < 3
    assert w.total_mass() + w.super_mass() == before


def test_no_collapse_below_threshold_or_when_off():
    w = make_world()
    w.collapse_on = True
    dense_patch(w, factor=0.8)                      # below the threshold
    run(w, config.COLLAPSE_EVERY)
    assert not w.wells
    w.collapse_on = False
    dense_patch(w, x0=70)
    run(w, config.COLLAPSE_EVERY)
    assert not w.wells


def test_wells_attract_each_other():
    w = make_world(pw=400, ph=200)
    a = w.add_well(100, 100, 30000.0)
    b = w.add_well(300, 100, 30000.0)
    run(w, 100)
    assert a.vx > 0 and b.vx < 0
    assert b.x - a.x < 100 - 5           # they started 100 cells apart


def test_every_well_falls_alike_whatever_its_mass():
    moved = {}
    for kind, mass in (("star", 5000.0), ("star", 500000.0), ("super", 50000.0), ("super", 500000.0)):
        w = make_world(pw=400, ph=200)
        w.held = w.add_well(200, 100, 300000.0)        # the same pull for all, held in place
        if kind == "star":
            probe = w.add_well(100, 100, mass)
        else:
            probe = w.add_super_well(60, 100, mass)    # its range must not reach the other (that would merge)
        x0 = probe.x
        run(w, 15)
        moved[kind, mass] = probe.x - x0
    assert moved["star", 5000.0] > 0
    assert moved["star", 5000.0] == pytest.approx(moved["star", 500000.0], rel=0.05)      # free fall
    for mass in (50000.0, 500000.0):                 # super wells too: the whole pull, whatever their mass (each
        w = make_world(pw=400, ph=200)               # pair softened over the larger of the two, so the pulls are
        held = w.held = w.add_well(200, 100, 300000.0)   # equal and opposite)
        probe = w.add_super_well(60, 100, mass)
        soft = max(w.softening(probe), w.softening(held))
        d = held.x - probe.x
        rho = math.hypot(d, soft)
        w.step()
        assert probe.vx == pytest.approx(w.g_scale * held.pull() * d / rho ** 3 * fade(rho, w.kinv)[0], rel=1e-6)


def test_solid_well_can_orbit_a_super_well():
    w = make_world(pw=1600, ph=1200)
    sw = w.add_super_well(800, 600, 400000)
    d = 0.9 * w.reach_len                            # within the reach (past ~1.16 of it no circular orbit is stable)
    star = w.add_well(800 + 2 * d, 600, 200000.0, radius=8)
    star.vx, star.vy = w.orbit_velocity(sw, star.x, star.y, star.mass)   # a circular two-body orbit: the super well
    w.put_in_orbit(sw, star.mass, star.vx - sw.vx, star.vy - sw.vy)      # (as free as it) takes the recoil
    angles = []
    for _ in range(400):
        w.step()
        dx, dy = w.delta(sw.x, sw.y, star.x, star.y)
        assert 0.8 * d < math.hypot(dx, dy) < 1.2 * d                   # stays in orbit...
        angles.append(math.atan2(dy, dx))
    assert np.abs(np.diff(np.unwrap(angles))).sum() > 2 * math.pi        # ...and goes round at least once


def test_repulsors_stay_put():
    w = make_world(pw=400, ph=200)
    rep = w.add_well(200, 100, 30000.0, sign=-1)
    w.add_well(150, 100, 30000.0)
    run(w, 50)
    assert (rep.x, rep.y) == (100.0, 50.0)


def test_super_well_swallows_wells():
    w = make_world(pw=400, ph=200)
    sw = w.add_super_well(200, 100, 100000)
    w.add_well(160, 100, 2000.0)
    other = w.add_super_well(250, 100, 6000)
    sw.spin = other.spin = 1.0                       # faster spin would fling the well into orbit
    run(w, 300)
    assert w.wells == [sw]
    assert sw.mass + w.total_mass() == pytest.approx(108000)   # the super well merger spat some out as particles


def test_wells_feel_particles_with_self_gravity():
    w = make_world(pw=400, ph=200)
    w.sg_on = True
    xs, ys = np.meshgrid(np.arange(150, 190), np.arange(30, 70))
    w.place_many(xs.ravel(), ys.ravel(), 64)
    wl = w.add_well(100, 100, 1000.0)
    run(w, 40)
    assert wl.vx > 0
    w2 = make_world(pw=400, ph=200)       # without self-gravity, particles don't pull wells
    w2.star_form_on = False               # (heavy enough to ignite, the block would become a star, which does)
    w2.place_many(xs.ravel(), ys.ravel(), 64)
    wl2 = w2.add_well(100, 100, 1000.0)
    run(w2, 40)
    assert wl2.vx == 0


def test_collapse_keeps_momentum():
    w = make_world()
    w.merge_on = w.split_on = False
    w.collapse_on = True
    dense_patch(w)
    w.kin[w.mass > 0, 1] = 0.3                      # the whole patch drifting down at 0.3
    run(w, config.COLLAPSE_EVERY)
    sw = [wl for wl in w.wells if wl.is_super][0]
    assert sw.vy == pytest.approx(0.3, abs=0.1) and abs(sw.vx) < 0.05


def overlapping_pair(w, m1, m2, overlap=0.9):
    """Two super wells whose ranges just overlap (their gap `overlap` x their ranges added up), at rest."""
    a = w.add_super_well(200, 200, m1)
    b = w.add_super_well(200, 200, m2)
    b.x += overlap * (w.well_range(a) + w.well_range(b))
    b.built = (b.x, b.y, b.mass)
    return a, b


def test_unequal_pairs_radiate_less():
    def radiated(m2):
        w = make_world(pw=600, ph=400)
        w.radiation_on = True
        a, b = overlapping_pair(w, 400000, m2)
        sent, radiate = [], w._radiate_waves
        w._radiate_waves = lambda *args: sent.append(radiate(*args)) or sent[-1]
        run(w, 800)
        assert len(w.wells) == 1
        return sum(sent) / (400000 + m2)
    assert radiated(100000) < 0.75 * radiated(400000)  # ~ 4 m1 m2 / M^2


def test_far_apart_super_wells_dont_merge():
    w = make_world(pw=1600, ph=400)
    a = w.add_super_well(100, 200, 10000)
    b = w.add_super_well(1500, 200, 10000)
    assert math.hypot(a.x - b.x, a.y - b.y) > w.well_range(a) + w.well_range(b)
    run(w, 60)
    assert len(w.wells) == 2


def test_collapse_takes_all_that_is_inside_its_horizon():
    w = make_world()
    w.merge_on = w.split_on = False
    w.collapse_on = True
    total = dense_patch(w)
    run(w, config.COLLAPSE_EVERY)
    sw = w.wells[0]
    assert sw.mass == total and w.total_mass() == 0  # all of it, nothing thrown out
    assert w.horizon(sw) >= 7 > sw.core()            # matter can't get away from round it; light only from closer


@pytest.mark.xfail(reason="physics rework step 6: ejection is only left for scripted mergers; a light well's ejecta collide in its tight launch ring under the point-mass pull", strict=False)
@pytest.mark.parametrize("mass", [40000, 400000])
def test_ejected_mass_escapes_the_range(mass):
    w = World(1600, 1600, 2, seed=3)                # 800 x 800 cells: room to leave the range
    w.collapse_on = w.merge_on = w.split_on = False
    sw = w.add_super_well(800, 800, mass)
    w.rebuild_field()
    ejected = w.eject(sw, mass * 0.05)
    reach = w.well_range(sw)
    assert ejected > 0
    run(w, 150)                                     # out of range, before any can bounce back off a wall
    idx = np.nonzero(w.mass)[0]
    r = np.hypot(idx % w.w - sw.x, idx // w.w - sw.y)
    assert w.mass[idx][r > reach].sum() >= 0.9 * ejected   # nearly all got out (a few may collide)


def test_solid_well_pushes_particles_out_and_stays_solid():
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False
    xs, ys = np.meshgrid(np.arange(80, 120), np.arange(80, 120))
    w.place_many(xs.ravel(), ys.ravel(), 4)          # a block of particles where the star will be
    before, count = w.total_mass(), w.particle_count()
    star = w.add_sized_well(200, 200, 24)          # radius 12 cells at (100, 100)
    run(w, 1)
    assert w.total_mass() == before and w.particle_count() == count
    assert not w.mass[w.solid > 0].any()
    assert np.count_nonzero(w.solid) > 400
    run(w, 300)
    assert not w.mass[w.solid > 0].any()           # nothing ever gets inside
    idx = np.nonzero(w.mass)[0]
    r = np.hypot(idx % w.w - star.x, idx // w.w - star.y)
    assert np.median(r) < star.radius + 25       # they settle on the surface as a crust


def test_solid_well_ground_holds_particles_up():
    w = make_world(pw=400, ph=400)
    w.add_sized_well(200, 200, 24)
    w.place_many([100], [40], [1])                   # falls straight onto the star from above
    run(w, 300)
    i = np.nonzero(w.mass)[0][0]
    assert 11 <= np.hypot(i % w.w - 100, i // w.w - 100) <= 15


@pytest.mark.parametrize("direction", [1, -1])
def test_global_orbit_spins_the_universe(direction):
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False
    a = np.linspace(0, 2 * np.pi, 60, endpoint=False)
    w.place_many(np.round(100 + 60 * np.cos(a)), np.round(100 + 60 * np.sin(a)), 1)
    w.set_orbit(direction)
    run(w, 300)
    idx = np.nonzero(w.mass)[0]
    rx, ry = idx % w.w - w.w / 2, idx // w.w - w.h / 2
    r = np.hypot(rx, ry)
    tangential = (rx * w.kin[idx, 1] - ry * w.kin[idx, 0]) / r     # > 0 clockwise on screen (y points down)
    target = np.hypot(w.orbit_speed * 60, config.ORBIT_MIN_SPEED)
    assert np.median(tangential) == pytest.approx(direction * target, rel=0.3)
    assert 45 < np.median(r) < 75                    # still roughly on its circle


def test_global_orbit_carries_wells():
    w = make_world(pw=400, ph=400)
    wl = w.add_well(300, 200, 1000.0)                # 50 cells right of the centre
    w.set_orbit(1)
    w.orbit_speed = 0.005                            # slow enough that it doesn't get halfway round
    run(w, 100)
    assert wl.vy > 0                                 # clockwise on screen: right of centre moves down


def test_wrap_carries_particles_across_the_border():
    w = make_world()
    w.set_wrap(True)
    w.place_many([1], [40], [1], [-1.0], [0.0])      # heading out through the left edge
    run(w, 5)
    i = np.nonzero(w.mass)[0][0]
    assert i % w.w > w.w - 6 and i // w.w == 40      # came back in on the right, same row
    assert w.kin[i, 0] == pytest.approx(-1.0)


def test_without_wrap_the_border_is_a_wall():
    w = make_world()
    w.place_many([1], [40], [1], [-1.0], [0.0])
    run(w, 5)
    i = np.nonzero(w.mass)[0][0]
    assert i % w.w < 5


def test_wrap_falls_through_the_floor_to_the_top():
    w = make_world()
    w.set_wrap(True)
    w.set_gravity(0)
    w.place_many([50], [w.h - 2], [1], [0.0], [1.0])
    run(w, 4)
    i = np.nonzero(w.mass)[0][0]
    assert i // w.w < 10


def test_wrap_wells_pull_across_the_seam():
    w = make_world()
    w.set_wrap(True)
    w.add_well((w.w - 3) * w.cell, 40 * w.cell, 30000.0, radius=1.0)
    w.held = w.wells[0]
    w.rebuild_field()
    assert w.fx[40 * w.w + 2] < 0                    # 5 cells away round the left edge, not 95 to the right
    w.set_wrap(False)
    w.rebuild_field()
    assert w.fx[40 * w.w + 2] > 0


def test_wrap_solid_well_spans_the_edge_and_wells_cross_it():
    w = make_world()
    w.set_wrap(True)
    w.add_well(0, 80, 1000.0, radius=6.0)            # centred on the left edge
    w.rebuild_field()
    row = w.solid.reshape(w.h, w.w)[40]
    assert row[0] and row[w.w - 3] and not row[w.w // 2]
    mover = w.add_well(198, 40, 10.0, vx=1.0)       # cell x = 99, moving right
    w.held = w.wells[0]
    run(w, 3)
    assert mover.x < 5


def test_wrap_self_gravity_is_periodic():
    w = make_world()
    w.set_wrap(True)
    w.sg_on = True
    xs, ys = np.meshgrid(np.arange(0, 8), np.arange(36, 44))
    w.place_many(xs.ravel(), ys.ravel(), 256)        # a lump at the left edge
    w.sg.update(w.mass, w.sg_g)
    sg = w.sg
    b = (40 // sg.block) * sg.cw + (w.w - 6) // sg.block   # just left of the right edge
    assert sg.gx[b] > 0                              # pulled right, across the seam towards the lump


def test_spawner_rate_scales_with_its_circle():
    counts = []
    for radius_px in (12, 24):
        w = make_world(pw=400, ph=400)
        w.merge_on = w.split_on = False
        sp = w.add_spawner(200, 200, radius_px, locked=True)
        run(w, 100)
        counts.append(w.particle_count() + w.ghost_count())
        assert counts[-1] == pytest.approx(100 * sp.rate, rel=0.25)
    assert counts[1] == pytest.approx(4 * counts[0], rel=0.3)


def test_spawner_falls_through_everything_under_gravity():
    w = make_world(pw=400, ph=400)
    w.set_gravity(0)
    w.add_sized_well(200, 300, 30)                   # a star in the way
    sp = w.add_spawner(200, 40, 8)
    run(w, 40)
    assert sp.y > 150 and sp.vy > 0                  # fell straight through the star (radius 15 at y = 150)


def test_locked_spawner_stays_put():
    w = make_world(pw=400, ph=400)
    w.set_gravity(0)
    w.add_well(300, 200, 100000.0)
    sp = w.add_spawner(100, 100, 8, locked=True)
    run(w, 40)
    assert (sp.x, sp.y, sp.vx, sp.vy) == (50.0, 50.0, 0.0, 0.0)
    assert w.ghost_count() > 0


def test_super_well_deletes_spawner():
    w = make_world(pw=400, ph=400)
    w.add_super_well(200, 200, 200000).spin = 0       # no spin: it falls straight in
    w.add_spawner(260, 200, 4)
    run(w, 100)
    assert not w.spawners
    n = w.particle_count() + w.ghost_count()
    run(w, 20)
    assert w.particle_count() + w.ghost_count() <= n   # nothing new pours in


def test_spawner_random_masses():
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False
    w.add_spawner(200, 200, 30, pour_mass=(2, 9), locked=True)
    run(w, 30)
    assert set(np.unique(w.ghost_m)) == {2, 4, 8}    # the rungs in the range


def test_merge_losses_fall_mostly_on_the_smaller_well():
    from sv.world import merge_losses
    big, small = merge_losses(100000, 50000, 3000)
    assert big + small == pytest.approx(3000)
    assert big == pytest.approx(small / 2)          # half the size -> twice the loss
    eq_big, eq_small = merge_losses(100000, 50000, 3000, bias=0)
    assert eq_big == pytest.approx(eq_small)
    pr_big, pr_small = merge_losses(100000, 50000, 3000, bias=-1)
    assert pr_big == pytest.approx(2 * pr_small)
    tiny_big, tiny_small = merge_losses(100000, 500, 3000)   # the small one can't cover its share
    assert tiny_small == pytest.approx(500) and tiny_big == pytest.approx(2500)


def test_super_merge_takes_more_from_the_smaller_well():
    w = make_world(pw=600, ph=400)
    a, b = overlapping_pair(w, 480000, 240000)
    run(w, 800)
    assert w.wells == [a] and w.universe_mass() == 720000


def test_new_super_wells_spin_either_way_without_the_global_orbit():
    w = make_world()
    assert not w.orbit
    ways = {np.sign(w.add_super_well(100, 80, 50000).spin) for _ in range(40)}
    assert ways == {-1.0, 1.0}


def test_disk_preset_settings_and_presets_reset_them():
    from sv.presets import disk, rain
    w = make_world(pw=400, ph=300)
    w.set_reach(20)
    w.set_gravity_scale(0.6)
    disk(w)
    assert not w.wells and w.orbit == 1 and w.sg_on and w.g_scale == config.GRAVITY_SCALE
    assert w.reach_len == config.GRAVITY_REACH       # every preset runs at the default reach and strength
    assert w.round and not w.wrap and (w.w, w.h) == (250, 250)    # a disc through the 200 x 150 window's corners
    assert w.particle_count() > 1000
    rain(w)
    assert not w.round and (w.w, w.h) == (200, 150)
    assert w.orbit == config.ORBIT and w.wrap == config.WRAP and w.g_scale == config.GRAVITY_SCALE
    assert w.reach_len == config.GRAVITY_REACH


def test_round_universe_keeps_orbiting_matter_on_its_circle():
    """Carried out of the window by the global orbit, a particle goes on round its circle off-screen and comes back in
    on the far side - never jumping across a border - instead of reappearing on the opposite edge going the wrong
    way. (A lone free particle slowly sinks inwards in the orbit, round or not, so it is slow and the circle loose.)"""
    w = make_world(pw=400, ph=300)                  # a 200 x 150 cell window
    w.merge_on = w.split_on = False
    w.set_round(True)
    w.set_orbit(1)
    w.set_orbit_edge_speed(2.0)
    cx, cy = w.w / 2, w.h / 2
    w.place_many([round(cx)], [round(cy - 110)], [1], [w.orbit_speed * 110], [0.0])   # 110 cells out: off-screen
    path = []                                                                        # above and below the window
    for _ in range(300):
        w.step()
        i = np.nonzero(w.mass)[0]
        assert i.size == 1
        path.append((i[0] % w.w - cx, i[0] // w.w - cy))
    radii = [math.hypot(x, y) for x, y in path]
    assert max(abs(r - 110) for r in radii) < 15
    steps = [math.hypot(x1 - x0, y1 - y0) for (x0, y0), (x1, y1) in zip(path, path[1:])]
    assert max(steps) <= config.VMAX + 1                                             # no teleporting
    outside = [abs(y) > w.vh / 2 for _, y in path]
    assert sum(a != b for a, b in zip(outside, outside[1:])) >= 3   # out of the window, back in, out again...
    assert any(y < -w.vh / 2 for _, y in path) and any(y > w.vh / 2 for _, y in path)


def test_round_rim_is_solid_ground_turning_with_the_orbit():
    w = make_world(pw=400, ph=300)
    w.set_round(True)
    w.set_orbit(1)
    corner = 2 * w.w + 2                            # (2, 2): outside the disc
    assert w.solid[corner] and not w.solid[(w.h // 2) * w.w + w.w // 2]
    vx, vy = kernels.orbit_flow(2 - w.w / 2, 2 - w.h / 2, w.orbit_speed, config.ORBIT_MIN_SPEED)
    assert w.gvx[corner] == pytest.approx(vx, rel=1e-4) and w.gvy[corner] == pytest.approx(vy, rel=1e-4)
    w.brush(4, 4, 6, 1)                             # pouring into the rim places nothing
    assert w.particle_count() == 0
    w.set_orbit(0)
    assert w.gvx[corner] == 0.0 and w.gvy[corner] == 0.0
    w.rebuild_field()                               # rebuilding the wells' ground keeps the rim
    assert w.solid[corner]


def test_round_and_wrap_exclude_each_other():
    w = make_world(pw=400, ph=300)
    w.set_wrap(True)
    w.place_many([100], [75], [16])
    w.set_round(True)
    assert w.round and not w.wrap and (w.w, w.h) == (250, 250)
    assert w.mass[125 * w.w + 125] == 16            # the scene stays centred
    w.set_wrap(True)
    assert w.wrap and not w.round and (w.w, w.h) == (200, 150) and w.mass[75 * w.w + 100] == 16


def test_round_universe_keeps_wells_inside_the_rim():
    w = make_world(pw=400, ph=300)
    w.set_round(True)
    sw = w.add_super_well(10, 10, 50000)            # in the corner, outside the disc
    w.step()
    assert math.hypot(sw.x - w.w / 2, sw.y - w.h / 2) <= w.w / 2


def test_orbit_speed_is_set_at_the_window_edge():
    w = make_world(pw=400, ph=300)
    w.set_orbit_edge_speed(3.0)
    before = w.orbit_speed
    w.set_round(True)                               # a bigger universe turns just as fast
    assert w.orbit_speed == pytest.approx(before) and w.orbit_edge_speed() == pytest.approx(3.0)


def test_universe_mass_counts_particles_ghosts_and_super_wells():
    w = make_world()
    w.place_many([10, 20], [10, 20], [4, 16])
    w.add_ghosts(np.array([50.0]), np.array([50.0]), np.array([64]))
    w.add_super_well(150, 100, 1000)
    assert w.universe_mass() == 4 + 16 + 64 + 1000


def test_camera_maps_window_and_universe_both_ways():
    from sv.render import Camera
    w = make_world(pw=400, ph=300)
    w.set_round(True)
    cam = Camera()
    cam.update(w, (400, 300))
    assert cam.to_world(200, 150) == pytest.approx((250.0, 250.0))   # 1x: the window's centre is the universe's
    assert cam.point(*(c / w.cell for c in cam.to_world(37, 211))) == pytest.approx((37, 211))
    cam.zoom_at(0.5, 100, 80)
    assert cam.zoom == pytest.approx(cam.min_zoom()) == pytest.approx(300 / 500)   # no further out than it all fits
    cam.reset()
    before = cam.to_world(300, 100)
    cam.zoom_at(2.0, 300, 100)                      # the point under the mouse stays put
    assert cam.to_world(300, 100) == pytest.approx(before)
    cam.pan(10_000, 0)                              # never past the universe's edge
    assert cam.to_world(0, 0)[0] == pytest.approx(0.0)


def test_super_well_pulls_beyond_its_dotted_circle():
    w = make_world(pw=800, ph=400)
    w.merge_on = w.split_on = w.collapse_on = False
    sw = w.add_super_well(200, 200, 100000)
    w.held = sw
    w.rebuild_field()
    start = 100 + 60                                 # far past its point of no return (cells)
    assert start > 100 + 3 * w.horizon(sw)
    w.place_many([round(start)], [100], [1])
    run(w, 15)
    i = np.nonzero(w.mass)[0][0]
    assert i % w.w < start - 3                       # pulled in by the inverse-square law


@pytest.mark.parametrize("omega", [0.0, 0.02, -0.02])
def test_spinning_solid_well_carries_its_crust(omega):
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = w.collapse_on = False
    star = w.add_well(200, 200, 200000.0, radius=20.0)
    star.omega = omega
    w.held = star                                  # keep it in place
    a = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    w.place_many(np.round(100 + 22 * np.cos(a)), np.round(100 + 22 * np.sin(a)), 1)   # a ring on its surface
    run(w, 100)
    idx = np.nonzero(w.mass)[0]
    rx, ry = idx % w.w - 100.0, idx // w.w - 100.0
    spin = np.mean((rx * w.kin[idx, 1] - ry * w.kin[idx, 0]) / (rx * rx + ry * ry))   # rad/tick, > 0 clockwise
    assert np.all(np.hypot(rx, ry) < 26)             # still lying on the surface
    if omega == 0:
        assert abs(spin) < 0.002
    else:
        assert spin == pytest.approx(omega, rel=0.4)    # carried round with the ground


def test_super_wells_spins_add_up_when_they_merge():
    w = make_world(pw=600, ph=400)
    a = w.add_super_well(200, 200, 480000)
    b = w.add_super_well(400, 200, 240000)
    a.spin, b.spin = 1.0, -1.0
    for _ in range(2000):
        w.step()
        if len(w.wells) == 1:
            break
    assert w.wells == [a] and 0 < a.spin < 0.5     # opposite spins partly cancel


def test_global_orbit_keeps_everything_moving_without_piling_in_the_middle(monkeypatch):
    monkeypatch.setattr(config, "STAR_FORM_ON", False)   # a star would sink to the middle: that's not the orbit
    w = make_world(pw=600, ph=600)
    w.merge_on = w.split_on = False
    rng = np.random.default_rng(0)
    n = int(w.n * 0.4)                               # a dense disc that fits inside the walls
    r = 140 * np.sqrt(rng.uniform(0, 1, n))
    a = rng.uniform(0, 2 * np.pi, n)
    w.place_many(np.round(150 + r * np.cos(a)), np.round(150 + r * np.sin(a)), rng.choice([1, 4, 16], n))
    w.set_orbit(1)
    w.orbit_speed = 0.005                            # (rad/tick) the default edge speed would spin this small disc fast
    run(w, 600)
    idx = np.nonzero(w.mass)[0]
    r = np.hypot(idx % w.w - w.w / 2, idx // w.w - w.h / 2)
    speed = np.hypot(w.kin[idx, 0], w.kin[idx, 1])
    assert (speed < 0.1).mean() < 0.05               # practically nothing at rest
    near = (30 / 140) ** 2                           # share of the disc within 30 cells of the centre
    assert (r < 30).mean() < 1.5 * near              # no pile in the middle


def test_super_well_spin_keys_scale_and_cap():
    w = make_world()
    sw = w.add_super_well(100, 80, 50000)
    w.set_spin(sw, -0.5)
    for _ in range(50):
        w.scale_spin(sw, config.SUPER_SPIN_STEP)
    assert sw.spin == pytest.approx(-config.SUPER_SPIN_MAX)   # faster, still counterclockwise, capped at the most
    assert sw.jz == pytest.approx(-w.max_spin_j(sw.mass))     # (the angular momentum it holds)
    for _ in range(100):
        w.scale_spin(sw, 1 / config.SUPER_SPIN_STEP)
    assert sw.spin == pytest.approx(-0.02)


@pytest.mark.parametrize("speed, expect", [(0.5, False), (config.VMAX * 0.9, True)])
def test_merge_and_split_only_in_fast_collisions(speed, expect):
    merges = splits = 0                              # (fusing and breaking get likelier the more energy: _tunnel)
    for seed in range(20):
        w = make_world(seed=seed)
        w.merge_on = w.split_on = True
        w.place_many([40, 50], [40, 40], [16, 16], [speed, 0.0], [0.0, 0.0])   # one flies into the other
        for _ in range(30):
            w.step()
            merges += w.stats[2]
            splits += w.stats[3]
    if expect:
        assert merges > 0 and splits > 0
    else:
        assert merges == 0 and splits == 0           # a slow touch just pushes


def test_super_well_explodes_past_the_threshold_and_releases_all_its_mass():
    w = make_world(pw=1200, ph=800)
    w.merge_on = w.split_on = False
    w.collapse_on = True
    sw = w.add_super_well(600, 400, config.SUPER_EXPLODE_MASS - 1000)
    w.place_many(np.arange(290, 310), np.full(20, 200), 100)     # 2,000 more falls in and tips it over
    before = sw.mass + w.total_mass()
    for _ in range(300):
        w.step()
        if w.explosions:
            break
    assert w.explosions == 1 and not any(wl.is_super for wl in w.wells)
    assert w.total_mass() + w.ghost_mass() == pytest.approx(before)   # every bit of it came back out as debris
    assert w.ghost_count() > 1000 and w.ghost_m.max() > 2000          # very heavy at first...
    run(w, 100)
    assert w.ghost_m.max() < 1500 and w.ghost_count() > 5000          # ...cooling into many lighter pieces
    assert w.total_mass() + w.ghost_mass() == pytest.approx(before)
    run(w, config.SUPER_EXPLODE_CALM - 100 - 20)
    assert not any(wl.is_super for wl in w.wells)    # the debris isn't collapsed straight back
    check_consistent(w)


def test_explosion_ring_starts_at_the_well_and_the_blast_pushes_particles_away(monkeypatch):
    monkeypatch.setattr(config, "SUPER_BLAST_COAST", 0.0)   # the debris stops with the front (coasting: below)
    w = make_world(pw=1200, ph=800)
    w.merge_on = w.split_on = False
    w.g_scale = 1e-9                                 # nothing else moves anything
    xs, ys = np.meshgrid(np.arange(600), np.arange(400))
    xs, ys = xs.ravel(), ys.ravel()
    keep = w.rng.random(xs.size) < 0.25
    w.place_many(xs[keep], ys[keep], 4)
    w.add_super_well(600, 400, config.SUPER_EXPLODE_MASS + 10).heavy = True   # cell (300, 200); its grace over
    w.step()
    assert w.explosions == 1
    d = np.hypot(w.ghost_x - 300, w.ghost_y - 200)
    assert d.max() < 15                              # the ring comes from where the well was
    r = np.hypot(xs - 300, ys - 200)
    dust = lambda lim: int(((w.mass[ys * w.w + xs] > 0) & (r < lim)).sum())
    start = dust(40)
    run(w, 40)
    assert w.ghost_count() > 0                       # the debris is still flying...
    assert dust(40) < 0.1 * start                    # ...and the nearby dust has been shoved back out of the way
    reach = config.SUPER_BLAST_RADIUS * w.blast_scale(config.SUPER_EXPLODE_MASS + 10)
    assert dust(reach * 1.2) > 0.3 * dust(1e9)       # and not just thrown away
    run(w, 160)
    assert w.ghost_count() == 0                      # the debris has landed, spread over the swept area
    assert dust(40) > 0.5 * start
    check_consistent(w)


def test_blast_debris_lands_where_it_comes_to_rest(monkeypatch):
    monkeypatch.setattr(config, "SUPER_BLAST_COAST", 0.0)   # the debris stops with the front (coasting: below)
    w = make_world(pw=1200, ph=800)
    w.merge_on = w.split_on = False
    w.g_scale = 1e-9                                 # nothing else moves anything
    rng = np.random.default_rng(1)
    n = w.w * w.h // 5
    w.place_many(rng.integers(0, w.w, n), rng.integers(0, w.h, n), 4)
    w.add_super_well(600, 400, config.SUPER_EXPLODE_MASS + 10).heavy = True   # its grace already over
    run(w, 200)
    assert w.ghost_count() == 0
    # the debris is spread over the blast area rather than piled on its rim: its particles fill the inside too
    yy, xx = np.nonzero(w.mass.reshape(w.h, w.w) > 4)  # debris pieces are heavier than the dust
    r = np.hypot(xx - 300, yy - 200)
    reach = min(config.SUPER_BLAST_RADIUS * w.blast_scale(config.SUPER_EXPLODE_MASS + 10), 0.45 * min(w.w, w.h))
    assert np.mean(r < 0.5 * reach) > 0.15
    assert np.mean(r > 1.1 * reach) < 0.02           # nothing thrown far out to find room


def test_blast_debris_flies_on_past_the_front_slowing_smoothly_and_stops_short_of_the_edge():
    w = make_world(pw=1200, ph=800)                  # 600 x 400 cells, walled
    w.merge_on = w.split_on = False
    w.g_scale = 1e-9                                 # nothing else moves anything
    w.add_super_well(600, 400, config.SUPER_EXPLODE_MASS + 10).heavy = True   # cell (300, 200); its grace over
    reach = min(config.SUPER_BLAST_RADIUS * w.blast_scale(config.SUPER_EXPLODE_MASS + 10), 0.45 * min(w.w, w.h))
    speeds, stopped = [], None
    for t in range(600):
        w.step()
        if not w.blasts:                             # its debris's edge has come to rest
            break
        assert int((w.mass > 0).sum()) == 0          # none of it lands while it flies
        side = np.abs(w.ghost_y - 200) < 0.3 * np.abs(w.ghost_x - 300)   # along x, where there is room
        speeds.append(np.median(np.hypot(w.ghost_vx[side], w.ghost_vy[side])))
        if stopped is None and w.blasts[0].r >= reach:
            stopped = t
    run(w, 40)                                       # the last few pieces cool and land
    assert w.ghost_count() == 0                      # all landed once it had come to rest
    assert stopped is not None and len(speeds) > stopped + 30   # it flew on well after the front stopped ...
    s = np.array(speeds[2:])
    assert (np.diff(s) <= 1e-6 + 0.02 * s[:-1]).all()   # ... only ever slowing, never stalling and speeding up again
    assert s[stopped - 2] > 0.25 * s[0]              # still moving briskly when the front stopped
    yy, xx = np.nonzero(w.mass.reshape(w.h, w.w) > 0)
    dx, dy = xx - 300, yy - 200
    r = np.hypot(dx, dy)
    side = np.abs(dy) < 0.3 * np.abs(dx)             # along x there is room to coast; along y the walls are close
    assert np.percentile(r[side], 99) > 1.3 * reach  # it went on well past where the front stopped ...
    assert np.mean(r < 0.5 * reach) > 0.03           # ... still filling the inside, not all thrown to the edge
    margin = 2                                       # none piled against the walls
    assert xx.min() >= margin and yy.min() >= margin and xx.max() <= w.w - 1 - margin and yy.max() <= w.h - 1 - margin
    check_consistent(w)


def test_ghosts_pass_through_particles_and_land_after_their_time():
    w = make_world()
    w.merge_on = w.split_on = False
    w.set_gravity(0)                                 # down
    xs, ys = np.meshgrid(np.arange(30, 70), np.arange(50, 60))
    w.place_many(xs.ravel(), ys.ravel(), 4)          # a slab in the way
    w.pour_ghosts(100, 40, 10, 16)                   # above it (pixels: cell 2)
    n_ghosts, ghost_mass, mass0 = w.ghost_count(), w.ghost_mass(), w.total_mass()
    assert n_ghosts > 0 and w.total_mass() == mass0  # ghosts aren't on the grid
    run(w, 40)
    assert (w.ghost_y > 60).any()                    # fallen through the slab
    run(w, config.GHOST_TICKS)
    assert w.ghost_count() == 0                      # landed
    assert w.total_mass() == mass0 + ghost_mass
    check_consistent(w)


def test_ghosts_dont_attract_each_other_or_collapse():
    w = make_world(pw=400, ph=320)
    w.sg_on = True
    w.collapse_on = True
    w.pour_ghosts(200, 160, 12, config.MAX_MASS)     # far more than the lightest super well, all in one spot
    assert w.ghost_mass() > 5 * w.lightest_super_mass()
    x0, y0 = w.ghost_x.copy(), w.ghost_y.copy()
    run(w, config.GHOST_TICKS // 2)
    assert np.allclose(w.ghost_x, x0) and np.allclose(w.ghost_y, y0)   # no pull between ghosts: they stay put
    assert not w.wells                               # and nothing collapsed


def test_super_well_swallows_ghosts():
    w = make_world(pw=400, ph=320)
    sw = w.add_super_well(200, 160, 200000)
    sw.spin = 0.0
    w.held = sw
    w.pour_ghosts(260, 160, 6, 8)
    before = sw.mass + w.ghost_mass()
    run(w, 150)
    assert w.ghost_count() == 0 and w.total_mass() == 0
    assert sw.mass == pytest.approx(before)


def test_default_orbit_turns_the_edge_at_the_configured_speed():
    for pw, ph in ((600, 400), (1920, 1000)):
        w = make_world(pw=pw, ph=ph)
        assert w.orbit_edge_speed() == pytest.approx(config.ORBIT_EDGE_SPEED)
    w.resize(1200, 900)                              # the window grows: the edge still turns as fast
    assert w.orbit_edge_speed() == pytest.approx(config.ORBIT_EDGE_SPEED)


def layered_ball(w, cx, cy, radius, masses=(256, 32, 2), aspect=1.0):
    """A packed disc (an ellipse when aspect != 1) of three layers by radius: core, mantle, crust."""
    xs, ys = np.meshgrid(np.arange(w.w), np.arange(w.h))
    d = np.hypot((xs - cx) / aspect, ys - cy) / radius
    inside = d <= 1.0
    m = np.where(d < 0.35, masses[0], np.where(d < 0.7, masses[1], masses[2]))
    w.place_many(xs[inside], ys[inside], m[inside])
    return int(m[inside].sum())


def star_world():
    w = make_world(pw=400, ph=320)
    w.merge_on = w.split_on = False
    return w


def igniting_ball(w, cx, cy, radius=18, mass=128):
    """A packed disc of one rung heavy enough that its weight ignites its core (World._ignites). Returns its mass."""
    return layered_ball(w, cx, cy, radius, (mass, mass, mass))


def test_a_knot_whose_weight_ignites_it_becomes_a_star():
    w = star_world()
    mass = igniting_ball(w, 100, 80)
    n = w.particle_count()
    w.form_stars()
    assert len(w.stars) == 1 and not w.wells
    st = w.stars[0]
    assert w.particle_count() == n and np.count_nonzero(w.owner) >= 0.9 * n   # its particles stay: they are the star
    assert st.mass >= 0.9 * mass and st.radius == pytest.approx(18, rel=0.1) and st.fuel   # (its packed edge may stop
    #                                                                                         just short of its rim)
    assert (st.x, st.y) == (pytest.approx(100, abs=1.5), pytest.approx(80, abs=1.5))


@pytest.mark.parametrize("radius, masses, aspect", [
    (10, (32, 32, 32), 1.0),                         # too light: its weight doesn't ignite it
    (10, (256, 32, 2), 1.0),                         # layered, but too light to ignite
    (2.5, (256, 32, 2), 1.0),                        # too small
])
def test_clumps_that_dont_qualify_stay_particles(radius, masses, aspect):
    w = star_world()
    layered_ball(w, 100, 80, radius, masses, aspect)
    n = w.particle_count()
    w.form_stars()
    assert not w.stars and w.particle_count() == n


def test_star_forms_on_its_own_and_keeps_momentum():
    w = star_world()
    w.collapse_on = False
    igniting_ball(w, 100, 80)
    w.kin[w.mass > 0, 0] = 0.3                       # the whole clump drifting right
    w.tick_count = config.STAR_FORM_EVERY - 5        # (nothing holds it together: check before it spreads)
    run(w, 5)
    assert len(w.stars) == 1 and w.stars_formed == 1
    assert w.stars[0].vx == pytest.approx(0.3, rel=0.05)


def test_a_knot_inside_a_larger_body_becomes_a_star():
    w = star_world()
    xs, ys = np.meshgrid(np.arange(60, 140), np.arange(60, 100))
    w.place_many(xs.ravel(), ys.ravel(), 1)                     # a slab of light dust...
    d = np.hypot(xs - 100, ys - 80)
    w.mass.reshape(w.h, w.w)[ys[d < 19], xs[d < 19]] = 128     # ...with a heavy knot inside, heavy enough to ignite
    w.quad.reshape(w.h, w.w, 4)[ys[d < 19], xs[d < 19]] = (32, 32, 32, 32)
    w.form_stars()
    assert len(w.stars) == 1 and w.stars[0].radius < 30         # the knot (and some dust round it), not the slab
    assert abs(w.stars[0].x - 100) < 3 and abs(w.stars[0].y - 80) < 3
    check_consistent(w)


def test_no_star_forms_in_or_next_to_another_star():
    w = make_world(pw=800, ph=320)
    w.merge_on = w.split_on = False
    xs, ys = np.meshgrid(np.arange(w.w), np.arange(w.h))
    d = np.hypot(xs - 100, ys - 80) / 10
    st = w.add_star(200, 160, 8, mass=50000.0)       # a star at cell (100, 80)...
    ring = (d <= 1.0) & (d > 0.45)
    w.place_many(xs[ring], ys[ring], np.where(d[ring] < 0.65, 256, np.where(d[ring] < 0.85, 32, 2)))   # ...crusted
    w.form_stars()
    assert len(w.stars) == 1                         # it isn't a knot of its own, nor is its crust
    igniting_ball(w, 100 + st.ring + 4 + 18, 80)     # a knot that would ignite, just past its capture ring
    w.form_stars()
    assert len(w.stars) == 1
    igniting_ball(w, 320, 80)                        # one well clear of it forms
    w.form_stars()
    assert len(w.stars) == 2


def test_spawner_pours_ghosts_that_land_or_particles_when_asked():
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False
    sp = w.add_spawner(200, 200, 16, locked=True)
    run(w, 20)
    assert w.ghost_count() > 0 and w.particle_count() == 0
    sp.ghosts = False
    run(w, 20)
    assert w.particle_count() > 0                    # ordinary particles straight away
    sp.locked = False
    w.remove_body(sp)
    run(w, config.GHOST_TICKS)
    assert w.ghost_count() == 0                      # every ghost landed


def test_crowded_ghosts_all_land_without_lining_up():
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False
    xs, ys = np.meshgrid(np.arange(85, 115), np.arange(85, 115))
    w.place_many(xs.ravel(), ys.ravel(), 1)          # a packed block...
    w.add_ghosts(np.full(1500, 100.0), np.full(1500, 100.0), 1)   # ...with a crowd of ghosts in one cell inside it
    w.ghost_age[:] = config.GHOST_TICKS
    run(w, 2 * config.GHOST_LAND_SPREAD * 25)        # (each joins one of its rung nearby, or looks further out)
    assert w.ghost_count() == 0                      # none stuck for lack of room nearby
    occ = (w.mass > 0).reshape(w.h, w.w)
    thin = lambda o: (o[1:-1, 1:-1] & ~o[:-2, 1:-1] & ~o[2:, 1:-1]).sum()   # cells with nothing above or below
    assert thin(occ) < 2 * thin(occ.T) + 20          # landed as a blob, not stacked in horizontal strips


# --- stars: balls of particles held together by their own gravity -----------------------------------

def total(w):
    """All the mass there is: particles (stars' included), ghosts and super wells."""
    return w.total_mass() + w.ghost_mass() + w.super_mass()


STAR_DENSITY = 16.0             # stars here are as heavy as the brush's area x this, as placed stars were when these
                                # tests were written (a placed star now gets its weight from the pour mass)


def place_star(w, px, py, radius_px, **kw):
    """A star filling a radius_px circle, as heavy as STAR_DENSITY makes it (World.add_star with a mass)."""
    return w.add_star(px, py, radius_px, mass=w.brush_mass(radius_px, 1, STAR_DENSITY), **kw)


def test_placed_star_is_a_layered_ball_of_particles_that_holds_together():
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False                  # (no fusing in it: just how it holds together)
    st = place_star(w, 200, 200, 24)                    # radius 12 cells at (100, 100)
    n, mass = w.particle_count(), w.total_mass()
    assert st.count == n and st.mass == mass == pytest.approx(w.brush_mass(24, 1, STAR_DENSITY), rel=0.05)
    idx = np.nonzero(w.mass)[0]
    r = np.hypot(idx % w.w - 100, idx // w.w - 100)
    assert w.mass[idx][r < 4].mean() > 4 * w.mass[idx][r > 9].mean()     # a heavy core in a light envelope
    run(w, 300)
    assert w.stars == [st] and st.mass == w.total_mass() == mass         # all of it, still holding together
    assert st.radius == pytest.approx(12, rel=0.15) and abs(st.x - 100) < 1 and abs(st.y - 100) < 1
    check_consistent(w)


def test_star_travels_as_one():
    w = make_world(pw=600, ph=300)
    w.merge_on = w.split_on = False                  # (no fusing in it: just how it moves)
    st = place_star(w, 100, 150, 20, vx=1.0)
    n = st.count
    run(w, 100)
    assert st.x == pytest.approx(50 + 100, abs=2) and abs(st.y - 75) < 1
    assert st.count == n and st.vx == pytest.approx(1.0, abs=0.02)
    assert w.stats[1] == 0                           # its particles didn't jostle each other on the way


def test_star_pulls_and_is_pulled_without_self_gravity():
    w = make_world(pw=600, ph=300)
    assert not w.sg_on
    st = place_star(w, 300, 150, 16)
    xs, ys = np.meshgrid(np.arange(230, 250), np.arange(65, 85))
    w.place_many(xs.ravel(), ys.ravel(), 256)        # a heavy lump 90 cells to its right
    run(w, 60)
    assert st.vx > 0.5                               # pulled towards the lump...
    lump = np.nonzero((w.mass > 0) & (w.owner != w.stars.index(st) + 1))[0]   # (the lump may be a star too)
    assert (lump % w.w).mean() < 239.5 - 0.5         # ...which it pulls back


def test_star_particles_are_left_out_of_the_self_gravity_mesh():
    w = make_world()
    place_star(w, 100, 80, 12)
    w.place_many([10], [10], [7])
    w.sg.update(w.mass, w.sg_g, w.owner)
    assert w.sg.rho.sum() == 7                       # the star pulls as a whole instead


def test_slow_matter_is_captured_and_fast_matter_passes():
    w = make_world(pw=600, ph=400)
    w.merge_on = w.split_on = False
    st = place_star(w, 300, 200, 24)
    n = st.count
    w.place_many([150 + 18, 150 - 18], [100, 100], [1, 1], [0.0, 0.0], [0.0, 5.0])   # inside its capture ring
    w.step()
    loose = np.nonzero((w.mass > 0) & (w.owner == 0))[0]
    assert loose.size == 1 and abs(w.kin[loose[0], 1]) > 4     # only the fast one isn't bound to it
    assert st.count == n + 1


def test_head_on_crash_scatters_matter_and_what_stays_bound_merges():
    w = make_world(pw=800, ph=500)
    w.merge_on = w.split_on = False                  # (no fusing in them: just how they meet)
    place_star(w, 250, 250, 24, vx=1.5)
    place_star(w, 550, 250, 24, vx=-1.5)
    before, most_loose = total(w), 0
    for _ in range(600):                             # (ploughing through their own debris, they circle each other
        w.step()                                     # for a while before they merge: ~480 ticks)
        most_loose = max(most_loose, w.total_mass() - w.star_mass())
    assert most_loose > 0.1 * before                 # the crash flung matter out of both...
    assert 1 <= len(w.stars) <= 2 and w.star_mass() > 0.5 * before   # ...and what stays bound stays in stars
    assert total(w) == before
    check_consistent(w)


def test_grazing_stars_shave_each_other_but_keep_going():
    w = make_world(pw=800, ph=500)
    a = place_star(w, 200, 230, 24, vx=1.5)
    b = place_star(w, 600, 270, 24, vx=-1.5)
    ma, mb = a.mass, b.mass
    run(w, 250)
    assert w.stars == [a, b]
    assert 0.7 * ma < a.mass < ma and 0.7 * mb < b.mass < mb       # surfaces shaved off, the stars intact
    assert a.vx > 0.5 and b.vx < -0.5


def test_star_that_no_longer_holds_together_comes_apart_quietly():
    w = make_world(pw=600, ph=600)
    w.merge_on = w.split_on = False
    st = place_star(w, 300, 300, 24)
    run(w, config.STAR_FORM_EVERY)
    idx = np.nonzero(w.owner)[0]
    dx, dy = idx % w.w - st.x, idx // w.w - st.y
    r = np.hypot(dx, dy)
    out = r > 0.5                                    # all of it flung away, too fast to stay
    w.kin[idx[out], 0] = 3 * dx[out] / r[out]
    w.kin[idx[out], 1] = 3 * dy[out] / r[out]
    w.flag[idx] = 1
    before = total(w)
    for _ in range(3 * config.STAR_FORM_EVERY):
        w.step()
        if not w.stars:
            break
    assert not w.stars and w.star_explosions == 0 and w.stars_torn == 1   # unbound: it just comes apart ...
    assert not w.blasts and total(w) == before                           # ... no blast (that takes spent fuel)


def test_star_falling_into_a_super_well_is_torn_apart_and_swallowed():
    w = make_world(pw=800, ph=500)
    sw = w.add_super_well(400, 250, 200000)
    sw.spin = 0.5
    w.held = sw
    place_star(w, 400, 100, 20, vx=1.0)
    before = total(w)
    run(w, 300)
    assert not w.stars and w.stars_torn == 1 and w.star_explosions == 0
    assert sw.mass > 200000 and total(w) == before


def test_a_heavy_but_thin_star_does_not_collapse():
    w = make_world(pw=600, ph=400)
    w.collapse_on = True
    st = w.add_star(300, 200, 60, mass=60000)            # 30 cells across: far too thin to be inside its horizon
    assert st.mass > w.lightest_super_mass()             # (though heavier than the lightest super well)
    run(w, 2 * config.COLLAPSE_EVERY)
    assert w.stars == [st] and not w.wells
    w = make_world(pw=600, ph=400)
    w.collapse_on = True
    st = w.add_star(300, 200, 60, mass=30000)            # lighter than any super well: stays a star
    run(w, 2 * config.COLLAPSE_EVERY)
    assert w.stars == [st] and not w.wells


def test_gently_touching_stars_stay_two_but_merge_once_sunk_into_each_other():
    w = make_world(pw=600, ph=400)
    w.merge_on = w.split_on = False                  # (no fusing in them: just how they meet)
    place_star(w, 281, 200, 20)
    place_star(w, 319, 200, 20)                         # 19 cells apart, radius 10: touching, at rest
    before = w.total_mass()
    run(w, 60)
    assert len(w.stars) == 2                            # neighbours resting against each other stay two stars ...
    run(w, 640)
    assert len(w.stars) == 1                            # ... until, drawn into each other, they end as one
    assert w.total_mass() == before and w.stars[0].mass > 0.9 * before   # (a little shed in the jostling)


def test_drag_pulls_a_star_along_and_deleting_it_erases_its_particles():
    w = make_world(pw=600, ph=400)
    st = place_star(w, 200, 200, 20)
    w.place_many([10], [10], [3])
    w.held = st
    w.move_body(st, 400, 200)                        # 100 cells to the right
    run(w, 60)
    assert st.x > 150 and w.stars == [st]
    w.held = None
    w.remove_body(st)
    assert not w.stars and w.total_mass() == 3 and not w.owner.any()


def test_resize_keeps_stars():
    w = make_world()
    place_star(w, 100, 80, 12)
    w.set_cell(1)                                    # the scene is resampled at twice the resolution
    run(w, 2)
    assert len(w.stars) == 1 and abs(w.stars[0].x - 100) < 2 and abs(w.stars[0].y - 80) < 2
    assert w.stars[0].mass == w.total_mass()


def test_wrap_star_holds_together_across_the_seam():
    w = make_world(pw=400, ph=200)
    w.merge_on = w.split_on = False                  # (no fusing in it: just how it moves)
    w.set_wrap(True)
    st = place_star(w, 0, 100, 16, vx=-0.5)             # centred on the left edge
    n = st.count
    run(w, 60)
    assert w.stars == [st] and st.count == n and st.radius == pytest.approx(8, rel=0.2)
    assert st.x == pytest.approx(w.w - 30, abs=2)    # 30 cells left, round the seam


def test_global_orbit_adds_no_bodies():
    w = make_world(pw=400, ph=300)
    for direction in (1, -1, 0):
        w.set_orbit(direction)
        assert not w.wells


def test_remassed_repulsor_is_the_size_and_reach_of_a_fresh_one():
    w = make_world(pw=600, ph=400)
    fresh = w.add_sized_well(150, 200, 24, pour_mass=4, sign=-1)        # 4x the mass of a pour-1 one
    grown = w.add_sized_well(450, 200, 24, sign=-1)
    w.scale_well(grown, 4.0)
    assert grown.mass == pytest.approx(fresh.mass)
    assert grown.radius == pytest.approx(fresh.radius) and w.reach(grown) == pytest.approx(w.reach(fresh))
    w.scale_well(grown, 0.25)                                            # and back down
    assert grown.radius == pytest.approx(12)
    w.rebuild_field()
    assert np.count_nonzero(w.solid) > 0


@pytest.mark.parametrize("factor", [0.5, 2.0])
def test_remassed_star_is_the_size_of_a_fresh_one_and_still_holds_together(factor):
    w = make_world(pw=800, ph=500)
    w.merge_on = w.split_on = False
    st = place_star(w, 200, 250, 24)
    w.scale_star(st, factor)
    fresh = place_star(w, 600, 250, 24 * math.sqrt(factor))              # placed at that mass
    assert st.mass == pytest.approx(fresh.mass, rel=0.05)
    assert st.radius == pytest.approx(fresh.radius, rel=0.05) and st.ring == pytest.approx(fresh.ring, rel=0.05)
    assert st.count == pytest.approx(fresh.count, rel=0.05)
    run(w, 100)
    assert len(w.stars) == 2 and w.star_explosions == 0                 # made lighter isn't unstable
    assert st.mass == pytest.approx(fresh.mass, rel=0.05)


# --- gravity reach: every pull fades with distance ----------------------------------------------------

def test_well_pull_fades_with_distance_and_is_the_slope_of_its_potential():
    w = make_world(pw=1600, ph=400)
    w.set_reach(40)
    w.add_well(100, 200, 100000.0)                   # cell (50, 100)
    w.rebuild_field()
    fx = lambda d: -float(w.fx[100 * w.w + 50 + d])  # pull towards the well, d cells to its right
    plain = lambda d: w.g_scale * config.G * 100000.0 * d / (d * d + config.WELL_SOFTENING ** 2) ** 1.5
    for d in (10, 30):                               # within the reach: the plain pull
        assert fx(d) == pytest.approx(plain(d), rel=0.02)
    assert fx(60) == pytest.approx(0.5 * plain(60), rel=0.05)   # halfway through the taper: half
    assert fx(85) == 0.0 and fx(240) == 0.0          # past twice the reach: none at all
    phi = lambda d: float(w.phi[100 * w.w + 50 + d])
    for d in (20, 40, 50, 60, 70):                   # the pull is the potential's slope (over 4 cells: float32)
        assert (phi(d + 2) - phi(d - 2)) / 4 == pytest.approx(fx(d), rel=0.05)
    assert phi(90) == phi(240) == 0.0                # and beyond it nothing to climb
    w.set_reach(0)                                   # all the way: the plain inverse-square law again
    w.rebuild_field()
    assert fx(240) == pytest.approx(plain(240), rel=0.02)


def test_reach_for_solves_the_faded_pull():
    from sv.gravity import reach_for
    for strength, accel, reach in ((80, 0.01, 60), (12000, 0.01, 60), (5, 0.02, 15), (12000, 0.01, 0)):
        r = reach_for(strength, accel, 1 / reach if reach else 0.0)
        kinv = 1 / reach if reach else 0.0
        assert strength / r ** 2 * fade(r, kinv)[0] == pytest.approx(accel, rel=1e-6)


def test_heavy_super_well_far_away_hardly_moves_matter():
    moved = {}
    for reach in (60, 0):
        w = make_world(pw=1600, ph=400)
        w.set_reach(reach)
        w.merge_on = w.split_on = False
        sw = w.add_super_well(1500, 200, 5000000)
        sw.spin = 0
        w.held = sw                                  # keep it put
        w.place_many([100], [100], [1])              # 700 cells away
        run(w, 100)
        i = np.nonzero(w.mass)[0][0]
        moved[reach] = abs(i % w.w - 100)
    assert moved[60] < 1 and moved[0] > 5


def test_faraway_heavy_body_does_not_cut_a_stars_ring():
    for reach, cut in ((60, False), (0, True)):
        rings = []
        for companion in (True, False):
            w = make_world(pw=1600, ph=400)
            w.set_reach(reach)
            st = place_star(w, 200, 200, 24)
            if companion:
                w.held = w.add_super_well(500, 200, 5000000)     # 150 cells away (past twice the reach of 60)
            w._set_ring(st, grow=False)
            rings.append(st.ring)
        if cut:                                      # unfaded, its tide cuts the ring down (1.5 Hill radii)...
            assert rings[0] < 0.8 * rings[1]
        else:                                        # ...faded, from that far it hardly does
            assert rings[0] == pytest.approx(rings[1], rel=0.05)


def test_self_gravity_fades_with_distance():
    pulls = {}
    for reach in (30, 0):
        w = make_world(pw=800, ph=200)
        w.set_reach(reach)
        xs, ys = np.meshgrid(np.arange(20, 40), np.arange(40, 60))
        w.place_many(xs.ravel(), ys.ravel(), 64)
        w.sg.update(w.mass, w.sg_g)
        sg = w.sg
        b = lambda x: (50 // sg.block) * sg.cw + x // sg.block
        pulls[reach] = (-sg.gx[b(60)], -sg.gx[b(330)])   # 30 and 300 cells from the clump
    assert pulls[30][0] > 0.5 * pulls[0][0]                # near: much the same
    assert pulls[30][1] < 0.01 * pulls[0][1]               # ten reach lengths away: gone


# --- super well mergers: a shock, and a moment's grace before going supernova ------------------------

def test_merger_over_the_limit_waits_before_going_supernova():
    w = make_world(pw=600, ph=400)
    a = w.add_super_well(300, 200, 0.6 * config.SUPER_EXPLODE_MASS)
    b = w.add_super_well(301, 200, 0.6 * config.SUPER_EXPLODE_MASS)   # cores touching: they merge at once
    w.step()
    assert len(w.wells) == 1 and w.wells[0].mass >= config.SUPER_EXPLODE_MASS and w.explosions == 0
    run(w, config.SUPER_MERGE_GRACE - 2)
    assert w.explosions == 0                         # still within its grace
    run(w, 3)
    assert w.explosions == 1 and not w.wells         # then it goes


def test_more_mergers_dont_stretch_the_grace():
    w = make_world(pw=600, ph=400)
    big = w.add_super_well(300, 200, 0.6 * config.SUPER_EXPLODE_MASS)
    w.add_super_well(301, 200, 0.6 * config.SUPER_EXPLODE_MASS)
    w.step()
    until = big.calm_until
    run(w, 50)
    w.add_super_well(2 * big.x + 1, 2 * big.y, 100000)                 # another one falls in
    w.step()
    assert len(w.wells) == 1 and big.calm_until == until



def test_well_that_gets_over_the_limit_without_merging_waits_before_going_supernova():
    w = make_world(pw=600, ph=400)
    wl = w.add_super_well(300, 200, config.SUPER_EXPLODE_MASS - 1000)
    w.step()
    wl.mass += 2000                                  # as swallowing particles or debris would
    w.step()
    run(w, config.SUPER_MERGE_GRACE - 2)
    assert w.explosions == 0 and w.wells == [wl]     # still within its grace
    run(w, 3)
    assert w.explosions == 1 and not w.wells         # then it goes


def test_getting_over_the_limit_inside_a_merger_window_still_waits_the_full_grace():
    w = make_world(pw=600, ph=400)
    big = w.add_super_well(300, 200, 0.4 * config.SUPER_EXPLODE_MASS)
    w.add_super_well(301, 200, 0.4 * config.SUPER_EXPLODE_MASS)
    w.step()                                         # they merge, under the limit: a window opens
    run(w, 50)
    big.mass = config.SUPER_EXPLODE_MASS + 1000      # then it gets too heavy, 50 ticks into the window
    w.step()
    run(w, config.SUPER_MERGE_GRACE - 2)
    assert w.explosions == 0                         # the whole grace from then, not what was left of the window
    run(w, 3)
    assert w.explosions == 1

def heavy_clump(w, cx, cy, r=9):
    """A packed disc of particles with a heavy core (1024) in a light envelope (16), like the blobs a disk forms."""
    ys, xs = np.mgrid[-r:r + 1, -r:r + 1]
    inside = xs ** 2 + ys ** 2 <= r * r
    xs, ys = xs[inside], ys[inside]
    w.place_many(cx + xs, cy + ys, np.where(xs ** 2 + ys ** 2 <= 16, 1024, 16))


def mass_angle(w):
    """Angle of the particles' centre of mass round the middle of the universe."""
    y, x = np.divmod(np.nonzero(w.mass)[0], w.w)
    m = w.mass[w.mass > 0].astype(float)
    return math.atan2(((y - w.h / 2) * m).sum(), ((x - w.w / 2) * m).sum())


@pytest.mark.parametrize("orbit", [0, 1])
def test_heavy_self_gravitating_clump_turns_with_the_global_orbit(orbit):
    w = make_world(pw=600, ph=600)
    w.star_form_on = False
    w.set_orbit(orbit)
    w.set_orbit_edge_speed(5.0)
    w.set_wrap(True)
    w.set_self_gravity(True)
    w.g_scale = 0.6
    w.set_reach(20)
    heavy_clump(w, 240, 150)                         # 90 cells right of the middle
    m0 = w.total_mass()
    turned, prev = 0.0, mass_angle(w)
    for t in range(150):
        w.step()
        if t % 10 == 9:
            a = mass_angle(w)
            turned += (a - prev + math.pi) % (2 * math.pi) - math.pi
            prev = a
    assert w.total_mass() == m0
    if orbit:
        assert turned > 0.85 * w.orbit_speed * 150  # carried round with the universe, not held by its own gravity
        labels = np.zeros(w.n, np.int32)
        kernels.label_clumps(w.mass, w.w, w.h, labels, np.zeros(w.n, np.int32))
        m = np.bincount(labels, weights=w.mass.astype(float))[1:]
        assert m.max() > 0.95 * m.sum()            # and it holds together
    else:
        assert abs(turned) < 0.05


def test_supernova_mass_is_a_setting_and_presets_restore_it():
    from sv.presets import empty
    w = make_world(pw=600, ph=400)
    wl = w.add_super_well(300, 200, 3_000_000)
    w.step()
    w.explode_mass = 2_500_000                       # lowered under it: it waits out its grace, then goes
    run(w, config.SUPER_MERGE_GRACE + 2)
    assert w.explosions == 1 and wl not in w.wells
    empty(w)
    assert w.explode_mass == config.SUPER_EXPLODE_MASS


def test_supernova_preset_is_one_super_well_half_again_over_the_supernova_mass():
    from sv.presets import supernova
    w = make_world(pw=600, ph=400)
    w.place_many([10], [10], [4])
    supernova(w)
    assert w.round and w.particle_count() == 0 and len(w.wells) == 1
    wl = w.wells[0]
    assert wl.is_super and wl.mass == pytest.approx(1.5 * w.explode_mass, rel=1e-6)
    assert wl.x == pytest.approx(w.w / 2) and wl.y == pytest.approx(w.h / 2)
    assert config.DEFAULT_PRESET == "supernova"


def test_radiation_sheds_heat_from_merges_and_splits_and_keeps_all_mass():
    w = make_world()
    w.radiation_on = w.merge_on = w.split_on = True
    w.add_well(100, 80, 200000.0)                    # fast impacts, so merges and splits happen
    rng = np.random.default_rng(0)
    w.place_many(rng.integers(0, w.w, 3000), rng.integers(0, w.h, 3000), rng.choice([16, 64, 256], 3000))
    m0 = w.universe_mass()
    made = 0
    for _ in range(300):
        w.step()
        made += w.heat_made
        check_consistent(w)                          # children still add up to the mass that is left
        assert w.universe_mass() == m0               # heat is mass, carried off as light particles
    assert made > 0


def test_heat_blows_light_particles_away_but_barely_moves_heavy_ones():
    w = make_world()
    w.place_many([20, 60], [20, 20], [1, 1000])
    w.add_ghosts(np.array([20.0, 60.0]), np.array([20.0, 20.0]), np.array([1, 1]), 6.0, 0.0, tag=kernels.HEAT_TAG)
    kernels.heat_push(w.ghost_x, w.ghost_y, w.ghost_vx, w.ghost_vy, w.ghost_m, w.ghost_tag, kernels.HEAT_TAG, 0.5,
                      config.HEAT_MIN_SPEED, config.VMAX, w.w, w.h, w.mass, w.kin, w.owner, w.flag)
    light, heavy = 20 * w.w + 20, 20 * w.w + 60
    assert w.kin[light, 0] == pytest.approx(3.0)     # half an elastic hit between equals
    assert 0 < w.kin[heavy, 0] < 0.01                # a heavy one soaks the heat up...
    assert w.ghost_vx[1] < 0.1                       # ...and stops it
    assert w.ghost_vx[0] * 1 + w.kin[light, 0] * 1 == pytest.approx(6.0)   # momentum is kept
    assert w.flag[light] and w.flag[heavy]


def test_radiation_is_taken_in_by_the_first_matter_it_meets():
    w = make_world(pw=400, ph=200)
    w.radiation_on = True
    w.merge_on = w.split_on = False
    xs, ys = np.meshgrid(np.arange(150, 160), np.arange(45, 55))
    w.place_many(xs.ravel(), ys.ravel(), 16)         # a block in its way
    w.add_ghosts(np.array([20.0]), np.array([50.0]), 3, config.VMAX, 0.0, tag=kernels.HEAT_TAG)   # 3 quanta
    m0, (_, k0, q0, b0) = w.universe_mass(), w.energy()
    assert w.heat_count() == 1 and w.ghost_count() == 0 and w.ghost_mass() == 0   # energy, not matter
    run(w, 30)
    _, k1, q1, b1 = w.energy()
    hit = w.kin[(w.mass > 0), 4]
    assert w.heat_count() == 0 and w.universe_mass() == m0   # taken in, and no matter made
    assert k1 + q1 + b1 == pytest.approx(k0 + q0 + b0)      # as heat and a push
    assert hit.max() > 0 and k1 > 0


@pytest.mark.parametrize("recycle", [True, False])
def test_radiation_reaching_the_edge_comes_back_in_or_is_gone(recycle):
    w = make_world(pw=400, ph=400)
    w.set_round(True)
    w.radiation_on = True
    w.radiation_recycle = recycle
    w.add_ghosts(np.array([w.w / 2]), np.array([w.h / 2]), 1, config.VMAX, 0.0, tag=kernels.HEAT_TAG)
    run(w, 200)                                      # an empty universe: it reaches the edge, many times over
    assert w.heat_count() == (1 if recycle else 0) and w.radiation_lost == (0 if recycle else 1)
    if recycle:                                      # back inside, heading in
        assert math.hypot(w.ghost_x[0] - w.w / 2, w.ghost_y[0] - w.h / 2) < min(w.w, w.h) / 2


@pytest.mark.parametrize("temperature", [0.0, 4.0])
def test_hot_matter_fuses_where_it_lies_and_cold_matter_does_not(temperature):
    w = make_world(pw=200, ph=200)
    w.merge_on, w.split_on = True, False
    xs, ys = np.meshgrid(np.arange(30, 70), np.arange(30, 70))
    w.place_many(xs.ravel(), ys.ravel(), 1)          # a packed block of the lightest rung, at rest
    w.kin[w.mass > 0, 4] = temperature               # (heat per unit mass x mass 1)
    m0, (_, k0, q0, b0) = w.universe_mass(), w.energy()
    fused = 0
    for _ in range(40):
        w.step()
        fused += w.fused
    _, k1, q1, b1 = w.energy()
    assert w.universe_mass() == m0 and set(np.unique(w.mass[w.mass > 0])) <= {1, 2, 4, 8}   # rungs, mass kept
    assert k1 + q1 + b1 == pytest.approx(k0 + q0 + b0, rel=1e-4)   # what fusing gives off is heat
    if temperature:
        assert fused > 50 and q1 > q0                # hot enough: it fuses, nothing colliding, and heats up
    else:
        assert fused == 0                            # cold: never


@pytest.mark.parametrize("pour", [1, 4, 16, 256])
def test_placed_star_fills_the_brush_circle_with_a_core_of_the_pour_mass(pour):
    w = make_world(pw=400, ph=400)
    st = w.add_star(200, 200, 40, pour)              # a 40 px brush: 20 cells
    idx = np.nonzero(w.owner)[0]
    r = np.hypot(idx % w.w - st.x, idx // w.w - st.y)
    assert r.max() <= 20.5 and np.percentile(r, 95) > 18    # the brush circle, filled to its edge
    m = w.mass[idx]
    assert (m[r < 0.4 * 20 - 1] == pour).all()       # its core is made of pour-mass particles...
    assert (m[r > 0.7 * 20 + 1] == max(1, round(pour / 8))).all()   # ...its envelope of lighter ones
    assert st.mass == m.sum()


def test_random_pour_makes_a_core_of_random_masses_in_the_range():
    w = make_world(pw=400, ph=400)
    st = w.add_star(200, 200, 40, (64, 256))
    idx = np.nonzero(w.owner)[0]
    core = w.mass[idx][np.hypot(idx % w.w - st.x, idx // w.w - st.y) < 7]
    assert set(np.unique(core)) == {64, 128, 256}    # every rung in the range


def test_ghost_star_passes_through_matter_then_lands_as_a_star_keeping_its_mass():
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False
    xs, ys = np.meshgrid(np.arange(90, 111), np.arange(120, 124))            # a wall of matter in its way
    w.place_many(xs.ravel(), ys.ravel(), 4)
    gs = w.add_star(200, 340, 20, 16, vy=-0.5, ghost=True)                   # cell (100, 170), heading up
    m0 = w.universe_mass()
    assert not w.stars and w.ghost_stars == [gs] and m0 == w.total_mass() + gs.mass
    for _ in range(config.GHOST_TICKS - 1):
        w.step()
        assert w.universe_mass() == m0
    assert gs.y < 100 and w.ghost_stars                                      # through the wall, still a ghost
    w.step()
    assert not w.ghost_stars and len(w.stars) == 1 and w.universe_mass() == m0
    assert abs(w.stars[0].y - gs.y) < 2 and w.stars[0].vy < -0.3            # landed where it got to, moving on


def test_ghost_star_landing_on_matter_sends_what_has_no_room_out_as_ghosts():
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False
    w.place_many(np.arange(95, 106), np.full(11, 100), 4)                    # a bar across where it will land
    gs = w.add_star(200, 200, 20, 16, ghost=True)
    m0 = w.universe_mass()
    w._land_ghost_star(gs)
    assert w.stars and w.ghost_count() == 11 and w.universe_mass() == m0
    run(w, 3)
    assert w.ghost_count() == 0 and w.universe_mass() == m0                  # they land nearby


def test_super_well_swallows_a_ghost_star_whole():
    w = make_world(pw=400, ph=400)
    sw = w.add_super_well(200, 200, 100000)
    gs = w.add_star(200, 200, 10, 4, ghost=True)
    m0 = w.universe_mass()
    w.step()
    assert not w.ghost_stars and not w.stars and sw.mass == 100000 + gs.mass and w.universe_mass() == m0


def test_remassing_a_star_keeps_its_density():
    w = make_world(pw=400, ph=400)
    st = w.add_star(200, 200, 40, 4)
    r0, m0 = st.radius, st.mass
    w.scale_well(st, 1.25)
    assert st.mass == pytest.approx(1.25 * m0, rel=0.05)
    assert st.radius == pytest.approx(r0 * math.sqrt(1.25), rel=0.1)
    idx = np.nonzero(w.owner)[0]
    core = w.mass[idx][np.hypot(idx % w.w - st.x, idx // w.w - st.y) < 0.3 * st.radius]
    assert (core == 4).all()                         # still a core of pour-mass particles


def orbit_world():
    """A big universe with gravity reaching everywhere at the app's strength: where a star can orbit a super well."""
    w = make_world(pw=1200, ph=1200)                 # 600 x 600 cells
    w.set_reach(0)
    w.g_scale = 0.6
    w.radiation_on = True                            # (off, a star this big stays too loose to hold: see README)
    return w


def test_star_placed_in_orbit_circles_its_super_well_and_the_well_stays_put():
    w = orbit_world()
    wl = w.add_super_well(600, 600, 80000)
    wl.spin = -abs(wl.spin)                          # counterclockwise
    st = w.add_star(600 + 2 * 130, 600, 40, 16, orbit=True)   # 130 cells to the right
    rho = math.sqrt(130 ** 2 + w.softening(wl) ** 2)
    m = st.mass
    v = math.sqrt(w.g_scale * config.G * (wl.mass + m) * 130 ** 2 / rho ** 3)    # two-body: their combined pull
    assert st.vx == pytest.approx(0, abs=1e-9)
    assert st.vy - wl.vy == pytest.approx(-v, rel=1e-3)          # circular relative orbit, the way the well spins
    assert wl.vy * wl.mass == pytest.approx(-st.vy * st.mass)    # it takes the opposite momentum
    m0, x0, y0 = st.mass, wl.x, wl.y
    turned, prev, rs = 0.0, 0.0, []
    while abs(turned) < 2 * math.pi:
        w.step()
        assert st in w.stars
        dx, dy = st.x - wl.x, st.y - wl.y
        rs.append(math.hypot(dx, dy))
        a = math.atan2(dy, dx)
        turned += (a - prev + math.pi) % (2 * math.pi) - math.pi
        prev = a
        assert len(rs) < 1500
    assert turned < 0                                # round the way it was sent
    assert 115 < min(rs) and max(rs) < 145           # a near circle all the way round
    assert st.mass > 0.85 * m0                       # not torn (a new star settles, shedding about 8% anyway)
    assert math.hypot(wl.x - x0, wl.y - y0) < 5      # the two don't drift off together


def test_star_in_orbit_goes_round_the_well_pulling_hardest_or_stays_put_without_one():
    w = orbit_world()
    st = w.add_star(200, 1000, 20, 16, vx=0.3, orbit=True)
    assert st.vx == pytest.approx(0.3) and st.vy == 0.0   # no super well: as asked
    near = w.add_super_well(600, 400, 20000)         # 100 cells away
    far = w.add_super_well(1100, 400, 200000)        # 350 cells away: ten times the mass, pulling less here
    st = w.add_star(400, 400, 20, 16, orbit=True)
    assert w.orbit_well(200, 200) is near
    assert st.vx == pytest.approx(0, abs=1e-9) and abs(st.vy) > 0.1 and far.vx == far.vy == 0.0


def test_systems_preset_puts_stars_in_orbit_round_super_wells_out_of_each_others_reach(monkeypatch):
    from sv.presets import systems
    w = World(1920, 1080, 2, seed=3)                 # fullscreen, as it is laid out for
    systems(w)                                       # (it sets its own reach and strength)
    assert w.round and w.reach_len == config.SYSTEM_REACH and w.g_scale == config.SYSTEM_SCALE
    mid, others = w.wells[0], w.wells[1:]
    assert all(wl.is_super for wl in w.wells) and config.SYSTEM_OTHERS[0] <= len(others) <= config.SYSTEM_OTHERS[1]
    assert mid.x == pytest.approx(w.w / 2) and mid.y == pytest.approx(w.h / 2)
    home = {st: min(w.wells, key=lambda wl: w.distance(st.x, st.y, wl.x, wl.y)) for st in w.stars}
    count = {id(wl): sum(h is wl for h in home.values()) for wl in w.wells}
    assert count[id(mid)] == config.SYSTEM_CENTRE_STARS
    assert all(1 <= count[id(wl)] <= 2 for wl in others)
    orbit = config.SYSTEM_ORBIT
    for a in w.wells:                                # no well's gravity reaches another system's stars
        for b in w.wells:
            if a is not b:
                assert w.distance(a.x, a.y, b.x, b.y) >= 2 * w.reach_len + orbit - 1e-6
    for st, wl in home.items():
        assert w.distance(st.x, st.y, wl.x, wl.y) == pytest.approx(orbit, abs=1.5)
        assert w.distance(st.x, st.y, w.w / 2, w.h / 2) + st.radius < w.w / 2   # inside the universe
        dx, dy = st.x - wl.x, st.y - wl.y
        turn = dx * (st.vy - wl.vy) - dy * (st.vx - wl.vx)
        assert np.sign(turn) == np.sign(wl.spin)     # circling its own well the way it spins
    run(w, 600)                                      # ten seconds on, every star still on its orbit
    for st, wl in home.items():
        assert st in w.stars and 0.8 * orbit < w.distance(st.x, st.y, wl.x, wl.y) < 1.2 * orbit


def test_super_wells_pull_from_where_they_are_now_not_from_the_field():
    w = make_world(pw=400, ph=400)
    w.set_reach(0)
    wl = w.add_super_well(200, 200, 100000)          # cell (100, 100)
    w.held = wl                                      # kept where it is put
    w.step()
    serial = w.field_serial
    w.add_ghosts(np.array([100.0]), np.array([140.0]), np.array([1]), age=-10 ** 6)
    wl.x += 0.4                                      # under the distance that marked its core again
    w.step()
    assert w.ghost_vx[0] > 0 and w.ghost_vy[0] < 0   # towards where it is, not straight up to where it was
    assert w.field_serial == serial                  # and moving it didn't rebuild the field
    ax, ay = w.field_at(100.0, 140.0)
    rho = math.sqrt(0.4 ** 2 + 40 ** 2 + w.softening(wl) ** 2)
    assert math.hypot(ax, ay) == pytest.approx(w.g_scale * wl.pull() / rho ** 2 * math.hypot(0.4, 40) / rho)


def test_dense_star_holds_a_close_orbit_inside_a_short_reach():
    """A small, dense star round a light super well, all within a 50-cell reach: the orbit used to grow every turn
    while the well's field lagged behind its swing (42 -> 129 cells in four turns)."""
    w = make_world(pw=1200, ph=1200)
    w.set_reach(50)
    w.g_scale = 0.6
    w.radiation_on = True
    w.collapse_on = w.star_form_on = False
    wl = w.add_super_well(600, 600, 40000)
    st = w.add_star(600 + 2 * 42, 600, 8, 256, orbit=True)
    turned, prev, rs = 0.0, 0.0, []
    while abs(turned) < 2 * 2 * math.pi:
        w.step()
        assert st in w.stars and len(rs) < 1500
        dx, dy = st.x - wl.x, st.y - wl.y
        rs.append(math.hypot(dx, dy))
        a = math.atan2(dy, dx)
        turned += (a - prev + math.pi) % (2 * math.pi) - math.pi
        prev = a
    assert 35 < min(rs) and max(rs) < 50             # two turns, near the circle it started on


def test_brush_star_is_the_star_the_brush_places():
    w = make_world(pw=400, ph=400)
    r, m = w.brush_star(30, 16)
    st = w.add_star(200, 200, 30, 16)
    assert r == 15 and m == pytest.approx(st.mass, rel=0.05)   # (its layers are rounded to rungs at random)


@pytest.mark.parametrize("reach, mass, brush, pour, orbit, ok", [
    (0, 80000, 40, 16, 150, True),                   # the README's star held 120-170 cells out ...
    (0, 80000, 40, 16, 110, False),                  # ... stripped at 110
    (50, 40000, 8, 256, 42, True),                   # a small dense star within a short reach
    (50, 40000, 8, 256, 62, False),                  # past ~1.16 x the reach no orbit is stable
])
def test_orbit_band_matches_where_orbits_were_found_to_hold(reach, mass, brush, pour, orbit, ok):
    w = make_world(pw=1200, ph=1200)
    w.set_reach(reach)
    w.g_scale = 0.6
    wl = w.add_super_well(600, 600, mass)
    inner, outer = w.orbit_band(wl, *w.brush_star(brush, pour))
    assert (inner < orbit < outer) == ok


def test_orbit_band_is_nowhere_for_a_big_star_in_a_short_reach_and_shrinks_beside_a_neighbour():
    w = make_world(pw=1600, ph=1600)
    w.set_reach(20)
    w.g_scale = 0.6
    wl = w.add_super_well(800, 800, 80000)
    assert w.orbit_band(wl, *w.brush_star(40, 16)) is None
    w.set_reach(0)
    alone = w.orbit_band(wl, *w.brush_star(20, 16))
    w.add_super_well(800 + 2 * 400, 800, 80000)     # an equal one 400 cells away
    inner, outer = w.orbit_band(wl, *w.brush_star(20, 16))
    assert inner == alone[0] and outer == pytest.approx(0.3 * 400) and outer < alone[1]


@pytest.mark.xfail(reason="orbits past ~0.78 x the reach are barely bound: three stars sharing one drift apart (TO_DO.md: bigger wells holding more)", strict=False)
def test_auto_star_fills_an_orbit_evenly_and_the_stars_hold():
    w = make_world(pw=1200, ph=1200)
    w.set_reach(config.SYSTEM_REACH)                 # where stars can orbit a super well (TO_DO.md)
    w.g_scale = config.SYSTEM_SCALE
    w.radiation_on = True
    wl = w.add_super_well(600, 600, 80000)
    clicks = [(600 + 2 * 150, 600), (600, 600 + 2 * 150), (600 - 2 * 150, 600 - 40), (600, 600 - 2 * 150)]
    placed = [w.add_auto_star(*c) for c in clicks]
    assert all(placed[:3]) and placed[3] is None     # three fill the orbit; a fourth has no room
    d = [w.distance(st.x, st.y, wl.x, wl.y) for st in placed[:3]]
    inner, outer = w.orbit_band(wl, placed[0].radius, placed[0].mass)
    assert all(inner - 2 < x < outer + 2 for x in d) and max(d) - min(d) < 2   # one orbit, inside the band
    angles = sorted(math.atan2(st.y - wl.y, st.x - wl.x) for st in placed[:3])
    gaps = np.diff(angles + [angles[0] + 2 * math.pi])
    assert gaps.min() > math.radians(115)            # evenly spread
    run(w, 1200)
    for st in placed[:3]:
        assert st in w.stars and 0.75 * d[0] < w.distance(st.x, st.y, wl.x, wl.y) < 1.25 * d[0]


def test_auto_star_needs_a_super_well():
    w = make_world()
    assert w.add_auto_star(200, 160) is None


@pytest.mark.parametrize("pour, px, collapses", [(1024, 20, False), (2048, 12, False), (2048, 20, True), (4096, 12, True)])
def test_a_star_collapses_only_when_inside_its_own_horizon(pour, px, collapses):
    w = make_world(pw=400, ph=400)
    w.collapse_on = True
    near, limit = w.star_collapse_check(px, pour)    # what the Star tool's brush warns of
    assert (near >= limit) == collapses
    st = w.add_star(200, 200, px, pour)
    m0 = w.universe_mass()
    run(w, config.COLLAPSE_EVERY)                    # (the first check: later, burning, a star can shrink and collapse)
    assert (st in w.stars) != collapses
    supers = [wl for wl in w.wells if wl.is_super]
    assert bool(supers) == collapses and w.universe_mass() == m0
    if collapses:                                    # all of it, inside its new horizon
        assert supers[0].mass >= 0.99 * st.mass and w.horizon(supers[0]) >= px / 2 / w.cell * 0.9


# --- super wells: spin, frame dragging, pairs and gravitational waves (physics rework step 6) -----------------

def circling_pair(w, m, gap):
    """Two super wells of mass m, gap cells apart, not spinning, on a circular orbit round each other."""
    a = w.add_super_well(300, 400, m)
    b = w.add_super_well(300 + 2 * gap, 400, m)
    w.set_spin(a, 0.0)
    w.set_spin(b, 0.0)
    rho = math.hypot(gap, config.SUPER_SOFTENING)
    v = math.sqrt(w.g_scale * config.G * 2 * m * gap * gap / rho ** 3 * fade(rho, w.kinv)[0])
    a.vy, b.vy = v / 2, -v / 2
    return a, b


def test_a_pair_of_super_wells_orbits_by_gravity_alone():
    w = make_world(pw=1200, ph=800)
    w.radiation_on = False                           # no waves: nothing takes their orbit's energy
    a, b = circling_pair(w, 300000, 30)
    gaps = []
    for _ in range(1000):
        w.step()
        gaps.append(math.hypot(b.x - a.x, b.y - a.y))
    assert a in w.wells and b in w.wells and 0.7 * 30 < min(gaps) and max(gaps) < 1.3 * 30


def test_gravitational_waves_spiral_a_pair_in_until_it_merges_spinning():
    w = make_world(pw=1200, ph=800)
    w.radiation_on = True
    a, b = circling_pair(w, 300000, 20)
    turned, prev, waves = 0.0, 0.0, 0
    for t in range(600):
        w.step()
        waves = max(waves, w.wave_count())
        if len([wl for wl in w.wells if wl.is_super]) == 1:
            break
        ang = math.atan2(b.y - a.y, b.x - a.x)
        turned += (ang - prev + math.pi) % (2 * math.pi) - math.pi if t else 0.0
        prev = ang
    merged = [wl for wl in w.wells if wl.is_super]
    assert len(merged) == 1 and abs(turned) > 2 * math.pi       # round each other at least once, then merged
    assert 0.8 * 600000 < merged[0].mass < 600000 and waves > 0  # lighter by what went out as waves
    assert merged[0].spin * turned > 0 and abs(merged[0].spin) > 0.3   # spinning the way they went round
    # (y down: going round clockwise on screen, the angle grows, as spin > 0 is clockwise)


def test_waves_are_energy_flying_at_the_speed_of_light_taken_in_never_landing():
    w = make_world(pw=600, ph=400)
    w.radiation_on = True
    w.merge_on = w.split_on = False
    xs, ys = np.meshgrid(np.arange(200, 210), np.arange(95, 105))
    w.place_many(xs.ravel(), ys.ravel(), 16)
    w.add_ghosts(np.array([20.0]), np.array([100.0]), 3, config.LIGHT_SPEED, 0.0, tag=kernels.WAVE_TAG)
    m0 = w.universe_mass()
    assert w.wave_count() == 1 and w.ghost_mass() == 0          # energy, not matter
    run(w, 3)
    assert w.ghost_x[0] == pytest.approx(20 + 3 * config.LIGHT_SPEED)   # straight on, at the speed of light
    run(w, 20)
    assert w.wave_count() == 0 and w.universe_mass() == m0 and w.kin[w.mass > 0, 4].max() > 0   # taken in as heat


def test_the_faint_circle_is_where_space_moves_faster_than_matter_can():
    w = make_world(pw=1200, ph=1200)
    wl = w.add_super_well(600, 600, 1_000_000)
    w.set_spin(wl, 0.0)
    assert w.well_range(wl) == wl.core() and w.frame_turn(wl.x + 20, wl.y) == (0.0, 0.0, 0.0)   # no spin: no drag
    w.set_spin(wl, 1.0)
    r = w.well_range(wl)
    assert r > wl.core()
    assert w.frame_turn(wl.x + r, wl.y)[0] * r == pytest.approx(config.VMAX, rel=0.02)   # space at matter's top speed
    assert 0 < w.frame_turn(wl.x + 3 * r, wl.y)[0] * 3 * r < config.VMAX                # slower further out


@pytest.mark.parametrize("spin", [1.0, 0.0])
def test_a_spinning_super_well_carries_what_falls_in_round(spin):
    w = make_world(pw=1200, ph=1200)
    w.merge_on = w.split_on = w.collapse_on = False
    wl = w.add_super_well(600, 600, 1_000_000)
    w.held = wl
    w.set_spin(wl, spin)                             # > 0: clockwise on screen
    w.place_many([300 + 40], [300], [1])             # dropped at rest, right of it
    run(w, 4)
    y = np.nonzero(w.mass)[0][0] // w.w - 300
    assert (y >= 1) if spin else (y == 0)            # clockwise: right of it, carried down; no spin: straight in


@pytest.mark.parametrize("way", [1, -1])
def test_matter_that_collapses_spins_its_super_well_the_way_it_went_round(way):
    w = make_world()
    w.merge_on = w.split_on = False
    w.collapse_on = True
    dense_patch(w)
    idx = np.nonzero(w.mass)[0]
    dx, dy = idx % w.w - 47.0, idx // w.w - 37.0
    w.kin[idx, 0] = -way * 0.05 * dy                 # turning round its middle (> 0: clockwise on screen)
    w.kin[idx, 1] = way * 0.05 * dx
    run(w, config.COLLAPSE_EVERY)
    wl = next(wl for wl in w.wells if wl.is_super)
    assert wl.spin * way > 0


def test_swallowing_matter_that_goes_round_it_spins_a_super_well_up():
    w = make_world(pw=1200, ph=1200)
    w.merge_on = w.split_on = w.collapse_on = False
    wl = w.add_super_well(600, 600, 500_000)
    w.held = wl
    w.set_spin(wl, 0.0)
    rng = np.random.default_rng(0)
    r, a = rng.uniform(30, 50, 200), rng.uniform(0, 2 * np.pi, 200)
    w.place_many(np.round(300 + r * np.cos(a)), np.round(300 + r * np.sin(a)), 16, -2 * np.sin(a), 2 * np.cos(a))
    run(w, 300)
    assert w.total_mass() == 0 and wl.spin > 0 and wl.jz > 0   # it swallowed it all, and spins the way it went round


def test_super_well_arms_turn_with_space_where_they_are_drawn():
    w = make_world(pw=600, ph=400)
    wl = w.add_super_well(300, 200, 1_000_000)
    w.set_spin(wl, 0.5)
    slow = w.whirl_omega(wl)
    d = 2 * wl.core()
    assert slow == pytest.approx(w.frame_turn(wl.x + d, wl.y)[0]) and slow > 0
    w.set_spin(wl, 1.0)
    assert w.whirl_omega(wl) == pytest.approx(2 * slow)          # twice the spin, twice as fast
    w.set_spin(wl, -1.0)
    assert w.whirl_omega(wl) < 0                                 # and the other way round
