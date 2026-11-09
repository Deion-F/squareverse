# Squareverse v3: plan

Written 2026-11-06. Nothing is built yet; this is the plan to pick up from. `squareverse_v2` stays as it is (frozen,
still runnable). v3 is a fresh project in `squareverse_v3/`.

## Why a new version

v2 is a 2D cell grid with one square particle per cell (falling-sand style, numba on the CPU, optional wgpu). That
design can't stretch from star formation up to galaxies orbiting each other:

- positions snap to cells and speed is capped (VMAX), so orbits are coarse and super wells crowd out the room they
  need (see the TO_DO.md notes on "bigger wells hold more");
- one particle per cell means mass, not just distance, sets the cost;
- the invented rules (mass rungs, collision fusion, VMAX as c) don't scale to real timescales.

v3 keeps the look and the spirit (squares, emergent behaviour, a hands-on sandbox) but uses the methods real
astrophysics codes use, running on the GPU.

## Decisions (user, 2026-11-06)

| Topic | Decision |
|---|---|
| Platform | **Rust + wgpu.** One native executable per OS (Windows: DX12/Vulkan, Mac: Metal, Linux: Vulkan); nothing for users to install. |
| Physics | **Real astrophysics, real units**, with sub-grid models where the scale is too small to resolve. |
| Zoom model | **One shared simulation; zoom only changes the drawing (level of detail).** Every galaxy always runs with all its particles, so the zoomed-in and zoomed-out views are literally the same data. |
| Dimensions | **2D**, with gravity falling off as 1/r² as in 3D (as v2). |
| Star particle | **A setting, "stars per particle", default 1**: each particle is one real star (mass from the real IMF). Higher values make each particle a star cluster, so galaxies can be Milky Way mass. |
| Dark matter | **Coarse DM particles**, invisible by default (toggle to draw), forming halos and the cosmic web. |
| Start | **Both**: placed-galaxy presets, plus an "early universe" preset where near-smooth gas + DM collapses on its own. |
| Planets | **Star system view**: planets are sub-grid, decided by the heavy elements in the gas the star formed from; selecting a star opens a third zoom level that shows them. |
| Time | **One universe clock; zoom suggests the speed** (e.g. 1 Myr/frame zoomed out, ~10 kyr/frame on a galaxy), and the user can override it. Per-particle adaptive steps. |
| Binaries | **Hybrid**: wide pairs are two real particles; tight pairs are one particle carrying an exact Kepler orbit (drawn as two in the star system view), which can merge, swap partners or be torn apart. |
| Tools | Place galaxy; place super well / pour gas; select & inspect (follow, zoom in, edit, drag); delete / kick; **save the current tools + universe state as a new preset**. |
| Frame rate | **Aim for 60 fps, with a 30 fps option** for weaker machines. Drawing interpolates between sim steps; the sim takes as many steps as fit in the frame budget. |
| Look | **Squares, coloured realistically**: stars by surface temperature (red dwarf → blue giant), gas by temperature/density, additive glow (HDR + tonemap) so dense regions brighten. |
| Small super wells | **Both routes**: stellar black holes left by massive stars sink and merge in dense clusters into intermediate wells; rarely, dense metal-poor gas collapses straight into one. |
| Elements | **Five groups per particle**: H, He, C/N/O (ices), Mg/Si (rock), Fe. |
| v2 | **Kept frozen**; the Claude helper agents are rewritten for v3. |

On the user's request to start the two views separately: because of the "one sim" decision, v3 is **one engine**,
but the galaxy scale (phases 2–4) and the universe scale (phase 5) get **their own presets, test scenes and tuning
passes**. They are joined in phase 6. Phase 5 can start as soon as phase 1 is done, in parallel with 2–4.

## Units and numbers

- Length in parsecs (pc), mass in solar masses (M☉), time in megayears (Myr). G = 4.50e-3 pc³ / (M☉ Myr²);
  1 pc/Myr ≈ 0.98 km/s; c ≈ 306,600 pc/Myr.
- **Positions are 64-bit fixed point** per axis, stored on the GPU as two u32 words (hi, lo) with carry, not
  floats. (Corrected 2026-11-06: 32 bits over a 20 Mpc box is only ~0.005 pc, ~1,000 AU, too coarse near a super
  well and lossy when rounding small sub-steps.) 64 bits give ~1e-12 pc everywhere, the same near the centre of a
  galaxy as in the voids, and integer wrap-around gives the periodic universe for free. Differences are taken in
  integers, then converted to f32 for forces (GPUs are slow at f64). Velocities and everything else are f32.
- **Two target machines** (user, 2026-11-06): the desktop (RTX 2070 Super, 8 GB) at 60 fps, and the laptop
  (Ryzen 5 PRO 5650U, integrated Radeon, WSL2) at 60 fps if possible and never below a stable 30. The default
  particle count is picked for the GPU found (`src/budget.rs`, provisional until phase 1 measures both), and
  the 30 fps setting exists for the laptop. Desktop budget, to be measured in phase 1: ~2–4M particles at 60 fps (for
  example 20–50 galaxies), at ~60–100 bytes per particle; the laptop's is likely 5–10x less. Quality settings:
  Low (~250k), Medium (~1M), High (2–4M), with the default chosen per machine.

## Particles

One structure-of-arrays set of GPU buffers; a `kind` field picks the physics.

| Kind | Holds | Notes |
|---|---|---|
| Gas (SPH) | mass, internal energy, density, smoothing length, 5 element fractions | merges in thin hot gas, splits in dense gas (adaptive resolution) |
| Star | mass, birth time, elements, binary data (companion mass, a, e, phase) | one star, or a population if stars per particle > 1 |
| Remnant | white dwarf / neutron star / stellar black hole | stellar black holes can grow into intermediate super wells |
| Super well (black hole) | mass, spin (angular momentum), accretion rate | sink particle; small numbers, smallest timesteps |
| Dark matter | mass | heavy, with large softening (see Gravity) |

Common to all: id, position, velocity, timestep bin, flags.

## Physics by scale, and what gets approximated

The guiding rule: compute exactly what you can see at the current scale, and replace what you can't resolve with a
model that gives the right averages.

### Gravity
- **TreePM.** A 2D quadtree on the GPU (Morton codes → radix sort → tree → Barnes-Hut walk, opening angle ~0.5–0.7)
  for short range, and from phase 5 a particle-mesh (FFT) part for long range in the periodic box. Force softening
  per kind; for a 2D disc the softening also stands in for disc thickness, which keeps the disc from tearing itself
  into unphysical rings.
- **Dark matter acts only through a smoothed field** (large softening), so a few heavy DM particles don't kick
  1 M☉ stars about (2-body heating).
- **Adaptive steps:** hierarchical power-of-two timestep bins (kick-drift-kick leapfrog); each particle steps as often
  as its own acceleration / gas sound speed needs. The tree is rebuilt each base step and only refitted for
  sub-steps. Close pairs near a super well take tiny steps without slowing everything else.
