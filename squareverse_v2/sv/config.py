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
WAKE_PAR_RADIUS = 300.0                # cells: a moved well wakes the particles in its reach on all cores only when
                                       #   that is wider than this (starting the cores costs more than a small disc:
                                       #   one core wakes a 200-cell disc in ~40 us, the cores' tail is ~250 us)
STAR_CARRY_PAR = 8                     # stars carried on all cores once there are this many (kernels.carry_stars_par)

# --- Starting state of the app ----------------------------------------------
DEFAULT_PRESET = "systems"             # rain, disk, cloud, binary, systems or empty (--preset overrides)
SYSTEM_REACH = 120.0                   # the systems and binary presets keep the gravity reach and strength their orbits
SYSTEM_SCALE = 0.6                     #   were tuned for (at the default 30 a star orbiting a super well spirals in
                                       #   within a few turns: TO_DO.md)
SYSTEM_WELL = 400_000                  # the systems preset: super wells this heavy (the lightest there can be at its
                                       #   strength, so no star outweighs them),
SYSTEM_ORBIT = 120.0                   #   each orbited this far out (cells: the middle of where they can, 92-135 at a
SYSTEM_STAR_RADIUS = 10.0              #   reach of 120) by stars of this size (cells; a 20 px brush: three of the
SYSTEM_POUR = 16                       #   default size unsettle each other) and pour mass
SYSTEM_CENTRE_STARS = 3                # stars round the one in the middle
SYSTEM_OTHERS = (2, 3)                 # how many more systems are scattered round it (at random, between these) ...
SYSTEM_OTHER_STARS = (1, 2)            #   ... with this many stars each, out of each other's reach where there is room
SYSTEM_SPACING = 5.0                   # (with gravity reaching everywhere: at most this x the orbit apart)
SYSTEM_EDGE = 10.0                     # their stars clear of the edge by this (cells)
SYSTEM_BALANCE = 0.1                   # where the others' pulls on the middle one cancel to under this share of one's
                                       #   at the nearest they may be (else its stars are dragged off their orbits)
DISK_REACH = 20.0                      # the disk preset's gravity reach (cells) and strength, which it was made for
DISK_SCALE = 0.6
DISK_MASS = 20_000_000                 # the disk preset's total mass, in particles of every mass from 1 up
DISK_FILL = 0.6                        # ...filling this share of its ring's cells
TICKS_PER_FRAME = 1                    # + / -
BRUSH_PX = 40                          # brush circle radius (mouse wheel), in px at zoom 1
POUR_MASS = 4                          # a mass, or "random" for RANDOM_MASS (keys 1-6)
SUPER_PLACE_MASS = 1_000_000           # a placed super well's mass (B, Super well tool); its core size follows it
SUPER_PLACE_STEP = 1_000_000           #   the menu's mass buttons and the mouse wheel step it by this
REPULSOR_PLACE_MASS = 250_000          # a placed repulsor's mass (shift+G, Repulsor tool); its size follows it
REPULSOR_PLACE_MASSES = (50_000, 100_000, 250_000, 500_000, 1_000_000, 2_000_000)   # the menu's mass buttons
PLACE_SIZE_PX = (2, 160)               # the brush, a star or a spawner: radius range in px at zoom 1 (mouse wheel)
REPULSOR_SIZE_PX = (2, 320)            # a repulsor's radius range in px at zoom 1
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
STAR_REACH_FADE = 0.3                  # where a tide cuts it down, the uncut ring is dotted this bright round it
STAR_GLOW = 0.55                       # brightness of a solid well's corona at its surface...
STAR_GLOW_SIZE = 2.2                   # ...fading out at this x its radius
SPAWNER_COLOR = (120, 220, 150)
SUPER_RIM_COLOR = (120, 110, 150)
SUPER_RANGE_COLOR = (150, 140, 190)
SUPER_SPIN_COLOR = (200, 175, 255)
GHOST_TINT = (190, 215, 255)           # ghosts are drawn see-through, washed towards this

