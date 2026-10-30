"""Rule tests for the movement / mass / collision logic (run: python -m unittest discover -s tests)."""

import random
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from squareverse import config  # noqa: E402
from squareverse.child import ChildUniverse  # noqa: E402
from squareverse.universe import Squareverse  # noqa: E402

N = 12  # child grid
HALF = 6


def kids(up_left=0, up_right=0, down_left=0, down_right=0):
    """Child positions with the given number of children per quadrant of the 12x12 mini universe."""
    out = []
    for count, (c0, r0) in ((up_left, (0, 0)), (up_right, (HALF, 0)), (down_left, (0, HALF)),
                            (down_right, (HALF, HALF))):
        cells = [(c0 + i % HALF, r0 + i // HALF) for i in range(count)]
        out.extend(cells)
    return out


def balanced(mass):
    """`mass` children spread over all four quadrants (no single dominant half)."""
    q, r = divmod(mass, 4)
    return kids(q + (r > 0), q + (r > 1), q + (r > 2), q)


def universe(seed=0, **kw):
    return Squareverse(100, 10, random.Random(seed), **kw)   # 10 x 10 grid


class MassTests(unittest.TestCase):
    def test_mass_is_number_of_children(self):
        u = universe()
        sq = u.add_square(1, 1, child_positions=balanced(17))
        self.assertEqual(sq.mass, 17)
        self.assertEqual(len(sq.children), 17)

    def test_random_mass_within_range(self):
        u = universe(child_count_range=(5, 9))
        u.spawn(30)
        self.assertTrue(all(5 <= sq.mass <= 9 for sq in u.squares.values()))

    def test_spawn_is_all_or_nothing(self):
        u = universe()
        self.assertEqual(u.spawn(101), 0)
        self.assertEqual(len(u.squares), 0)
        self.assertEqual(u.spawn(100), 100)


class AttemptTests(unittest.TestCase):
    def test_free_move_keeps_momentum(self):
        u = universe()
        a = u.add_square(5, 5, child_positions=balanced(8))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertEqual((a.col, a.row), (6, 5))
        self.assertIs(u.square_at(6, 5), a)
        self.assertIsNone(u.square_at(5, 5))

    def test_heavier_pushes_whole_chain_one_cell_each(self):
        u = universe()
        a = u.add_square(2, 5, child_positions=balanced(10))
        b = u.add_square(3, 5, child_positions=balanced(4))
        c = u.add_square(4, 5, child_positions=balanced(2))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertEqual([(s.col, s.row) for s in (a, b, c)], [(3, 5), (4, 5), (5, 5)])
        self.assertEqual([u.square_at(x, 5) for x in (2, 3, 4, 5)], [None, a, b, c])
        self.assertEqual(c.previous_direction, "right")   # idle pushed Squares inherit the push direction

    def test_pushed_square_keeps_its_own_momentum(self):
        u = universe()
        a = u.add_square(2, 5, child_positions=balanced(10))
        b = u.add_square(3, 5, child_positions=balanced(4))
        a.previous_direction, b.previous_direction = "right", "up"
        u.move_square(a)
        self.assertEqual(b.previous_direction, "up")

    def test_light_square_crushed_against_heavier(self):
        u = universe()
        a = u.add_square(2, 5, child_positions=balanced(10))
        b = u.add_square(3, 5, child_positions=balanced(3))
        c = u.add_square(4, 5, child_positions=balanced(5))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertFalse(b.alive)
        self.assertEqual((a.col, a.row), (3, 5))
        self.assertEqual((c.col, c.row), (4, 5))
        self.assertEqual(u._stats.crushed, 1)

    def test_equal_mass_in_chain_is_crushed(self):
        u = universe()
        a = u.add_square(2, 5, child_positions=balanced(10))
        b = u.add_square(3, 5, child_positions=balanced(4))
        c = u.add_square(4, 5, child_positions=balanced(4))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertFalse(b.alive)
        self.assertTrue(c.alive)

    def test_pushed_into_border_is_destroyed(self):
        u = universe()
        a = u.add_square(8, 5, child_positions=balanced(10))
        b = u.add_square(9, 5, child_positions=balanced(3))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertFalse(b.alive)
        self.assertEqual((a.col, a.row), (9, 5))

    def test_equal_mass_blocks_then_bounces(self):
        u = universe()
        a = u.add_square(5, 5, child_positions=balanced(6))
        u.add_square(6, 5, child_positions=balanced(6))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertEqual((a.col, a.row), (4, 5))
        self.assertEqual(a.previous_direction, "left")

    def test_border_bounces(self):
        u = universe()
        a = u.add_square(9, 5, child_positions=balanced(6))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertEqual((a.col, a.row), (8, 5))


class LadderTests(unittest.TestCase):
    def _blocked_sideways(self, children, seed=0):
        u = universe(seed)
        a = u.add_square(5, 5, child_positions=children)
        u.add_square(6, 5, child_positions=balanced(40))   # heavier: blocks attempt 1 (right)
        u.add_square(4, 5, child_positions=balanced(40))   # heavier: blocks attempt 2 (left)
        a.previous_direction = "right"
        u.move_square(a)
        return a

    def test_attempt_three_uses_side_with_more_children(self):
        a = self._blocked_sideways(kids(up_left=1, up_right=1, down_left=3, down_right=3))
        self.assertEqual((a.col, a.row), (5, 6))   # down: 6 children vs up: 2

        a = self._blocked_sideways(kids(up_left=4, up_right=3, down_left=1, down_right=1))
        self.assertEqual((a.col, a.row), (5, 4))   # up: 7 vs down: 2

    def test_attempt_three_random_only_on_tie(self):
        seen = Counter()
        for seed in range(40):
            a = self._blocked_sideways(kids(up_left=2, up_right=2, down_left=2, down_right=2), seed)
            seen[(a.col, a.row)] += 1
        self.assertEqual(set(seen), {(5, 4), (5, 6)})

    def test_attempt_four_uses_remaining_direction(self):
        u = universe()
        a = u.add_square(5, 5, child_positions=kids(1, 1, 3, 3))
        for cell in ((6, 5), (4, 5), (5, 6)):              # right, left and down (the more populated) blocked
            u.add_square(*cell, child_positions=balanced(40))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertEqual((a.col, a.row), (5, 4))
        self.assertEqual(a.directions_already_tried, {"right", "left", "down", "up"})

    def test_trapped_square_is_destroyed(self):
        u = universe()
        a = u.add_square(5, 5, child_positions=balanced(4))
        for cell in ((6, 5), (4, 5), (5, 6), (5, 4)):
            u.add_square(*cell, child_positions=balanced(40))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertFalse(a.alive)

    def test_trapped_square_survives_without_crush(self):
        u = universe(crush_when_trapped=False)
        a = u.add_square(5, 5, child_positions=balanced(4))
        for cell in ((6, 5), (4, 5), (5, 6), (5, 4)):
            u.add_square(*cell, child_positions=balanced(40))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertTrue(a.alive)
        self.assertTrue(a.blocked)

    def test_all_children_on_one_side_override_momentum(self):
        u = universe()
        a = u.add_square(5, 5, child_positions=kids(up_left=3, up_right=3))
        a.previous_direction = "right"
        u.move_square(a)
        self.assertEqual((a.col, a.row), (5, 4))

    def test_no_momentum_follows_children(self):
        u = universe()
        a = u.add_square(5, 5, child_positions=kids(up_left=1, up_right=1, down_left=2, down_right=4))
        with mock.patch.object(config, "SPAWN_CHILD_CYCLES", 0):   # isolate the selection rule from child motion
            u.move_square(a)
        self.assertEqual((a.col, a.row), (5, 6))   # down 6, right 5, left 3, up 2

    def test_no_momentum_runs_spawn_cycles_first(self):
        u = universe()
        a = u.add_square(5, 5, child_positions=[(0, 0)])
        a.children.children[0][2] = "right"
        u.move_square(a)
        # 5 spawn cycles + 1 cycle after the move (which may not reuse the direction the parent just took)
        self.assertGreaterEqual(a.children.children[0][0], 5)


class ChildUniverseTests(unittest.TestCase):
    def test_single_side_detection_all_four_sides(self):
        rng = random.Random(0)
        self.assertEqual(ChildUniverse(N, kids(up_left=2, up_right=2)).dominant(rng), (True, "up"))
        self.assertEqual(ChildUniverse(N, kids(down_left=2, down_right=2)).dominant(rng), (True, "down"))
        self.assertEqual(ChildUniverse(N, kids(up_left=2, down_left=2)).dominant(rng), (True, "left"))
        self.assertEqual(ChildUniverse(N, kids(up_right=2, down_right=2)).dominant(rng), (True, "right"))

    def test_dominant_side_without_single(self):
        rng = random.Random(0)
        self.assertEqual(ChildUniverse(N, kids(1, 5, 1, 1)).dominant(rng), (False, "right"))

    def test_cycles_really_repeat(self):
        cu = ChildUniverse(N, [(0, 0)])
        cu.children[0][2] = "right"
        cu.run(3, set(), random.Random(0))
        self.assertEqual(cu.children[0][:2], [3, 0])

    def test_child_avoids_directions_parent_tried(self):
        cu = ChildUniverse(N, [(5, 5)])
        cu.children[0][2] = "right"
        cu.run(1, {"right", "left", "up"}, random.Random(0))
        self.assertEqual(cu.children[0][:2], [5, 6])

    def test_counts_track_moves(self):
        rng = random.Random(3)
        cu = ChildUniverse.random(N, 50, rng)
        for _ in range(20):
            cu.run(1, set(), rng)
            expected_up = sum(1 for c, r, _ in cu.children if r < HALF)
            expected_left = sum(1 for c, r, _ in cu.children if c < HALF)
            counts = cu.counts()
            self.assertEqual((counts["up"], counts["left"]), (expected_up, expected_left))
            self.assertEqual(sum(cu.cells), 50)


class TickTests(unittest.TestCase):
    def test_grid_and_squares_stay_consistent(self):
        u = universe(7)
        u.spawn(60)
        for _ in range(50):
            u.tick()
            on_grid = [sq for sq in u.grid if sq is not None]
            self.assertEqual(len(on_grid), len(u.squares))
            for sq in u.squares.values():
                self.assertIs(u.square_at(sq.col, sq.row), sq)

    def test_seeded_runs_are_reproducible(self):
        def run(seed):
            u = universe(seed)
            u.spawn(40)
            for _ in range(30):
                u.tick()
            return sorted((sq.id, sq.col, sq.row) for sq in u.squares.values())
        self.assertEqual(run(11), run(11))


class AnimationTests(unittest.TestCase):
    """Smooth movement replays each tick in waves; drawn Squares must never overlap."""

    @staticmethod
    def drawn_positions(u, wave_time):
        pos = [sq.position_at(wave_time, u.wave_count) for sq in u.squares.values()]
        pos += [sq.position_at(wave_time, u.wave_count) for sq, death_wave in u.dying if wave_time < death_wave]
        return pos

    def assert_no_overlap(self, positions, context):
        positions = sorted(positions)
        for i, (x, y) in enumerate(positions):
            for x2, y2 in positions[i + 1:]:
                if x2 - x >= 1 - 1e-9:
                    break
                if abs(y2 - y) < 1 - 1e-9:
                    self.fail(f"Squares overlap at {(x, y)} / {(x2, y2)} ({context})")

    def test_no_visual_overlap_during_ticks(self):
        for seed, count in ((3, 50), (5, 70), (8, 90)):        # dense 10x10 grids: lots of pushes and crushes
            u = universe(seed)
            u.spawn(count)
            for tick in range(40):
                u.tick()
                samples = 8 * u.wave_count
                for k in range(samples + 1):
                    wave_time = u.wave_count * k / samples
                    self.assert_no_overlap(self.drawn_positions(u, wave_time), f"seed {seed} tick {tick} t={wave_time}")

    def test_steps_are_single_cells_in_increasing_waves(self):
        u = universe(4)
        u.spawn(70)
        for _ in range(30):
            u.tick()
            for sq in u.squares.values():
                waves = [step[4] for step in sq.steps]
                self.assertEqual(waves, sorted(set(waves)))
                for fc, fr, tc, tr, _, _ in sq.steps:
                    self.assertEqual(abs(tc - fc) + abs(tr - fr), 1)
                if sq.steps:
                    self.assertEqual(tuple(sq.steps[-1][2:4]), (sq.col, sq.row))
                    self.assertEqual(sq.position_at(u.wave_count, u.wave_count), (sq.col, sq.row))

    def test_collisions_are_drawn_touching(self):
        checked = 0
        for seed, count in ((3, 50), (5, 70), (8, 90)):
            u = universe(seed)
            u.spawn(count)
            for tick in range(40):
                u.tick()
                for a, a_cell, b, b_cell, wave in u.contacts:
                    self.assertEqual(abs(a_cell[0] - b_cell[0]) + abs(a_cell[1] - b_cell[1]), 1)
                    t = max(wave - 1e-4, 0)           # the instant before the bounce / crush is shown
                    for sq, cell in ((a, a_cell), (b, b_cell)):
                        x, y = sq.position_at(t, u.wave_count)
                        self.assertAlmostEqual(x, cell[0], places=3, msg=f"seed {seed} tick {tick}")
                        self.assertAlmostEqual(y, cell[1], places=3, msg=f"seed {seed} tick {tick}")
                    checked += 1
        self.assertGreater(checked, 100)


if __name__ == "__main__":
    unittest.main()