- Newtonian only. Super well horizons are far below resolution (4e-7 pc for 4e6 M☉), so they are drawn at a minimum
  size; swallowing happens inside an accretion radius. Super well pairs that get closer than resolution spiral in by
  the gravitational-wave formula (Peters, as v2 step 6) and merge with spin from their angular momentum.

### Gas
- **SPH** (Wendland kernel, ~20–30 neighbours in 2D), neighbour search on the same Morton-sorted order.
- **Cooling** from a tabulated cooling function of temperature and metallicity, with a temperature floor; an optional
  uniform UV background in the early-universe preset.
- **Merge / split:** gas particles merge where the gas is thin and hot (the gas between galaxies, so it never needs
  millions of particles) and split where it is dense, limiting the mass ratio between neighbours to keep SPH accurate.
- No magnetic fields, no radiative transfer (see Feedback).

### Stars: birth, life, death
- **Birth:** gas that is dense, cold, collapsing and Jeans unstable turns into stars at a set efficiency per
  free-fall time; the gas particle is split into stars drawn from the IMF (0.1–100 M☉) adding up to its mass.
- **Life:** no star interiors are simulated. Lifetime, luminosity and temperature come from fitting formulas of mass
  and metallicity (main sequence → giant → remnant). Fusion shows up as composition: what a star returns to the gas
  when it dies.
- **Death and enrichment:** below ~8 M☉: a white dwarf, with the envelope (rich in C/N/O) returned as gas; 8–25 M☉:
  core-collapse supernova (10⁵¹ erg, O/Mg/Si/Fe yields), leaving a neutron star; above ~25 M☉: a stellar black hole.
  Type Ia supernovae (Fe) come from white dwarfs in tight binaries. Each generation forms from gas enriched by the
  last.
- **Feedback:** supernova energy goes into the neighbouring gas as stochastic thermal injection (so it doesn't cool
  away at once at low resolution); massive stars heat and ionise the gas around them through a Strömgren-sphere
  approximation instead of real radiative transfer.
- With stars per particle > 1, a star particle is a population, and the same tables are applied statistically
  over time.

### Binaries
- Wide pairs are two particles. Tight pairs are one particle with an exact Kepler orbit. The binary fraction and
  orbits at birth follow observed distributions for the star's mass. Close encounters harden, soften, disrupt or swap
  pairs by encounter rates (later option: unpack a tight pair into two particles while a perturber is close). Mass
  transfer and mergers by simple rules; this is the route to Type Ia supernovae.

### Super wells (black holes)
- **Central:** a sink particle; Bondi accretion capped at the Eddington rate; AGN feedback heats nearby gas. It
  dominates only the very centre; the galaxy's rotation comes from the halo + disc, as in real galaxies.
- **Small ones in the arms:** stellar black holes sink in dense clusters (mass segregation is resolved when stars
  per particle is 1) and merge inside a capture radius into intermediate wells; and direct collapse, where a dense,
  metal-poor gas clump above a mass threshold becomes a seed well. Either can sink to the centre (dynamical
  friction, with a sub-grid correction when it is under-resolved) and merge with the central one.

### Universe scale
- Periodic box, TreePM. The early-universe preset uses comoving coordinates with a scale factor a(t) (expansion) and
  starts from Zel'dovich-approximation initial conditions drawn from a power spectrum. Placed-galaxy presets use a
  static box.
- The gas between galaxies is the same SPH gas, merged into heavy particles where it is thin.
- A **galaxy finder** (friends-of-friends on the GPU every few steps) labels galaxies, their super wells and
  totals, and drives "select a galaxy".

### Planets (star system view)
- Not simulated as particles. Each star's system is generated deterministically from its id, mass and the five
  element groups it was born with (giant-planet chance rising with Fe; rocky planets need Mg/Si; ice giants need
  C/N/O), so it costs no memory and is the same every time it is looked at. Systems are destroyed or changed when
  the star dies (planets round white dwarfs may survive). The view shows analytic orbits, including a tight
  companion, on years-per-second time while the universe clock runs at its own speed.

## Drawing and zoom

- One continuous camera from the universe down to a single galaxy's centre; "same thing at every zoom" holds
  because there is only one set of particles.
- Every particle is drawn as a square. At small zoom a square is ≤ 1 pixel and they add up (HDR, additive) into
  glowing galaxies, with gas as a density splat coloured by temperature. As you zoom in, squares grow by luminosity,
  and detail overlays (super well marks, binaries, remnants) fade in. DM is drawn only when toggled.
- Drawing interpolates between sim steps at 60 fps (30 fps option); the sim fills the rest of the frame budget.
- Selecting a galaxy follows it and zooms in, with the suggested speed changing smoothly; selecting a star at close
  zoom opens the star system view.

## Tech stack

