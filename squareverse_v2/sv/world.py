"""The World: owns the particle arrays, wells and toggles, and drives the kernels."""

import math
import time
from dataclasses import dataclass

import numba
import numpy as np

from . import config, kernels, palette
from .gpu import Chooser
from .gravity import SelfGravity, external_field, fade, order_buckets, reach_for

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


def final_star(target, k):
    """Where star k's particles end up when each star k goes to target[k]: itself, another star or -1 (none)."""
    while k >= 0 and target[k] != k:
        k = target[k]
    return k


def roche_lobe(q):
    """Radius of a body's Roche lobe as a share of its distance to a companion, q = its mass / the companion's
    (Eggleton's fit): inside it the body's own gravity holds matter, outside the companion's tide takes it."""
    q3 = q ** (1 / 3)
    return 0.49 * q3 * q3 / (0.6 * q3 * q3 + math.log1p(q3))


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
    """An explosion's shock front: a ring round (x, y) at radius r (cells) slowing as it nears `reach`, pushing the
    particles it passes up to `push` cells out. Its debris (ghosts tagged with `tag`) expands with it, each piece
    keeping its share of the front's radius. `settled` counts the ticks since the front stopped."""
    x: float
    y: float
    r: float
    reach: float
    tag: int
    v0: float = config.SUPER_BLAST_SPEED
    push: float = config.SUPER_BLAST_PUSH
    drag: float = config.SUPER_BLAST_DRAG
    wind: bool = False          # keeps blowing behind the front (kernels.blast_push) ...
    blow: int = 0               # ... and over all of its reach for this many ticks after the front stops
    source: object = None       # a body it stays centred on while that lasts (a merged super well)
    settled: int = 0

    def speed(self, r):
        """Speed of the front at radius r: v0 when it starts, none at its edge."""
        return self.v0 * np.sqrt(np.maximum(0.0, 1.0 - np.asarray(r) / self.reach))


@dataclass(eq=False, slots=True)
class Well:
    """A gravity well, in cell units. Its pull is G * mass, the same constant particles attract each other with.

    A solid well has a size: a spinning body nothing can enter (its softening radius); a repulsor (sign -1) pushes
    instead and stays put. A super well swallows every particle and well that reaches its core; its core grows with
    its mass. Its pull follows the same law at every distance; within its range (the dotted circle) it also spins
    space round. Wells attract each other (and feel the stars and, with self-gravity on, the particles). Gravity
    accelerates a solid well as it does a particle, whatever its mass; a super well responds more sluggishly the
    heavier it is. (Stars are not wells: see Star.)
    """
    x: float
    y: float
    mass: float
    radius: float = 0.0         # normal well size
    is_super: bool = False
    sign: int = 1               # -1: repulsor
    spin: float = 0.0           # super well: -1..1, > 0 clockwise (it drags space round that way, faster when larger)
    omega: float = 0.0          # solid well: rotation speed (rad/tick, > 0 clockwise); its surface carries particles
    phase: float = 0.0          # angle it has turned through (for drawing)
    vx: float = 0.0
    vy: float = 0.0
    merging: bool = False       # super well being drawn into another (its speed isn't capped by its mobility)
    calm_until: int = 0         # super well: it can't go supernova before this tick (just merged or got too heavy)
    heavy: bool = False         # super well: over the supernova mass (World.explode_mass) when last checked
    auto_spin: bool = False     # super well: its spin follows its mass (World.mass_spin) while spin_follows_mass
    built: tuple = (0.0, 0.0, 0.0)   # (x, y, mass) when the field was last built

    def pull(self):
        return self.sign * config.G * self.mass

    def core(self):
        return super_core(self.mass)

    def body_radius(self):
        """Its drawn body: a solid well's size, or a super well's core (event horizon)."""
        return self.core() if self.is_super else self.radius

    def mobility(self):
        """How freely it accelerates: 1 for a weightless well, falling towards 0 as it gets heavier."""
        return config.WELL_INERTIA_MASS / (config.WELL_INERTIA_MASS + self.mass)

    def fall(self):
        """How freely gravity accelerates it: a solid well falls like a particle does, whatever its mass, so it can
        swing into orbit; a super well is as sluggish as its mobility."""
        return self.mobility() if self.is_super else 1.0

    def top_speed(self):
        return config.VMAX * (self.mobility() if self.is_super else 1.0)


@dataclass(eq=False, slots=True)
class Star:
    """A star: a ball of ordinary particles held together by their own gravity, in cell units. It has no body of its
    own. Every tick its particles are found again - those inside its capture ring (`ring`) bound to it, moving
    slower relative to it than its escape speed - and it is where they are: their centre of mass, moving with their
    momentum. It pulls as a point of their total mass there, softened over STAR_SOFTENING x its radius, whether
    self-gravity is on or not (its particles aren't in the self-gravity mesh, so they count once).

    Matter it captures becomes part of it and matter that escapes doesn't. A star that loses too much of what it
    held (see STAR_UNSTABLE_SHARE) can't hold together and explodes. Where two stars overlap the matter in between is
    shocked out, and stars whose centres meet merge."""
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    mass: float = 0.0           # its particles' mass
    count: int = 0              # how many particles
    radius: float = 1.0         # their rms distance from the centre x sqrt(2): a packed disc's radius
    ring: float = 0.0           # capture radius (cells)
    smooth: float = 0.0         # its mass, followed smoothly (STAR_SMOOTH)
    peak: float = 0.0           # the most `smooth` has been lately (STAR_PEAK_HALF_LIFE)
    size: float = 0.0           # the largest radius lately
    omega: float = 0.0          # spin of its particles about the centre (rad/tick, > 0 clockwise)
    age: int = 0                # ticks since it formed
    ox: float = 0.0             # how far it has moved since it was last carried a whole cell (see carry_stars)
    oy: float = 0.0
    fix: tuple = (0.0, 0.0)     # takes back its net pull on its own particles (see kernels.step)
    ax: float = 0.0             # how its velocity changed last tick
    ay: float = 0.0
    tide: object = None         # the star or super well whose tide reaches into its body (its Roche lobe is smaller)
    woke: tuple = (0.0, 0.0, 0.0)   # (x, y, mass) when its surroundings were last woken
    target: object = None       # (x, y) it is being dragged towards

    def pull(self):
        return config.G * self.mass

    def softening(self):
        return config.STAR_SOFTENING * max(self.radius, 1.0)


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


@dataclass(eq=False, slots=True)
class GhostStar:
    """A star still arriving: its particles (offsets dx, dy from its centre, in cells, and their masses) fly together
    as one ghost - passing through everything, feeling gravity as a particle does - and land as a star GHOST_TICKS
    after it was placed (World._land_ghost_star)."""
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    dx: np.ndarray
    dy: np.ndarray
    masses: np.ndarray
    age: int = 0

    @property
    def mass(self):
        return int(self.masses.sum())


HEAT_ROWS = 4096                # heat noted per tick (per strip on all cores); more is simply not shed


