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
python main.py --cpu               # one core, no GPU: exactly as before acceleration (see below)
python -m pytest                   # physics invariants
```

Everything is controlled from the menu behind the button in the bottom-right corner (or Tab): sliders for values
that scale, ON / OFF switches, buttons for choices, and an (i) beside each that explains what it does. The sliders
also have ◀ ▶ arrows beside their value for fine steps (0.1 for gravity strength, rotation speed and super-well spin;
1 for speed and brush size), which repeat while held. Each setting
shows its figures beside it (the step time by the speed, the collapse threshold by collapse, and so on); the rarely
needed settings and the performance figures fold away under Advanced. The mouse tool section picks what a left click
does: pour, ghosts, erase, place a star / repulsor / super well / spawner, select (and drag) a body to see and change
it, or delete one. Every setting also has a keyboard shortcut: **H** lists them. F1–F4 load the presets (rain, disk,
cloud, binary). The disk (the starting scene) is heavy: 20 million mass (`DISK_MASS`; less in a small window, where
no particle can be heavier than `MAX_MASS`) in particles of every mass from 1 to a few thousand, spread evenly over
the orders of magnitude, filling 60% of its ring (`DISK_FILL`). That is enough for several super wells to grow to
the supernova mass without any one of them holding most of the universe. The number of particles, the tick rate (ticks per second) and the frame rate always show in the
top-left corner, and the CPU use (the machine's, and the simulation's share of all its cores), the GPU use and all
the mass in the universe (particles, ghosts and what super wells hold) in the top-right one, or under the status line
while the menu is open. The GPU figure is Windows' own (the busiest engine type, all processes, as Task Manager shows
it), read by a `powershell.exe` left running in the background (`sv/usage.py`); without one it shows n/a. The app
starts with gravity at ×0.6 reaching 20 cells, rotation at 3 cells/tick, a 40 px brush and pour mass 4 (`sv/config.py`;
the tests pin the tuning they were written for in `tests/conftest.py`). The menu is `sv/menu.py`, built on the small
widget kit in `sv/ui.py`.

* **Stars:** a star is a ball of ordinary particles held together by its own gravity, layered by mass: heavy matter
  sinks to its core and light matter floats in its envelope. G (or the Star tool) places one filling exactly the
  brush circle: its core (the inner 40%) is made of particles of the pour mass (a random pour: random masses in its
  range), the middle layer of 3/8 of that and the envelope of 1/8 (at least 1; `STAR_PLACE_LAYERS`), so the pour mass
  sets what it is made of and how heavy it is. With the default 40 px brush, pour 1 makes a 1,257-mass star and pour
  64 a 27,744-mass one, all holding together; pour 256 packs about 100,000 into the core, past the collapse threshold,
  and it collapses into a super well within a few ticks (a bigger brush spreads it out). `,` / `.` rebuild it
  lighter or heavier, its radius × √(mass factor), each ring holding particles as heavy as it does now. Shift+click
  with the Star tool, or any placement with the menu's "Stars arrive as ghosts" on (`GHOST_STARS`), places a ghost
  star instead: its particles fly together through everything, feeling gravity, and land as a star `GHOST_TICKS`
  (180) later where it got to; any whose cell is taken land nearby as ordinary particles, and a super well's core
  swallows one whole. A small dot marks its centre of mass and a faint ring in its colour
  (red-orange when light, through yellow and white to blue-white when very heavy) its capture ring.
  * *What belongs to it:* every tick its particles are found again: those inside its capture ring that are bound to
    it, moving slower relative to it than its escape speed there. Matter it captures becomes part of it, and matter
    that is flung out or flies past doesn't. The ring is where its pull drops to `STAR_CAPTURE_ACCEL`, cut down to
    its Roche lobe against each other star and super well, so a heavier neighbour's tide takes its outskirts.
  * *Gravity:* a star pulls as a point of its particles' total mass at their centre of mass, softened over
    `STAR_SOFTENING` × its radius, whether self-gravity is on or not. Its particles are left out of the self-gravity
    mesh, so nothing is counted twice, and they always feel the mesh, so a star is pulled back by the matter it
    pulls. Its own pull doesn't press a particle into the one of the same star it rests on (that is the star's
    pressure), so a star keeps its shape while outside pulls, tides included, still act on each particle.
  * *Motion:* a star moves as one body. Once it has gone half a cell, all its particles are carried a cell at its
    body's velocity, and the particles only move themselves as fast as they move relative to it: falling in,
    shocked, or stretched by a tide. Collisions involving a star's particles keep their momentum.
  * *Collisions:* where two stars touch faster than `STAR_SHOCK_MIN`, the matter in the contact (as deep into each as
    they move relative to each other in a tick) is shocked: it splashes out sideways at up to their relative speed
    and stays only if it is still bound. A grazing touch shaves their surfaces; a head-on crash scatters much of
    both, and what stays bound is recaptured. Stars that touch gently, or whose centres meet, merge.
  * *Instability:* a star that has lost more than half of the most it held lately (`STAR_UNSTABLE_SHARE`,
    `STAR_PEAK_HALF_LIFE`), or is lighter than `STAR_MIN_MASS`, can't hold together. Touching another star, it merges
    into it, and the remnant is judged the same way. With a heavier body's tide reaching into it (a much bigger star
    or a super well), it is torn apart and its particles stream away. Otherwise it explodes like a small supernova:
    its particles leave as debris riding a shock front out to `STAR_BLAST_REACH` × its size, which shoves what it
    passes.
  * *Black holes:* a star near a super well is stripped by its tide, torn apart, and its particles swirl into the
    core. A star heavy and dense enough to hold `COLLAPSE_MASS` in a collapse window collapses into a super well
    itself, like any other matter.
  Shift+drag pulls a star along, X deletes the nearest one with its particles, and `,` / `.` make it lighter or
  heavier: it is rebuilt where it is, moving as it was, as a star placed at its new mass would be. Hover a star to see its mass, particles, radius, ring and how much of its recent mass it holds.
  The menu counts the stars formed, exploded and torn apart.
* **Repulsors:** Shift+G places a repulsor weighing the brush circle's area × the pour mass × `WELL_DENSITY` (64): a
  solid, spinning body that pushes instead of pulling and stays put. Its size follows its mass (the brush at pour
  mass 1, bigger for heavier pours), and `,` / `.` resize it with its mass, so its body and reach match a fresh one's. Particles can't enter it; they bounce off and slide round its surface. (A solid attracting
  well with the same body can still be made in code with `World.add_well`.) Shift+drag moves it, X deletes it.
* **Star formation:** every 60 ticks, the densest knots of matter (up to 12, `STAR_FORM_SEEDS`) are checked, and a
  knot that looks like a young star becomes one: its particles, where they are and moving as they move, become the
  star's. A knot is the largest disc round a dense spot that is at least 80% packed, between 4 and 30 cells in radius
  (about 50 to 2,800 particles), where the packing ends; it may be part of a larger body, such as an arm of a disk. It
  must be layered: a heavy core inside a lighter envelope, the core's typical mass at least 2× the envelope's (a
  smooth gradient counts), with most of each side's particles on its own side of the divide. It must hold itself
  together: weigh at least 2× `STAR_MIN_MASS`, with 80% of its mass bound to it (`STAR_FORM_BOUND`). No star forms
  within 8 cells of a star's capture ring, of a repulsor or three times its radius, near a super well's core, or
  against a solid border (a pile on the floor isn't a star), and at most one forms per check. See `STAR_FORM_*`. Scenes
  of one particle mass (like the cloud preset) can't form stars, since nothing is layered.
* **Super wells:** B places one (as heavy as a brush-sized well, and never lighter than the collapse threshold). It
  is a tiny black core that deletes every particle, repulsor and super well touching it and adds their mass to its own. Its pull
  grows with that mass and follows the same law as every other mass, fading with distance (see Gravity reach). Inside its dotted circle it
  whirls everything round the way it spins (`SUPER_SWIRL_*`), at full strength right out to the circle (it fades in
  only over the outer 15%). Nothing inside sleeps or rests on friction, so matter keeps circling unless other
  matter blocks its way, and spirals in over several turns. Its spiral arms show which way it spins, turning faster and brighter the faster it
  spins. `;` / `'` spin the nearest super well slower / faster (up to `SUPER_SPIN_MAX`, 7). One placed with B starts at spin 1.5
  (`SUPER_SPIN_PLACED`), and one formed by collapse at 1.5 (`SUPER_SPIN_NATURAL`). A new one spins the same way as the
  global orbit when that is on, and either way at random when it is off. Above spin 1 it whirls
  matter faster than it would orbit and flings it out into a ring instead of drawing it in: spin makes no difference
  to how fast a well feeds up to 1, 1.5 slows it a little, 3 roughly halves it and 5 cuts it to a third. With
  "Spin rises with mass" on (`SUPER_SPIN_FOLLOWS_MASS`, off by default) a new well's spin climbs in a straight line
  with its mass from 1.5 to 3 at the supernova mass (`SUPER_SPIN_FULL`), so it feeds ever more slowly as it grows.
  In tests on the disk that gave fewer explosions (about a third as many) but none set off by a neighbour's blast,
  and more regular lifetimes. Setting a well's spin by hand stops it following its mass. When two super wells' dotted circles overlap, they are drawn
  together, slowly at first and ever faster as they near: the pull between them grows as their distance shrinks
  (`SUPER_MERGE_ACCEL`, up to `SUPER_MERGE_MAX_SPEED`, 3 cells/tick), and their motion round each other fades
  (`SUPER_MERGE_SPIRAL`), so they spiral in and merge within a few seconds. The lighter one covers more of the gap.
  The merged well spits out 0.2–2% of their combined mass as particles (`MERGE_EJECT`), taken mostly from the smaller of the two
  (`MERGE_LOSS_BIAS`). A merger also sends out a shock: a front runs out to 1.5× the merged well's range
  (`SUPER_MERGE_SHOCK_REACH`), starting at 6 cells/tick so it outruns what is falling in, and moving with the well.
  Behind it a wind keeps everything moving outwards at 7 cells/tick (`SUPER_MERGE_SHOCK_KICK`), faster than the
  well, self-gravity and the global rotation pull it back, for 90 ticks in all (`SUPER_MERGE_SHOCK_TICKS`). So a
  merger in the middle of a lot of matter sweeps it out into a shell instead of swallowing it: in tests about
  three quarters of the matter in its range was gone within 45–90 ticks, and the well didn't grow while the wind
  blew. Then the matter falls back. A merged well can't go supernova for 120 ticks
  (`SUPER_MERGE_GRACE`) even if it is over the limit, and neither can one that has just got over the limit any
  other way (swallowing matter or another supernova's debris, or fed by a collapse): it always has 120 ticks from
  the moment it gets too heavy. Further mergers within that window don't stretch it. A super well that reaches the supernova mass (the menu's Supernova at, in steps of 0.5M; `SUPER_EXPLODE_MASS`, 10,000,000 at start) goes
  supernova: it vanishes and all of its mass leaves its spot as very heavy debris (ghosts of about 3,300
  mass, `SUPER_BLAST_HOT_MASS`) behind a shock front that starts at 6 cells/tick (`SUPER_BLAST_SPEED`) and slows to
  a halt 225 cells out (`SUPER_BLAST_RADIUS`, at most 45% of the shorter side). The debris expands with the front
  like a real remnant, each piece moving at its own share of the front's radius × the front's speed, its share
  spread from 15% to 100% (`SUPER_BLAST_FILL`) so it comes to rest evenly over the area the front swept, not piled
  on its rim. The front shoves every particle it
  passes outwards, those near the middle about 60 cells (`SUPER_BLAST_PUSH`), less further out and nothing at the
  edge, then they come to a stop (`SUPER_BLAST_DRAG`), leaving a clear cavity and a pile-up shell. The debris cools as it
  flies: every 20 ticks from age 20 each piece over 400 mass breaks in two, the new piece about 1.5 cells away
  (`SUPER_BLAST_SCATTER`) so they spread out rather than stack up, ending as about 17,000–30,000 pieces of 200–400
  mass. Each lands as an ordinary particle where it is as soon as it is cool and has stopped (see Ghosts for how). Collapse is paused for 180 ticks (`SUPER_EXPLODE_CALM`) so the
  debris can spread before dense parts of it collapse again. Repulsors, super wells and spawners aren't pushed.
