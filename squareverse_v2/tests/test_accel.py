"""Acceleration (World.accelerate): the strip tick on all cores, the parallel kernels, and the GPU. Run from
squareverse_v2/:  python -m pytest tests"""

import time

import numpy as np
import pytest

from sv import config, gpu, kernels
from sv.gpu import Chooser
from sv.gravity import external_field
from sv.presets import rain
from sv.world import World


def make_world(seed=1, pw=400, ph=320, cell=2, cores=True):
    w = World(pw, ph, cell, seed=seed)
    w.collapse_on = False
    if cores:
        w.accelerate(cores=True)
    return w


def check_consistent(w):
    assert (w.quad.sum(axis=1)[w.mass > 0] == w.mass[w.mass > 0]).all(), "children must sum to mass"
    assert w.mass.max() <= config.MAX_MASS


@pytest.fixture(scope="module")
def device():
    g, why = gpu.open_device()
    if g is None:
        pytest.skip(f"no GPU: {why}")
    return g


def test_a_new_world_runs_as_before():
    w = World(200, 160, 2, seed=1)
    assert not w.cores and w.gpu is None and w.field_way is None and w.ghost_way is None


@pytest.mark.parametrize("gdir, wrap, orbit", [(None, False, 0), (0, False, 0), (2, True, 0), (None, True, 1)])
def test_strips_conserve_mass_and_children(gdir, wrap, orbit):
    w = make_world()
    w.set_gravity(gdir)
    w.set_wrap(wrap)
    w.set_orbit(orbit)
    w.merge_on = w.split_on = True
    w.star_form_on = False                # stars' fusion changes the count too: only merges and splits here
    w.add_well(200, 160, 200000.0)        # heavy well: fast impacts, so splits really happen
    rng = np.random.default_rng(0)
    w.place_many(rng.integers(0, w.w, 6000), rng.integers(0, w.h, 6000), rng.choice([1, 4, 16], 6000))
    m0, n0 = w.total_mass(), w.particle_count()
    merges = splits = 0
    for _ in range(300):
        w.step()
        merges += w.stats[kernels.S_MERGES]
        splits += w.stats[kernels.S_SPLITS]
    assert w.strips is not None, "the universe is wide enough for strips"
    nx, ny = w.strips["shape"]
    assert (nx, ny) == ((w.w // 64 // 2 * 2, 1) if gdir == 0 else (1, w.h // config.STRIP_SIZE // 2 * 2))
    check_consistent(w)
    assert merges > 0 and splits > 0
    assert w.total_mass() == m0
    assert w.particle_count() == n0 - merges + splits


def test_strips_run_every_awake_particle_once():
    w = make_world()
    rain(w)
    for _ in range(20):
        awake = int(np.count_nonzero(w.flag.astype(bool) & (w.mass > 0)))
        w.step()
        assert w.n_awake == awake
        assert (w.stamp[w.mass > 0] >> 1 <= w.tick_count).all()


def test_strips_keep_a_star_together_and_its_mass():
    w = make_world(pw=600, ph=400)
    w.merge_on = w.split_on = False                  # (no fusing in it: just how the strips carry it)
    st = w.add_star(300, 200, 40, mass=30000)
    count, x, y = st.count, st.x, st.y
    m0 = w.total_mass() + w.super_mass()
    for _ in range(200):
        w.step()
    assert w.stars == [st] and st.count == count                     # it keeps all its particles...
    assert abs(st.x - x) < 0.5 and abs(st.y - y) < 0.5                # ...and its place
    assert w.total_mass() + w.super_mass() == m0


def test_strips_fall_back_to_one_core_when_too_small():
    w = make_world(pw=128, ph=128, cell=4)          # 32 x 32 cells: too small to cut in two
    rain(w)
    for _ in range(5):
        w.step()
    assert w.strips is None and w.n_awake > 0


def test_parallel_ghosts_match_one_core():
    w = make_world(pw=600, ph=400)
    w.set_orbit(1)
    w.add_super_well(300, 200, 200000)
    w.add_star(150, 200, 30, mass=20000)
    w.step()
    w.pour_ghosts(100, 100, 60, (1, 64))
    w.pour_ghosts(450, 300, 60, 4)
    params, whirls = w.params(), w.whirls()
    w._star_field()
    g = (w.ghost_x, w.ghost_y, w.ghost_vx, w.ghost_vy, w.ghost_m, w.ghost_age)
    a, b = [x.copy() for x in g], [x.copy() for x in g]
    absorbed = [np.zeros((len(w.wells), 6)) for _ in range(2)]
    swallowed = []
    for state, ab, fn in ((a, absorbed[0], kernels.step_ghosts), (b, absorbed[1], kernels.step_ghosts_par)):
        for _ in range(60):
            swallowed.append(fn(*state, w.w, w.h, params, w.fx, w.fy, w.sg.gx, w.sg.gy, w.sg.block, w.sg.cw, w.hole,
                                ab, whirls, w.star_pulls, w.sfx, w.sfy, config.STAR_FIELD_BLOCK, w.scw, w.sch))
    assert all((x == y).all() for x, y in zip(a, b))
    assert (absorbed[0] == absorbed[1]).all() and absorbed[0][:, 0].sum() > 0     # (mass swallowed)
    assert sum(swallowed[:60]) == sum(swallowed[60:])


def test_parallel_helpers_match_one_core():
    rng = np.random.default_rng(3)
    edges = np.sort(rng.normal(size=999))
    values = rng.normal(size=50000)
    out = np.empty(values.size, np.uint16)
    kernels.bucketize(edges, values, out)
    assert (out == np.searchsorted(edges, values)).all()

    w, h = 300, 200
    mass = (rng.random(w * h) < 0.5).astype(np.uint16)
    for wrap, (cx, cy, r) in ((False, (10.5, 190.0, 40.0)), (True, (5.0, 3.0, 60.0)), (True, (150.0, 100.0, 140.0))):
        a, b = np.zeros(w * h, np.uint8), np.zeros(w * h, np.uint8)
        kernels.wake_disk(cx, cy, r, w, h, mass, a, wrap)
        kernels.wake_disk_par(cx, cy, r, w, h, mass, b, wrap)
        assert (a == b).all() and a.any()

    bucket = rng.integers(0, 40, 100000).astype(np.uint16)
    for tick in (1, 2):
        for n in (0, 1, 9, 3000):
            cur = np.zeros(100010, np.int32)
            cur[10:10 + n] = rng.choice(100000, n, replace=False)
            a, b = np.zeros_like(cur), np.zeros_like(cur)
            kernels._sort_by_bucket(cur, 10, n, bucket, np.zeros(41, np.int64), a, tick)
            kernels._sort_by_key(cur, 10, n, bucket, b, tick)
            assert (a == b).all()


def test_chooser_keeps_the_faster_way_and_times_again_when_the_job_grows():
    calls = []

    def way(name, ms):
        def run(n):
            calls.append(name)
            time.sleep(ms / 1000)
            return name
        return run

    c = Chooser({"slow": way("slow", 4), "fast": way("fast", 0)}, size_of=lambda n: n)
    for _ in range(2 * (Chooser.TRIALS + 1)):
        c(100)
    assert c.choice == "fast" and c.ms["slow"] > c.ms["fast"]
    calls.clear()
    for _ in range(10):
        assert c(150) == "fast"                      # within 2x of the size it was timed at: no new trials
    assert calls == ["fast"] * 10
    c(1000)                                          # much bigger: both are timed again
    assert c.plan and "slow" in calls[10:] + c.plan

    forced = Chooser({"slow": way("slow", 0), "fast": way("fast", 0)}, force="slow", size_of=lambda n: n)
    assert all(forced(n) == "slow" for n in (1, 1000, 10 ** 6))


@pytest.mark.parametrize("wrap", [False, True])
def test_gpu_field_matches_the_cpu(device, wrap):
    rows = [(20.0, 30.0, 40.0, 3.0), (180.0, 100.0, 500.0, 12.0), (3.0, 150.0, -60.0, 2.0)]
    args = (200, 160, rows, (0.03, -0.1), wrap, 1 / 30)
    cpu = external_field(*args)
    gpu_ = external_field(*args, gpu=device)
    for c, g in zip(cpu, gpu_):
        assert np.abs(g - c).max() < 1e-4 * max(1.0, np.abs(c).max())


def test_gpu_ghosts_match_the_cpu(device):
    w = make_world(pw=600, ph=400)
    w.set_orbit(1)
    w.set_wrap(True)
    w.add_super_well(300, 200, 200000)
    w.add_star(150, 200, 30, mass=20000)
    w.step()
    w.pour_ghosts(100, 100, 60, (1, 64))
    params, whirls = w.params(), w.whirls()
    w._star_field()
    g = (w.ghost_x, w.ghost_y, w.ghost_vx, w.ghost_vy, w.ghost_m, w.ghost_age)
    a, b = [x.copy() for x in g], [x.copy() for x in g]
    rest = (w.w, w.h, params, w.fx, w.fy, w.sg.gx, w.sg.gy, w.sg.block, w.sg.cw, w.hole)
    tail = (whirls, w.star_pulls, w.sfx, w.sfy, config.STAR_FIELD_BLOCK, w.scw, w.sch)
    absorbed = [np.zeros((len(w.wells), 6)) for _ in range(2)]
    kernels.step_ghosts(*a, *rest, absorbed[0], *tail)
    device.step_ghosts(*b, *rest, absorbed[1], *tail)
    assert np.abs(a[0] - b[0]).max() < 1e-3 and np.abs(a[1] - b[1]).max() < 1e-3
    assert np.abs(a[2] - b[2]).max() < 1e-4 and np.abs(a[3] - b[3]).max() < 1e-4
    assert (a[5] == b[5]).all()


def test_world_on_the_gpu_conserves_mass(device):
    w = make_world(pw=600, ph=400, cores=False)
    w.accelerate(cores=True, gpu=device, force_gpu=True)
    w.set_wrap(True)
    rain(w)
    w.set_gravity(None)
    w.add_super_well(300, 200, 200000)
    w.pour_ghosts(100, 100, 40, 4)
    m0 = w.total_mass() + w.super_mass() + w.ghost_mass()
    for _ in range(100):
        w.step()
    assert w.where_work_runs()[1][1] == "GPU" and w.where_work_runs()[2][1] == "GPU"
    assert w.total_mass() + w.super_mass() + w.ghost_mass() == m0
    check_consistent(w)


def test_chooser_drops_a_way_that_fails():
    def broken(n):
        raise RuntimeError("device lost")

    c = Chooser({"gpu": broken, "cpu": lambda n: n + 1}, force="gpu")
    with pytest.warns(UserWarning, match="gpu failed"):
        assert c(1) == 2
    assert c.choice == "cpu" and list(c.ways) == ["cpu"] and c(5) == 6


def test_parallel_render_and_occupied_cells_match_one_core():
    w = make_world()
    rain(w)
    w.add_ghosts(np.array([10.0, 50.0]), np.array([10.0, 60.0]), np.array([4, 64]))
    for _ in range(5):
        w.step()
    for chunks in (1, 7, 64):
        assert (kernels.occupied_par(w.mass, chunks) == np.flatnonzero(w.mass)).all()
    for mode in range(4):
        a = w.render(mode).copy()
        w.cores = False
        b = w.render(mode).copy()
        w.cores = True
        assert (a == b).all()


def test_self_gravity_mesh_padding_is_a_fast_fft_length_and_changes_nothing():
    from sv.gravity import SelfGravity, fast_len
    assert [fast_len(n) for n in (1, 7, 542, 576, 1000)] == [1, 8, 576, 576, 1000]
    rng = np.random.default_rng(0)
    w, h = 1082, 1082                                  # 271 blocks a side: the mesh used to be padded to 542
    mass = np.zeros(w * h, np.uint16)
    mass[rng.integers(0, w * h, 20000)] = rng.integers(1, 256, 20000)
    fast = SelfGravity(w, h, kinv=1 / 20)
    assert fast._pad.shape == (576, 576)
    fast.update(mass, 0.002)
    exact = SelfGravity(w, h, kinv=1 / 20)
    py = px = 2 * exact.ch                             # the old padding: just twice the mesh
    iy = np.minimum(np.arange(py), py - np.arange(py))
    r = exact.block * np.hypot(iy[:, None], iy[None, :])
    rho = np.sqrt(r * r + (config.SG_SOFTENING * exact.block) ** 2)
    from sv.gravity import fade
    exact.green_hat = np.fft.rfft2(-fade(rho, 1 / 20)[1] / rho)
    exact._pad = np.zeros((py, px))
    exact.update(mass, 0.002)
    assert np.allclose(fast.gx, exact.gx, atol=1e-6) and np.allclose(fast.gy, exact.gy, atol=1e-6)


def test_heat_from_every_strip_is_sent_out():
    w = make_world()
    w.radiation_on = w.merge_on = w.split_on = True
    w.add_well(200, 160, 400000.0)
    rng = np.random.default_rng(0)
    w.place_many(rng.integers(0, w.w, 6000), rng.integers(0, w.h, 6000), rng.choice([16, 64, 256], 6000))
    m0 = w.universe_mass()
    made = 0
    for _ in range(200):
        w.step()
        made += w.heat_made
        assert w.heat_made == 0 or w.strips is not None
    assert made > 0 and w.universe_mass() == m0