class World:
    def __init__(self, pw, ph, cell=config.DEFAULT_CELL, seed=None):
        self.vpw, self.vph = pw, ph   # the window (px); the universe is as big, or a disc round it (set_round)
        self.round = False
        self.pw, self.ph = pw, ph     # the universe (px at zoom 1)
        self.rng = np.random.default_rng(seed)
        kernels.seed(int(self.rng.integers(2 ** 31)))
        self.wells = []             # Well objects
        self.stars = []             # Star objects
        self.spawners = []          # Spawner objects
        self.gdir = None if config.GRAVITY_DIR is None else DIR_NAMES.index(config.GRAVITY_DIR)
        self.g = config.GLOBAL_G
        self.g_scale = config.GRAVITY_SCALE   # multiplies all gravity: global, wells, super wells, self-gravity
        self.reach_len = config.GRAVITY_REACH   # cells: how far every pull reaches before it fades (0: all the way)
        self.explode_mass = config.SUPER_EXPLODE_MASS   # a super well this heavy goes supernova
        self.collapse_on = config.COLLAPSE_ON
        self.spin_follows_mass = config.SUPER_SPIN_FOLLOWS_MASS
        self.star_form_on = config.STAR_FORM_ON
        self.collapses = 0
        self.explosions = 0
        self.blasts = []             # shock fronts of exploding super wells still sweeping or settling
        self.blast_serial = 0
        self.stars_formed = 0
        self.star_explosions = 0
        self.stars_torn = 0          # unstable stars torn apart in a super well's range (no explosion)
        self.calm_until = 0          # no collapse before this tick (after an explosion)
        self.wrap = config.WRAP     # continuous borders: leaving one side enters from the other
        self.orbit = config.ORBIT   # global orbit: 1 clockwise, -1 counterclockwise, 0 off
        self.sg_on = config.SG_ON
        self.sg_g = config.G
        self.held = None            # the well or spawner being dragged (it ignores gravity meanwhile)
        self.merge_on = config.MERGE_ON
        self.split_on = config.SPLIT_ON
        self.scatter = config.COLLISION_SCATTER   # radians: how far off head-on loose particles bounce
        self.lean_on = config.LEAN_ON
        self.radiation_on = config.RADIATION_ON   # merging, splitting and fusion give off heat
        self.heat_rows = np.zeros((HEAT_ROWS, 5))  # heat shed this tick, for one core (see kernels._shed)...
        self.fuse_rows = np.zeros((HEAT_ROWS, 5))  # ...and by fusion in stars
        self.heat_made = 0                         # heat particles sent out in the last tick
        self.fused = 0                             # fusions in stars in the last tick
        self.tick_count = 0
        self.stats = np.zeros(kernels.N_STATS, np.int64)
        self.step_ms = 0.0
        self.gravity_ms = 0.0
        self.mass_lut = palette.mass_lut()
        self.heat_lut = palette.heat_lut()
        self.heat_color = np.array(config.HEAT_COLOR, np.uint8)
        self.shade_mul = palette.shade_mul()
        self.bg = np.array(config.BG, np.uint8)
        self.outside = np.array(config.OUTSIDE, np.uint8)
        self.ghost_tint = np.array(config.GHOST_TINT, np.int32)
        self.cores = False          # share the work out over all CPU cores (see accelerate)
        self.gpu = None             # a gpu.Gpu taking the work it is faster at (see accelerate)
        self.field_way = self.ghost_way = None
        self.field_serial = self.hole_serial = 0   # bumped whenever the wells' field / the core map changes
        self.strips = None          # the strip step's per-strip arrays (see _step_strips)
        self.sg_tick = 0            # the tick the self-gravity mesh was last binned
        self._clear_ghosts()
        self._alloc(cell)
        self.orbit_speed = self.orbit_speed_for(config.ORBIT_EDGE_SPEED)   # rad/tick

    def _alloc(self, cell):
        self.cell = cell
        self.w, self.h = max(1, self.pw // cell), max(1, self.ph // cell)
        n = self.n = self.w * self.h
        self.rim, self.rim_mask, self.rim_v = None, None, None   # a round universe's cells outside its circle,
        if self.round:                                           # as indices and a mask (see _mark_rim)
            ys, xs = np.divmod(np.arange(n), self.w)
            rx, ry = xs + 0.5 - self.w / 2, ys + 0.5 - self.h / 2
            outside = rx * rx + ry * ry > (min(self.w, self.h) / 2) ** 2
            self.rim, self.rim_mask = np.flatnonzero(outside), outside.astype(np.uint8)
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
        self.sg = SelfGravity(self.w, self.h, wrap=self.wrap, kinv=self.kinv)
        self.hole = np.zeros(n, np.int16)       # super well k's core cells hold k + 1
        self.hole_serial += 1
        self.solid = np.zeros(n, np.uint8)      # 1 inside a normal well's body (star ground)
        self.gvx = np.zeros(n, np.float32)      # velocity of that ground (star motion + spin)
        self.gvy = np.zeros(n, np.float32)
        self.absorbed = np.zeros(1, np.int64)   # mass swallowed per well, collected after each tick
        self.owner = np.zeros(n, np.int16)      # star k's particles hold k + 1 (see Star)
        self.blob = np.zeros(n, np.int32)       # the blob the particle in each cell belongs to (see _carry_blobs)
        self.blob_v = np.zeros((1, 3))          # each blob's velocity, and 1 if the orbit carries it
        self.blob_scratch = (np.zeros(n, np.int64), np.zeros(n, np.int32), np.zeros(n, np.int32))
        self.best = np.zeros(n, np.float32)     # scratch for update_stars
        b = config.STAR_FIELD_BLOCK
        self.scw, self.sch = -(-self.w // b), -(-self.h // b)
        self.sfx = np.zeros(self.scw * self.sch)   # the stars' pull at block centres (see kernels._star_pull)
        self.sfy = np.zeros(self.scw * self.sch)
        self.star_pulls = np.zeros((0, 5))
        self.star_v = np.zeros((0, 4))
        self.star_f = np.zeros((0, 3))
        self.order_starred = False              # the ranks round stars were overridden last tick
        self.field_dirty = True                 # rebuild the field and wake everything
        self.changed_wells = []                 # wells that moved or grew: rebuild, wake only their reach
        self.bucket = self.bucket_base = None   # processing ranks: as given to the kernel, and before the stars'
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
        p[kernels.P_SCATTER] = self.scatter
        p[kernels.P_REACH] = self.kinv
        p[kernels.P_SG_ON] = self.sg_on
        p[kernels.P_ORBIT_W] = self.orbit * self.orbit_speed
        p[kernels.P_ORBIT_GRIP] = config.ORBIT_GRIP
        p[kernels.P_ORBIT_VMIN] = config.ORBIT_MIN_SPEED
        p[kernels.P_WHIRL_SPEED] = config.SUPER_SWIRL_SPEED
        p[kernels.P_WHIRL_GRIP] = config.SUPER_SWIRL_GRIP
        p[kernels.P_WHIRL_INFALL] = config.SUPER_SWIRL_INFALL
        p[kernels.P_WHIRL_EDGE] = config.SUPER_SWIRL_EDGE
        p[kernels.P_ORBIT_CX], p[kernels.P_ORBIT_CY] = self.w / 2, self.h / 2
        p[kernels.P_SG_COS], p[kernels.P_SG_SIN] = self.sg_turn()
        p[kernels.P_HEAT] = config.HEAT_SHARE if self.radiation_on else 0.0
        return p

    def sg_turn(self):
        """Cosine and sine of the angle the global orbit has turned the universe through since the self-gravity mesh
        was binned (see kernels.sg_block_at): (1, 0) with the orbit off."""
        a = self.orbit * self.orbit_speed * (self.tick_count - 1 - self.sg_tick)
        return (math.cos(a), math.sin(a)) if a else (1.0, 0.0)

    def sg_accel(self, x, y):
        """The self-gravity mesh's pull on a body at (x, y)."""
        sg = self.sg
        b = kernels.sg_block_at(x, y, self.w, self.h, sg.block, sg.cw, *self.sg_turn(), self.w / 2, self.h / 2,
                                self.wrap)
        return float(sg.gx[b]), float(sg.gy[b])

    def accelerate(self, cores=True, gpu=None, force_gpu=False):
        """Share the work out: over all CPU cores (cores), and onto a GPU (a gpu.Gpu) for the wells' field and the
        ghosts - each only while it is the faster way on this machine, timed as it runs (force_gpu: always the GPU).
        On all cores the particles run in strips side by side (_step_strips): the same physics in a slightly different
        order, so a run differs in its details, and a seed no longer repeats it exactly. With neither, every kernel
        runs as it always has (main.py --cpu)."""
        self.cores, self.gpu = cores, gpu
        ghosts = kernels.step_ghosts_par if cores else kernels.step_ghosts
        if gpu is None:
            self.field_way, self.ghost_way = None, ghosts
            return
        force = "gpu" if force_gpu else None
        self.field_way = Chooser({"cpu": external_field,
                                  "gpu": lambda *a: external_field(*a, gpu=self.gpu, key=self.field_serial)}, force,
                                 size_of=lambda w, h, rows, *rest: len(rows))
        self.ghost_way = Chooser({"cpu": ghosts,
                                  "gpu": lambda *a: self.gpu.step_ghosts(*a, self.field_serial, self.hole_serial)},
                                 force, size_of=lambda *a: a[4].size)

    def where_work_runs(self):
        """(job, where it runs, ms per call when timed) for the work that can be shared out, for the menu."""
        many = f"{numba.get_num_threads()} cores"
        out = [("particles", many if self.cores and self.strips else "1 core", None)]
        for job, way, cpu in (("field", self.field_way, many), ("ghosts", self.ghost_way,
                                                                many if self.cores else "1 core")):
            if isinstance(way, Chooser):
                out.append((job, "GPU" if way.choice == "gpu" else cpu, way.ms[way.choice]))
            else:
                out.append((job, cpu, None))
        return out

    def gravity_vector(self):
        if self.gdir is None:
            return None
        dx, dy = DIRS[self.gdir]
        k = self.g * self.g_scale / math.hypot(dx, dy)
        return dx * k, dy * k

    @property
    def kinv(self):
        """1 / how far gravity reaches (cells), as the kernels take it: 0 when it reaches all the way."""
        return 1.0 / self.reach_len if self.reach_len > 0 else 0.0

    def reach(self, well):
        """Distance (cells) at which a well's pull drops to SUPER_RANGE_ACCEL: how far waking particles matters. A
        well's pull goes on beyond it, fading; a super well's range (the dotted circle) is SUPER_RANGE_FACTOR of it."""
        return reach_for(self.g_scale * abs(well.pull()), config.SUPER_RANGE_ACCEL, self.kinv)

    def softening(self, well):
        """Distance (cells) over which a well's pull is softened: a star's size; for a super well, super_softening."""
        return self.super_softening(well.mass) if well.is_super else well.radius

    def super_softening(self, mass):
        """A super well's softening: a share of the range it would have if gravity reached all the way (never less
        than its core), so its pull near the core stays gentle enough to swing past however far gravity reaches."""
        plain = math.sqrt(self.g_scale * config.G * mass / config.SUPER_RANGE_ACCEL) * config.SUPER_RANGE_FACTOR
        return max(super_core(mass), config.SUPER_SOFTENING * plain)

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
        bodies = np.array([(wl.x, wl.y, wl.radius, wl.omega, wl.vx, wl.vy) for wl in self.wells if not wl.is_super],
                          np.float64).reshape(-1, 6)
        kernels.mark_solid(bodies, self.w, self.h, self.solid, self.gvx, self.gvy, self.mass, self.kin, self.quad,
                           self.shade, self.stamp, self.flag, self.wrap)   # also pushes out any particle inside
        self._mark_rim(full=bool(bodies.size))     # a body over the rim leaves its own velocity there
        self._mark_holes()          # also swallows particles already inside a core
        rows = [(wl.x, wl.y, self.g_scale * wl.pull(), self.softening(wl)) for wl in self.wells]
        self.field_serial += 1
        self.fx, self.fy, self.phi = (self.field_way or external_field)(self.w, self.h, rows, self.gravity_vector(),
                                                                        self.wrap, self.kinv)
        if self.field_dirty:
            self.wake_all()
        else:                       # only wells moved or grew: just the particles in their reach can notice
            for wl in self.changed_wells:
                r = self.reach(wl) + 1.0
                for x, y in ((wl.x, wl.y), wl.built[:2]):
                    (kernels.wake_disk_par if self.cores else kernels.wake_disk)(x, y, r, self.w, self.h, self.mass,
                                                                                 self.flag, self.wrap)
        for wl in self.wells:
            wl.built = (wl.x, wl.y, wl.mass)
        self.field_dirty = False
        self.changed_wells = []
        self.order_dirty = True

    def _mark_holes(self):
        cores = np.array([(k, wl.x, wl.y, wl.core()) for k, wl in enumerate(self.wells) if wl.is_super],
                         np.float64).reshape(-1, 4)
        self.absorbed = np.zeros(max(1, len(self.wells)), np.int64)
        self.hole_serial += 1
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
        mass, px, py, _ = kernels.absorb_disk(cx, cy, k * b / 2 + 2, self.w, self.h, self.mass, self.kin,
                                               self.quad, self.flag, self.wrap)
        near = [wl for wl in self.wells if wl.is_super and self.distance(wl.x, wl.y, cx, cy) < k * b]
        if near:                    # feed it, keeping momentum
            wl = near[0]
            wl.vx = (wl.vx * wl.mass + px) / (wl.mass + mass)
            wl.vy = (wl.vy * wl.mass + py) / (wl.mass + mass)
            wl.mass += int(mass)
        else:                       # a new super well moving with the matter that formed it, spitting some out
            spin = self.spawn_spin() * config.SUPER_SPIN_NATURAL
            wl = Well(cx, cy, int(mass), is_super=True, spin=spin, vx=px / mass, vy=py / mass,
                      built=(cx, cy, int(mass)), auto_spin=True)
            self.wells.append(wl)
            self.eject(wl, mass * self.rng.uniform(*config.COLLAPSE_EJECT))
        self.collapses += 1
        self.changed_wells.append(near[0] if near else self.wells[-1])

    def form_stars(self):
        """Turn knots of matter that look like young stars into stars: their particles become a star's. A knot is
        found round each of the densest spots (up to STAR_FORM_SEEDS, apart from each other): the largest disc round
        it, STAR_FORM_RADIUS cells across, that is packed (STAR_FORM_FILL) - so it is round and solid in the middle -
        and where the packing ends. It may be part of a larger body, such as a filament. It must be layered: a heavy
        core inside a lighter envelope (see layered()), and hold itself together by its own gravity (see bound()).
        None forms in or next to a star's capture ring, a solid well or a super well's core, or against a solid
        border, and at most STAR_FORM_PER_CHECK form at a time."""
        lo, hi = config.STAR_FORM_RADIUS
        b, cw, ch = self.sg.block, self.sg.cw, self.sg.ch
        rho = np.zeros(cw * ch)
        kernels.bin_mass(self.mass, self.w, self.h, b, cw, rho)
        dens = box_sum(rho.reshape(ch, cw), 1)           # mass round each block: heavy, packed knots stand out
        for st in self.stars:                            # stars are the densest spots: look elsewhere
            r = int((st.ring + config.STAR_FORM_GAP) // b) + 1
            sx, sy = int(st.x) // b, int(st.y) // b
            dens[max(0, sy - r):sy + r + 1, max(0, sx - r):sx + r + 1] = 0.0
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
            if self.layered(idx[keep], np.hypot(dx, dy)[keep] / r) and self.bound(idx[keep]):
                self._new_star(idx[keep])
                self.stars_formed += 1
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
        """Whether a knot of radius r at (x, y) would come within STAR_FORM_GAP of a star's capture ring, of a solid
        well or its crust and surroundings (three times its radius), or of a super well's core."""
        gx, gy, _, _ = self._disk_cells(x, y, r + config.STAR_FORM_GAP)
        idx = gy * self.w + gx
        if self.solid[idx].any() or self.hole[idx].any():
            return True
        for wl in self.wells:
            reach = wl.core() if wl.is_super else 3 * wl.radius
            if self.distance(wl.x, wl.y, x, y) < reach + r + config.STAR_FORM_GAP:
                return True
        for st in self.stars:
            if self.distance(st.x, st.y, x, y) < st.ring + r + config.STAR_FORM_GAP:
                return True
        return False

    def bound(self, idx):
        """Whether a knot (cells idx) could hold itself together as a star: it weighs at least twice STAR_MIN_MASS,
        and STAR_FORM_BOUND of its mass moves slower than escape speed relative to it, as a star would pull."""
        m = self.mass[idx].astype(np.float64)
        total = m.sum()
        if total < 2 * config.STAR_MIN_MASS:
            return False
        dx, dy = self._offsets(idx)
        dx, dy = dx - (dx * m).sum() / total, dy - (dy * m).sum() / total
        vx, vy = self.kin[idx, 0].astype(np.float64), self.kin[idx, 1].astype(np.float64)
        vx, vy = vx - (vx * m).sum() / total, vy - (vy * m).sum() / total
        radius = math.sqrt(max(2.0 * ((dx - dx.mean()) ** 2 + (dy - dy.mean()) ** 2).mean(), 1.0))
        soft = config.STAR_SOFTENING * radius
        rho = np.sqrt(dx * dx + dy * dy + soft * soft)
        bound = 0.5 * (vx * vx + vy * vy) < self.g_scale * config.G * total / rho * fade(rho, self.kinv)[1]
        return m[bound].sum() >= config.STAR_FORM_BOUND * total

    def _offsets(self, idx):
        """Offsets (dx, dy) of cells idx from the first of them, the short way round when the borders wrap."""
        xs, ys = (idx % self.w).astype(np.float64), (idx // self.w).astype(np.float64)
        dx, dy = xs - xs[0], ys - ys[0]
        if self.wrap:
            dx -= self.w * np.floor(dx / self.w + 0.5)
            dy -= self.h * np.floor(dy / self.h + 0.5)
        return dx, dy

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

    def _new_star(self, idx):
        """Make the particles in cells idx a star, where they are and moving as they move. Returns it."""
        m = self.mass[idx].astype(np.float64)
        total = m.sum()
        dx, dy = self._offsets(idx)
        cx, cy = idx[0] % self.w + (dx * m).sum() / total, idx[0] // self.w + (dy * m).sum() / total
        if self.wrap:
            cx, cy = cx % self.w, cy % self.h
        vx, vy = self.kin[idx, 0].astype(np.float64), self.kin[idx, 1].astype(np.float64)
        pvx, pvy = (vx * m).sum() / total, (vy * m).sum() / total
        radius = math.sqrt(max(2.0 * (((dx - dx.mean()) ** 2 + (dy - dy.mean()) ** 2).mean()), 1.0))
        st = Star(cx, cy, pvx, pvy, total, idx.size, radius, smooth=total, peak=total, size=radius,
                  woke=(cx, cy, total))
        self.stars.append(st)
        self.owner[idx] = len(self.stars)
        self._set_ring(st, grow=False)
        kernels.wake_disk(cx, cy, self.reach(st) + 1.0, self.w, self.h, self.mass, self.flag, self.wrap)
        return st

    def well_radius(self, mass):
        """The size (cells) of a placed solid well (repulsor) of this mass: its area x WELL_DENSITY is its mass."""
        return max(1.0, math.sqrt(mass / (math.pi * config.WELL_DENSITY)))

    def add_star(self, px, py, radius_px, pour_mass=1, mass=None, vx=0.0, vy=0.0, ghost=False):
        """A star at a pixel position filling the brush circle of radius_px, moving at (vx, vy). Its core is made of
        pour_mass particles (a number, or a (min, max) range: random masses in it) and its outer layers of lighter
        ones in proportion (_layer_masses), so the pour sets what it is made of and how heavy it is. Given a mass
        instead, it holds that much, shared out heavy in the middle and light outside (_fill_star). Its free cells are
        filled; particles already there become part of it. ghost: it arrives as a GhostStar instead, landing
        GHOST_TICKS later (pour mass only). Returns it (None if there was no room)."""
        c = self.cell
        cx, cy, r = px / c, py / c, max(1.0, radius_px / c)
        if mass is not None:
            idx = self._fill_star(cx, cy, r, mass, vx, vy)
            return self._new_star(idx) if idx.size else None
        xs, ys, dx, dy = self._disk_cells(cx, cy, r)
        masses = self._layer_masses(np.hypot(dx, dy) / r, pour_mass)
        if ghost:
            gs = GhostStar(cx, cy, float(vx), float(vy), r, dx, dy, masses)
            self.ghost_stars.append(gs)
            return gs
        self.place_many(xs, ys, masses, vx, vy)
        idx = ys * self.w + xs
        idx = idx[(self.mass[idx] > 0) & (self.owner[idx] == 0)]
        return self._new_star(idx) if idx.size else None

    def _layer_masses(self, d, pour_mass):
        """Particle masses for a placed star's cells at d x its radius out: pour_mass in its core, and the lighter
        layers further out the same share of it STAR_PLACE_LAYERS gives them against the core (at least 1)."""
        layers = config.STAR_PLACE_LAYERS
        core = layers[0][1]
        share = np.select([d <= edge for edge, _ in layers], [f / core for _, f in layers], layers[-1][1] / core)
        if isinstance(pour_mass, tuple):
            pour = self.rng.integers(pour_mass[0], pour_mass[1] + 1, d.size)
        else:
            pour = np.full(d.size, pour_mass)
        return np.clip(np.round(pour * share), 1, config.MAX_MASS).astype(np.int64)

    def _step_ghost_stars(self):
        """Move the ghost stars as particles move (passing through everything), let a super well's core swallow one
        whole, and land those GHOST_TICKS old."""
        for gs in list(self.ghost_stars):
            if gs is not self.held:
                ax, ay = self._body_accel(gs)
                gs.vx += ax
                gs.vy += ay
                speed = math.hypot(gs.vx, gs.vy)
                if speed > config.VMAX:
                    gs.vx *= config.VMAX / speed
                    gs.vy *= config.VMAX / speed
                gs.x += gs.vx
                gs.y += gs.vy
                if self.wrap:
                    gs.x %= self.w
                    gs.y %= self.h
                else:
                    gs.x, gs.y = min(max(gs.x, 0.0), self.w - 1.0), min(max(gs.y, 0.0), self.h - 1.0)
                    self._keep_inside(gs)
            core = next((wl for wl in self.wells if wl.is_super
                         and self.distance(wl.x, wl.y, gs.x, gs.y) <= wl.core()), None)
            if core is not None:
                core.mass += gs.mass
                self.changed_wells.append(core)
                self.ghost_stars.remove(gs)
                continue
            gs.age += 1
            if gs.age >= config.GHOST_TICKS:
                self._land_ghost_star(gs)

    def _land_ghost_star(self, gs):
        """A ghost star lands where it is, moving as it moves: its particles fill their cells and become a star;
        those whose cell is taken (or off the grid) become ordinary ghosts that land nearby next tick."""
        self.ghost_stars.remove(gs)
        xs = np.floor(gs.x + gs.dx + 0.5).astype(np.int64)
        ys = np.floor(gs.y + gs.dy + 0.5).astype(np.int64)
        if self.wrap:
            xs, ys = xs % self.w, ys % self.h
        on = (xs >= 0) & (xs < self.w) & (ys >= 0) & (ys < self.h)
        cells = np.where(on, ys * self.w + xs, 0)
        free = on & (self.mass[cells] == 0) & (self.solid[cells] == 0) & (self.hole[cells] == 0)
        self.place_many(xs[free], ys[free], gs.masses[free], gs.vx, gs.vy)
        if not free.all():
            self.add_ghosts(xs[~free].astype(np.float64), ys[~free].astype(np.float64), gs.masses[~free], gs.vx,
                            gs.vy, age=config.GHOST_TICKS - 1)
        idx = cells[on]
        idx = idx[(self.mass[idx] > 0) & (self.owner[idx] == 0)]
        if idx.size:
            self._new_star(idx)

    def _body_accel(self, b):
        """What moves a spawner or ghost star at (b.x, b.y) moving at (b.vx, b.vy) as it would a particle there: the
        wells' field and global gravity, self-gravity, the global orbit, the super wells' whirlpools and the stars."""
        i = min(int(b.y), self.h - 1) * self.w + min(int(b.x), self.w - 1)
        ax, ay = float(self.fx[i]), float(self.fy[i])
        if self.sg_on:
            gx, gy = self.sg_accel(b.x, b.y)
            ax += gx
            ay += gy
        if self.orbit:
            ox, oy = self._orbit_accel(b.x, b.y, b.vx, b.vy)
            ax += ox
            ay += oy
        ox, oy = self._whirl_accel(b, b.x, b.y, b.vx, b.vy)
        ax += ox
        ay += oy
        if self.stars:
            ox, oy = self._stars_accel(b.x, b.y)
            ax += ox
            ay += oy
        return ax, ay

    def _fill_star(self, cx, cy, r, mass, vx, vy, k=-1):
        """Fill the free cells within r of (cx, cy) with a layered ball of particles holding `mass` (as far as
        MAX_MASS allows), moving at (vx, vy). Returns the cells with particles in that disc that belong to no star or
        to star k."""
        xs, ys, dx, dy = self._disk_cells(cx, cy, r)
        d = np.hypot(dx, dy) / r
        layers = config.STAR_PLACE_LAYERS
        rel = np.select([d <= edge for edge, _ in layers], [f for _, f in layers], layers[-1][1])
        masses = np.clip(np.round(mass / rel.sum() * rel * self.rng.uniform(0.75, 1.25, rel.size)), 1,
                         config.MAX_MASS).astype(np.int64)
        self.place_many(xs, ys, masses, vx, vy)
        idx = ys * self.w + xs
        return idx[(self.mass[idx] > 0) & ((self.owner[idx] == 0) | (self.owner[idx] == k + 1))]

    def _star_cells(self, k, st):
        """The cells holding star k's particles."""
        xs, ys, _, _ = self._disk_cells(st.x, st.y, st.ring + 2.0)
        idx = ys * self.w + xs
        return idx[self.owner[idx] == k + 1]

    def _remap_owner(self, target):
        """Star k's particles go to star target[k] (-1: to none)."""
        table = np.zeros(len(target) + 1, np.int16)
        table[1:] = np.asarray(target) + 1
        self.owner[:] = table[self.owner]

    def _drop_stars(self, target):
        """Remove the stars whose target isn't themselves; the particles of each go to the star it names (merged)
        or to none, and the rest are renumbered."""
        survivors = [k for k in range(len(target)) if target[k] == k]
        new = {k: n for n, k in enumerate(survivors)}
        self._remap_owner([new.get(final_star(target, k), -1) for k in range(len(target))])
        if self.held in self.stars and target[self.stars.index(self.held)] != self.stars.index(self.held):
            self.held = None
        self.stars = [self.stars[k] for k in survivors]

    def _set_ring(self, st, grow=True):
        """A star's capture ring: where its pull drops to STAR_CAPTURE_ACCEL, cut down to its Roche lobe against
        each other star and super well; between STAR_RING_MIN x its largest radius lately (and 2 cells) and
        STAR_RING_MAX x its radius, widening by at most STAR_RING_GROWTH a tick."""
        r = reach_for(self.g_scale * st.pull(), config.STAR_CAPTURE_ACCEL, self.kinv)
        st.tide = None
        for b in self.stars + self.wells:
            if b is st or (isinstance(b, Well) and not b.is_super) or b.mass <= 0:
                continue
            d = self.distance(st.x, st.y, b.x, b.y)
            lobe = d * roche_lobe(max(st.mass, 1.0) / (b.mass * self.tide_share(d)))
            r = min(r, lobe)
            if lobe < st.radius and b.mass > st.mass:
                st.tide = b
        lo = max(2.0, config.STAR_RING_MIN * st.size)
        r = min(max(r, lo), max(lo, config.STAR_RING_MAX * st.radius))
        st.ring = min(r, st.ring + config.STAR_RING_GROWTH) if grow else r

    def tide_share(self, d):
        """How much of the plain inverse-square tide (the change of a pull across a body) is left at distance d as
        gravity fades: e^(-x) (1 + x + x^2 / 2), x = d / reach. A faraway companion hardly stretches a star."""
        x = d * self.kinv
        return math.exp(-x) * (1.0 + x + 0.5 * x * x)

    def carry_stars(self):
        """Move each star as a whole at its velocity - the momentum of its body (the particles packed together, not
        loose matter it has captured) over its mass, as this tick's forces left it: once it has gone half a cell, all
        its particles are carried a cell (kernels.star_shift), so they travel together however fast it goes; loose
        ones make up the difference to their own velocity themselves. Returns how far each was carried."""
        motion = np.zeros((len(self.stars), 6))
        kernels.star_motion(np.array([(st.x, st.y, st.ring + 2.0) for st in self.stars], np.float64), self.w, self.h,
                            self.mass, self.kin, self.owner, motion, self.wrap)
        for st, row in zip(self.stars, motion):
            m, px, py = row[:3] if row[0] > 0 else row[3:]
            if m > 0:
                st.ax, st.ay = px / m - st.vx, py / m - st.vy
                st.vx, st.vy = px / m, py / m
        carried = []
        for k, st in enumerate(self.stars):
            st.ox += st.vx
            st.oy += st.vy
            cx, cy = 0, 0
            for _ in range(config.MAX_STEPS):
                sx = 1 if st.ox >= 0.5 else (-1 if st.ox <= -0.5 else 0)
                sy = 1 if st.oy >= 0.5 else (-1 if st.oy <= -0.5 else 0)
                if sx == 0 and sy == 0:
                    break
                kernels.star_shift(k, sx, sy, st.x + cx, st.y + cy, st.ring + 2.0, config.RESTITUTION,
                                   config.WALL_E, self.w, self.h, self.mass, self.kin, self.quad, self.shade,
                                   self.stamp, self.flag, self.owner, self.solid, self.hole, self.absorbed, self.wrap)
                st.ox -= sx
                st.oy -= sy
                cx += sx
                cy += sy
            st.ox, st.oy = min(max(st.ox, -0.5), 0.5), min(max(st.oy, -0.5), 0.5)
            carried.append((cx, cy))
        return carried

    def step_stars(self):
        """Carry the stars (carry_stars), find each one's particles again (kernels.update_stars) and follow its mass,
        centre of mass, size and spin. Then stars that overlap shock the matter between them (kernels.star_shock),
        heavy matter sinks inside them (kernels.star_sink), and stars whose centres meet, or that touch gently,
        merge. One that can no longer hold together merges into a star it touches, is torn apart by a tide, or
        explodes. Last, the rings are set for the next tick and what moving stars pass is woken."""
        stars = self.stars
        if not stars:
            return
        carried = self.carry_stars()
        self._collect_absorbed()
        rows = np.array([((st.x - st.ox + cx) % self.w if self.wrap else st.x - st.ox + cx,
                          (st.y - st.oy + cy) % self.h if self.wrap else st.y - st.oy + cy, st.vx, st.vy,
                          self.g_scale * st.pull(), st.softening() ** 2, st.ring + 1.0)
                         for st, (cx, cy) in zip(stars, carried)], np.float64)
        sums = np.zeros((len(stars), 11))
        kernels.update_stars(rows, self.w, self.h, self.mass, self.kin, self.owner, self.best, sums, self.wrap,
                             self.kinv)
        keep = 1.0 - config.STAR_SMOOTH
        fade = 0.5 ** (1.0 / config.STAR_PEAK_HALF_LIFE)
        for k, st in enumerate(stars):
            m, n = sums[k, 0], sums[k, 5]
            st.x, st.y = rows[k, 0], rows[k, 1]
            if n > 0:                                    # where its particles are, and how far it has yet to be carried
                st.x, st.y = st.x + sums[k, 1] / m + st.ox, st.y + sums[k, 2] / m + st.oy
                if self.wrap:
                    st.x, st.y = st.x % self.w, st.y % self.h
                ox, oy = sums[k, 6] / n, sums[k, 7] / n
                st.radius = math.sqrt(max(2.0 * (sums[k, 8] / n - ox * ox - oy * oy), 1.0))
                st.omega = sums[k, 9] / sums[k, 10] if sums[k, 10] > 0 else 0.0
            st.mass, st.count = m, int(n)
            st.smooth = keep * st.smooth + (1.0 - keep) * m
            st.peak = max(st.smooth, st.peak * fade)
            st.size = max(st.radius, st.size * fade)
            st.age += 1
        self._shock_stars()
        self.stats[kernels.S_SINKS] += kernels.star_sink(
            np.array([(st.x, st.y, st.ring) for st in stars], np.float64), config.SINK_CHANCE, self.w, self.h,
            self.mass, self.kin, self.quad, self.shade, self.stamp, self.owner, self.wrap)
        target = list(range(len(stars)))
        for i in range(len(stars)):                      # stars whose centres meet, or that touch gently, merge
            for j in range(i + 1, len(stars)):
                a, b = stars[i], stars[j]
                if target[i] != i or target[j] != j or not (a.count and b.count):
                    continue
                d = self.distance(a.x, a.y, b.x, b.y)
                if d < config.STAR_MERGE * max(a.size, b.size) or (
                        d < a.radius + b.radius and math.hypot(b.vx - a.vx, b.vy - a.vy) < config.STAR_SHOCK_MIN):
                    big, small = (i, j) if a.mass >= b.mass else (j, i)
                    self._merge_stars(stars[big], stars[small])
                    target[small] = big
        unstable = [k for k, st in enumerate(stars) if target[k] == k and (
            st.count < config.STAR_MIN_PARTICLES or st.age >= config.STAR_SETTLE and (
                st.smooth < config.STAR_UNSTABLE_SHARE * st.peak or st.smooth < config.STAR_MIN_MASS))]
        for k in unstable:                               # one failing in another's embrace merges into it
            st = stars[k]
            touching = [j for j in range(len(stars)) if j != k and target[j] == j and stars[j].count
                        and self.distance(st.x, st.y, stars[j].x, stars[j].y) < st.radius + stars[j].radius]
            if touching and target[k] == k:
                j = max(touching, key=lambda j: stars[j].mass)
                self._merge_stars(stars[j], st)
                target[k] = j
        if target != list(range(len(stars))):          # the merged ones' particles are the other's now
            self._remap_owner([final_star(target, k) for k in range(len(target))])
        for k in unstable:
            st = stars[k]
            if target[k] != k:
                continue
            target[k] = -1
            if st.tide is not None or any(wl.is_super and self.distance(wl.x, wl.y, st.x, st.y) < self.well_range(wl)
                                          for wl in self.wells):
                self.stars_torn += 1                     # torn apart by a tide: its particles stream away
            elif st.count:
                self._explode_star(k, st)
        if target != list(range(len(stars))):
            self._drop_stars(target)
        for st in self.stars:
            self._set_ring(st)
            wx, wy, wm = st.woke
            moved = self.distance(st.x, st.y, wx, wy)
            if moved > config.WELL_REBUILD_MOVE or abs(st.mass - wm) > 0.1 * max(wm, 1.0):
                kernels.wake_disk(st.x, st.y, self.reach(st) + moved + 1.0, self.w, self.h, self.mass, self.flag,
                                  self.wrap)
                st.woke = (st.x, st.y, st.mass)
        if self.held in self.stars and self.held.target is not None:
            self._drag_star(self.held)

    def _shock_stars(self):
        """Stars whose circles (their radii) overlap while moving apart or together faster than STAR_SHOCK_MIN shock
        the matter where they touch, as deep into each as they move relative to each other in STAR_SHOCK_DEPTH
        ticks: it splashes out sideways at up to STAR_SHOCK x their relative speed and stays only if it is still
        bound. A grazing touch shaves their surfaces; a fast head-on crash scatters much of both."""
        stars = self.stars
        for i, a in enumerate(stars):
            for j in range(i + 1, len(stars)):
                b = stars[j]
                if not (a.count and b.count) or self.distance(a.x, a.y, b.x, b.y) >= a.radius + b.radius:
                    continue
                u = math.hypot(b.vx - a.vx, b.vy - a.vy)
                if u < config.STAR_SHOCK_MIN:
                    continue
                small, big, ks, kb = (a, b, i, j) if a.radius <= b.radius else (b, a, j, i)
                depth = config.STAR_SHOCK_DEPTH * u
                kernels.star_shock(small.x, small.y, small.radius + depth, big.x, big.y, big.radius + depth, ks, kb,
                                   config.STAR_SHOCK * u, self.w, self.h, self.mass, self.kin, self.owner,
                                   self.stamp, self.flag, self.wrap)

    def _merge_stars(self, big, small):
        """small merges into big: what they hold, and how much they held lately, add up; big moves to their common
        centre of mass, with their momentum."""
        total = big.mass + small.mass
        if total > 0:
            dx, dy = self.delta(big.x, big.y, small.x, small.y)
            big.x += dx * small.mass / total
            big.y += dy * small.mass / total
            if self.wrap:
                big.x, big.y = big.x % self.w, big.y % self.h
            big.vx = (big.vx * big.mass + small.vx * small.mass) / total
            big.vy = (big.vy * big.mass + small.vy * small.mass) / total
            big.fix = tuple((f * big.mass + g * small.mass) / total for f, g in zip(big.fix, small.fix))
        big.mass, big.count = total, big.count + small.count
        big.smooth += small.smooth
        big.peak += small.peak
        big.radius = math.hypot(big.radius, small.radius)
        big.size = math.hypot(big.size, small.size)
        big.ring = max(big.ring, small.ring)

    def _explode_star(self, k, st):
        """Star k can't hold together: it blows up like a small supernova. Its particles leave as debris (ghosts,
        so they spread rather than jam) riding a shock front from its surface out to STAR_BLAST_REACH x its size,
        which shoves what it passes outwards."""
        idx = self._star_cells(k, st)
        self.star_explosions += 1
        if not idx.size:
            return
        reach = max(min(config.STAR_BLAST_REACH * st.size + 10.0, 0.45 * min(self.w, self.h)), st.radius + 5.0)
        self.blast_serial += 1
        blast = Blast(st.x, st.y, max(st.radius, 2.0), reach, self.blast_serial, config.STAR_BLAST_SPEED,
                      config.STAR_BLAST_PUSH * reach)
        self.blasts.append(blast)
        xs = idx % self.w + self.rng.uniform(-0.45, 0.45, idx.size)
        ys = idx // self.w + self.rng.uniform(-0.45, 0.45, idx.size)
        dx, dy = xs - st.x, ys - st.y
        if self.wrap:
            dx -= self.w * np.floor(dx / self.w + 0.5)
            dy -= self.h * np.floor(dy / self.h + 0.5)
        d = np.maximum(np.hypot(dx, dy), 1e-9)
        out = blast.speed(d) / d
        self.add_ghosts(xs, ys, self.mass[idx].astype(np.int64), st.vx + dx * out, st.vy + dy * out, tag=blast.tag)
        self.mass[idx] = 0
        self.kin[idx] = 0.0
        self.quad[idx] = 0
        self.owner[idx] = 0
        kernels.wake_disk(st.x, st.y, st.ring + 3.0, self.w, self.h, self.mass, self.flag, self.wrap)

    def _drag_star(self, st):
        """A star being dragged: its particles head for the target together, faster the further away it is."""
        dx, dy = self.delta(st.x, st.y, *st.target)
        vx, vy = 0.2 * dx, 0.2 * dy
        speed = math.hypot(vx, vy)
        if speed > 0.5 * config.VMAX:
            vx, vy = vx * 0.5 * config.VMAX / speed, vy * 0.5 * config.VMAX / speed
        idx = self._star_cells(self.stars.index(st), st)
        self.kin[idx, 0] = vx
        self.kin[idx, 1] = vy
        self.flag[idx] = 1
        st.vx, st.vy, st.ax, st.ay = vx, vy, 0.0, 0.0

    def remove_star(self, st):
        """Delete a star and its particles."""
        k = self.stars.index(st)
        idx = self._star_cells(k, st)
        self.mass[idx] = 0
        self.kin[idx] = 0.0
        self.quad[idx] = 0
        kernels.wake_disk(st.x, st.y, st.ring + 3.0, self.w, self.h, self.mass, self.flag, self.wrap)
        target = list(range(len(self.stars)))
        target[k] = -1
        self._drop_stars(target)

    def scale_star(self, st, factor):
        """Make a star heavier or lighter by factor: it is rebuilt where it is, moving as it moves, its radius x
        sqrt(factor), made as it is now - each ring of it holding particles as heavy as that share of its radius
        holds now on average (rounded at random, so its mass comes out factor x as heavy) - so a star of
        pour-mass particles stays one. Its pull, softening and capture ring are a fresh one's. It holds all of its new
        mass from now (it isn't unstable for having been made lighter)."""
        k = self.stars.index(st)
        old = self._star_cells(k, st)
        ox, oy = old % self.w - st.x, old // self.w - st.y
        if self.wrap:
            ox -= self.w * np.floor(ox / self.w + 0.5)
            oy -= self.h * np.floor(oy / self.h + 0.5)
        rings = 8                                        # its make-up, ring by ring out to its radius
        ring = np.minimum((np.hypot(ox, oy) / max(st.radius, 1.0) * rings).astype(np.int64), rings - 1)
        held = np.bincount(ring, weights=self.mass[old], minlength=rings)
        cells = np.bincount(ring, minlength=rings)
        profile = np.divide(held, cells, out=np.zeros(rings), where=cells > 0)
        for q in range(1, rings):                        # a ring with nothing left in it: as the one inside it
            if not cells[q]:
                profile[q] = profile[q - 1]
        if not cells[0]:
            profile[0] = profile[cells > 0][0] if cells.any() else 1.0
        self.mass[old] = 0
        self.kin[old] = 0.0
        self.quad[old] = 0
        self.owner[old] = 0
        r = max(1.0, st.radius * math.sqrt(factor))
        xs, ys, dx, dy = self._disk_cells(st.x, st.y, r)
        p = profile[np.minimum((np.hypot(dx, dy) / r * rings).astype(np.int64), rings - 1)]
        masses = np.clip(np.floor(p + self.rng.random(p.size)), 1, config.MAX_MASS).astype(np.int64)
        self.place_many(xs, ys, masses, st.vx, st.vy)
        idx = ys * self.w + xs
        idx = idx[(self.mass[idx] > 0) & ((self.owner[idx] == 0) | (self.owner[idx] == k + 1))]
        if not idx.size:
            return
        self.owner[idx] = k + 1
        m = float(self.mass[idx].sum(dtype=np.int64))
        dx, dy = self._offsets(idx)
        st.mass = st.smooth = st.peak = m
        st.count = idx.size
        st.radius = st.size = math.sqrt(max(2.0 * (((dx - dx.mean()) ** 2 + (dy - dy.mean()) ** 2).mean()), 1.0))
        st.ox = st.oy = 0.0
        self._set_ring(st, grow=False)
        kernels.wake_disk(st.x, st.y, self.reach(st) + 1.0, self.w, self.h, self.mass, self.flag, self.wrap)

    def _stars_accel(self, x, y):
        """The stars' pull on a body at (x, y)."""
        ax = ay = 0.0
        for st in self.stars:
            dx, dy = self.delta(x, y, st.x, st.y)
            rho = math.sqrt(dx * dx + dy * dy + st.softening() ** 2)
            f = self.g_scale * st.pull() / rho ** 3 * fade(rho, self.kinv)[0]
            ax += dx * f
            ay += dy * f
        return ax, ay

    def _star_field(self):
        """The stars' pull for the kernels: rows of x, y, strength, softening^2 and near radius^2 (where their
        exact pull replaces the blended far field: their ring, at least 4 softening lengths and 3 blocks), and that
        far field at block centres."""
        b = config.STAR_FIELD_BLOCK
        rows = []
        for st in self.stars:
            soft = st.softening()
            near = max(st.ring, 4.0 * soft, 3.0 * b)
            rows.append((st.x, st.y, self.g_scale * st.pull(), soft * soft, near * near))
        self.star_pulls = np.array(rows, np.float64).reshape(-1, 5)
        self.star_v = np.array([(st.vx + st.ax, st.vy + st.ay, *st.fix) for st in self.stars],
                               np.float64).reshape(-1, 4)
        self.star_f = np.zeros((len(self.stars), 3))
        if self.stars:
            kernels.star_field(self.star_pulls, self.w, self.h, b, self.scw, self.sch, self.sfx, self.sfy, self.wrap,
                               self.kinv)

    def _order_stars(self):
        """Re-rank the cells round each star for processing in its own frame (kernels.star_order)."""
        np.copyto(self.bucket, self.bucket_base)
        if self.stars:
            rows = np.array([(st.x, st.y, min(st.ring, 1.5 * st.size + 3.0)) for st in self.stars], np.float64)
            kernels.star_order(rows, self.bucket_counts.size - 1, self.w, self.h, self.bucket_base, self.bucket,
                               self.wrap)
        self.order_starred = bool(self.stars)

    def step_wells(self):
        """Move the wells: they attract each other and feel the stars (and the particles when self-gravity is on).
        Solid wells fall freely, like particles; super wells, and every well's response to the global orbit and the
        whirlpools, are slower the heavier they are. A super well swallows any well that reaches its core."""
        wells = self.wells
        if not wells:
            return
        xs = np.array([wl.x for wl in wells])
        ys = np.array([wl.y for wl in wells])
        pulls = self.g_scale * np.array([wl.pull() for wl in wells])
        soft = np.array([self.softening(wl) for wl in wells])
        for wl in wells:                                # turn (for drawing)
            if wl.is_super:
                if self.spin_follows_mass and wl.auto_spin:
                    wl.spin = math.copysign(self.mass_spin(wl.mass), wl.spin)
                wl.phase += self.whirl_omega(wl)
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
            rho = np.sqrt(d2 + soft * soft)
            f = pulls / rho ** 3 * fade(rho, self.kinv)[0]
            f[k] = 0.0
            ax, ay = float((dx * f).sum()), float((dy * f).sum())
            if self.stars:
                sx, sy = self._stars_accel(wl.x, wl.y)
                ax += sx
                ay += sy
            if self.sg_on:
                gx, gy = self.sg_accel(wl.x, wl.y)
                ax += gx
                ay += gy
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
                self._keep_inside(wl)
            # a super well's field is soft and its core several cells across: half its core is close enough
            moved = max(config.WELL_REBUILD_MOVE, 0.5 * wl.core()) if wl.is_super else config.WELL_REBUILD_MOVE
            if self.distance(wl.x, wl.y, wl.built[0], wl.built[1]) > moved:
                self.changed_wells.append(wl)
        self._swallow_wells()
        for wl in [wl for wl in self.wells if wl.is_super]:
            heavy = wl.mass >= self.explode_mass
            if heavy and not wl.heavy:  # just got too heavy, however (merging, swallowing, fed by collapse): it waits
                wl.calm_until = max(wl.calm_until, self.tick_count + config.SUPER_MERGE_GRACE)
            wl.heavy = heavy
            if heavy and self.tick_count >= wl.calm_until:
                self.explode(wl)

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

    def explode(self, wl):
        """A super well that grew too heavy goes supernova: it vanishes and all its mass comes back out from where it
        was as very heavy debris (ghosts, so nothing in the way stops them) flying outwards behind a shock front that
        shoves every particle it passes away, further the nearer it was (see `_step_blasts`). The debris expands with
        the front, each piece at its own share of the front's radius (spread so it ends up evenly over the area the
        front swept clear: SUPER_BLAST_FILL), and cools as it flies, breaking into lighter pieces (see
        `_cool_blasts`). Collapse is held off for SUPER_EXPLODE_CALM ticks so the debris can spread."""
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
        share = np.sqrt(rng.uniform(config.SUPER_BLAST_FILL ** 2, 1.0, masses.size))   # even over the area
        r = r0 * share
        s = share * blast.speed(r0)
        self.add_ghosts(wl.x + r * np.cos(a), wl.y + r * np.sin(a), masses, wl.vx + s * np.cos(a),
                        wl.vy + s * np.sin(a), tag=blast.tag)
        self.explosions += 1
        self.calm_until = self.tick_count + config.SUPER_EXPLODE_CALM

    def _step_blasts(self):
        """Sweep each shock front on: it shoves the particles it passes outwards, and damps the outward motion of
        everything behind it, so what it pushed back stops after a while."""
        for b in self.blasts:
            if b.source is not None and b.source in self.wells:
                b.x, b.y = b.source.x, b.source.y
            r_new = b.r + float(b.speed(b.r))
            if r_new >= b.reach - 0.05:
                r_new = b.reach
            if b.r < b.reach:
                kernels.blast_push(b.x, b.y, b.r, r_new, b.reach, b.push, b.drag, b.wind,
                                   0.95 * config.VMAX, self.w, self.h, self.mass, self.kin, self.stamp, self.flag,
                                   self.solid, self.wrap)
            elif b.wind:
                # the front has stopped, but its wind blows on over all of its reach
                kernels.blast_push(b.x, b.y, b.reach + 1.0, b.reach, b.reach, b.push, b.drag, True,
                                   0.95 * config.VMAX, self.w, self.h, self.mass, self.kin, self.stamp, self.flag,
                                   self.solid, self.wrap)
                b.settled += 1
            else:
                # the front has stopped: no ring to shove (r_in past r_out), only the fading behind it
                kernels.blast_push(b.x, b.y, b.reach + 1.0, b.reach, b.reach, 0.0, b.drag, False, 0.0,
                                   self.w, self.h, self.mass, self.kin, self.stamp, self.flag, self.solid, self.wrap)
                b.settled += 1
            b.r = r_new
        self.blasts = [b for b in self.blasts if b.settled < (b.blow if b.wind else config.SUPER_BLAST_SETTLE)]

    def _cool_blasts(self):
        """Blast debris (ghosts tagged with their blast's number) expands with its front while the blast lasts, each
        piece moving outwards at its share of the front's radius x the front's speed, so it keeps that share and
        stops where the front stops, spread over the area it swept. It cools however long that is: every
        SUPER_BLAST_COOL_EVERY ticks from
        SUPER_BLAST_COOL_FROM each piece heavier than SUPER_BLAST_COOL_TO breaks in two, the new piece landing up to
        about SUPER_BLAST_SCATTER cells away so the pieces spread out rather than stack up. Once cool, and at rest
        or its blast over, a piece lands as an ordinary particle where it is (next tick), before anything can pull
        the debris together into a crowd with no room for it."""
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
            speed = np.minimum(d / b.r, 1.0) * float(b.speed(b.r))   # none once the front has stopped
            vx, vy = self.ghost_vx[sel], self.ghost_vy[sel]
            along = vx * ux + vy * uy
            self.ghost_vx[sel] = speed * ux + 0.9 * (vx - along * ux)   # sideways drift fades
            self.ghost_vy[sel] = speed * uy + 0.9 * (vy - along * uy)
        age = self.ghost_age[hot]
        due = hot[(age >= config.SUPER_BLAST_COOL_FROM)
                  & ((age - config.SUPER_BLAST_COOL_FROM) % config.SUPER_BLAST_COOL_EVERY == 0)
                  & (self.ghost_m[hot] > config.SUPER_BLAST_COOL_TO)]
        if due.size:
            m = self.ghost_m[due]
            new = np.clip(np.round(m * self.rng.uniform(0.3, 0.7, due.size)), 1, m - 1).astype(np.int64)
            self.ghost_m[due] = m - new
            jx, jy = self.rng.normal(0.0, config.SUPER_BLAST_SCATTER, (2, due.size))
            for tag in np.unique(self.ghost_tag[due]):
                k = self.ghost_tag[due] == tag
                self.add_ghosts(self.ghost_x[due[k]] + jx[k], self.ghost_y[due[k]] + jy[k], new[k],
                                self.ghost_vx[due[k]], self.ghost_vy[due[k]], tag=int(tag), age=self.ghost_age[due[k]])
        hot = self.ghost_tag > 0
        over = ~np.isin(self.ghost_tag, list(active))
        still = np.hypot(self.ghost_vx, self.ghost_vy) < 0.1
        done = hot & (self.ghost_m <= config.SUPER_BLAST_COOL_TO) & (over | still)
        self.ghost_tag[done] = 0
        self.ghost_age[done] = np.maximum(self.ghost_age[done], config.GHOST_TICKS)   # lands where it came to rest

    def scale_spin(self, wl, factor):
        """Spin a super well faster or slower, keeping its direction, between 0.05 and SUPER_SPIN_MAX."""
        self.set_spin(wl, wl.spin * factor)

    def set_spin(self, wl, spin):
        """Set a super well's spin (> 0 clockwise), its size between 0.05 and SUPER_SPIN_MAX. Set by hand, it no
        longer follows the well's mass."""
        wl.spin = math.copysign(min(config.SUPER_SPIN_MAX, max(0.05, abs(spin))), spin)
        wl.auto_spin = False
        self.wake_all()

    def whirl_omega(self, wl):
        """How fast a super well's whirlpool carries matter round (rad/tick, > 0 clockwise), SUPER_SPIN_ARMS_AT of the
        way out to its dotted circle: the speed its whirl drives things towards there (kernels.whirl), never over
        VMAX. Its spiral arms turn at this."""
        reach = self.well_range(wl)
        d = max(config.SUPER_SPIN_ARMS_AT * reach, 1.0)
        _, target, _ = kernels.whirl(d, 0.0, 0.0, 0.0, reach, wl.spin, self.g_scale * wl.pull(), self.softening(wl),
                                     config.SUPER_SWIRL_SPEED, 1.0, config.SUPER_SWIRL_INFALL, config.SUPER_SWIRL_EDGE,
                                     self.kinv)
        return math.copysign(min(abs(target), config.VMAX), target) / d

    def set_spin_follows_mass(self, on):
        """Let super wells' spin rise with their mass, or not. Turned off, every super well goes back to the spin a
        new one starts with (SUPER_SPIN_PLACED, the way it turns now), its hand-set spin too, and follows its mass
        again if this is turned back on."""
        self.spin_follows_mass = on
        if on:
            return
        for wl in self.wells:
            if wl.is_super:
                wl.spin = math.copysign(config.SUPER_SPIN_PLACED, wl.spin)
                wl.auto_spin = True
        self.wake_all()

    def mass_spin(self, mass):
        """How fast a super well of this mass spins while its spin follows its mass: SUPER_SPIN_PLACED when it is
        new, rising in a straight line to SUPER_SPIN_FULL at the supernova mass."""
        x = min(1.0, mass / self.explode_mass)
        return config.SUPER_SPIN_PLACED + (config.SUPER_SPIN_FULL - config.SUPER_SPIN_PLACED) * x

    def step_spawners(self):
        """Move unlocked spawners under gravity (like a particle, passing through everything), delete any that reach
        a super well's core, and let each pour its particles."""
        for sp in list(self.spawners):
            if not sp.locked and sp is not self.held:
                ax, ay = self._body_accel(sp)
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
                    self._keep_inside(sp)
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
        # escape speed from the well as it will be: 1/2 v^2 = its potential's depth there, S / rho faded
        left = wl.mass - amount
        strength = self.g_scale * config.G * left
        soft = self.super_softening(left)

        def launch_speed(r):
            rho = np.sqrt(r * r + soft * soft)
            v_esc = np.sqrt(2 * strength / rho * fade(rho, self.kinv)[1])
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
        """A super well swallows a solid well touching its core, and two super wells merge when their cores touch:
        mass adds up and momentum is conserved. A merger sends out a shock (merge_shock) and can't go supernova for
        SUPER_MERGE_GRACE ticks (more mergers in that time don't make it longer)."""
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
                    if not b.is_super:
                        if d <= a.core() + b.radius:
                            a.vx = (a.vx * a.mass + b.vx * b.mass) / (a.mass + b.mass)
                            a.vy = (a.vy * a.mass + b.vy * b.mass) / (a.mass + b.mass)
                            a.mass += b.mass
                            self.remove_well(b)
                            merged = True
                            break
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
                    if self.tick_count >= big.calm_until:   # a window already open isn't stretched by more mergers
                        big.calm_until = self.tick_count + config.SUPER_MERGE_GRACE
                    self.merge_shock(big)
                    self.field_dirty = True
                    merged = True
                    break
                if merged:
                    break

    def merge_shock(self, wl):
        """Two super wells have just merged into wl: a shock front runs out from it (moving with it) to
        SUPER_MERGE_SHOCK_REACH x its range, starting at SUPER_MERGE_SHOCK_SPEED so it gets ahead of what is falling
        in, and behind the front a wind keeps everything moving outwards at SUPER_MERGE_SHOCK_KICK - faster than
        the well, self-gravity and the global orbit pull it back - sweeping it into a shell, so the merger clears
        the matter round it instead of swallowing it at once. The wind blows for SUPER_MERGE_SHOCK_TICKS in all;
        then the matter falls back in its own time."""
        r0 = max(wl.core() + 1.0, 2.0)
        reach = max(min(config.SUPER_MERGE_SHOCK_REACH * self.well_range(wl), 0.45 * min(self.w, self.h)), r0 + 5.0)
        self.blast_serial += 1
        drag = config.SUPER_BLAST_DRAG
        v0 = config.SUPER_MERGE_SHOCK_SPEED
        run = 2.0 * (reach - r0) / v0                    # ticks the front takes, slowing as Blast.speed does
        self.blasts.append(Blast(wl.x, wl.y, r0, reach, self.blast_serial, v0, config.SUPER_MERGE_SHOCK_KICK / drag,
                                 drag, wind=True, blow=max(0, round(config.SUPER_MERGE_SHOCK_TICKS - run)), source=wl))

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
                                          config.SUPER_SWIRL_INFALL, config.SUPER_SWIRL_EDGE, self.kinv)
                ax += wx
                ay += wy
        return ax, ay

    def _orbit_accel(self, x, y, vx, vy):
        return kernels.orbit_accel(x - self.w / 2, y - self.h / 2, vx, vy, self.orbit * self.orbit_speed,
                                   config.ORBIT_GRIP, config.ORBIT_MIN_SPEED)

    def orbit_speed_for(self, edge_speed):
        """The global orbit's angular speed (rad/tick) that turns the edge of the window (half its shorter side out
        from the centre) at edge_speed cells/tick."""
        r = min(self.vw, self.vh) / 2
        return math.sqrt(max(edge_speed ** 2 - config.ORBIT_MIN_SPEED ** 2, 0.0)) / r

    def orbit_edge_speed(self):
        """Speed the global orbit turns things at the edge of the window (cells/tick)."""
        r = min(self.vw, self.vh) / 2
        return math.hypot(self.orbit_speed * r, config.ORBIT_MIN_SPEED)

    @property
    def vw(self):
        """The window's width in cells (the universe is as wide, or wider when round)."""
        return max(1, self.vpw // self.cell)

    @property
    def vh(self):
        return max(1, self.vph // self.cell)

    def rebuild_order(self, cut_only=False):
        """Rank cells for leading-particles-first processing: lowest potential first and, with the global orbit on,
        furthest ahead in the direction of turning first, so a moving clump's front moves before the rest follow.
        cut_only: the potential hasn't changed, only turn the orbit's cut (cheap: no re-ranking)."""
        self.order_tick = self.tick_count
        if not self.orbit:
            self._set_buckets(order_buckets(np.asarray(self.phi, np.float32), self.rng, cores=self.cores))
            self.order_dirty = False
            return
        nb = 4096
        if self.angle_rank is None or self.angle_rank.size != self.n or self.angle_key != (self.w, self.h):
            ys, xs = np.divmod(np.arange(self.n), self.w)
            angle = np.arctan2(ys - self.h / 2, xs - self.w / 2).astype(np.float32)
            self.angle_rank = order_buckets(angle, self.rng, nb, self.cores).astype(np.int32)
            self.angle_key = (self.w, self.h)
        if not cut_only or self.phi_rank is None:
            flat = float(self.phi.max() - self.phi.min()) <= 1e-9
            self.phi_rank = None if flat else order_buckets(self.phi, self.rng, nb, self.cores).astype(np.int32)
            self.order_dirty = False
        # Ranked by angle there is a cut where the rank jumps from last to first: flow crossing it is processed
        # trailing-first and jams into a visible line. So the cut is turned a little every re-rank (a cyclic shift of
        # the angle rank), which smears any such edge away.
        self.cut = (self.cut + config.ORDER_CUT_STEP) % (2 * math.pi)
        ahead = self.angle_rank if self.orbit < 0 else nb - 1 - self.angle_rank     # lower = further ahead
        ahead = (ahead + int(self.cut / (2 * math.pi) * nb)) % nb
        # the sum of two ranks already orders the cells; its 2 x 4096 levels fit the bucket sort as they are
        self._set_buckets((ahead if self.phi_rank is None else self.phi_rank + ahead).astype(np.uint16))

    def _set_buckets(self, bucket):
        self.bucket_base = bucket
        self.bucket = bucket.copy()
        self.order_starred = True                        # the stars' ranks go on top again

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
        if self.stars or self.order_starred:
            self._order_stars()
        if self.tick_count % config.SG_EVERY == 0 and (self.sg_on or self.stars):
            # without self-gravity, still kept for the stars: they feel the matter they pull
            changed = self.sg.update(self.mass, self.sg_g * self.g_scale, self.owner)
            self.sg_tick = self.tick_count
            if self.sg_on:
                kernels.wake_blocks(changed, self.sg.block, self.sg.cw, self.w, self.h, self.mass, self.flag)
        elif not self.sg_on and not self.stars and self.sg.gx.any():
            self.sg.reset()
        self._star_field()
        t1 = time.perf_counter()
        self.tick_count += 1
        self.stats[:] = 0
        params, whirls = self.params(), self.whirls()
        if self.blasts:
            self._step_blasts()
        if self.orbit:
            self._carry_blobs()
        elif self.blob_v.shape[0] > 1:                  # the orbit was turned off: no blobs
            self.blob[:] = 0
            self.blob_v = np.zeros((1, 3))
        ran = self._step_strips(params, whirls) if self.cores else None
        if ran is None:
            ran = kernels.step(self.w, self.h, self.tick_count, params, self.mass, self.kin, self.quad, self.shade,
                               self.stamp, self.flag, self.cur, self.order, self.bucket_counts, self.bucket, self.fx,
                               self.fy, self.sg.gx, self.sg.gy, self.sg.block, self.sg.cw, self.hole, self.absorbed,
                               self.solid, self.gvx, self.gvy, whirls, self.star_pulls, self.sfx, self.sfy,
                               config.STAR_FIELD_BLOCK, self.scw, self.sch, self.owner, self.star_v, self.star_f,
                               self.stats, self.blob, self.blob_v, self.heat_rows)
            heat = [self.heat_rows[:self.stats[kernels.S_HEAT]]]
        else:
            tl = self.strips
            heat = [tl["heat"][t, :c] for t, c in enumerate(tl["stats"][:, kernels.S_HEAT]) if c]
        self.n_awake = ran
        self.heat_made = self.fused = 0
        if self.radiation_on:
            if self.stars:
                heat.append(self._fuse())
            self._emit_heat(heat)
        if self.ghost_m.size:
            self._step_ghosts(params, whirls)
            self._cool_blasts()
            if self.radiation_on:
                kernels.heat_push(self.ghost_x, self.ghost_y, self.ghost_vx, self.ghost_vy, self.ghost_m,
                                  self.ghost_tag, config.HEAT_COUPLING, config.HEAT_MIN_SPEED, config.VMAX, self.w,
                                  self.h, self.mass, self.kin, self.owner, self.flag)
        # what a star's pull on its own particles adds up to is taken back from them next tick
        for st, (fx, fy, m) in zip(self.stars, self.star_f):
            st.fix = (-fx / m, -fy / m) if m > 0 else (0.0, 0.0)
        self._collect_absorbed()
        if self.collapse_on and self.tick_count % config.COLLAPSE_EVERY == 0 and self.tick_count >= self.calm_until:
            self.check_collapse()
        self.step_stars()
        if self.star_form_on and self.tick_count % config.STAR_FORM_EVERY == 0:
            self.form_stars()
        self.step_wells()
        self.step_spawners()
        if self.ghost_stars:
            self._step_ghost_stars()
        t2 = time.perf_counter()
        self.gravity_ms = (t1 - t0) * 1000
        self.step_ms = (t2 - t1) * 1000

    def _carry_blobs(self):
        """With the global orbit on, carry packed blobs of matter round with it as a whole (kernels.carry_blobs), as
        stars carry themselves: a clump moved a particle at a time can't keep up, since its own gravity pulls its
        particles into the gaps the first ones leave. A blob is at least BLOB_MIN touching particles that belong to
        no star, not spread out over more than BLOB_MAX_RADIUS, and not inside a super well's range (its whirlpool
        rules there); it moves at the orbit's velocity at its centre of mass - a whole cell at a time, at random
        with the right odds for the fraction - and its particles only move relative to it (kernels.step)."""
        occupied = kernels.occupied_par(self.mass, 64) if self.cores else np.flatnonzero(self.mass)
        rows = kernels.find_blobs(occupied, self.mass, self.owner, self.w, self.h, self.wrap,
                                  self.blob, *self.blob_scratch)
        n = rows.shape[0]
        v = np.zeros((n + 1, 3))
        if n:
            cells, _, cx, cy, spread = rows.T
            rx, ry = cx - self.w / 2, cy - self.h / 2
            r2 = rx * rx + ry * ry
            om = self.orbit * self.orbit_speed
            k = np.sqrt(om * om * r2 + config.ORBIT_MIN_SPEED ** 2) / np.sqrt(np.maximum(r2, 0.25)) * np.sign(om)
            carry = (cells >= config.BLOB_MIN) & (spread <= config.BLOB_MAX_RADIUS) & (r2 >= 0.25)
            for wl in self.wells:
                if wl.is_super:
                    dx, dy = cx - wl.x, cy - wl.y
                    if self.wrap:
                        dx -= self.w * np.floor(dx / self.w + 0.5)
                        dy -= self.h * np.floor(dy / self.h + 0.5)
                    carry &= dx * dx + dy * dy > self.well_range(wl) ** 2
            v[1:, 0] = np.where(carry, -ry * k, 0.0)
            v[1:, 1] = np.where(carry, rx * k, 0.0)
            v[1:, 2] = carry
            moves = np.zeros((n + 1, 2), np.int64)
            moves[1:] = np.floor(v[1:, :2] + self.rng.random((n, 2))) * carry[:, None]
            kernels.carry_blobs(occupied, self.blob, moves, config.RESTITUTION, config.WALL_E, self.w, self.h,
                                self.mass, self.kin, self.quad, self.shade, self.stamp, self.flag, self.solid,
                                self.hole, self.absorbed, self.wrap)
        self.blob_v = v

    def _step_strips(self, params, whirls):
        """The particles' tick on all cores (kernels.step_tiles), in strips. With global gravity pulling up, down or
        diagonally (and no global orbit) they are strips of columns, so a falling stream stays inside its strip -
        at least 64 cells wide, so strips running side by side don't share cache lines; otherwise strips of rows,
        which keep each strip's memory in one piece (and a sideways stream inside it). They start somewhere new every
        tick, so no edge stays put long enough to show. Returns how many particles ran, or None when the universe is
        too small to cut in two."""
        size = max(config.STRIP_SIZE, 2 * (config.MAX_STEPS + 2))
        if self.gdir is not None and self.gdir not in (2, 6) and not self.orbit:
            nx, ny = self.w // max(size, 64) // 2 * 2, 1
        else:
            nx, ny = 1, self.h // size // 2 * 2
        if nx * ny < 2:
            self.strips = None
            return None
        nt = nx * ny
        tl = self.strips
        if tl is None or tl["shape"] != (nx, ny):
            tl = self.strips = {"shape": (nx, ny), "counts": np.zeros(nt, np.int64),
                               "stats": np.zeros((nt, 16), np.int64),   # rows a cache line apart (or more)
                               "heat": np.zeros((nt, HEAT_ROWS, 5))}
        absorbed = np.zeros((nt, self.absorbed.size), np.int64)
        star_f = np.zeros((nt,) + self.star_f.shape)
        cut_x, cut_y = int(self.rng.integers(self.w)), int(self.rng.integers(self.h))
        chunk = numba.set_parallel_chunksize(1)
        ran = kernels.step_tiles(self.w, self.h, self.tick_count, params, nx, ny, cut_x, cut_y, self.mass, self.kin,
                                 self.quad, self.shade, self.stamp, self.flag, self.cur, self.order, self.bucket,
                                 self.fx, self.fy, self.sg.gx, self.sg.gy, self.sg.block, self.sg.cw,
                                 self.hole, absorbed, self.solid, self.gvx, self.gvy, whirls, self.star_pulls,
                                 self.sfx, self.sfy, config.STAR_FIELD_BLOCK, self.scw, self.sch, self.owner,
                                 self.star_v, star_f, tl["stats"], tl["counts"], self.blob, self.blob_v,
                                 tl["heat"])
        numba.set_parallel_chunksize(chunk)
        self.stats += tl["stats"][:, :kernels.N_STATS].sum(axis=0)
        self.absorbed += absorbed.sum(axis=0)
        self.star_f += star_f.sum(axis=0)
        return int(ran)

    def render(self, mode=0):
        (kernels.render_par if self.cores else kernels.render)(mode, self.mass, self.kin, self.quad, self.shade,
                                                               self.flag, self.mass_lut, self.heat_lut,
                                                               self.shade_mul, self.bg, config.VMAX,
                                                               self.rgb.reshape(-1, 3))
        if self.rim is not None:                         # past a round universe's edge
            kernels.paint(self.rim, self.outside, self.rgb.reshape(-1, 3))
        if self.ghost_m.size:
            kernels.render_ghosts(self.ghost_x, self.ghost_y, self.ghost_m, self.ghost_tag, self.w, self.h,
                                  self.mass_lut, self.ghost_tint, self.heat_color, self.rgb.reshape(-1, 3))
        for gs in self.ghost_stars:
            gx, gy = gs.x + gs.dx, gs.y + gs.dy
            if self.wrap:
                gx, gy = gx % self.w, gy % self.h
            kernels.render_ghosts(gx, gy, gs.masses, np.zeros(gs.masses.size, np.int64), self.w, self.h,
                                  self.mass_lut, self.ghost_tint, self.heat_color, self.rgb.reshape(-1, 3))
        return self.rgb

    # --- ghosts -----------------------------------------------------------------------------------

    def _clear_ghosts(self):
        """Ghosts: particles off the grid (positions in cells) that feel gravity but collide with nothing; and ghost
        stars (GhostStar)."""
        self.ghost_stars = []
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
        super wells swallow those that reach a core, and land the ones GHOST_TICKS old as ordinary particles where
        they are (see kernels.land_ghosts)."""
        g = (self.ghost_x, self.ghost_y, self.ghost_vx, self.ghost_vy, self.ghost_m, self.ghost_age)
        step = self.ghost_way or kernels.step_ghosts
        self.stats[kernels.S_ABSORBED] += step(*g, self.w, self.h, params, self.fx, self.fy, self.sg.gx, self.sg.gy,
                                               self.sg.block, self.sg.cw, self.hole, self.absorbed, whirls,
                                               self.star_pulls, self.sfx, self.sfy, config.STAR_FIELD_BLOCK, self.scw,
                                               self.sch)
        kernels.land_ghosts(*g, config.GHOST_TICKS, config.GHOST_LAND_NEAR, config.GHOST_LAND_PATIENCE,
                            max(self.w, self.h), config.MAX_MASS, self.w, self.h, self.mass, self.kin, self.quad,
                            self.shade, self.stamp, self.flag, self.solid, self.hole, self.wrap)
        keep = self.ghost_m > 0
        if not keep.all():
            for name in ("ghost_x", "ghost_y", "ghost_vx", "ghost_vy", "ghost_m", "ghost_age", "ghost_tag"):
                setattr(self, name, getattr(self, name)[keep])

    def _fuse(self):
        """Fusion in every star (kernels.star_fuse). Returns the heat it shed, as rows like kernels._shed's."""
        rows = np.array([(st.x, st.y, st.radius + 1.0, k) for k, st in enumerate(self.stars)], np.float64)
        count = np.zeros(kernels.N_STATS, np.int64)
        self.fused = kernels.star_fuse(rows, config.FUSION_CHANCE, config.FUSION_LIGHT, config.FUSION_HEAT_SHARE,
                                       config.MAX_MASS, self.w, self.h, self.mass, self.kin, self.quad, self.owner,
                                       self.flag, self.fuse_rows, count, self.wrap)
        return self.fuse_rows[:count[kernels.S_HEAT]]

    def _emit_heat(self, parts):
        """Send out the heat shed this tick (rows of x, y, vx, vy, mass; see kernels._shed): each as up to HEAT_PIECES
        light heat particles - ghosts tagged kernels.HEAT_TAG, sharing its mass - flying off HEAT_SPEED faster than
        it was moving, in random directions, landing HEAT_TICKS later (kernels.heat_push: on the way they blow light
        matter away)."""
        rows = np.concatenate(parts) if parts else np.zeros((0, 5))
        if not rows.size:
            return
        loss = rows[:, 4].astype(np.int64)
        n = np.minimum(loss, config.HEAT_PIECES)
        src = np.repeat(np.arange(rows.shape[0]), n)
        nth = np.arange(src.size) - np.repeat(np.cumsum(n) - n, n)          # which piece of its event each is
        masses = loss[src] // n[src] + (nth < loss[src] % n[src])
        a = self.rng.uniform(0.0, 2 * math.pi, src.size)
        r = rows[src]
        self.add_ghosts(r[:, 0], r[:, 1], masses, r[:, 2] + config.HEAT_SPEED * np.cos(a),
                        r[:, 3] + config.HEAT_SPEED * np.sin(a), tag=kernels.HEAT_TAG,
                        age=config.GHOST_TICKS - config.HEAT_TICKS)
        self.heat_made = int(src.size)

    def heat_count(self):
        """Heat particles in flight."""
        return int(np.count_nonzero(self.ghost_tag == kernels.HEAT_TAG))

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
        self.stars.clear()                               # they are made of particles
        if self.held is not None and not isinstance(self.held, (Well, Spawner)):
            self.held = None
        self.owner[:] = 0
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
        self.scatter = config.COLLISION_SCATTER   # radians: how far off head-on loose particles bounce
        self.radiation_on = config.RADIATION_ON
        self.orbit = config.ORBIT
        self.orbit_speed = self.orbit_speed_for(config.ORBIT_EDGE_SPEED)
        self.g_scale = config.GRAVITY_SCALE
        self.explode_mass = config.SUPER_EXPLODE_MASS
        if self.reach_len != config.GRAVITY_REACH:
            self.set_reach(config.GRAVITY_REACH)
        if self.wrap != config.WRAP:
            self.set_wrap(config.WRAP)
        self.field_dirty = True

    def set_cell(self, cell):
        self.resize(self.pw, self.ph, cell)

    def universe_px(self):
        """The universe's size (px at zoom 1): the window's, or when round a square round the disc that reaches
        ROUND_RADIUS x half the window's diagonal out (a whole, even number of cells across)."""
        if not self.round:
            return self.vpw, self.vph
        c = 2 * self.cell
        side = int(math.ceil(config.ROUND_RADIUS * math.hypot(self.vpw, self.vph) / c)) * c
        return side, side

    def set_round(self, on):
        """Make the universe round (a disc reaching past the window's corners, centred on it) or the window's
        rectangle again. A round one has no straight borders to wrap; the scene stays centred, and whatever lies
        outside the new shape is lost."""
        if on == self.round:
            return
        if on and self.wrap:
            self.set_wrap(False)
        self.round = on
        self.resize(self.vpw, self.vph, centred=True)

    def resize(self, pw, ph, cell=None, centred=False):
        """Change the window's size (px) and/or the square size, resampling the scene so it keeps its shape (sand.py
        World.resize); the universe follows the window (universe_px). When the area changes, the scene stays pinned
        to the side global gravity points at, or centred when there is none, it is round or `centred`; wells move
        with it."""
        cell = cell or self.cell
        pw, ph = max(pw, 128), max(ph, 128)          # keeps the self-gravity mesh at least 2 blocks wide
        for gs in list(self.ghost_stars):            # stars still arriving land first, and are resampled with the rest
            self._land_ghost_star(gs)
        old_cell, ow, oh = self.cell, self.w, self.h
        old = (self.mass, self.kin, self.quad, self.shade)
        edge = self.orbit_edge_speed()
        self.vpw, self.vph = pw, ph
        pw, ph = self.universe_px()
        gx, gy = DIRS[self.gdir] if self.gdir is not None and not (self.round or centred) else (0, 0)
        offx = (pw - self.pw) * (gx + 1) // 2
        offy = (ph - self.ph) * (gy + 1) // 2
        self.pw, self.ph = pw, ph
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
        for st in self.stars:
            st.x = (st.x * old_cell + offx) / cell
            st.y = (st.y * old_cell + offy) / cell
            for name in ("vx", "vy", "radius", "ring", "size"):
                setattr(st, name, getattr(st, name) * old_cell / cell)
            st.target = None
            if self.wrap:
                st.x %= self.w
                st.y %= self.h
        for wl in self.wells:
            wl.x = (wl.x * old_cell + offx) / cell
            wl.y = (wl.y * old_cell + offy) / cell
            wl.radius *= old_cell / cell
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
        self._mark_rim()
        for b in self.wells + self.spawners:
            self._keep_inside(b)

    def _mark_rim(self, full=True):
        """A round universe's cells outside its circle are solid ground (like a solid well's body) moving with the
        global orbit, so matter flung out to the rim slides round it with everything else instead of stopping
        dead; any particle left out there is removed. full=False (after the wells' ground is rebuilt with no solid
        well about, so nothing else touched the rim) only marks it solid again, and its velocity if the orbit
        changed."""
        if self.rim is None:
            return
        i = self.rim
        np.maximum(self.solid, self.rim_mask, out=self.solid)
        om = self.orbit * self.orbit_speed
        if full or self.rim_v != om:
            vx = vy = np.zeros(i.size, np.float32)
            if om:
                ys, xs = np.divmod(i, self.w)
                rx, ry = xs - self.w / 2, ys - self.h / 2
                r = np.sqrt(rx * rx + ry * ry)
                k = np.sqrt(om * om * r * r + config.ORBIT_MIN_SPEED ** 2) / r * np.sign(om)
                vx, vy = (-ry * k).astype(np.float32), (rx * k).astype(np.float32)
            self.gvx[i], self.gvy[i] = vx, vy
            self.rim_v = om
        if not full:
            return
        out = i[self.mass[i] > 0]
        if out.size:
            self.mass[out] = 0
            self.kin[out] = 0.0
            self.quad[out] = 0
            self.owner[out] = 0

    def _keep_inside(self, b):
        """In a round universe, bring a well, spawner or ghost star that has strayed past the rim back inside it (a
        well's body just clear of it), stopping its motion outwards."""
        if self.rim is None:
            return
        dx, dy = b.x - self.w / 2, b.y - self.h / 2
        r = math.hypot(dx, dy)
        lim = max(1.0, min(self.w, self.h) / 2 - (b.body_radius() if isinstance(b, Well) else 0.0) - 1.0)
        if r <= lim:
            return
        b.x, b.y = self.w / 2 + dx * lim / r, self.h / 2 + dy * lim / r
        out = (b.vx * dx + b.vy * dy) / r
        if out > 0:
            b.vx -= out * dx / r
            b.vy -= out * dy / r

    # --- wells ------------------------------------------------------------------------------------

    def add_well(self, px, py, mass, radius=config.WELL_SOFTENING, sign=1, vx=0.0, vy=0.0):
        """A solid well (a repulsor if sign < 0) at a pixel position; radius is its size in cells."""
        x, y = px / self.cell, py / self.cell
        omega = float(self.rng.choice((-1, 1)) * self.rng.uniform(*config.STAR_SPIN))
        wl = Well(x, y, mass, radius, sign=sign, vx=vx, vy=vy, omega=omega, built=(x, y, mass))
        self.wells.append(wl)
        self.field_dirty = True
        return wl

    def brush_mass(self, radius_px, pour_mass, density=config.WELL_DENSITY):
        """Mass of a well (or star) the size of a brush circle: its area filled with pour_mass particles, `density`
        times over (a (min, max) pour range counts as its middle)."""
        r = max(1.0, radius_px / self.cell)
        m = sum(pour_mass) / 2 if isinstance(pour_mass, tuple) else pour_mass
        return math.pi * r * r * m * density

    def add_sized_well(self, px, py, radius_px, pour_mass=1, sign=1):
        """A well as heavy as brush_mass() for a radius_px circle, and as big as well_radius() makes that mass (the
        brush's size at pour mass 1)."""
        mass = self.brush_mass(radius_px, pour_mass)
        return self.add_well(px, py, mass, self.well_radius(mass), sign)

    def spawn_spin(self):
        """Which way a new super well spins: with the global orbit when it is on (1 clockwise, -1 counterclockwise),
        else either way at random."""
        return float(self.orbit) if self.orbit else float(self.rng.choice((-1, 1)))

    def add_super_well(self, px, py, mass=None):
        """A super well holding `mass` (default: the current collapse threshold), spinning SUPER_SPIN_PLACED fast
        the way spawn_spin() says."""
        mass = mass or self.collapse_threshold()
        x, y = px / self.cell, py / self.cell
        spin = self.spawn_spin() * config.SUPER_SPIN_PLACED
        wl = Well(x, y, mass, is_super=True, spin=spin, built=(x, y, mass), auto_spin=True)
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
        """The star, well or spawner whose circle covers a pixel (nearest centre wins), or None."""
        best, best_d = None, math.inf
        for b in self.stars + self.wells + self.spawners:
            d = math.hypot(b.x * self.cell - px, b.y * self.cell - py)
            reach = self.well_radius_px(b) if isinstance(b, Well) else b.radius * self.cell
            if d <= max(min_grab_px, reach) and d < best_d:
                best, best_d = b, d
        return best

    def nearest_body(self, px, py):
        """The nearest star, well or spawner to a pixel, or None."""
        bodies = self.stars + self.wells + self.spawners
        if not bodies:
            return None
        return min(bodies, key=lambda b: math.hypot(b.x * self.cell - px, b.y * self.cell - py))

    def move_body(self, b, px, py):
        """Drag a well or spawner to a pixel position (it stops there), or a star towards it (see _drag_star)."""
        if isinstance(b, Star):
            b.target = (px / self.cell, py / self.cell)
        elif isinstance(b, Well):
            self.move_well(b, px, py)
        else:
            b.x, b.y = px / self.cell, py / self.cell
            b.vx = b.vy = 0.0

    def remove_body(self, b):
        if isinstance(b, Star):
            self.remove_star(b)
        elif isinstance(b, Well):
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
        """The nearest well to a pixel; normal_only: the nearest star or solid well (no super wells)."""
        best, best_d = None, math.inf
        for wl in (self.stars + self.wells if normal_only else self.wells):
            if normal_only and getattr(wl, "is_super", False):
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
        """Make a star or well heavier or lighter by factor. A star or solid well takes the size a freshly placed one
        of its new mass has, and its body, pull and reach follow (a super well's core and range follow its mass)."""
        if isinstance(wl, Star):
            self.scale_star(wl, factor)
            return
        wl.mass *= factor
        if not wl.is_super:
            wl.radius = self.well_radius(wl.mass)
        self.field_dirty = True

    def scale_gravity(self, factor):
        """Make all gravity stronger or weaker; the collapse threshold moves the opposite way."""
        self.set_gravity_scale(self.g_scale * factor)

    def set_gravity_scale(self, scale):
        """Set the strength of all gravity (between 1/16 and 16)."""
        self.g_scale = min(16.0, max(1 / 16, scale))
        self.field_dirty = True

    def set_reach(self, cells):
        """How far gravity reaches (cells; 0: all the way): every pull fades beyond about this distance."""
        self.reach_len = max(0.0, float(cells))
        self.sg = SelfGravity(self.w, self.h, wrap=self.wrap, kinv=self.kinv)
        self.field_dirty = True

    def set_wrap(self, on):
        """Continuous borders on or off; turning them on makes a round universe the window's rectangle again."""
        if on and self.round:
            self.set_round(False)
        self.wrap = on
        self.sg = SelfGravity(self.w, self.h, wrap=on, kinv=self.kinv)
        self.field_dirty = True

    def set_orbit(self, direction):
        """Global orbit: 1 clockwise, -1 counterclockwise, 0 off."""
        self.orbit = direction
        self.order_dirty, self.order_tick = True, -10 ** 9   # re-rank for the new flow at once
        self._mark_rim()
        self.wake_all()

    def scale_orbit(self, factor):
        self.orbit_speed *= factor
        self._mark_rim()
        self.wake_all()

    def set_orbit_edge_speed(self, speed):
        """Turn the global orbit so the edge of the universe moves at `speed` cells/tick."""
        self.orbit_speed = self.orbit_speed_for(speed)
        self._mark_rim()
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

    def universe_mass(self):
        """All the matter there is: the particles, the ghosts (ghost stars too) and what super wells hold (it moves
        between them, but
        none is made or lost except by pouring, erasing and placing)."""
        return self.total_mass() + self.ghost_mass() + self.super_mass() + sum(gs.mass for gs in self.ghost_stars)

    def super_mass(self):
        """Mass held by super wells (swallowed particles and wells)."""
        return int(sum(wl.mass for wl in self.wells if wl.is_super))

    def star_mass(self):
        """Mass of the particles that belong to stars."""
        return int(sum(st.mass for st in self.stars))

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


def warmup(cores=False):
    """Compile (or load from the disk cache) every kernel on a tiny world so the first real frame doesn't stall.
    cores: also the ones World.accelerate uses."""
    if cores:
        w = World(80, 64, 1, seed=0)
        w.accelerate(cores=True)
        w.add_super_well(60, 40, 50)
        w.add_star(20, 20, 6, mass=3000)
        w.orbit = 1
        w.brush(40, 30, 12, 4)
        w.pour_ghosts(30, 50, 6, 2)
        for _ in range(3):
            w.step()
        w.render(0)
    w = World(32, 32, 1, seed=0)
    w.add_well(4, 4, 50.0, radius=2.0)
    w.add_super_well(24, 24, 50)
    w.add_star(10, 12, 4, mass=3000, vx=0.5)
    w.add_star(20, 12, 4, mass=3000, vx=-0.5)
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
    kernels.star_shock(10.0, 12.0, 4.0, 14.0, 12.0, 4.0, 0, 1, 1.0, w.w, w.h, w.mass, w.kin, w.owner, w.stamp,
                       w.flag, w.wrap)
    if w.stars:
        w.scale_star(w.stars[0], 1.25)
        w._explode_star(0, w.stars[0])
    for _ in range(3):                                   # the blast and its debris
        w.step()
    w.set_round(True)                                    # the rim
    w.step()
    for mode in range(len(VIEW_MODES)):
        w.render(mode)
