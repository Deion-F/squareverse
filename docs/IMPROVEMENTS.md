# Squareverse — Improvements & Optimizations (original Tkinter/MongoDB version)

Goal: make the **existing** simulation run as smoothly as possible while changing the movement / mass / collision
logic as little as possible. Every item below is tagged:

* **No logic change** — identical simulation behaviour, only faster/cleaner.
* **Bug fix** — restores what the code clearly intends (behaviour changes only where it was wrong).
* **Logic change** — alters the simulation; listed for completeness, opt-in.

Logic reference: [ORIGINAL_LOGIC.md](ORIGINAL_LOGIC.md).

---

## 1. Where the time goes (measured)

Profile of 6 cycles, 800 px universe, 25 px grid, 256 Squares (`cProfile`, Python 3.13, WSL2):

| Bucket | Time | Share | Source |
|---|---|---|---|
| Tk calls (`_tkinter.tkapp.call`) | 2.39 s | **44 %** | `autoflush=True` → `_root.update()` after every `setFill`, `setOutline`, `move_by_id`, plus `checkMouse()` after every Square |
| MongoDB socket I/O | ~2.9 s | **54 %** | `find_one` per collision check + `bulk_write` per move, ~2.4 round trips per Square per cycle |
| Python simulation logic | ~0.1 s | **2 %** | everything else |

Per-cycle time for the same scenario after applying items below to the unmodified code from a test harness:

| Variant | ms / cycle | Speed-up |
|---|---|---|
| Original | 877 | 1× |
| + §2.1 batch Tk redraws (no autoflush, 1 update per cycle) | 329 | 2.7× |
| + §3.1 two MongoDB indexes | 253 | 3.5× |
| pygame rebuild: §3.3 in-memory grid + §4, **with child universes running** | 6.3 | ~140× |

Population over 40 cycles from 256 Squares (seeds 1–2) is the same in the original and the rebuild
(original 128 / 118 left, rebuild 121–129), so the speed-up isn't coming from different collision dynamics.

> The simulation logic itself is cheap. **Almost all the cost is I/O: redrawing Tk after every tiny change and asking
> MongoDB a question for every step.** Fixing those two gives the bulk of the gains with zero logic changes.

---

## 2. Rendering (Tk) — no logic change

### 2.1 Turn off autoflush and redraw once per cycle  ★ biggest single win
`createSquareverseWindow` (`god_script.py:96`) uses `GraphWin(..., autoflush=True)`. Each `moveSquare` triggers
≈4 full `_root.update()` calls, plus another in `checkMouse()`.

```python
# god_script.py:96
self.window = GraphWin(title=..., width=..., height=..., autoflush=False)

# moveAllSquares: check the mouse / redraw once per cycle, not once per Square
while mouse_clicked is None:
    for square in list(self.window.squares):
        if square.tkinter_id in self.square_objects:
            self.moveSquare(square)
    self.window.update()                 # one redraw per cycle
    mouse_clicked = self.window.checkMouse()
```
Measured: **877 → 329 ms/cycle**. (The commented `manualUpdate()/flush()` lines show this was tried before; with
autoflush off you *must* call `update()` yourself, or the window freezes — that is probably why it was reverted.)
If one-redraw-per-cycle feels too "steppy", call `self.window.update()` every *k* Squares (e.g. 32).

### 2.2 Drop redundant colour writes
`moveSquare` re-applies `setFill(body_color)` and `setOutline(outline_color)` on every move (`god_script.py:355-356`),
and `moveSquareBody` sets the outline again. Fill never changes. Only call `setOutline` when the outline actually
changed (track `square.current_outline`). Saves 2–3 Tk `itemconfig` calls per move.

### 2.3 Stop iterating the canvas list
`window.squares` exists only to iterate Squares. Iterate `list(self.square_objects.values())` instead — same order
(dicts keep insertion order), no Tk dependency, and fixes bug B3 (see §5).

---

## 3. Storage (MongoDB) — no logic change

### 3.1 Add indexes  (2 lines)
Every collision check is `find_one({top_left_corner_x, top_left_corner_y})`, and every move/destroy does
`update_one({tkinter_id})`. Neither field is indexed → collection scans of all cells, each time.

```python
# Mongo.create_parent_squareverse_coordinates, after inserting
dbCollection.create_index([("top_left_corner_x", 1), ("top_left_corner_y", 1)], unique=True)
dbCollection.create_index("tkinter_id")
```
Measured: **329 → 253 ms/cycle** (on top of §2.1). Gains grow with grid size.

### 3.2 Batch the grid creation & spawning
* `create_parent_squareverse_coordinates` does **one `insert_one` per cell** (1,024 round trips at defaults) →
  build the list and `insert_many` once.
* `get_available_parent_squareverse_coordinates` runs `$match+$sample+$count` and then `$match+$sample` again →
  run `$match+$sample` once, `list()` it, and check `len(...) >= n`.
* Don't write `previous_direction` to the DB (bug B8: never read).