- Crates: `wgpu` (compute + rendering), `winit` (window), `egui` + `egui-wgpu` + `egui-winit` (menu: sliders,
  toggles, (i) help, keyboard shortcuts, carrying over v2's menu conventions), `glam`, `bytemuck`, `serde` +
  `postcard` and `lz4_flex` (saved universes and presets, pure Rust), `rand_pcg`, `clap`.
- WGSL has no f64 and no float atomics: deposits (mesh, density sums) use integer fixed-point atomics, which also
  makes runs reproducible from a seed (stable sorts, no order-dependent float sums), and that is what testing needs.
- **Development from WSL:** build the Windows executable (`x86_64-pc-windows-gnu` with mingw-w64, or `cargo-xwin`)
  and run the `.exe` from WSL, so it uses DX12 / Vulkan directly instead of WSL's Mesa D3D12 translation. Linux
  builds run in WSL for headless tests. Mac builds come from a GitHub Actions macOS runner; they are unsigned, so
  the first start needs right-click → Open.
- Minimum hardware: any GPU with compute shaders (DX12 / Vulkan / Metal; GLES 3.1 through wgpu's GL backend).
- **Headless mode** for agents and tests: `squareverse --headless --preset X --steps N --report out.json`
  (timings per pass from GPU timestamp queries, conserved totals, star formation rate, metallicity, galaxy list).

## Phases

Each phase ends with measurements (via the sim-experimenter) and tests passing. Global numbers in the acceptance
lines are targets, to be confirmed in phase 1.

0. **Setup.** `squareverse_v3/` cargo project; window + egui + wgpu; Windows build from WSL; headless runner;
   rewrite the helper agents for v3 (sim-experimenter → headless JSON runs, test-runner → `cargo test` + headless
   checks, sim-optimizer → GPU timestamp profiling, docs-sync → v3 README) and update CLAUDE.md.
1. **Gravity core.** Fixed-point positions, GPU radix sort, quadtree, Barnes-Hut, block timesteps, square
   rendering with zoom / pan, frame-rate setting. Tests: two-body orbit energy drift, force error vs direct sum,
   reproducibility from a seed. *Accept:* 1M particles at ≥ 60 fps on the 2070 Super; record the 4M figure.
2. **Galaxy, collisionless** (galaxy scale). Galaxy generator in equilibrium (disc + bulge + smoothed DM halo +
   central super well; velocities from the potential, Toomre Q setting); IMF stars with lifetimes and colours;
   super well sink. *Accept:* flat rotation curve, disc stable for ≥ 10 rotations, spiral arms in a cold disc.
3. **Gas and star cycle** (galaxy scale). SPH, cooling, star formation by gas splitting, stellar deaths with element
   yields, feedback, gas merge / split, remnants, central super well accretion + AGN. *Accept:* star formation rate
   vs gas density near the observed (Kennicutt-Schmidt) relation; several generations with rising metallicity; no
   runaway cooling or blow-out.
4. **Binaries and small super wells** (galaxy scale). Tight-binary sub-grid, encounters, Type Ia; stellar black
   holes → intermediate wells; direct collapse seeds; sinking to the centre; super well pairs and gravitational-wave
   merging.
5. **Universe scale** (can run alongside 2–4). Periodic box, PM long range (WGSL FFT) → TreePM, comoving expansion,
   Zel'dovich start, intergalactic gas with merging, galaxy finder, placed-galaxy presets (pair on a collision
   course, group). *Accept:* cosmic web forms from the early-universe preset; galaxy pairs merge on sensible
   timescales; 20–50 galaxies at the target frame rate.
6. **Join the views.** Continuous zoom with level of detail, zoom-suggested speed, select → follow → zoom.
   *Accept:* zooming in and out changes nothing in the physics (same totals and same state as an unzoomed headless
   run from the same seed).
7. **Star system view.** Deterministic planet generation from composition, the third zoom level, tight binaries
   drawn.
8. **Tools, presets, release.** All the tools, save / load universe state and "save as preset", menu polish,
   README, release builds for Windows / Linux / Mac, then `/optimize` if the user asks.

## Risks to watch

- **Razor-thin 2D discs** are more unstable than real ones: rely on softening as thickness and a Toomre Q setting;
  measure in phase 2.
- **Heavy DM next to 1 M☉ stars** heats discs: DM is force-smoothed; check disc thickness / dispersion growth over
  time.
- **Feedback at low resolution** tends to cool away (overcooling): use stochastic injection; tune in phase 3.
- **With 1 star per particle galaxies are dwarf-sized** (~10⁵–10⁶ M☉): the presets should state this, and the stars
  per particle setting covers big galaxies.
- **Writing an FFT and a GPU tree in WGSL** is the largest piece of engine work: keep a CPU reference implementation
  for tests.
- **Mac / Metal limits** (storage buffers per shader stage etc.): keep binding counts within wgpu's default limits.

## Carried over from v2

Ideas that transfer: the menu style ((i) help on every setting, ◀ ▶ fine steps, keyboard shortcuts, H for help,
Advanced fold), the status figures in the corners, conserved-totals checks in tests, and the super well pair
physics from step 6 (spin from angular momentum, Peters inspiral). The open v2 TO_DO items (merge-rate cap, fusion
ladder tuning, heavy super well speed) are superseded by v3's design, not carried over.

## Laptop backlog (user, 2026-11-08: collected here, run in one go later with the optimizer)

The user no longer switches to the laptop after each change. Every check the laptop (Ryzen 5 PRO 5650U, integrated
Radeon, WSL2) needs goes here as it comes up, with what to change based on the result. When all the work is done,
the sim-optimizer runs through this list on the laptop. Each item:
- **What:** the commands to run;
- **Look for:** what to read from the output;
- **Then:** the change to make, and in which file.

Setup, once (in WSL from the repo root):

```
git pull
cd squareverse_v3 && cargo build --release --target x86_64-pc-windows-gnu
E=target/x86_64-pc-windows-gnu/release/squareverse.exe
$E --list-adapters
```

### L1. Block steps and frame budget, test disc (phase 1b)

- **What:**

  ```
  for p in 25000 50000 100000; do $E --scene disc --headless --steps 10 --particles $p | grep -E '"(name|backend|particles|gpu_ms_per_myr|force_evals_per_myr)"' | tr -d '\n '; echo; done
  $E --scene disc --exit-after-frames 600
  $E --scene disc --fps 30 --exit-after-frames 300
  $E --scene disc --particles 100000 --exit-after-frames 600
  ```

- **Look for:**
  - fps at the target, and the worst frame under ~20 ms (60 fps) or ~37 ms (30 fps);
  - `myr_per_s` and `sim_budget_ms`;
  - `gpu_ms_mean` by pass.
- **Then:**
  - If fps misses the target although `sim_budget_ms` is small: the overhead between passes (the Intel UHD 630
    showed this on the desktop). Check that `budget_scale` (`src/app.rs`) settles, and reduce the passes per
    sub-step.
  - If the worst frame is long while the mean is fine: the force floor (`FORCE_FLOOR`, `src/sim/mod.rs`, 0.2 of a
    full pass, measured on the RTX) may differ on the Radeon. Measure the per-pass times with
    `SV_DEBUG_PASSES=1 WSLENV=SV_DEBUG_PASSES $E --scene disc --headless --steps 3 --particles 50000` and set it
    from the deepest-bin-only sub-steps.

### L2. The galaxy (phase 2)

- **What:**

  ```
  for p in 25000 50000 100000; do $E --headless --steps 10 --particles $p | grep -E '"(name|backend|particles|gpu_ms_per_myr|force_evals_per_myr)"' | tr -d '\n '; echo; done
  $E --exit-after-frames 600
  $E --fps 30 --exit-after-frames 300
  $E --particles 100000 --exit-after-frames 600
  $E --particles 25000 --exit-after-frames 600
  ```

- **Look for:**
  - fps and the worst frame (as L1);
  - `myr_per_s` at each count. One rotation of the disc at 8 kpc takes ~200 Myr.
- **Then:**
  - Set the integrated default in `src/budget.rs` to the largest count giving at least ~2 Myr/s (a rotation in
    under two minutes) at 60 fps, or at 30 if 60 can't give 1 Myr/s.
  - Below 25k the galaxy gets noisy: then let the integrated GPU default to 30 fps instead
    (`budget::default_fps`, to add).

### L3. For the optimizer, from the desktop (no laptop needed, but the same pass)

- **The galaxy's sim speed:** 170 GPU ms per Myr at 500k on the RTX, 3.8 Myr/s in the window.
  - Most of it is force passes over the short lists of the deep bins (7 levels), each costing about one walk's
    latency (`FORCE_FLOOR`).
  - Candidates: split a particle's walk over several threads on short lists; drift tree nodes instead of
    refitting each sub-step.
- **Late frames at 1M in the galaxy window:** 59.7 fps, worst frame 31.7 ms. The late-frame feedback shrank the sim
  budget to 6.4 ms, giving 1.2 Myr/s. Find what the timestamps miss there (many small passes per frame?).

### L4. Gas (phase 3), for the optimizer

- **What:** after L2, the same commands. The galaxy now has gas. Also
  `$E --headless --steps 10 --particles 50000 | grep -E '"(gpu_ms_per_myr|gas)"'` for the gas passes' share.
- **Look for:** `myr_per_s` against L2's figures. On the RTX, gas slowed the galaxy 3.8 -> 2.2 Myr/s at 500k (the
  gas passes are ~30% of the GPU time, and gas adds particles in deep bins).
