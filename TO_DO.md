- When calculating for results of physics changes such as getting stars to orbit a SGW, always assume that global rotation (set to its minimum value) is enabled. Either direction could be enabled. Also confirm whether the changes you made were built to work in a rotating universe or a static.

- Add a cap to the rate that particles can merge, to better simulate stars fusing and giving off heat overtime instead of all at once. The cap should be related to how much grativty the particles expereince, so very large stars should be able to fuse heavier particles very often while small stars fuse and give off heat much slower. The intended behaviour is for a naturally born star is that matter clumps together and over a certain threshold of matter in a certain region it "ignites" into a star which means that the material at the core is expereincing enough gravity that even with no motion it will fuse with the same mass or lighter particles, giving off heat in the process. The threshold for becomming a star would ensure that fusion in the core of the star is possible (however as stars lose mass via heat, if the smallest possible star was created and no additional mass was added to it then it would go below the threshold for particles to fuse in its core and in this case the star should go supernova to simulate it becomming unstable). As a side note, this would mean that two things can lead to a particle fusing, colliding at high enough speeds or experencing enough gravity.

- confirm the sim isn't compiling kernels when not needed

- The simulation runs very slowly when there is a very heavy SGW. Is this expected? I would assume that since every particle inside of a SGW isn't simulated, a SGW and another SGW 10x bigger should have roughly the same performance?

- ~~Make the menu window wider as it keeps jumping around when the values at the very top change and go onto a second line.~~ Done: `PANEL_W` 380 -> 450 (`sv/ui.py`), wide enough for 10M particles, 1B mass and 100M ticks on one line.

- ~~Invesitagte why the test runner is no longer able to close the sim even after being given permission.~~ Done: the subagents only close the sim on the user's own go-ahead, and auto mode blocked the kill until settings.local.json got an autoMode allow rule.

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
   - **The decay comes from the well's spin:** with frame dragging off it still spirals in, but with spin 0
     the orbit holds at 25-27 cells for ~3 turns (star radius steady at 3.6-3.9). Suspect the whirlpool
     (`SUPER_SWIRL_*`) or another spin effect reaching a star ~26 cells out at reach 30 (the faint circle is ~13).
   - **Then a second problem:** even with spin 0, after ~400 ticks the star is thrown out (25 -> 41 -> 80 cells).
     Not yet traced.
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