### 3.3 Keep the grid in memory; MongoDB optional  ★ second biggest win
MongoDB is used as a 2-D array. A Python dict gives the exact same answers without network round trips:

```python
# Squareverse
self.grid = {}                       # (x, y) -> ParentSquare  (absent = empty)

def collision_check(self, square, direction):
    x = square.x + self.valid_directions[direction]['x']
    y = square.y + self.valid_directions[direction]['y']
    if x < S or y < S or x > N or y > N:
        return True, None                                  # BORDER
    occupant = self.grid.get((x, y))
    return (occupant is not None), (x, y, occupant)        # OCCUPIED / FREE
```
The return shape mirrors `collision_check_parent_squareverse`, so the decision tree is untouched. If persistence or
analytics in Mongo are wanted, write a snapshot with a single `bulk_write` once per cycle (or every N cycles) from
the dict — never read it back during the simulation.

This also removes the need to run a MongoDB server just to start the program, and eliminates stale-DB crashes (B2).

---

## 4. Code structure — no logic change

### 4.1 Collapse `moveSquare` into a ladder + one attempt function
`moveSquare` is 1,870 lines because the same "attempt" block (FREE → move, heavier → push chain, else → next) is
copy-pasted 17 times at increasing indentation. A behaviour-identical version:

```python
def moveSquare(self, sq):
    sq.directions_already_tried = set()
    if sq.previous_direction is None:
        return self.moveRandomDirection(sq)
    first = sq.previous_direction
    ladder = [lambda: first,
              lambda: self.valid_directions[first]['i'],
              lambda: choice(list(set(self.valid_directions) - sq.directions_already_tried)),
              lambda: choice(list(set(self.valid_directions) - sq.directions_already_tried))]
    for pick in ladder:
        d = pick()
        sq.directions_already_tried.add(d)
        if self.attempt(sq, d):          # FREE / PUSH → moved
            return
    self.destroySquare(sq)               # crushed (see note on irregular leaves)
```
`attempt()` is the §7.4 routine from ORIGINAL_LOGIC.md, written once. To be *bit-for-bit* identical you'd have to
special-case the three irregular leaves (ORIGINAL_LOGIC §7.3); in practice they're accidents of copy-paste, and the
uniform ladder is what the code intends.

Benefits: ~1,800 fewer lines, one place to change rules, fewer chances for the copy-paste divergences that
produced B1/B5.

### 4.2 Store integer positions on the Square
Use `square.x, square.y` (ints) instead of `square.body.p1.x` etc. — avoids Point attribute churn and is the key for
the in-memory grid.

### 4.3 Remove dead code
`squareChainCollisionCheck`, `duplicateSquareCheck`, `ParentSquare.moveSquareChild/collisionCheck`,
`collision_detection_mongo*`, `SquareChild`, `ChildSquareverse.createSquares/moveSquareChildren/checkSquarePositions`,
`Mongo.collision_check_testing`, `insert_valid_directions`, `insert_squareverse_coordinates`, and the large commented
blocks (~60 % of `god_script.py`). Also unused imports (`gc`, `sleep`, `copy`, `pprint`, `randint`).

---

## 5. Bug fixes (small, intent-restoring)

| # | Fix | Change |
|---|---|---|
| B1 | Chain DB write uses the wrong cell | Move `count = len(colission_chain_coordinates) - 1` **above** `for collision_square in collision_chain[::-1]:` (17 copies; 1 with §4.1). |
| B2 | Stale DB crashes the next run | Call `self.mongo_client.delete_squareverse_db()` at the start of `createSquareverseWindow` (or use §3.3). |
| B3 | Squares skipped after a destroy | Iterate over a copy: `for square in list(self.window.squares):` |
| B6 | Wrong inverse for `d_right_down` | `"i": "d_left_up"` at `god_script.py:138`. |
| B9 | Colour `256 - mass` | `color_rgb(255 - mass, …)`. |
| C1–C4 | Child universe (if re-enabled) | Use a list of child positions (not a cursor); check each half with independent `if`s; restrict child tried-set to the child's 4 directions; bound the re-pick loop. |

---

## 6. Optional logic changes (not applied to the original)

| Idea | Why | Impact |
|---|---|---|
| Let `moveRandomDirection` push like the ladder does (B4) | Consistency: idle heavy Squares are currently trapped by light ones. | Fewer "trapped" deaths. |
| Uniform ladder (remove irregular leaves, B5) | Predictability. | Negligible statistical change. |
| Double-buffered cycle (decide all moves, then apply) | Order-independent results. | Different emergent behaviour — big change, not recommended unless desired. |

---

## 7. What the pygame rebuild does with this list

`squareverse_pygame/` (see its README) applies §2 by design (one draw per frame, no per-object redraws), §3.3
(in-memory grid, MongoDB dropped), §4 (single ladder + attempt routine), and the §5 bug fixes. It keeps the push /
crush / border / mass-comparison rules from ORIGINAL_LOGIC §7.4 unchanged, and re-enables the child Squareverse as
the source of mass and inertia per the agreed design.