- **Then:**
  - Set the integrated default (`src/budget.rs`) from the galaxy-with-gas figures, not L2's.
  - If the gas passes dominate on the Radeon, candidates are a group walk for the gas density and force (the gas is
    spatially sorted), and slicing the gas passes like the force pass (`Work::Gas` is one item).

### L5. Super wells and binaries (phase 4), for the optimizer

- **What:** nothing new to run; L2 / L4's commands cover it (the galaxy now has accreting wells).
- **Look for:** the `evolve` stage in `gpu_ms_mean`.
- **Then:** if `evolve` is large, look at `wells_env.wgsl surroundings` (one thread a well, a tree walk of 500 pc)
  and `swallow` (every particle loops over the wells, up to 256).

### L6. The universe, galaxy pair and group (phase 5), for the optimizer

- **What:**

  ```
  for sc in universe pair group; do $E --scene $sc --headless --steps 20 --particles 100000 | grep -E '"(gpu_ms_per_myr|pm|find|wells|feedback)"' | tr -d '\n '; echo; done
  for sc in universe pair group; do $E --scene $sc --exit-after-frames 900; $E --scene $sc --fps 30 --exit-after-frames 450; done
  ```

- **Look for:** fps and the worst frame; `myr_per_s` (the universe needs ~13,400 Myr to reach today: at 30 Myr/s
  that is 7.5 minutes); the `pm` (mesh FFT), `find` (galaxy finder) and `wells` stages in `gpu_ms_mean`.
- **Then:**
  - Set the integrated GPU's default particles per scene (`src/budget.rs`, today one count for every scene): the
    universe wants as many as hold 30 fps with at least ~15 Myr/s.
  - If `pm` is large on the Radeon: 256 mesh cells instead of 512 (`SimConfig::universe`, `pm_cells`; the force
    error is about the same, `tree_pm_matches_the_tree`), or a radix-4 FFT in `shaders/pm.wgsl`.
  - If one `find` part makes a frame late: more, smaller parts (`FIND_PARTS`), or fewer linking rounds.
  - **Desktop numbers to compare (RTX 2070 Super, Vulkan, 2026-11-09, 525k incl. 5% spares):** galaxy 60.0 fps,
    worst 17.3 ms, 2.35 Myr/s; pair 60.0, 17.6, 2.46; group (24 galaxies) 60.0, 17.6, 3.13; universe 60.0, 17.4,
    37.5 Myr/s.

### L7. Selecting, the star system view and the tools (phases 6 - 8)

- **What:** `$E` (the galaxy), then: click a star (it is followed; the panel shows it), press "Star system", zoom
  with the wheel, press Esc twice; tool 4 (gas) and click in the disc; tool 6 (delete) and drag; F5 then F9 (quick
  save and load). Also `$E --scene group`: click a galaxy's ring when zoomed out.
- **Look for:** whether frames hitch while following (one small pass a frame), how long placing gas and deleting
  pause the window (they finish the step under way first), and the save / load time at the default count.
- **Then:** if the tools' pause is long (more than ~0.5 s), apply them at the next step boundary the sim reaches
  by itself instead of finishing the step at once (`Sim::finish_step` in `brush` / `spawn`).

## Progress

Phase 0 (started 2026-11-06):

- [x] Toolchain: rustup in `~/.cargo` (stable 1.99.1, targets linux-gnu and windows-gnu); `build-essential` and
  `mingw-w64` installed by the user. (A Zig linker stood in before that; no longer needed.)
- [x] `squareverse_v3/` cargo project (wgpu 30, winit 0.30, egui 0.37 with `default_fonts`, which 0.37 no longer
  turns on by itself). `src/fixed.rs` + `shaders/fixed.wgsl` (64-bit fixed point), `src/gpu.rs` (adapter pick: DX12
  first on Windows; WSL D3D12 env set up as v2 did), `src/timing.rs` (GPU timestamps per pass, non-blocking),
  `src/sim/` (phase-0 workload: orbits round one point mass, KDK; IMF masses and main-sequence colours),
  `src/render.rs` (squares, HDR additive, tonemap), `src/ui.rs` + `src/app.rs` (window, menu, HUD, keys, zoom /
  pan, 60 / 30 fps pacing), `src/headless.rs` (`--headless --report --snapshot`), `src/budget.rs`.
- [x] Tests: `cargo test` (9 pass): fixed-point round trip / wrap / sub-AU separations, IMF, main sequence, seed
  reproducibility, energy (-4e-7 over 2,000 steps), GPU vs CPU f64 reference across the box edge (worst 3e-4 pc after
  20 steps, 181 particles crossing). Clippy clean.
- [x] Windows `.exe` built from WSL (`cargo build --release --target x86_64-pc-windows-gnu`) and run natively:
  RTX 2070 Super on DX12, 1M particles, window 59.9 fps (GPU 0.68 step + 2.56 draw ms a frame).
- [x] Integrated-GPU stand-in: the desktop's Intel UHD 630 (weaker than the laptop's Radeon): 250k particles
  59.2 fps at the 60 target, 29.9 at 30 (GPU ~11.6 ms a frame, 8.2 of it drawing). It crashes on Vulkan (old driver),
  hence DX12 first. Headless step: 0.60 ms at 250k, 4.4 ms at 1M (RTX: 0.032 / 0.13).
- [x] Helper agents rewritten for v3 (sim-experimenter, test-runner, sim-optimizer, docs-sync, /optimize: they
  check the Windows exe with `tasklist.exe` too, and name the machine), CLAUDE.md updated, `squareverse_v3/README.md`.
- [x] **Laptop check** (2026-11-06; results below). Steps, in WSL from the repo root:
  1. Once, paste these two lines into the WSL terminal (the first asks for your password), then open a new
     terminal:

     ```
     sudo apt update && sudo apt install -y build-essential mingw-w64
     curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal -t x86_64-pc-windows-gnu
     ```

  2. `cd squareverse_v3 && cargo build --release --target x86_64-pc-windows-gnu`
  3. `E=target/x86_64-pc-windows-gnu/release/squareverse.exe; $E --list-adapters`
  4. Window at the default count, 60 then 30 fps target (each prints one JSON line):
     `$E --exit-after-frames 600` and `$E --fps 30 --exit-after-frames 300`
  5. If 60 isn't held: `$E --particles 100000 --exit-after-frames 600` to see where it is.
  6. Headless step cost: `$E --headless --steps 300 --particles 250000 | grep -E '"(name|backend|gpu_ms_per_step)"'`

### Laptop results (Ryzen 5 PRO 5650U, integrated Radeon)

