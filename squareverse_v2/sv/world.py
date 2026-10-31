"""The World: owns the particle arrays, wells and toggles, and drives the kernels."""

import math
import time
from dataclasses import dataclass

import numpy as np

from . import config, kernels, palette
from .gravity import SelfGravity, external_field, order_buckets

# Global gravity directions, clockwise on screen starting from "down" (sand.py).
DIRS = [(0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1), (1, 0), (1, 1)]
DIR_NAMES = ["down", "down-left", "left", "up-left", "up", "up-right", "right", "down-right"]
VIEW_MODES = ["mass", "speed", "children", "awake"]


def merge_losses(m1, m2, loss, bias=None):
    """Split the mass two merging super wells lose between them: shares go as mass ** -bias (bias 1: inversely to
    their size), and neither loses more than it has. Returns (loss of the first, loss of the second)."""
    bias = config.MERGE_LOSS_BIAS if bias is None else bias
    w1, w2 = m1 ** -bias, m2 ** -bias
    l1 = loss * w1 / (w1 + w2)
    l1 = min(max(l1, loss - m2), m1)                # if one can't cover its share the other makes up the rest
    return l1, loss - l1


def super_core(mass):
    """Radius (cells) of a super well's absorbing core."""
    return config.SUPER_CORE + config.SUPER_CORE_GROWTH * math.sqrt(mass)


def box_sum(a, r):
    """Sum of a 2-D array over the (2r + 1)-square round each cell (cut off at the edges)."""
    h, w = a.shape
    s = np.zeros((h + 2 * r + 1, w + 2 * r + 1))
    s[r + 1:r + 1 + h, r + 1:r + 1 + w] = a
    s = s.cumsum(0).cumsum(1)
    k = 2 * r + 1
    return s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]


@dataclass(eq=False, slots=True)
class Blast:
    """A supernova's shock front: a ring round (x, y) at radius r (cells) slowing as it nears `reach`, pushing the
    particles it passes. Its debris (ghosts tagged with `tag`) rides the same front. `settled` counts the ticks since
    the front stopped."""
    x: float
    y: float
    r: float
    reach: float
    tag: int
    settled: int = 0

    def speed(self, r):
        """Speed of the front at radius r: SUPER_BLAST_SPEED when it starts, none at its edge."""
        return config.SUPER_BLAST_SPEED * np.sqrt(np.maximum(0.0, 1.0 - np.asarray(r) / self.reach))


@dataclass(eq=False, slots=True)
class Well:
    """A gravity well, in cell units. Its pull is G * mass, the same constant particles attract each other with.

    A normal well has a size (its softening radius); a repulsor (sign -1) pushes instead and stays put. A super well
    swallows every particle and well that reaches its core; its core grows with its mass. Its pull follows the same
    law at every distance; within its range (the dotted circle) it also spins space round. Wells attract each other
    (and, with self-gravity on, feel the particles). Gravity accelerates a star as it does a particle, whatever its
    mass; a super well responds more sluggishly the heavier it is.
    """
    x: float
    y: float
    mass: float
    radius: float = 0.0         # normal well size
    is_super: bool = False
    sign: int = 1               # -1: repulsor
    spin: float = 0.0           # super well: -1..1, > 0 clockwise (it drags space round that way, faster when larger)
    omega: float = 0.0          # star: rotation speed (rad/tick, > 0 clockwise); its surface carries particles
    phase: float = 0.0          # angle it has turned through (for drawing)
    wave: float = -1.0          # star touched by a super well: radius dissolved so far round the contact point
    wave_dx: float = 0.0        #   (offset of the contact point from its centre); < 0 = whole
    wave_dy: float = 0.0
    wave_by: object = None      #   the super well dissolving it
    vx: float = 0.0
    vy: float = 0.0
    merging: bool = False       # super well being drawn into another (its speed isn't capped by its mobility)
    built: tuple = (0.0, 0.0, 0.0)   # (x, y, mass) when the field was last built

    def pull(self):
        return self.sign * config.G * self.mass

    def core(self):
        return super_core(self.mass)

    def body_radius(self):
        """Its drawn body: a star's size, or a super well's core (event horizon)."""
        return self.core() if self.is_super else self.radius

    def mobility(self):
        """How freely it accelerates: 1 for a weightless well, falling towards 0 as it gets heavier."""
        return config.WELL_INERTIA_MASS / (config.WELL_INERTIA_MASS + self.mass)

    def fall(self):
        """How freely gravity accelerates it: a star falls like a particle does, whatever its mass, so it can swing
        into orbit; a super well is as sluggish as its mobility."""
        return self.mobility() if self.is_super else 1.0

    def top_speed(self):
        return config.VMAX * (self.mobility() if self.is_super else 1.0)


@dataclass(eq=False, slots=True)
class Spawner:
    """A massless particle source, in cell units: pours `rate` particles per tick at random spots inside its circle -
    ghosts by default (SPAWNER_GHOSTS), else ordinary particles into free cells - with mass `masses` (a number or a (min, max) range) and its own velocity. It passes through everything.
    Unless locked it falls under gravity like a particle; a super well's core deletes it."""
    x: float
    y: float
    radius: float
    rate: float
    masses: object
    locked: bool = False
    ghosts: bool = config.SPAWNER_GHOSTS   # pours ghosts (see World.add_ghosts) rather than particles
    vx: float = 0.0
    vy: float = 0.0
    debt: float = 0.0           # fractional particles carried over between ticks


