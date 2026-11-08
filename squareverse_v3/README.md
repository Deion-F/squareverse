# Squareverse v3

Galaxies and the universe they live in, simulated on the GPU and drawn as squares. A ground-up rebuild of
`squareverse_v2` in Rust + wgpu: one native program per OS (Windows: DX12 / Vulkan, Mac: Metal, Linux: Vulkan / GL),
nothing for users to install. The design, the decisions behind it and progress are in `../PLAN_V3.md`.

**Status: phase 3 (gas and the star cycle) done.** The default scene is a Milky-Way-like galaxy in balance: a disc
of stars, a gas disc, a bulge, a dark matter halo and a super well at the centre.
- **Gas:** SPH hydrodynamics. It cools and forms stars (near the Kennicutt-Schmidt law).
- **Stars:** they age into giants and remnants. They give back mass, elements (He, C/N/O, Mg/Si, Fe) and supernova
  heat, so each generation forms richer in metals.
- **Gravity:** a Barnes-Hut tree on the GPU. Each particle steps as often as it needs, and the frame rate holds
  while the sim slows instead.

Next: binaries and small super wells (phase 4), with gas accretion onto wells and their feedback.

## Setting up a machine (WSL / Ubuntu), once

Paste these two lines into the WSL terminal (the first asks for your password), then open a new terminal:

```
sudo apt update && sudo apt install -y build-essential mingw-w64
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal -t x86_64-pc-windows-gnu
```

`build-essential` is the C linker Rust needs on Linux, `mingw-w64` builds the Windows exe from WSL, and the second
line installs Rust into `~/.cargo`.

## Running

```
cargo run --release                                   # the window
cargo run --release -- --particles 500000 --fps 30    # options: see --help
cargo run --release -- --headless --steps 50 --snapshot frame.png    # no window: JSON report (+ a PNG)
cargo run --release -- --list-adapters                # the GPUs wgpu can see
cargo run --release -- --exit-after-frames 600        # close after 600 frames and print the fps reached
cargo run --release -- --headless --theta 0.5 --walk group --rebuild-every 1   # gravity options
cargo run --release -- --headless --dt 2 --levels 7 --eta 0.025 --eta-jerk 0.1    # time-step options
cargo run --release -- --toomre-q 1.0                 # a cold galaxy disc: a bar and spiral arms
cargo run --release -- --scene disc                   # the phase-1 test disc
cargo run --release -- --headless --no-feedback --no-cooling --no-star-formation --gas-mass 0   # gas switches
cargo test -- --nocapture                             # unit + GPU tests
cargo build --release --target x86_64-pc-windows-gnu  # the Windows exe, from WSL (needs mingw-w64)
```

## Units and positions

Lengths in parsecs (pc), masses in solar masses (Msun), times in megayears (Myr), so speeds are pc / Myr (1 km/s =
1.0227 pc / Myr) and G = 4.4985e-3 pc^3 / (Msun Myr^2) (`src/units.rs`).

Positions are 64-bit fixed point per axis over a periodic box (`src/fixed.rs`, `shaders/fixed.wgsl`): 0 .. 2^64 is
the box once, and integer overflow is the wrap-around. On the GPU an axis is two u32 words with carry. Over the
default 20 Mpc box one unit is ~1e-12 pc, the same everywhere. Separations are taken in integers and only then turned
into floats, so they are as precise near the centre of a galaxy as in the voids, and the drawing subtracts the camera
the same way (no jitter at any zoom).

## Gravity and time steps (`src/sim/mod.rs`, `src/sort.rs`, `shaders/`)

**Block time steps.** The longest step is `dt` (2 Myr); each particle takes dt / 2^bin, bin 0 - 6 (`levels` 7 in the
galaxy, 5 in the test disc), so steps run from 2 Myr down to 1/32 (test disc: 0.125). The galaxy's bulge centre has
orbits of a few Myr: with only 5 levels it swelled 590 -> 3,700 pc in 100 Myr. A particle steps at most sqrt(2 eta softening / |a|) (eta 0.025, GADGET's
criterion) and at most eta_jerk |a| / |da/dt| (eta_jerk 0.1 in the galaxy, 0.05 in the test disc; da/dt from the change in its acceleration over its last
step). The galaxy's pull dominates |a|, so the second rule is the one that sees a close encounter coming. A particle
may take shorter steps from the end of any step, longer ones only where their boundaries line up. A step of dt is
2^(levels - 1) sub-steps (64 in the galaxy). Each step begins with **Evolve** (below), and each sub-step is:

1. **Open, drift** (`integrate.wgsl`): the opening half kick for the particles whose step begins now; every particle
   drifts one sub-step, in fixed point.
2. **Tree.** Every 8 sub-steps (`rebuild_every`) it is rebuilt:
   - **Sort** (`morton.wgsl`, `radix.wgsl`, `scan.wgsl`): the particles' bounding box and their 48-bit Morton keys,
     then a stable radix sort in six passes of 8 bits.
   - **Build**: `gather.wgsl` and `gather_step.wgsl` move the particles, their last accelerations and their bins into
     key order. Then `karras.wgsl` builds a binary radix tree (Karras 2012), and `moments.wgsl` climbs from the leaves
     to give each node its mass, centre of mass, bounding box, opening radius and second moments.
   - **Refit**: in between, only the moments are recomputed, for the new positions over the same tree.
3. **Compact** (`compact.wgsl`): lists the particles whose step ends now.
4. **Force** (`force_particle.wgsl`): each listed particle walks the tree. A node beyond its opening radius (size /
   theta plus the offset of its centre of mass from the box centre) acts as a softened point mass plus its quadrupole;
   a nearer one is opened.
   - `--walk group` uses `force.wgsl` instead: 64 particles walk together. It is slower, badly so on short lists.
   - `--open-small X` lets nodes smaller than X softening lengths act as one mass at any distance. It is off by
     default, because it measured no faster.
5. **Close** (`integrate.wgsl`): the listed particles' closing half kick, and each picks its next bin.

Each of these is a `Work` item. Everything is deterministic (integer atomics only), so a seed gives the same state on
the same GPU and backend, wherever the frames fall.

Measured 2026-11-07 (20k particles, 250 Myr), relative energy change for seeds 1, 2 and 3:

| Stepping | Energy change, seeds 1 / 2 / 3 | Force evaluations per particle per Myr |
|---|---|---|
| Block steps | -1.3e-4 / -6.4e-5 / -4.5e-5 | 2.55 |
| The old fixed 0.25 Myr step | 9e-6 / -3.6e-4 / 6.7e-5 | 4 |
| Fixed 0.125 Myr | ~1e-5 | 8 |

- **Speed (1M particles, RTX 2070 Super):** block steps take 91 GPU ms per Myr, against 105 for the fixed 0.25 Myr
  step and ~210 for 0.125. `--levels 4` (down to 0.25 Myr) takes 71.
- **Why the gain is modest:** a force pass over a few particles still costs about one tree walk's latency, roughly
  20% of a full pass, because the GPU isn't full. So the sub-steps that only the deepest bin needs are expensive.
  A walk split over several threads per particle would help (an /optimize candidate).

**Force error** (Gaussian cluster of 20k against direct summation), median / 99th percentile, measured 2026-11-06:

| Walk | theta 0.6 | theta 0.3 |
|---|---|---|
| Particle | 3.1e-3 / 2.0e-2 | 3.3e-4 / 2.3e-3 |
| Group | 5.0e-4 / 7.9e-3 | 4.3e-5 / 5.6e-4 |

**Kinds and softening.** Every particle has a kind: star, dark matter, super well, white dwarf, neutron star, stellar
black hole, or swallowed. The kind is kept in the top 4 bits of its id word.
- **Softening by kind:** stars and remnants 50 pc (20 in the test disc), dark matter 1,000 pc, super wells 50 pc.
  A pair uses the larger of the two.
- **Why the dark matter gets its own tree:** the Morton key carries a bit for dark matter, so the sorted dark
  matter comes last and the tree's root splits into a tree of everything else and a tree of the dark matter. Every
  node then holds one softening class, and every pair is softened the same both ways.
  - With mixed nodes (each node softened by its largest), the forces were one-sided: a bulge alone gained 18% of
    its energy in 200 Myr.
  - The large dark matter softening keeps its heavy particles, which in 2D all cross the disc plane, from heating
    the disc. At 300 pc the disc's radial dispersion rose 65 -> 107 pc/Myr in 500 Myr; at 1,000 pc it stayed at 72.

