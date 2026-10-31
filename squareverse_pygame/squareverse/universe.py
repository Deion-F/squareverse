"""The parent Squareverse: grid, Squares, movement and collision rules.

Rules are those of the original god_script.py (documented in docs/ORIGINAL_LOGIC.md §7) with the child Squareverse
re-enabled as the source of mass and inertia. The MongoDB grid is replaced by an in-memory list with the same
semantics: a cell is either empty or holds exactly one Square.
"""

from dataclasses import dataclass, field

from . import config
from .child import ChildUniverse
from .directions import CARDINAL, DELTA, DIAGONAL, INVERSE

FREE, OCCUPIED, BORDER = "free", "occupied", "border"


def _end_by(timing, wave):
    """Make an animation step (and any steps in lockstep with it) finish no later than `wave`."""
    if timing[0] is None or wave < timing[0]:
        timing[0] = wave


@dataclass(eq=False, slots=True)
class Square:
    id: int
    col: int
    row: int
    children: ChildUniverse
    mass: int
    body_color: tuple
    outline_color: tuple
    previous_direction: str | None = None
    bounced: bool = False          # last move was a bounce (not its first-choice direction)
    blocked: bool = False          # failed every attempt and survived (white outline, as in the original)
    alive: bool = True
    directions_already_tried: set = field(default_factory=set)
    # animation of the current tick, one entry per one-cell step:
    # [from_col, from_row, to_col, to_row, start_wave, timing] where timing = [end_wave or None (= end of tick)]
    steps: list = field(default_factory=list)
    last_wave: int = -1

    def position_at(self, wave_time, wave_count):
        """Grid position (floats) at `wave_time` in [0, wave_count] of the current tick's animation."""
        for from_col, from_row, to_col, to_row, start, timing in self.steps:
            end = wave_count if timing[0] is None else timing[0]
            if wave_time >= end:
                continue
            if wave_time <= start:
                return from_col, from_row
            t = (wave_time - start) / (end - start)
            t = t * t * (3 - 2 * t)    # smoothstep
            return from_col + (to_col - from_col) * t, from_row + (to_row - from_row) * t
        return self.col, self.row


@dataclass(slots=True)
class TickStats:
    moved: int = 0
    pushed: int = 0
    crushed: int = 0       # pushed Square squeezed against an equal/heavier one
    border_kills: int = 0  # pushed Square driven into the border
    trapped: int = 0       # mover that failed all ladder attempts (destroyed when CRUSH_WHEN_TRAPPED)


