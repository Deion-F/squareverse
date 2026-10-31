"""Tunable settings. Physics units are cells and ticks unless noted."""

# --- World / display ---------------------------------------------------------
WINDOW = (960, 720)                    # px; the world fills the window
CELL_SIZES = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16]
DEFAULT_CELL = 2                       # px per particle
FPS = 60
MAX_TICKS_PER_FRAME = 8

# --- Starting state of the app ----------------------------------------------
DEFAULT_PRESET = "disk"                # rain, disk, cloud, binary or empty (--preset overrides)
TICKS_PER_FRAME = 1                    # + / -
BRUSH_PX = 24                          # brush circle radius (mouse wheel)
POUR_MASS = 1                          # a mass, or "random" for RANDOM_MASS (keys 1-6)
VIEW = "mass"                          # mass, speed, children or awake (V)
INSPECTOR_ON = True                    # I
HELP_ON = False                        # H

BG = (17, 19, 24)
FG = (200, 204, 212)
DIM = (110, 116, 128)
WELL_COLOR = (255, 170, 80)
REPULSOR_COLOR = (90, 200, 255)
PLANET_COLOR = (58, 50, 66)
SPAWNER_COLOR = (120, 220, 150)
SUPER_RIM_COLOR = (120, 110, 150)
SUPER_RANGE_COLOR = (150, 140, 190)
SUPER_SPIN_COLOR = (200, 175, 255)
CRATER_COLOR = (40, 34, 48)

# --- Particles ---------------------------------------------------------------
MAX_MASS = 4096                        # merges stop here
POUR_MASSES = (1, 4, 16, 64, 256)      # keys 1-5
RANDOM_MASS = (1, 256)                 # key 6: each poured particle gets a uniform random mass in this range
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
SLEEP_ACCEL = 1e-4                     # a free one only when (nearly) no force acts on it either

# --- Children (quadrant model of the original child universe) ----------------
CHILD_MOVES = 2                        # children moved between quadrants per children update
CHILD_EVERY = 4                        # ticks between a particle's children updates (staggered across particles)
SLOSH = 0.3                            # bias of children towards the side opposite the acceleration
LEAN_ON = False                        # children steer their parent (J); off by default because for light
LEAN = 0.002                           #   particles it is a random push comparable to weak gravity

# --- Merging / splitting -----------------------------------------------------
MERGE_ON = True
STICK_SPEED = 0.4                      # contacts slower than this may merge
MERGE_CHANCE = 0.01                    # per slow contact
SPLIT_ON = True
BIND = 0.6                             # impact energy per unit mass needed to break a particle
SPLIT_KICK = 0.3                       # separation speed of the parts, x impact speed

# --- Gravity -----------------------------------------------------------------
G_SCALE_STEP = 1.25                    # < / > multiply or divide all gravity by this
GLOBAL_G = 0.2                         # global gravity (arrow keys), at gravity scale 1
GRAVITY_DIR = None                     # starting global gravity: None or down, down-left, left, ... (arrows, Q/E, 0)
GRAVITY_SCALE = 1.0                    # starting strength of all gravity (< / >)
G = 0.002                              # gravitational constant: particles, wells and super wells all pull with
                                       #   accel = G * mass * r / (r^2 + soft^2)^1.5
WELL_DENSITY = 64.0                    # a brush-sized well weighs its circle's area x pour mass x this
WELL_SOFTENING = 4.0                   # preset wells' size (cells)
WELL_INERTIA_MASS = 20000.0            # wells accelerate (and top out) at VMAX x this / (this + their mass)
PLANET_SPIN = (0.005, 0.02)            # a new planet spins at a random speed in this range (rad/tick), either way;
                                       #   its surface carries resting particles round with it
PLANET_RESTITUTION = 0.8               # how much two colliding planets bounce back (0 = stick, 1 = perfect)
PLANET_REST_SPEED = 0.02               # slower contacts are resting: held apart, no bounce, no debris
PLANET_EJECT = 0.10                    # most debris a collision sheds, as a share of the pair's combined mass,
PLANET_EJECT_SPEED = 1.0               #   reached at this impact speed (slower hits shed proportionally less)
PLANET_LOSS_BIAS = 1.0                 # who loses it: each planet's share ~ its mass ^ -bias (1 = the smaller more)
PLANET_DEBRIS_SPEED = 0.5              # debris flies out at 0.9 x impact speed + this (cells/tick)
WELL_REBUILD_MOVE = 0.5                # cells a well moves before the field is recomputed
FIELD_BLOCK = 4                        # wells' pull is summed every this many cells and blended in between...
FIELD_NEAR = 16.0                      # ...except within this many cells (or 3 softening lengths) of a well: exact
ORDER_EVERY = 30                       # ticks between re-ranking after wells move (it only affects efficiency)
ORDER_BUCKETS = 16384                   # potential buckets for "leading particles first" ordering