**Stellar evolution** (`evolve.wgsl`, once per step of dt, from fitting formulas, not star interiors):
- **Main sequence:** a lifetime of 10 Gyr x m^-2.5, at least 3 Myr. The last tenth of it is spent as a giant:
  cooler and much brighter.
- **Remnants:** below 8 Msun a white dwarf (0.109 m + 0.394 Msun, cooling and fading), 8 - 25 a neutron star (1.4),
  above that a black hole (m / 4). Neutron stars and black holes aren't drawn.
- **One particle, one star's colour:** each particle carries one star's mass from the Kroupa IMF.
  - When a particle is one star (stars per particle about 1), its mass becomes the remnant's at death.
  - When it stands for a population (the galaxy: ~10^5 - 10^6 stars each), it loses mass smoothly as its stars die,
    0.046 ln(age / 0.276 Myr + 1) of its birth mass (Jungwiert et al. 2001).
  - For now that mass just leaves; phase 3 returns it as gas.

**Super wells:** heavy particles with their own softening.
- **Swallowing:** a single-star particle that comes within `accretion_pc` (2 pc) of a well, bound to it, is swallowed.
  Mass and momentum are added with 64-bit integer atomics, so the result is the same in any order.
- **Not for populations:** a population particle is never swallowed. One stands for a million stars spread over 50
  pc, and taking them whole grew the central well 4e6 -> 5e8 Msun in 2 Gyr.

## Gas and the star cycle (phase 3)

**SPH** (`shaders/hydro.wgsl`), 2D:
- **Kernel:** Wendland C2 with ~24 neighbours. The reach H adapts to the density, between half the softening (25 pc)
  and 3 kpc.
- **Equations:** pressure P = (γ - 1) Σ u with γ 5/3, Monaghan artificial viscosity, "density - energy" form.
- **Neighbours:** gas sorts into its own run and its own part of the tree (a class bit in the Morton key, like the
  dark matter). Each tree node keeps its largest H, so every pair is found from both sides.
- **Cost:** two walks per step: density, then pressure forces.

**Cooling and heating** (`shaders/integrate.wgsl`), solved implicitly over each gas particle's step:
- **Below 10^4 K:** Koyama & Inutsuka (2002), with photoelectric heating.
- **Above:** collisional ionisation equilibrium, blended between primordial and solar by metallicity.
- **Density:** a surface density Σ stands for a density Σ / 2 z0, with half-thickness z0 = 100 pc.
- **Floors:**
  - 100 K;
  - a Jeans floor (the 2D Jeans length kept above 2 H);
  - above the star formation density, an effective equation of state, P ∝ rho^(4/3) from 8,000 K (Schaye & Dalla
    Vecchia 2008). Without it the cooled gas collapsed into ~40 massive clumps.
- **Courant:** a gas particle's step also stays under 0.3 H / (signal speed).

**Star formation** (`shaders/evolve.wgsl`):
- **Where:** gas denser than 0.1 hydrogen atoms per cm³ that is cool (under 15,000 K, or on the equation of state).
- **How fast:** with chance 1 - exp(-0.01 dt / t_ff) a step, the gas particle becomes a star particle. It keeps its
  mass and elements; its star is drawn from the IMF.
- **Determinism:** the dice are a hash of the particle id and the clock, so a seed gives the same run.

**What stars give back** (`evolve.wgsl` emit, `feedback.wgsl`, `feedback_apply.wgsl`): each step, every star
particle's mass loss goes to its nearest gas particle within 500 pc.
- **Elements:** the star's birth elements plus new ones.
  - Core-collapse era (under 40 Myr): rich in O, Mg, Si, some Fe.
  - Later (AGB): C and N.
  - Type Ia supernovae: Fe, 1.3e-3 per Msun formed, delay time ∝ 1/t from 100 Myr.
- **Energy:** supernovae give 10^51 erg each, 0.0118 core-collapse per Msun formed over 3 - 40 Myr. All of it heats
  that one neighbour (as stochastic thermal feedback), at most as hot as its shortest step can follow. A heated
  particle takes a short step at once.
- **Determinism:** the sums are 64-bit integer atomics.