class Squareverse:
    def __init__(self, size_px, grid_spacing, rng, *, diagonal_moves=None, crush_when_trapped=None,
                 child_grid=None, child_count_range=None):
        if size_px % grid_spacing:
            raise ValueError("universe size must be a multiple of the grid spacing")
        self.size_px = size_px
        self.spacing = grid_spacing
        self.n = size_px // grid_spacing
        self.rng = rng
        self.diagonal_moves = config.DIAGONAL_MOVES if diagonal_moves is None else diagonal_moves
        self.crush_when_trapped = config.CRUSH_WHEN_TRAPPED if crush_when_trapped is None else crush_when_trapped
        self.child_grid = child_grid or config.CHILD_GRID
        lo, hi = child_count_range or config.CHILD_COUNT_RANGE
        self.child_count_range = (max(1, lo), min(hi, self.child_grid ** 2))
        self.directions = CARDINAL + DIAGONAL if self.diagonal_moves else CARDINAL
        self.grid = [None] * (self.n * self.n)   # row-major; None = empty cell
        self.squares = {}                         # id -> Square, in spawn order (= original move order)
        self._next_id = 1
        self.tick_count = 0
        self.last_stats = TickStats()
        self._stats = self.last_stats
        # animation bookkeeping for the current tick (see _shift)
        self.wave_count = 1
        self.dying = []           # (square, death_wave): destroyed this tick, drawn until their death wave
        self._vacated = {}        # cell index -> (wave it is free from, direction it was left in, step or None)
        self._hold = {}           # cell index -> wave its occupant must stay until (something collided with it)
        self._blockers = []       # Squares the current mover collided with without moving them
        self.contacts = []        # (a, a_cell, b, b_cell, wave): a and b must be drawn touching at `wave`
        self._max_wave = 0
        self._in_tick = False

    @property
    def max_number_of_squares(self):
        return self.n * self.n

    # --- creation / deletion -------------------------------------------------------------------

    def add_square(self, col, row, *, mass=None, child_positions=None, outline_color=None):
        """Place one Square. Mass = number of children; pass `mass` or explicit `child_positions`."""
        if self.grid[row * self.n + col] is not None:
            raise ValueError(f"cell {(col, row)} is occupied")
        if child_positions is not None:
            children = ChildUniverse(self.child_grid, child_positions)
        else:
            if mass is None:
                mass = self.rng.randint(*self.child_count_range)
            children = ChildUniverse.random(self.child_grid, mass, self.rng)
        mass = len(children)
        # heavier = darker, as in the original (256 - mass), scaled to this mass range
        shade = 255 - round(255 * mass / self.child_count_range[1]) if self.child_count_range[1] else 255
        shade = max(0, min(255, shade))
        if outline_color is None:
            outline_color = (self.rng.randrange(256), self.rng.randrange(256), self.rng.randrange(256))
        square = Square(self._next_id, col, row, children, mass, (shade, shade, shade), outline_color)
        self._next_id += 1
        self.grid[row * self.n + col] = square
        self.squares[square.id] = square
        return square

    def spawn(self, count):
        """Original semantics: spawn `count` Squares on random empty cells, or nothing if there isn't room."""
        empty = [i for i, cell in enumerate(self.grid) if cell is None]
        if count <= 0 or count > len(empty):
            return 0
        for idx in self.rng.sample(empty, count):
            self.add_square(idx % self.n, idx // self.n)
        return count

    def spawn_amount(self, choice):
        """Original menu: m = all empty cells, h = max // 2, q = max // 4, or a number."""
        choice = str(choice).strip().lower()
        if choice == "m":
            return self.max_number_of_squares - len(self.squares)
        if choice == "h":
            return self.max_number_of_squares // 2
        if choice == "q":
            return self.max_number_of_squares // 4
        return int(choice)

    def destroy(self, square, not_before=0):
        """Remove a Square. During a tick, returns the animation wave at which it disappears."""
        if not square.alive:
            return None
        death_wave = self._ready_wave(square, not_before) if self._in_tick else None
        square.alive = False
        idx = square.row * self.n + square.col
        self.grid[idx] = None
        del self.squares[square.id]
        if self._in_tick:
            if square.steps:
                _end_by(square.steps[-1][5], death_wave)
            self._vacated[idx] = (death_wave, None, None)
            self.dying.append((square, death_wave))
            self._max_wave = max(self._max_wave, death_wave)
        return death_wave

    def clear_animation(self):
        """Snap every Square to its final position (used when movement stops)."""
        for square in self.squares.values():
            square.steps.clear()
        self.dying.clear()
        self.wave_count = 1

    def destroy_all(self):
        for square in list(self.squares.values()):
            self.destroy(square)

    def square_at(self, col, row):
        if 0 <= col < self.n and 0 <= row < self.n:
            return self.grid[row * self.n + col]
        return None

    # --- simulation ----------------------------------------------------------------------------

    def tick(self):
        """One cycle: every Square gets one move, sequentially, in spawn order (original moveAllSquares)."""
        self._stats = TickStats()
        squares = list(self.squares.values())   # snapshot: destroys no longer skip the next Square (bug B3)
        for square in squares:
            square.steps.clear()
            square.last_wave = -1
        self._vacated.clear()
        self._hold.clear()
        self.contacts.clear()
        self.dying.clear()
        self._max_wave = 0
        self._in_tick = True
        try:
            for square in squares:
                if square.alive:
                    self.move_square(square)
        finally:
            self._in_tick = False
        self.wave_count = self._max_wave + 1
        self.tick_count += 1
        self.last_stats = self._stats
        return self._stats

    def check(self, col, row, direction):
        """Original collision_check_parent_squareverse: (BORDER, None) / (OCCUPIED, occupant) / (FREE, None)."""
        dc, dr = DELTA[direction]
        col += dc
        row += dr
        if col < 0 or row < 0 or col >= self.n or row >= self.n:
            return BORDER, None
        occupant = self.grid[row * self.n + col]
        return (OCCUPIED, occupant) if occupant is not None else (FREE, None)

    def move_square(self, square):
        """The attempt ladder.

        1. previous direction (momentum) -- or, with no momentum, the child universe's dominant side after
           SPAWN_CHILD_CYCLES child cycles; with momentum, the dominant side overrides it only when ALL children
           sit in one half (original a41bbab rule)
        2. the inverse of attempt 1 (bounce)
        3. the untried direction whose side holds the most child Squares (random only on a tie)
        4. the next untried direction with the most child Squares (random only on a tie)
        then: trapped -> destroyed (CRUSH_WHEN_TRAPPED) or stays with a white outline.
        """
        square.blocked = False
        self._blockers = []
        tried = square.directions_already_tried
        tried.clear()
        children = square.children
        if square.previous_direction is None:
            children.run(config.SPAWN_CHILD_CYCLES, tried, self.rng)
            first = children.dominant(self.rng)[1]
        else:
            single, side = children.dominant(self.rng)
            # right after a bounce momentum wins once; otherwise a light Square (children all in one half) would
            # head back into whatever just blocked it and ping-pong between two cells
            first = side if single and not square.bounced else square.previous_direction

        for direction in (first, INVERSE[first]):
            tried.add(direction)
            if self.attempt(square, direction):
                square.bounced = direction != first
                return self._after_move(square)

        for _ in range(2):
            direction = children.most_populated([d for d in self.directions if d not in tried], self.rng)
            if direction is None:
                break
            tried.add(direction)
            if self.attempt(square, direction):
                square.bounced = True
                return self._after_move(square)

        self._stats.trapped += 1
        if self.crush_when_trapped:
            cell = (square.col, square.row)
            death_wave = self.destroy(square, self._arrival_wave(self._blockers))
            self._touch(square, cell, self._blockers, death_wave)
        else:
            square.blocked = True

    def _after_move(self, square):
        # original a41bbab: one child cycle after every successful parent move
        square.children.run(config.MOVE_CHILD_CYCLES, square.directions_already_tried, self.rng)

    def attempt(self, mover, direction):
        """One ladder attempt (ORIGINAL_LOGIC.md §7.4). Returns True if the mover moved."""
        result, occupant = self.check(mover.col, mover.row, direction)
        mover_cell = (mover.col, mover.row)
        if result is FREE:
            wave = self._shift(mover, direction, self._arrival_wave(self._blockers))
            self._touch(mover, mover_cell, self._blockers, wave)
            mover.previous_direction = direction
            self._stats.moved += 1
            return True
        if result is BORDER:
            return False
        if mover.mass <= occupant.mass:
            self._blockers.append(occupant)
            return False

        # push: only strictly heavier Squares push; masses in the chain are compared pairwise
        chain = [occupant]
        victim = against = None
        while True:
            front = chain[-1]
            result, next_square = self.check(front.col, front.row, direction)
            if result is FREE:
                break
            if result is BORDER or front.mass <= next_square.mass:
                if not self.crush_when_trapped:   # --no-crush: a push that would destroy a Square is blocked
                    self._blockers.append(occupant)
                    return False
                victim = chain.pop()
                if result is BORDER:
                    self._stats.border_kills += 1
                else:
                    against = next_square
                    self._stats.crushed += 1
                break
            chain.append(next_square)

        # the whole chain starts moving together, once every Square involved has arrived and is free to go
        involved = chain + [mover] + ([victim] if victim else [])
        start = max(max(self._ready_wave(sq) for sq in involved),
                    self._arrival_wave(self._blockers + ([against] if against else [])))
        if victim is not None:
            victim_cell = (victim.col, victim.row)
            death_wave = self.destroy(victim, start)
            if against is not None:
                self._touch(victim, victim_cell, [against], death_wave)

        # far end first, each Square into the next cell (fixes bug B1, which wrote every chain Square to one cell)
        for pushed in reversed(chain):
            self._shift(pushed, direction, start)
            if pushed.previous_direction is None:
                pushed.previous_direction = direction
        self._stats.pushed += len(chain)
        wave = self._shift(mover, direction, start)
        self._touch(mover, mover_cell, self._blockers, wave)
        mover.previous_direction = direction
        self._stats.moved += 1
        return True

    # --- animation timing ----------------------------------------------------------------------

    def _ready_wave(self, square, not_before=0):
        """Earliest wave a Square can start its next step (or disappear)."""
        held = self._hold.get(square.row * self.n + square.col, 0)
        return max(square.last_wave + 1, held, not_before)

    @staticmethod
    def _arrival_wave(squares):
        """Wave by which every Square in `squares` has finished arriving where it is now."""
        return max((sq.last_wave + 1 for sq in squares), default=0)

    def _touch(self, square, cell, others, wave):
        """`square` (at `cell`) collided with `others`: draw them touching at `wave`.

        Each other Square must have arrived by then and stays in place until then, so a bounce or a crush is
        never shown before the two Squares actually meet.
        """
        if wave is None:   # outside a tick (direct calls): nothing is animated
            return
        n = self.n
        for other in others:
            if other.steps:
                _end_by(other.steps[-1][5], wave)
            idx = other.row * n + other.col
            if self._hold.get(idx, -1) < wave:
                self._hold[idx] = wave
            self.contacts.append((square, cell, other, (other.col, other.row), wave))

    def _shift(self, square, direction, not_before=0):
        """Move one cell, schedule the step's animation wave and return it.

        Moves happen one after another, but are drawn concurrently. A step may only start once the cell it enters
        has been left: in the same wave if the previous occupant left in the same direction (they slide in
        lockstep and share timing), otherwise in the next wave. Each slide lasts until its Square must move again,
        another Square needs the cell it is leaving, or the tick ends - so most Squares glide for the whole tick.
        """
        dc, dr = DELTA[direction]
        n = self.n
        from_idx = square.row * n + square.col
        to_col, to_row = square.col + dc, square.row + dr
        to_idx = to_row * n + to_col
        wave = self._ready_wave(square, not_before)
        timing = None
        vacated = self._vacated.get(to_idx)
        if vacated is not None:
            free_wave, left_direction, left_step = vacated
            wave = max(wave, free_wave if left_direction in (None, direction) else free_wave + 1)
            if left_step is not None:
                if left_direction == direction and wave == left_step[4]:
                    timing = left_step[5]                 # lockstep with the Square ahead
                else:
                    _end_by(left_step[5], wave)           # the Square ahead must be clear before this starts
        if square.steps:
            _end_by(square.steps[-1][5], wave)            # finish the previous step first
        step = [square.col, square.row, to_col, to_row, wave, timing or [None]]
        square.steps.append(step)
        self._vacated[from_idx] = (wave, direction, step)
        square.last_wave = wave
        self._max_wave = max(self._max_wave, wave)

        self.grid[from_idx] = None
        square.col, square.row = to_col, to_row
        self.grid[to_idx] = square
        return wave
