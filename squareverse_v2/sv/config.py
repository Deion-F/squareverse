"""Tunable settings. Physics units are cells and ticks unless noted."""

# --- World / display ---------------------------------------------------------
WINDOW = (960, 720)                    # px; the world fills the window
CELL_SIZES = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16]
DEFAULT_CELL = 2                       # px per particle
FPS = 60
MAX_TICKS_PER_FRAME = 8

# --- Acceleration (main.py --cpu turns it all off) ----------------------------
STRIP_SIZE = 20                        # cells: on all cores the particles run in strips at least this thick, and
                                       #   at least 2 x (MAX_STEPS + 2) so two running together never meet; thinner
                                       #   strips share clumps of matter out more evenly

# --- Starting state of the app ----------------------------------------------
DEFAULT_PRESET = "disk"                # rain, disk, cloud, binary or empty (--preset overrides)
DISK_MASS = 20_000_000                 # the disk preset's total mass, in particles of every mass from 1 up
DISK_FILL = 0.6                        # ...filling this share of its ring's cells
TICKS_PER_FRAME = 1                    # + / -
BRUSH_PX = 40                          # brush circle radius (mouse wheel), in px at zoom 1
POUR_MASS = 4                          # a mass, or "random" for RANDOM_MASS (keys 1-6)
VIEW = "mass"                          # mass, speed, children or awake (V)
INSPECTOR_ON = True                    # I
HELP_ON = False                        # H

BG = (17, 19, 24)
FG = (200, 204, 212)
DIM = (110, 116, 128)
REPULSOR_COLOR = (90, 200, 255)
STAR_COLORS = ((255, 95, 45), (255, 180, 60), (255, 236, 170), (160, 195, 255))   # light -> very heavy stars
STAR_COLOR_MASS = (3.0, 6.0)           # log10 of the star masses at the two ends of STAR_COLORS
STAR_RING_FADE = 0.3                   # a star's capture ring is drawn this bright over the background
STAR_GLOW = 0.55                       # brightness of a solid well's corona at its surface...
STAR_GLOW_SIZE = 2.2                   # ...fading out at this x its radius
SPAWNER_COLOR = (120, 220, 150)
SUPER_RIM_COLOR = (120, 110, 150)
SUPER_RANGE_COLOR = (150, 140, 190)
SUPER_SPIN_COLOR = (200, 175, 255)
GHOST_TINT = (190, 215, 255)           # ghosts are drawn see-through, washed towards this

# --- Particles ---------------------------------------------------------------
MAX_MASS = 4096                        # merges stop here
POUR_MASSES = (1, 4, 16, 64, 256)      # keys 1-5
RANDOM_MASS = (1, 256)                 # key 6: each poured particle gets a uniform random mass in this range
POUR_CHANCE = 0.25                     # per cell per frame under the brush (sand.py)
GHOST_TICKS = 180                      # shift+click pours ghosts: they feel gravity (not each other's) but collide
                                       #   with nothing for this many ticks, then land as ordinary particles in
                                       #   the nearest free cells
GHOST_LAND_NEAR = 3                    # ...within this many cells; with none that close it merges into the lightest
                                       #   particle there with room, or else stays a ghost and tries again, and only
GHOST_LAND_PATIENCE = 600              #   after this many ticks of that may it land in a free cell further away

# --- Motion ------------------------------------------------------------------
VMAX = 8.0                             # cells / tick
MAX_STEPS = 8                          # cell moves per tick
WALL_E = 0.3                           # restitution against the window edge
RESTITUTION = 0.2                      # restitution between particles
COLLISION_SCATTER = 0.3                # radians: loose particles bounce off at up to this angle from head-on
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

# --- Radiation (heat) ------------------------------------------------------------------------------------
RADIATION_ON = True                    # merging, splitting and fusion in stars give off heat
HEAT_SHARE = 0.01                      # a merge or split loses this share of the mass (rounded at random) as heat:
HEAT_PIECES = 4                        #   up to this many light heat particles (ghosts) that fly out from it
HEAT_SPEED = 6.0                       #   this fast (cells/tick, on top of its velocity) in random directions,
HEAT_TICKS = 40                        #   for this many ticks, then land as ordinary light particles. While faster
HEAT_COUPLING = 0.5                    #   than HEAT_MIN_SPEED against a free particle in its cell (not a star's),
HEAT_MIN_SPEED = 1.0                   #   a heat particle hands it this share of a head-on elastic collision's
                                       #   momentum and slows by as much: light matter is blown away, heavy matter
                                       #   barely moves and soaks the heat up
