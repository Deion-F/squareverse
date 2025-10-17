"""SquareVerse - 2D Grid-Based Physics Simulation."""

__version__ = '1.0.0'
__author__ = 'SquareVerse Team'
__description__ = 'A grid-based physics simulation with mass-based collision dynamics'

from .core import Square, PhysicsEngine, GridWorld
from .utils import SetupWindow, SimulationWindow

__all__ = [
    'Square',
    'PhysicsEngine', 
    'GridWorld',
    'SetupWindow',
    'SimulationWindow'
]