class World:
    def __init__(self, pw, ph, cell=config.DEFAULT_CELL, seed=None):
        self.pw, self.ph = pw, ph
        self.rng = np.random.default_rng(seed)
        kernels.seed(int(self.rng.integers(2 ** 31)))
        self.wells = []             # Well objects
        self.spawners = []          # Spawner objects
        self.gdir = None if config.GRAVITY_DIR is None else DIR_NAMES.index(config.GRAVITY_DIR)
        self.g = config.GLOBAL_G
        self.g_scale = config.GRAVITY_SCALE   # multiplies all gravity: global, wells, super wells, self-gravity
        self.collapse_on = config.COLLAPSE_ON
        self.collapses = 0
        self.explosions = 0
        self.blasts = []             # shock fronts of exploding super wells still sweeping or settling
        self.blast_serial = 0
        self.stars_formed = 0
        self.calm_until = 0          # no collapse before this tick (after an explosion)
        self.wrap = config.WRAP     # continuous borders: leaving one side enters from the other
        self.orbit = config.ORBIT   # global orbit: 1 clockwise, -1 counterclockwise, 0 off
        self.sg_on = config.SG_ON
        self.sg_g = config.G
        self.held = None            # the well or spawner being dragged (it ignores gravity meanwhile)
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
        self.ghost_tint = np.array(config.GHOST_TINT, np.int32)
        self._clear_ghosts()
        self._alloc(cell)
        self.orbit_speed = self.orbit_speed_for(config.ORBIT_EDGE_SPEED)   # rad/tick

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
        self.sg = SelfGravity(self.w, self.h, wrap=self.wrap)
        self.hole = np.zeros(n, np.int16)       # super well k's core cells hold k + 1
        self.solid = np.zeros(n, np.uint8)      # 1 inside a normal well's body (star ground)
        self.gvx = np.zeros(n, np.float32)      # velocity of that ground (star motion + spin)
        self.gvy = np.zeros(n, np.float32)
        self.absorbed = np.zeros(1, np.int64)   # mass swallowed per well, collected after each tick
        self.field_dirty = True                 # rebuild the field and wake everything
        self.changed_wells = []                 # wells that moved or grew: rebuild, wake only their reach
        self.bucket = None
        self.angle_rank, self.angle_key, self.phi_rank = None, None, None   # cached ranks for the orbit ordering
        self.cut = 0.0                          # where the orbit ordering's cut is turned to (radians)
        self.order_tick = -10 ** 9

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
        p[kernels.P_SLEEP_ACCEL] = config.SLEEP_ACCEL
        p[kernels.P_WRAP] = self.wrap
        p[kernels.P_CHILD_MOVES] = config.CHILD_MOVES
        p[kernels.P_CHILD_EVERY] = config.CHILD_EVERY
        p[kernels.P_SLOSH] = config.SLOSH
        p[kernels.P_LEAN] = config.LEAN if self.lean_on else 0.0
        p[kernels.P_MERGE_ON] = self.merge_on
        p[kernels.P_MERGE_SPEED] = config.MERGE_SPEED
        p[kernels.P_MERGE_CHANCE] = config.MERGE_CHANCE
        p[kernels.P_MAX_MASS] = config.MAX_MASS
        p[kernels.P_SPLIT_ON] = self.split_on
        p[kernels.P_BIND] = config.BIND
        p[kernels.P_SPLIT_SPEED] = config.SPLIT_SPEED
        p[kernels.P_KICK] = config.SPLIT_KICK
        p[kernels.P_SG_ON] = self.sg_on
        p[kernels.P_ORBIT_W] = self.orbit * self.orbit_speed
        p[kernels.P_ORBIT_GRIP] = config.ORBIT_GRIP
        p[kernels.P_ORBIT_VMIN] = config.ORBIT_MIN_SPEED
        p[kernels.P_WHIRL_SPEED] = config.SUPER_SWIRL_SPEED
        p[kernels.P_WHIRL_GRIP] = config.SUPER_SWIRL_GRIP
        p[kernels.P_WHIRL_INFALL] = config.SUPER_SWIRL_INFALL
        p[kernels.P_WHIRL_EDGE] = config.SUPER_SWIRL_EDGE
        p[kernels.P_ORBIT_CX], p[kernels.P_ORBIT_CY] = self.w / 2, self.h / 2
        return p

    def gravity_vector(self):
        if self.gdir is None:
            return None
        dx, dy = DIRS[self.gdir]
        k = self.g * self.g_scale / math.hypot(dx, dy)
        return dx * k, dy * k

    def reach(self, well):
        """Distance (cells) at which a well's pull drops to SUPER_RANGE_ACCEL: how far waking particles matters. A
        well's pull goes on beyond it; a super well's range (the dotted circle) is SUPER_RANGE_FACTOR of it."""
        return math.sqrt(self.g_scale * abs(well.pull()) / config.SUPER_RANGE_ACCEL)

    def softening(self, well):
        """Distance (cells) over which a well's pull is softened: a star's size; for a super well a share of its
        range (never less than its core), so its pull near the core stays gentle enough to swing past."""
        if well.is_super:
            return max(well.core(), config.SUPER_SOFTENING * self.well_range(well))
        return well.radius

    def well_range(self, well):
        """A super well's range (cells, the dotted circle): its zone of strong pull, where it spins space round and
        where another super well's range overlapping it draws the two together. 0 for normal wells."""
        return self.reach(well) * config.SUPER_RANGE_FACTOR if well.is_super else 0.0

    def delta(self, ax, ay, bx, by):
        """(bx - ax, by - ay) in cells, the shortest way round when the borders wrap."""
        dx, dy = bx - ax, by - ay
        if self.wrap:
            dx -= self.w * math.floor(dx / self.w + 0.5)
            dy -= self.h * math.floor(dy / self.h + 0.5)
        return dx, dy

    def distance(self, ax, ay, bx, by):
        return math.hypot(*self.delta(ax, ay, bx, by))

    def collapse_threshold(self):
        return config.COLLAPSE_MASS / self.g_scale

    def rebuild_field(self):
        bodies = np.array([(wl.x, wl.y, wl.radius, wl.omega, wl.vx, wl.vy, wl.wave_dx, wl.wave_dy, wl.wave)
                           for wl in self.wells if not wl.is_super], np.float64).reshape(-1, 9)
        kernels.mark_solid(bodies, self.w, self.h, self.solid, self.gvx, self.gvy, self.mass, self.kin, self.quad,
                           self.shade, self.stamp, self.flag, self.wrap)   # also pushes out any particle inside
        self._mark_holes()          # also swallows particles already inside a core
        rows = [(wl.x, wl.y, self.g_scale * wl.pull(), self.softening(wl)) for wl in self.wells]
        self.fx, self.fy, self.phi = external_field(self.w, self.h, rows, self.gravity_vector(), self.wrap)
        if self.field_dirty:
            self.wake_all()
        else:                       # only wells moved or grew: just the particles in their reach can notice
            for wl in self.changed_wells:
                r = self.reach(wl) + 1.0
                for x, y in ((wl.x, wl.y), wl.built[:2]):
                    kernels.wake_disk(x, y, r, self.w, self.h, self.mass, self.flag, self.wrap)
        for wl in self.wells:
            wl.built = (wl.x, wl.y, wl.mass)
        self.field_dirty = False
        self.changed_wells = []
        self.order_dirty = True

    def _mark_holes(self):
        cores = np.array([(k, wl.x, wl.y, wl.core()) for k, wl in enumerate(self.wells) if wl.is_super],
                         np.float64).reshape(-1, 4)
        self.absorbed = np.zeros(max(1, len(self.wells)), np.int64)
        kernels.mark_holes(cores, self.w, self.h, self.hole, self.mass, self.kin, self.quad, self.flag,
                           self.absorbed, self.wrap)
        self._collect_absorbed()

    def _collect_absorbed(self):
        for k in np.nonzero(self.absorbed)[0]:
            wl = self.wells[k]
            wl.mass += int(self.absorbed[k])
            if wl.mass > 1.25 * wl.built[2]:          # grown noticeably: stronger pull, wider range, bigger core
                self.changed_wells.append(wl)
        self.absorbed[:] = 0

    def check_collapse(self):
        """Collapse the heaviest COLLAPSE_BLOCKS-square window of self-gravity blocks into a super well (or into a
        super well already close by) when it holds at least the collapse threshold."""
        sg, k, b = self.sg, config.COLLAPSE_BLOCKS, self.sg.block
        if sg.ch < k or sg.cw < k:
            return
        kernels.bin_mass(self.mass, self.w, self.h, b, sg.cw, sg.rho)
        s = np.zeros((sg.ch + 1, sg.cw + 1))
        s[1:, 1:] = sg.rho.reshape(sg.ch, sg.cw).cumsum(0).cumsum(1)
        window = s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]
        by, bx = np.unravel_index(np.argmax(window), window.shape)
        if window[by, bx] < self.collapse_threshold():
            return
        x0, y0 = bx * b, by * b
        sub = self.mass.reshape(self.h, self.w)[y0:y0 + k * b, x0:x0 + k * b].astype(np.float64)
        ys, xs = np.nonzero(sub)
        wts = sub[ys, xs]
        cx = x0 + (xs * wts).sum() / wts.sum()
        cy = y0 + (ys * wts).sum() / wts.sum()
        mass, px, py, lz = kernels.absorb_disk(cx, cy, k * b / 2 + 2, self.w, self.h, self.mass, self.kin,
                                               self.quad, self.flag, self.wrap)
        near = [wl for wl in self.wells if wl.is_super and self.distance(wl.x, wl.y, cx, cy) < k * b]
        if near:                    # feed it, keeping momentum
            wl = near[0]
            wl.vx = (wl.vx * wl.mass + px) / (wl.mass + mass)
            wl.vy = (wl.vy * wl.mass + py) / (wl.mass + mass)
            wl.mass += int(mass)
        else:                       # a new super well moving with the matter that formed it, spitting some out
            # it spins SUPER_SPIN_NATURAL fast, the way the collapsing matter was turning about its centre of mass
            # (a coin toss if it wasn't)
            way = 1 if lz > 0 else -1 if lz < 0 else int(self.rng.choice((-1, 1)))
            spin = way * config.SUPER_SPIN_NATURAL
            wl = Well(cx, cy, int(mass), is_super=True, spin=spin, vx=px / mass, vy=py / mass,
                      built=(cx, cy, int(mass)))
            self.wells.append(wl)
            self.eject(wl, mass * self.rng.uniform(*config.COLLAPSE_EJECT))
        self.collapses += 1
        self.changed_wells.append(near[0] if near else self.wells[-1])

    def form_stars(self):
        """Turn knots of matter that look like young stars into stars holding their total mass, momentum and spin.
        A knot is found round each of the densest spots (up to STAR_FORM_SEEDS, apart from each other): the largest
        disc round it, STAR_FORM_RADIUS cells across, that is packed (STAR_FORM_FILL) - so it is round and solid in
        the middle - and where the packing ends. It may be part of a larger body, such as a filament. It must be
        layered: a heavy core inside a lighter envelope (see layered()). None forms in or next to a star or
        its crust, near a super well's core, or against a solid border, and at most STAR_FORM_PER_CHECK form at a time."""
        lo, hi = config.STAR_FORM_RADIUS
        b, cw, ch = self.sg.block, self.sg.cw, self.sg.ch
        rho = np.zeros(cw * ch)
        kernels.bin_mass(self.mass, self.w, self.h, b, cw, rho)
        dens = box_sum(rho.reshape(ch, cw), 1)           # mass round each block: heavy, packed knots stand out
        apart, formed = -(-2 * hi // b), 0
        for _ in range(config.STAR_FORM_SEEDS):
            by, bx = np.unravel_index(int(np.argmax(dens)), dens.shape)
            if dens[by, bx] <= 0.0:
                break
            dens[max(0, by - apart):by + apart + 1, max(0, bx - apart):bx + apart + 1] = 0.0
            x, y = self._knot_centre(min(bx * b + b // 2, self.w - 1), min(by * b + b // 2, self.h - 1), 2 * b)
            r = self._packed_radius(x, y, hi + 1)
            if not lo <= r <= hi or self._near_body(x, y, r):
                continue
            if not self.wrap and not (r < x < self.w - 1 - r and r < y < self.h - 1 - r):
                continue                                 # cut off by a solid border: a pile, not a knot
            gx, gy, dx, dy = self._disk_cells(x, y, r)
            idx = gy * self.w + gx
            keep = self.mass[idx] > 0
            if self.layered(idx[keep], np.hypot(dx, dy)[keep] / r):
                self._form_star(idx[keep])
                formed += 1
                if formed >= config.STAR_FORM_PER_CHECK:
                    break

    def _knot_centre(self, x, y, r):
        """The cell at the centre of mass of the particles within r of (x, y), refined twice (a mean shift)."""
        for _ in range(2):
            gx, gy, dx, dy = self._disk_cells(x, y, r)
            m = self.mass[gy * self.w + gx].astype(np.float64)
            if m.sum() <= 0:
                break
            x = int(round(x + (dx * m).sum() / m.sum())) % self.w if self.wrap else \
                min(max(int(round(x + (dx * m).sum() / m.sum())), 0), self.w - 1)
            y = int(round(y + (dy * m).sum() / m.sum())) % self.h if self.wrap else \
                min(max(int(round(y + (dy * m).sum() / m.sum())), 0), self.h - 1)
        return x, y

    def _packed_radius(self, x, y, r_max):
        """The largest radius (cells, whole numbers up to r_max) of a disc round (x, y) at least STAR_FORM_FILL full
        of particles, or 0."""
        gx, gy, dx, dy = self._disk_cells(x, y, r_max)
        ring = np.ceil(np.hypot(dx, dy)).astype(np.int64)            # the smallest whole radius each cell is in
        cells = np.cumsum(np.bincount(ring, minlength=r_max + 1))
        full = np.cumsum(np.bincount(ring, weights=self.mass[gy * self.w + gx] > 0, minlength=r_max + 1))
        packed = full[1:r_max + 1] >= config.STAR_FORM_FILL * np.maximum(cells[1:r_max + 1], 1)
        return r_max if packed.all() else int(np.argmin(packed))

    def _near_body(self, x, y, r):
        """Whether a knot of radius r at (x, y) would touch a star's ground, or come within STAR_FORM_GAP of the crust
        and surroundings of a star (three times its radius) or of a super well's core."""
        gx, gy, _, _ = self._disk_cells(x, y, r + config.STAR_FORM_GAP)
        idx = gy * self.w + gx
        if self.solid[idx].any() or self.hole[idx].any():
            return True
        for wl in self.wells:
            reach = wl.core() if wl.is_super else 3 * wl.radius
            if self.distance(wl.x, wl.y, x, y) < reach + r + config.STAR_FORM_GAP:
                return True
        return False

    def layered(self, idx, r):
        """Whether a knot (cells idx, r = their distance from its middle as a share of its radius) has a heavy core
        inside a lighter envelope: dividing it at some radius, the core's typical (median) mass is at least
        STAR_FORM_LAYER_RATIO x the envelope's, with STAR_FORM_PURITY of each side's particles on its own side of the
        mass between them, and at least STAR_FORM_MIN_LAYER particles in each."""
        lm = np.log(self.mass[idx].astype(np.float64))
        gap, k, pure = math.log(config.STAR_FORM_LAYER_RATIO), config.STAR_FORM_MIN_LAYER, config.STAR_FORM_PURITY
        for f in np.arange(0.3, 0.75, 0.05):
            inner = r <= f
            a, b = lm[inner], lm[~inner]
            if a.size < k or b.size < k:
                continue
            ma, mb = np.median(a), np.median(b)
            if ma - mb < gap:
                continue
            t = (ma + mb) / 2
            if (a > t).mean() >= pure and (b <= t).mean() >= pure:
                return True
        return False

    def _form_star(self, idx):
        m = self.mass[idx].astype(np.float64)
        total = m.sum()
        xs, ys = (idx % self.w).astype(np.float64), (idx // self.w).astype(np.float64)
        cx, cy = (xs * m).sum() / total, (ys * m).sum() / total
        vx, vy = self.kin[idx, 0].astype(np.float64), self.kin[idx, 1].astype(np.float64)
        pvx, pvy = (vx * m).sum() / total, (vy * m).sum() / total
        dx, dy = xs - cx, ys - cy
        inertia = (m * (dx * dx + dy * dy)).sum()
        omega = (m * (dx * (vy - pvy) - dy * (vx - pvx))).sum() / inertia if inertia > 0 else 0.0
        omega = max(-config.STAR_SPIN[1], min(config.STAR_SPIN[1], omega))   # as fast as a placed one at most
        self.mass[idx] = 0
        self.kin[idx] = 0.0
        self.quad[idx] = 0
        radius = math.sqrt(idx.size / math.pi)
        self.wells.append(Well(cx, cy, total, radius, omega=omega, vx=pvx, vy=pvy, built=(cx, cy, total)))
        self.stars_formed += 1
        self.field_dirty = True                          # the new ground is marked and its surroundings woken

    def step_wells(self):
        """Move the wells: they attract each other (and feel the particles when self-gravity is on). Stars fall
        freely, like particles; super wells, and every well's response to the global orbit and the whirlpools, are
        slower the heavier they are. A super well swallows any well that reaches its core."""
        wells = self.wells
        if not wells:
            return
        xs = np.array([wl.x for wl in wells])
        ys = np.array([wl.y for wl in wells])
        pulls = self.g_scale * np.array([wl.pull() for wl in wells])
        soft = np.array([self.softening(wl) for wl in wells])
        sg = self.sg
        for wl in wells:                                # turn (for drawing)
            if wl.is_super:
                wl.phase += math.copysign(min(abs(wl.spin) * config.SUPER_SPIN_VISUAL, config.SUPER_SPIN_VISUAL_MAX),
                                          wl.spin)
            else:
                wl.phase += wl.omega
        for k, wl in enumerate(wells):
            if wl is self.held or wl.sign < 0:
                continue
            dx, dy = xs - wl.x, ys - wl.y
            if self.wrap:
                dx -= self.w * np.floor(dx / self.w + 0.5)
                dy -= self.h * np.floor(dy / self.h + 0.5)
            d2 = dx * dx + dy * dy
            inv = 1.0 / np.sqrt(d2 + soft * soft)
            f = pulls * inv ** 3
            f[k] = 0.0
            ax, ay = float((dx * f).sum()), float((dy * f).sum())
            if self.sg_on:
                b = (min(int(wl.y), self.h - 1) // sg.block) * sg.cw + min(int(wl.x), self.w - 1) // sg.block
                ax += float(sg.gx[b])
                ay += float(sg.gy[b])
            fall = wl.fall()
            wl.vx += ax * fall
            wl.vy += ay * fall
            # the global orbit and the whirlpools drag things round rather than pull them: heavy ones respond slowly
            ox, oy = self._whirl_accel(wl, wl.x, wl.y, wl.vx, wl.vy)
            if self.orbit:
                o2x, o2y = self._orbit_accel(wl.x, wl.y, wl.vx, wl.vy)
                ox += o2x
                oy += o2y
            mob = wl.mobility()
            wl.vx += ox * mob
            wl.vy += oy * mob
            vmax = config.VMAX if wl.merging else wl.top_speed()
            speed = math.hypot(wl.vx, wl.vy)
            if speed > vmax:
                wl.vx *= vmax / speed
                wl.vy *= vmax / speed
        self._draw_supers_together()
        for wl in wells:
            if wl is self.held:
                continue
            wl.x += wl.vx
            wl.y += wl.vy
            if self.wrap:
                wl.x %= self.w
                wl.y %= self.h
            else:
                if not 0 <= wl.x <= self.w - 1:
                    wl.x, wl.vx = min(max(wl.x, 0.0), self.w - 1.0), 0.0
                if not 0 <= wl.y <= self.h - 1:
                    wl.y, wl.vy = min(max(wl.y, 0.0), self.h - 1.0), 0.0
            # a super well's field is soft and its core several cells across: half its core is close enough
            moved = max(config.WELL_REBUILD_MOVE, 0.5 * wl.core()) if wl.is_super else config.WELL_REBUILD_MOVE
            if self.distance(wl.x, wl.y, wl.built[0], wl.built[1]) > moved:
                self.changed_wells.append(wl)
        self._swallow_wells()
        for wl in [wl for wl in self.wells if wl.is_super and wl.mass >= config.SUPER_EXPLODE_MASS]:
            self.explode(wl)
        stars = [wl for wl in self.wells if not wl.is_super and wl.sign > 0 and wl.wave < 0]
        for i, a in enumerate(stars):
            for b in stars[i + 1:]:
                if a not in self.wells:                  # shattered
                    break
                if b in self.wells and self.distance(a.x, a.y, b.x, b.y) < a.radius + b.radius:
                    self._collide_stars(a, b)
        self._dissolve_stars()

    def _collide_stars(self, a, b):
        """Two stars whose bodies overlap: pushed apart to touching and, if they hit hard enough, bounced back
        along the line between their centres (momentum conserved, STAR_RESTITUTION). A star smaller than
        STAR_SHATTER_RADIUS then shatters into particles; otherwise they shed debris from the point of contact,
        taken mostly from the smaller one (STAR_LOSS_BIAS), and each shrinks to keep its density."""
        dx, dy = self.delta(a.x, a.y, b.x, b.y)
        d = math.hypot(dx, dy)
        if d < 1e-9:
            ang = self.rng.uniform(0, 2 * math.pi)
            dx, dy, d = math.cos(ang), math.sin(ang), 1e-9
        nx, ny = dx / d, dy / d                          # from a towards b
        ma, mb = a.mass, b.mass
        overlap = a.radius + b.radius - d
        a.x -= nx * overlap * mb / (ma + mb)
        a.y -= ny * overlap * mb / (ma + mb)
        b.x += nx * overlap * ma / (ma + mb)
        b.y += ny * overlap * ma / (ma + mb)
        if self.wrap:
            a.x, a.y, b.x, b.y = a.x % self.w, a.y % self.h, b.x % self.w, b.y % self.h
        self.changed_wells += [a, b]
        u = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny     # closing speed
        if u <= 0:
            return
        if u < config.STAR_REST_SPEED:                 # resting contact: they just stop closing
            j = u * ma * mb / (ma + mb)
        else:
            j = (1 + config.STAR_RESTITUTION) * u * ma * mb / (ma + mb)
        a.vx -= j / ma * nx
        a.vy -= j / ma * ny
        b.vx += j / mb * nx
        b.vy += j / mb * ny
        if u < config.STAR_REST_SPEED:
            return
        small = [wl for wl in (a, b) if wl.radius < config.STAR_SHATTER_RADIUS]
        if small:
            for wl in small:
                self._shatter(wl, config.STAR_SHATTER_SPEED + 0.5 * u)
            return
        # debris: up to STAR_EJECT of their combined mass, in proportion to the impact speed
        share = config.STAR_EJECT * min(1.0, u / config.STAR_EJECT_SPEED)
        loss = int((ma + mb) * share)
        if loss <= 0:
            return
        contact = (a.x + nx * a.radius, a.y + ny * a.radius)
        base = ((a.vx * a.mass + b.vx * b.mass) / (ma + mb), (a.vy * a.mass + b.vy * b.mass) / (ma + mb))
        placed = self._spawn_debris(contact, loss, base, 0.9 * u + config.STAR_DEBRIS_SPEED)
        if placed <= 0:
            return
        lost_a, lost_b = merge_losses(ma, mb, placed, bias=config.STAR_LOSS_BIAS)
        for wl, lost in ((a, lost_a), (b, lost_b)):
            left = max(wl.mass - lost, 1.0)
            wl.radius = max(1.0, wl.radius * math.sqrt(left / wl.mass))
            wl.mass = left
        self.field_dirty = True                          # bodies shrank: rebuild the ground

    def _spawn_debris(self, at, amount, base_v, speed):
        """Fling `amount` of mass as particles of random masses from a point, outwards at `speed` on top of base_v,
        into free cells around it. Returns the mass actually placed."""
        masses = self._random_masses(amount)
        n = masses.size
        rng = self.rng
        cand = 4 * n + 16                                # extra spots: some fall on solid ground or particles
        r = rng.uniform(1.0, 3.0 + math.sqrt(cand), cand)
        ang = rng.uniform(0.0, 2 * math.pi, cand)
        xs = np.round(at[0] + r * np.cos(ang)).astype(np.int64)
        ys = np.round(at[1] + r * np.sin(ang)).astype(np.int64)
        if self.wrap:
            xs %= self.w
            ys %= self.h
        ok = (xs >= 0) & (xs < self.w) & (ys >= 0) & (ys < self.h)
        idx = np.where(ok, ys * self.w + xs, -1)
        _, first = np.unique(idx, return_index=True)
        keep = np.zeros(cand, bool)
        keep[first] = True
        keep &= ok
        keep[keep] = (self.mass[idx[keep]] == 0) & (self.solid[idx[keep]] == 0)
        spots = np.nonzero(keep)[0][:n]
        masses = masses[:spots.size]
        speed = min(speed, 0.95 * config.VMAX)
        self.place_many(xs[spots], ys[spots], masses, base_v[0] + np.cos(ang[spots]) * speed,
                        base_v[1] + np.sin(ang[spots]) * speed)
        return int(masses.sum())

    def _disk_cells(self, cx, cy, r):
        """The cells within r of (cx, cy), as mark_solid counts them: (xs, ys, dx, dy), offsets from the centre."""
        xs = np.arange(math.floor(cx - r), math.floor(cx + r) + 2)
        ys = np.arange(math.floor(cy - r), math.floor(cy + r) + 2)
        gx, gy = np.meshgrid(xs, ys)
        dx, dy = gx - cx, gy - cy
        inside = dx * dx + dy * dy <= r * r
        gx, gy, dx, dy = gx[inside], gy[inside], dx[inside], dy[inside]
        if self.wrap:
            gx, gy = gx % self.w, gy % self.h
        else:
            ok = (gx >= 0) & (gx < self.w) & (gy >= 0) & (gy < self.h)
            gx, gy, dx, dy = gx[ok], gy[ok], dx[ok], dy[ok]
        return gx, gy, dx, dy

    def _split_mass(self, amount, k):
        """At most k random particle masses (each 1..MAX_MASS, spread round their mean) adding up to amount, or to
        as much of it as k particles can hold."""
        amount = int(amount)
        k = min(int(k), amount)
        if k <= 0:
            return np.zeros(0, np.int64)
        wts = self.rng.uniform(0.25, 1.75, k)
        m = np.minimum(np.floor(wts / wts.sum() * (amount - k)).astype(np.int64) + 1, config.MAX_MASS)
        short = amount - int(m.sum())
        while short > 0:                                 # rounding (or the cap) left some over: hand it round
            open_ = self.rng.permutation(np.nonzero(m < config.MAX_MASS)[0])
            if not open_.size:
                break
            add = np.minimum(config.MAX_MASS - m[open_], -(-short // open_.size))
            cum = np.cumsum(add)
            cut = int(np.searchsorted(cum, short))
            if cut < add.size:
                add[cut] -= cum[cut] - short
                add[cut + 1:] = 0
            m[open_] += add
            short -= int(add.sum())
        return m

    def _burst(self, xs, ys, amount, vx, vy):
        """Turn `amount` of mass into particles in the given free cells (one each, random masses) with velocities
        vx, vy (arrays over the cells). Returns the mass placed."""
        idx = ys * self.w + xs
        _, first = np.unique(idx, return_index=True)
        first = first[self.mass[idx[first]] == 0]
        masses = self._split_mass(amount, first.size)
        pick = self.rng.permutation(first)[:masses.size]
        before = self.total_mass()
        self.place_many(xs[pick], ys[pick], masses, vx[pick], vy[pick])
        return self.total_mass() - before

    def _scatter_rest(self, wl, amount, speed, sink=None):
        """Fling what is left of a broken star out round it as debris; anything that finds no room goes to sink
        (a super well) if given. Returns the mass placed."""
        placed, tries = 0, 0
        while amount - placed >= 1 and tries < 8:
            placed += self._spawn_debris((wl.x, wl.y), int(amount - placed), (wl.vx, wl.vy), speed)
            tries += 1
        if sink is not None and sink in self.wells:
            sink.mass += amount - placed
            self.changed_wells.append(sink)
        return placed

    def _shatter(self, wl, speed):
        """A star breaks up into particles of random masses filling its body and adding up to its mass, flying
        apart from its centre (faster towards its surface) on top of its motion and spin."""
        self.remove_well(wl)
        xs, ys, dx, dy = self._disk_cells(wl.x, wl.y, wl.radius)
        self.solid[ys * self.w + xs] = 0                 # its body is gone (the ground is rebuilt next tick)
        d = np.maximum(np.hypot(dx, dy), 1e-9)
        out = speed * np.minimum(d / wl.radius, 1.0) / d
        jx, jy = self.rng.normal(0.0, 0.3 * speed, (2, d.size))    # uneven, so the pieces don't fly as a lattice
        placed = self._burst(xs, ys, wl.mass, wl.vx - wl.omega * dy + dx * out + jx,
                             wl.vy + wl.omega * dx + dy * out + jy)
        self._scatter_rest(wl, wl.mass - placed, speed)

    def _start_wave(self, pl, sw):
        """A super well's core touched star pl: it starts dissolving from the point facing the well."""
        dx, dy = self.delta(pl.x, pl.y, sw.x, sw.y)
        d = max(math.hypot(dx, dy), 1e-9)
        pl.wave, pl.wave_dx, pl.wave_dy, pl.wave_by = 0.0, dx / d * pl.radius, dy / d * pl.radius, sw
        self.changed_wells.append(pl)

    def _dissolve_stars(self):
        """Advance each dissolving star's wave by STAR_DISSOLVE_SPEED: the cells of its body it sweeps over turn
        into particles holding their share of its mass, kicked away from the point of contact. Once the wave has
        crossed it the star is gone."""
        kick = config.STAR_DISSOLVE_KICK
        for pl in [wl for wl in self.wells if wl.wave >= 0]:
            old, new = pl.wave, pl.wave + config.STAR_DISSOLVE_SPEED
            xs, ys, dx, dy = self._disk_cells(pl.x, pl.y, pl.radius)
            ex, ey = dx - pl.wave_dx, dy - pl.wave_dy
            de = np.hypot(ex, ey)
            left = de > old
            ring = left & (de <= new)
            done = new >= 2 * pl.radius or ring.sum() == left.sum()
            amount = round(pl.mass) if done else round(pl.mass * ring.sum() / max(1, left.sum()))
            xs, ys, dx, dy, ex, ey, de = (a[ring] for a in (xs, ys, dx, dy, ex, ey, de))
            self.solid[ys * self.w + xs] = 0
            de = np.maximum(de, 1e-9)
            placed = self._burst(xs, ys, amount, pl.vx - pl.omega * dy + ex / de * kick,
                                 pl.vy + pl.omega * dx + ey / de * kick)
            pl.mass -= placed
            pl.wave = new
            if done:
                self.remove_well(pl)
                self._scatter_rest(pl, pl.mass, kick + 0.5, sink=pl.wave_by)
            else:
                self.changed_wells.append(pl)

    def explode(self, wl):
        """A super well that grew too heavy goes supernova: it vanishes and all its mass comes back out from where it
        was as a ring of very heavy debris (ghosts, so nothing in the way stops them) flying outwards on a shock front
        that shoves every particle it passes away, further the nearer it was (see `_step_blasts`). The debris cools
        as it flies, breaking into lighter pieces (see `_cool_blasts`). Collapse is held off for SUPER_EXPLODE_CALM
        ticks so the debris can spread."""
        self.remove_well(wl)
        rng = self.rng
        r0 = max(wl.core() + 1.0, 2.0)
        reach = max(min(config.SUPER_BLAST_RADIUS, 0.45 * min(self.w, self.h)), r0 + 5.0)
        self.blast_serial += 1
        blast = Blast(wl.x, wl.y, r0, reach, self.blast_serial)
        self.blasts.append(blast)
        n = max(1, round(wl.mass / config.SUPER_BLAST_HOT_MASS))
        masses = self._split_mass(wl.mass, n)
        a = 2 * math.pi * (np.arange(masses.size) + rng.uniform(0.0, 1.0, masses.size)) / masses.size
        r = r0 + rng.uniform(0.0, 3.0, masses.size)
        s = blast.speed(r)
        self.add_ghosts(wl.x + r * np.cos(a), wl.y + r * np.sin(a), masses, wl.vx + s * np.cos(a),
                        wl.vy + s * np.sin(a), tag=blast.tag)
        self.explosions += 1
        self.calm_until = self.tick_count + config.SUPER_EXPLODE_CALM

    def _step_blasts(self):
        """Sweep each shock front on: it shoves the particles it passes outwards, and damps the outward motion of
        everything behind it, so what it pushed back stops after a while."""
        for b in self.blasts:
            r_new = b.r + float(b.speed(b.r))
            if r_new >= b.reach - 0.05:
                r_new = b.reach
            if b.r < b.reach:
                kernels.blast_push(b.x, b.y, b.r, r_new, b.reach, config.SUPER_BLAST_PUSH, config.SUPER_BLAST_DRAG,
                                   0.95 * config.VMAX, self.w, self.h, self.mass, self.kin, self.stamp, self.flag,
                                   self.solid, self.wrap)
            else:
                # the front has stopped: no ring to shove (r_in past r_out), only the fading behind it
                kernels.blast_push(b.x, b.y, b.reach + 1.0, b.reach, b.reach, 0.0, config.SUPER_BLAST_DRAG, 0.0,
                                   self.w, self.h, self.mass, self.kin, self.stamp, self.flag, self.solid, self.wrap)
                b.settled += 1
            b.r = r_new
        self.blasts = [b for b in self.blasts if b.settled < config.SUPER_BLAST_SETTLE]

    def _cool_blasts(self):
        """Blast debris (ghosts tagged with their blast's number) rides its front while the blast lasts, slowing as
        the front does, and cools however long that is: every SUPER_BLAST_COOL_EVERY ticks from
        SUPER_BLAST_COOL_FROM each piece heavier than SUPER_BLAST_COOL_TO breaks in two, the new piece scattering a
        little. Once cool, and at rest or its blast over, a piece is an ordinary ghost."""
        hot = np.nonzero(self.ghost_tag > 0)[0]
        if not hot.size:
            return
        active = {b.tag: b for b in self.blasts}
        for b in active.values():
            sel = hot[self.ghost_tag[hot] == b.tag]
            if not sel.size:
                continue
            dx, dy = self.ghost_x[sel] - b.x, self.ghost_y[sel] - b.y
            if self.wrap:
                dx -= self.w * np.floor(dx / self.w + 0.5)
                dy -= self.h * np.floor(dy / self.h + 0.5)
            d = np.maximum(np.hypot(dx, dy), 1e-9)
            ux, uy = dx / d, dy / d
            speed = b.speed(np.minimum(d, b.reach))
            vx, vy = self.ghost_vx[sel], self.ghost_vy[sel]
            along = vx * ux + vy * uy
            out = d < b.reach                            # past the edge: stopped
            self.ghost_vx[sel] = np.where(out, speed * ux + 0.9 * (vx - along * ux), 0.0)  # sideways drift fades
            self.ghost_vy[sel] = np.where(out, speed * uy + 0.9 * (vy - along * uy), 0.0)
        age = self.ghost_age[hot]
        due = hot[(age >= config.SUPER_BLAST_COOL_FROM)
                  & ((age - config.SUPER_BLAST_COOL_FROM) % config.SUPER_BLAST_COOL_EVERY == 0)
                  & (self.ghost_m[hot] > config.SUPER_BLAST_COOL_TO)]
        if due.size:
            m = self.ghost_m[due]
            new = np.clip(np.round(m * self.rng.uniform(0.3, 0.7, due.size)), 1, m - 1).astype(np.int64)
            self.ghost_m[due] = m - new
            jx, jy = self.rng.normal(0.0, 0.2, (2, due.size))
            for tag in np.unique(self.ghost_tag[due]):
                k = self.ghost_tag[due] == tag
                self.add_ghosts(self.ghost_x[due[k]], self.ghost_y[due[k]], new[k], self.ghost_vx[due[k]] + jx[k],
                                self.ghost_vy[due[k]] + jy[k], tag=int(tag), age=self.ghost_age[due[k]])
        hot = self.ghost_tag > 0
        over = ~np.isin(self.ghost_tag, list(active))
        still = np.hypot(self.ghost_vx, self.ghost_vy) < 0.1
        self.ghost_tag[hot & (self.ghost_m <= config.SUPER_BLAST_COOL_TO) & (over | still)] = 0

    def scale_spin(self, wl, factor):
        """Spin a super well faster or slower, keeping its direction, between 0.05 and SUPER_SPIN_MAX."""
        way = 1.0 if wl.spin >= 0 else -1.0
        wl.spin = way * min(config.SUPER_SPIN_MAX, max(0.05, abs(wl.spin) * factor))
        self.wake_all()

    def step_spawners(self):
        """Move unlocked spawners under gravity (like a particle, passing through everything), delete any that reach
        a super well's core, and let each pour its particles."""
        sg = self.sg
        for sp in list(self.spawners):
            if not sp.locked and sp is not self.held:
                i = min(int(sp.y), self.h - 1) * self.w + min(int(sp.x), self.w - 1)
                ax, ay = float(self.fx[i]), float(self.fy[i])
                if self.sg_on:
                    b = (min(int(sp.y), self.h - 1) // sg.block) * sg.cw + min(int(sp.x), self.w - 1) // sg.block
                    ax += float(sg.gx[b])
                    ay += float(sg.gy[b])
                if self.orbit:
                    ox, oy = self._orbit_accel(sp.x, sp.y, sp.vx, sp.vy)
                    ax += ox
                    ay += oy
                ox, oy = self._whirl_accel(sp, sp.x, sp.y, sp.vx, sp.vy)
                ax += ox
                ay += oy
                sp.vx += ax
                sp.vy += ay
                speed = math.hypot(sp.vx, sp.vy)
                if speed > config.VMAX:
                    sp.vx *= config.VMAX / speed
                    sp.vy *= config.VMAX / speed
                sp.x += sp.vx
                sp.y += sp.vy
                if self.wrap:
                    sp.x %= self.w
                    sp.y %= self.h
                else:
                    if not 0 <= sp.x <= self.w - 1:
                        sp.x, sp.vx = min(max(sp.x, 0.0), self.w - 1.0), 0.0
                    if not 0 <= sp.y <= self.h - 1:
                        sp.y, sp.vy = min(max(sp.y, 0.0), self.h - 1.0), 0.0
            if any(wl.is_super and self.distance(wl.x, wl.y, sp.x, sp.y) <= wl.core() for wl in self.wells):
                self.remove_body(sp)                    # swallowed: it stops spawning
                continue
            sp.debt += sp.rate
            n = int(sp.debt)
            if n:
                sp.debt -= n
                self._pour(sp, n)

    def _pour(self, sp, n):
        rng = self.rng
        r = sp.radius * np.sqrt(rng.uniform(0.0, 1.0, n))
        a = rng.uniform(0.0, 2 * math.pi, n)
        xs, ys = sp.x + r * np.cos(a), sp.y + r * np.sin(a)
        if isinstance(sp.masses, tuple):
            masses = rng.integers(sp.masses[0], sp.masses[1] + 1, n)
        else:
            masses = sp.masses
        if sp.ghosts:                                    # ghosts: they can't pile up at the spawner and collapse
            self.add_ghosts(xs, ys, masses, sp.vx, sp.vy)
            return
        xs, ys = np.round(xs).astype(np.int64), np.round(ys).astype(np.int64)
        if self.wrap:
            xs %= self.w
            ys %= self.h
        self.place_many(xs, ys, masses, sp.vx, sp.vy)

    def _draw_supers_together(self):
        """Super wells whose ranges overlap are drawn together, whatever their mass, until their cores touch and they
        merge. They close faster and faster: the pull between them grows the nearer they are (SUPER_MERGE_ACCEL x the
        sum of their ranges / their distance, per tick), up to SUPER_MERGE_MAX_SPEED. Their sideways motion round each
        other fades (SUPER_MERGE_SPIRAL), so they spiral in. The lighter one covers more of the gap (about their common
        centre of mass); one being dragged stays put and the other comes to it."""
        supers = [wl for wl in self.wells if wl.is_super]
        for wl in supers:
            wl.merging = False
        for i, a in enumerate(supers):
            for b in supers[i + 1:]:
                reach = self.well_range(a) + self.well_range(b)
                gap = self.distance(a.x, a.y, b.x, b.y)
                if gap >= reach or gap <= 0:
                    continue
                a.merging = b.merging = True
                bdx, bdy = self.delta(a.x, a.y, b.x, b.y)   # b as seen from a (round the border if shorter)
                ux, uy = bdx / gap, bdy / gap
                rvx, rvy = b.vx - a.vx, b.vy - a.vy
                closing = -(rvx * ux + rvy * uy)
                tx, ty = rvx + closing * ux, rvy + closing * uy             # sideways part
                pull = config.SUPER_MERGE_ACCEL * reach / max(gap, a.core() + b.core())
                closing = min(max(closing, 0.0) + pull, config.SUPER_MERGE_MAX_SPEED, gap)
                keep = 1.0 - config.SUPER_MERGE_SPIRAL
                rvx, rvy = -closing * ux + keep * tx, -closing * uy + keep * ty
                if a is self.held or b is self.held:
                    moving, sign = (b, 1.0) if a is self.held else (a, -1.0)
                    moving.vx, moving.vy = sign * rvx, sign * rvy
                    continue
                total = a.mass + b.mass
                cvx = (a.vx * a.mass + b.vx * b.mass) / total
                cvy = (a.vy * a.mass + b.vy * b.mass) / total
                a.vx, a.vy = cvx - rvx * b.mass / total, cvy - rvy * b.mass / total
                b.vx, b.vy = cvx + rvx * a.mass / total, cvy + rvy * a.mass / total

    def _random_masses(self, amount):
        """Particle masses drawn uniformly from EJECT_MASS, the last one trimmed so they add up to exactly amount."""
        lo, hi = config.EJECT_MASS
        masses = self.rng.integers(lo, hi + 1, 2 * amount // (lo + hi) + 16)
        while masses.sum() < amount:
            masses = np.concatenate([masses, self.rng.integers(lo, hi + 1, masses.size)])
        cum = np.cumsum(masses)
        last = int(np.searchsorted(cum, amount))
        masses = masses[:last + 1]
        masses[-1] -= cum[last] - amount
        return masses

    def eject(self, wl, amount):
        """Spit `amount` of a super well's mass out as particles of random masses, each fast enough to climb out of
        its range if nothing stops it. The well loses exactly the mass that found free cells. Returns that mass."""
        amount = int(min(amount, wl.mass - 1))
        if amount <= 0:
            return 0
        rng = self.rng
        masses = self._random_masses(amount)
        # escape speed from the well as it will be: 1/2 v^2 = S / sqrt(r^2 + soft^2) (its pull never ends)
        left = wl.mass - amount
        strength = self.g_scale * config.G * left
        reach = math.sqrt(strength / config.SUPER_RANGE_ACCEL) * config.SUPER_RANGE_FACTOR
        soft = max(super_core(left), config.SUPER_SOFTENING * reach)

        def launch_speed(r):
            v_esc = np.sqrt(2 * strength / np.sqrt(r * r + soft * soft))     # its pull never ends
            return config.EJECT_ESCAPE * v_esc + 0.3

        # start far enough out that the launch speed fits under VMAX (particles can't go faster)
        r0 = soft + 2.0
        while r0 < self.w + self.h and launch_speed(r0) > 0.95 * config.VMAX:
            r0 += 1.0
        n = masses.size
        r = r0 + rng.uniform(0.0, n / (2 * math.pi * r0) + 2.0, n)
        a = rng.uniform(0.0, 2 * math.pi, n)
        speed = np.minimum(launch_speed(r), 0.95 * config.VMAX)
        xs = np.round(wl.x + r * np.cos(a)).astype(np.int64)
        ys = np.round(wl.y + r * np.sin(a)).astype(np.int64)
        if self.wrap:
            xs %= self.w
            ys %= self.h
        ok = (xs >= 0) & (xs < self.w) & (ys >= 0) & (ys < self.h)
        idx = np.where(ok, ys * self.w + xs, -1)
        _, first = np.unique(idx, return_index=True)
        keep = np.zeros(n, bool)
        keep[first] = True
        keep &= ok
        keep[keep] = (self.mass[idx[keep]] == 0) & (self.solid[idx[keep]] == 0)
        self.place_many(xs[keep], ys[keep], masses[keep], wl.vx + np.cos(a[keep]) * speed[keep],
                        wl.vy + np.sin(a[keep]) * speed[keep])
        ejected = int(masses[keep].sum())
        wl.mass -= ejected
        self.changed_wells.append(wl)
        return ejected

    def _swallow_wells(self):
        """A star touching a super well's core starts dissolving into particles (which the core swallows as they
        reach it). Two super wells merge when their cores touch: mass adds up and momentum is conserved."""
        merged = True
        while merged:
            merged = False
            for a in self.wells:
                if a.sign < 0:
                    continue
                if not a.is_super:
                    continue
                for b in self.wells:
                    if b is a or b.sign < 0:
                        continue
                    d = self.distance(a.x, a.y, b.x, b.y)
                    if not b.is_super:          # a star touching the core dissolves (the core eats the particles)
                        if b.wave < 0 and d <= a.core() + b.radius:
                            self._start_wave(b, a)
                        continue
                    if d > a.core() + b.core():
                        continue
                    big, small = (a, b) if a.mass >= b.mass else (b, a)
                    # two super wells merging spit some mass back out, taken from each by MERGE_LOSS_BIAS
                    loss = (big.mass + small.mass) * self.rng.uniform(*config.MERGE_EJECT)
                    lost_big, lost_small = merge_losses(big.mass, small.mass, loss)
                    big.mass -= lost_big
                    small.mass -= lost_small
                    total = big.mass + small.mass
                    sdx, sdy = self.delta(big.x, big.y, small.x, small.y)
                    big.x += sdx * small.mass / total
                    big.y += sdy * small.mass / total
                    if self.wrap:
                        big.x %= self.w
                        big.y %= self.h
                    big.vx = (big.vx * big.mass + small.vx * small.mass) / total
                    big.vy = (big.vy * big.mass + small.vy * small.mass) / total
                    # spins add up by mass: opposite ones partly cancel
                    big.spin = (big.spin * big.mass + small.spin * small.mass) / total
                    big.mass = total + loss     # held until ejected, so the well loses exactly what is placed
                    if self.held is small:
                        self.held = None
                    self.wells.remove(small)
                    if loss:
                        self.eject(big, loss)
                    self.field_dirty = True
                    merged = True
                    break
                if merged:
                    break

    def whirls(self):
        """Each super well's whirlpool for the step kernel: rows of x, y, range, spin, pull strength, softening."""
        return np.array([(wl.x, wl.y, self.well_range(wl), wl.spin, self.g_scale * wl.pull(), self.softening(wl))
                         for wl in self.wells if wl.is_super], np.float64).reshape(-1, 6)

    def _whirl_accel(self, body, x, y, vx, vy):
        """The super wells' whirlpools on a well or spawner at (x, y). Not on a super well: one is only inside another's
        whirlpool when their ranges overlap, and then they are being drawn together (_draw_supers_together)."""
        ax = ay = 0.0
        if getattr(body, "is_super", False):
            return ax, ay
        for wl in self.wells:
            if wl.is_super:
                dx, dy = self.delta(wl.x, wl.y, x, y)
                wx, wy, _ = kernels.whirl(dx, dy, vx, vy, self.well_range(wl), wl.spin, self.g_scale * wl.pull(),
                                          self.softening(wl), config.SUPER_SWIRL_SPEED, config.SUPER_SWIRL_GRIP,
                                          config.SUPER_SWIRL_INFALL, config.SUPER_SWIRL_EDGE)
                ax += wx
                ay += wy
        return ax, ay

    def _orbit_accel(self, x, y, vx, vy):
        return kernels.orbit_accel(x - self.w / 2, y - self.h / 2, vx, vy, self.orbit * self.orbit_speed,
                                   config.ORBIT_GRIP, config.ORBIT_MIN_SPEED)

    def orbit_speed_for(self, edge_speed):
        """The global orbit's angular speed (rad/tick) that turns the edge of the universe at edge_speed cells/tick."""
        r = min(self.w, self.h) / 2
        return math.sqrt(max(edge_speed ** 2 - config.ORBIT_MIN_SPEED ** 2, 0.0)) / r

    def orbit_edge_speed(self):
        """Speed the global orbit turns things at the edge of the universe (cells/tick)."""
        r = min(self.w, self.h) / 2
        return math.hypot(self.orbit_speed * r, config.ORBIT_MIN_SPEED)

    def rebuild_order(self, cut_only=False):
        """Rank cells for leading-particles-first processing: lowest potential first and, with the global orbit on,
        furthest ahead in the direction of turning first, so a moving clump's front moves before the rest follow.
        cut_only: the potential hasn't changed, only turn the orbit's cut (cheap: no re-ranking)."""
        self.order_tick = self.tick_count
        if not self.orbit:
            self.bucket = order_buckets(np.asarray(self.phi, np.float32), self.rng)
            self.order_dirty = False
            return
        nb = 4096
        if self.angle_rank is None or self.angle_rank.size != self.n or self.angle_key != (self.w, self.h):
            ys, xs = np.divmod(np.arange(self.n), self.w)
            angle = np.arctan2(ys - self.h / 2, xs - self.w / 2).astype(np.float32)
            self.angle_rank = order_buckets(angle, self.rng, nb).astype(np.int32)
            self.angle_key = (self.w, self.h)
        if not cut_only or self.phi_rank is None:
            flat = float(self.phi.max() - self.phi.min()) <= 1e-9
            self.phi_rank = None if flat else order_buckets(self.phi, self.rng, nb).astype(np.int32)
            self.order_dirty = False
        # Ranked by angle there is a cut where the rank jumps from last to first: flow crossing it is processed
        # trailing-first and jams into a visible line. So the cut is turned a little every re-rank (a cyclic shift of
        # the angle rank), which smears any such edge away.
        self.cut = (self.cut + config.ORDER_CUT_STEP) % (2 * math.pi)
        ahead = self.angle_rank if self.orbit < 0 else nb - 1 - self.angle_rank     # lower = further ahead
        ahead = (ahead + int(self.cut / (2 * math.pi) * nb)) % nb
        # the sum of two ranks already orders the cells; its 2 x 4096 levels fit the bucket sort as they are
        self.bucket = (ahead if self.phi_rank is None else self.phi_rank + ahead).astype(np.uint16)

    # --- simulation -------------------------------------------------------------------------------

    def step(self):
        t0 = time.perf_counter()
        if self.field_dirty or self.changed_wells:
            self.rebuild_field()
        # the processing order lags a little while a well is being dragged: it only affects efficiency
        if self.order_dirty and self.tick_count - self.order_tick >= config.ORDER_EVERY or self.bucket is None:
            self.rebuild_order()
        elif self.orbit and self.tick_count - self.order_tick >= config.ORDER_CUT_EVERY:
            self.rebuild_order(cut_only=True)
        if self.sg_on and self.tick_count % config.SG_EVERY == 0:
            changed = self.sg.update(self.mass, self.sg_g * self.g_scale)
            kernels.wake_blocks(changed, self.sg.block, self.sg.cw, self.w, self.h, self.mass, self.flag)
        t1 = time.perf_counter()
        self.tick_count += 1
        self.stats[:] = 0
        params, whirls = self.params(), self.whirls()
        if self.blasts:
            self._step_blasts()
        self.n_awake = kernels.step(self.w, self.h, self.tick_count, params, self.mass, self.kin, self.quad,
                                    self.shade, self.stamp, self.flag, self.cur, self.order, self.bucket_counts,
                                    self.bucket, self.fx, self.fy, self.sg.gx, self.sg.gy, self.sg.block, self.sg.cw,
                                    self.hole, self.absorbed, self.solid, self.gvx, self.gvy, whirls, self.stats)
        if self.ghost_m.size:
            self._step_ghosts(params, whirls)
            self._cool_blasts()
        self._collect_absorbed()
        if self.collapse_on and self.tick_count % config.COLLAPSE_EVERY == 0 and self.tick_count >= self.calm_until:
            self.check_collapse()
        if config.STAR_FORM_ON and self.tick_count % config.STAR_FORM_EVERY == 0:
            self.form_stars()
        self.step_wells()
        self.step_spawners()
        t2 = time.perf_counter()
        self.gravity_ms = (t1 - t0) * 1000
        self.step_ms = (t2 - t1) * 1000

    def render(self, mode=0):
        kernels.render(mode, self.mass, self.kin, self.quad, self.shade, self.flag, self.mass_lut, self.heat_lut,
                       self.shade_mul, self.bg, config.VMAX, self.rgb.reshape(-1, 3))
        if self.ghost_m.size:
            kernels.render_ghosts(self.ghost_x, self.ghost_y, self.ghost_m, self.w, self.h, self.mass_lut,
                                  self.ghost_tint, self.rgb.reshape(-1, 3))
        return self.rgb

    # --- ghosts -----------------------------------------------------------------------------------

    def _clear_ghosts(self):
        """Ghosts: particles off the grid (positions in cells) that feel gravity but collide with nothing."""
        self.ghost_x = np.zeros(0)
        self.ghost_y = np.zeros(0)
        self.ghost_vx = np.zeros(0)
        self.ghost_vy = np.zeros(0)
        self.ghost_m = np.zeros(0, np.int64)
        self.ghost_age = np.zeros(0, np.int64)
        self.ghost_tag = np.zeros(0, np.int64)       # > 0: debris of that blast (see _cool_blasts)

    def pour_ghosts(self, px, py, radius_px, m):
        """Pour ghost particles in a circle around a pixel, at the brush's rate, anywhere in it (they overlap
        particles, stars and each other freely). m: a mass or a (min, max) range."""
        c = self.cell
        xs, ys, _, _ = self._disk_cells(px // c, py // c, max(0.5, radius_px / c))
        pick = self.rng.random(xs.size) < config.POUR_CHANCE
        n = int(pick.sum())
        if not n:
            return
        lo, hi = m if isinstance(m, tuple) else (m, m)
        self.add_ghosts(xs[pick], ys[pick], self.rng.integers(lo, hi + 1, n))

    def add_ghosts(self, xs, ys, masses, vx=0.0, vy=0.0, tag=0, age=0):
        """Add ghosts at positions in cells (arrays) with masses (an array or one mass), velocity (a number or an
        array), a blast tag and an age."""
        n = len(xs)
        if self.wrap:
            xs, ys = np.mod(xs, self.w), np.mod(ys, self.h)
        else:
            xs, ys = np.clip(xs, 0, self.w - 1), np.clip(ys, 0, self.h - 1)
        self.ghost_x = np.concatenate([self.ghost_x, np.asarray(xs, np.float64)])
        self.ghost_y = np.concatenate([self.ghost_y, np.asarray(ys, np.float64)])
        self.ghost_vx = np.concatenate([self.ghost_vx, np.broadcast_to(np.float64(vx), n)])
        self.ghost_vy = np.concatenate([self.ghost_vy, np.broadcast_to(np.float64(vy), n)])
        self.ghost_m = np.concatenate([self.ghost_m, np.broadcast_to(np.asarray(masses, np.int64), n)])
        self.ghost_age = np.concatenate([self.ghost_age, np.broadcast_to(np.asarray(age, np.int64), n)])
        self.ghost_tag = np.concatenate([self.ghost_tag, np.full(n, tag, np.int64)])

    def _step_ghosts(self, params, whirls):
        """Move the ghosts (feeling every gravity but each other's: they aren't in the self-gravity mesh), let the
        super wells swallow those that reach a core, and land the ones GHOST_TICKS old as ordinary particles."""
        g = (self.ghost_x, self.ghost_y, self.ghost_vx, self.ghost_vy, self.ghost_m, self.ghost_age)
        self.stats[kernels.S_ABSORBED] += kernels.step_ghosts(*g, self.w, self.h, params, self.fx, self.fy,
                                                              self.sg.gx, self.sg.gy, self.sg.block, self.sg.cw,
                                                              self.hole, self.absorbed, whirls)
        kernels.land_ghosts(*g, config.GHOST_TICKS, max(self.w, self.h), self.w, self.h, self.mass, self.kin,
                            self.quad, self.shade, self.stamp, self.flag, self.solid, self.hole, self.wrap)
        keep = self.ghost_m > 0
        if not keep.all():
            for name in ("ghost_x", "ghost_y", "ghost_vx", "ghost_vy", "ghost_m", "ghost_age", "ghost_tag"):
                setattr(self, name, getattr(self, name)[keep])

    def ghost_count(self):
        return int(self.ghost_m.size)

    def ghost_mass(self):
        return int(self.ghost_m.sum())

    # --- editing ----------------------------------------------------------------------------------

    def wake_all(self):
        kernels.wake_all(self.mass, self.flag)

    def brush(self, px, py, radius_px, m):
        """Pour or erase in a circle around a pixel. m: a mass, a (min, max) range to draw each mass from
        uniformly, or 0 to erase."""
        lo, hi = m if isinstance(m, tuple) else (m, m)
        c = self.cell
        kernels.brush(px // c, py // c, max(0.5, radius_px / c), lo, hi, config.POUR_CHANCE, self.w, self.h,
                      self.mass, self.kin, self.quad, self.shade, self.stamp, self.flag, self.solid, self.wrap)

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
                                  self.flag, self.solid)

    def clear(self):
        self.blasts.clear()
        self.mass[:] = 0
        self.kin[:] = 0
        self.quad[:] = 0
        self.flag[:] = 0
        self.n_awake = 0
        self.sg.reset()
        self._clear_ghosts()

    def reset(self):
        """Empty world with default settings (used by presets)."""
        self.clear()
        self.wells.clear()
        self.spawners.clear()
        self.held = None
        self.gdir = None if config.GRAVITY_DIR is None else DIR_NAMES.index(config.GRAVITY_DIR)
        self.sg_on = config.SG_ON
        self.merge_on = config.MERGE_ON
        self.split_on = config.SPLIT_ON
        self.orbit = config.ORBIT
        self.orbit_speed = self.orbit_speed_for(config.ORBIT_EDGE_SPEED)
        self.g_scale = config.GRAVITY_SCALE
        if self.wrap != config.WRAP:
            self.set_wrap(config.WRAP)
        self.field_dirty = True

    def set_cell(self, cell):
        self.resize(self.pw, self.ph, cell)

    def resize(self, pw, ph, cell=None):
        """Change the pixel area and/or square size, resampling the scene so it keeps its shape (sand.py
        World.resize). When the area changes, the scene stays pinned to the side global gravity points at, or
        centred when there is none; wells move with it."""
        cell = cell or self.cell
        pw, ph = max(pw, 128), max(ph, 128)          # keeps the self-gravity mesh at least 2 blocks wide
        old_cell, ow, oh = self.cell, self.w, self.h
        old = (self.mass, self.kin, self.quad, self.shade)
        gx, gy = DIRS[self.gdir] if self.gdir is not None else (0, 0)
        offx = (pw - self.pw) * (gx + 1) // 2
        offy = (ph - self.ph) * (gy + 1) // 2
        self.pw, self.ph = pw, ph
        edge = self.orbit_edge_speed()
        self._alloc(cell)
        self.orbit_speed = self.orbit_speed_for(edge)   # the edge keeps turning as fast
        ox = (np.arange(self.w) * cell + cell // 2 - offx) // old_cell
        oy = (np.arange(self.h) * cell + cell // 2 - offy) // old_cell
        inside = (((oy >= 0) & (oy < oh))[:, None] & ((ox >= 0) & (ox < ow))[None, :]).ravel()
        src = (np.clip(oy, 0, oh - 1)[:, None] * ow + np.clip(ox, 0, ow - 1)[None, :]).ravel()
        self.mass[:] = np.where(inside, old[0][src], 0)
        self.kin[:] = old[1][src]
        self.kin[:, :2] *= old_cell / cell
        self.kin[:, 2:] = 0.0
        self.quad[:] = old[2][src]
        self.shade[:] = old[3][src]
        for wl in self.wells:
            wl.x = (wl.x * old_cell + offx) / cell
            wl.y = (wl.y * old_cell + offy) / cell
            wl.radius *= old_cell / cell
            wl.wave_dx *= old_cell / cell
            wl.wave_dy *= old_cell / cell
            if wl.wave >= 0:
                wl.wave *= old_cell / cell
            wl.vx *= old_cell / cell
            wl.vy *= old_cell / cell
            if self.wrap:
                wl.x %= self.w
                wl.y %= self.h
        self.ghost_x = (self.ghost_x * old_cell + offx) / cell
        self.ghost_y = (self.ghost_y * old_cell + offy) / cell
        self.ghost_vx *= old_cell / cell
        self.ghost_vy *= old_cell / cell
        if self.wrap:
            self.ghost_x %= self.w
            self.ghost_y %= self.h
        for sp in self.spawners:
            sp.x = (sp.x * old_cell + offx) / cell
            sp.y = (sp.y * old_cell + offy) / cell
            sp.radius *= old_cell / cell
            sp.rate = math.pi * sp.radius ** 2 * config.SPAWNER_RATE
            sp.vx *= old_cell / cell
            sp.vy *= old_cell / cell
            if self.wrap:
                sp.x %= self.w
                sp.y %= self.h

    # --- wells ------------------------------------------------------------------------------------

    def add_well(self, px, py, mass, radius=config.WELL_SOFTENING, sign=1, vx=0.0, vy=0.0):
        """A normal well (a repulsor if sign < 0) at a pixel position; radius is its size in cells."""
        x, y = px / self.cell, py / self.cell
        omega = float(self.rng.choice((-1, 1)) * self.rng.uniform(*config.STAR_SPIN))
        wl = Well(x, y, mass, radius, sign=sign, vx=vx, vy=vy, omega=omega, built=(x, y, mass))
        self.wells.append(wl)
        self.field_dirty = True
        return wl

    def brush_mass(self, radius_px, pour_mass):
        """Mass of a well the size of a brush circle: its area filled with pour_mass particles, WELL_DENSITY times
        over (a (min, max) pour range counts as its middle)."""
        r = max(1.0, radius_px / self.cell)
        m = sum(pour_mass) / 2 if isinstance(pour_mass, tuple) else pour_mass
        return math.pi * r * r * m * config.WELL_DENSITY

    def add_sized_well(self, px, py, radius_px, pour_mass=1, sign=1):
        """A well the size of a radius_px circle, as heavy as brush_mass()."""
        return self.add_well(px, py, self.brush_mass(radius_px, pour_mass), max(1.0, radius_px / self.cell), sign)

    def add_super_well(self, px, py, mass=None):
        """A super well holding `mass` (default: the current collapse threshold), spinning SUPER_SPIN_PLACED fast
        either way."""
        mass = mass or self.collapse_threshold()
        x, y = px / self.cell, py / self.cell
        spin = float(self.rng.choice((-1, 1)) * config.SUPER_SPIN_PLACED)
        wl = Well(x, y, mass, is_super=True, spin=spin, built=(x, y, mass))
        self.wells.append(wl)
        self.field_dirty = True
        return wl

    def add_spawner(self, px, py, radius_px, pour_mass=1, locked=False):
        """A particle spawner the size of a radius_px circle, pouring SPAWNER_RATE particles per tick per cell of its
        area, of mass pour_mass (a number or a (min, max) range). A locked one stays put and ignores gravity."""
        r = max(1.0, radius_px / self.cell)
        sp = Spawner(px / self.cell, py / self.cell, r, math.pi * r * r * config.SPAWNER_RATE, pour_mass, locked)
        self.spawners.append(sp)
        return sp

    def body_at(self, px, py, min_grab_px=12):
        """The well or spawner whose circle covers a pixel (nearest centre wins), or None."""
        best, best_d = None, math.inf
        for b in self.wells + self.spawners:
            d = math.hypot(b.x * self.cell - px, b.y * self.cell - py)
            reach = self.well_radius_px(b) if isinstance(b, Well) else b.radius * self.cell
            if d <= max(min_grab_px, reach) and d < best_d:
                best, best_d = b, d
        return best

    def nearest_body(self, px, py):
        """The nearest well or spawner to a pixel, or None."""
        bodies = self.wells + self.spawners
        if not bodies:
            return None
        return min(bodies, key=lambda b: math.hypot(b.x * self.cell - px, b.y * self.cell - py))

    def move_body(self, b, px, py):
        """Drag a well or spawner to a pixel position; it stops there."""
        if isinstance(b, Well):
            self.move_well(b, px, py)
        else:
            b.x, b.y = px / self.cell, py / self.cell
            b.vx = b.vy = 0.0

    def remove_body(self, b):
        if isinstance(b, Well):
            self.remove_well(b)
        else:
            self.spawners.remove(b)
            if self.held is b:
                self.held = None

    def well_radius_px(self, wl):
        """Radius of a well's drawn body: a normal well's size, or a super well's core."""
        return wl.body_radius() * self.cell

    def well_at(self, px, py, min_grab_px=12):
        """The well whose body covers a pixel (nearest centre wins), or None."""
        best, best_d = None, math.inf
        for wl in self.wells:
            d = math.hypot(wl.x * self.cell - px, wl.y * self.cell - py)
            if d <= max(min_grab_px, self.well_radius_px(wl)) and d < best_d:
                best, best_d = wl, d
        return best

    def nearest_well(self, px, py, normal_only=False):
        best, best_d = None, math.inf
        for wl in self.wells:
            if normal_only and wl.is_super:
                continue
            d = math.hypot(wl.x * self.cell - px, wl.y * self.cell - py)
            if d < best_d:
                best, best_d = wl, d
        return best

    def move_well(self, wl, px, py):
        """Drag a well: it stops, and only the particles within its reach of where it was and is are woken."""
        wl.x, wl.y = px / self.cell, py / self.cell
        wl.vx = wl.vy = 0.0
        self.changed_wells.append(wl)

    def remove_well(self, wl):
        self.wells.remove(wl)
        if self.held is wl:
            self.held = None
        self.field_dirty = True

    def scale_well(self, wl, factor):
        wl.mass *= factor
        self.field_dirty = True

    def scale_gravity(self, factor):
        """Make all gravity stronger or weaker; the collapse threshold moves the opposite way."""
        self.g_scale = min(16.0, max(1 / 16, self.g_scale * factor))
        self.field_dirty = True

    def set_wrap(self, on):
        """Continuous borders on or off."""
        self.wrap = on
        self.sg = SelfGravity(self.w, self.h, wrap=on)
        self.field_dirty = True

    def set_orbit(self, direction):
        """Global orbit: 1 clockwise, -1 counterclockwise, 0 off."""
        self.orbit = direction
        self.order_dirty, self.order_tick = True, -10 ** 9   # re-rank for the new flow at once
        self.wake_all()

    def scale_orbit(self, factor):
        self.orbit_speed *= factor
        self.wake_all()

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
        """Mass of the particles (not counting what super wells have swallowed)."""
        return int(self.mass.sum(dtype=np.int64))

    def super_mass(self):
        """Mass held by super wells (swallowed particles and wells)."""
        return int(sum(wl.mass for wl in self.wells if wl.is_super))

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
    w.add_well(16, 16, 5000.0)
    w.add_super_well(24, 24, 50)
    w.sg_on = w.merge_on = w.split_on = w.collapse_on = True
    w.orbit = 1
    w.brush(16, 8, 6, 4)
    w.brush(16, 8, 2, 0)
    w.place_many([1, 2], [1, 1], [3, 5], [0.5, 0.0], [0.0, 0.5])
    w.pour_ghosts(8, 24, 4, 2)
    w.ghost_age[:] = config.GHOST_TICKS - 2
    for _ in range(config.COLLAPSE_EVERY):
        w.step()
    w.form_stars()
    for mode in range(len(VIEW_MODES)):
        w.render(mode)
