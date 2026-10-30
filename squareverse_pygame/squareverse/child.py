"""The child Squareverse: a hidden mini universe inside every parent Square.

Its children determine the parent's mass (one unit per child) and its inertia: the parent is steered towards the
half of the mini universe holding the most children (see ORIGINAL_LOGIC.md §9). Children move with the original
child rules (previous direction -> inverse -> random), have no mass and never push.
"""

from .directions import CARDINAL, DELTA, INVERSE


class ChildUniverse:
    __slots__ = ("n", "half", "cells", "children", "quadrants")

    def __init__(self, n, positions):
        """n: cells per side. positions: iterable of (col, row) for each child."""
        self.n = n
        # original: a cell is in the "up" half when its top-left y < centre point -> first (n + 1) // 2 rows
        self.half = (n + 1) // 2
        self.cells = bytearray(n * n)
        self.children = []  # [col, row, previous_direction]
        # quadrants[v][h]: v = 0 up / 1 down, h = 0 left / 1 right
        self.quadrants = [[0, 0], [0, 0]]
        for col, row in positions:
            idx = row * n + col
            if self.cells[idx]:
                raise ValueError(f"two children at {(col, row)}")
            self.cells[idx] = 1
            self.children.append([col, row, None])
            self.quadrants[row >= self.half][col >= self.half] += 1

    @classmethod
    def random(cls, n, count, rng):
        # original placed children in cell-id order (column-major); keep that iteration order
        cells = sorted(rng.sample(range(n * n), count), key=lambda i: (i % n, i // n))
        return cls(n, ((i % n, i // n) for i in cells))

    # --- reading the mini universe -------------------------------------------------------------

    def __len__(self):
        return len(self.children)

    def counts(self):
        (ul, ur), (dl, dr) = self.quadrants
        return {"up": ul + ur, "down": dl + dr, "left": ul + dl, "right": ur + dr}

    def score(self, direction):
        """Number of children on the side of the mini universe that `direction` points to.

        Diagonals (only used when config.DIAGONAL_MOVES is on) count their quadrant, doubled so a quadrant competes
        fairly with a half.
        """
        (ul, ur), (dl, dr) = self.quadrants
        return {
            "up": ul + ur, "down": dl + dr, "left": ul + dl, "right": ur + dr,
            "d_left_up": 2 * ul, "d_right_up": 2 * ur, "d_left_down": 2 * dl, "d_right_down": 2 * dr,
        }[direction]

    def dominant(self, rng):
        """Original moveChildSquares/checkChildSquarePositions result.

        Returns (True, side) when every child sits in one half (checked up, down, left, right -- fixes bug C2, which
        could only ever detect "up"), otherwise (False, side with the most children, ties broken randomly).
        """
        counts = self.counts()
        total = len(self.children)
        if total:
            for side in CARDINAL:
                if counts[side] == total:
                    return True, side
        best = max(counts.values())
        return False, rng.choice([side for side in CARDINAL if counts[side] == best])

    def most_populated(self, candidates, rng):
        """The candidate direction with the most children; random only between tied candidates."""
        if not candidates:
            return None
        scores = {d: self.score(d) for d in candidates}
        best = max(scores.values())
        return rng.choice([d for d in candidates if scores[d] == best])

    # --- moving the children -------------------------------------------------------------------

    def run(self, cycles, parent_tried, rng):
        """Move every child once per cycle (fixes bug C1: the original cursor only ever ran one cycle)."""
        for _ in range(cycles):
            for child in self.children:
                self._move_child(child, parent_tried, rng)

    def _move_child(self, child, parent_tried, rng):
        # original: children inherit the directions the parent already tried this move
        tried = set(parent_tried)
        previous = child[2]
        if previous is None or previous in tried:
            self._random_until_free(child, tried, rng)
            return
        tried.add(previous)
        if self._try(child, previous):
            return
        inverse = INVERSE[previous]
        if inverse not in tried:
            tried.add(inverse)
            if self._try(child, inverse):
                return
        self._random_until_free(child, tried, rng)

    def _random_until_free(self, child, tried, rng):
        # bug C3 fix: only the child's own 4 directions count, so the loop always terminates
        remaining = [d for d in CARDINAL if d not in tried]
        while remaining:
            direction = rng.choice(remaining)
            remaining.remove(direction)
            if self._try(child, direction):
                return

    def _try(self, child, direction):
        dc, dr = DELTA[direction]
        col, row = child[0], child[1]
        new_col, new_row = col + dc, row + dr
        n = self.n
        if new_col < 0 or new_row < 0 or new_col >= n or new_row >= n:
            return False
        new_idx = new_row * n + new_col
        if self.cells[new_idx]:
            return False
        self.cells[row * n + col] = 0
        self.cells[new_idx] = 1
        half = self.half
        self.quadrants[row >= half][col >= half] -= 1
        self.quadrants[new_row >= half][new_col >= half] += 1
        child[0], child[1], child[2] = new_col, new_row, direction
        return True