# --- Particles ---------------------------------------------------------------
MAX_MASS = 4096                        # the heaviest rung: particle masses come in rungs 1, 2, 4, ... up to this (Fusion)
POUR_MASSES = (1, 4, 16, 64, 256)      # keys 1-5
RANDOM_MASS = (1, 256)                 # key 6: each poured particle gets a random rung in this range
HEAVY_POUR_MASSES = (512, 1024, 2048, 4096)   # shift + 1-4: a second row, up to MAX_MASS, for heavy stars and pours
RANDOM_HEAVY_MASS = (512, 4096)        # shift + 6: a random rung in this range
POUR_CHANCE = 0.25                     # per cell per frame under the brush (sand.py)
GHOST_TICKS = 180                      # shift+click pours ghosts: they feel gravity (not each other's) but collide
                                       #   with nothing for this many ticks, then land as ordinary particles in
                                       #   the nearest free cells
GHOST_LAND_NEAR = 3                    # ...within this many cells; with none that close it joins a particle there of its
                                       #   own rung (making the next one up), or else stays a ghost and tries again,
GHOST_LAND_SPREAD = 2                  #   looking a cell further out every this many ticks it has waited (so in a
                                       #   packed pile of other rungs it lands at the nearest room, not far away)

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
# --- Fusion and fission ------------------------------------------------------------------------------------
# A particle's mass is a rung: 1, 2, 4, ... MAX_MASS. Two of the same rung can fuse into the next one up (their masses
# add up to it exactly), and one can break into two of the rung below. Each rung holds binding energy - its mass x
# VMAX^2 (VMAX is the speed of light) x a share that rises to FUSION_BINDING at FUSION_PEAK ("iron") and falls after
# it - so fusing light rungs gives off energy (as heat) and fusing past the peak takes it. Whether two touching or
# colliding particles fuse depends on the energy they bring - their motion against each other and their heat - against
# a barrier that grows with their masses: they get over it with a chance of exp(-barrier / energy) (kernels._tunnel),
# so hotter matter fuses more often and heavier rungs need it hotter. Nothing else decides when they fuse.
MERGE_ON = True                        # fusion (M)
SPLIT_ON = True                        # fission: a hard enough hit breaks a particle into two of the rung below (P)
FUSION_BINDING = 0.05                  # binding energy per unit of mass at the peak, as a share of VMAX^2 (the rest
                                       #   energy): 3.2 per unit of mass. The curve to it is 1 - (1 - rung / peak rung)^2
FUSION_PEAK = 256                      # the most tightly bound rung: fusing up to it gives off energy, past it takes it
FUSION_TAIL = 0.15                     # past the peak the binding per unit of mass falls by this share by MAX_MASS
FUSION_BARRIER = 9.0                   # the barrier two particles of masses a and b must get over: this x a b /
                                       #   (a^1/3 + b^1/3), in energy (two of mass m: this / 2 x m^5/3). Against their
                                       #   energy, m a b / (a + b) x (relative speed^2 / 2 + both temperatures): two
                                       #   mass-1 particles at 2 cells/tick fuse ~1 time in 100, two of 16 need a
                                       #   temperature of ~6, two of 256 ~40

# --- Radiation (heat) ------------------------------------------------------------------------------------
RADIATION_ON = True                    # hot surfaces radiate (HEAT_RADIATE) and super well mergers send out waves
HEAT_MIN_SPEED = 1.0                   # gravitational waves faster than this against a free particle push it
HEAT_CONDUCT = 0.1                     # heat (energy that collisions, contacts and internal friction lose: see
                                       #   kernels.KIN) spreads between touching particles, evening out this share of
                                       #   their difference in temperature (heat per unit mass) each heat step ...
HEAT_RADIATE = 0.02                    # ... and with radiation on, a particle with open sides radiates this share of its
                                       #   heat per tick per open side of four, as heat particles of mass 1 (the
                                       #   lightest), each one unit of mass's worth of energy, VMAX^2 (VMAX is the speed
                                       #   of light: World.radiation_cost)
