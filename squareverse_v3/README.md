# Squareverse v3

Galaxies and the universe they live in, simulated on the GPU and drawn as squares. A ground-up rebuild of
`squareverse_v2` in Rust + wgpu: one native program per OS (Windows: DX12 / Vulkan, Mac: Metal, Linux: Vulkan / GL),
nothing for users to install. The design, the decisions behind it and progress are in `../PLAN_V3.md`.

**Status: phase 1 (gravity core), first part done.** Every particle pulls on every other through a Barnes-Hut tree
built on the GPU each step, plus a central point mass (phase 2 makes it a super well). Still to come in phase 1:
adaptive per-particle time steps, and spreading a step over several frames so the frame rate holds when the sim
can't keep up.

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
cargo run --release -- --headless --dt 2 --levels 5 --eta 0.025 --eta-jerk 0.05   # time-step options
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

**Block time steps.** The longest step is `dt` (2 Myr); each particle takes dt / 2^bin, bin 0 - 4 (`levels` 5), so
steps run from 2 Myr down to 0.125. A particle steps at most sqrt(2 eta softening / |a|) (eta 0.025, GADGET's
criterion) and at most eta_jerk |a| / |da/dt| (eta_jerk 0.05, da/dt from the change in its acceleration over its last
step). The galaxy's pull dominates |a|, so the second rule is the one that sees a close encounter coming. A particle
may take shorter steps from the end of any step, longer ones only where their boundaries line up. A step of dt is
16 sub-steps of 0.125 Myr, and each sub-step is:

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

## The scene

`SimConfig::default()` (`src/sim/mod.rs`) is a disc around a central mass:
- **Central mass:** a point mass of 1e10 Msun (softening 50 pc) in the middle of a 20 Mpc box.
- **Disc:** 2e9 Msun (`disc_mass`) between 1 and 15 kpc, on near-circular orbits. The circular speed counts the disc
  inside each radius, plus a 10% random speed spread.
- **Particles:** softening 20 pc, theta 0.6. Each gets a mass from the Kroupa IMF (0.08 - 100 Msun), scaled so the
  disc weighs `disc_mass` (each particle then stands for several stars). Its colour comes from its star's
  main-sequence temperature and luminosity (`src/sim/init.rs`).

The cold disc soon breaks into flocculent spiral arms and clumps.

How many particles by default depends on the GPU (`src/budget.rs`):
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
  - particles and seed for the next reset, with a button back to this GPU's default;
  - Reset.
* **Display:** frame-rate target 60 / 30 fps, brightness (light each star adds), exposure (the whole picture), square
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
- the GPU matches a CPU f64 reference (`src/sim/reference.rs`) with the disc centred on the box's corner, so particles
  cross the wrap and every step carries between the words.

**Diagnostics** (`cargo test --release --test gpu -- --ignored --nocapture <name>`):
- `force_accuracy_table`: the force error for theta 0.4 - 1.0;
- `clump_force_table`: the error in the evolved, clumpy disc for `open_small`.

## Measured (2026-11-07, Windows exe, RTX 2070 Super on Vulkan)

Window with the frame budget, speed "max", 60 fps target:

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
