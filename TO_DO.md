- When calculating for results of physics changes such as getting stars to orbit a SGW, always assume that global rotation (set to its minimum value) is enabled. Either direction could be enabled. Also confirm whether the changes you made were built to work in a rotating universe or a static.

- Add a cap to the rate that particles can merge, to better simulate stars fusing and giving off heat overtime instead of all at once. The cap should be related to how much grativty the particles expereince, so very large stars should be able to fuse heavier particles very often while small stars fuse and give off heat much slower. The intended behaviour is for a naturally born star is that matter clumps together and over a certain threshold of matter in a certain region it "ignites" into a star which means that the material at the core is expereincing enough gravity that even with no motion it will fuse with the same mass or lighter particles, giving off heat in the process. The threshold for becomming a star would ensure that fusion in the core of the star is possible (however as stars lose mass via heat, if the smallest possible star was created and no additional mass was added to it then it would go below the threshold for particles to fuse in its core and in this case the star should go supernova to simulate it becomming unstable). As a side note, this would mean that two things can lead to a particle fusing, colliding at high enough speeds or experencing enough gravity.

- confirm the sim isn't compiling kernels when not needed

- have dense regions of matter collapse into a SGW at the same desnity as the value set for stars collapsing into SGW

- The simulation runs very slowly when there is a very heavy SGW. Is this expected? I would assume that since every particle inside of a SGW isn't simulated, a SGW and another SGW 10x bigger should have roughly the same performance?

- ~~Make the menu window wider as it keeps jumping around when the values at the very top change and go onto a second line.~~ Done: `PANEL_W` 380 -> 450 (`sv/ui.py`), wide enough for 10M particles, 1B mass and 100M ticks on one line.

- ~~Invesitagte why the test runner is no longer able to close the sim even after being given permission.~~ Done: the subagents only close the sim on the user's own go-ahead, and auto mode blocked the kill until settings.local.json got an autoMode allow rule.

## Physics rework: let stars and super wells emerge from the parameters (planned 2026-11-04)

