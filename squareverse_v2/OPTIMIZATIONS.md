# Squareverse v2: optimization review and plan

A ranked list of ways to make the simulation faster while losing little or no functionality, with the measurements
behind it. It was written on 2026-10-30 against commit `e31f216`; re-measure before starting, because the code moves.

## Baseline

Headless, 960×720 at cell 1, on a 12-core machine. Times are ms per tick.

| preset | particles / awake | `kernels.step` | field rebuild | order rebuild | render | other |
|---|---|---|---|---|---|---|
| rain | 214k / 206k | **25.8** | – | – | 1.3 | HUD scans 0.27, collapse 0.18 |
| disk (orbit + SG + wrap) | 60k / 60k | **15.4** | – | – | 1.1 | SG 0.42 + wake_blocks 0.29 |
| cloud (SG) | 105k / 104k | **14.2** | – | – | 1.5 | SG 0.95 + wake_blocks 0.29 |
| binary (2 wells) | 67k / 67k | **17.4** | **4.7** (8.5 ms per call, every 2nd tick) | **33 ms spike** every 30 ticks | 1.2 | |

What the measurements show:

1. **`kernels.step` is 85–95% of tick time.** It runs on one core and the machine has 12.
2. **Memory locality costs about 30% in radial scenes.** Forcing pure memory order made disk 28% and binary 31% faster.
   The orbit/radial potential order visits cells scattered across the grid. Rain *needs* fine ordering, though: with
   256 or fewer buckets, or with memory order, particles crash into each other and split, and the particle count grew
   from 240k to 400k.

   | `ORDER_BUCKETS` | rain | disk | binary |
   |---|---|---|---|
   | 16384 (current) | 25.2 ms | 16.2 ms | 17.9 ms |
   | 2048 | 25.9 ms | 15.9 ms | 19.0 ms |
   | 256 | 44.0 ms (n blew up to 409k) | 13.3 ms | 15.2 ms |
   | 32 | 46.2 ms (n blew up to 394k) | 11.3 ms | 11.5 ms |

3. **Much of the awake work is wasted.** In rain at t=150, 213k particles are awake but only 66k move. The rest are
   jammed particles that keep re-waking each other through collisions (133k per tick), plus heavier particles that
   stay awake (`stay=True`) while they try to sink.
4. **`field()` is far slower than it needs to be:** 8.5 ms for just 2 wells. It recomputes `_lerp_axis` for every
   cell, runs on one core, allocates 3 new full-grid arrays per rebuild, and computes `phi` on every rebuild even
   though only the order rebuild reads it.
5. **`order_buckets` causes a 33 ms hitch.** The cost is numpy `searchsorted` over 691k cells. With the orbit on, the
   static "ahead" angle key is also recomputed with `arctan2` over every cell.
6. **Compile flags don't help.** `error_model="numpy"`, `boundscheck=False` and `fastmath` all landed within the ±10%
   run-to-run noise.

## Optimization list

Ranked by expected gain divided by risk.

### Tier 1: large gains, no functionality loss

1. **Parallelize `kernels.step` with strip decomposition** (`parallel=True`, `prange`). Expected: **4–8×** on the
   dominant cost.
   - Split the grid into strips at least `2·(MAX_STEPS+2)` = 20 cells wide; about 64 is a good choice.
   - Run two phases: all even strips in parallel, then all odd strips. A particle reaches at most MAX_STEPS cells,
     plus 1 for a slide, a split or a wake, so strips running at the same time never touch the same cells.
   - Pick the strip orientation along the global gravity direction: columns for up/down, rows for left/right, columns
     otherwise. Each strip then holds the whole potential range, so "lowest potential first" stays exact inside a
     strip, which rain depends on.
   - Keep the existing `stamp>>1 == tick` guard. It already stops a particle that crossed into a later-phase strip
     from running twice in one tick.
   - Give each strip its own `stats` and `absorbed` rows and add them up at the end.
   - Gather and counting-sort per strip. This also parallelizes the 0.2 ms full-grid gather scan.
   - With wrap on, force an even strip count so the strips pair up correctly across the seam.
   - RNG: numba's per-thread `np.random` streams are nondeterministic, so `--seed` would stop being reproducible.
     Replace them with an inline xorshift64* whose state is seeded from (seed, tick, strip). Runs stay deterministic,
     and it is cheaper than Mersenne Twister.
