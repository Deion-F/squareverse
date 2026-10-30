# Squareverse — pygame edition

A rebuild of the original Tkinter + MongoDB Squareverse (one folder up) on **pygame**, with an in-memory grid and the
child Squareverse ("mini universe") re-enabled as the source of every Square's **mass and inertia**.
The original project is untouched.

```bash
cd squareverse_pygame
../.venv/bin/python main.py                 # prompts for size and grid spacing like the original
../.venv/bin/python main.py --no-prompt --squares q --seed 7
```

No MongoDB server is needed any more. Only dependency: `pygame` (`pip install -r requirements.txt`).

## Controls

| Key / mouse | Action | Original equivalent |
|---|---|---|
| `Space` / `M` / left-click | start or stop movement | menu `m`, click to stop |
| `N` | single tick while stopped | — |
| `S` then type, `Enter` | spawn a number of Squares, or `m` / `h` / `q` | menu `s` |
| `1` / `2` / `3` | spawn ¼ max / ½ max / fill every empty cell | `q` / `h` / `m` |
| `D` / right-click | delete the Square under the cursor | menu `d` (was a placeholder) |
| `A` | delete all Squares | menu `a` |
| `+` / `-` | tick rate 1, 2, 4, 8, 15, 30, 60, max per second | — |
| `L` | smooth movement (interpolate between ticks) on/off | — |
| `I` | hover inspector: shows a Square's mini universe, mass, momentum and side counts | — |
| `H` | HUD on/off | — |
| `C` | controls list | — |
| `E` / `Esc` | end the simulation | menu `e` |

Command-line options: `--size 1-10`, `--spacing PX`, `--squares N|m|h|q`, `--seed N`, `--tps N` (0 = max),
`--no-smooth`, `--diagonals`, `--no-crush`, `--no-prompt`, `--benchmark TICKS` (headless timing).

## Layout

```
main.py                    entry point, prompts / CLI, headless benchmark
squareverse/config.py      every tunable (grid, child universe, crush rule, colours, tick rate)
squareverse/directions.py  direction deltas and inverses
squareverse/child.py       ChildUniverse - the mini universe inside each Square
squareverse/universe.py    Squareverse + Square - grid, attempt ladder, push chains, border
squareverse/render.py      pygame drawing (cached grid background, Squares, HUD, inspector)
squareverse/app.py         event loop: fixed-rate ticks, frame-rate rendering, controls
tests/test_rules.py        26 rule tests:  ../.venv/bin/python -m unittest discover -s tests
```

The original's 5,600 lines across `god_script.py`, `mongo.py` and `graphics.py` are now ~900 lines.

## The rules

Full reference for the original: [`../docs/ORIGINAL_LOGIC.md`](../docs/ORIGINAL_LOGIC.md).

### Mass: the mini universe
* Every Square holds a hidden **12×12 child Squareverse** (the original's 300 px / 25 px child grid).
* It's seeded with a random number of children (`CHILD_COUNT_RANGE`, default 1–96). **Mass = number of children.**
  Heavier Squares are drawn darker (original: `256 - mass`).
* Children move with the original child rules: previous direction → inverse → random untried. They have no mass,
  never push, and **inherit the directions the parent already tried** this move.

### Inertia: how the mini universe steers its Square (original `a41bbab` rules)
* A Square with no momentum runs **5 child cycles**, then heads for the half of its mini universe with the most
  children (random only on a tie).
* A Square with momentum keeps its previous direction **unless every child is in one half**, in which case it heads
  that way.
* After every successful move, the children run **1 cycle**.
* More children means the distribution shifts more slowly, so heavier Squares hold their course longer.

### The attempt ladder (one move per Square per tick, spawn order)
1. the direction from the inertia rule above
2. its inverse (bounce)
3. the untried direction whose side holds **the most child Squares** (random only on a tie)
4. the remaining untried direction with the most child Squares (random only on a tie)
5. still blocked → the Square is **destroyed** (original behaviour; `--no-crush` keeps it with a white outline)

### Each attempt: collisions (unchanged from the original)
* **Free cell** → move.
* **Universe border** → blocked.
* **Occupied by an equal or heavier Square** → blocked.
* **Occupied by a lighter Square** → **push**. The chain extends while each Square is strictly heavier than the one
  in front. If a pushed Square meets an equal/heavier one it is **crushed** (destroyed). If it is pushed into the
  **border** it is destroyed. Everything left shifts one cell, the mover advances, and idle pushed Squares take the
  push direction as their momentum.

## What changed vs the original, and why

| Change | Reason |
|---|---|
| pygame instead of Tkinter / Zelle `graphics.py` | one draw per frame instead of a Tk redraw after every colour or position change |
| MongoDB replaced by an in-memory grid (same occupancy semantics) | removed ~2.4 network round trips per Square per cycle; no server, no stale-DB crashes |
| Ticks at a fixed rate, rendering at up to 120 fps with interpolation | smooth motion independent of simulation cost |
| Each tick's moves are animated in dependency order ("waves") | moves happen one after another; sliding them all at once made Squares overlap on screen. A Square now starts entering a cell only once the previous occupant has left it (or slides alongside it in the same direction), and multi-step pushes play step by step. Collisions are shown at the moment of contact: a blocked Square bounces only after the Square it hit has arrived next to it, push chains start together, and a crushed Square stays visible until it is squeezed |
| 1,870-line `moveSquare` → `move_square` + `attempt` | one copy of each rule |
| Child universe re-enabled and drives mass and direction | agreed design: combines `HEAD` (mass, pushing) and `a41bbab` (child-driven inertia) |
| Ladder attempts 3–4 follow the child counts instead of random | as requested |
| 4 cardinal directions by default (`--diagonals` for HEAD's 8) | the child-count ladder is defined for the four sides |
| Fixed bugs B1, B3, B6, B9, C1–C4 (see `docs/IMPROVEMENTS.md` §5) | chain cells, skipped Squares, wrong diagonal inverse, colour range, child-cycle bugs |
| Irregular ladder leaves (B5) not reproduced | every failed ladder now ends the same way |

## Performance

Headless `--benchmark 100`, 800 px universe, 25 px grid, child universes running (WSL2, Python 3.13):

| Start | first tick | steady ms / tick |
|---|---|---|
| 256 Squares (¼) | 57 ms | **6.3** |
| 512 Squares (½) | 109 ms | 9.5 |
| 1024 Squares (full) | 247 ms | 11.3 |
| 2500 Squares, 100×100 grid | 556 ms | 86 |

The original averaged **877 ms per cycle** at 256 Squares. The first tick is slower because every new Square runs its
5 spawn child cycles. Rendering 1,000 Squares takes about 1–2 ms per frame.

Population over 40 ticks from 256 Squares matches the original (about 120–130 left in both), because the
crush-when-trapped rule is unchanged.