* **Collapse** (Shift+B, on by default): every 8 ticks, the heaviest 20×20-cell window collapses into a super well
  (or feeds one close by) once it holds `COLLAPSE_MASS` (5,000). The new super well keeps the matter's momentum and
  spits out 10–30% of it. Ejected particles have random masses (`EJECT_MASS`) and leave at 1.2× the speed needed to
  escape its range, so they get out unless something stops them.
* **Spawners:** F places a particle spawner the size of the brush circle, pouring ghost particles (see Ghosts;
  `SPAWNER_GHOSTS`) at the current pour mass (or random range), so they don't pile up and collapse at the spawner. It pours as densely as the brush does by hand: `SPAWNER_RATE` (= `POUR_CHANCE`, 0.25)
  particles per tick per cell of area, about 110 per tick for the default brush. (The brush pours per frame, so at
  speeds above 1 tick per frame a spawner pours more per frame than the brush.) A spawner has no collisions, so it passes through particles and stars. It falls under
  every kind of gravity like a particle, and a super well's core deletes it. Shift+F places a locked spawner that
  stays exactly where it is put and ignores gravity. Shift+drag moves spawners, and X deletes the nearest.
* **Continuous borders:** W makes the edges wrap: a particle leaving one side enters from the opposite one. Gravity
  reaches across the seam too (wells pull the shortest way round, and self-gravity becomes periodic), and wells and
  spawners wrap as well. Only for the window-shaped universe: turning it on makes a round one the window again.