HEAT_EVERY = 2                         # ticks between heat steps (kernels.heat_step; the rates above are per tick)
RADIATION_RECYCLE = True               # radiation (energy only: quanta of VMAX^2 at the speed of light, taken in as heat
                                       #   by the first matter it meets) that reaches the universe's edge comes back
                                       #   in from a random point of it, heading inwards, so the universe keeps its
                                       #   energy; off, it is gone (menu: Radiation comes back)
HEAT_PRESSURE = 0.0                    # heat pushes: a particle's pressure is its heat x this (1: as a 2D gas's, energy
                                       #   per area) and touching particles push each other apart with their mean
                                       #   pressure, so hot matter expands and a hot core holds up what lies on it
                                       #   (kernels._pressure_push); 0 turns it off. Off until stars are reworked
                                       #   (TO_DO.md physics rework step 5): at 1 a star's internal friction turns its
                                       #   jostling into heat and the pressure turns it back into jostling, so with only
                                       #   radiation to take it away stars puffed apart and hot piles never slept
RADIATION_COLOR = (150, 225, 255)      # radiation - heat and gravitational waves - glows this pale blue (yellow
HEAT_COLOR = RADIATION_COLOR           #   heat looked like the stars' own particles)

# --- Gravity -----------------------------------------------------------------
G_SCALE_STEP = 1.25                    # < / > multiply or divide all gravity by this
GLOBAL_G = 0.2                         # global gravity (arrow keys), at gravity scale 1
GRAVITY_DIR = None                     # starting global gravity: None or down, down-left, left, ... (arrows, Q/E, 0)
GRAVITY_SCALE = 1.2                    # starting strength of all gravity (< / >): strong up close ...
G = 0.002                              # gravitational constant: particles, wells and super wells all pull with
                                       #   accel = G * mass * r / (r^2 + soft^2)^1.5, in full out to the softened
GRAVITY_REACH = 30.0                   #   distance R (this many cells; ... but short: in a universe this small a long
                                       #   reach gathers a supernova's debris into a few big clumps whose stars all
                                       #   merge, while 30 leaves ~40 separate stars), then fading smoothly to nothing at 2 R
                                       #   (kernels.fade), so things must come close to interact and further apart
                                       #   don't at all; orbits within R are stable, past ~1.16 R none is (0: it
                                       #   reaches all the way)
WELL_DENSITY = 64.0                    # a brush-sized well weighs its circle's area x pour mass x this
WELL_SOFTENING = 4.0                   # default size of a solid well (cells)
WELL_INERTIA_MASS = 20000.0            # solid wells respond to the global orbit and the whirlpools x this / (this +
                                       #   their mass); gravity accelerates every well (super wells too) in full
STAR_SPIN = (0.005, 0.02)              # a solid well spins at a random speed in this range (rad/tick), either way

# --- Stars: balls of particles held together by their own gravity ----------------------------------
STAR_SOFTENING = 0.6                   # a star pulls as a point at its centre of mass, softened over this x its
                                       #   radius; its pull works whether self-gravity is on or not
STAR_FIELD_BLOCK = 8                   # its pull is summed every this many cells and blended in between, except
                                       #   within its ring (or 3 blocks / 4 softening lengths): exact there
STAR_CAPTURE_ACCEL = 0.02              # its capture ring: where its pull drops to this, cut down to its Roche lobe
STAR_RING_MAX = 2.0                  #   against a heavier neighbour, but at most this x its radius and at least
STAR_RING_MIN = 1.0                    #   this x its largest radius lately (or 2 cells)
STAR_RING_GROWTH = 0.25                #   and it widens by at most this many cells per tick
                                       # Its particles are those inside the ring whose speed relative to it is
                                       #   below escape speed (bound to it); the most tightly bound star wins.
