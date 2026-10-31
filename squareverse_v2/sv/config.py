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
REPULSOR_COLOR = (90, 200, 255)
STAR_COLORS = ((255, 95, 45), (255, 180, 60), (255, 236, 170), (160, 195, 255))   # light -> very heavy stars
STAR_GLOW = 0.55                       # brightness of a star's corona at its surface...
STAR_GLOW_SIZE = 2.2                   # ...fading out at this x its radius
SPAWNER_COLOR = (120, 220, 150)
SUPER_RIM_COLOR = (120, 110, 150)
SUPER_RANGE_COLOR = (150, 140, 190)
SUPER_SPIN_COLOR = (200, 175, 255)
GHOST_TINT = (190, 215, 255)           # ghosts are drawn see-through, washed towards this
DISSOLVE_COLOR = (255, 140, 220)       # the wave front eating a star that touched a super well

# --- Particles ---------------------------------------------------------------
MAX_MASS = 4096                        # merges stop here
POUR_MASSES = (1, 4, 16, 64, 256)      # keys 1-5
RANDOM_MASS = (1, 256)                 # key 6: each poured particle gets a uniform random mass in this range
POUR_CHANCE = 0.25                     # per cell per frame under the brush (sand.py)
GHOST_TICKS = 180                      # shift+click pours ghosts: they feel gravity (not each other's) but collide
                                       #   with nothing for this many ticks, then land as ordinary particles in
                                       #   the nearest free cells

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
MERGE_SPEED = 1.0                      # only collisions at least this fast (closing speed, cells/tick) may merge
MERGE_CHANCE = 0.05                    #   the two, with this chance per collision
SPLIT_ON = True
SPLIT_SPEED = 2.0                      # only collisions at least this fast may break the particle that is hit...
BIND = 0.6                             # ...and only with this much impact energy per unit of its mass
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
WELL_INERTIA_MASS = 20000.0            # super wells accelerate (and top out at VMAX) x this / (this + their mass);
                                       #   so do stars in the global orbit and whirlpools (gravity moves them freely)
STAR_SPIN = (0.005, 0.02)              # a new star spins at a random speed in this range (rad/tick), either way;
                                       #   its surface carries resting particles round with it
STAR_RESTITUTION = 1.0                # how much two colliding stars bounce back (0 = stick, 1 = perfect)
STAR_REST_SPEED = 0.02                 # slower contacts are resting: held apart, no bounce, no debris
STAR_EJECT = 0.10                      # most debris a collision sheds, as a share of the pair's combined mass,
STAR_EJECT_SPEED = 1.0                 #   reached at this impact speed (slower hits shed proportionally less)
STAR_LOSS_BIAS = 1.0                   # who loses it: each star's share ~ its mass ^ -bias (1 = the smaller more)
STAR_DEBRIS_SPEED = 0.5                # debris flies out at 0.9 x impact speed + this (cells/tick)
STAR_SHATTER_RADIUS = 10.0             # a star smaller than this (cells) shatters into particles of random masses
STAR_SHATTER_SPEED = 0.6               #   when it hits another, flying apart at up to this + half the impact speed
STAR_DISSOLVE_SPEED = 1.5              # a star touching a super well's core dissolves into particles in a wave
STAR_DISSOLVE_KICK = 0.4               #   from the point of contact, moving this many cells/tick; the particles
                                       #   are kicked this fast away from that point
STAR_FORM_ON = True                    # a round clump layered heavy core / lighter mantle / lightest crust becomes a
STAR_FORM_EVERY = 30                   #   star holding its mass (checked every this many ticks). A clump is
STAR_FORM_RADIUS = (4.0, 30.0)         #   touching particles with space round them, between these sizes (radius
                                       #   in cells of a disc of the same area: about 50 to 2,800 particles),
STAR_FORM_ROUND = 1.5                  #   at most this elongated (long / short axis),
STAR_FORM_FILL = 0.8                   #   filling at least this share of the disc of the same area (not ragged),
STAR_FORM_LAYER_RATIO = 2.0            #   each layer's typical mass at least this x the next one out's,
STAR_FORM_PURITY = 0.75                #   with at least this share of each layer's particles in its own mass band
STAR_FORM_MIN_LAYER = 3                #   and at least this many particles in each layer
WELL_REBUILD_MOVE = 0.5                # cells a well moves before the field is recomputed
FIELD_BLOCK = 4                        # wells' pull is summed every this many cells and blended in between...
FIELD_NEAR = 16.0                      # ...except within this many cells (or 3 softening lengths) of a well: exact
ORDER_EVERY = 30                       # ticks between re-ranking after wells move (it only affects efficiency)
ORDER_CUT_EVERY = 120                  # ticks between turning the orbit ordering's cut (it shows as a line otherwise)
ORDER_CUT_STEP = 0.9                   # radians the cut turns each time
ORDER_BUCKETS = 16384                   # potential buckets for "leading particles first" ordering