| Date | Command | Adapter / backend | Particles | fps (target) | Worst frame ms | GPU ms: step / draw / tonemap / ui |
|---|---|---|---|---|---|---|
| 2026-11-06 | `--exit-after-frames 600` | AMD Radeon (integrated) / Dx12 | 250,000 | 59.7 ( 60) | 21.1 | 3.04 / 4.33 / 1.00 / 0.01 |
| 2026-11-06 | `--fps 30 --exit-after-frames 300` | AMD Radeon (integrated) / Dx12 | 250,000 | 30.1 ( 30) | 34.3 | 4.81 / 5.20 / 1.30 / 0.01 |
| 2026-11-06 | `--headless --steps 300 --particles 250000` | AMD Radeon (integrated) / Dx12 | 250,000 | n/a | n/a | step only: 1.17 |
| 2026-11-06 | `--particles 500000 --exit-after-frames 600` | AMD Radeon (integrated) / Dx12 | 500,000 | 57.7 ( 60) | 34.9 | 5.10 / 8.46 / 1.61 / 0.02 |
| 2026-11-06 | `--particles 1000000 --exit-after-frames 600` | AMD Radeon (integrated) / Dx12 | 1,000,000 | 33.1 ( 60) | 51.7 | 10.12 / 16.76 / 0.96 / 0.01 |
| 2026-11-06 | `--particles 1000000 --fps 30 --exit-after-frames 300` | AMD Radeon (integrated) / Dx12 | 1,000,000 | 30.0 ( 30) | 36.7 | 10.30 / 17.37 / 1.09 / 0.02 |
| 2026-11-06 | `--headless --steps 300 --particles 1000000` | AMD Radeon (integrated) / Dx12 | 1,000,000 | n/a | n/a | step only: 3.57 |

Result: the 250,000 default for integrated GPUs holds 60 fps (and a stable 30 at the 30 target); 500k just misses
60, with drawing the largest pass. Driver 31.0.21924.4004 (DX12); Vulkan and GL adapters are also listed.

Target: 60 fps if possible, never below a stable 30 at the default count (`src/budget.rs`: 250,000 for an
integrated GPU). If it misses, lower that default for integrated GPUs, and note it here.

Notes for phase 1:

- Drawing dominates on integrated GPUs (6 vertices per particle, instanced). Try a compute splat (atomic adds into
  a fixed-point accumulation buffer, then tonemap) when particles are <= 1 px, and keep quads for bigger squares.
- The integrated GPU is ~20-30x slower than the RTX on the same work: measure the gravity budget on it, not just on
  the desktop, and let `src/budget.rs` follow measurement.
- The window's `--exit-after-frames` JSON line (fps, worst frame, GPU ms per pass) is the quick fps check on any
  machine.

Phase 1 (started 2026-11-06):

- [x] Self-gravity on the GPU: Morton keys, stable radix sort, gather, Karras tree, node moments (atomic records),
  per-particle walk with monopole + quadrupole, KDK. All passes within 8 storage buffers; deterministic.
- [x] Refit between rebuilds (`rebuild_every` 4), `--theta`, `--walk group|particle`, `--rebuild-every`; headless
  `gpu_ms_by_stage` (integrate / sort / gather / tree / force).
- [x] Tests: force vs direct sum (both walks, two thetas), two-body orbit, momentum, energy, seed, box edge.
- [x] Vulkan preferred on Windows (DX12 + FXC takes ~170 s to compile the shaders; Intel keeps DX12).
- [x] Measured (see squareverse_v3/README.md): RTX 500k 12.2 ms a step (window 60.0 fps), 1M 23.1 ms; Intel UHD 630
  100k 36.4 ms. Defaults now 500k discrete, 50k integrated.
