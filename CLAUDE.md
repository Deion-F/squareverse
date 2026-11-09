# Squareverse

Two versions live here:

- **`squareverse_v3/`** (Rust + wgpu, in progress): the current work. Design, decisions and progress are in
  `PLAN_V3.md` at the repo root; read its Progress section first when picking work up.
- **`squareverse_v2/`** (Python + numba): frozen. Keep it runnable; don't change it unless the user asks.

## Building v3

- Rust is in `~/.cargo/bin` (use `~/.cargo/bin/cargo` if `cargo` isn't on the PATH). `cargo build`, `cargo test --
  --nocapture`, `cargo run --release` from `squareverse_v3/`.
- Windows exe from WSL: `cargo build --release --target x86_64-pc-windows-gnu` (needs `mingw-w64`), then run
  `target/x86_64-pc-windows-gnu/release/squareverse.exe` from WSL; it uses the GPU natively (DX12 / Vulkan). Inside
  WSL the Linux build reaches the GPU only through Mesa's OpenGL over D3D12 (set up automatically by
  `gpu::prepare_platform`).
- Laptop checks are collected in PLAN_V3.md "Laptop backlog" (the user runs them in one go later, with the optimizer); add each new one there with what to change on its result.
- Headless: `squareverse --headless --steps N` (steps of dt, 2 Myr (universe 20), each 2^(levels-1) block sub-steps; `--scene galaxy|disc|universe|pair|group`) `--particles P --seed S [--report r.json] [--snapshot s.png] [--show-dm]`; the
  snapshot is the final frame as a PNG, which you can look at with Read.
- If `cc` is missing (no `build-essential`), cargo can't link. Ask the user to run `sudo apt install -y
  build-essential mingw-w64`; until then a Zig linker can stand in (see PLAN_V3.md Progress).

## Two machines

The user develops on a desktop (RTX 2070 Super) and a laptop (Ryzen 5 PRO 5650U, integrated Radeon, WSL2). v3 must
hold 60 fps on the desktop and on the laptop 60 if possible, never below a stable 30. Name the machine (from the
headless report's `adapter`) with every timing.

## Optimization subagent

The `sim-optimizer` subagent (`.claude/agents/sim-optimizer.md`) is in charge of performance, but it is slow and
thorough (a run takes half an hour or more), so it runs **only when the user types `/optimize`**
(`.claude/commands/optimize.md`). Don't start it on your own, not even after physics changes or when something
looks slow; you can suggest `/optimize` to the user instead.

When it runs, tell it what changed (files, functions or a diff range) and what the change is meant to do. Then pass
its before/after numbers and any trade-offs on to the user. If it reports that the user's sim is running, ask the
user whether it may close the sim and continue, or should wait until they close it and confirm. Send the answer
back to the same subagent (SendMessage) so it carries on where it stopped; it closes the sim only once told the user
agreed.

## Sonnet helper subagents

The main thread (Opus) keeps physics design, debugging, tuning decisions and interpreting results. These Sonnet
subagents in `.claude/agents/` take narrow, well-specified jobs, and **may be used without the user asking**. All
work on v3:

- `sim-experimenter`: runs headless experiments to a spec (flags or config, what to measure, steps, seeds,
  pass/fail) and returns raw numbers. Use it instead of writing and running measurement scripts in the main thread.
- `test-runner`: runs `cargo test` (and clippy) and triages failures (actual vs expected, flaky or not, likely
  cause). Use it after changes rather than reading full test output in the main thread.
- `docs-sync`: brings `squareverse_v3/README.md` / OPTIMIZATIONS.md in step with a change (names, values, flags,
  keys, menu). Use it after a change that touches anything the README quotes. It flags measured figures that may be
  stale; re-measure those with `sim-experimenter`, don't guess them.

Give each one exactly what it needs to work alone (it starts with no context). The same rules apply as for the
optimizer: if it reports the user's sim is running, ask the user (close and continue, or wait) and send the answer
back to that subagent; for runs over ~5 minutes, relay its progress updates. Check what they report before passing it
on.
