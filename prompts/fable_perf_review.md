You're doing a performance review of Squareverse v3, a 2D astrophysics sandbox in Rust + wgpu (`squareverse_v3/`: engine in `src/`, about 30 compute and render shaders in `shaders/`). **Don't change any code.** What I need from you is a ranked report of specific optimization opportunities. I'll hand that report to the project's own optimizer agent (`.claude/agents/sim-optimizer.md`), which will measure each one, implement it and verify it. So your job is to find the opportunities and argue for them, not to land them.

## Read first
- `CLAUDE.md`, then `.claude/agents/sim-optimizer.md`. Its rules are the ones your proposals have to fit.
- `PLAN_V3.md`: "Units and numbers", "Laptop backlog" (L3–L6 already list some candidates) and "Progress".
- `squareverse_v3/README.md`: the gravity, gas, wells, universe and "Measured" sections. They describe the pipeline pass by pass.
- The hot code: `src/sim/mod.rs` (the `Work` items, `Sim::advance` frame budget), `src/sort.rs`, `src/timing.rs`, `src/render.rs`, and the shaders `force_particle.wgsl`, `force.wgsl`, `integrate.wgsl`, `moments.wgsl`, `karras.wgsl`, `radix.wgsl`/`scan.wgsl`/`morton.wgsl`, `compact.wgsl`, `hydro.wgsl`, `evolve.wgsl`, `wells_env.wgsl`, `pm.wgsl`, `finder.wgsl`, `squares.wgsl`.

## Pipeline in brief
Positions are 64-bit fixed point. Each step uses block timesteps: dt 2 Myr, 7 levels in the galaxy, so one step is 64 sub-steps. Each sub-step does an open kick and drift, a tree rebuild every 8 sub-steps or a moments refit in between (Morton sort, Karras tree), then compacts the active list, runs a Barnes-Hut force walk (one thread per particle, quadrupoles, a separate dark-matter subtree) and a close kick. Gas runs SPH, the universe scene runs TreePM with a WGSL FFT, and stellar evolution runs once per step. Everything uses integer atomics, so a seed reproduces bit for bit. In the window the frame rate is held fixed, and the sim runs as many `Work` items as fit in about 85% of the frame period (force passes are sliced into up to 64 pieces). **So more speed shows up as more sim time per real second (Myr/s), not as higher fps.**

## Machines and targets
- **Desktop, RTX 2070 Super (top priority):** hold 60 fps and push Myr/s up. These are the current numbers, Windows exe on Vulkan:
  - galaxy at 525k: 2.35 Myr/s, 175 GPU ms per Myr headless;
  - pair: 2.46 Myr/s;
  - group: 3.13 Myr/s;
  - universe: 37.5 Myr/s.
  - At 1M in the galaxy, the window reaches 59.7 fps but its worst frame is 31.7 ms. The late-frame feedback then cuts the budget to 6.4 ms, which gives 1.2 Myr/s. Something the GPU timestamps don't capture is making frames late.
- **Laptop, Ryzen 5 PRO 5650U with an integrated Radeon:** shared memory bandwidth, 15 W, throttles. It runs 60 fps where it can and must never drop below a stable 30. The default count is 50k. Prioritize the desktop, but **flag every proposal that isn't hardware-specific and would also help the laptop** (fewer passes or dispatches, less memory traffic, less CPU-side overhead, algorithmic savings). Mark proposals that are desktop-only, or that would hurt a bandwidth-starved integrated GPU, as such.
- Known hotspots to check first:
  - force passes over the short active lists of the deepest bins: each one costs about one walk's latency, roughly 20% of a full pass;
  - gas passes, about 30% of GPU time;
  - `wells_env` / `swallow`;
  - `pm` and `find` in the universe scene.

## Constraints your proposals must respect
- **Physics and determinism stay fixed:** same `state_hash` for the same seed, backend and GPU, and the tests still pass. If a proposal reorders float sums or changes force accuracy (theta, opening criteria, softening), say so explicitly and say what would have to be checked.
- **Portability:** it has to run on DX12, Vulkan, Metal and GL with wgpu's default limits. A new feature (subgroups, for example) is only acceptable as optional with a fallback.
- **Usage:** keep it static. Read the code; don't run benchmark sweeps, because the optimizer will do the measuring. If one or two short headless runs would settle where the time goes, run them. `cargo build --release` from `squareverse_v3/`, then `target/release/squareverse --headless --steps 5 --particles 100000 --scene galaxy`, and read the per-stage GPU ms. First check that the user's sim isn't running (the check is in `sim-optimizer.md`). Bear in mind that WSL's GL-over-D3D12 numbers are only indicative.

## Report
Write it to `squareverse_v3/PERF_REVIEW_FABLE.md`, no more than about 2 pages, and don't commit it. It should contain:
1. **Where the time goes:** your model of the frame and step cost, per pass and per scene, citing the figures above and any you measured.
2. **Ranked opportunities.** Order them by expected desktop gain ÷ effort. For each one, give:
   - the location, as `file:line` or a function or shader name;
   - what's slow and why (the evidence);
   - the concrete change;
   - the expected gain, with your reasoning;
   - which machines it helps: **Desktop / Laptop / Both**;
   - the risk to determinism or accuracy;
   - effort, S, M or L;
   - **how the optimizer should verify it:** the exact headless or window command and the metric that should move.
3. **Assessment of the existing candidates** in PLAN_V3.md L3–L6: agree, disagree or refine, with your reasons.
4. **Ruled out:** ideas you considered and rejected, one line each, so nobody chases them.
5. **Open questions:** measurements the optimizer should take before it commits to the top items.

Be specific and terse. A short list of well-argued items with real `file:line` references is worth more than a long generic checklist.