**Measured** (100k particles, RTX 2070 Super, 300 Myr, 2026-11-08):
- **Star formation:** ~6 Msun/yr.
- **Kennicutt-Schmidt:** within a factor 2 - 4 of the observed law at Σ 5 - 260 Msun/pc².
- **Metals:** gas metallicity 1.12 -> 1.54 solar; stars born later are richer (1.63 -> 2.01 solar in the test's
  150 Myr).
- **Gas:** stays in its disc (half-mass radius 8.0 -> 8.7 kpc), mostly 10^4 K, ~5% above 10^5 K.
- **Speed at 500k:** the window holds 60 fps at 2.2 Myr/s.

**Not yet:**
- gas accretion onto the wells (Bondi) and their feedback (phase 4); for now a well swallows bound gas within 2 pc;
- merging and splitting gas particles;
- gas momentum from stellar mass loss (the gas keeps its own velocity).

## The scenes

**Galaxy** (the default, `init::galaxy`, roughly the Milky Way, `GalaxyConfig`):
- **Disc:** exponential, 4e10 Msun, scale length 2.6 kpc, cut at 5 scale lengths; Toomre Q 1.5 (`--toomre-q`, and
  in the menu).
- **Bulge:** projected Plummer, 1e10 Msun, scale 1 kpc.
- **Halo:** dark matter, Σ ∝ 1 / sqrt(R² + 3 kpc²) out to 40 kpc, 3.5e11 Msun. In 2D with 1/r² gravity this gives a
  flat rotation curve, as Mestel's disc does, the way an isothermal sphere does in 3D.
- **Centre:** a super well of 4e6 Msun.
- **Gas:** 1e10 Msun, exponential with twice the stars' scale length, at 10^4 K. Metallicity is solar at 8 kpc,
  falling 0.06 dex per kpc.
- **Particles:** 40% dark matter, 10% bulge, 10% gas, the rest disc. Disc stars are spread evenly over ages 0 - 10 Gyr, the
  bulge's are about 10 Gyr old, so many have already died at the start.

**How the galaxy is put in balance:**
1. The positions are placed first.
2. One force pass on the GPU gives each particle's pull, averaged in rings into the circular speed curve.
3. The velocities follow (`init::galaxy_velocities`):
   - **Bulge and halo:** no rotation, isotropic dispersion from the Jeans equation, Σσ²(R) = ∫ Σ g dR'.
   - **Gas:** on circular orbits.
   - **Disc:** σ_R from Q (σ_R = Q 3.36 G Σ / κ), σ_φ = σ_R κ / 2Ω, and rotation from the circular speed less the
     asymmetric drift.

**Measured 2026-11-08 (RTX 2070 Super, Q 1.5):**
- **Rotation curve:** 221 - 237 pc/Myr from 4 to 24 kpc.
- **Over 10 rotations (2 Gyr):** the disc's half-mass radius 4,200 -> 4,154 pc at 500k (+2% at 100k). Its radial
  dispersion rises ~60% (spiral heating).
- **Cold disc:** at Q 1.0 it grows a bar and two spiral arms within 300 Myr.

