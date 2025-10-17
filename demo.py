#!/usr/bin/env python3
"""
Quick start script for SquareVerse with preset configurations.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from squareverse.utils.managers.simulation_window import SimulationWindow


def main():
    """Launch simulation with default configuration."""
    print("=" * 60)
    print("  SquareVerse - Quick Start Demo")
    print("=" * 60)
    print("\nConfiguration:")
    print("  Window Size: 600px")
    print("  Grid Size: 20 cells")
    print("  Cell Size: 30px")
    print("\nLaunching simulation...")
    print("\nTips:")
    print("  - Click 'Spawn Square' to add squares")
    print("  - Try different masses (0.5, 1.0, 2.0, 5.0)")
    print("  - Click 'Start Movement' to begin physics")
    print("  - Watch heavier squares push lighter ones!")
    print()
    
    # Start with default configuration
    simulation = SimulationWindow(600, 20)
    simulation.run()
    
    print("\nDemo ended. Goodbye!")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nDemo interrupted. Exiting.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
