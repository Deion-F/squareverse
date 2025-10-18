"""Square entity with mass and physics properties."""

import numpy as np
from typing import Tuple
import colorsys


class Square:
    """Represents a square entity in the grid world."""
    
    # Class variable to track unique IDs
    _id_counter = 0
    
    def __init__(self, x: int, y: int, mass: float = 1.0):
        """
        Initialize a square.
        
        Args:
            x: Grid x-coordinate
            y: Grid y-coordinate
            mass: Mass of the square (affects collision physics)
        """
        Square._id_counter += 1
        self.id = Square._id_counter
        
        self.x = x
        self.y = y
        self.mass = max(0.1, mass)  # Minimum mass to prevent division by zero
        
        # Velocity in grid cells per step - only up, down, left, right (no diagonals)
        # We'll pick a random direction: 0=right, 1=up, 2=left, 3=down
        direction = np.random.randint(0, 4)
        if direction == 0:   # Right
            self.vx, self.vy = 1, 0
        elif direction == 1: # Up
            self.vx, self.vy = 0, -1
        elif direction == 2: # Left
            self.vx, self.vy = -1, 0
        else:               # Down
            self.vx, self.vy = 0, 1
        
        # Color based on mass (heavier = darker/redder)
        self.color = self._calculate_color()
        # Whether the square was unable to move last update
        self.stalled = False
        
    def _calculate_color(self) -> str:
        """Calculate color based on mass (visual differentiation)."""
        # Map mass to color: light (low mass) to dark red (high mass)
        # Assuming mass range from 0.1 to 10.0
        normalized_mass = min(max(self.mass, 0.1), 10.0)
        
        # Use HSV color space: Hue from blue (240°) to red (0°)
        hue = 240 - (normalized_mass / 10.0) * 240  # 240° (blue) to 0° (red)
        saturation = 0.8
        value = 0.9 - (normalized_mass / 10.0) * 0.4  # Darker for heavier
        
        # Convert to RGB
        rgb = colorsys.hsv_to_rgb(hue / 360.0, saturation, value)
        return f'#{int(rgb[0]*255):02x}{int(rgb[1]*255):02x}{int(rgb[2]*255):02x}'
    
    def get_position(self) -> Tuple[int, int]:
        """Get current grid position."""
        return (self.x, self.y)
    
    def set_position(self, x: int, y: int):
        """Set grid position."""
        self.x = x
        self.y = y
    
    def get_velocity(self) -> Tuple[int, int]:
        """Get current velocity."""
        return (self.vx, self.vy)
    
    def set_velocity(self, vx: int, vy: int):
        """Set velocity."""
        self.vx = vx
        self.vy = vy
    
    def update_position(self, grid_width: int, grid_height: int):
        """
        Update position based on velocity.
        
        Args:
            grid_width: Width of the grid
            grid_height: Height of the grid
        """
        new_x = self.x + self.vx
        new_y = self.y + self.vy
        
        # Bounce off walls
        if new_x < 0 or new_x >= grid_width:
            self.vx = -self.vx
            new_x = max(0, min(new_x, grid_width - 1))
        
        if new_y < 0 or new_y >= grid_height:
            self.vy = -self.vy
            new_y = max(0, min(new_y, grid_height - 1))
        
        self.x = new_x
        self.y = new_y
    
    def __repr__(self):
        return f"Square(id={self.id}, pos=({self.x},{self.y}), mass={self.mass:.1f}, v=({self.vx},{self.vy}))"
    
    @classmethod
    def reset_id_counter(cls):
        """Reset the ID counter (useful for testing)."""
        cls._id_counter = 0