**Test disc** (`--scene disc`, `SimConfig::test_disc()`, the phase-1 scene and the tests'):
- stars round a fixed central point mass of 1e10 Msun, a 2e9 Msun disc from 1 to 15 kpc;
- softening 20 pc, IMF masses scaled to the disc, no stellar evolution.

**Default particle counts** depend on the GPU (`src/budget.rs`):
- 500,000 on a discrete GPU;
- 50,000 on an integrated one;
- 250,000 on a known discrete GPU reached through a translation layer (WSL's OpenGL over D3D12).

The frame-rate targets are 60 fps on the desktop (RTX 2070 Super), and on the laptop (integrated Radeon) 60 if
possible, never below a stable 30.

## The window

**Drawing** (`src/render.rs`, `shaders/squares.wgsl`, `shaders/tonemap.wgsl`):
- Every particle is a square snapped to the pixel grid, added into an HDR target so crowded pixels glow.
- The result is tonemapped to the screen (Reinhard on luminance, which keeps colours).
- Stars are coloured by their surface temperature, as a black body.

**Frame budget** (`src/app.rs`, `Sim::advance`): the frame rate holds and the sim slows instead.
- Each frame the sim gets a GPU time budget: 85% of the frame period, less the drawing.
- It runs as many work items as fit, even slices of one force pass, using cost estimates learned from GPU
  timestamps.
- An item may start when four fifths of it fit; any overrun comes off the next frame's budget.
- Frames that arrive late anyway shrink the budget until they are on time.
- Particles are drawn moved along their velocity to a display clock that runs at the sim's average pace, so motion
  stays smooth while the sim advances unevenly.
- Without timestamps the sim runs one sub-step a frame.

The menu is behind the button in the bottom-right corner (or Tab), with an (i) beside each setting:

* **Simulation:**
  - pause;
  - speed: sim time per second, 0.5 - 200 Myr/s or "max" (the default: as much as the frame budget allows), with
    the speed reached shown below;
  - the scene (galaxy or test disc) and the galaxy's Toomre Q, for the next reset;
  - particles and seed for the next reset, with a button back to this GPU's default;
  - Reset.
* **Display:** frame-rate target 60 / 30 fps, dark matter on / off (dim violet), gas on / off (by temperature), brightness (light each star adds), exposure (the whole picture), square
  size (1 - 6 px), reset view, fullscreen.
* **Advanced:**
  - the GPU and backend, and the sim's GPU budget a frame;
  - the time-step range, force evaluations per particle per Myr, and the share of particles in each time-step bin;
  - GPU milliseconds per pass, from timestamp queries.

The top-left corner shows particles, simulated time, Myr per second and fps against the target. The top-right shows
the GPU and its total ms a frame.

| Key | |
|---|---|
| Tab | open / close the menu |
| H | the list of keys |
| Space | pause / run |
| [ / ] | slower / faster (sim time per second) |
| R | reset the universe |
| D | show / hide the dark matter |
| G | show / hide the gas |
| F | frame-rate target 60 / 30 fps |
| Home | reset the view |
| F11 | fullscreen |
| Wheel | zoom at the cursor |
| Drag | move the view (left or right button) |
| Esc | close the key list / menu |

## Headless runs

`--headless` runs `--steps` steps of dt (default 50, after a 2-step warm-up that is left out of the timings). It
prints a JSON report (`src/headless.rs`), or writes it to `--report`. The report holds:
- the adapter (name, backend, kind, driver) and the config;
- steps and simulated time;
- `wall_ms_per_step`, `gpu_ms_per_step` and `gpu_ms_per_myr` (GPU timestamps, the median step; null without timestamp
  support), and `gpu_ms_by_stage`;
- `bin_counts` (particles in each time-step bin) and `force_evals_per_myr`;
- for the galaxy, `galaxy_start` / `galaxy_end`: each part's half-mass radius, the disc's radial dispersion at 1, 2
  and 3 scale lengths, the rotation curve, particles by kind, and the central well's mass;
- energy before and after, and its relative change;
- `state_hash`: FNV-1a over every position and velocity word. The same seed on the same machine and backend gives the
  same hash.

`--snapshot out.png` also draws the final state into a 1280 x 800 PNG, with the window's default view and look
(`src/snapshot.rs`). `SV_DEBUG_PASSES=1` prints every pass of the last step with its GPU time (from WSL to the
Windows exe, add `WSLENV=SV_DEBUG_PASSES`).

The window's `--exit-after-frames N` prints one JSON line:
- fps, the worst frame, sim Myr and Myr per second;
- the mean GPU ms a frame by pass, and the worst GPU frame;
- the bin counts and the sim's budget.

## Tests

Run `cargo test --release -- --nocapture`.

**Unit tests:** fixed-point round trip, wrap and sub-AU separations; the IMF's range and mean; the main sequence; the
disc's mass.

**GPU tests** (`tests/gpu.rs`, one shared device; with no GPU they print why and check nothing, and `SV_ALLOW_CPU=1`
runs them in software):
- the same seed gives the same state, and another seed doesn't;
- tree forces against direct summation, for both walks at two thetas;
- two bodies keep their orbit for 10 orbits;
- energy with self-gravity and block steps;
- momentum without the central mass;
- block steps follow a fine fixed step under the central mass (median 0.02 pc, worst 1.1 pc after 40 Myr);
- three steps run whole and run as ~2,800 tiny frames give the same state hash;
- the galaxy has a flat rotation curve (within 10% from 4 to 16 kpc) and keeps its parts' sizes over 100 Myr;
- stars of known mass and age become the right remnants with the right masses;
- a well swallows a bound star and keeps mass and momentum, but not a fast one;
- a hot gas blob expands and keeps its energy (within 2% over 10 Myr) and momentum;
- gas at 10^6 K cools to ~10^4 K and stays above the floor;
- the galaxy's gas forms stars, its metallicity rises, later stars are richer, and the gas neither blows out nor
  collapses;
- the GPU matches a CPU f64 reference (`src/sim/reference.rs`) with the disc centred on the box's corner, so particles
  cross the wrap and every step carries between the words.

**Diagnostics** (`cargo test --release --test gpu -- --ignored --nocapture <name>`):
- `force_accuracy_table`: the force error for theta 0.4 - 1.0;
- `clump_force_table`: the error in the evolved, clumpy disc for `open_small`;
- `galaxy_diagnostics`: the galaxy's rotation curve, energies and half-mass radii over time (settings from `SV_*`
  environment variables).

## Measured (Windows exe, RTX 2070 Super on Vulkan)

**Galaxy, window, 60 fps target (2026-11-08):**
- **500,000 particles:** 60.0 fps, worst frame 17.2 ms, 3.8 Myr/s. One turn at 8 kpc (~200 Myr) takes ~50 s.
- **1,000,000 particles:** 59.7 fps, worst frame 31.7 ms, 1.2 Myr/s. Some frames came late, so the budget shrank.
- **Headless:** 170 GPU ms per Myr at 500k.

**Test disc, window, speed "max" (2026-11-07):**

| Particles | fps | Worst frame | Sim speed |
|---|---|---|---|
| 500,000 | 59.9 | 18.7 ms | 15.3 Myr/s |
| 1,000,000 | 60.0 | 17.3 ms | 7.4 Myr/s |
| 4,000,000 | 60.0 | 17.3 ms | 1.8 Myr/s |

GPU ms per Myr of sim time, headless:

| Particles | Block steps | Old fixed 0.25 Myr step |
|---|---|---|
| 500,000 | 46 | 49 |
| 1,000,000 | 91 | 105 |
| 4,000,000 | 305 | not measured |

**Drawing:** 0.3 ms a frame at 500k, 0.7 at 1M, 2.6 at 4M.

**Intel UHD 630 (DX12, the desktop's integrated GPU, weaker than the laptop's Radeon), 50,000 particles:**
- 58.9 fps at 60;
- 136.7 GPU ms per Myr at 100k.

On this desktop the Intel GPU's frames are copied across to the RTX, which drives the monitors.

**Earlier measurements:** phase 0 and the laptop's results are in `../PLAN_V3.md`.

## Choosing the GPU

The best adapter wins: discrete before integrated, then Vulkan before DX12 / Metal before OpenGL, never a software
one unless `--allow-cpu` (`gpu::pick_adapter`). Vulkan comes first because it compiles our shaders in ~2 s, where
DX12 with Windows' built-in compiler (FXC) took ~170 s. So the Windows build carries Microsoft's DXC
(`vendor/dxc/`: `dxcompiler.dll` and `dxil.dll`, copied beside the exe by `build.rs`), which brings DX12 down to
4 - 7 s; ship those two DLLs with the exe. Intel GPUs are the exception and get DX12: this desktop's UHD 630 (driver
26.20.100.7642) crashes the process on Vulkan. `--adapter NAME` keeps only GPUs whose name contains NAME; the
`WGPU_BACKEND` environment variable (`dx12`, `vulkan`, `metal`, `gl`) limits the backends (from WSL, pass it to the exe
with `WSLENV=WGPU_BACKEND/w`).

## Under WSL

Inside WSL the GPU is reachable only through Mesa's OpenGL over D3D12. `gpu::prepare_platform` sets that up as v2
did (`GALLIUM_DRIVER=d3d12`, and `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` when an NVIDIA GPU is passed through);
software adapters such as llvmpipe are never picked unless `--allow-cpu`. The Windows exe built from WSL runs
natively on DX12 / Vulkan and is the build to judge speed by.
