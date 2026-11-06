# Squareverse v3

Galaxies and the universe they live in, simulated on the GPU and drawn as squares. A ground-up rebuild of
`squareverse_v2` in Rust + wgpu: one native program per OS (Windows: DX12 / Vulkan, Mac: Metal, Linux: Vulkan / GL),
nothing for users to install. The design, the decisions behind it and progress are in `../PLAN_V3.md`.

**Status: phase 0 (setup).** The engine runs a stand-in workload: stars orbiting one point mass, to prove the
pieces underneath (fixed-point positions, GPU timing, drawing, the menu, headless runs and tests). Phase 1 replaces
the point mass with real self-gravity.

```
cargo run --release                                   # the window
cargo run --release -- --particles 500000 --fps 30    # options: see --help
cargo run --release -- --headless --steps 500 --snapshot frame.png   # no window: JSON report (+ a PNG)
cargo run --release -- --list-adapters                # the GPUs wgpu can see
cargo run --release -- --exit-after-frames 600        # close after 600 frames and print the fps reached
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

## The phase-0 scene

`SimConfig::default()` (`src/sim/mod.rs`): a point mass of 1e10 Msun in the middle of a 20 Mpc box, stars spread
evenly over the area between 1 and 15 kpc on near-circular orbits (3% random speed spread), softening 50 pc, 0.25 Myr
a step, integrated by kick-drift-kick leapfrog (`shaders/step.wgsl`). Each star gets a mass from the Kroupa IMF
(0.08 - 100 Msun) and a main-sequence temperature and luminosity (`src/sim/init.rs`), which set its colour and
brightness.

How many particles by default depends on the GPU (`src/budget.rs`, provisional until phase 1 measures them):
1,000,000 on a discrete GPU, 250,000 on an integrated one, 500,000 on a known discrete GPU reached through a
translation layer (WSL's OpenGL over D3D12), 200,000 on another unknown one, 30,000 in software. The frame-rate
targets: 60 fps on the desktop (RTX 2070 Super); on the laptop (integrated Radeon) 60 if possible, never below a
stable 30.

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

`cargo test -- --nocapture`. Unit tests: fixed-point round trip, wrap and sub-AU separations, the IMF's range and
mean, the main sequence. GPU tests (`tests/gpu.rs`, one shared device; with no GPU they print why and check nothing,
`SV_ALLOW_CPU=1` runs them in software): the same seed gives the same state and another seed doesn't; energy holds on
the orbits; the GPU matches a CPU f64 reference (`src/sim/reference.rs`) with the disc centred on the box's corner,
so particles cross the wrap and every step carries between the words.

## Measured (2026-11-06, phase-0 workload, Windows exe on DX12)

| GPU | particles | fps (target) | GPU ms a frame: step / draw / tonemap |
|---|---|---|---|
| RTX 2070 Super | 1,000,000 | 59.9 (60) | 0.68 / 2.56 / 0.04 (4 steps a frame) |
| Intel UHD 630 (integrated) | 250,000 | 59.2 (60), 29.9 (30) | 2.4 / 8.2 / 1.0 |

GPU time a step, headless: RTX 2070 Super 0.032 ms at 250k, 0.13 ms at 1M, 0.54 ms at 4M; Intel UHD 630 0.60 ms at
250k, 4.4 ms at 1M. The laptop's integrated Radeon has not been measured yet. Drawing is the largest cost on the
integrated GPU.

## Choosing the GPU

The best adapter wins: discrete before integrated, then DX12 before Vulkan / Metal before OpenGL, never a software
one unless `--allow-cpu` (`gpu::pick_adapter`). DX12 comes first on Windows because it is the drivers' best-kept
path: this desktop's Intel UHD 630 (driver 26.20.100.7642) crashes the process on Vulkan and runs fine on DX12.
`--adapter NAME` keeps only GPUs whose name contains NAME; the `WGPU_BACKEND` environment variable (`dx12`, `vulkan`,
`metal`, `gl`) limits the backends (from WSL, pass it to the exe with `WSLENV=WGPU_BACKEND/w`).

## Under WSL

Inside WSL the GPU is reachable only through Mesa's OpenGL over D3D12. `gpu::prepare_platform` sets that up as v2
did (`GALLIUM_DRIVER=d3d12`, and `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` when an NVIDIA GPU is passed through);
software adapters such as llvmpipe are never picked unless `--allow-cpu`. The Windows exe built from WSL runs
natively on DX12 / Vulkan and is the build to judge speed by.