2. **Fix `field()`** (`sv/kernels.py`). Expected: 8.5 ms → about 0.5 ms per rebuild, which saves about 4 ms per tick
   whenever wells move.
   - Compute the x-axis `_lerp_axis` results once per column into arrays, instead of once per cell.
   - Use `prange` over rows for the blend and the near-field pass.
   - Write into persistent `fx`/`fy`/`phi` buffers instead of allocating new arrays in `gravity.external_field`.
   - Compute `phi` only when an order rebuild is due, using a flag argument.
3. **Fix `order_buckets` / `rebuild_order`** (`sv/gravity.py`, `sv/world.py`). Expected: the 33 ms hitch drops to
   about 1–2 ms.
   - Write a numba `prange` bucketing kernel: either a binary search on the edges, or a linear map within quantile
     segments.
   - Cache the orbit "ahead" rank array per (w, h, orbit direction). It never changes for a given world size and
     direction.
   - Optionally rank at FIELD_BLOCK resolution and expand to cells.

### Tier 2: moderate gains, no functionality loss

4. **Locality-aware ordering for radial and orbit scenes.** Measured upper bound: 11–30% on disk and binary.
   - Choose the bucket count from the field's shape: about 2·max(w, h) for uniform gravity (2048 is safe for rain), a
     few hundred when the field is radial or the orbit is on.
   - Alternatively, bucket by 8×8 tile and process each tile's cells together.
   - Validate with the rain/disk split and merge counts described under Verification.
5. **Pack the per-cell state the hot loop reads.** Expected: 5–15%.
   - Merge `hole` and `solid` into one `terrain` array, so each movement probe reads 2 arrays (`mass`, `terrain`)
     instead of 3.
   - Optionally interleave mass, shade and the stamp-blocked bit.
6. **Micro-optimizations in the hot loop.** A few % each.
   - Make `wake_around` write flags without the mass checks. `step`'s gather already skips empty cells, so the 9 mass
     reads can go.
   - Replace `%` with a conditional ±w/±h in the wrap paths (`_cell`, `step`).
7. **Make `wake_blocks` loop over changed blocks only.** It currently scans all 691k cells every self-gravity update:
   0.29 ms → about 0.
8. **Self-gravity.**
   - Reuse the FFT and gradient buffers.
   - Use float32, or `scipy.fft` with `workers=-1` if scipy is available.
   - Share the `bin_mass` result with `check_collapse` when both run on the same tick.

### Tier 3: render and frame loop (shows up as FPS, not step time)

9. **Pipeline the simulation and the display.** Add `nogil=True` to the `step` and `render` kernels, then run
   `world.step()` and the render kernel in a worker thread while the main thread handles events, the HUD and `flip`.
   This hides 3–5 ms per frame at the cost of one frame of display latency.
10. **Render straight into a persistent Surface** (`sv/render.py` `draw_world`).
    - At cell 1, skip `transform.scale` and `frombuffer`.
    - At cell > 1, have the numba kernel upscale and draw the grid lines itself. That removes the scale and the
      full-screen SRCALPHA overlay blit at cell ≥ 4.
    - `prange` the render kernel.
11. **Cut HUD and help costs.**
    - Have the step kernel return the particle count and total mass, or keep them updated incrementally, instead of
      two full-grid scans per frame (0.27 ms).
    - Re-render the HUD text at about 5 Hz instead of every frame.
    - Cache the help panel surface. It currently renders about 50 font surfaces every frame.

### Tier 4: small behaviour changes (put them behind config flags and validate)

12. **Fewer awake-but-idle particles.** Up to about 3× fewer simulated particles while piles settle.
    - (a) Wake `j` on a collision only when the velocity it receives (`du_k`) is above a threshold.
    - (b) Let `stay` particles retry sinking every K ticks, staggered like `CHILD_EVERY`, with `SINK_CHANCE` scaled up
      so layering happens at the same speed.
