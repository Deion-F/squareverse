"""Physics engine for collision detection and force calculations."""

import numpy as np
from typing import List, Dict, Tuple, Optional
from .square import Square


class PhysicsEngine:
    """Handles physics calculations and collision detection."""
    
    def __init__(self):
        """Initialize the physics engine."""
        self.collision_elasticity = 0.8  # Energy retention in collisions
        
    def detect_collisions(self, squares: List[Square], grid_width: int, grid_height: int) -> List[Tuple[Square, Square]]:
        """
        Detect all collisions between squares.
        
        Args:
            squares: List of all squares in the simulation
            grid_width: Width of the grid
            grid_height: Height of the grid
            
        Returns:
            List of tuples containing colliding square pairs
        """
        collisions = []
        position_map: Dict[Tuple[int, int], List[Square]] = {}
        
        # Build position map
        for square in squares:
            pos = (square.x, square.y)
            if pos not in position_map:
                position_map[pos] = []
            position_map[pos].append(square)
        
        # Find squares occupying the same cell
        for pos, squares_at_pos in position_map.items():
            if len(squares_at_pos) > 1:
                # Multiple squares at same position - collision!
                for i in range(len(squares_at_pos)):
                    for j in range(i + 1, len(squares_at_pos)):
                        collisions.append((squares_at_pos[i], squares_at_pos[j]))
        
        return collisions
    
    def resolve_collision(self, square1: Square, square2: Square, grid_width: int, grid_height: int):
        """
        Resolve collision between two squares using mass-based physics.
        Heavier squares push lighter squares.
        
        Args:
            square1: First square
            square2: Second square
            grid_width: Width of the grid
            grid_height: Height of the grid
        """
        # For collisions, the heavier square should keep moving and push the lighter out of the way.
        # Identify heavy and light square
        if square1.mass >= square2.mass:
            heavy, light = square1, square2
        else:
            heavy, light = square2, square1

        # Capture lighter square's prior velocity to decide push behavior
        light_prev_v = (int(np.sign(light.vx)), int(np.sign(light.vy)))

        # Determine heavy's movement direction. Prefer its current velocity; if zero, infer from positions.
        hvx, hvy = heavy.vx, heavy.vy
        if hvx == 0 and hvy == 0:
            # Infer from positions: move from heavy's pos toward light's pos
            dx = light.x - heavy.x
            dy = light.y - heavy.y
            if abs(dx) >= abs(dy):
                hvx = 1 if dx > 0 else -1
                hvy = 0
            else:
                hvx = 0
                hvy = 1 if dy > 0 else -1

        # Force heavy to keep moving in its direction
        heavy.vx, heavy.vy = int(np.sign(hvx)), int(np.sign(hvy))

        # If equal mass, try to push both apart randomly
        if square1.mass == square2.mass:
            self._push_squares_apart(square1, square2, grid_width, grid_height)
            return

        # If the lighter was moving towards the heavy just before collision, push it in the
        # heavy's movement direction; otherwise infer away-from-heavy direction.
        # Determine if light was moving towards heavy (dot product > 0)
        vec_to_heavy = (heavy.x - light.x, heavy.y - light.y)
        dot = vec_to_heavy[0] * light_prev_v[0] + vec_to_heavy[1] * light_prev_v[1]
        if dot > 0:
            # light was moving toward heavy -> push in heavy's direction
            push_dir = (heavy.vx, heavy.vy)
        else:
            push_dir = None

        # Push the lighter square preferentially using push_dir logic
        self._push_square_away(light, heavy, grid_width, grid_height, push_dir=push_dir)
    
    def _push_square_away(self, light_square: Square, heavy_square: Square, 
                          grid_width: int, grid_height: int, push_dir: Optional[Tuple[int, int]] = None):
        """Push lighter square away from heavier square.

        If push_dir is provided, attempt to push the light square in that direction first.
        Otherwise infer a direction away from the heavy square. If the preferred direction
        is blocked (out of bounds or occupied), attempt other cardinal directions randomly.
        """
        # Preferred push direction
        if push_dir is not None and (push_dir[0] != 0 or push_dir[1] != 0):
            pref = (int(push_dir[0]), int(push_dir[1]))
        else:
            # Infer away-from-heavy direction
            dx = light_square.x - heavy_square.x
            dy = light_square.y - heavy_square.y
            if dx == 0 and dy == 0:
                # Same position: choose a random cardinal direction
                dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]
                pref = dirs[np.random.randint(0, 4)]
            else:
                if abs(dx) >= abs(dy):
                    pref = (1, 0) if dx > 0 else (-1, 0)
                else:
                    pref = (0, 1) if dy > 0 else (0, -1)

        # All cardinal directions, prefer the push direction first
        all_dirs = [pref] + [d for d in [(1, 0), (-1, 0), (0, 1), (0, -1)] if d != pref]
        # Shuffle the remaining to randomize fallback attempts
        remaining = all_dirs[1:]
        np.random.shuffle(remaining)
        candidates = [all_dirs[0]] + remaining

        # Try candidates and accept first legal move (within bounds). Occupancy checks
        # are best-effort here; caller may still need to handle final collisions.
        moved = False
        for d in candidates:
            tx = light_square.x + d[0]
            ty = light_square.y + d[1]
            tx = int(max(0, min(tx, grid_width - 1)))
            ty = int(max(0, min(ty, grid_height - 1)))
            # If target is same as heavy's position and heavy isn't leaving, skip
            if (tx, ty) == (heavy_square.x, heavy_square.y):
                # allow if heavy will move out (best-effort: if heavy has non-zero velocity)
                if heavy_square.vx == 0 and heavy_square.vy == 0:
                    continue
            # Accept move
            light_square.x = tx
            light_square.y = ty
            moved = True
            break

        if not moved:
            # Can't move - stay in place (caller will mark stalled)
            return
    
    def _push_squares_apart(self, square1: Square, square2: Square, 
                            grid_width: int, grid_height: int):
        """Push two equal-mass squares apart."""
        # Push both squares in opposite directions (cardinal directions only)
        direction = np.random.randint(0, 2)  # 0=horizontal, 1=vertical
        if direction == 0:
            # Horizontal movement
            dx, dy = 1, 0
        else:
            # Vertical movement
            dx, dy = 0, 1
        
        new_x1 = max(0, min(square1.x + dx, grid_width - 1))
        new_y1 = max(0, min(square1.y + dy, grid_height - 1))
        
        new_x2 = max(0, min(square2.x - dx, grid_width - 1))
        new_y2 = max(0, min(square2.y - dy, grid_height - 1))
        
        square1.x = int(new_x1)
        square1.y = int(new_y1)
        square2.x = int(new_x2)
        square2.y = int(new_y2)
    
    def update_physics(self, squares: List[Square], grid_width: int, grid_height: int):
        """
        Update physics for all squares (movement and collisions).
        
        Args:
            squares: List of all squares
            grid_width: Width of the grid
            grid_height: Height of the grid
        """
        # Plan moves: compute desired positions with wall bouncing handled
        planned = []  # list of (square, desired_x, desired_y)
        for square in squares:
            # Compute desired position
            dx = square.vx
            dy = square.vy
            desired_x = square.x + dx
            desired_y = square.y + dy

            # Handle wall bounce by inverting velocity if out of bounds
            if desired_x < 0 or desired_x >= grid_width:
                square.vx = -square.vx
                desired_x = square.x + square.vx
            if desired_y < 0 or desired_y >= grid_height:
                square.vy = -square.vy
                desired_y = square.y + square.vy

            # Ensure desired are ints and within bounds
            desired_x = int(max(0, min(desired_x, grid_width - 1)))
            desired_y = int(max(0, min(desired_y, grid_height - 1)))

            planned.append((square, desired_x, desired_y))

        # Sort by mass descending so heavier squares get movement priority
        planned.sort(key=lambda t: t[0].mass, reverse=True)

        # Reserve final positions to avoid duplicates
        reserved = set()
        # We'll also allow swapping: if a heavy square moves into a lighter square's cell,
        # the lighter may move out later in the loop if its desired cell is free.

        # Track new positions to assign after planning
        new_positions = {}

        # Build maps for swap detection: original position -> square, and desired map
        orig_pos_map = {(s.x, s.y): s for s in squares}
        planned_map = {s.id: (dx, dy) for (s, dx, dy) in planned}

        for square, dx, dy in planned:
            cur = (square.x, square.y)
            desired = (dx, dy)

            # If desired equals current, just keep position
            if desired == cur:
                new_positions[square.id] = cur
                reserved.add(cur)
                square.stalled = False
                continue

            # Prepare candidate directions in order:
            # 1) desired (current velocity)
            # 2) opposite direction
            # 3-4) the two remaining directions in random order
            vx = desired[0] - cur[0]
            vy = desired[1] - cur[1]

            # Opposite
            opp = (-vx, -vy)

            # All cardinal directions
            all_dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)]

            # Determine remaining dirs excluding desired and opposite
            remaining = [d for d in all_dirs if d != (vx, vy) and d != opp]
            # Shuffle remaining order
            np.random.shuffle(remaining)

            candidates = [(vx, vy), opp] + remaining

            moved = False
            for cand in candidates:
                tx = cur[0] + cand[0]
                ty = cur[1] + cand[1]

                # Keep within bounds
                tx = int(max(0, min(tx, grid_width - 1)))
                ty = int(max(0, min(ty, grid_height - 1)))

                target = (tx, ty)

                # Detect two-way swap: target is another square's original position
                other = orig_pos_map.get(target)
                if other is not None:
                    other_desired = planned_map.get(other.id)
                    # other_desired is a tuple (dx,dy) or None; compute desired pos for other
                    if other_desired is not None:
                        other_desired_pos = other_desired
                        # If other intended to move into our current position, that's a swap
                        if other_desired_pos == cur:
                            # Skip this target to avoid two-way swap
                            continue

                # If target not reserved, allow move and set velocity to cand
                if target not in reserved:
                    new_positions[square.id] = target
                    reserved.add(target)
                    # update velocity to the actual move direction
                    square.vx, square.vy = cand[0], cand[1]
                    square.stalled = False
                    moved = True
                    break

            if not moved:
                # Couldn't move in any direction -> stalled
                new_positions[square.id] = cur
                reserved.add(cur)
                square.stalled = True

        # Apply new positions
        id_to_square = {s.id: s for s in squares}
        for sid, pos in new_positions.items():
            s = id_to_square.get(sid)
            if s is None:
                continue
            s.x, s.y = pos

        # Update occupied positions (caller should do this as well)
        # Detect and resolve any remaining collisions defensively
        collisions = self.detect_collisions(squares, grid_width, grid_height)
        for square1, square2 in collisions:
            # If collision remains, resolve velocities and attempt to push
            self.resolve_collision(square1, square2, grid_width, grid_height)
