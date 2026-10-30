# Squareverse — Original Movement & Collision Logic (reference)

This document describes, exactly, how the **original Tkinter + MongoDB version** of Squareverse moves Squares,
detects collisions and resolves them. It is written so the logic can be reproduced (or returned to) without
re-reading the ~3,800-line `god_script.py`.

* **Snapshot documented:** commit `adf1c79` ("Returning code to working before AI optimizations") — the current `HEAD`.
* **Also documented:** the *child Squareverse* ("mini universe") logic, which exists in `HEAD` but is **disconnected**,
  and the way commit `a41bbab` wired it into parent movement. The pygame rebuild re-enables it (see §9).
* Line numbers refer to `HEAD` unless marked `a41bbab:`.

---

## 1. Files and responsibilities

| File | Role |
|---|---|
| `squareverse_maker.py` | Entry point. Prompts for universe size and grid spacing, creates the `Squareverse`, opens the menu. |
| `god_script.py` | All simulation logic: `Squareverse` (parent universe), `ChildSquareverse`, `ParentSquare`, `SquareChild`. |
| `mongo.py` | `Mongo` class — **the authoritative occupancy grid**. Every collision check is a MongoDB query. |
| `graphics.py` | Zelle `graphics.py` (Tkinter wrapper) with project additions: `GraphWin.squares`, `draw_square`, `undraw_square`, `move_by_id`. |

Runtime requirements: Python + Tk, `pymongo`, a MongoDB server on `localhost:27017` (database `squareverse`).

---

## 2. Coordinate system & grid

All positions are **pixel coordinates of a Square's top-left corner**, always a multiple of the grid spacing.

```
spacing  = grid spacing S (default 25 px)
size     = universe size  N (menu choice 1-10 × 100 px, default 800)
window   = N + 2S          (an S-pixel margin on every side)

valid top-left x, y ∈ { S, 2S, 3S, …, N }        → (N/S) × (N/S) cells
max_number_of_squares = round(N / S) ** 2         (god_script.py:86)
```

Example with defaults: N=800, S=25 → 32×32 = **1024 cells**, window 850×850.

Valid spacings offered by the menu (`squareverse_maker.py:28`): divisors `i` of N with `10 ≤ i ≤ N/10` and `N/i` even.

### 2.1 MongoDB grid (`mongo.py:73 create_parent_squareverse_coordinates`)
One document per cell in collection `squareverse.squareverse_coordinates`:

```python
{ "_id": ObjectId,
  "top_left_corner_x": int, "top_left_corner_y": int,
  "bottom_right_corner_x": int, "bottom_right_corner_y": int,
  "tkinter_id": None | int,          # occupant's Tk canvas id; None = empty
  "previous_direction": None | str,  # occupant's last direction (written, never read back)
  "mass": None | int }               # occupant's mass (READ during chain collisions)
```

A cell is **occupied** iff `tkinter_id != None`. The Square object holds its own position in
`square.body.p1/p2` (Zelle `Point`s) — collision checks use **the object's position to compute the target cell**, then
**the DB to see who is in it**. These two sources of truth can drift (see §8, bug B1).

---

## 3. Directions

`Squareverse.valid_directions` (`god_script.py:99`) — **8 directions** in `HEAD`:

| key | dx | dy | `"i"` (inverse) |
|---|---|---|---|
| `up` | 0 | −S | `down` |
| `down` | 0 | +S | `up` |
| `left` | −S | 0 | `right` |
| `right` | +S | 0 | `left` |
| `d_left_up` | −S | −S | `d_right_down` |
| `d_left_down` | −S | +S | `d_right_up` |
| `d_right_up` | +S | −S | `d_left_down` |
| `d_right_down` | +S | +S | **`d_left_down`** ← bug, should be `d_left_up` (§8, B6) |

Squares move **exactly one cell per move**. In `a41bbab` only the 4 cardinal directions existed.

---

## 4. Square creation & mass

`Squareverse.createSquares(n)` (`god_script.py:209`):

1. `Mongo.get_available_parent_squareverse_coordinates(n)` (`mongo.py:173`)
   * `$match {tkinter_id: None}` + `$sample n` + `$count` → if fewer than `n` empty cells, **nothing** is spawned
     ("There are not enough empty grids remaining").
   * otherwise runs the `$match`+`$sample` again and returns those `n` random empty cells.
