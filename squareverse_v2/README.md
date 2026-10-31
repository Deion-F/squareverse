# Squareverse v2

A particle sandbox for watching large numbers of square particles under gravity wells, global gravity and
self-gravity. Particles of different masses layer, collide, merge and split. It is a ground-up rebuild of
the older `squareverse_pygame` edition (in the history of `master`) for performance, using the architecture of the
falling-sand prototype (`~/TV_Project/sand.py`) plus numba.

```
./squareverse                      # from the repository root
python main.py --preset cloud      # or directly; re-launches itself with ../.venv if numba is missing
python main.py --cell 1 --preset disk --particles 200000
python main.py --fullscreen                    # F11 toggles; the window is also resizable
python main.py --preset rain --benchmark 300   # headless timings
python -m pytest                   # physics invariants
```

Press **H** in the app for the controls. F1–F4 load the presets (rain, disk, cloud, binary).

* **Stars (wells):** G places a well and Shift+G a repulsor, the size of the brush circle (mouse wheel). A well is
  a solid, spinning star: a glowing disc with a corona, coloured by its mass (red-orange when light, through yellow and
  white to blue-white when very heavy; a repulsor glows cold blue), its sunspots turning with it. Its surface carries
  resting particles round. Particles
  can't enter its body: they bounce off, slide around and rest on its surface, building a
  crust. Particles already inside when it is placed, or when it moves over them, are pushed out to its surface. A
  well has a mass: its circle's area × the pour mass × `WELL_DENSITY` (64). It pulls with the same constant `G` as
  particles, so a well poured at mass 64 holds its own in a heavy scene. Wells attract each other and, with
  self-gravity on, are pulled by the particles. Gravity accelerates a star as it does a particle, whatever its mass
  (up to `VMAX`), so a star swings into orbit round a super well or another star instead of crawling. Only the drag of
  the global orbit and of super wells' whirlpools moves heavy stars more slowly (`WELL_INERTIA_MASS`).
  Colliding stars bounce apart elastically (`STAR_RESTITUTION` 1.0) and shed debris from the point of contact,
  the smaller losing more; each shrinks to keep its density (`STAR_*` settings). A star smaller than
  `STAR_SHATTER_RADIUS` (10 cells) shatters instead: it breaks into particles of random masses adding up to its
  mass, which fly apart. A star that touches a super well's core dissolves into particles in a wave that spreads
  from the point of contact (`STAR_DISSOLVE_*`), and the core swallows them as they reach it. Repulsors stay put and ignore the global
  gravity direction. Shift+drag moves any well, X deletes the nearest one, and `,` / `.` make the nearest well lighter
  or heavier. Hover a well to see its mass, speed and reach.