SG_ON = False
SG_BLOCK = 4                           # cells per side of a self-gravity mesh block
SG_EVERY = 4                           # ticks between self-gravity field updates
SG_SOFTENING = 1.0                     # in mesh blocks
SG_WAKE = 0.002                        # field change that wakes sleeping particles in a block

SPAWNER_RATE = 0.005                   # particles per tick per cell of a spawner's circle (24 px brush: ~2/tick)
WRAP = False                           # continuous borders (W): leaving one side enters from the opposite one
ORBIT = 0                              # starting global orbit: 0 off, 1 clockwise, -1 counterclockwise (O)
ORBIT_SPEED = 0.005                    # global orbit angular speed (rad/tick): 1.5 cells/tick 300 cells out
ORBIT_MIN_SPEED = 0.5                  # it turns things at least this fast (cells/tick), even at the centre
ORBIT_GRIP = 0.02                      # how quickly things are brought up to the orbiting speed (per tick)
ORBIT_STEP = 1.25                      # K / L multiply or divide the orbit speed by this

# --- Super wells (collapse) --------------------------------------------------
COLLAPSE_ON = True                     # shift+B
COLLAPSE_MASS = 40000                  # mass in a COLLAPSE_BLOCKS x COLLAPSE_BLOCKS block window that collapses,
COLLAPSE_BLOCKS = 5                    #   divided by the gravity scale (blocks are SG_BLOCK cells: 20 x 20 cells)
COLLAPSE_EVERY = 8                     # ticks between collapse checks
SUPER_RANGE_ACCEL = 0.01               # a well's reach: where its pull drops below this
SUPER_RANGE_FACTOR = 0.25              # a super well's range (the dotted circle) is this x its reach: it spins
                                       #   space round within it, and overlapping ranges merge. Its pull goes on
SUPER_SOFTENING = 0.25                 # its pull is softened over this share of its range, so infalling particles
                                       #   keep their sideways motion (under VMAX) and can miss the core or orbit
SUPER_CORE = 1.5                       # absorbing core radius (cells) = SUPER_CORE + SUPER_CORE_GROWTH * sqrt(mass)
SUPER_CORE_GROWTH = 0.004
SUPER_SWIRL_SPEED = 6.0                # a spinning super well whirls everything inside its range: sideways speed
SUPER_SWIRL_GRIP = 0.25                #   is driven towards spin x this x closeness (0 at the edge, 1 at the
                                       #   centre), gripped this x closeness^2 hard (per tick): gentle on entering,
                                       #   almost impossible to resist beside the core (0 speed = straight in)
SUPER_SWIRL_INFALL = 0.98              # ...but never faster than this share of the speed that would hold it in
                                       #   orbit there, so whirling matter still spirals in
SUPER_SPIN_J = 5.0                     # spin of a new super well = the collapsing matter's angular momentum per
SUPER_SPIN_MIN = 0.25                  #   unit mass / this, between this minimum and 1, in the way it was turning
SUPER_SPIN_VISUAL = 0.12               # how fast its spiral arms turn at full spin (rad/tick)
SUPER_MERGE_RATE = 0.08                # super wells whose ranges overlap close this share of their gap per tick,
SUPER_MERGE_MIN_SPEED = 1.0            #   at least this fast (cells/tick), until their cores touch and they merge
MERGE_EJECT = (0.01, 0.10)             # share of the combined mass a super well merger spits out as particles
MERGE_LOSS_BIAS = 1.0                  # who loses that mass: each well's share ~ its mass ^ -bias. 1 = inversely
                                       #   to size (a well merging with one half its size loses half as much as
                                       #   it); 0 = equal shares; -1 = in proportion to size
COLLAPSE_EJECT = (0.10, 0.30)          # share of the collapsed mass a new super well spits out
EJECT_MASS = (1, 256)                  # masses of the ejected particles (uniform)
EJECT_ESCAPE = 1.2                     # ejected particles leave at this x the speed needed to escape the range
