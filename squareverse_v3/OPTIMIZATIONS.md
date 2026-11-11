# Optimizations

What was landed or ruled out for speed, with the numbers that decided it. Each entry names the machine and
backend; "A/B" means the two builds were run alternately, three runs each, medians. GPU ms are timestamp totals a
step of dt (headless `gpu_ms_per_step`, the median step); a sub-step is dt / 2^(levels - 1).

## 2026-11-11: optimizer pass on `PERF_REVIEW_FABLE.md` (RTX 2070 Super, Vulkan, Windows exe)

Starting point: commit `b595a56`. The laptop wasn't measured: PLAN_V3.md Laptop backlog L8 lists what to check
there.

### Summary, before and after (headless, seed 1, 5 steps, A/B, 3 runs each)

| Scene, particles | GPU ms a step | Wall ms a step |
|---|---|---|
| Galaxy 50k | 129.4 -> 73.4 | 138.9 -> 83.0 |
| Galaxy 100k | 199.5 -> 107.5 | 206.7 -> 116.8 |
| Galaxy 525k | 638.5 -> 350.5 | 629.5 -> 354.5 |
| Galaxy 1M | 1,303 -> 656 | 1,289 -> 661 |
| Pair 525k | 537.6 -> 341.3 | 541.5 -> 345.6 |
| Group 525k | 495.6 -> 333.1 | 499.5 -> 338.8 |
| Universe 100k (z ~ 30) | 63.4 -> 47.1 | 65.3 -> 49.9 |
| Universe 525k (z ~ 30) | 425.5 -> 289.1 | 422.8 -> 289.4 |
| Test disc 1M | 172.8 -> 111.9 | 174.0 -> 113.9 |

"Before" GPU ms are from the build with only the timer fix (below), since the old timer missed passes.

Window, 60 fps target, 600 frames, A/B (fps, worst frame, sim speed, sim budget):

| Scene, particles | Before | After |
|---|---|---|
| Galaxy 525k (3 runs) | 60.0, 17.3 - 17.6 ms, 1.69 - 1.90 Myr/s, 13.7 ms | 60.0, 17.3 - 17.4 ms, 3.33 - 3.58 Myr/s, 13.7 ms |
| Galaxy 1M (3 runs) | 59.8 - 60.0, 25.7 - 26.6 ms, 0.56 - 0.74 Myr/s, 6.2 - 8.0 ms | 60.0, 17.3 - 17.7 ms, 1.62 - 1.74 Myr/s, 13.3 ms |
| Universe 525k (2) | 60.0, 17.3 - 17.4 ms, 35.6 - 36.5 Myr/s | 60.0, 17.2 - 17.3 ms, 50.5 - 51.1 Myr/s |
| Group 525k (2) | 60.0, 17.3 - 17.4 ms, 2.63 - 2.68 Myr/s | 60.0, 17.2 ms, 3.48 - 3.61 Myr/s |
| Pair 525k (2) | 60.0, 17.3 - 18.2 ms, 2.30 - 2.40 Myr/s | 60.0, 17.3 - 18.5 ms, 3.25 - 3.45 Myr/s |

Results: `state_hash` changed where the tree changes (rebuild cadence: galaxy, pair) or float sums regroup (split
walks: wherever a list is short enough, so every scene with block steps except the universe at 525k); everything
else is bit-identical (checked by hash after each item). Energy change and force errors hold: the ignored force
tables (`force_accuracy_table`, `clump_force_table`) match the baseline to the last digit; galaxy energy over
100 Myr at 30k, seeds 1 - 4, baseline -3.74 / -4.23 / -5.95 / -3.91e-3 against final -2.86 / -4.35 / -6.40 /
-4.33e-3 (mean -4.46 against -4.49e-3; seed spread 2.9 - 6.5e-3; neither the cadence nor the split moves the mean).

### Landed