STAR_DAMPING = 0.2                   # internal friction: a star's particles' jostling (motion relative to the star
                                       #   moving and turning as a whole) fades by this share a tick (see
                                       #   World._damp_stars); without it a tide's shear tore fast-orbiting stars apart
STAR_HILL_RING = 1.5                   # near a much heavier body a star's capture ring is cut to this x its Hill radius
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
                                       #   in this many ticks, and only stays if bound. Slower, they merge once sunk
STAR_TOUCH_MERGE = 0.6                 #   into each other this far (centres closer than this x the sum of their radii;
                                       #   1 = as soon as they touch), so neighbours resting against each other stay two
STAR_MERGE = 0.5                       #   stars; and any whose centres come within this x the larger's radius merge
STAR_BLAST_REACH = 4.0                 # an exploding star's blast reaches this x its radius + 10 cells,
STAR_BLAST_SPEED = 3.0                 #   starting at this speed (cells/tick); its particles ride the front
STAR_BLAST_PUSH = 0.4                  #   as debris, and it shoves what it passes this x its reach
STAR_PLACE_LAYERS = ((0.4, 8.0), (0.7, 3.0), (1.0, 1.0))   # a placed star's particle masses by radius share, against
                                       #   its envelope: its core is made of pour-mass particles, the middle 3/8 and
                                       #   the envelope 1/8 of that (at least 1)
ORBIT_BAND_HOLD = 6.0                  # the Star tool shows round each super well where the star it would place can
ORBIT_BAND_HOLD_PER_SPEED = 0.0        #   orbit: outside the whirlpool's faint circle, beyond where its own pull at its surface is
                                       #   (this + this x the circular speed) x the tide across it - with star damping
                                       #   and the normal force that no longer cancels a star's pull against a tide
                                       #   (2026-11), dense stars 90-130 cells out round
                                       #   0.3-5M wells kept 98-100% of their mass over 1,500 ticks at 5.9x or more,
                                       #   92% at 4.7x, and came apart at 4.5x or less, whatever their speed ...
ORBIT_BAND_MAX_SPEED = 6.0             #   ... and where the circular speed is at most this (cells/tick; VMAX is 8) ...
ORBIT_BAND_STABLE = 2.8                #   ... out to where the pull falls as fast as 1 / r^this (2.8: 3 is the limit
                                       #   for any stable orbit), within half its Hill radius against any other super
                                       #   well (and 0.6 of the way to where their pulls balance), inside the edge
ORBIT_BAND_COLOR = (110, 220, 140)
ORBIT_BAND_NONE_COLOR = (235, 110, 95)  # round a super well the star can't orbit anywhere: a dashed circle
AUTO_STAR_RECIPES = ((16, 10), (16, 8), (64, 8), (16, 6), (64, 6), (256, 6), (512, 6), (1024, 6), (1024, 4),
                     (1024, 3))        # (at a reach of 30 only the last, densest ones can orbit)
                                       # the Auto star tool's stars, (pour mass, radius in cells), tried in this
                                       #   order until one can orbit the super well clicked near (skipping any over half
                                       #   the collapse threshold: it would collapse into a super well itself) ...
AUTO_STAR_SPACING = 120.0              #   ... round a well with stars already, on their orbit at least this many
                                       #   degrees from each: up to three, evenly spaced, hold (4 or more, or 60 degrees
                                       #   apart, were pulled off their orbits within a minute)
ORBIT_STARS = True                     # a placed star sets off in orbit round the super well pulling hardest on it
                                       #   (menu; T)
GHOST_STARS = False                    # placed stars arrive as ghost stars, landing GHOST_TICKS later (menu; shift+click
                                       #   with the Star tool always places one)