2. For each cell: `ParentSquare(self, _id)` then `drawSquareBody(...)` (`god_script.py:3220`):
   * **`mass = randrange(0, 256)`** — mass is random in `HEAD`; nothing else determines it.
   * fill colour = `color_rgb(256 - mass, 256 - mass, 256 - mass)` (heavier = darker; mass 0 → invalid 256, §8 B9).
   * outline = random RGB, width 1.
   * `tkinter_id = body.draw_square(window, square)` → canvas id, and the Square is appended to `window.squares`.
   * the `ChildSquareverse` creation lines are **commented out** (`god_script.py:3245-3248`).
3. `square_objects[tkinter_id] = square` and one bulk write sets `tkinter_id` + `mass` on each chosen cell.

Spawn menu amounts (`god_script.py:40-47`): `m` = remaining empty cells, `h` = max // 2, `q` = max // 4
(`h`/`q` ignore existing Squares, so they fail once the grid is partly full).

New Squares start with `previous_direction = None`.

---

## 5. The main loop

`showSquareverseMenu` → `m` → `moveAllSquares()` (`god_script.py:308`):

```text
while no mouse click:
    for square in window.squares:          # spawn order; list is mutated by destroySquare (§8 B3)
        if square.tkinter_id in square_objects:
            moveSquare(square)
        mouse = window.checkMouse()         # Tk update after EVERY square
    print time for the cycle
```

A **cycle** = every Square gets one `moveSquare` call, sequentially. Later Squares see the board as already changed
by earlier Squares in the same cycle (no double buffering).

---

## 6. Collision detection

### 6.1 `Mongo.collision_check_parent_squareverse(square, universe, direction)` (`mongo.py:435`)

```text
x' = square.body.p1.x + dx[direction]
y' = square.body.p1.y + dy[direction]

if x' < S or y' < S or x' > N or y' > N:          → (True,  None)          # BORDER
cell = find_one({top_left_corner_x: x', top_left_corner_y: y'})
if cell.tkinter_id != None:                        → (True,  cell)          # OCCUPIED (cell carries occupant mass)
else:                                              → (False, cell)          # FREE
```

So every check returns one of three outcomes. The rest of this document uses:

* **FREE** – `(False, cell)`
* **OCCUPIED** – `(True, cell)`; `cell['mass']` and `cell['tkinter_id']` identify the occupant
* **BORDER** – `(True, None)`

Cost: one `find_one` round trip per check (border checks are free).

### 6.2 Child universe version — `collision_check_child_squareverse` (`mongo.py:506`)
Identical, but against collection `squareverse_coordinates_<parent tkinter_id>` and the field `child_square_id`.

---

## 7. Movement & collision resolution (`Squareverse.moveSquare`, `god_script.py:345-2213`)

The 1,870-line method is one decision tree, copy-pasted at increasing indentation. It reduces to the
following **attempt ladder** plus one **attempt routine**.

### 7.1 Per-move reset (`god_script.py:347-356`)
```text
valid_directions        = all 8 keys
directions_already_tried = ∅
selected_direction       = None
body.setFill(body_color); body.setOutline(outline_color)     # 2 Tk updates every move
```

### 7.2 Square with no momentum (`previous_direction is None`) → `moveRandomDirection` (`god_script.py:2229`)
```text
while not all 8 directions tried:
    d = random choice from untried directions; mark tried
    if check(d) is FREE: moveSquareBody(d); stop
    else: outline = White                    # NOTE: OCCUPIED here never pushes, regardless of mass
else (all 8 blocked):
    destroySquare(square)                    # trapped Square is removed
```

### 7.3 Square with momentum (`previous_direction` set) — the attempt ladder

| Attempt | Direction chosen |
|---|---|
| 1 | `previous_direction` (momentum) |
| 2 | inverse of attempt-1 direction (`valid_directions[d]['i']`) — a "bounce" |
| 3 | random choice from untried directions |
| 4 | random choice from untried directions |
| — | **destroy the moving Square** ("crushed") — with two irregular exceptions below |

Each attempt runs the **attempt routine** (§7.4). If it *moves*, the ladder stops; if it is *blocked*, the next
attempt runs. Blocked means **BORDER**, or **OCCUPIED with `mover.mass <= occupant.mass`**.

Irregular leaves of the copy-pasted tree (exact behaviour of `HEAD`):

| Failure path (attempt 1→2→3→4) | Code | Result |
|---|---|---|
| any path ending with a failed attempt 4 (default) | e.g. `god_script.py:842, 962, 967` | `destroySquare(mover)` |
| lighter → lighter → lighter → **border** | `god_script.py:843-845` | **nothing** (mover stays, keeps momentum) |
| **border** → lighter → lighter → **border** | `god_script.py:1640-1643` | **nothing** |
| border → border → lighter → **border** | `god_script.py:1982-2102` | a **5th** random attempt, then destroy |

### 7.4 Attempt routine (one direction `d`)

