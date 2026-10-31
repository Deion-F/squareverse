"""Physics invariants of the v2 engine. Run from squareverse_v2/:  python -m pytest tests"""

import math

import numpy as np
import pytest

from sv import config
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
    """A 15 x 15 block of particles holding `factor` x the collapse threshold. Returns its mass."""
    m = int(np.ceil(factor * w.collapse_threshold() / 225))
    xs, ys = np.meshgrid(np.arange(x0, x0 + 15), np.arange(y0, y0 + 15))
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
    assert masses.min() == 3 and masses.max() == 9
    check_consistent(w)


def test_sized_well_matches_brush_and_weighs_its_area():
    w = make_world()                      # 2 px cells
    small = w.add_sized_well(100, 80, 24)
    big = w.add_sized_well(100, 80, 48, pour_mass=64)
    ranged = w.add_sized_well(100, 80, 24, pour_mass=(1, 9))
    assert small.radius == 12 and big.radius == 24 and w.well_radius_px(small) == 24
    assert small.mass == pytest.approx(np.pi * 144 * config.WELL_DENSITY)
    assert big.mass == pytest.approx(small.mass * 4 * 64)
    assert ranged.mass == pytest.approx(small.mass * 5)   # a pour range counts as its middle
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


def test_collapse_threshold_follows_gravity_scale():
    w = make_world()
    t = w.collapse_threshold()
    w.scale_gravity(2.0)
    assert w.collapse_threshold() == t / 2
    w.add_super_well(50, 50)
    assert w.wells[0].mass == round(t / 2)


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


def test_heavy_wells_move_slower():
    moved = {}
    for mass in (5000.0, 500000.0):
        w = make_world(pw=400, ph=200)
        w.held = w.add_well(200, 100, 300000.0)        # the same pull for both, held in place
        probe = w.add_well(100, 100, mass)
        run(w, 15)
        moved[mass] = probe.x - 50
    assert moved[5000.0] > 10 * moved[500000.0] > 0


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
    w.add_super_well(250, 100, 6000)
    run(w, 300)
    assert w.wells == [sw]
    assert sw.mass + w.total_mass() == 108000      # the super well merger spat some out as particles


def test_wells_feel_particles_with_self_gravity():
    w = make_world(pw=400, ph=200)
    w.sg_on = True
    xs, ys = np.meshgrid(np.arange(150, 190), np.arange(30, 70))
    w.place_many(xs.ravel(), ys.ravel(), 64)
    wl = w.add_well(100, 100, 1000.0)
    run(w, 40)
    assert wl.vx > 0
    w2 = make_world(pw=400, ph=200)       # without self-gravity, particles don't pull wells
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


def test_super_wells_with_overlapping_ranges_merge_and_eject():
    w = make_world(pw=600, ph=400)
    a = w.add_super_well(200, 200, 480000)
    b = w.add_super_well(400, 200, 320000)
    assert math.hypot(a.x - b.x, a.y - b.y) < w.well_range(a) + w.well_range(b)
    run(w, 60)                                      # "rapidly": within a second at 60 ticks/s
    assert w.wells == [a]
    ejected = w.total_mass()
    assert a.mass + ejected == 800000
    assert 0.01 * 800000 * 0.9 <= ejected <= 0.10 * 800000


def test_far_apart_super_wells_dont_merge():
    w = make_world(pw=1600, ph=400)
    a = w.add_super_well(100, 200, 10000)
    b = w.add_super_well(1500, 200, 10000)
    assert math.hypot(a.x - b.x, a.y - b.y) > w.well_range(a) + w.well_range(b)
    run(w, 60)
    assert len(w.wells) == 2


def test_collapse_ejects_a_share():
    w = make_world()
    w.merge_on = w.split_on = False
    w.collapse_on = True
    total = dense_patch(w)
    run(w, config.COLLAPSE_EVERY)
    sw = w.wells[0]
    assert sw.mass + w.total_mass() == total
    assert 0.65 * total <= sw.mass <= 0.90 * total  # 10-30% ejected (a little more stays out if cells were taken)


@pytest.mark.parametrize("mass", [20000, 400000])
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


def test_super_well_range_is_a_share_of_its_reach():
    w = make_world()
    sw = w.add_super_well(100, 80, 50000)
    assert w.well_range(sw) == pytest.approx(config.SUPER_RANGE_FACTOR * w.reach(sw))
    assert w.collapse_threshold() == config.COLLAPSE_MASS == 40000