STAR_FORM_ON = True                    # a knot of matter with a heavy core inside a lighter envelope becomes a star
STAR_FORM_EVERY = 10                   #   holding its mass (checked every this many ticks, round up to
STAR_FORM_SEEDS = 200                  #   this many of the densest spots). A knot is the largest disc round a
STAR_FORM_RADIUS = (4, 30)             #   spot, between these radii (cells: about 50 to 2,800 particles), that is
STAR_FORM_FILL = 0.8                   #   at least this full, where the packing ends. Its core's typical mass
STAR_FORM_LAYER_RATIO = 2.0            #   must be at least this x its envelope's,
STAR_FORM_PURITY = 0.6                 #   with this share of each side's particles on its own side of the divide
STAR_FORM_MIN_LAYER = 3                #   and at least this many particles on each side. None forms within this
STAR_FORM_GAP = 8                      #   many cells of a star's capture ring, a solid well or a super well's
STAR_FORM_PER_CHECK = 200              #   core, and at most this many form per check. It must weigh at least 2x
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

SG_ON = True 
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
COLLAPSE_MASS = 240000                 # mass in a COLLAPSE_BLOCKS x COLLAPSE_BLOCKS block window that collapses,
COLLAPSE_BLOCKS = 5                    #   divided by the gravity scale (blocks are SG_BLOCK cells: 20 x 20 cells):
                                       #   200k at the default strength. It is also the lightest a super well can be
                                       #   and the heaviest a star can be - one that reaches it collapses into a super
                                       #   well (World._collapse_heavy_stars) - so stars are always lighter
COLLAPSE_EVERY = 8                     # ticks between collapse checks
STAR_COLLAPSE_FACTOR = 4.0             # a star's own particles count this many times less in the collapse check, so a
STAR_COLLAPSE_RANGE = (1.0, 20.0)      #   star becomes a super well only if this many times denser than loose matter
                                       #   must be (the menu's Stars collapse at, between these)
STAR_COLLAPSE_WARN = 0.7               # the Star tool's brush turns amber when its star would hold this share of that
SUPER_RANGE_ACCEL = 0.01               # a well's reach: where its pull drops below this
SUPER_RANGE_FACTOR = 0.25              # a super well's range (the faint circle) is this x its reach: it spins
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
SUPER_DRAG = 0.35                      # a spinning super well drags space itself round (frame dragging), out to its
SUPER_DRAG_MAX = 0.7                   #   reach (where its pull drops to SUPER_RANGE_ACCEL): space there turns at
SUPER_DRAG_EDGE = 0.5                  #   this x its spin (at most SUPER_DRAG_MAX) of the angular speed something
SUPER_DRAG_TURN_MAX = 0.25             #   circling there has, fading out over this outer share of the reach, never
                                       #   faster than this (rad/tick) nor carrying anything faster than VMAX.
                                       #   Everything in it is carried round - where it is and which way it is
                                       #   heading, turned together - so nothing is sped up, but what falls in
                                       #   spirals in the way the well spins instead of falling straight. Within
                                       #   its range its whirlpool takes over (across SUPER_SWIRL_EDGE)
SUPER_WHIRL_COLOR = (90, 80, 120)     # its whirlpool's range (a faint circle; its point of no return is dotted)
SUPER_SPIN_NATURAL = 0.5               # spin of a super well formed by collapse (which way: see SUPER_SPIN_PLACED);
                                       #   low, so a light well barely stirs what orbits it (it rises with mass)
SUPER_SPIN_MAX = 7.0                   # ; / ' spin the nearest super well down / up by SUPER_SPIN_STEP, up to this
SUPER_SPIN_PLACED = 0.5                # spin of a super well placed with B; new ones spin with the global orbit,
                                       #   or either way at random when it is off
SUPER_SPIN_STEP = 1.25
SUPER_SPIN_FOLLOWS_MASS = True        # a new super well's spin rises with its mass, in a straight line from its
SUPER_SPIN_FULL = 3.0                 #   starting spin to this at SUPER_EXPLODE_MASS: the heavier it gets, the more
                                      #   it flings matter out instead of feeding, so it grows steadily (setting
                                      #   its spin by hand stops this for that well)
