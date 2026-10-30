"""Tunable settings. Physics units are cells and ticks unless noted."""

# --- World / display ---------------------------------------------------------
WINDOW = (960, 720)                    # px; the world fills the window
CELL_SIZES = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16]
DEFAULT_CELL = 2                       # px per particle
FPS = 60
MAX_TICKS_PER_FRAME = 8

BG = (17, 19, 24)
FG = (200, 204, 212)
DIM = (110, 116, 128)
WELL_COLOR = (255, 170, 80)
REPULSOR_COLOR = (90, 200, 255)

# --- Particles ---------------------------------------------------------------
MAX_MASS = 4096                        # merges stop here
POUR_MASSES = (1, 4, 16, 64, 256)      # keys 1-5
POUR_CHANCE = 0.25                     # per cell per frame under the brush (sand.py)

# --- Motion ------------------------------------------------------------------
VMAX = 8.0                             # cells / tick
MAX_STEPS = 8                          # cell moves per tick
WALL_E = 0.3                           # restitution against the window edge
RESTITUTION = 0.2                      # restitution between particles
IMPACT_MIN = 0.15                      # slower contacts are resting contact: no momentum exchange, no waking
SLIDE_DAMP = 0.7                       # velocity kept after sliding off another particle (sand.py SLIDE_DAMP)
SINK_CHANCE = 0.35                     # heavier particles push down through lighter ones (sand.py SINK_CHANCE)
DRAG = 0.0                             # fraction of velocity lost per tick
SLEEP_EPS = 0.02                       # a blocked particle slower than this falls asleep

# --- Children (quadrant model of the original child universe) ----------------
CHILD_MOVES = 2                        # children moved between quadrants per children update
CHILD_EVERY = 4                        # ticks between a particle's children updates (staggered across particles)
SLOSH = 0.3                            # bias of children towards the side opposite the acceleration
LEAN_ON = False                        # children steer their parent (J); off by default because for light
LEAN = 0.002                           #   particles it is a random push comparable to weak gravity

# --- Merging / splitting -----------------------------------------------------
MERGE_ON = False
STICK_SPEED = 0.4                      # contacts slower than this may merge
MERGE_CHANCE = 0.01                    # per slow contact
SPLIT_ON = False
BIND = 0.6                             # impact energy per unit mass needed to break a particle
SPLIT_KICK = 0.3                       # separation speed of the parts, x impact speed

# --- Gravity -----------------------------------------------------------------
GLOBAL_G = 0.2                         # global gravity (arrow keys)
WELL_STRENGTH = 60.0                   # accel = strength * r / (r^2 + soft^2)^1.5
WELL_SOFTENING = 4.0
ORDER_BUCKETS = 16384                   # potential buckets for "leading particles first" ordering

SG_ON = False
SG_G = 0.002                           # self-gravity constant
SG_BLOCK = 4                           # cells per side of a self-gravity mesh block
SG_EVERY = 4                           # ticks between self-gravity field updates
SG_SOFTENING = 1.0                     # in mesh blocks
SG_WAKE = 0.002                        # field change that wakes sleeping particles in a block