```text
result = check(mover, d)

FREE:
    moveSquareBody(mover, d, cell)                         → MOVED

OCCUPIED and mover.mass > cell.mass:                       → PUSH (always ends MOVED)
    chain        = [square_objects[cell.tkinter_id]]       # the Square directly in front
    chain_cells  = []
    k = 0
    loop:
        r = check(chain[k], d)                             # same direction as the mover
        chain_cells.append(r.cell)
        FREE      → break                                   # chain ends at an empty cell
        BORDER    → destroySquare(chain[k]); pop chain[k] and its cell; break
        OCCUPIED  →
            if chain[k].mass <= r.cell.mass:               # next Square is at least as heavy
                destroySquare(chain[k]); pop; break        # chain[k] is CRUSHED between them
            else:
                chain.append(square_objects[r.cell.tkinter_id]); k += 1
    for sq in reversed(chain):                             # move the far end first
        move sq one cell in d (body points + canvas)
        if sq.previous_direction is None: sq.previous_direction = d     # pushed idle Squares inherit d
        Mongo update → chain_cells[LAST]                   # ← BUG B1: index reset every iteration
        sq.outline = outline_color
    move mover one cell in d; mover.previous_direction = d; Mongo update → cell

OCCUPIED and mover.mass <= cell.mass:                      → BLOCKED
BORDER:                                                    → BLOCKED
```

Key rules this encodes:

* **Only strictly heavier Squares push.** Equal mass blocks.
* **Mass comparisons in a chain are pairwise** (`chain[k]` vs the Square in front of it), *not* against the mover.
  A heavy mover can push a light Square into a heavier one; the light one is crushed and the mover advances
  into the gap.
* **A pushed Square that hits the border is destroyed** (the border never gives way).
* A push always succeeds for the mover: after crush/border removal there is always a gap one cell ahead.
* Pushed Squares do **not** spend their own move; they may move again later in the same cycle when their turn comes.

### 7.5 `moveSquareBody` (`god_script.py:2215`)
```text
body.p1 += (dx, dy); body.p2 += (dx, dy)
window.move_by_id(tkinter_id, dx, dy)          # Tk update
previous_direction = selected_direction
Mongo.update_parent_square_coordinates(square, target_cell)
body.setOutline(outline_color)                 # Tk update
```

### 7.6 `Mongo.update_parent_square_coordinates` (`mongo.py:387`)
One `bulk_write` of two `UpdateOne`s:
1. `{tkinter_id: square.id}` → set `tkinter_id/previous_direction/mass = None` (vacate old cell)
2. `{_id: target._id}` → set `tkinter_id = square.id, previous_direction, mass` (occupy new cell)

### 7.7 `destroySquare` (`god_script.py:2414`)
1. `update_one({tkinter_id: id}, {$set: tkinter_id/previous_direction/mass = None})`
2. `body.undraw_square(square)` → canvas delete + `window.squares.remove(square)` + Tk update
3. `del square_objects[id]`

### 7.8 Ending the simulation
`e` (or any unknown option) → `destroySquareverse()` → drops the whole `squareverse` database and closes the window.
**This is the only place the DB is cleared**; a crash/kill leaves stale cells that break the next run (§8, B2).

### 7.9 Unused code in the movement path
* `squareChainCollisionCheck` (`god_script.py:2268`) — never called; calls non-existent
  `collision_check_squareverse` / `update_square_coordinates`.
* `ParentSquare.moveSquareChild`, `collisionCheck`, `collision_detection_mongo*`, `duplicateSquareCheck`,
  `ChildSquareverse.createSquares/moveSquareChildren/checkSquarePositions` — legacy, not reached.

---

## 8. Known defects in the original (behaviour as-is)

| # | Defect | Where | Effect |
|---|---|---|---|
| B1 | In the chain move loop, `count = len(chain_cells) - 1` is **inside** the `for` loop, so every chain Square's Mongo record is written to the **last** cell. | `god_script.py:472` (+16 copies) | Chains of ≥2: DB loses Squares ("ghosts" visible but not in DB → others can move onto them). Verified: 1 ghost appears every few cycles at 50 % density. |
| B2 | DB is only reset on a clean exit; startup never clears it. | `createSquareverseWindow` | After a kill/crash, the next run reads stale `tkinter_id`s → `KeyError` in `square_objects[...]`. |
| B3 | `moveAllSquares` iterates `window.squares` while `destroySquare` removes items from it. | `god_script.py:316` | The Square after a destroyed one is skipped that cycle. |
| B4 | `moveRandomDirection` never pushes; momentum ladder does. | `god_script.py:2229` | Idle Squares can be trapped (and destroyed) by lighter neighbours. |
| B5 | Irregular ladder leaves (no-op / 5th attempt). | §7.3 table | Slightly different survival odds depending on failure path. |
| B6 | `d_right_down` inverse is `d_left_down`. | `god_script.py:138` | Bounce from down-right goes down-left instead of up-left. |
| B7 | Population collapses: trapped Squares are destroyed. | ladder end | 128 → 67 Squares in 8 cycles at 50 % density (measured). Design behaviour, but worth knowing. |
| B8 | `previous_direction` stored in Mongo is never read. | `mongo.py:393` | Wasted writes. |
| B9 | `256 - mass` gives 256 for mass 0 → `#100100100` colour string. | `god_script.py:3223` | Tk parses it as a 12-bit colour; harmless but unintended. |

