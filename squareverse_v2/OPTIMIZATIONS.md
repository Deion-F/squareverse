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