13. **Python per-tick overhead.** About 0.1 ms per tick; it matters only for small scenes.
    - Cache `params()` and `whirls()` and invalidate them when a toggle changes.
    - `step_wells`, `_swallow_wells` and the star collision checks are O(W²) Python loops. Vectorize them, or move
      them to numba, if scenes start using dozens of wells.

## Order of work

1. **Phase A:** items 2, 3, 6, 7, 10 and 11. Low risk and independent of each other.
2. **Phase B:** the custom RNG, then the strip-parallel `step` (item 1).
3. **Phase C:** item 5 (packing), then item 4 (ordering), then item 9 (pipelining).
4. **Phase D:** item 12 behind flags, kept only if the behaviour check under Verification stays close to the
   baseline.

Files involved:
- `sv/kernels.py`: `step`, `field`, the `wake_*` kernels, `render`, plus the new RNG and bucketing kernels
- `sv/world.py`: `step`, `rebuild_field`, `rebuild_order`, `_alloc`, cached params
- `sv/gravity.py`: `external_field`, `order_buckets`, `SelfGravity`
- `sv/render.py` and `sv/app.py`: render path, HUD caching, worker thread
- `sv/config.py`: strip width, bucket policy, new flags

## Verification

- Run `python -m pytest` after each phase. It covers mass conservation and the other physics invariants.
- Run `python main.py --preset {rain,disk,cloud,binary} --cell 1 --benchmark 300` and compare with the baseline above.
- **Behaviour check:** step rain (`World(960, 720, 1, seed=1)`, `PRESETS["rain"]`) for 1500 ticks. Every 150 ticks,
  log the particle count, the awake count and `world.stats` (moved, collisions, merges, splits, sinks). The run should
  stay close to the baseline:

  | tick | particles | awake | moved | collisions | splits |
  |---|---|---|---|---|---|
  | 150 | 222k | 214k | 66k | 133k | 78 |
  | 600 | 89k | 81k | 14k | 51k | 11 |
  | 900 | 53k | 39k | 2.0k | 30k | 0 |
  | 1500 | 33k | 14k | 0.6k | 11k | 0 |

- **Determinism:** once the custom RNG is in, two runs of `--seed 1 --benchmark 200` must print identical totals.
- **Visual check:** run the app at cell 1 and cell 8 with wrap and orbit on, and look for seams at strip boundaries.
- Breakdown by phase: time each call in `World.step` separately: `rebuild_field`, `rebuild_order`, `sg.update`,
  `wake_blocks`, `kernels.step`, `check_collapse`, `step_wells`, `render`.

## 2026-11-02: exact super-well gravity, the tapered fade and the inspiral (commit `4a8102a`)