* **Round universe:** U (or the menu's Shape) makes the universe a disc centred on the window, reaching past its
  corners (`ROUND_RADIUS` × half the window's diagonal), instead of the window's rectangle. Anything the global
  orbit carries off one edge of the window goes on round its circle out of sight and comes back in on the far side,
  as if the universe really turned, where wrapping borders would bring it in on the opposite edge going the wrong
  way. Outside the disc is solid rim moving with the orbit, so matter flung out slides round it rather than piling
  up; wells and spawners are kept inside. The disk, cloud and binary presets are round, rain is the window. A round
  universe has about twice the cells (600 × 600 for a 960 × 720 window at 2 px): on the disk scene a tick took about
  23% longer than the same particles in the window's rectangle (17.0 against 13.8 ms) and drawing 0.3 ms more.
* **Camera:** ctrl+wheel or Z / shift+Z zoom out / in at the mouse, from where the whole universe fits the window
  up to `ZOOM_MAX`; middle drag or alt+drag pans; R goes back to 1× centred and shift+R fits the whole universe
  (also in the menu). This is a camera, not the square size: the simulation is unchanged, and zoomed out past a
  pixel per square the image is averaged. The brush and placed bodies keep their size in the universe.
* **Global orbit:** O cycles off / clockwise / counterclockwise, and K / L make it slower / faster. It starts
  turning the edge of the window (half its shorter side out from the centre) at 3 cells/tick (`ORBIT_EDGE_SPEED`),
  whatever the window size or universe shape, and resizing keeps that speed. Everything,
  wells included, is brought round the centre of the universe, faster the further out it is and never slower than
  `ORBIT_MIN_SPEED`, so nothing comes to rest. Each thing gets exactly the inward pull its own circling needs, so
  nothing slow is dragged to the middle, plus a nudge towards the orbiting speed (`ORBIT_GRIP`). Particles are
  processed front-first along the flow so moving groups don't jam.
* **Gravity strength:** `<` / `>` scale all gravity (global direction, wells, super wells, self-gravity). The
  collapse threshold is divided by the same factor, so stronger gravity collapses sooner.
* **Gravity reach:** every pull (stars, wells, repulsors, super wells, self-gravity; not the uniform direction or
  the global orbit) fades with distance: it is the inverse-square pull × (1 + d/R) e^(−d/R), d the softened
  distance and R = `GRAVITY_REACH` (20 cells at start; the menu's Reach slider, 10–400, or all the way right for no
  fading). Close in it is as strong as ever (95% at R/4, 74% at R), but at 3R only 20% is left and at 6R 2%, so
  things have to come near each other to interact strongly and a heavy body can't run the whole universe. The
  potential fades the same way (e^(−d/R)), so escape speeds are lower too. A super well's reach, and with it its
  dotted circle, is where its faded pull drops to `SUPER_RANGE_ACCEL`, so it now grows only slowly with mass: at
  gravity strength 1 the circle's radius is 20 cells for a 50,000 well (25 unfaded), 47 for a 1M one (112) and 70
  for a 7.5M one (306). Its softening stays what it would be unfaded, so close in it pulls as before. Stars' capture rings shrink the same way, and a faraway companion's tide on a star
  fades even faster (× e^(−x)(1 + x + x²/2), x = d/R), so stars are only torn apart by what comes close. One
  consequence of a pull that fades this fast: circular orbits further out than about 1.6 R aren't stable (anything
  there drifts in or out).
* **Ghosts:** Shift+click pours ghost particles (Shift+click on a well or spawner still drags it). For
  `GHOST_TICKS` (180, 3 seconds) they feel every kind of gravity except each other's, but collide with nothing,
  passing through particles, stars and each other. They aren't counted in self-gravity or collapse, so a big pour
  can't turn straight into a super well. Then each lands as an ordinary particle where it is: in a random free cell
  of the nearest ring of cells round it with room, within 3 cells (`GHOST_LAND_NEAR`), so a crowd landing together
  spreads out evenly. With no free cell that close it merges into the lightest particle there that has room under
  `MAX_MASS` (keeping momentum, like a merging collision), and with neither it stays a ghost and tries again every
  tick. Only after 600 ticks of that (`GHOST_LAND_PATIENCE`) may it land in a free cell further away, so matter
  doesn't pop up far from where it was. Ghosts have no pressure, so a crowd of them can fall into a dense knot;
  that knot usually collapses into a super well, which swallows them. A super
  well's core always swallows them. They are drawn see-through.
* **Particles:** S toggles self-gravity, and M / P toggle merging / splitting (both on by default). Loose particles
  that collide bounce off at a random angle of up to `COLLISION_SCATTER` (0.3 rad, about 17°) from straight back, as
  if they met a little off-centre, so a stream glances off what it hits instead of piling up in a line behind it
  (momentum is still conserved; resting contact and stars' particles are unaffected). Advanced → Particles has a
  slider for it. Keys 1–5 pour a
  fixed mass, and 6 pours particles with a random mass between the min and max of `RANDOM_MASS` in `sv/config.py`.
* **Radiation (heat):** on by default (menu: Stars and black holes). A merge or split loses `HEAT_SHARE` (1%) of the
  mass involved, rounded at random so it averages out, taken from the particle's children; the particle step notes
  each loss (per strip on all cores, `kernels._shed`) and the World sends it out as up to `HEAT_PIECES` (4) light heat
  particles: ghosts tagged `kernels.HEAT_TAG`, drawn bright yellow, flying off `HEAT_SPEED` (6 cells/tick) faster in
  random directions and landing as ordinary light particles `HEAT_TICKS` (40) later. On the way, a heat particle
  still faster than `HEAT_MIN_SPEED` against the free particle in its cell hands it `HEAT_COUPLING` (half) of a
  head-on elastic collision's momentum and slows by as much (`kernels.heat_push`): a light particle is blown away, a
  heavy one barely moves and soaks the heat up. Stars fuse (`kernels.star_fuse`): each of a star's particles of mass
  `FUSION_LIGHT` (16) or less meets a light neighbour of the same star with `FUSION_CHANCE` per tick, and the two
  become one heavier particle that sinks into the core, losing `FUSION_HEAT_SHARE` (5%) as heat. Heat passes through
  stars' own particles, so it blows a wind of light matter away from a star instead of tearing it apart. No mass is
  lost: heat is mass, carried off as light particles. The heavy disk starts hot (over 1,000 heat particles a tick as
  it first collapses, when merges and splits run near 1,000 a tick each) and settles to about 12 a tick within
  1,000 ticks; on the disk a tick took 13.4 ms against 11.1 without radiation.

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

## All cores and the GPU (`World.accelerate`, `sv/gpu.py`)

By default the work is shared out over every CPU core, and over the GPU where that is faster:

| job | `--cpu` | default |
|---|---|---|
| the particles' tick (`kernels.step`) | one core | all cores, in strips (`step_tiles`) |
| ghosts | one core | all cores, or the GPU |
| the wells' field | all cores | all cores, or the GPU |
| re-ranking the processing order, waking round moved wells | one core | all cores |

* **Strips.** A particle reaches at most `MAX_STEPS` + 1 cells in a tick, so the universe is cut into strips at least
  2 × (`MAX_STEPS` + 2) thick (`STRIP_SIZE`); every other strip runs at once, then the rest. With global gravity
  pulling up, down or diagonally they are strips of columns (at least 64 wide), so a falling stream stays inside its
  strip and keeps its leading-particles-first order; otherwise strips of rows. They start somewhere new every tick,
  so no edge stays put. This processes particles in a slightly different order than one core does, so a run differs
  in its details and a `--seed` no longer repeats it exactly; the physics is the same (in rain the counts of moved,
  colliding, merging, splitting and sinking particles match the one-core run within the spread between seeds).
  Ghosts, the order re-ranking and waking give exactly the same results on all cores.
* **The GPU** runs through [wgpu](https://github.com/pygfx/wgpu-py) (WebGPU), so it works with any vendor's GPU
  through whatever the machine has: Vulkan, Metal, Direct3D 12 or OpenGL. The best adapter is picked: discrete
  before integrated, native APIs before OpenGL, never a software one (llvmpipe, WARP, ...); `--gpu-name NAME` picks
  one by name. It takes the ghosts and the wells' field (float32 ports of those kernels); the particles' tick can't
  go there, since each particle's move depends on the ones before it. Copying data to and from the GPU can cost
  more than the GPU saves (on an integrated GPU, and especially under WSL), so each job is timed both ways as it
  runs, every 900 calls and whenever its size halves or doubles, and the faster way is kept. `--gpu` always uses the
  GPU instead; `--no-gpu` leaves it out. The menu's Advanced → Performance shows where each job runs.
* **WSL** reaches the GPU only through Mesa's Direct3D 12 driver (OpenGL), which Mesa doesn't pick by itself, so
  `sv/gpu.py` sets `GALLIUM_DRIVER=d3d12` (and prefers an NVIDIA GPU when one is passed through) unless those are
  already set.
* Without `wgpu` installed (`pip install wgpu`, in `requirements.txt`) or a hardware GPU, it runs on the cores.

On the Ryzen 5 PRO 5650U (6 cores, 12 threads, integrated Radeon graphics), ms per tick:

| scene | `--cpu` | default |
|---|---|---|
| rain, 960×720 (1 px) | 6.5 | 3.5 |
| 955×492 cells, ~32k particles + 58k ghosts, 8 super wells (like a disk after a while, with a spawner) | 35 | 19 |

Here the GPU loses to the cores at both of its jobs (an integrated GPU, with its copies going through WSL's
OpenGL-on-Direct3D 12 layer), so the timing keeps them on the CPU. Where a GPU is faster, typically a discrete one
reached natively, the timing hands it those jobs.

## Physics model (`sv/kernels.py`)

* One particle per cell. Each has a float velocity and a sub-cell offset, so speeds below one cell/tick still move it.
* **Forces:** cached field from wells and global gravity, plus self-gravity (particle-mesh: mass is binned into
  4×4 blocks, the potential comes from an FFT convolution, refreshed every 4 ticks), plus the stars' pull (summed at
  8×8 block centres and blended, exact near each star, refreshed every tick). The wells' field is summed at 4×4
  block centres and blended, exact within 3 softening lengths of each well (16 to 72 cells, `FIELD_NEAR` /
  `FIELD_NEAR_MAX`: a super well's soft pull is smooth enough to blend beyond that), built on all cores, plus optional children lean (J).
  Every one of those pulls, and the potentials, fade with distance as `kernels.fade` says (see Gravity reach); the
  self-gravity kernel is the faded softened 1/r.
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
* **Stars:** a per-cell `owner` map says which star each particle belongs to (`update_stars`); `star_shift` carries
  a star's particles a cell at a time, front first, and `star_shock`, `star_sink` and `star_motion` handle contacts,
  layering and its body's velocity.
* **Super wells:** their core cells are marked in a per-cell `hole` map; a particle stepping (or sliding) into one
  is removed and its mass added to the well. Particles plus super wells always conserve total mass.
* **Global rotation:** each particle is nudged towards circling the centre (`orbit_accel`). A jammed particle counts
  as turning with the universe rather than standing still, and packed blobs (`BLOB_MIN`+ touching particles of no
  star, not spread over more than `BLOB_MAX_RADIUS`, outside super wells' ranges) are carried round as a whole each
  tick at the rotation's velocity at their centre of mass (`find_blobs` / `carry_blobs`, like `star_shift`), their
  particles moving only relative to the blob: moved a particle at a time, a self-gravitating clump can't keep up,
  since its gravity pulls its particles into the gaps the first ones leave. The self-gravity mesh, binned every 4
  ticks, is read where the matter was when binned, turned back by the angle the universe has turned since
  (`sg_block_at`), so a clump isn't pulled back to where it was.
* **Sleep:** a particle that is blocked and slow, or free with no force, stops being simulated until woken.

Tunables are in `sv/config.py`.

## Known limits

* It is a grid model. Clumps behave like sticky granular piles, not rigid bodies, so two separate clumps don't drift
  together under a weak mutual pull. Strong wells still pull and tear them.
* A merged particle still fills one cell however heavy it is. Colour shows mass on a log scale.
* Stars bring matter together: massive clumps sink inward through a disk and merge, and a merger heavy enough
  collapses into a super well, so a disk scene evolves faster than it did with solid stars.
* The heavy disk collapses into 10–25 super wells within a few hundred ticks (its density is far over the
  collapse threshold everywhere). From then on the wells grow mostly by merging, and a supernova's debris often
  feeds a neighbour over the limit, setting off a chain. With gravity reaching 60 cells, no well's dotted circle
  got past about 67 cells in tests (up to 244 with no fading), and in 4,000 ticks the disk went through 14–17
  supernovas (3–6 with no fading), about 210 collapses (50–110) and nearly 60 stars formed (7–16). Most of those
  stars are still torn apart, though: the disk holds about 220 mass per cell, against 16 in a placed star, so close
  to the disk its pull (about 2 cells/tick² at its edge) is 40× a star's own, and its tide wrecks a star within
  20 ticks however far gravity reaches. A star dense enough to resist that is over the collapse mass and becomes a
  super well. Wells whose dotted circles don't overlap can settle in a stable arrangement and stop growing until
  something disturbs them. A universe that heavy also costs more to run: about 15–35 ms a tick at 960×720 and 45–50 ms at
  1920×990 (2 px cells), against under 10 ms for a light one, since nothing inside a super well's circle sleeps.
* Contacts between free particles lose momentum (that is the friction that lets piles settle), so after a perfectly
  symmetric head-on crash the merged star can recoil a little along the line of impact.
* Children lean is off by default. For a mass-1 particle it is a random push about as strong as a distant
  well's pull, which makes orbits wander.
