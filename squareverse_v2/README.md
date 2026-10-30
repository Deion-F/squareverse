# Squareverse v2

A particle sandbox for watching large numbers of square particles under gravity wells, global gravity and
self-gravity. Particles of different masses layer, collide, merge and split. It is a ground-up rebuild of
`squareverse_pygame/` for performance, using the architecture of the falling-sand prototype (`~/TV_Project/sand.py`)
plus numba.

```
./squareverse                      # from the repository root (v2; `--legacy` runs the old edition)
python main.py --preset cloud      # or directly; re-launches itself with ../.venv if numba is missing
python main.py --cell 1 --preset disk --particles 200000
python main.py --preset rain --benchmark 300   # headless timings
python -m pytest                   # physics invariants
```

Press **H** in the app for the controls. F1–F4 load the presets (rain, disk, cloud, binary). G places a well and
Shift+G a repulsor. S toggles self-gravity, and M / P toggle merging / splitting.

## Why it is fast

| | legacy `squareverse_pygame` | v2 |
|---|---|---|
| Hidden per-particle work | a full child universe (up to 192 children) moved every tick, about 90% of tick time | 4 child counts per particle, updated every 4th tick |
| Which particles run | every Square, every tick | only **awake** ones. Settled particles sleep and are woken by neighbours, wells or self-gravity changes |
| State | dataclass objects, string directions, dicts | flat numpy arrays per cell; the tick loop is numba-compiled machine code |
| Processing order | spawn order | lowest potential first (leading particles first, as in sand.py), in memory order within a potential bucket |
| Rendering | 2 `draw.rect` per Square per frame | one kernel fills an RGB buffer, then one `frombuffer` + `scale` blit |

Measured on a Ryzen 5 PRO 5650U laptop (`--benchmark 300`, mean ms per tick):

| scene | particles | awake (mean) | step | rendering |
|---|---|---|---|---|
| legacy, 100×100 grid | 10,000 → 3,137 | all | **400** | (2 rects per Square) |
| sand.py, 480×360 (same rain test) | 59,226 | 20k–130k awake cells | **36–214** | – |
| rain, 480×360 | 46,902 | 31,916 | 3.0 | < 1.5 ms |
| rain, 480×360 | 83,966 | 63,034 | 5.9 | < 1.5 ms |
| disk, 960×720 (1 px) | 145,264 | 120,246 | 22.8 | ~3 ms |
| rain, 960×720 (1 px) | 267,250 | 217,669 | 21.1 | ~3 ms |
| cloud + self-gravity, 960×720 | 95,926 | 103,968 | 11.0 + 1.7 gravity | ~3 ms |

A settled world costs almost nothing, because only moving particles are simulated.

## Physics model (`sv/kernels.py`)

* One particle per cell. Each has a float velocity and a sub-cell offset, so speeds below one cell/tick still move it.
* **Forces:** cached field from wells and global gravity, plus self-gravity (particle-mesh: mass is binned into
  4×4 blocks, the potential comes from an FFT convolution, refreshed every 4 ticks), plus optional children lean (J).
* **Contacts**, applied in this order:
  1. Split, on high impact energy.
  2. 1D momentum exchange, for impacts above the resting threshold.
  3. Merge, for slow contacts (momentum and children are conserved).
  4. Sink: a heavier particle pushes through a lighter one, only when the force presses it in.
  5. Slide or topple, as in sand.py.
  6. Blocked: lose the approach velocity, with static friction when pressed.

  All of these use velocity relative to the neighbour, so particles flowing together (orbits) don't brake each other.
* **Sleep:** a particle that is blocked and slow, or free with no force, stops being simulated until woken.

Tunables are in `sv/config.py`.

## Known limits

* It is a grid model. Clumps behave like sticky granular piles, not rigid bodies, so two separate clumps don't drift
  together under a weak mutual pull. Strong wells still pull and tear them.
* A merged particle still fills one cell however heavy it is. Colour shows mass on a log scale.
* Children lean is off by default. For a mass-1 particle it is a random push about as strong as a distant
  well's pull, which makes orbits wander.