FUSION_LIGHT = 16                      # fusion in stars: a star's particle this light or lighter meets a light
FUSION_CHANCE = 0.002                  #   neighbour of the same star with this chance per tick, and the two fuse
FUSION_HEAT_SHARE = 0.05               #   into one, losing this share of their mass as heat (blowing light matter
                                       #   away from the star: its own particles let heat through)
HEAT_COLOR = (255, 250, 70)                # heat particles glow this colour (saturated: no particle is this colour)

# --- Gravity -----------------------------------------------------------------
G_SCALE_STEP = 1.25                    # < / > multiply or divide all gravity by this
GLOBAL_G = 0.2                         # global gravity (arrow keys), at gravity scale 1
GRAVITY_DIR = None                     # starting global gravity: None or down, down-left, left, ... (arrows, Q/E, 0)
GRAVITY_SCALE = 0.6                    # starting strength of all gravity (< / >)
G = 0.002                              # gravitational constant: particles, wells and super wells all pull with
                                       #   accel = G * mass * r / (r^2 + soft^2)^1.5 x (1 + d/R) e^(-d/R), d the
GRAVITY_REACH = 20.0                   #   softened distance and R this many cells: gravity fades past a few R, so
                                       #   things must come close to interact strongly (0: it reaches all the way)
WELL_DENSITY = 64.0                    # a brush-sized well weighs its circle's area x pour mass x this
WELL_SOFTENING = 4.0                   # default size of a solid well (cells)
WELL_INERTIA_MASS = 20000.0            # super wells accelerate (and top out at VMAX) x this / (this + their mass);
                                       #   so do solid wells in the global orbit and whirlpools
STAR_SPIN = (0.005, 0.02)              # a solid well spins at a random speed in this range (rad/tick), either way

# --- Stars: balls of particles held together by their own gravity ----------------------------------
STAR_SOFTENING = 0.6                   # a star pulls as a point at its centre of mass, softened over this x its
                                       #   radius; its pull works whether self-gravity is on or not
STAR_FIELD_BLOCK = 8                   # its pull is summed every this many cells and blended in between, except
                                       #   within its ring (or 3 blocks / 4 softening lengths): exact there
STAR_CAPTURE_ACCEL = 0.02              # its capture ring: where its pull drops to this, cut down to its Roche lobe
STAR_RING_MAX = 4.0                    #   against a heavier neighbour, but at most this x its radius and at least
STAR_RING_MIN = 1.0                    #   this x its largest radius lately (or 2 cells)
STAR_RING_GROWTH = 0.25                #   and it widens by at most this many cells per tick
                                       # Its particles are those inside the ring whose speed relative to it is
                                       #   below escape speed (bound to it); the most tightly bound star wins.
STAR_SMOOTH = 0.05                     # its mass is followed smoothly (this share per tick) and compared with the
STAR_PEAK_HALF_LIFE = 600              #   most it has held lately (forgotten with this half-life, in ticks):
STAR_UNSTABLE_SHARE = 0.5              #   below this share of it, or lighter than STAR_MIN_MASS (not in its
STAR_MIN_MASS = 300                    #   first STAR_SETTLE ticks), or with fewer than STAR_MIN_PARTICLES, it
STAR_SETTLE = 20                       #   can't hold together. Touching another star it merges into it; with a
STAR_MIN_PARTICLES = 12                #   heavier body's tide reaching into it (or in a super well's range) it is
                                       #   torn apart, its particles streaming away; otherwise it explodes.
STAR_SHOCK_MIN = 0.3                   # stars touching faster than this (relative speed, cells/tick) shock the
STAR_SHOCK = 1.0                       #   matter where they touch: it splashes out sideways at up to this x their
STAR_SHOCK_DEPTH = 1.0                 #   relative speed (from their common motion), as deep into each as they move
                                       #   in this many ticks, and only stays if bound. Slower, touching, they merge,
STAR_MERGE = 0.5                       #   as do stars whose centres come within this x the larger's radius
STAR_BLAST_REACH = 4.0                 # an exploding star's blast reaches this x its radius + 10 cells,
STAR_BLAST_SPEED = 3.0                 #   starting at this speed (cells/tick); its particles ride the front
STAR_BLAST_PUSH = 0.4                  #   as debris, and it shoves what it passes this x its reach
STAR_PLACE_LAYERS = ((0.4, 8.0), (0.7, 3.0), (1.0, 1.0))   # a placed star's particle masses by radius share, against
                                       #   its envelope: its core is made of pour-mass particles, the middle 3/8 and
                                       #   the envelope 1/8 of that (at least 1)
GHOST_STARS = False                    # placed stars arrive as ghost stars, landing GHOST_TICKS later (menu; shift+click
                                       #   with the Star tool always places one)