Child-universe defects (only matter if re-enabled):

| # | Defect | Where |
|---|---|---|
| C1 | `moveChildSquares` iterates a pymongo **cursor** `number_of_cycles` times; a cursor is exhausted after one pass, so "5 cycles" = 1 cycle. Positions are also stale snapshots. | `god_script.py:2608-2615` |
| C2 | `checkChildSquarePositions` uses `if "up" … elif "down" …` on keys that are always present, so only **up** can ever be detected as a single direction. | `god_script.py:2730-2760` |
| C3 | Child inherits parent's tried set (`parent_square.directions_already_tried.copy()`); with 8 parent directions the `len(tried) != len(valid)` loop can never terminate correctly / `choice([])`. | `god_script.py:2765-2775` |
| C4 | In `a41bbab`, `while selected in tried: moveChildSquares(1)` can spin indefinitely if the dominant side never changes. | `a41bbab:478-479` |

---

## 9. The child Squareverse ("mini universe")

### 9.1 Structure (`ChildSquareverse.createSquareverseWindow`, `god_script.py:2484`)
Created per parent (in `a41bbab:1680-1682`) with hard-coded **size 300, spacing 25 → 12×12 = 144 cells**,
4 cardinal directions, centre coordinate `((300+25)+25)//2 = 175`.
Cells live in collection `squareverse_coordinates_<parent tkinter_id>` with field `child_square_id`.
`create_child_squareverse_coordinates` (`mongo.py:96`) places a child in **every 3rd cell** (ids 3, 6, …, 144 → 48 children).
Nothing is drawn (the child window code is commented out).

### 9.2 Child movement (`ChildSquareverse.moveChildSquare`, `god_script.py:2763`)
Same idea as the parent ladder, 4 directions, **no mass, no pushing**:

```text
tried = copy(parent.directions_already_tried)        # avoid directions the parent just failed
if child.previous_direction is None or in tried:
    random untried directions until FREE → move
else:
    try previous; if blocked try its inverse (if untried); then random untried until FREE
    (blocked everywhere → child stays)
on move: Mongo — vacate old cell, occupy new cell, store previous_direction
```

### 9.3 Reading the child universe (`count_child_square_coordinates`, `mongo.py:288`)
`$facet` counts children per **half** of the 12×12 grid:

| key | condition (`c` = 175) |
|---|---|
| `up` | `top_left_y < c` |
| `down` | `top_left_y >= c` |
| `left` | `top_left_x < c` |
| `right` | `top_left_x >= c` |

`moveChildSquares(parent, cycles)` (`god_script.py:2608`) runs `cycles` child cycles, then returns
* `(True, side)` if **all** children are in one half, else
* `(False, side_with_most_children)` (ties broken randomly).

### 9.4 How `a41bbab` used it to steer the parent (inertia)
```text
previous_direction is None:
    run 5 child cycles → pick dominant side (re-run 1 cycle while that side was already tried)
    try it; FREE → move; blocked → outline White, loop to next child pick
previous_direction set:
    measure (0 cycles); if ALL children on one side → that side, else keep previous_direction
    FREE → move, then 1 child cycle
    blocked → inverse; FREE → move + 1 child cycle
            blocked → 5 child cycles → dominant side → try; blocked → its inverse; blocked → stay
```
Parents had no mass in `a41bbab`; any occupied cell simply blocked.

---

## 10. Quick reference — one move of one Square in `HEAD`

```text
reset colours, tried = ∅
if no momentum:
    try random directions (FREE only) → move | all blocked → destroy
else:
    for d in [previous, inverse(previous), random, random]:
        FREE                      → move, done
        OCCUPIED & heavier        → push chain (crush/border-kill as needed), move, done
        OCCUPIED & not heavier    → next d
        BORDER                    → next d
    destroy mover  (except the irregular leaves in §7.3)
```
