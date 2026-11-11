# Performance review (Fable, 2026-11-11)

For the sim-optimizer. No code was changed. All figures: RTX 2070 Super, Vulkan, Windows exe, headless, seed 1,
single runs of 5 steps (not A/B medians). `E=target/x86_64-pc-windows-gnu/release/squareverse.exe`.

## 1. Where the time goes

**The headless GPU figures are wrong for 7 levels.** `GpuTimer` times only the first 256 passes of a submit
(`src/timing.rs:8`, `:85`); a galaxy step has ~443, so 27 of 64 sub-steps are missing, including the full-list
passes. At 525k: `gpu_ms_per_step` 368, `wall_ms_per_step` 642. The README's 175 GPU ms per Myr is really ~320
(check: 2.35 Myr/s x 320 = 750 GPU ms a second, the window's budget). Use wall time until item 0 lands.

Full step, rebuilt from `SV_DEBUG_PASSES` (37 sub-steps seen, the rest by their class):

| Scene | Step | force | gas | refit | sort + build | find | rest |
|---|---|---|---|---|---|---|---|
| Galaxy 525k | 642 ms | 75% | 14% | 6% | 3.5% | - | 1.5% |
| Galaxy 100k | 209 ms | 57% | 33% | 4.5% | 2.5% | - | 2.5% |
| Universe 100k (z ~ 30) | 66 ms | 35% | 41% | 3.5% | 2% | 15% | 3.5% (pm 0.4%) |

**Force time follows the tree's age, not the list's length.** Galaxy 525k, by sub-steps since the rebuild:

| Sub-steps since rebuild | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 0 (rebuilt) |
|---|---|---|---|---|---|---|---|---|
| Listed particles | 1.1k | 4.6k | 1.1k | 44k | 1.1k | 4.6k | 1.1k | 221k - 525k |
| Force ms | 2.0 | 2.5 | 3.0 | 12.7 - 16.7 | 4.4 - 5.0 | 5.5 - 5.9 | 6.6 - 7.0 | 16.7 - 29.7 |

The same 1.1k particles cost 2.0 ms on a fresh tree and 7.0 ms seven sub-steps later; 44k cost as much as 221k
on a fresh one. Refit keeps the topology, and the fast inner particles' boxes bloat and overlap. About 27% of the
step is this excess. Gas is flat at 0.9 - 1.3 ms a sub-step whatever the list (latency of three short walks), 4.2
on a full list.

## 2. Opportunities, by desktop gain / effort

**0. Time every pass (S, prerequisite).** `src/timing.rs:8`: `MAX_PASSES` 256 -> 2048 (4,096 queries is wgpu
30's `QUERY_SET_MAX_QUERIES`). Both machines. No risk. Verify: `$E --headless --steps 5 --particles 525000`,
`gpu_ms_per_step` within ~5% of `wall_ms_per_step`; `SV_DEBUG_PASSES=1` prints ~443 lines a step.

**1. Rebuild every 4 sub-steps in galaxy scenes (S).** `src/sim/mod.rs:294` (`rebuild_every: 8`), `plan()`
`:1623`. 8 was set when a sub-step was 0.125 Myr; rebuilds then land exactly on the sub-steps where bins >= 4
end. Measured with the existing flag at 525k: `--rebuild-every 8` 646 ms a step, `4` 532 (-18%, +22% Myr/s), `2`
550; energy change -2.5e-5 in all three. Desktop at 525k; ~2% at 100k; laptop unknown (its sort was dear in
phase 1: measure at 50k first). The universe showed no ageing at 100k: keep 8 there (per scene in `for_scene`).
Risk: new `state_hash` (other tree, same opening rule); test-disc figures shift if the shared default changes; the
value must come from the config only, never from measured rates. Verify: A/B `--rebuild-every 4|8` at 100k, 525k,
1M, `wall_ms_per_step`; then window `myr_per_s`.

**2. Price force passes by tree age (S); likely the late frames at 1M.** `FORCE_FLOOR` `:487`, `estimate()`
`:1670`, `collect()` `:1833`. The model charges listed share with a 20% floor; the 44k pass (8% of particles)
costs 43 - 56% of a full pass, so its frame overruns about 2x. That happens once per 8 sub-steps, about every 13
frames at 1.2 Myr/s, which is the rate at which x0.85 per late frame against +0.005 per frame (`src/app.rs:443`)
holds the budget near 6.4 of 13.5 ms. Inferred, not measured. Change: one learned force rate per sub-steps-since-
rebuild instead of one. Both machines. No risk to results (`frames_falling_anywhere_change_nothing`). Verify:
`$E --particles 1000000 --exit-after-frames 600`: `worst_frame_ms` under 20, `sim_budget_ms` ~13, `myr_per_s` up
(up to ~2x with item 1).

**3. Split a short list's walk over threads (M).** `shaders/force_particle.wgsl:23`. Up to ~14k threads the pass
time is flat (812 or 14k particles: 1.3 - 1.6 ms at 100k), so 48 of 64 sub-steps are bound by one walk's latency.
Change: T threads a particle, T the largest of 16/8/4/2/1 with `todo_n * T` under a cap (computed in the shader
from `todo_n`, so no read-back decides it). Thread t takes the t-th subtree at depth log2 T (or the shallower
accepted node if its remaining bits are 0); partial sums go to workgroup memory, a barrier, then thread 0 adds
them in t order. Slicing is unchanged (slots = list x T <= n). Gain: after item 1 those sub-steps are ~125 of 530
ms at 525k; halving them is ~12%, ~16% at 100k. Both (laptop: find its thread capacity first). Risk: float sums
regrouped, so a new hash wherever T > 1; same interactions. Verify: force ms on sub-steps 1 - 3 after a rebuild;
energy and force-error tests.

**4. A 32-byte walk record (M).** `force_particle.wgsl:62-79`, `moments.wgsl:113-129`, `karras.wgsl`,
`common.wgsl:281`. An opened node costs 4 dependent loads from 2 buffers (node vec4s 2, 3, 0, then `child`), and
vec4 3 is only needed once the node is accepted. Reorder to vec4 0 = centre of mass, vec4 1 = (mass, radius²,
child x, child y), vec4 2 = (sxx, sxy, syy, softening²), then box and (first, count, H); Karras writes the
children into the node too. Open = 2 adjacent loads, accept = 3. Gain: unknown until prototyped; 10 - 20% of the
walk would be 7 - 14% of the step. Both (less memory traffic). Bit-identical. Verify: full-pass force ms, same
hash.

**5. Gas density beside the gravity walk (M).** `Work::Gas` `:1724`, `hydro.wgsl:98`. Gas on short lists is pure
latency: ~65 ms a step (12% at 525k, 31% at 100k). Density only reads what gravity leaves alone, so run it in the
force dispatch on separate threads (workgroup 256 = 128 gravity + 128 density; 8 storage buffers, at the limit);
`force` stays its own pass. Gain: the density share of that latency, perhaps 6% at 525k and 15% at 100k. Both.
Bit-identical. First add a timer label to split density from force.

**6. Universe (S).** (a) `force_particle.wgsl:94` and `:104` evaluate `short_range` (erfc + 2 exp) twice for
each accepted node: compute once. Bit-identical; a few % of the universe's force. (b) The finder is 15% of GPU
time at 100k and display only (`finder.wgsl:15`): let `link` return at once when the last round changed no
label, or run it less often (`SimConfig::universe`, `every_myr` 100; the user's call). Both machines. Verify:
`$E --scene universe --headless --steps 20 --particles 100000`, `force` and `find`.

**7. Fixed per-sub-step passes (S each, laptop).** `integrate.wgsl:169` `kick` over the list instead of all n
(list length stored at `todo_list[n]` to stay within 8 buffers); flag folded into the first scan level and the
last add into `scatter` (5 dispatches -> 3); `moments.wgsl:68` `reset` replaced by an epoch in the counter.
Together under 2% on the RTX; on the Radeon these passes were ~12% of the frame in phase 1. Bit-identical.

## 3. The plan's candidates (L1, L3 - L6)

- **L3 split walks:** agree (item 3), but second to the rebuild cadence. **Drift nodes instead of refitting:**
  disagree; refit is 6%, the cost is the stale topology, which drifting leaves. **Late frames, "many small
  passes":** no, a 525k frame holds under 20; see item 2.
- **L1 `FORCE_FLOOR` on the Radeon:** it isn't a constant on any GPU; item 2 replaces it.
- **L4:** the gas passes are 14% at 525k, not 30%. Group walk for gas: disagree (latency-bound; the group walk was
  2.5x slower on short lists). Slicing `Work::Gas`: only for pacing (4.2 ms in one piece at 525k).
- **L5:** drop. Wells 3.7 ms, evolve 0.16, feedback 1.9 per 642 ms step.
- **L6:** `pm` is 0.3 ms a step with 512 cells: no radix-4 FFT or 256 cells for the desktop. `find`: cut the work
  (item 6b), not more parts.

## 4. Ruled out

- Neighbour walks started from the leaf's ancestor: boxes overlap after refits, so it isn't exact.
- Fewer Morton bits or radix passes: changes the tree; the sort is 2.6%.
- Indirect dispatch for exact list sizes: five full-n dispatches of compact cost 0.085 ms.
- Subgroup scans: optional feature for under 1%. `--open-small`, compute splat: already measured, no gain.

## 5. Open questions (measure first)

1. With item 0: the stage table per sub-steps-since-rebuild at 525k and 1M, and for pair and group.
2. Node visits per walk on sub-step 1 against 7 (a debug counter): is the bloat confined to the inner few kpc?
3. Late frames at 1M: log estimate against timed ms per item on late frames; expect the force item 4 sub-steps
   after a rebuild.
4. Gas: visits per walk, and how often `density` walks twice (`hydro.wgsl:115`).
5. Laptop: thread capacity (list length where force time starts to rise), and items 1 and 3 at 50k.
6. Universe at late times (clustered): does the tree age there, and what do the finder's rounds cost?
