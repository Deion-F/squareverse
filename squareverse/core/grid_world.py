"""Grid world manager for spatial organization."""

import numpy as np
from typing import List, Optional, Tuple, Set
from .square import Square


class GridWorld:
    """Manages the 2D grid world and square positions."""
    
    def __init__(self, grid_width: int, grid_height: int):
        """
        Initialize the grid world.
        
        Args:
            grid_width: Number of columns in the grid
            grid_height: Number of rows in the grid
        """
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.squares: List[Square] = []
        
        # Track occupied positions for efficient collision detection
        self.occupied_positions: Set[Tuple[int, int]] = set()
    
    def add_square(self, x: int, y: int, mass: float) -> Optional[Square]:
        """
        Add a square to the world.
        
        Args:
            x: Grid x-coordinate
            y: Grid y-coordinate
            mass: Mass of the square
            
        Returns:
            The created square, or None if position is invalid
        """
        if not self.is_valid_position(x, y):
            return None
        
        square = Square(x, y, mass)
        self.squares.append(square)
        self.occupied_positions.add((x, y))
        return square
    
    def add_square_random(self, mass: float) -> Optional[Square]:
        """
        Add a square at a random unoccupied position.
        
        Args:
            mass: Mass of the square
            
        Returns:
            The created square, or None if no space available
        """
        available_positions = self.get_available_positions()
        if not available_positions:
            return None
        
        # Choose random position
        idx = np.random.randint(0, len(available_positions))
        x, y = available_positions[idx]
        
        return self.add_square(x, y, mass)
    
    def remove_square(self, square_id: int) -> bool:
        """
        Remove a square by ID.
        
        Args:
            square_id: ID of the square to remove
            
        Returns:
            True if square was removed, False if not found
        """
        for i, square in enumerate(self.squares):
            if square.id == square_id:
                self.squares.pop(i)
                self._rebuild_occupied_positions()
                return True
        return False
    
    def remove_all_squares(self):
        """Remove all squares from the world."""
        self.squares.clear()
        self.occupied_positions.clear()
        Square.reset_id_counter()
    
    def get_square_at(self, x: int, y: int) -> Optional[Square]:
        """
        Get square at specific position.
        
        Args:
            x: Grid x-coordinate
            y: Grid y-coordinate
            
        Returns:
            Square at position, or None if empty
        """
        for square in self.squares:
            if square.x == x and square.y == y:
                return square
        return None
    
    def get_available_positions(self) -> List[Tuple[int, int]]:
        """Get list of all unoccupied grid positions."""
        all_positions = set((x, y) for x in range(self.grid_width) 
                           for y in range(self.grid_height))
        occupied = set((s.x, s.y) for s in self.squares)
        available = list(all_positions - occupied)
        return available
    
    def is_valid_position(self, x: int, y: int) -> bool:
        """Check if position is within grid bounds."""
        return 0 <= x < self.grid_width and 0 <= y < self.grid_height
    
    def get_square_count(self) -> int:
        """Get number of squares in the world."""
        return len(self.squares)
    
    def get_max_squares(self) -> int:
        """Get maximum number of squares that can fit in the grid."""
        return self.grid_width * self.grid_height
    
    def _rebuild_occupied_positions(self):
        """Rebuild the occupied positions set."""
        self.occupied_positions = set((s.x, s.y) for s in self.squares)
    
    def update_occupied_positions(self):
        """Update occupied positions after squares have moved."""
        self._rebuild_occupied_positions()
    
    def __repr__(self):
        return f"GridWorld({self.grid_width}x{self.grid_height}, {len(self.squares)} squares)"