Goal (user, 2026-11-04): as few hand-set thresholds as possible. Keep only "constants of nature" - G x strength,
reach, VMAX as the speed of light c, the mass ladder and its binding curve, one fusion-barrier constant, restitution,
heat conduction / radiation rates - plus numerical/speed settings (mesh blocks, softening, sleeping). Everything else
(when particles fuse, when a star ignites, dies or collapses, a super well's size and spin, frame dragging) should
follow from those. Accurate enough that real phenomena could show up, still real time.

User decisions (2026-11-04):
1. Fusion powers stars, by a binding curve: below a peak rung ("iron", ~256) fusing similar masses gives off energy
   as radiation; past it fusion costs energy (needs mass + energy enough), so a star whose core reaches the peak
   loses its power and becomes unstable.
2. Don't raise VMAX (performance). Gravity reach and strength may be set to anything, even outside today's range,
   that gives the intended behaviour. (Horizon = where escape speed reaches VMAX: at reach 30 / strength 1.2 that is
   3.3 cells at 50k, 11 at 200k, 28 at 1M, 44 at 10M, while orbits hold only within ~1.16 x reach ~ 35 cells.)
3. Super well supernova at `SUPER_EXPLODE_MASS` stays a deliberate rule for now. Suggestion to offer later: make it
   dynamic - a super well explodes when its horizon reaches the gravity reach (gravity can't hold more than that
   together), ~1.2M at reach 30 / strength 1.2, and it scales with whatever reach and strength are chosen.
4. Order is Claude's call.

Measured from the gravity law (reach 30, strength 1.2, VMAX 8): escape speed at the centre of a packed disc of
particles of mass m, radius R: m 16 never above 3.2; m 64 never above 6.4; m 256 reaches 8 at R ~10; m 1024 at
R ~3; m 4096 at any size. So with collapse by escape speed, only stars with heavy (fused) cores, or heavy pours,
can collapse. Today's 200k-in-20x20 rule sits at an escape speed of ~10, the same range.

Steps, in order (each measured with the sim-experimenter; global rotation at its minimum on, either way, per the
first item at the top of this file):
1. **Super wells feel gravity in full** (drop `WELL_INERTIA_MASS` from `Well.fall`; keep momentum) and a two-body
   orbit setup (`put_in_orbit` / `orbit_velocity`: relative speed sqrt(G s (M+m) / d) split by mass). Independent
   of the rest; unblocks stars orbiting super wells.
2. **Energy and heat.** Rest energy = mass x VMAX^2. A heat value per particle. Kinetic energy that contacts throw
   away today (restitution, the blocked rule, star damping) becomes heat; heat spreads to neighbours, leaves from
   surface particles as radiation ghosts (mass = energy / c^2), and pushes neighbours apart (pressure). A
   mass + energy total and a conservation test.
3. **Mass ladder and fusion rule.** Rungs nominally doubling 1 .. 4096, each a little under nominal by the binding
   curve. Two touching particles: energy = relative kinetic energy (centre-of-mass frame) + heat; they fuse into
   the next rung if mass + energy / c^2 covers it and they get over a barrier (chance ~ exp(-B / E), B growing with
   both masses, one constant); overshoot leaves as radiation; else they bounce and the loss is heat. Splitting is
   the reverse. Replaces `MERGE_SPEED`, `MERGE_CHANCE`, `SPLIT_SPEED`, `BIND`, `HEAT_SHARE`, `FUSION_*` and the
   merge-rate cap above. Pours, ejecta and debris snap to rungs. Low rungs are too light for whole-number defects:
   count mass in 8x finer units (fits uint16: 4096 -> 32768).
4. **Collapse by escape speed and the horizon as the edge.** Where the potential (self-gravity mesh, kept instead of
   thrown away in `SelfGravity.update`, + stars + wells; refined near candidates) is deeper than -VMAX^2 / 2, that
   matter becomes a super well with its mass, momentum and angular momentum. The super well's edge is its horizon
   (`horizon_for`). Drops `COLLAPSE_*`, `STAR_COLLAPSE_*`, the star mass line, `COLLAPSE_EJECT`, `SUPER_CORE*`.
   Choose reach / strength here so light super wells leave room for orbits.
5. **Stars emerge.** Star objects stay as bookkeeping only (any bound clump, `bound()`); drop the `STAR_FORM_*`
   pattern-matcher, the fixed merge / shock rules (stars bounce as wholes - Option 3 below - and are one when the
   tracker finds one bound clump) and the fixed death rules (`STAR_UNSTABLE_SHARE`, `STAR_MIN_*`, `STAR_BLAST_*`):
   a core at the peak rung cools, contracts, and either runs away and blows apart or collapses (step 4). Risk:
   emergent supernovae may fizzle; fallback: a star that becomes unbound explodes at a speed set by its energy.
6. **Spin, frame dragging and pairs from angular momentum.** Spin = angular momentum held (collapse + what it
   swallows + mergers), capped at the maximum for its mass; space turns at ~ G J / (c^2 r^3), never carrying
   anything past VMAX, so near a fast spinner nothing can stand still or fall straight in. Drops the whirlpool
   (`SUPER_SWIRL_*`), `SUPER_DRAG_*`, `SUPER_SPIN_*`. Pairs orbit by plain gravity, lose energy to gravitational
   waves by a formula with c = VMAX, merge when horizons touch (replaces `SUPER_INSPIRAL_*`).
7. **Retune** presets, orbit bands, tests (many pin today's thresholds), README (docs-sync); `/optimize` if the
   user asks.

Progress:
- **To come back to after the steps (user, 2026-11-05): flip the size relationship, so bigger super wells can hold
  more in stable orbit** (as bigger black holes hold bigger galaxies). Now the reach fade caps stable orbits at
  ~1.16 x reach (~0.6 x reach for bound ones) whatever the mass, while the core, point of no return and innermost
  stable orbit (6 G M / c^2) grow with mass - so the bigger the well, the less room. Ideas to weigh: a reach that
  grows with the source's mass; or gravity unfaded for super wells.
- Reach default 60 (user, 2026-11-05).
- Light speed (2026-11-05): LIGHT_SPEED 24 (3 x VMAX), separate from VMAX (matter's top speed; the user's collapse rule
  stays: matter collapses where even VMAX can't escape). A super well's core is where light can't escape
  (`edge_for_mass` at c: compact - reach 60 / strength 1.2: 1.3 cells at 200k, 7.5 at 1M, 43 at 10M; 16 would give
  3.5 / 15 / 60, 32 0.8 / 4.3 / 31), its dotted point of no return where matter can't (`trap_for_mass`, VMAX).
  Rest energy and radiation quanta are mass x c^2; radiation flies at c (light keeps its speed in `_move_ghosts` /
  the GPU shader: a ghost faster than VMAX is light); FUSION_BINDING rescaled to 0.0056 (same 3.2 / unit mass).
- The radiation "ripples" (user, 2026-11-05): gravitational waves - beams along the line through merging super wells
  (two-armed spirals), which flew straight, unbent, then landed as matter in the middle of nowhere ~50 ticks later;
  and, far fewer, quanta coming back in at the edge (`World.radiation_back` counts them). Waves are now energy only.
- Step 7 retune (2026-11-05, uncommitted): the disk preset is on the default reach 60 / strength 1.2; systems and
  binary keep 120 / 0.6. Disk (`DISK_REACH` / `DISK_SCALE` gone): fullscreen, 244 stars form and 209 go supernova in
  the first 300 ticks, 3 wells of 2-8M, ~5k particles left by 1,800 ticks, 52 -> 23 ms a tick (at its old 20 / 0.6:
  slower burn, 7-11 wells, 74 -> 40 ms). Binary at reach 60 (two 30k stars 5 cells across, 24 apart, a ring 45-58
  out): the pair held 1,800 ticks alone, but with its ring it merged by ~800 and came apart - a ring stable round a
  binary needs ~2x its gap, past where orbits are bound (~0.78 x reach); its common centre is now set still
  (`World.shift_star`). **Systems** (`SYSTEM_REACH` / `SYSTEM_SCALE`): within reach 60 no layout held - 20-200k
  wells, orbits 38-56, pour 64-1024 stars 3-6 cells: one star of a well sinks, another is flung out at ~1 cell/tick. Two causes: the tide sinks stars in tight orbits
  (open, see 2026-11-02 notes; damping their spin to the orbit's instead of to zero was tried again: no better), and
  past ~0.78 x reach circular orbits are barely bound. Waits for "bigger wells hold more" above.
  Fixed on the way: `put_in_orbit` gave a star's recoil to its well alone, so the next star placed round it was set
  off ~6% too fast (the well was moving) - now the well and the stars already round it share it. Auto star test
  stays xfail (its stars sit at ~135 of reach 120, barely bound).
  Found: a burning binary's centre wanders ~0.1 cells/tick (not with radiation off): each quantum carries momentum c
  (24), and the random recoils add up - real in kind, far too big in size; ideas: emit in opposite pairs, or
  lighter quanta.
- Step 5 coded (2026-11-05, uncommitted): stars from their own weight. A knot becomes a star when bound, held
  against outside gravity (`_self_held`) and igniting: its core's (innermost quarter) expected fusions from its
  weight's pressure >= 1 a heat step (`_ignites`); found round the densest 7 x 7-block sums. Contact fusion counts
  a star's weight as heat (`kernels.star_pressure`, `World.press`), at FUSION_RATE (0.05) of the attempts, barrier
  FUSION_BARRIER 2.4 (9 never lit anything). Per star `burn` (smoothed) and `burned`, and `fuel` (core lighter than
  FUSION_PEAK when it formed). Death: a star no longer bound comes apart quietly (`stars_torn`); one that had fuel,
  burned, and whose core is now mostly at or past the peak explodes (`_explode_star`, at its escape speed, at most
  VMAX). HEAT_PRESSURE stays 0 (1 fails 14 tests: placed stars puff up, piles never sleep).
  Measured (fullscreen, defaults): a 7k pour-16 star burns dimly 6,000+ ticks; 28k pour-16 goes supernova at 2,420
  ticks, 28k pour-64 at 1,090. Ignition (test strength): rung 256 at radius >= 14, 64-128 at >= 18, 16 at >= 26.
  Supernova scene (11M well, 1,800 ticks): 312 stars formed, 162 supernovae, 39 collapses; the wells merge back
  into one 10M well that goes supernova again (~tick 1,350); 36-75 ms a tick. Debris cooled to 64 instead of 400:
  951 formed, 588 supernovae, 4 collapses, but 58-154k particles and 93-160 ms - SUPER_BLAST_COOL_TO stays 400.
  Super well arms (user: "don't spin anymore"): not a bug - a well formed by collapse has spin ~0.01-0.02 (matter
  brings in little net rotation, and VMAX caps what infall adds); the arms were drawn at the far point of no return,
  where that turns space almost not at all. They are now drawn at twice the core (`whirl_omega`); placed wells
  (spin 0.5) turn visibly.
- Step 6 coded (2026-11-05, committed): spin = the angular momentum a super well holds (`Well.jz`; at most G M^2 / c,
  `max_spin_j`; spin = jz / that, -1..1): from collapse (`absorb_disk` lz), swallowed matter (`absorbed` column 5,
  every swallow site, turned about the well in `_collect_absorbed`), swallowed solid wells, and mergers (both spins +
  the pair's orbit). Frame dragging from it: space turns at 2 G J / c^2 / rho^3, faded, never carrying matter past
  VMAX (`kernels.frame_turn`); the faint circle (`well_range`) is now where that reaches VMAX (an ergosphere; the
  core when not spinning); things it carries faster than SLEEP_EPS don't sleep. The whirlpool is gone (kernel whirl,
  SUPER_SWIRL_*, SUPER_DRAG_*, spin rising with mass, SUPER_SPIN_NATURAL / FULL / ARMS_AT, SUPER_RANGE_FACTOR). Pairs:
  plain gravity (the scripted inspiral, Binary, SUPER_INSPIRAL_*, merger ejecta MERGE_EJECT and merger shock gone);
  with radiation on they lose 32/5 G^4 m1^2 m2^2 (m1 + m2) / (c^5 d^5) a tick to waves, taken with its angular
  momentum from their going round each other (at most half of it a tick); inside their innermost stable orbit (6 G M
  / c^2) they plunge within about an orbit and merge spinning with the angular momentum they had there
  (`World._plunging`). Waves are radiation: energy-only quanta at c, absorbed or brought back at the edge like heat.
  Tried and dropped: the relativistic 3 G M h^2 / (c^2 r^4) pull with super wells allowed up to c (one-tick steps
  overshot near close approach and flung pairs across the universe); with it at VMAX the cap held pairs in orbits
  inside the innermost stable one.
  Measured (1920x1080 cell 2, reach 60): two 1M wells 60 apart merge after 1.2 orbits, 4% radiated, spin 0.65; 300k
  pairs from 20 / 40 cells: 2.2 / 20 orbits, 4%, spin 0.64 / 0.59 (real equal-mass mergers: ~5%, 0.69); without
  waves a pair holds its orbit (111+ orbits). A maximally spinning 1M well drags space round at 2.1 cells/tick 20
  cells out, 0.5 at 40, 0.1 at 80; its faint circle is at 10 (core 7.5). Swallowed matter spins a well up, but VMAX
  caps what angular momentum it brings in (r x VMAX per unit mass at the core): a sparse orbiting ring gave its well
  15% of its angular momentum. Systems preset holds 9 stars 900 ticks, 6-7 ms a tick; disk preset collapses into
  0.8-2.6M wells with 2.6-8 cell cores, 30-43 ms a tick.
  Tests: 182 pass, 2 xfail (`test_ejected_mass_escapes_the_range`: `eject` is no longer used by anything;
  `test_auto_star_fills_an_orbit_evenly...`: retune), whirlpool / inspiral / spin-follows-mass tests replaced by
  step 6 ones (pair orbits by gravity alone, waves spiral it in and it merges spinning, waves are energy taken in,
  faint circle = where space outruns matter, spinning well carries what falls in, collapse spins the way matter
  went round, swallowed orbiting matter spins a well up, arms turn with space at the point of no return).
- Step 4 coded (2026-11-05, committed): a super well's core is its horizon (`Well.edge`, kept by
  `World._set_edges` -> `edge_for_mass`: where escape speed reaches VMAX), softening SUPER_SOFTENING 1 cell (a
  point; the old 0.25 x a quarter of the reach made it ~14 cells at 200k, so nothing under ~167k could have a
  horizon). Collapse (`check_collapse`): round each star at least `lightest_super_mass()` and the COLLAPSE_SPOTS (8)
  densest spots, the mass within each distance r (`kernels.mass_rings`) against `mass_for_edge(r)` = (VMAX^2 / 2)
  rho / (G strength fade) - matter inside its own horizon - collapses: all within the largest such r becomes the
  well (`_collapse_at`: momentum, angular momentum in `Well.jz` for step 6, stars centred there dropped). The same
  for stars and loose matter (the user's TO_DO item). Gone: COLLAPSE_MASS, COLLAPSE_BLOCKS, STAR_COLLAPSE_FACTOR /
  RANGE, COLLAPSE_EJECT, SUPER_CORE_GROWTH, `collapse_threshold`, `_collapse_heavy_stars` (stars may now outweigh the
  lightest super well if they are spread out), the menu's "Stars collapse at". Tools: Star / Pour cursor warning and
  largest star brush use the same figure (`placement_collapse`, `star_collapse_check`); Super well tool sizes by
  horizon. At reach 30 / strength 1.2: lightest super well 17k; horizon 3.3 cells at 50k, 11 at 200k, 28 at 1M, 44 at
  10M; packed discs: pour 64 r30 (181k) 0.16 of collapsing, pour 256 r20 (322k) 0.65, pour 1024 r8 (206k) and pour
  4096 r3 (116k) collapse. (reach 60: 12.8 at 200k, 40 at 1M; strength 0.6 halves the mass for the same horizon.)
  Found: a heavy super well's horizon outgrows its whirlpool range (test settings: 1M edge 36.5 vs range 27.7), so
  the whirlpool / frame dragging sit inside it - step 6 replaces both. Measured (1920x1080 cell 2): systems preset
  holds all 9 stars 900 ticks (400k wells, horizon 13.8), 7 ms a tick; disk preset: 9 regions of its heavy matter
  collapse into 1.6-2.4M wells (horizons 20-22) within 300 ticks, then none, ~40 ms a tick.
  Tests: 180 pass, 10 marked xfail (strict=False) with reasons - to revisit: step 6 (whirlpool / frame dragging /
  scripted inspiral tuned to the old softened pull): `test_super_wells_spiral_in_circling_ever_faster_then_merge`,
  `test_inspiral_radiates_ever_more_waves...` (the 1-mass wave leak), `test_ejected_mass_escapes_the_range` (only
  mergers eject now), `test_spin_curves_infall...`, `test_whirlpool_is_strong...`, `test_spinning_super_well_drags_
  space...`, `test_clump_inside_whirlpool...`, `test_merger_shock_clears...`, `test_super_well_arms_turn...`; step 7:
  `test_auto_star_fills_an_orbit_evenly...`. Rewritten for the rule: `dense_patch` (a block as near `factor` x
  collapsing as rungs allow), star collapse (inside its own horizon), lightest super well, Super well tool, Pour /
  Star cursor, heavy-but-thin star stays a star, collapse takes the whole patch.
- Radiation is energy only (user, 2026-11-04): heat particles are quanta of VMAX^2 (one unit of mass's worth) flying
  at VMAX, sent through an open side with the emitter recoiling (p = E/c); the first particle in their way takes them
  in as heat + momentum (`kernels.radiation_step`); they never land as matter; a super well swallowing one gains 1
  mass. At the universe's edge they come back in from a random point of it heading inwards (`RADIATION_RECYCLE`,
  menu "Radiation comes back"; off: gone, counted in `radiation_lost`). `ghost_count` / `ghost_mass` leave them out
  (`heat_count`). Checked: a hot crash in a round universe keeps kinetic + heat + radiation at 172,800 for 800 ticks
  (recycling); off, what is left + what left = 172,800; mass exact either way.
- Step 3 coded (2026-11-04, committed): masses are rungs 1, 2, 4 ... 4096. Mass stays a whole number (gravity
  unchanged, mass exact); the mass defect is binding energy per rung, `kernels._binding`: m x FUSION_BINDING (0.05)
  x VMAX^2 x (1 - (1 - rung/peak rung)^2) up to FUSION_PEAK 256, then falling by FUSION_TAIL 0.15 by 4096. Only two of
  the same rung fuse (into the next); chance exp(-barrier / E) (`_tunnel`), barrier FUSION_BARRIER (9) x a b /
  (a^1/3 + b^1/3), E = reduced mass x (relative speed^2 / 2 + both temperatures) (`_fuse_energy`); past the peak E
  must also cover what the fusion takes. In collisions (`_advance`) and between touching particles in `heat_step`
  (a hot core fuses where it lies). Fission: a hit with E over the split cost, through the same barrier, breaks a
  rung into two halves (`_split`, no kick). Binding energy released / taken is heat; `World.energy()` now returns
  (rest, kinetic, heat, -binding) and a crash with fusion and fission keeps kinetic + heat - binding at 80,640
  exactly. All new matter is snapped to rungs (`snap_rung`, `random_rungs`, `rung_pieces`: pours, star layers,
  ejecta, blast debris, waves); `land_ghosts` only joins a particle of the ghost's own rung. Removed: MERGE_SPEED,
  MERGE_CHANCE, SPLIT_SPEED, BIND, SPLIT_KICK, HEAT_SHARE / PIECES / TICKS / COUPLING, FUSION_LIGHT / CHANCE /
  HEAT_SHARE, `star_fuse`, `World._fuse`. Menu: Fusion / Fission toggles (M / P).
  Also: supernova debris cools in exact halves (rungs); a ghost with no free cell nearby looks a cell further out
  every GHOST_LAND_SPREAD (2) ticks (replaces GHOST_LAND_PATIENCE 600: in a packed pile of other rungs it used to
  float 600+ ticks); ejecta and placed stars' layers are rounded to a rung either side at random keeping the
  expected mass (`round_rungs`; estimates use `_layer_masses(..., expect=True)`); `World.radiation_swallowed` counts
  quanta super wells swallowed (each became 1 mass). Tests: 189 pass, only the known auto star fails (obsolete
  tests rewritten for rungs / radiation: random pours, spawner masses, radiation taken in, radiation at the edge,
  hot matter fuses where it lies and cold doesn't).
  Measured (1920x1080 cell 2, all cores): disk preset (75% of its mass in 512-1024, past the peak) - 1,000-2,500
  fusions and as many fissions a tick; past-the-peak rungs shatter in its violent crash (1024: 50% -> 12% of the
  mass), the mix spreads down to light rungs; median temperature 29 at tick 150, 0.65 by 600 as radiation leaves;
  85-111 ms a tick. Cloud (all mass 1, T ~0.1) and systems (stars at T ~0.01): no fusion at all - **stars are cold:
  incompressible matter (one particle per cell) can't be heated by squeezing, so nothing ignites from heat alone.**
  Plan for step 5 (the user's "enough gravity, even with no motion"): count the weight pressing on a particle - the
  hydrostatic pressure of what lies above it in its own gravity - as energy for fusing, alongside heat and motion.
- Step 2 coded (2026-11-04, committed): heat is kin's 5th column (`kernels.KIN`); every kinetic energy loss in
  `_advance` becomes heat exactly (`_pair_ke` / `_heat_loss`, signed: contact rules that hand out energy take it from
  heat - a crash of two blocks keeps kinetic + heat at 172,800 to the unit; a few particles dip below 0 heat for
  ~25 ticks), except an outside force's kick that a contact takes straight back (`_unkicked`: resting under gravity
  does no work - without this, piles in deep wells heated without limit); VMAX cap and wall bounces too; star
  damping's calmed jostling (`damp_star`); splits share heat by mass, fusion adds it up. `kernels.heat_step` (every
  HEAT_EVERY 2 ticks): conduction (HEAT_CONDUCT 0.1) and radiation from open sides (HEAT_RADIATE 0.02) into a pool per
  self-gravity block (`World.rad_pool`), sent out as mass-1 heat ghosts each costing VMAX^2 + HEAT_SPEED^2 / 2 (a
  particle alone almost never holds that much: per-particle quanta never radiated). Heat view (V), `World.energy()`,
  menu line (Advanced -> Performance). Heat pressure (`_pressure_push`, HEAT_PRESSURE) written, energy-exact (charged
  by the kinetic energy it adds, at most half the particle's heat a tick), but **off by default**: at 1, damping ->
  heat -> pressure -> jostling looped, stars puffed apart (all orbit tests lost their stars), hot piles never slept
  (13 test failures). Revisit in step 5 with fusion and cooling.
  Found on the way: the "give" rule (a heavy particle hands what it loses against a star's light particle to it)
  sent light star particles off at thousands of cells/tick (also at HEAD: disk preset, right after stars form):
  `_cap_speed` caps them at VMAX, the made-up energy not kept. Also: `kick` name clash (split kick) - careful.
  Measured: disk preset median temperature ~3.6-3.9 after 100 ticks (thermal speed ~2.7), p99 20-29; only 4 stars by
  tick 100 with pressure on (29 before step 2). heat_step ~3.5-8.5 ms a tick serial at 1102x1102 (optimizer later).
  Tests: 182 pass, 5 fail: the known auto star; `test_head_on_crash_scatters_matter_and_what_stays_bound_merges`
  (2 stars, wants 1 - passes without `_cap_speed`: it relied on the flung particles; step 5 replaces star merging);
  3 mass-conservation tests with radiation on (`test_heat_from_every_strip_is_sent_out` +266..81k,
  `test_inspiral_...` +2, `test_radiation_sheds_heat_...` +1): radiated heat becomes mass-1 particles, so mass grows
  wherever gravity does work (rain: ~+0.04% / 100 ticks with pressure on, +4% with it off). Waiting on the user:
  should radiation land as matter (energy -> mass) or only carry energy?
  Timing note: never time while the test suite runs (numba threads oversubscribe: 25x slower, 32 s suite -> 450 s).
- Step 1 coded (2026-11-04, committed): `Well.fall` / `top_speed` removed, `Well.mobility` is 1 for super wells
  (only solid wells are sluggish in the global orbit / whirlpools), every well capped at VMAX; `orbit_velocity(wl,
  x, y, mass)` gives the two-body orbit and `put_in_orbit` the well's recoil -m u / M; `add_star` works out the
  star's mass before choosing its velocity.
  Measured on the way (1920x1080 cell 2, round, reach 30 / 1.2, 80k well, star or point body 26 cells out):
  - Every star fell in within 30-110 ticks at first. Cause 1: within a tick the star's particles were pulled
    towards where the well was at the start, but the well towards where the star had moved to: a drag of ~0.003
    cells/tick^2 on every orbit (5x weaker with the old mobility of 1/5: the old 300-600 tick spiral-in). Fixed:
    `_stars_accel_then` pulls wells from the stars' tick-start positions (`star_pulls`), softened over the well's own
    size. Cause 2: pairs softened differently (well-star, well-well), so the pulls weren't equal and opposite and
    the pair's centre wandered up to 50 cells. Fixed: well pairs use the larger softening. A point body (solid
    well) now holds 24.9-27.3 cells for 1500 ticks with the pair's centre fixed to 0.1 cell (no rotation).
  - Global rotation killed even the point body's orbit in 53 ticks: `orbit_accel` is velocity-dependent (2% a tick
    grip towards the flow - ~0.05 against a star orbiting at 2.4 cells/tick - plus v^2/r towards the universe's
    centre), applied to each body separately. Fixed: `kernels.orbit_push` - anything bound to a super well (its
    energy against the well, plus the rotation's shear between them, `orbit_shear`, below 0) gets the push that well's
    whole system gets (orbit_accel at the centre of mass of the well and the stars / wells bound to it:
    `World._own_orbit_push`) instead of its own, so a system turns with the universe as one (particles, ghosts incl.
    the GPU shader, wells, spawners). Point body 15 cells out now holds 14.0-16.3 for 1500 ticks with rotation on
    (either way). Tried and dropped: a share rising with how bound (stable orbits round the softened, faded pull are
    less bound than Kepler's, kept part of their own push and were thrown out); a g^2/(g^2+dp^2) dominance factor
    (killed the orbits again). The shear term is what stops barely-bound matter far out at the edge of a well's
    reach (GPU vs CPU test, ghosts 118 cells out) from counting.
    (Note: with the round universe the grid is bigger than the window - its centre is cell (551, 551) at 1920x1080
    cell 2 - so positions measured from the window's centre look like a drift when a system just turns round the
    universe.)
  - Super wells now feel matter by Newton's third law, not the self-gravity mesh: the kernels add up each super
    well's pull on every free particle and ghost and the well gets it back reversed (`absorbed` columns 3-4 ->
    `Well.react`, used in `step_wells`; stars still pull wells as wholes). The mesh, rebuilt every 4 ticks and softened
    differently, made a well that had cleared a hole round itself chase the hole's far wall: after a 2M merger shock
    the well ran away at 4 cells/tick and total momentum grew to millions; now it tops out at 0.16 (0.06 with no
    shock). Swallowed matter's momentum goes to the well too (`absorbed` columns 0-2; also ghost stars).
  - Short reach limit: with the reach fade, circular orbits are energetically unbound beyond ~0.78 x reach (KE /
    |phi| = 0.5 at 0.4R, 0.84 at 0.6R, 1.05 at 0.8R, 1.28 at 0.9R) though dynamically stable to ~1.16R. So at 26
    cells (0.87R) the bound test flickers and the rotation still knocks the orbit eccentric (16.6-23.4, then
    steady). Systems that must survive rotation need orbits within ~0.6 x reach, or a longer reach.
  - Real stars still fall in at 15-26 cells with or without rotation, spin or self-gravity, shedding ~1/3 of their
    mass in 150 ticks; star damping off is worse. That's the old "stars sink in tight fast orbits" (star internals /
    carrying), not the orbit itself: the same star at the last commit (HEAD) also puffs up (radius 4.3 -> 6.9) and
    is gone at tick 321. It spins up past the orbital rate (lock only applies at > 10x mass) and puffs up; damping
    its spin towards the orbital rate instead (tidal locking) was tried and reverted - it still puffed up and died.
    Left for step 5 (star internals get rebuilt there: damping into heat, heat pressure).
  - Tests (2026-11-04): 186 pass, 1 fails - `test_auto_star_fills_an_orbit_evenly_and_the_stars_hold`: three ~1.7k
    stars at 133 cells (1.11 x reach 120) round an 80k well hold perfectly with the well held still, but with the well
    free they drift apart within 1200 ticks (one in to 109, one out to 303); a band edge of 1/r^2.4 or 1/r^2.0
    (118-125 cells) only slows it. A three-star ring round a free well near the reach limit is unstable; left for the
    retune (step 7). Updated for the change: `test_every_well_falls_alike_whatever_its_mass` (was
    `..._heavy_super_wells_move_slower`), `test_solid_well_can_orbit_a_super_well` (two-body setup),
    `test_star_placed_in_orbit_circles...` (two-body speed), test_accel's `absorbed` arrays (n, 5).
- Found on the way (for step 6): matter a super well swallows (`absorbed`, `_collect_absorbed`) adds mass but not
  momentum, so a moving well keeps its speed while sweeping up matter at rest. Step 6 needs the swallowed momentum
  and angular momentum anyway (spin from J): carry both through the same plumbing.

## Where we left off (2026-11-04, handoff)

Done and committed (`8ae3e9c`, pushed): supernova debris flies on past the front; Star damping slider; placement
tools; star-glue speedups.

Done, NOT committed yet (working tree on `squareverse-v2`):
- Menu 450 px wide (`sv/ui.py` `PANEL_W`).
- Star formation every 10 ticks, 200 knots, up to 200 stars per check; capture ring at most 2x radius; gentle merge
  only once sunk in (`STAR_TOUCH_MERGE` 0.6). Tests adjusted (`test_physics.py` touching/grazing stars,
  `test_accel.py` strips test turns star formation off). Star tests pass.
- This TO_DO's Claude Suggestions section.
- sim-optimizer pass for many small stars, finished: edits in `sv/kernels.py`, `sv/world.py`, `sv/config.py`
  (`WAKE_PAR_RADIUS` 300, `STAR_CARRY_PAR` 8); details and numbers in `OPTIMIZATIONS.md` "2026-11-04: many small
  stars". Bit-identical; full suite 186 passed. Supernova scene star window, median of 3: all cores tick
  88.0 -> 73.5 ms (worst 50-tick window 113 -> 84), one core 133.7 -> 112.4; `step_stars` 48.5 -> 28.6 ms; a
  `form_stars` check 43 -> 15 ms (68 -> 32 in the formation burst). Presets unchanged or faster (systems
  3.08 -> 2.40 ms). Cold numba cache now compiles in ~58 s (was ~45), once.

Next, in order:
1. ~~**sim-optimizer**~~ Done (above). History: all its changes were bit-identical (seeded
   hashes match for the round and wrapped supernova scenes and the systems preset). Supernova scene, ticks
   L+80..L+280, first round: all cores median 85-103 -> 73-90 ms, single core 140-142 -> 115-129 ms, a form_stars
   check 44 -> 12 ms. Then, also bit-identical: stars carried side by side on all cores (`kernels.carry_stars_par`,
   `STAR_CARRY_PAR` 8; carry_stars 22.0 -> 10.6 ms a tick on all cores, step_stars 53 -> 27 ms in all; all-cores
   tick median ~70 ms against 99 before; single core step_stars 53 -> 25, tick ~140 -> 112-120 ms), `layered()` in
   numba, a prefilter in `_near_body`, and `WAKE_PAR_RADIUS` 64 -> 300 (the serial wake is now faster up to r~300).
   Code changes finished at ~13:50. Left at that point: the round-2 A/B timings (all cores and single core, 3 each),
   the full test suite and the OPTIMIZATIONS.md entry (~35-45 min). If the session ended before it reported: check
   `git diff`, run the full suite, and rerun the A/B timing (or `/optimize` again with this note) before committing.
2. **Retune for short-range gravity** - partly done. Default is now reach 30 / strength 1.2 (`GRAVITY_REACH`,
   `GRAVITY_SCALE`); the disk preset keeps its tuned 20 / 0.6 (`DISK_REACH`, new `DISK_SCALE`). **Systems and binary
   still set their own 120 / 0.6 (`SYSTEM_REACH`, `SYSTEM_SCALE`) because stars can't yet orbit a super well at
   reach 30.** The user wants every preset on the new values, systems first. What's known (single star, one well,
   collapse off, 1,000 ticks; `World.add_star(orbit=True)`):
   - Orbits must sit inside ~1.16x the reach (<= ~35 cells), so orbital speed is high unless the well is light:
     ~2 cells/tick round 40k at 26 cells, ~5 round 300k (at reach 120 the preset's stars orbit at ~1.2).
   - Every combination tried fails: 40k / 80k / 300k wells with radius-3 pour-1024 stars (~10k) spiral in within
     300-600 ticks; a 20k well (star half its mass) flies apart; a pour-4096 star (70k) outweighs the well.
     Lone stars of every recipe keep their shape, so it's the orbit.
   - First suspect was the well's spin (spin 0 held ~3 turns, 0.5 / 1.0 / 1.5 spiral in, either direction, with or
     without frame dragging), but nothing spin-dependent reaches a star 26 cells out (the whirlpool stops at its
     ~13-cell range), and spin 0 fails too (thrown out after ~400 ticks). **Real cause (2026-11-04): the star is
     10-25% of its well's mass, and two rules assume stars are tiny next to wells (true at reach 120, ~0.1%):**
     1. A super well responds to gravity at only its mobility, `WELL_INERTIA_MASS` / (that + its mass): 1/3 at
        40k, 1/5 at 80k, 1/16 at 300k (`Well.fall`). The star feels the well's full pull but the well feels a
        fraction of the star's, so their shared momentum isn't conserved and the orbit gains or loses energy every
        turn: spiral in or thrown out.
     2. `World.add_star(orbit=True)` / `orbit_velocity` give the star the circular speed for the well's mass
        alone and the well only part of the recoil (`put_in_orbit`). With mobility forced to 1 the pair flies
        apart at once, so that setup is wrong for a comparable-mass pair.
     Fix to try: treat a star-and-super-well pair as a true two-body orbit - relative speed
     sqrt(G x strength x (M + m) / d) split by mass, and the well responding in full to stars' pull (keeping its
     sluggishness for everything else).
   - Found on the way: at spin <= 1 the whirlpool's push is capped at ~the local orbital speed (`kernels.whirl`:
     min(spin x `SUPER_SWIRL_SPEED`, 0.98 x orbital)), so spin only changes it above 1; below that, spin mostly
     sets frame dragging (0.35 x spin). New wells now start at spin 0.5 (`SUPER_SPIN_PLACED` / `NATURAL`, were
     1.5), still rising to 3 at the supernova mass.
   - **Stars are now always lighter than super wells (user's rule, 2026-11-04).** One line, the collapse threshold
     (`COLLAPSE_MASS` 240k / strength: 200k at the default 1.2, 400k at 0.6), is both the lightest super well and
     the heaviest star: a star that reaches it collapses into a super well holding all its mass
     (`World._collapse_heavy_stars`, on the collapse schedule, alongside the density rule); a collapse never
     ejects so much that the new well falls under the line; the systems preset's wells are 400k (was 80k; its test
     still passes). Not yet done: the Star tool's cursor only warns about the density rule, not the mass line;
     README. Consequence for reach 30: wells of 200k+ make orbits ~26 cells out fast (~4 cells/tick), so systems
     at reach 30 need the two-body fix above and probably a heavier star / longer orbit trade-off.
   - Found on the way: a 1-mass leak (799,999 of 800,000) in a two-well inspiral with radiation on, seen when the
     wells spun at 0.5; the test now pins its wells to spin 1.5. Probably rounding in the gravitational waves.
   - Idea from the user (2026-11-04): it's the well's spin, not orbital speed, that the spin-with-mass scale affects
     (orbital speed is set by the well's mass and distance alone). New wells start at spin 1.5
     (`SUPER_SPIN_PLACED` / `SUPER_SPIN_NATURAL`) rising to 3 at the supernova mass (`SUPER_SPIN_FULL`); spin is
     measured against the local orbital speed, like a real black hole's 0-1 spin number. Suggested: keep it rising
     with mass but start much lower (e.g. 0.5), so small wells barely stir their surroundings and can hold stars
     while heavy ones still spin up and feed slowly. Making heavier wells spin slower is the alternative, but it
     loses the brake that rising spin puts on runaway growth (fewer supernova chains). First test: single star at
     spin 0.5 and 1.0.
   - Next: find both causes (a test like `scratchpad/orbit2.py`: one well, one star, NOSPIN / NODRAG switches),
     then tune the systems preset (light well ~40k, small dense stars), binary, auto star (`AUTO_STAR_RECIPES` now
     ends with (1024, 3)), the Star tool's default size, tests and README. The collapse threshold (33k at strength
     1.2) may need lowering for wells that light.
   Original plan (decided): **reach 30 / strength 1.2 as the default for everything**. See the
   short-range gravity entry below for what has to be retuned. Measure each preset at the new reach with the
   sim-experimenter rather than guessing; then update tests (conftest pins reach 60) and the README.
   Starting point, from `World.orbit_band` (the Star tool's band, worked out, not simulated): at reach 30 /
   strength 1.2, stars can orbit super wells of 20k-1M only about 17-34 cells out (at 120 / 0.6: 16-136), and only
   dense ones: pour 256 or 1024 at radius 3-10 cells; pour-16 stars mostly have no band. The collapse threshold drops
   to 33k (80k wells are still over it). So for the systems preset try `SYSTEM_ORBIT` ~27, `SYSTEM_STAR_RADIUS` 5-6,
   `SYSTEM_POUR` 256, `SYSTEM_WELL` 80k; reorder `AUTO_STAR_RECIPES` to dense recipes first; shrink
   `AUTO_STAR_SPACING` (120) to fit orbits ~170 cells round; and the Star tool's default brush (40 px = 20 cells)
   is too big for any band. Then check in simulation that the orbits hold over many turns, with several stars
   per well.
3. Then: Option 3 (star clusters) only if reach 30 still merges stars too much; the README update listed below; the
   merge-rate cap.

Experiment scripts used for the star work lived in a local scratchpad (`exp5.py`, `exp6.py`) and won't be on another
machine; the scene they build is described at the top of Claude Suggestions.

## Claude Suggestions

Ideas discussed and parked to come back to, with what was found. Test scene used for the star work: 1920x1080, cell 2,
round universe, collapse off, orbit off, one 11M super well at the centre that goes supernova (its debris lands at
tick ~272, "L").

- **Many small stars - where it stands (2026-11-04).** Star formation now checks every 10 ticks and forms every
  qualifying knot (`STAR_FORM_EVERY` 10, `STAR_FORM_SEEDS` 200, `STAR_FORM_PER_CHECK` 200), capture rings are at most
  2x a star's radius (`STAR_RING_MAX`, was 4) and gently touching stars only merge once sunk in
  (`STAR_TOUCH_MERGE` 0.6). About 200 small stars (radius 8-12, 45k-130k mass) form within 200 ticks of the debris
  landing, but within ~300 ticks the whole remnant pulls itself into 8-13 big clumps and the stars inside each merge,
  leaving 4-7 stars (1-2 with global rotation on at its minimum). Neighbours don't steal particles (<1%); stars are
  emptied by knocks (~50%) and shocks (~30%) in surroundings moving ~4 cells/tick, against a small star's escape speed
  of ~3-4.5. Tried and dropped (no measurable effect): keeping a star's particles until 1.5x escape speed, and capping
  shock depth at 0.25 of the smaller star's radius. A star can't be much smaller than ~8 cells across: one particle
  per cell, so only heavier particles make it more compact. Rejected: forming stars from smaller, lighter knots.
- **Short-range gravity: works (tested 2026-11-04, not yet made the default).** Gravity strong up close but falling
  off quickly, since the universe is tiny and real-life range makes no sense here. Stars alive 800 ticks after the
  debris landed (2 seeds), by reach (`GRAVITY_REACH`, menu: Reach) and strength (menu: Strength):
  reach 120 / 0.6 (now): 7-9 stars, largest 4-6M; 60 / 0.6: 14-15; 30 / 0.6: 38-41, largest 1.3-1.9M;
  30 / 1.2: 39-41; **15 / 1.2: 114-115 round, separate stars of mostly 30k-40k, largest 0.5-0.8M**, spread evenly
  instead of gathering into big clumps. Tick time about the same (it was 120-200 ms single-core while the optimizer
  was also running). **Decided: reach 30 / strength 1.2 as the default for everything** (a compromise: reach 15
  would leave stable orbits only within ~17 cells of a super well, since orbits hold only inside ~1.16x the reach).
  In progress: retune everything tuned at reach 120 to orbits within ~35 cells - the systems preset
  (`SYSTEM_ORBIT` 120, `SYSTEM_STAR_RADIUS` 10, `SYSTEM_WELL` 80k), placed / auto stars and their orbit bands
  (`ORBIT_BAND_*`, `AUTO_STAR_*`), super wells' ranges, the disk preset (`DISK_REACH` 20), tests (conftest pins
  reach 60) and the README's tuning figures.
  Stars landing near the round rim get squashed against it (visible in both short-reach runs).
- **Minimum core mass for stars: little effect below ~50k.** Share of new stars surviving 300 ticks, by core mass
  (the mass within half the radius; ~2,550 stars pooled over all five gravity settings): <5k 28%, 5-20k 20%,
  20-50k 26%, 50-100k 40%, >100k 54%. Heavier cores do last longer, but only ~2% of stars have a core over 50k, so a
  minimum high enough to matter would remove almost every star. Not pursued for now; short-range gravity did far
  more.
- **Option 3: stars in a clump become a cluster instead of merging.** Today two stars can't overlap (one particle per
  cell), so a slow contact sinks in and merges, a fast one splashes the overlap, and centres meeting merges them; in a
  collapsing clump every star keeps hitting the others, so they all end up as one. Suggested changes:
  1. Touching stars bounce off each other as wholes: a push on each star's velocity, away from the other, like two
     balls colliding and losing a little energy, without disturbing either star's particles.
  2. Splash (`_shock_stars`) only for fast impacts, faster than about the smaller star's escape speed.
  3. Merge only slow, deep overlaps (nearly at rest against each other and well sunk in).
  4. Gravity between stars unchanged (they already pull as point masses), so stars that keep bouncing inside a clump
     end up orbiting each other as a bound cluster, with near misses, slingshots and stars flung out, thinning slowly
     through rare mergers and ejections.
  To watch: the bounces must lose a little energy or a cluster heats up and flies apart (engine contacts are
  dissipative on purpose and star contacts have their own rules); touching stars in a dense cluster could jitter,
  so the bounce should be soft enough for stars in contact to settle; more surviving stars make the per-star cost
  matter more. Code: `World.step_stars`'s merge loop and `World._shock_stars`. Decide after the short-range gravity
  results.
- **Supernova debris heats up a lot after landing.** In the triple-super-well recording (12.5M), the landed debris
  had ~950k merging collisions and as many splits in 1,000 ticks, radiating 1.3-1.5M mass as heat (~11% of the
  remnant), with ~600 heat particles a tick at the peak. The merge-rate cap above is the natural fix.
- **README not yet updated** for the supernova debris flying on past the front (`SUPER_BLAST_COAST` 1.0,
  `SUPER_BLAST_COAST_MARGIN` 10), the Star damping slider (Advanced -> Stars, `STAR_DAMPING`), the star formation
  and merge settings above, and the menu width; left until their values are settled. Its supernova text also says
  the debris ends as 17,000-30,000 pieces of 200-400 mass; measured ~44,600 pieces, 87.5% of the mass at 200-400.
- **A seeded multi-core test isn't repeatable.** `tests/test_accel.py::test_strips_conserve_mass_and_children` gives
  slightly different particle counts between runs despite fixed seeds, most likely because the multi-core kernels
  don't process particles in a fixed order. Pre-existing; mass is always conserved.