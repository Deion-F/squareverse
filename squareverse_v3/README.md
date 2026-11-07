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
cargo run --release -- --headless --steps 500 --snapshot frame.png   # no window: JSON report (+ a PNG)
cargo run --release -- --list-adapters                # the GPUs wgpu can see
cargo run --release -- --exit-after-frames 600        # close after 600 frames and print the fps reached
cargo run --release -- --headless --theta 0.5 --walk group --rebuild-every 1   # gravity options
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

## Gravity (`src/sim/mod.rs`, `src/sort.rs`, `shaders/`)

A step, all on the GPU, all deterministic (integer atomics only, so a seed gives the same state on the same GPU
and backend):

1. **Kick, drift** (`integrate.wgsl`): half a kick with last step's acceleration, then the drift, in fixed point.
2. **Sort** (`morton.wgsl`, `radix.wgsl`, `scan.wgsl`): the particles' bounding box and 48-bit Morton keys over it,
   then a stable radix sort, 8 bits a pass, six passes (each 256-particle tile sorted in shared memory by eight 1-bit
   splits, tiles placed by a scanned histogram). `gather.wgsl` then moves the particles into key order, so
   neighbours in space are neighbours in memory.
3. **Tree** (`karras.wgsl`, `moments.wgsl`): a binary radix tree over the sorted keys (Karras 2012), then each node's
   mass, centre of mass (fixed point), bounding box, opening radius and second moments, climbing from the leaves.