SG_ON = False
SG_BLOCK = 4                           # cells per side of a self-gravity mesh block
SG_EVERY = 4                           # ticks between self-gravity field updates
SG_SOFTENING = 1.0                     # in mesh blocks
SG_WAKE = 0.002                        # field change that wakes sleeping particles in a block

SPAWNER_GHOSTS = True                  # spawners pour ghost particles (they land as ordinary ones GHOST_TICKS on)
SPAWNER_RATE = 0.005                   # particles per tick per cell of a spawner's circle (24 px brush: ~2/tick)
WRAP = False                           # continuous borders (W): leaving one side enters from the opposite one
ORBIT = 0                              # starting global orbit: 0 off, 1 clockwise, -1 counterclockwise (O)
ORBIT_EDGE_SPEED = 3.0                 # starting global orbit speed: cells/tick at the edge of the universe (half the
                                       #   shorter side out); it turns at the same angular speed throughout
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
SUPER_CORE = 0.75                      # absorbing core radius (cells) = SUPER_CORE + SUPER_CORE_GROWTH * sqrt(mass)
SUPER_CORE_GROWTH = 0.002
SUPER_SWIRL_SPEED = 20.0               # a spinning super well whirls everything inside its range: sideways speed
SUPER_SWIRL_GRIP = 0.25                #   is driven towards spin x this, gripped this hard (per tick), all the way
SUPER_SWIRL_EDGE = 0.15                #   out, fading in only over this outer share of the range. Inside, nothing
                                       #   sleeps or rests on friction: it moves unless matter blocks the way
SUPER_SWIRL_INFALL = 0.98              # ...but never faster than this share of the speed that would hold it in
                                       #   orbit there (x its spin above 1), so whirling matter still spirals in;
                                       #   a well spun up past 1 flings matter out into a ring instead
SUPER_SPIN_NATURAL = 5.0               # spin of a super well formed by collapse, the way the matter was turning
SUPER_SPIN_MAX = 7.0                   # ; / ' spin the nearest super well down / up by SUPER_SPIN_STEP, up to this
SUPER_SPIN_PLACED = 5.0                # spin of a super well placed with B (either way)
SUPER_SPIN_STEP = 1.25
SUPER_SPIN_VISUAL = 0.4                # how fast its spiral arms turn at spin 1 (rad/tick)...
SUPER_SPIN_VISUAL_MAX = 0.8            # ...and at most (faster would look like turning backwards)
SUPER_MERGE_ACCEL = 0.0025             # super wells whose ranges overlap are drawn together, closing faster by this x
                                       #   (sum of their ranges / their distance) cells/tick every tick, so the pull
                                       #   grows as they near (a few seconds from first overlap to merging) ...
SUPER_MERGE_MAX_SPEED = 3.0            #   ... up to this closing speed (cells/tick), until their cores touch and merge
SUPER_MERGE_SPIRAL = 0.03              #   their sideways motion round each other fades by this share per tick
MERGE_EJECT = (0.01, 0.10)             # share of the combined mass a super well merger spits out as particles
MERGE_LOSS_BIAS = 1.0                  # who loses that mass: each well's share ~ its mass ^ -bias. 1 = inversely
                                       #   to size (a well merging with one half its size loses half as much as
                                       #   it); 0 = equal shares; -1 = in proportion to size
COLLAPSE_EJECT = (0.10, 0.30)          # share of the collapsed mass a new super well spits out
EJECT_MASS = (1, 256)                  # masses of the ejected particles (uniform)
EJECT_ESCAPE = 1.2                     # ejected particles leave at this x the speed needed to escape the range
SUPER_EXPLODE_MASS = 5_000_000         # a super well this heavy explodes like a supernova: all its mass leaves its spot
                                       #   as a ring of very heavy debris (ghosts) ...
SUPER_BLAST_HOT_MASS = 3300            #   ... each piece about this heavy at first (random, never over MAX_MASS) ...
SUPER_BLAST_COOL_FROM = 20             #   ... which from this age (ticks), then every SUPER_BLAST_COOL_EVERY, breaks
SUPER_BLAST_COOL_EVERY = 20            #   in two ("cools") until the pieces are no heavier than...
SUPER_BLAST_COOL_TO = 400              #   ... this
SUPER_BLAST_RADIUS = 150.0             # the ring and the shock front slow to a halt this far out (cells; at most 45% of
                                       #   the shorter side) ...
SUPER_BLAST_SPEED = 6.0                #   ... starting at this speed (cells/tick), slowing like a blast wave
SUPER_BLAST_PUSH = 60.0                # the front shoves every particle it passes outwards, those nearby this far
                                       #   (cells), less and less the further out, nothing at the edge
SUPER_BLAST_DRAG = 0.1                 #   behind the front, outward motion fades by this much per tick (so a shoved
                                       #   particle coasts about 1 / this x its speed, not for ever)
SUPER_BLAST_SETTLE = 40                #   and keeps fading for this many ticks after the front has stopped
SUPER_EXPLODE_CALM = 180               # ticks after an explosion before anything can collapse again