STAR_FORM_ON = True                    # a knot of matter with a heavy core inside a lighter envelope becomes a star
STAR_FORM_EVERY = 60                   #   holding its mass (checked every this many ticks, round up to
STAR_FORM_SEEDS = 12                   #   this many of the densest spots). A knot is the largest disc round a
STAR_FORM_RADIUS = (4, 30)             #   spot, between these radii (cells: about 50 to 2,800 particles), that is
STAR_FORM_FILL = 0.8                   #   at least this full, where the packing ends. Its core's typical mass
STAR_FORM_LAYER_RATIO = 2.0            #   must be at least this x its envelope's,
STAR_FORM_PURITY = 0.6                 #   with this share of each side's particles on its own side of the divide
STAR_FORM_MIN_LAYER = 3                #   and at least this many particles on each side. None forms within this
STAR_FORM_GAP = 8                      #   many cells of a star's capture ring, a solid well or a super well's
STAR_FORM_PER_CHECK = 1                #   core, and at most this many form per check. It must weigh at least 2x
STAR_FORM_BOUND = 0.8                  #   STAR_MIN_MASS, with this share of its mass bound to it (slower than
                                       #   escape speed relative to it)
WELL_REBUILD_MOVE = 0.5                # cells a well moves before the field is recomputed
FIELD_BLOCK = 4                        # wells' pull is summed every this many cells and blended in between...
FIELD_NEAR = 16.0                      # ...except within this many cells (or 3 softening lengths) of a well: exact
FIELD_NEAR_MAX = 72.0                  # ...up to this far: a well softened more than that is smooth enough to blend
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
SPAWNER_RATE = POUR_CHANCE             # particles per tick per cell of a spawner's circle: as dense as pouring by hand
WRAP = False                           # continuous borders (W): leaving one side enters from the opposite one
ROUND_RADIUS = 1.0                     # a round universe (U; the space presets) is a disc this x half the window's
                                       #   diagonal across, centred on it, so whatever turns with the global orbit
                                       #   through the window stays on its circle off-screen and comes back round;
                                       #   outside it is solid rim turning with the orbit (zoom out to see it all)
ZOOM_STEP = 1.25                       # ctrl+wheel / Z / shift+Z zoom out or in by this
ZOOM_MAX = 8.0                         # ...up to this; out to where the whole universe fits the window
OUTSIDE = (9, 10, 13)                  # colour beyond the universe's edge
ORBIT = 0                              # starting global orbit: 0 off, 1 clockwise, -1 counterclockwise (O)
ORBIT_EDGE_SPEED = 3.0                 # starting global orbit speed: cells/tick at the edge of the window (half its
                                       #   shorter side out); it turns at the same angular speed throughout
ORBIT_MIN_SPEED = 0.5                  # it turns things at least this fast (cells/tick), even at the centre
ORBIT_GRIP = 0.02                      # how quickly things are brought up to the orbiting speed (per tick)
ORBIT_STEP = 1.25                      # K / L multiply or divide the orbit speed by this
BLOB_MIN = 8                           # touching particles (no star's) at least this many form a blob, carried round
BLOB_MAX_RADIUS = 25.0                 #   by the global orbit as a whole; one more spread out than this (radius of
                                       #   gyration, cells: a long arc, say) is left to move a particle at a time

# --- Super wells (collapse) --------------------------------------------------
COLLAPSE_ON = True                     # shift+B
COLLAPSE_MASS = 40000                  # mass in a COLLAPSE_BLOCKS x COLLAPSE_BLOCKS block window that collapses,
COLLAPSE_BLOCKS = 5                    #   divided by the gravity scale (blocks are SG_BLOCK cells: 20 x 20 cells)
COLLAPSE_EVERY = 8                     # ticks between collapse checks
SUPER_RANGE_ACCEL = 0.01               # a well's reach: where its pull drops below this
SUPER_RANGE_FACTOR = 0.25              # a super well's range (the dotted circle) is this x its reach: it spins
                                       #   space round within it, and overlapping ranges merge. Its pull goes on
SUPER_SOFTENING = 0.25                 # its pull is softened over this share of its range (as it would be if
                                       #   gravity reached all the way: GRAVITY_REACH), so infalling particles
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
SUPER_SPIN_NATURAL = 1.5               # spin of a super well formed by collapse (which way: see SUPER_SPIN_PLACED)
SUPER_SPIN_MAX = 7.0                   # ; / ' spin the nearest super well down / up by SUPER_SPIN_STEP, up to this
SUPER_SPIN_PLACED = 1.5                # spin of a super well placed with B; new ones spin with the global orbit,
                                       #   or either way at random when it is off