4. **Force** (`force_particle.wgsl`): each particle walks the tree; a node beyond its opening radius (size / theta +
   the centre of mass's offset from the box centre) acts as a softened point mass plus its quadrupole, a nearer one
   is opened. `--walk group` uses `force.wgsl` instead: 64 neighbouring particles walk together and share each node
   read; more accurate at the same theta, slower on the GPUs measured so far.
5. **Kick** with the new forces.

Between full rebuilds (`rebuild_every`, 4) the tree is only refitted: the moments are recomputed for the new
positions over the same tree, skipping the sort and build. Forces stay right (the opening test uses each node's
actual bounds); only the tree's efficiency slowly drops.

Measured 2026-11-06 (tests, Gaussian cluster of 20k against direct summation), force error median / 99th
percentile: theta 0.6 3.1e-3 / 2.0e-2, theta 0.3 3.3e-4 / 2.3e-3 (group walk: 5.0e-4 / 7.9e-3 and 4.3e-5 / 5.6e-4).
Without quadrupoles theta 0.6 was 2.5e-2 / 8.5e-2.

## The scene

`SimConfig::default()` (`src/sim/mod.rs`): a central point mass of 1e10 Msun (softening 50 pc) in the middle of a
20 Mpc box, and a disc of 2e9 Msun (`disc_mass`) between 1 and 15 kpc on near-circular orbits (10% random speed
spread; the circular speed counts the disc inside each radius), softening 20 pc, theta 0.6, 0.25 Myr a step. Each
particle gets a mass from the Kroupa IMF (0.08 - 100 Msun), scaled so the disc weighs `disc_mass` (each particle then
stands for several stars), and its star's main-sequence temperature and luminosity for its colour
(`src/sim/init.rs`). The cold disc soon breaks into flocculent spiral arms and clumps. At 0.25 Myr steps their close
encounters cost 1e-4 - 4e-4 of the energy over 500 Myr at 20k particles; 0.125 Myr steps keep it near 3e-6
(adaptive steps will handle this).

How many particles by default depends on the GPU (`src/budget.rs`): 500,000 on a discrete GPU, 50,000 on an
integrated one (provisional until the laptop measures it), 250,000 on a known discrete GPU reached through a
translation layer (WSL's OpenGL over D3D12). The frame-rate targets: 60 fps on the desktop (RTX 2070 Super); on the
laptop (integrated Radeon) 60 if possible, never below a stable 30.

## The window

Every particle is a square snapped to the pixel grid, added into an HDR target so crowded pixels glow, then
tonemapped (Reinhard on luminance, which keeps colours) to the screen (`src/render.rs`, `shaders/squares.wgsl`,
`shaders/tonemap.wgsl`). Stars are coloured by their surface temperature, as a black body.

The menu is behind the button in the bottom-right corner (or Tab), with an (i) beside each setting:

* **Simulation:** pause, speed (steps per frame, 1 - 64, with ⏴ ⏵ fine steps; shows Myr a step and a frame),
  particles and seed for the next reset (with a button back to this GPU's default), Reset.
* **Display:** frame-rate target 60 / 30 fps, brightness (light each star adds), exposure (the whole picture), square
  size (1 - 6 px), reset view, fullscreen.
* **Advanced:** the GPU and backend, and GPU milliseconds per pass (step, draw, tonemap, ui) from timestamp queries.

The top-left corner shows particles, simulated time, steps per second and fps against the target; the top-right the
GPU and its total ms a frame.

| Key | |
|---|---|
| Tab | open / close the menu |
| H | the list of keys |
| Space | pause / run |
| [ / ] | slower / faster (steps per frame) |
| R | reset the universe |
| F | frame-rate target 60 / 30 fps |
| Home | reset the view |
| F11 | fullscreen |
| Wheel | zoom at the cursor |
| Drag | move the view (left or right button) |
| Esc | close the key list / menu |

## Headless runs

`--headless` runs `--steps` steps (after a 10-step warm-up kept out of the timings) and prints a JSON report
(`src/headless.rs`), or writes it to `--report`: the adapter (name, backend, kind, driver), the config, steps and
simulated time, `wall_ms_per_step`, `gpu_ms_per_step` (GPU timestamps, the median batch of 50; null without
timestamp support), energy before and after and its relative change, and `state_hash` (FNV-1a over every position and
velocity word: the same seed on the same machine and backend gives the same hash). `--snapshot out.png` also draws the
final state into a 1280 x 800 PNG with the window's default view and look (`src/snapshot.rs`).

## Tests

`cargo test --release -- --nocapture`. Unit tests: fixed-point round trip, wrap and sub-AU separations, the IMF's
range and mean, the main sequence, the disc's mass. GPU tests (`tests/gpu.rs`, one shared device; with no GPU they
print why and check nothing, `SV_ALLOW_CPU=1` runs them in software): the same seed gives the same state and another
seed doesn't; tree forces against direct summation for both walks at two thetas; two bodies keep their orbit for 10
orbits; energy with self-gravity; momentum without the central mass; the GPU matches a CPU f64 reference
(`src/sim/reference.rs`) with the disc centred on the box's corner, so particles cross the wrap and every step carries
between the words. `cargo test --release --test gpu -- --ignored --nocapture force_accuracy_table` prints the force
error for theta 0.4 - 1.0.

## Measured (2026-11-06, Windows exe)

Phase 1, self-gravity, per-particle walk, theta 0.6, rebuild every 4 steps, GPU ms a step:

| GPU (backend) | particles | step | force / sort / tree / other |
|---|---|---|---|
| RTX 2070 Super (Vulkan) | 500,000 | 12.2 | 10.7 / 0.56 / 0.74 / 0.2 |
| RTX 2070 Super (Vulkan) | 1,000,000 | 23.1 | 20.3 / 1.6 / 1.5 / 0.4 |
| Intel UHD 630 (DX12) | 100,000 | 36.4 | 27.7 / 4.6 / 3.3 / 0.7 |

Window, RTX 2070 Super, 500,000 particles, a step a frame: 60.0 fps (worst frame 17.2 ms). The laptop has not been
measured with self-gravity yet.

Phase 0 (the stand-in point-mass workload): RTX 2070 Super 1,000,000 at 59.9 fps; Intel UHD 630 250,000 at 59.2;
the laptop's integrated Radeon 250,000 at 59.7 (results in `../PLAN_V3.md`).

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
