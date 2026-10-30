"""The World: owns the particle arrays, wells and toggles, and drives the kernels."""

import math
import time

import numpy as np

from . import config, kernels, palette
from .gravity import SelfGravity, external_field, order_buckets

# Global gravity directions, clockwise on screen starting from "down" (sand.py).
DIRS = [(0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1)]
DIR_NAMES = ["down", "down-left", "left", "up-left", "up", "up-right", "right", "down-right"]
VIEW_MODES = ["mass", "speed", "children", "awake"]


class World:
    def __init__(self, pw, ph, cell=config.DEFAULT_CELL, seed=None):
        self.pw, self.ph = pw, ph
        self.rng = np.random.default_rng(seed)
        kernels.seed(int(self.rng.integers(2 ** 31)))
        self.wells = []             # [x, y, strength] in cell units
        self.gdir = None            # index into DIRS, or None for no global gravity
        self.g = config.GLOBAL_G
        self.sg_on = config.SG_ON
        self.sg_g = config.SG_G
        self.merge_on = config.MERGE_ON
        self.split_on = config.SPLIT_ON
        self.lean_on = config.LEAN_ON
        self.tick_count = 0
        self.stats = np.zeros(kernels.N_STATS, np.int64)
        self.step_ms = 0.0
        self.gravity_ms = 0.0
        self.mass_lut = palette.mass_lut()
        self.heat_lut = palette.heat_lut()
        self.shade_mul = palette.shade_mul()
        self.bg = np.array(config.BG, np.uint8)
        self._alloc(cell)

    def _alloc(self, cell):
        self.cell = cell
        self.w, self.h = max(1, self.pw // cell), max(1, self.ph // cell)
        n = self.n = self.w * self.h
        self.mass = np.zeros(n, np.uint16)
        self.kin = np.zeros((n, 4), np.float32)
        self.quad = np.zeros((n, 4), np.uint16)
        self.shade = np.zeros(n, np.uint8)
        self.stamp = np.zeros(n, np.uint32)
        self.flag = np.zeros(n, np.uint8)       # 1 = simulate this cell's particle next tick
        self.cur = np.zeros(n, np.int32)        # scratch for the step kernel
        self.order = np.zeros(n, np.int32)
        self.n_awake = 0                        # particles simulated in the last tick
        self.bucket_counts = np.zeros(config.ORDER_BUCKETS + 1, np.int64)
        self.rgb = np.zeros((self.h, self.w, 3), np.uint8)
        self.sg = SelfGravity(self.w, self.h)
        self.field_dirty = True
        self.bucket = None
        self.order_time = 0.0

    # --- parameters / fields ----------------------------------------------------------------------

    def params(self):
        p = np.zeros(kernels.N_PARAMS, np.float64)
        p[kernels.P_VMAX] = config.VMAX
        p[kernels.P_MAX_STEPS] = config.MAX_STEPS
        p[kernels.P_WALL_E] = config.WALL_E
        p[kernels.P_E] = config.RESTITUTION
        p[kernels.P_IMPACT_MIN] = config.IMPACT_MIN
        p[kernels.P_SLIDE_DAMP] = config.SLIDE_DAMP
        p[kernels.P_SINK] = config.SINK_CHANCE
        p[kernels.P_DRAG] = config.DRAG
        p[kernels.P_SLEEP_EPS] = config.SLEEP_EPS
        p[kernels.P_CHILD_MOVES] = config.CHILD_MOVES
        p[kernels.P_CHILD_EVERY] = config.CHILD_EVERY
        p[kernels.P_SLOSH] = config.SLOSH
        p[kernels.P_LEAN] = config.LEAN if self.lean_on else 0.0
        p[kernels.P_MERGE_ON] = self.merge_on
        p[kernels.P_STICK] = config.STICK_SPEED
        p[kernels.P_MERGE_CHANCE] = config.MERGE_CHANCE
        p[kernels.P_MAX_MASS] = config.MAX_MASS
        p[kernels.P_SPLIT_ON] = self.split_on
        p[kernels.P_BIND] = config.BIND
        p[kernels.P_KICK] = config.SPLIT_KICK
        p[kernels.P_SG_ON] = self.sg_on
        return p

    def gravity_vector(self):
        if self.gdir is None:
            return None
        dx, dy = DIRS[self.gdir]
        k = self.g / math.hypot(dx, dy)
        return dx * k, dy * k

    def rebuild_field(self):
        wells = [(x, y, s, config.WELL_SOFTENING) for x, y, s in self.wells]
        self.fx, self.fy, self.phi = external_field(self.w, self.h, wells, self.gravity_vector())
        self.field_dirty = False
        self.order_dirty = True
        self.wake_all()

    def rebuild_order(self):
        self.bucket = order_buckets(self.phi, self.rng)
        self.order_dirty = False
        self.order_time = time.perf_counter()

    # --- simulation -------------------------------------------------------------------------------

    def step(self):
        t0 = time.perf_counter()
        if self.field_dirty:
            self.rebuild_field()
        # the processing order lags a little while a well is being dragged: it only affects efficiency
        if self.order_dirty and time.perf_counter() - self.order_time > 0.3 or self.bucket is None:
            self.rebuild_order()
        if self.sg_on and self.tick_count % config.SG_EVERY == 0:
            changed = self.sg.update(self.mass, self.sg_g)
            kernels.wake_blocks(changed, self.sg.block, self.sg.cw, self.w, self.h, self.mass, self.flag)
        t1 = time.perf_counter()
        self.tick_count += 1
        self.stats[:] = 0
        self.n_awake = kernels.step(self.w, self.h, self.tick_count, self.params(), self.mass, self.kin, self.quad,
                                    self.shade, self.stamp, self.flag, self.cur, self.order, self.bucket_counts,
                                    self.bucket, self.fx, self.fy, self.sg.gx, self.sg.gy, self.sg.block, self.sg.cw,
                                    self.stats)
        t2 = time.perf_counter()
        self.gravity_ms = (t1 - t0) * 1000
        self.step_ms = (t2 - t1) * 1000

    def render(self, mode=0):
        kernels.render(mode, self.mass, self.kin, self.quad, self.shade, self.flag, self.mass_lut, self.heat_lut,
                       self.shade_mul, self.bg, config.VMAX, self.rgb.reshape(-1, 3))
        return self.rgb

    # --- editing ----------------------------------------------------------------------------------

    def wake_all(self):
        kernels.wake_all(self.mass, self.flag)

    def brush(self, px, py, radius_px, m):
        """Pour (m > 0) or erase (m == 0) in a circle around a pixel."""
        c = self.cell
        kernels.brush(px // c, py // c, max(0.5, radius_px / c), m, config.POUR_CHANCE, self.w, self.h,
                      self.mass, self.kin, self.quad, self.shade, self.stamp, self.flag)

    def place_many(self, xs, ys, masses, vxs=None, vys=None):
        """Place particles at cell coordinates (arrays). Out-of-bounds and occupied cells are skipped."""
        xs = np.asarray(xs).astype(np.int64)
        ys = np.asarray(ys).astype(np.int64)
        ok = (xs >= 0) & (xs < self.w) & (ys >= 0) & (ys < self.h)
        n = xs.size
        masses = np.broadcast_to(np.asarray(masses, np.int64), n)[ok]
        vxs = np.broadcast_to(np.asarray(0.0 if vxs is None else vxs, np.float64), n)[ok]
        vys = np.broadcast_to(np.asarray(0.0 if vys is None else vys, np.float64), n)[ok]
        idx = ys[ok] * self.w + xs[ok]
        return kernels.place_many(idx, masses, vxs, vys, self.mass, self.kin, self.quad, self.shade, self.stamp,
                                  self.flag)

    def clear(self):
        self.mass[:] = 0
        self.kin[:] = 0
        self.quad[:] = 0
        self.flag[:] = 0
        self.n_awake = 0
        self.sg.reset()

    def reset(self):
        """Empty world with default settings (used by presets)."""
        self.clear()
        self.wells.clear()
        self.gdir = None
        self.sg_on = config.SG_ON
        self.merge_on = config.MERGE_ON
        self.split_on = config.SPLIT_ON
        self.field_dirty = True

    def set_cell(self, cell):
        """Change the square size, resampling the scene so it keeps its shape (sand.py World.resize)."""
        old_cell, ow = self.cell, self.w
        old = (self.mass, self.kin, self.quad, self.shade)
        self._alloc(cell)
        ox = np.minimum((np.arange(self.w) * cell + cell // 2) // old_cell, ow - 1)
        oy = np.minimum((np.arange(self.h) * cell + cell // 2) // old_cell, old[0].size // ow - 1)
        src = (oy[:, None] * ow + ox[None, :]).ravel()
        self.mass[:] = old[0][src]
        self.kin[:] = old[1][src]
        self.kin[:, :2] *= old_cell / cell
        self.kin[:, 2:] = 0.0
        self.quad[:] = old[2][src]
        self.shade[:] = old[3][src]
        scale = old_cell / cell
        self.wells = [[x * scale, y * scale, s] for x, y, s in self.wells]

    # --- wells ------------------------------------------------------------------------------------

    def add_well(self, px, py, strength):
        self.wells.append([px / self.cell, py / self.cell, strength])
        self.field_dirty = True

    def nearest_well(self, px, py, max_px=None):
        best, best_d = None, max_px if max_px is not None else math.inf
        for k, (x, y, _) in enumerate(self.wells):
            d = math.hypot(x * self.cell - px, y * self.cell - py)
            if d < best_d:
                best, best_d = k, d
        return best

    def move_well(self, k, px, py):
        self.wells[k][0] = px / self.cell
        self.wells[k][1] = py / self.cell
        self.field_dirty = True

    def remove_well(self, k):
        del self.wells[k]
        self.field_dirty = True

    def scale_well(self, k, factor):
        self.wells[k][2] *= factor
        self.field_dirty = True

    def set_gravity(self, gdir):
        self.gdir = gdir
        self.field_dirty = True

    def set_self_gravity(self, on):
        self.sg_on = on
        if not on:
            self.sg.reset()
        self.wake_all()

    # --- queries ----------------------------------------------------------------------------------

    def particle_count(self):
        return int(np.count_nonzero(self.mass))

    def total_mass(self):
        return int(self.mass.sum(dtype=np.int64))

    def awake_count(self):
        return self.n_awake

    def particle_at(self, px, py):
        x, y = int(px // self.cell), int(py // self.cell)
        if not (0 <= x < self.w and 0 <= y < self.h):
            return None
        i = y * self.w + x
        if not self.mass[i]:
            return None
        return {"mass": int(self.mass[i]), "v": (float(self.kin[i, 0]), float(self.kin[i, 1])),
                "quad": tuple(int(q) for q in self.quad[i]), "awake": bool(self.flag[i]), "cell": (x, y)}


def warmup():
    """Compile (or load from the disk cache) every kernel on a tiny world so the first real frame doesn't stall."""
    w = World(32, 32, 1, seed=0)
    w.add_well(16, 16, 10.0)
    w.sg_on = w.merge_on = w.split_on = True
    w.brush(16, 8, 6, 4)
    w.brush(16, 8, 2, 0)
    w.place_many([1, 2], [1, 1], [3, 5], [0.5, 0.0], [0.0, 0.5])
    for _ in range(3):
        w.step()
    for mode in range(len(VIEW_MODES)):
        w.render(mode)