* **Star formation:** every 30 ticks, a clump of touching particles with space round it becomes a star holding
  its total mass, momentum and spin when it is layered like one: a heavy core, a lighter mantle and a lighter crust
  still, each layer's typical mass at least 2× the next one out's, with a sharp divide between them (a smooth gradient
  doesn't count) and most of each layer's particles in its own mass band. It must also be round (at most 1.5× as long
  as it is wide, filling the disc of its area, solid in the middle) and between 4 and 30 cells in radius (about 50 to
  2,800 particles). See `STAR_FORM_*`. To make one, pour a small heavy blob, then a lighter ring round it, then a
  lighter ring still, with self-gravity on to hold it together.
* **Super wells:** B places one (as heavy as a brush-sized well, and never lighter than the collapse threshold). It
  is a tiny black core that deletes every particle and super well touching it and adds their mass to its own. Its pull
  grows with that mass and follows the same law as every other mass, at any distance. Inside its dotted circle it
  whirls everything round the way it spins (`SUPER_SWIRL_*`), at full strength right out to the circle (it fades in
  only over the outer 15%). Nothing inside sleeps or rests on friction, so matter keeps circling unless other
  matter blocks its way, and spirals in over several turns. Its spiral arms show which way it spins, turning faster and brighter the faster it
  spins. `;` / `'` spin the nearest super well slower / faster (up to `SUPER_SPIN_MAX`, 7). One placed with B starts at spin 5
  (`SUPER_SPIN_PLACED`); one formed by collapse spins at 5
  (`SUPER_SPIN_NATURAL`) the way the collapsing matter was turning. Above spin 1 it whirls
  matter faster than it would orbit and flings it out into a ring instead of drawing it in. When two super wells' dotted circles overlap, they are drawn
  together, slowly at first and ever faster as they near: the pull between them grows as their distance shrinks
  (`SUPER_MERGE_ACCEL`, up to `SUPER_MERGE_MAX_SPEED`, 3 cells/tick), and their motion round each other fades
  (`SUPER_MERGE_SPIRAL`), so they spiral in and merge within a few seconds. The lighter one covers more of the gap. The merged well spits out 1–10% of their combined mass as particles, taken mostly from the smaller of the two
  (`MERGE_LOSS_BIAS`). A super well that reaches `SUPER_EXPLODE_MASS` (5,000,000) goes
  supernova: it vanishes and all of its mass leaves its spot as a ring of very heavy debris (ghosts of about 3,300
  mass, `SUPER_BLAST_HOT_MASS`) riding a shock front that starts at 6 cells/tick (`SUPER_BLAST_SPEED`) and slows to
  a halt 150 cells out (`SUPER_BLAST_RADIUS`, at most 45% of the shorter side). The front shoves every particle it
  passes outwards, those near the middle about 60 cells (`SUPER_BLAST_PUSH`), less further out and nothing at the
  edge, then they come to a stop (`SUPER_BLAST_DRAG`), leaving a clear cavity and a pile-up shell. The debris cools as it
  flies: every 20 ticks from age 20 each piece over 400 mass breaks in two, ending as about 17,000 particles of 200–400
  mass that land as ordinary ones after the ghost time. Collapse is paused for 180 ticks (`SUPER_EXPLODE_CALM`) so the
  debris can spread before dense parts of it collapse again. Stars, super wells and spawners aren't pushed.
* **Collapse** (Shift+B, on by default): every 8 ticks, the heaviest 20×20-cell window collapses into a super well
  (or feeds one close by) once it holds `COLLAPSE_MASS` (5,000). The new super well keeps the matter's momentum and
  spits out 10–30% of it. Ejected particles have random masses (`EJECT_MASS`) and leave at 1.2× the speed needed to
  escape its range, so they get out unless something stops them.
* **Spawners:** F places a particle spawner the size of the brush circle, pouring ghost particles (see Ghosts;
  `SPAWNER_GHOSTS`) at the current pour mass (or random range), so they don't pile up and collapse at the spawner. Bigger circles pour more: `SPAWNER_RATE` particles per tick per cell of area, about 2 per
  tick for the default brush. A spawner has no collisions, so it passes through particles and stars. It falls under
  every kind of gravity like a particle, and a super well's core deletes it. Shift+F places a locked spawner that
  stays exactly where it is put and ignores gravity. Shift+drag moves spawners, and X deletes the nearest.
* **Continuous borders:** W makes the edges wrap: a particle leaving one side enters from the opposite one. Gravity
  reaches across the seam too (wells pull the shortest way round, and self-gravity becomes periodic), and wells and
  spawners wrap as well.
* **Global orbit:** O cycles off / clockwise / counterclockwise, and K / L make it slower / faster. It starts
  turning the edge of the universe at 3 cells/tick (`ORBIT_EDGE_SPEED`) whatever the window size, and resizing
  keeps the edge speed. Everything,
  wells included, is brought round the centre of the universe, faster the further out it is and never slower than
  `ORBIT_MIN_SPEED`, so nothing comes to rest. Each thing gets exactly the inward pull its own circling needs, so
  nothing slow is dragged to the middle, plus a nudge towards the orbiting speed (`ORBIT_GRIP`). Particles are
  processed front-first along the flow so moving groups don't jam.
* **Gravity strength:** `<` / `>` scale all gravity (global direction, wells, super wells, self-gravity). The
  collapse threshold is divided by the same factor, so stronger gravity collapses sooner.
* **Ghosts:** Shift+click pours ghost particles (Shift+click on a well or spawner still drags it). For
  `GHOST_TICKS` (180, 3 seconds) they feel every kind of gravity except each other's, but collide with nothing,
  passing through particles, stars and each other. They aren't counted in self-gravity or collapse, so a big pour
  can't turn straight into a super well. Then each lands as an ordinary particle in a random free cell of the nearest ring of cells round it that has
  room, so a crowd landing together spreads out evenly. A super
  well's core still swallows them. They are drawn see-through.
* **Particles:** S toggles self-gravity, and M / P toggle merging / splitting (both on by default). Keys 1–5 pour a
  fixed mass, and 6 pours particles with a random mass between the min and max of `RANDOM_MASS` in `sv/config.py`.

Resizing the window or going fullscreen resizes the world. The scene is kept and stays pinned to the side global
gravity points at, or centred when there is no global gravity. Wells move with it.

## Why it is fast

| | legacy `squareverse_pygame` | v2 |
|---|---|---|
| Hidden per-particle work | a full child universe (up to 192 children) moved every tick, about 90% of tick time | 4 child counts per particle, updated every 4th tick |
| Which particles run | every Square, every tick | only **awake** ones. Settled particles sleep and are woken by neighbours, wells or self-gravity changes |
| State | dataclass objects, string directions, dicts | flat numpy arrays per cell; the tick loop is numba-compiled machine code |
| Processing order | spawn order | lowest potential first (leading particles first, as in sand.py), in memory order within a potential bucket |
| Rendering | 2 `draw.rect` per Square per frame | one kernel fills an RGB buffer, then one `frombuffer` + `scale` blit |

Measured on a Ryzen 5 PRO 5650U laptop (`--benchmark 300`, mean ms per tick):

| scene | particles | awake (mean) | step | rendering |
|---|---|---|---|---|
| legacy, 100×100 grid | 10,000 → 3,137 | all | **400** | (2 rects per Square) |
| sand.py, 480×360 (same rain test) | 59,226 | 20k–130k awake cells | **36–214** | – |
| rain, 480×360 | 46,902 | 31,916 | 3.0 | < 1.5 ms |
| rain, 480×360 | 83,966 | 63,034 | 5.9 | < 1.5 ms |
| disk, 960×720 (1 px) | 145,264 | 120,246 | 22.8 | ~3 ms |
| rain, 960×720 (1 px) | 267,250 | 217,669 | 21.1 | ~3 ms |
| cloud + self-gravity, 960×720 | 95,926 | 103,968 | 11.0 + 1.7 gravity | ~3 ms |

A settled world costs almost nothing, because only moving particles are simulated.

## Physics model (`sv/kernels.py`)

* One particle per cell. Each has a float velocity and a sub-cell offset, so speeds below one cell/tick still move it.
* **Forces:** cached field from wells and global gravity, plus self-gravity (particle-mesh: mass is binned into
  4×4 blocks, the potential comes from an FFT convolution, refreshed every 4 ticks), plus optional children lean (J).
* **Contacts**, applied in this order:
  1. Split: the particle that is hit breaks in two, only in collisions at least `SPLIT_SPEED` (2) fast that also
     carry more than `BIND` impact energy per unit of its mass.
  2. 1D momentum exchange, for impacts above the resting threshold.
  3. Merge: the two become one with chance `MERGE_CHANCE` (5%), only in collisions at least `MERGE_SPEED` (1) fast
     that didn't split anything (momentum and children are conserved). Slow and resting contacts never merge.
  4. Sink: a heavier particle pushes through a lighter one, only when the force presses it in.
  5. Slide or topple, as in sand.py.
  6. Blocked: lose the approach velocity, with static friction when pressed.

  All of these use velocity relative to the neighbour, so particles flowing together (orbits) don't brake each other.
* **Super wells:** their core cells are marked in a per-cell `hole` map; a particle stepping (or sliding) into one
  is removed and its mass added to the well. Particles plus super wells always conserve total mass.
* **Sleep:** a particle that is blocked and slow, or free with no force, stops being simulated until woken.

Tunables are in `sv/config.py`.

## Known limits

* It is a grid model. Clumps behave like sticky granular piles, not rigid bodies, so two separate clumps don't drift
  together under a weak mutual pull. Strong wells still pull and tear them.
* A merged particle still fills one cell however heavy it is. Colour shows mass on a log scale.
* Children lean is off by default. For a mass-1 particle it is a random push about as strong as a distant
  well's pull, which makes orbits wander.