SUPER_SPIN_ARMS_AT = 0.5               # its spiral arms turn as fast as its whirlpool carries matter round this share
                                       #   of the way out to its faint circle...
SUPER_SPIN_FRAME_MAX = 0.6             # ...eased to less than this many radians per frame when that is faster (three
                                       #   arms a third of a turn apart turning further would seem to turn backwards)
SUPER_INSPIRAL_TICKS = 540             # super wells whose ranges overlap fall into orbit round each other and spiral
                                       #   in: from ranges just touching to merging takes about this many ticks, the
SUPER_INSPIRAL_SHRINK = 1.5            #   gap closing ~ (sum of ranges / gap) ^ this (slowly at first, ever faster) ...
SUPER_INSPIRAL_PLUNGE = 0.12           #   ... and at the end by at most this share of it a tick: the final plunge
SUPER_INSPIRAL_SPIN = 0.03             # they circle each other this fast (rad/tick) when their ranges just touch, and
SUPER_INSPIRAL_SPIN_MAX = 0.35         #   faster as they near (~ gap ^ -1.5, as Kepler's law), up to this and never
                                       #   faster than VMAX against each other
SUPER_INSPIRAL_GRIP = 0.1              # a pair just caught settles onto that orbit over 1 / this ticks
SUPER_STRETCH = 0.6                    # drawn: each core stretches towards the other by up to this share (~ 1 / gap^2),
SUPER_BRIDGE = 1.6                     #   and once their gap is under this x their cores' radii added up a bridge
                                       #   joins them
SUPER_RINGDOWN = 0.5                   # the merged core is a bar this stretched, turning as fast as they circled at
SUPER_RINGDOWN_TICKS = 18              #   the end, settling into a round core (e-folding time, ticks)
SUPER_GW_INSPIRAL = 0.012              # gravitational waves (radiation; at most, for equal masses, x 4 m1 m2 / M^2): a
                                       #   pair radiates this share of its mass as it spirals in, ever faster (the
                                       #   binding energy it gives up: ~ 1 / gap) ...
SUPER_GW_MERGER = 0.01                 #   ... this share in a burst as they merge ...
SUPER_GW_RINGDOWN = 0.008              #   ... and this share, fading, while the merged core settles
SUPER_GW_SPEED = 8.0                   # waves are particles flying straight at this speed (cells/tick), unbent by
SUPER_GW_TICKS = 50                    #   gravity, for this many ticks, then land as ordinary particles. They leave
SUPER_GW_SPREAD = 0.35                 #   in two beams along the line through the pair (spread this much, radians),
SUPER_GW_BURST_SPREAD = 0.9            #   (the merger's burst this much), so they trace a two-armed spiral
SUPER_GW_PIECES = 48                   #   at most this many a tick (the merger's burst: 8 x this), heavier when more
SUPER_GW_COUPLING = 0.15               #   is radiated; like heat they hand matter this share of a head-on hit
SUPER_GW_COLOR = RADIATION_COLOR       #   and glow this colour
SUPER_MERGE_GRACE = 120               # a super well that has just merged, or just got over SUPER_EXPLODE_MASS in
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
SUPER_BLAST_REF_MASS = 10_000_000      # the figures below are for a super well this heavy going supernova; a heavier
                                       #   or lighter one scales them by sqrt(mass / this) (World.blast_scale)
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
SUPER_BLAST_COAST = 1.0                # the debris doesn't stop with the front: it keeps flying (still ghosts, so it
                                       #   can't clump yet), slowing the same way, to rest this x the front's reach
                                       #   further out (so 2x as far in all), less where the universe's edge is
                                       #   closer; 0 = it stops with the front
SUPER_BLAST_COAST_MARGIN = 10.0        #   ... stopping at least this many cells short of the universe's edge (room
                                       #   for the pieces' scatter and landing GHOST_LAND_NEAR away)
SUPER_EXPLODE_CALM = 180               # ticks after an explosion before anything can collapse again