SUPER_SPIN_STEP = 1.25
SUPER_SPIN_FOLLOWS_MASS = False       # a new super well's spin rises with its mass, in a straight line from its
SUPER_SPIN_FULL = 3.0                 #   starting spin to this at SUPER_EXPLODE_MASS: the heavier it gets, the more
                                      #   it flings matter out instead of feeding, so it grows steadily (setting
                                      #   its spin by hand stops this for that well)
SUPER_SPIN_ARMS_AT = 0.5               # its spiral arms turn as fast as its whirlpool carries matter round this share
                                       #   of the way out to its dotted circle...
SUPER_SPIN_FRAME_MAX = 0.6             # ...eased to less than this many radians per frame when that is faster (three
                                       #   arms a third of a turn apart turning further would seem to turn backwards)
SUPER_MERGE_ACCEL = 0.0025             # super wells whose ranges overlap are drawn together, closing faster by this x
                                       #   (sum of their ranges / their distance) cells/tick every tick, so the pull
                                       #   grows as they near (a few seconds from first overlap to merging) ...
SUPER_MERGE_MAX_SPEED = 3.0            #   ... up to this closing speed (cells/tick), until their cores touch and merge
SUPER_MERGE_SPIRAL = 0.03              #   their sideways motion round each other fades by this share per tick
SUPER_MERGE_GRACE = 120                # a super well that has just merged, or just got over SUPER_EXPLODE_MASS in
                                       #   any way, can't go supernova for this many ticks (from the first merger:
                                       #   more in that time don't stretch it, unless one takes it over the limit)
SUPER_MERGE_SHOCK_REACH = 1.5          # a merger sends a shock front out to this x the merged well's range ...
SUPER_MERGE_SHOCK_SPEED = 6.0          #   ... starting at this speed (cells/tick), slowing as it goes; behind it a
SUPER_MERGE_SHOCK_KICK = 7.0           #   wind keeps everything moving outwards at this (cells/tick), stronger than
SUPER_MERGE_SHOCK_TICKS = 90           #   what pulls it back, for this many ticks in all
MERGE_EJECT = (0.002, 0.02)           # share of the combined mass a super well merger spits out as particles
MERGE_LOSS_BIAS = 1.0                  # who loses that mass: each well's share ~ its mass ^ -bias. 1 = inversely
                                       #   to size (a well merging with one half its size loses half as much as
                                       #   it); 0 = equal shares; -1 = in proportion to size
COLLAPSE_EJECT = (0.10, 0.30)          # share of the collapsed mass a new super well spits out
EJECT_MASS = (1, 256)                  # masses of the ejected particles (uniform)
EJECT_ESCAPE = 1.2                     # ejected particles leave at this x the speed needed to escape the range
SUPER_EXPLODE_MASS = 10_000_000        # a super well this heavy explodes like a supernova: all its mass leaves its spot
                                       #   as a ring of very heavy debris (ghosts) ... (the menu's Supernova at, in
SUPER_EXPLODE_STEP = 500_000           #   steps of this, between these)
SUPER_EXPLODE_RANGE = (500_000, 50_000_000)
SUPER_BLAST_HOT_MASS = 3300            #   ... each piece about this heavy at first (random, never over MAX_MASS) ...
SUPER_BLAST_COOL_FROM = 20             #   ... which from this age (ticks), then every SUPER_BLAST_COOL_EVERY, breaks
SUPER_BLAST_COOL_EVERY = 20            #   in two ("cools") until the pieces are no heavier than...
SUPER_BLAST_COOL_TO = 400              #   ... this; once cool and at rest, a piece lands where it is
SUPER_BLAST_SCATTER = 1.5              # a piece breaking off lands about this far (cells) from the one it broke from
SUPER_BLAST_RADIUS = 225.0             # the ring and the shock front slow to a halt this far out (cells; at most 45% of
                                       #   the shorter side) ...
SUPER_BLAST_SPEED = 6.0                #   ... starting at this speed (cells/tick), slowing like a blast wave
SUPER_BLAST_FILL = 0.15                # its debris expands with it, each piece at a fixed share of its radius,
                                       #   spread evenly over the area from this share out to the front, so it
                                       #   comes to rest over the area the front swept clear, not piled on its rim
SUPER_BLAST_PUSH = 60.0                # the front shoves every particle it passes outwards, those nearby this far
                                       #   (cells), less and less the further out, nothing at the edge
SUPER_BLAST_DRAG = 0.1                 #   behind the front, outward motion fades by this much per tick (so a shoved
                                       #   particle coasts about 1 / this x its speed, not for ever)
SUPER_BLAST_SETTLE = 40                #   and keeps fading for this many ticks after the front has stopped
SUPER_EXPLODE_CALM = 180               # ticks after an explosion before anything can collapse again