Measured headless at 1920×990, cell 2 (the user's maximized window: a round universe 1082 cells across), all cores,
no GPU. Each figure is the median ms per `World.step` (wall clock), and each row is the median of runs taken
alternating old / `4a8102a` / now.

| scene | `036e118` | `4a8102a` | now | runs |
|---|---|---|---|---|
| disk, reach 20, ticks 50–150 (~18 super wells, no pairs) | 34.6 | 43.2 | 38.2 | 5 each |
| disk, reach 20, ticks 170–470 (~30–37 super wells, ~10 pairs spiralling in) | 39.6 | 60.4 | 26.2 | 3 each |
| systems (default), ticks 100–400 | – | 5.6 | 5.4 | 3 each |
| Star tool picked, systems: `draw_orbit_bands` per frame | – | 7.7 | 0.9 | 2 each |

What `4a8102a` cost, and what fixed it:

- **The new `gravity.fade` on a single number** went through about 12 numpy calls (10 µs). `reach_for`'s 50-step
  bisection called it at every step, so every cache miss cost 0.5 ms, and super wells miss every time their mass
  changes (about 19 a tick in the disk). That came to 7 ms in `step_wells`, 2 ms in `whirls()` and 2 ms in
  `step_stars`, and `orbit_band` took 5 ms a frame. Now a single number takes a `math` path with the same arithmetic
  (0.35 µs, bit-identical; `math.log` and `np.log` agree on this machine), and `reach_for` works out the pull's share
  inline (a miss now takes 11 µs).
- **Super wells moving every tick** (the inspiral) left the kernels nearly unchanged (`_step_strips` is within noise
  with 18 exact `_pull`s per particle), but it added per-tick Python costs:
  - `step_wells` makes one matrix `fade()` call instead of one per well.
  - `_inspiral` and `_swallow_wells` prefilter all the pairs in numpy (`_maybe_overlapping`, `_maybe_touching`,
    with a margin for numpy's `hypot`) before their exact per-pair checks.
  - The waves are flown by a numba kernel (`kernels.fly_waves`), not by ~160 numpy calls a tick, and the pairs'
    waves are added to the ghost arrays in one go (`World._batch_ghosts`).
  - A moved well wakes a small disc on one core (`WAKE_PAR_RADIUS`). On all cores a 39-cell disc took 16 µs at the
    median and up to 7 ms in the tail, against 14 µs on one core.
- **`draw_orbit_bands`** clears and blits only the part of its full-screen layer it drew on. The full-screen blit
  alone was 1.3 ms.

Tried and ruled out:

- A potential-only copy of `kernels.field` for `_order_phi`. It gave identical results, but only cut one re-rank from
  10.3 to 8 ms (31 wells) and from 4.1 to 2.2 ms (3 wells). Instead `_order_phi` now just adds in place.
- Merging the two `heat_push` passes: the wave pass costs next to nothing, and one pass would change the order of
  the pushes.

Checks: every change is bit-identical. Seeded single-core runs of disk and systems (400 ticks), and of wrapped and
round scenes with super-well mergers, swallowed wells, a held well and waves, hash to the same state as `4a8102a`
every 25–50 ticks. The band overlay renders the same pixels. (All-cores runs don't repeat even at `4a8102a`: use
`--cpu` for such checks.)

## 2026-11-03: stars' per-tick glue after `55da239` / `70c0ef8` (reach 120, star damping, frame dragging)

Measured headless at 1920×1080, cell 2 (a round universe 1102 cells across), all cores, no GPU, in a busy systems
scene: the systems preset plus 5 more super wells of 300k with 3 stars each, all spun to 3, a 75k-particle dust ring
and 20 small blobs (~50–77k particles, ~15–20 stars, 8 super wells, global orbit off). Each figure is the median of the
per-run tick medians, runs alternating HEAD (`387e1d7`) / now, from the same seeded start.

| scene | HEAD | now | runs |
|---|---|---|---|
| busy, all cores, ticks 0–150 | 36.0 (34.3–42.7) | 31.2 (28.6–32.3) | 5 each |
| busy, `--cpu` | 58.6 (56.7–66.3) | 51.6 (50.7–54.3) | 3 each |
| systems preset, ticks 0–300 | 6.4 (6.1–7.4) | 5.4 (4.9–5.6) | 5 each |

Where the time went: not in frame dragging. `kernels.step` with `SUPER_DRAG = 0` was within noise of it on (14.0 vs
14.1 ms). It was the stars' Python glue, about 1 ms a star a tick (`step_stars` 17.0 ms for 15 stars):

- `World._disk_cells` (numpy `meshgrid` and masks, ~180 µs) ran ~42 times a tick to find a star's cells, in
  `_star_cells`, `_damp_stars` and twice in `carry_stars`. Now `kernels.owned_cells` (16 µs), same cells, same order.
- `_damp_stars` (new in `55da239`) did ~25 numpy calls a star (~130 µs). Now `kernels.damp_star` (~16 µs), with
  `kernels._pairwise_sum`, which adds up exactly as numpy does (pairwise, blocks of 8 below 128), so it is
  bit-identical. Checked against `np.sum` on random arrays of every length 0–3000 and up to 100k. Keep it
  non-recursive: a recursive cached kernel segfaulted every time it was loaded back from numba's disk cache.
- `World.frame_turn` worked out each spinning well's reach, softening, range and drag share again for every star.
  `carry_stars` now passes `drag_rows()`, worked out once a tick.

`step_stars` came down from 17.0 to 8.6 ms in that scene. Seeded `--cpu` runs of the busy and plain systems scenes
hash to the same state as HEAD every 25 ticks for 200 ticks.

Still costly, not changed:

- **Global orbit on:** `_carry_blobs` took 14.5 ms a tick in the busy scene (`find_blobs` 8.8 ms, a one-core flood
  fill; `carry_blobs` 6.3; `occupied_par` 1.9). Unchanged since `9428b5e`.
- `kernels.star_shift`: ~110 µs a call, ~1.5 calls a star a tick. Its `argsort` order (ties included) decides who
  moves first, so a different sort would change results.
- `_set_ring` (~47 µs a star) and `orbit_well`, in pure Python. Switching them to numpy's `hypot` would not be
  bit-identical.
- **The frame:** at zoom 0.49 `draw_world` costs ~15–20 ms a frame. That is `world.render` 4–9 ms, pygame
  `smoothscale` (one core) 9.5–11 ms and blit + fill ~2 ms. Plain `scale` takes 3 ms but looks different. A
  `prange` port of pygame's shrink filter would look the same.

## 2026-11-04: many small stars (star formation every 10 ticks, up to 200 at once)

Measured headless at 1920×1080, cell 2 (round, 1102 cells across), in the scene the new star formation was tuned on:
collapse and orbit off, one super well of 11M at the centre. It goes supernova, its debris lands ~272 ticks in (L),
~130–160 stars form by L+100 and merge down to ~10 by L+600. Seed 1, each figure the median of 3 runs, taken alternating
the uncommitted working tree before this work / now, after `World.warmup`. The window is L+80..L+280 (the star peak).
The formation burst is L..L+80. All-cores runs had the load of another experiment on the machine part of the time (load
average 2–7). One single-core run on each side was disturbed (161 and 130 ms) and is left out of the medians below.

| | all cores before | all cores now | one core before | one core now |
|---|---|---|---|---|
| tick, median | 88.0 | 73.5 | 133.7 | 112.4 |
| tick, worst 50-tick window (median) | 113.4 | 84.0 | 155.9 | 127.4 |
| tick, 95th percentile | 143.8 | 109.1 | 179.5 | 140.7 |
| `step_stars` | 48.5 | 28.6 | 43.8 | 25.0 |
| a `form_stars` check (every 10 ticks), L+80.. | 43.2 | 15.3 | 43.6 | 11.3 |
| a `form_stars` check, L..L+80 | 68.4 | 32.1 | 61.6 | 23.5 |
| worst tick, L..L+80 | 141.9 | ~102–122 | 157.9 | 98.4 |

The presets (`--benchmark 300 --no-gpu`, 3 runs each, alternating) are within noise or a little faster: systems step
3.08 → 2.40 ms, rain 8.21 → 7.91, disk 23.9 → 22.4.

Where the time went (all cores, before): `step_stars` was 53 of a 99 ms tick:

- `carry_stars` 22 ms, almost all `kernels.star_shift` (~138 calls a tick, the moving of each star's particles).
- `kernels.wake_disk` 11.4 ms: ~54 discs a tick of radius 45–180 (a moving star's reach). It tested every cell, did two
  integer modulos per cell, and branched on `mass`.
- `_set_ring` 6 ms: a Python loop over every star and super well for each star.
- `star_field` 6 ms on one core; `update_stars`, `star_motion`, `star_sink`, `_shock_stars`, `_remap_owner` 2–3 ms each.
- `form_stars`: ~145 candidate knots a check, each costing ~25 numpy calls in `_knot_centre` and `_packed_radius` and
  ~40 a cut in `layered`, plus `_near_body`'s loop over every star. That made 45–70 ms every 10 ticks.

What changed (every change bit-identical; see the checks below):

- **`kernels.wake_disk`** finds the run of cells each row of the disc covers (the same per-cell test, applied only at
  the run's ends) and or-s the flags in with a loop that vectorizes (`flag` is only ever 0 or 1). It is 20–30× faster
  (r = 82: 240 → 8–12 µs). `step_stars` gathers its discs into one `kernels.wake_disks` call: 54 large discs went from
  33 ms to 1.2 ms. `WAKE_PAR_RADIUS` went from 64 to 300: one core now beats the cores' start-up tail (~250 µs at
  p99) up to r ≈ 300.
- **`_set_ring`** looks only at the bodies `_ring_bodies` picks out for all stars at once in numpy: those whose tide
  reaches the star and whose Roche lobe, at its smallest, could come inside the ring's bounds or its radius. The bound
  uses `_SHARE_MAX`, tide_share's top (it overshoots 1 in the taper), and a 1e-9 margin. The rest cannot change what
  it finds. **`_shock_stars`** and the **merge loop** look at the pairs `_gaps` finds close. Stars that have taken
  part in a merge this tick have moved and grown, so every pair with one of them is checked exactly. **`_near_body`**
  prefilters the same way.
- **Carrying the stars** is planned in Python first (turn, steps; none of it depends on the grid), then run by
  `kernels.carry_stars`. On all cores, once there are `STAR_CARRY_PAR` (8) stars, `kernels.carry_levels` puts stars
  whose touched regions (r + 4 round the line they are carried along) overlap at successive levels, and
  `kernels.carry_stars_par` carries each level's stars side by side, with a row each for `absorbed` and `push`. Stars
  that share cells still go in their turn, so the result is the same. The turn of a star's velocities is done in float32 as
  numpy did, and the shared-out knocks as float64 cast back (numpy promotes the `np.float64` scalar), which
  was checked against the old numpy code on 40 turned stars. `carry_stars` 22 → 10.6 ms on all cores.
- All cores only: `star_field_par` (a row of blocks per thread), `update_stars_par` (owners a grid row at a time,
  each cell still seeing the stars in turn; then the sums a star at a time) and `star_motion_par`. One core and
  cores: `kernels.remap_owner` instead of numpy's `table[owner]`.
- **`form_stars`**: `kernels.disc_moments` (`_knot_centre`: sums of whole numbers, so exact in any order),
  `kernels.packed_radius` (the smallest k with k² ≥ dx² + dy², which is what `ceil(hypot)` gives on whole offsets),
  `kernels.layered` (the log stays numpy's, which may differ from numba's in the last bit; the medians and means are
  done as numpy does them).
- `warmup()` also compiles the new kernels, so the app doesn't stall on first use. A cold cache now takes ~58 s to
  compile everything instead of ~45 s.

Checks: seeded single-core runs hash (mass, kin, owner, flag, quad, stamp, ghosts, stars, wells) to the same state as
before every 25 ticks: this scene for 600 ticks, the same scene wrapped for 500, the systems preset for 300 and the
systems preset with its super wells spun to 3 for 200. The parallel paths were also forced on in single-core runs of
those scenes, and they hash the same. The parallel kernels match the serial ones exactly on real mid-run states, round
and wrapped, with rings that span the whole axis. The new `wake_disk` matches the old one on 4,000 random discs and
batches, wrapped or not, with radii from 0 to 80 and centres off the grid. 186 tests pass.

Still costly, not changed:

- `kernels.star_shift`, ~8.5 ms on all cores (13 on one): per particle it moves and wakes. Its `argsort` tie order
  decides who goes first (a particle shoved aside lands in the cell a tied neighbour moves into), so no other sort can
  be used.
- `star_sink` (~2–4 ms) draws from numba's global RNG in cell order, so it stays on one core.
- `kernels.step` / `step_tiles` (15–20 ms on all cores) and the supernova debris ghosts (`step_ghosts` ~9 ms) now cost
  more than the stars in this scene.
- On all cores, the Python-side `step_stars` is ~2–4 ms slower than on one core for the same work: the serial
  kernels between parallel ones run slower there (cache and clock effects).