def test_planet_pushes_particles_out_and_stays_solid():
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False
    xs, ys = np.meshgrid(np.arange(80, 120), np.arange(80, 120))
    w.place_many(xs.ravel(), ys.ravel(), 4)          # a block of particles where the planet will be
    before, count = w.total_mass(), w.particle_count()
    planet = w.add_sized_well(200, 200, 24)          # radius 12 cells at (100, 100)
    run(w, 1)
    assert w.total_mass() == before and w.particle_count() == count
    assert not w.mass[w.solid > 0].any()
    assert np.count_nonzero(w.solid) > 400
    run(w, 300)
    assert not w.mass[w.solid > 0].any()           # nothing ever gets inside
    idx = np.nonzero(w.mass)[0]
    r = np.hypot(idx % w.w - planet.x, idx // w.w - planet.y)
    assert np.median(r) < planet.radius + 25       # they settle on the surface as a crust


def test_planet_ground_holds_particles_up():
    w = make_world(pw=400, ph=400)
    w.add_sized_well(200, 200, 24)
    w.place_many([100], [40], [1])                   # falls straight onto the planet from above
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
    run(w, 100)
    assert wl.vy > 0                                 # clockwise on screen: right of centre moves down


def test_colliding_planets_rebound_shed_debris_and_shrink():
    w = make_world(pw=600, ph=400)
    w.merge_on = w.split_on = w.collapse_on = False
    a = w.add_well(200, 200, 60000.0, radius=12.0, vx=1.5)     # heading right
    b = w.add_well(400, 200, 30000.0, radius=8.0, vx=-1.5)     # half as heavy, heading left
    ra, rb, ma, mb = a.radius, b.radius, a.mass, b.mass
    before = ma + mb
    hit = False
    for _ in range(100):
        w.step()
        if a.mass < ma:
            hit = True
            break
    assert hit and len(w.wells) == 2
    assert a.vx < 0 < b.vx                           # bounced back the way they came
    assert a.mass + b.mass + w.total_mass() == pytest.approx(before)
    assert w.particle_count() > 0                    # debris
    assert (mb - b.mass) == pytest.approx(2 * (ma - a.mass), rel=0.05)   # half the size: loses twice as much
    assert a.radius < ra and b.radius < rb
    assert b.radius == pytest.approx(rb * math.sqrt(b.mass / mb))


def test_gently_touching_planets_shed_nothing():
    w = make_world(pw=600, ph=400)
    w.merge_on = w.split_on = w.collapse_on = False
    a = w.add_well(200, 200, 60000.0, radius=12.0)
    b = w.add_well(241, 200, 60000.0, radius=8.0)            # just touching, at rest
    run(w, 1)
    assert w.particle_count() == 0 and a.mass == 60000.0 and b.mass == 60000.0


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


def test_wrap_planet_body_spans_the_edge_and_wells_cross_it():
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
        counts.append(w.particle_count())
        assert counts[-1] == pytest.approx(100 * sp.rate, rel=0.25)
    assert counts[1] == pytest.approx(4 * counts[0], rel=0.3)


def test_spawner_falls_through_everything_under_gravity():
    w = make_world(pw=400, ph=400)
    w.set_gravity(0)
    w.add_sized_well(200, 300, 30)                   # a planet in the way
    sp = w.add_spawner(200, 40, 8)
    run(w, 40)
    assert sp.y > 150 and sp.vy > 0                  # fell straight through the planet (radius 15 at y = 150)


def test_locked_spawner_stays_put():
    w = make_world(pw=400, ph=400)
    w.set_gravity(0)
    w.add_well(300, 200, 100000.0)
    sp = w.add_spawner(100, 100, 8, locked=True)
    run(w, 40)
    assert (sp.x, sp.y, sp.vx, sp.vy) == (50.0, 50.0, 0.0, 0.0)
    assert w.particle_count() > 0


def test_super_well_deletes_spawner():
    w = make_world(pw=400, ph=400)
    w.add_super_well(200, 200, 200000).spin = 0       # no spin: it falls straight in
    w.add_spawner(260, 200, 4)
    run(w, 100)
    assert not w.spawners
    n = w.particle_count()
    run(w, 20)
    assert w.particle_count() <= n                   # nothing new pours in


def test_spawner_random_masses():
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = False
    w.add_spawner(200, 200, 30, pour_mass=(5, 9), locked=True)
    run(w, 30)
    m = w.mass[w.mass > 0]
    assert m.min() == 5 and m.max() == 9


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
    a = w.add_super_well(200, 200, 480000)
    b = w.add_super_well(400, 200, 240000)
    run(w, 60)
    assert w.wells == [a] and a.mass + w.total_mass() == 720000


def test_spin_curves_infall_so_some_matter_misses():
    swallowed = {}
    for spin in (0.0, config.SUPER_SWIRL_SPEED):
        config.SUPER_SWIRL_SPEED, saved = spin, config.SUPER_SWIRL_SPEED
        try:
            w = make_world(pw=600, ph=600)
            w.merge_on = w.split_on = False
            sw = w.add_super_well(300, 300, 1000000)
            sw.spin = 1.0
            w.held = sw                              # keep it still for the test
            w.rebuild_field()
            rng = np.random.default_rng(0)
            r = rng.uniform(20, 0.9 * w.well_range(sw), 50)
            a = rng.uniform(0, 2 * np.pi, 50)
            w.place_many(np.round(150 + r * np.cos(a)), np.round(150 + r * np.sin(a)), 1,
                         rng.normal(0, 0.3, 50), rng.normal(0, 0.3, 50))
            n0 = w.particle_count()
            run(w, 600)
            swallowed[spin] = 1 - w.particle_count() / n0
        finally:
            config.SUPER_SWIRL_SPEED = saved
    assert swallowed[0.0] > 0.95                     # no spin: everything falls straight in
    assert swallowed[config.SUPER_SWIRL_SPEED] < 0.85   # whirling: a good share misses and stays in orbit


def test_collapse_spin_follows_the_matter():
    w = make_world()
    w.merge_on = w.split_on = False
    w.collapse_on = True
    dense_patch(w)
    idx = np.nonzero(w.mass)[0]
    rx, ry = idx % w.w - 47.0, idx // w.w - 37.0
    w.kin[idx, 0], w.kin[idx, 1] = -0.01 * ry, 0.01 * rx     # turning (slowly) clockwise on screen
    run(w, config.COLLAPSE_EVERY)
    assert w.wells[0].spin > 0


def test_disk_preset_settings_and_presets_reset_them():
    from sv.presets import disk, rain
    w = make_world(pw=400, ph=300)
    disk(w)
    assert not w.wells and w.orbit == 1 and w.sg_on and w.wrap and w.g_scale == 0.8
    assert w.particle_count() > 1000
    rain(w)
    assert w.orbit == config.ORBIT and w.wrap == config.WRAP and w.g_scale == config.GRAVITY_SCALE


def test_super_well_pulls_beyond_its_dotted_circle():
    w = make_world(pw=800, ph=400)
    w.merge_on = w.split_on = w.collapse_on = False
    sw = w.add_super_well(200, 200, 100000)
    w.held = sw
    w.rebuild_field()
    start = 100 + 3 * w.well_range(sw)               # three times its range away (cells)
    w.place_many([round(start)], [100], [1])
    run(w, 60)
    i = np.nonzero(w.mass)[0][0]
    assert i % w.w < start - 3                       # pulled in by the inverse-square law


@pytest.mark.parametrize("omega", [0.0, 0.02, -0.02])
def test_spinning_planet_carries_its_crust(omega):
    w = make_world(pw=400, ph=400)
    w.merge_on = w.split_on = w.collapse_on = False
    planet = w.add_well(200, 200, 200000.0, radius=20.0)
    planet.omega = omega
    w.held = planet                                  # keep it in place
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
    run(w, 60)
    assert w.wells == [a] and 0 < a.spin < 0.5     # opposite spins partly cancel


def test_global_orbit_keeps_everything_moving_without_piling_in_the_middle():
    w = make_world(pw=600, ph=600)
    w.merge_on = w.split_on = False
    rng = np.random.default_rng(0)
    n = int(w.n * 0.4)                               # a dense disc that fits inside the walls
    r = 140 * np.sqrt(rng.uniform(0, 1, n))
    a = rng.uniform(0, 2 * np.pi, n)
    w.place_many(np.round(150 + r * np.cos(a)), np.round(150 + r * np.sin(a)), rng.choice([1, 4, 16], n))
    w.set_orbit(1)
    run(w, 600)
    idx = np.nonzero(w.mass)[0]
    r = np.hypot(idx % w.w - w.w / 2, idx // w.w - w.h / 2)
    speed = np.hypot(w.kin[idx, 0], w.kin[idx, 1])
    assert (speed < 0.1).mean() < 0.05               # practically nothing at rest
    near = (30 / 140) ** 2                           # share of the disc within 30 cells of the centre
    assert (r < 30).mean() < 1.5 * near              # no pile in the middle


def test_whirlpool_is_gentle_at_the_edge_and_overwhelming_at_the_core():
    w = make_world(pw=600, ph=600)
    w.merge_on = w.split_on = w.collapse_on = False
    sw = w.add_super_well(300, 300, 1000000)
    sw.spin = 1.0
    w.held = sw
    w.rebuild_field()
    reach = w.well_range(sw)
    near, edge = 150 + sw.core() + 4, 150 + 0.9 * reach
    w.place_many([round(near), round(edge)], [150, 150], [1, 1])
    run(w, 2)                                        # (the one beside the core is swallowed soon after)
    idx = np.nonzero(w.mass)[0]
    assert idx.size == 2
    x = idx % w.w
    near_v = w.kin[idx[np.argmin(x)], 1]             # right of the centre, clockwise = moving down
    edge_v = w.kin[idx[np.argmax(x)], 1]
    assert near_v > 0.7                              # whirled hard straight away beside the core
    assert 0 <= edge_v < 0.01                        # barely touched near the edge of its range
