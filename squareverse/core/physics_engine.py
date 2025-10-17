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
        # Calculate mass ratio
        total_mass = square1.mass + square2.mass
        mass_ratio_1 = square1.mass / total_mass
        mass_ratio_2 = square2.mass / total_mass
        
        # Exchange velocities based on mass (elastic collision in 2D)
        # Conservation of momentum: m1*v1 + m2*v2 = m1*v1' + m2*v2'
        # Conservation of energy (with elasticity factor)
        
        v1x_old, v1y_old = square1.vx, square1.vy
        v2x_old, v2y_old = square2.vx, square2.vy
        
        # Calculate new velocities using 1D collision formula applied to each axis
        new_vx1 = (v1x_old * (square1.mass - square2.mass) + 2 * square2.mass * v2x_old) / total_mass * self.collision_elasticity
        new_vy1 = (v1y_old * (square1.mass - square2.mass) + 2 * square2.mass * v2y_old) / total_mass * self.collision_elasticity
        
        new_vx2 = (v2x_old * (square2.mass - square1.mass) + 2 * square1.mass * v1x_old) / total_mass * self.collision_elasticity
        new_vy2 = (v2y_old * (square2.mass - square1.mass) + 2 * square1.mass * v1y_old) / total_mass * self.collision_elasticity
        
        # Ensure orthogonal movement (only up, down, left, or right)
        # For square 1
        if abs(new_vx1) > abs(new_vy1):
            # Horizontal movement dominant
            square1.vx = int(np.sign(new_vx1))
            square1.vy = 0
        else:
            # Vertical movement dominant
            square1.vx = 0
            square1.vy = int(np.sign(new_vy1))
            
        # For square 2
        if abs(new_vx2) > abs(new_vy2):
            # Horizontal movement dominant
            square2.vx = int(np.sign(new_vx2))
            square2.vy = 0
        else:
            # Vertical movement dominant
            square2.vx = 0
            square2.vy = int(np.sign(new_vy2))
            
        # Ensure squares aren't stationary
        if square1.vx == 0 and square1.vy == 0:
            direction = np.random.randint(0, 4)
            if direction == 0: square1.vx, square1.vy = -1, 0
            elif direction == 1: square1.vx, square1.vy = 1, 0
            elif direction == 2: square1.vx, square1.vy = 0, -1
            else: square1.vx, square1.vy = 0, 1
            
        if square2.vx == 0 and square2.vy == 0:
            direction = np.random.randint(0, 4)
            if direction == 0: square2.vx, square2.vy = -1, 0
            elif direction == 1: square2.vx, square2.vy = 1, 0
            elif direction == 2: square2.vx, square2.vy = 0, -1
            else: square2.vx, square2.vy = 0, 1
        
        # Separate the squares based on mass
        # The lighter square moves away more
        if square1.mass > square2.mass:
            # square2 is lighter, push it away
            self._push_square_away(square2, square1, grid_width, grid_height)
        elif square2.mass > square1.mass:
            # square1 is lighter, push it away
            self._push_square_away(square1, square2, grid_width, grid_height)
        else:
            # Equal mass, push both away
            self._push_squares_apart(square1, square2, grid_width, grid_height)
    
    def _push_square_away(self, light_square: Square, heavy_square: Square, 
                          grid_width: int, grid_height: int):
        """Push lighter square away from heavier square."""
        # Calculate direction from heavy to light
        dx = light_square.x - heavy_square.x
        dy = light_square.y - heavy_square.y
        
        # Normalize direction (orthogonal movement only)
        if dx == 0 and dy == 0:
            # Same position, push in random orthogonal direction
            direction = np.random.randint(0, 4)
            if direction == 0:    # Left
                dx, dy = -1, 0
            elif direction == 1:  # Right
                dx, dy = 1, 0
            elif direction == 2:  # Up
                dx, dy = 0, -1
            else:                # Down
                dx, dy = 0, 1
        else:
            # Make movement orthogonal by taking only the strongest component
            if abs(dx) > abs(dy):
                # Horizontal movement
                dx = np.sign(dx)
                dy = 0
            else:
                # Vertical movement
                dx = 0
                dy = np.sign(dy)
        
        # Move light square in that direction
        new_x = light_square.x + np.sign(dx)
        new_y = light_square.y + np.sign(dy)
        
        # Keep within bounds
        new_x = max(0, min(new_x, grid_width - 1))
        new_y = max(0, min(new_y, grid_height - 1))
        
        light_square.x = int(new_x)
        light_square.y = int(new_y)
    
    def _push_squares_apart(self, square1: Square, square2: Square, 
                            grid_width: int, grid_height: int):
        """Push two equal-mass squares apart."""
        # Push both squares in opposite directions (orthogonally)
        # Choose one of four directions: left/right or up/down
        if np.random.randint(0, 2) == 0:
            # Push horizontally
            dx, dy = 1, 0
        else:
            # Push vertically
            dx, dy = 0, 1
            
        if np.random.randint(0, 2) == 0:
            # Reverse direction
            dx, dy = -dx, -dy
            
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
        # Update positions
        for square in squares:
            square.update_position(grid_width, grid_height)
        
        # Detect and resolve collisions
        collisions = self.detect_collisions(squares, grid_width, grid_height)
        for square1, square2 in collisions:
            self.resolve_collision(square1, square2, grid_width, grid_height)