- [x] DXC (user approved 2026-11-06): Microsoft's `dxcompiler.dll` + `dxil.dll` v1.9.2609 in
  `squareverse_v3/vendor/dxc/` (sha256 checked against the release's digest, licences included); `build.rs` copies
  them beside the Windows exe and `gpu::instance_descriptor` points DX12 at them. DX12 start-up: Intel UHD 630
  168 -> 6.8 s, RTX 166 -> 3.8 s. Vulkan stays first on non-Intel GPUs (RTX 500k: 12.2 ms a step on Vulkan, 16.1 on
  DX12).
- [x] **Laptop check, phase 1** (2026-11-06; results below). In WSL from the
  repo root, after `git pull`:

  ```
  cd squareverse_v3 && cargo build --release --target x86_64-pc-windows-gnu
  E=target/x86_64-pc-windows-gnu/release/squareverse.exe
  $E --list-adapters
  for p in 25000 50000 100000; do $E --headless --steps 40 --particles $p | grep -E '"(name|backend|particles|gpu_ms_per_step)"' | tr -d '\n '; echo; done
  $E --exit-after-frames 600
  $E --fps 30 --exit-after-frames 300
  $E --particles 100000 --exit-after-frames 600
  ```

  (The first lines are the headless step cost at 25k / 50k / 100k; the last three print one JSON line each: fps,
  worst frame, GPU ms by stage.) Set the integrated default in `src/budget.rs` to the largest count that holds 60
  fps, or at least a stable 30.

### Laptop results, phase 1 (self-gravity)

| Date | Command | Adapter / backend | Particles | fps (target) | Worst frame ms | GPU ms a step / by stage |
|---|---|---|---|---|---|---|
| 2026-11-06 | `--headless --steps 40` | AMD Radeon (integrated) / Vulkan | 25,000 | n/a | n/a | 4.47 a step |
| 2026-11-06 | `--headless --steps 40` | AMD Radeon (integrated) / Vulkan | 50,000 | n/a | n/a | 9.29 a step |
| 2026-11-06 | `--headless --steps 40` | AMD Radeon (integrated) / Vulkan | 100,000 | n/a | n/a | 20.34 a step |
| 2026-11-06 | `--exit-after-frames 600` | AMD Radeon (integrated) / Vulkan | 50,000 (default) | 59.9 ( 60) | 28.8 | integrate 0.29, tree 0.77, force 7.55, draw 0.26, tonemap 0.73 |
| 2026-11-06 | `--fps 30 --exit-after-frames 300` | AMD Radeon (integrated) / Vulkan | 50,000 (default) | 30.1 ( 30) | 34.4 | integrate 0.33, tree 0.73, force 7.23, draw 0.28, tonemap 1.09 |
| 2026-11-06 | `--particles 75000 --exit-after-frames 600` | AMD Radeon (integrated) / Vulkan | 75,000 | 50.8 ( 60) | 43.4 | integrate 0.54, tree 1.33, force 12.88, draw 0.38, tonemap 0.91 |
| 2026-11-06 | `--particles 100000 --exit-after-frames 600` | AMD Radeon (integrated) / Vulkan | 100,000 | 39.6 ( 60) | 38.5 | integrate 0.74, sort 9.25, gather 0.42, tree 1.69, force 17.55, draw 0.46, tonemap 0.87 |

Result: the 50k integrated default holds 60 fps (worst frame 28.8 ms); 75k and 100k miss 60 (both above 30, not run at the 30 target), so
the default stays at 50k. The force walk is most of the frame. Vulkan is now picked first (was DX12 in phase 0).
The Radeon now beats the UHD 630 stand-in at compute (20.3 vs 36 ms a step at 100k). In the 100k run a 9.25 ms
`sort` stage shows up that the smaller runs don't report: worth a look when tuning.

- [x] Adaptive (block) time steps (2026-11-07):
  - **Steps:** dt 2 Myr, bins 0 - 4 (`levels` 5, down to 0.125 Myr), 16 sub-steps a step.
  - **Step rules:** each particle steps at most sqrt(2 eta eps / |a|) (eta 0.025) and at most eta_jerk |a| / |da/dt|
    (eta_jerk 0.05; the galaxy's pull dominates |a|, so only the change sees encounters).
  - **Per sub-step:** every particle drifts; the tree is refitted (rebuilt every 8 sub-steps); the particles whose
    step ends get listed (compact) and get forces.
  - **Energy over 250 Myr, 20k particles, seeds 1 / 2 / 3:** -1.3e-4 / -6.4e-5 / -4.5e-5 at 2.55 force evaluations
    per particle per Myr. The old fixed 0.25 Myr step gave 9e-6 / -3.6e-4 / 6.7e-5 at 4.
  - **Speed at 1M on the RTX:** 91 GPU ms per Myr against 105 for the fixed 0.25 step. The fixed 0.125 step, the
    same inner resolution, would take ~210.
  - **Why only modest:** a force pass over a few particles costs about one walk's latency, ~20% of a full pass,
    however few particles it has. So the sub-steps for the deepest bin are dear. `--levels 4` gives 71 ms per Myr
    at coarser inner steps.
  - **Tried and dropped:**
    - the group walk on short lists (2.5x slower);
    - listing the active particles was kept for the slicing, but it did not change the force time;
    - letting nodes under the softening act whole (`--open-small`; no faster, since the clumps weren't the cost).
  - **Next for speed:** split one particle's walk over several threads on short lists (/optimize).
- [x] Spread a step over several frames (2026-11-07), `Sim::advance`:
  - **How it works:** each sub-step is `Work` items. The window gives the sim a GPU budget each frame (85% of the
    period, less the drawing), and the sim runs the items that fit, slicing a force pass into up to 64 pieces.
  - **Cost model:** costs per item are learned from timestamps, and a force dispatch costs at least 20% of a full
    pass.
  - **Overruns:** an item may start when 4/5 of it fits; the overrun comes off the next frame. Frames that arrive late
    shrink the budget.
  - **Drawing:** particles are drawn moved along their velocity to a smooth display clock.
  - **Determinism:** the test `frames_falling_anywhere_change_nothing` runs ~2,800 tiny frames and gets the same
    hash as a whole run.
  - **Speed setting:** the menu's speed is now Myr/s (0.5 - 200 or max).
- [x] Drawing on integrated GPUs, compute splat: **not needed for now.**
  - Drawing measured 0.26 ms a frame at 50k on the laptop, and on the RTX 0.7 ms at 1M and 2.6 at 4M. Gravity is
    the cost.
  - Revisit in phase 6 (level of detail) if drawing grows.
- [x] Phase 1 acceptance (2026-11-07, RTX 2070 Super, Vulkan, window, speed max):

  | Particles | fps | Worst frame | Sim speed |
  |---|---|---|---|
  | 1M | 60.0 | 17.3 ms | 7.4 Myr/s |
  | 4M | 60.0 | 17.3 ms | 1.8 Myr/s |
  | 500k | 59.9 | 18.7 ms | 15.3 Myr/s |

  On the Intel UHD 630, 50k gives 58.9 fps (its frames are copied to the RTX, which drives the monitors).
- [ ] **Laptop check, phase 1b:** moved to the laptop backlog (L1) above.

### Laptop results, phase 1b (block steps, frame budget)

| Date | Command | Adapter / backend | Particles | fps (target) | Worst frame ms | Myr/s | GPU ms per Myr (headless) / by pass |
|---|---|---|---|---|---|---|---|
| | `--headless --steps 10` | | 25,000 | n/a | n/a | n/a | |
| | `--headless --steps 10` | | 50,000 | n/a | n/a | n/a | |
| | `--headless --steps 10` | | 100,000 | n/a | n/a | n/a | |
| | `--exit-after-frames 600` | | (default) | ( 60) | | | |
| | `--fps 30 --exit-after-frames 300` | | (default) | ( 30) | | | |
| | `--particles 100000 --exit-after-frames 600` | | 100,000 | ( 60) | | | |
| | `--particles 250000 --exit-after-frames 600` | | 250,000 | ( 60) | | | |

Phase 2 (started 2026-11-08):

- [x] **Particle kinds** (star, dark matter, super well, white dwarf, neutron star, black hole, swallowed) in the top
  4 bits of the id word.
  - **Softening by kind:** a pair uses the larger of the two. Stars 50 pc in the galaxy, dark matter 1,000, wells 50.
  - **A tree per softening class:** a dark matter bit above the 46-bit Morton key splits the tree at the root.
    - Mixed nodes, softened by their largest, made one-sided forces: a bulge alone gained 18% of its energy in
      200 Myr.
    - Split, the halo alone conserves energy to 7e-5.
- [x] **`about` records** per particle (birth time, the star's mass, mass at birth, part or well number), gathered
  with the sort.
- [x] **Stellar evolution** (`shaders/evolve.wgsl`, once per step of dt):
  - main-sequence lifetimes, then the last 10% as a giant, then a remnant by mass;
  - single stars take the remnant's mass at death; population particles lose mass smoothly (Jungwiert 2001);
  - the mass lost just leaves for now (phase 3: gas).
- [x] **Super well sink:** bound single stars within 2 pc are swallowed, with 64-bit integer atomics for mass and
  momentum. Population particles aren't swallowed: taking whole ~10^6 Msun clusters grew the well 4e6 -> 5e8 in
  2 Gyr.
- [x] **Galaxy generator** (`init::galaxy`, `GalaxyConfig`, MW-like):
  - **Parts:** exponential disc 4e10, Plummer bulge 1e10 (1 kpc), cored 1/R halo 3.5e11 to 40 kpc, well 4e6.
  - **Velocities from the measured forces:** Jeans for the bulge and halo; Toomre Q plus asymmetric drift for the
    disc.
  - **Steps:** 7 levels (2 Myr to 1/32) and eta_jerk 0.1. The bulge centre needs the deep bins: with 5 levels it
    blew up.
- [x] **Window:** scene and Toomre Q in the menu (for the next reset); dark matter toggle (D); wells drawn as white
  markers; nothing drawn for swallowed particles, neutron stars or black holes. **Headless:** galaxy figures
  (`galaxy_start` / `galaxy_end`) and flags (`--scene`, `--toomre-q`, `--softening`, `--dm-softening`,
  `--halo-share`, `--disc-mass`, `--bulge-mass`, `--halo-mass`, `--well-mass`).
- [x] **Tests:** the galaxy (flat curve, parts keep their sizes over 100 Myr, energy), stellar remnants, swallowing
  (mass and momentum); `galaxy_diagnostics` (ignored). 12 pass.
- [x] **Acceptance** (2026-11-08, RTX 2070 Super):
  - **Flat rotation curve:** 221 - 237 pc/Myr from 4 to 24 kpc.
  - **10 rotations (2 Gyr):** the disc's half-mass radius 4,200 -> 4,154 pc at 500k (+2% at 100k). Its radial
    dispersion rose ~60% (spiral heating); energy within 0.35% at 100k.
  - **Spiral arms:** at Q 1.0 a bar and two arms grow within 300 Myr.
- **Known, not fixed:**
  - The halo settles ~8% inward in its first ~500 Myr. That is usual for starts built from Jeans moments with
    Gaussian speeds.
  - The bulge alone loses 1.5 - 5% of its energy in 200 Myr, depending on the step settings. In the full galaxy
    it's 0.35% over 2 Gyr.
- [ ] **Laptop:** L2 in the laptop backlog.

Phase 3 (started 2026-11-08):

- [x] **Gas particles** (kind 7): a gas record per particle ((u, Σ, H, -), (hydro ax, ay, du/dt, signal speed)) and
  element mass fractions (He, C/N/O, Mg/Si, Fe) for every particle, gathered with the sort.
  - The gas gets its own tree class (Morton bits 46 - 47), and nodes get the largest H (20-word nodes).
  - A shared control buffer holds the list length, the gas run and the clock, to stay within 8 storage buffers.
- [x] **SPH** (`hydro.wgsl`): Wendland C2, ~24 neighbours, adaptive H (25 pc - 3 kpc), Monaghan viscosity, density
  and force walks over the gas tree; pairs within max(H_i, H_j).
- [x] **Cooling and heating:** Koyama & Inutsuka below 10^4 K, CIE above (metallicity-blended), solved implicitly.
  - **Floors:** 100 K, Jeans, and the effective EOS P ∝ rho^(4/3) above the star formation density.
  - **Courant** step limit.
- [x] **Star formation:** 0.1 cm^-3, cool or on the EOS, 1% per free-fall time, stochastic and deterministic (a hash
  of id and clock); whole gas particle -> star particle.
- [x] **Stellar feedback:** mass loss, elements (core collapse, AGB, Ia) and supernova energy go to the nearest gas
  (64-bit atomics). The energy is heat in one particle, capped at what its shortest step can follow.
- [x] **Galaxy:** a gas disc of 1e10 Msun (2x the stars' scale length) and metallicity gradients (gas and stars,
  older stars poorer).
  - Drawn by temperature (G toggles it).
  - Headless galaxy figures: gas mass, hot gas, metallicity, new stars, Kennicutt-Schmidt rings, gas half-mass
    radius and temperatures.
  - Flags: `--no-feedback`, `--no-cooling`, `--no-star-formation`, `--gas-mass`.
- [x] **Problems found and fixed (2026-11-08):**
  - Cooling gas collapsed to a ~1 pc kernel reach; the Courant step fell under the shortest one and the disc blew
    apart within 300 Myr. Fixed with an H floor of half the softening.
  - Repeated supernova heat in one particle ran away. Fixed with the heat cap at injection.
  - The cooled gas fragmented into ~40 massive clumps. Fixed with the effective EOS.
- [x] **Tests (15 pass):** a hot blob keeps its energy (1.5% over 10 Myr) and momentum; hot gas cools; a galaxy's gas
  forms stars, its metals rise, later stars are richer, no blow-out or collapse.
- [x] **Acceptance** (100k, 300 Myr):
  - **Kennicutt-Schmidt:** within 2 - 4x at Σ 5 - 260 Msun/pc².
  - **Generations:** several, with rising metallicity (gas 1.12 -> 1.54 solar).
  - **Stability:** no runaway cooling or blow-out (gas half-mass radius 8.0 -> 8.7 kpc).
- [ ] **Carried to phase 4:** Bondi accretion (Eddington-capped) onto wells and AGN feedback. For now bound gas
  within 2 pc is swallowed whole.
- [ ] **Carried to phase 5:** gas merging and splitting (adaptive resolution for the gas between galaxies).
- **Known:** dense star-forming knots remain (2D, 10% gas). Star formation is ~6 Msun/yr, high for the Milky Way;
  `sf_efficiency` (0.01) and the gas fraction tune it. Material shed by stars arrives without the star's momentum.
- [ ] **Laptop:** L4 in the laptop backlog.

Phase 4 (2026-11-08; paused once at the user's request, then finished):

- [x] **Well list rebuilt each step** (`wells_list.wgsl`, a prefix sum in sorted order, so it's deterministic): wells
  can be born and merge. At most 64.
- [x] **Bondi accretion** (`wells_env.wgsl`), Eddington-capped (Salpeter 45 Myr) and at most a quarter of the
  nearest gas particle a step. The mass and momentum come out of the gas through the deposit buffer (negative mass).
  - **AGN feedback:** 0.015 of mdot c² heats that gas.
  - **Galaxy:** the central well grew 4e6 -> 3e7 Msun in 300 Myr (100k).
- [x] **Dynamical friction** (Chandrasekhar, Maxwellian) for wells too light for the tree, weighted
  1 - M / 50 m. Test: 30 -> 11.8 pc/Myr in 8 Myr against 20.5 without.
- [x] **Well mergers** (`wells_merge.wgsl`): bound pairs within 100 pc. Mass, momentum and the mass-weighted
  acceleration are kept (else the next half kick carried the partner's pull). The last hardening and the GW
  inspiral are taken as instant.
- [x] **Direct collapse:** metal-poor (under 1e-3 solar), dense (over 10 cm^-3), massive (over 1e4 Msun) gas becomes
  a seed well at star formation. The gas metallicity is now kept in the gas record's 4th word.
- [x] **Tests:** 19 pass (4 new: Eddington-capped feeding with AGN heat, mergers keeping mass and momentum, dynamical
  friction, direct collapse).
- [x] **Well list to 256.** Single stars' black holes become (stellar-mass) wells that merge when bound into
  intermediate wells; those under 1,000 Msun aren't drawn.
- [x] **Binaries at birth** as a pure function of id and mass (`binary_of`, WGSL and Rust): fraction, log-normal
  periods, q, eccentricity. **Type Ia** from close white-dwarf binaries for single stars (the GPU agrees with the CPU
  on all 107 in the test).
- [x] **Tests:** 21 pass (+2: black holes to wells to mergers; Ia from binaries).
- [x] **RTX 2070 Super window, galaxy at 500k:** 60.0 fps, worst frame 19.7 ms, 2.3 Myr/s.
- **Not done, carried:**
  - Encounters hardening, softening or disrupting binaries: they need each star's local stellar density and
    dispersion; do it with the single-star cluster presets (phase 8) or the star system view (phase 7).
  - A galaxy-scale run of a light well sinking to the centre: friction is tested in a static field only.
- [ ] **Laptop:** L5 in the laptop backlog.

Phases 5 - 8 (2026-11-08 - 09, one pass at the user's request "finish all the remaining phases"; the phases'
code shares files, so they were built together and committed together):

Phase 5, the universe scale:

- [x] **Mesh gravity (TreePM)**, `shaders/pm.wgsl`: cloud-in-cell deposit with 64-bit integer sums, a 2D FFT in
  workgroup memory (radix 2, up to 1024 cells a side), the long-range Green's function of this 2D universe with 1/r²
  gravity, -2πG Σ_k / k · erfc(k r_s) (the 2D transform of erf(r / 2 r_s) / r), CIC deconvolved twice. The tree
  does the short range (erfc factor, nodes beyond 4.5 r_s left out). The long range is a kick-drift-kick on the
  longest step: half kicks at each step's end (`Work::Pm`) and start. Test: TreePM against the tree alone for
  clumps over 6 Mpc, median error 0.3%, 99th percentile 4% (512 cells; the mesh carries ~60% of the pull).
- [x] **Expansion** (`src/sim/cosmo.rs`): flat ΛCDM, a(t) in closed form (WGSL too); positions comoving (the fixed-point
  box), velocities peculiar. Each step's a and H (`cosmo_step`, on the GPU from the clock) are copied into the shared
  parameters: `unit_pc` becomes physical pc per unit, so every pass works in physical units unchanged. Hubble drag
  on velocities, adiabatic cooling of the gas, softening comoving until a = 0.25.
- [x] **The early universe** (`--scene universe`, `init::universe`): 20 Mpc from z = 30, dark matter and gas on
  interleaved lattices, Zel'dovich displacements and velocities from a Gaussian field. The 2D sheet stands for a 1 Mpc
  slab; its linear growth is scale-dependent (δ'' + 2Hδ' = 2πGΣkδ), so the start is set backwards from the chosen
  spectrum today, mode by mode (`Cosmology::growth`, tested against ΛCDM where the sheet matches 3D). Gas density
  from Σ maps 2D collapse to 3D (ρ ∝ Σ^1.5, `gas_rho`); UV background after z = 8 (10^4 K floor for thin gas);
  photoelectric heating scaled by metallicity; star formation also from gas held up only by the Jeans floor.
  - **Result (100k, RTX):** the cosmic web forms (filaments by z ~ 4, halos at the nodes by z = 0; density variance
    3 -> 51); ~290 halos of 32+ particles by z = 0; 4e11 Msun of stars; gas metallicity 0.27 solar.
  - **Fixed on the way:** gas ran away at z ~ 2 where the Courant step fell under the shortest step (dense gas at its
    Jeans floor next to AGN-heated gas): a gas particle now takes only the share of its hydro push its step can
    follow (`hydro_share`).
- [x] **Galaxy finder** (`shaders/finder.wgsl`): friends of friends on the GPU (12 linking rounds with hooking and
  pointer jumping; whole nodes within the linking length taken at once), group sums with 64-bit integers (exact,
  including negative values: `split64`). Universe: dark matter linked at 0.2 of its mean spacing (halos); placed
  galaxies: stars, gas and wells at 300 pc, every 200 Myr (universe: every 100). 8 rounds of 16 slices each, spread over
  frames (~0.26 s of GPU in all at 500k in the galaxy).
  Test: three clumps found with their exact members, masses and centres.
- [x] **Gas merging and splitting** (`shaders/resolution.wgsl`): thin hot light gas merges in pairs (mass, momentum,
  energy kept), heavy gas splits into free slots.
- [x] **Placed galaxies:** `--scene pair` (two Milky Way-like galaxies, parabolic orbit, pericentre 25 kpc) and
  `--scene group` (1 large, 3 medium, 20 dwarfs within 600 kpc, falling together), each galaxy built in balance on
  its own and placed (`init::place`).
  - **Pair merger (100k):** first pericentre at ~400 Myr, apocentre 68 kpc at ~900 Myr, second passage at 1.3 Gyr,
    central wells merged at ~1.55 Gyr.
- [x] **Acceptance (RTX 2070 Super, window, 525k):** web forms; pair merges in ~1.5 Gyr; the group's 24 galaxies at
  60.0 fps (worst frame 17.6 ms).
- [x] **Window speed fixes:** the finder leaves out the dark matter's part of the tree and starts from a cautious
  cost estimate (an optimistic one let its first run overload frames and cut the galaxy's speed by a third); the
  wells' surroundings walk is now one workgroup a well (it was one thread: 13 - 19 ms
  at 500k, now ~3); `Work::Evolve` is split in three items; old populations give back their mass every 8th step.
- **Known:**
  - Super wells overgrow in the universe (~5% of their halo by z = 0): the AGN's heat goes into one gas particle and
    is mostly capped away, so it doesn't regulate them.
  - The universe's lattice still shows in the voids.
- [ ] **Laptop:** L6.

Phase 6, joining the views:

- [x] Click a galaxy's ring (drawn round each galaxy the finder found while it is small on screen) or a particle
  (`shaders/probe.wgsl`: the nearest within 10 px, ties to the lowest id): it is followed (the camera glides to it)
  and zoomed to, with a panel about it. Dragging stops following; Esc clears.
- [x] Speed by zoom (on by default, A): ~10 Myr/s on a galaxy, ~0.5 on its centre, up to 2,000 on the universe.
- [x] Level of detail: close up, brighter stars are bigger squares (same light), white dwarfs, neutron stars and
  stellar black holes fade in.
- [x] **Acceptance:** `zooming_and_following_change_nothing`: the galaxy run whole and as the window would (budgets
  and speeds varying, a particle picked and followed, finder results read back each frame) end bit-identical.

Phase 7, the star system view:

- [x] `src/system.rs`: planets from the star's id, mass, elements at birth and companion: rocky planets from Mg/Si,
  gas giants with the Fischer & Valenti metallicity law (hot Jupiters 10%), ice giants from C/N/O; the companion
  clears unstable orbits; giants swallow inner planets, white dwarfs keep widened outer ones, supernovae unbind them.
  The window ("Star system" in the panel) draws the Kepler orbits and the companion moving at years per second.
- [x] Tests: the same star gives the same system; metal-rich stars have 3x+ the giants; primordial stars none;
  white dwarfs keep only widened outer planets.

Phase 8, tools, presets, release:

- [x] **Tools** (menu or keys 1 - 7): select, place a galaxy (built in balance), a super well, pour gas, kick, delete
  and move under a brush. They act between steps (`Sim::brush`, `Sim::spawn`); new particles go into spare slots
  (5% of the particles in the window: massless, at the centre, in the longest step, no forces).
- [x] **Saves and presets** (`src/save.rs`): the whole universe (every particle's records, the config and the clock)
  in one lz4-packed file; F5 / F9 quick save and load; "Save as preset" into `presets/`, listed in the menu. Test:
  a saved universe loads bit-identical and runs on.
- [x] **Release builds:** `squareverse_v3/ci/v3-release.yml` (to be moved into `.github/workflows/`) builds Windows, Linux and macOS (arm64, x86_64) packages
  on a `v3.*` tag (or by hand); untested here (it runs on GitHub).
- [ ] `/optimize` and the laptop backlog (L1 - L7), when the user asks.