1. **Time every pass** (`src/timing.rs` `MAX_PASSES` 256 -> 2,048, wgpu's 4,096 timestamps). A 7-level galaxy step
   has ~446 passes, so the timer had missed 27 of 64 sub-steps: 525k read 368 GPU ms a step against 633 (wall
   627). The README's GPU ms per Myr figures were low by this.
2. **Rebuild the tree every 4 sub-steps in the galaxy and pair** (`SimConfig::default` `rebuild_every`; the test
   disc, universe and group set 8). The bulge's fast particles outrun a refitted tree, its boxes overlap, and the
   walks open more nodes: the same 1.1k listed particles cost 2.0 ms of force on a fresh tree and 7.0 ms seven
   sub-steps later (525k); one 44k list 4 sub-steps on cost as much as 221k on a fresh tree. GPU ms a step at 8 / 4
   / 2 / 1: galaxy 525k 635 / 513 / 525 / 588; 1M ~1,310 / 943 / 963 / 1,083; 250k 311 / 276; 100k 198 / 187 / 196 /
   213; 50k 130 / 128; 25k 106 / 107; pair 525k 542 / 487 / 510, 1M 1,043 / 882, 250k 296 / 279, 100k 170 / 170.
   Kept at 8: group 525k 499 / 486 / 522 and 100k 148 / 150 (within noise); universe 525k 431 / 456 / 509 (16:
   432), 100k 63 / 64 / 66; test disc 1M 173 / 177 / 192, 200k 37 / 40 / 42.
3. **Force (and gas) cost learned by tree age and sub-step kind** (`Sim::force_cost`, `gas_cost`, `collect`; the
   timer now carries a tag per pass, `GpuTimer::compute_tagged`). The window's model charged a force slice its
   listed share of one full-pass rate with a 0.2 floor. Logged at 1M (estimate against timed ms per item): at
   cadence 8 the pass 4 sub-steps after a rebuild ran 3x its estimate (6 - 11 ms estimated, 29 - 36 timed), as the
   review guessed; at cadence 4, slices on a fresh tree ran 1.6x (up to 4x) over and short lists at 0.4 - 0.8 of
   theirs. Late frames shrank the budget to about half (scale median 0.53; 43 late frames in 780). Now each
   (age, kind) learns its least cost (a walk's latency) and its full-pass rate; the first measurement replaces the
   first guess outright. Medians of timed / estimate 0.96 - 1.01 per item; budget scale back at 1.0; 7 - 11 late
   frames in 780. Doesn't touch the physics (`frames_falling_anywhere_change_nothing`).
4. **A 32-byte walk record** (node layout in `shaders/common.wgsl`, written by `moments.wgsl`, read by the force,
   group force, gas, feedback, finder and wells walks). Opening a node now reads vec4s 0 and 1 (centre of mass;
   mass, opening radius², children), using it as one mass adds vec4 2 (quadrupole, softening²); the box and the
   particle run moved to the end, the children are copied into the node. Bit-identical. GPU ms a step: galaxy 525k
   510 -> 464, 100k 188 -> 177, universe 525k 428 -> 371, 100k 60.6 -> 58.2. A 96-byte record (24 words, aligned)
   was no better: 469 / 173 / 402 against 465 / 178 / 372.
5. **Walk stacks in functions, not entry points** (force_particle.wgsl `walk`, hydro.wgsl `pressure`, feedback.wgsl
   `nearest_gas`, finder.wgsl `lowest_label`). SPIR-V puts every function-local variable at the top of the entry
   point and WGSL zero-initialises it, so a 96-word stack declared in the entry point was written by every thread
   of the dispatch (all n), even those returning at once: on a short list that was most of the pass. Bit-identical.
   Force alone: galaxy 525k 464 -> 419, 100k 177 -> 166 GPU ms a step. Gas force: 525k gas stage 84.1 -> 41.7,
   100k 54.3 -> 45.8. Feedback 1.81 -> 1.48; finder within noise.
6. **Split walks on short lists** (force_particle.wgsl `SPLIT_MAX` 16, `SPLIT_SLOTS` 32,768). With the list x T
   within 32k slots, T threads (a power of two up to 16) share a particle's walk: each follows the chain of nodes
   holding the particle and walks what hangs off it at its levels (l mod T); the partial sums meet in workgroup
   memory and the first thread adds them in order. Same interactions; sums regrouped (new hash wherever T > 1).
   Tuned A/B (GPU ms a step, galaxy 525k / 100k / 1M): off 418.5 / 163.8 / 758.8; 16 & 16k 395.6 / 137.9 / 737.2;
   **16 & 32k 390.1 / 136.4 / 735.6**; 16 & 64k 389.3 / 140.8 / 742.7; 32 & 64k 395.6 / 140.7 / 744.3; 32 & 128k
   407.6 / 145.1 / 750.8; 64 & 256k 426.6 / 147.7 / 800.6. A first version giving each thread a fresh walk per
   hanging subtree (a stack set up for each) gained only at 100k (157.9) and lost at 525k (428.5).
7. **Gas density beside the gravity walk** (force_particle.wgsl, 256-thread workgroups: 128 gravity slots and 128
   for density of the same stretch of the list; new `shaders/density.wgsl` shared with hydro.wgsl; `Work::Gas` runs
   only the pressure pass for the particle walk). Bit-identical. GPU ms a step: galaxy 100k 128.0 -> 106.8, 525k
   351.8 -> 351.8, 1M 664.6 -> 655.8, universe 100k 51.8 -> 51.6. Needs 8 storage buffers in force_particle.wgsl
   (the default limit).
8. **The finder skips rounds after a converged one** (finder.wgsl `next_round`, `CHANGED` / `LAST` words after the
   slots). A round that changes no label leaves a fixed point, so later rounds' `link` and `jump` return at once.
   Same galaxies (group 200k after 202 Myr: 45, identical checksum; universe 100k at z 0.91: 245, identical) and
   same hash. GPU ms a finder run: universe 100k early 10.3 -> 4.1, at z 0.91 27.5 -> 14.8; group 200k 54 -> 34.

### Measured and not landed

- **`short_range` once per accepted node** (review 6a): universe 525k 427.4 against 427.5 GPU ms a step, galaxy
  525k 510.1 against 509.7 (the compiler already shares it). Reverted.
- **Rebuild every 2 or every sub-step** in the galaxy: see 2; the sort and build cost more than the fresher tree
  saves (525k: 525 and 588 against 513).
- **The finder's cadence** (`finder.every_myr`, 100 in the universe): left to the user. After 8 its runs cost
  ~4 - 15 GPU ms in the universe at 100k (more when clustered), ~3 ms a step on average at z ~ 1 (one run every 5
  steps); 200 Myr would halve that.
- **Kick over the list, compact flag folded into the scan, an epoch for `moments.wgsl reset`** (review 7): on the
  RTX, `integrate` + `compact` are 8.6 + 5.6 of 350 GPU ms a step at 525k (4%) and the refit's reset a small part
  of `refit`; the kick over the list would need a ninth storage binding in integrate.wgsl. Not done; laptop
  backlog L8 says when to.

### Where the time goes now (galaxy 525k, 350 GPU ms a step)

force (with gas density) 228 (65%), refit 35 (10%), sort 27 (8%), gas pressure 23 (6%), build 19 (6%), integrate
9, compact 6, wells 3.6, feedback 1.5. By sub-steps since the rebuild (cadence 4): the 16 rebuilt sub-steps of
a step take 228 of its 352 ms (their force passes 2.6 - 22 ms; the long lists end on them), the 48 refitted ones
1.8 - 3.2 ms each.
