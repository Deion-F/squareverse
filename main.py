#!/usr/bin/env python3
"""
SquareVerse - 2D Grid-Based Physics Simulation

A real-time physics simulation where squares with different masses
interact on a 2D grid. Heavier squares push lighter ones in collisions.
"""

import sys
import os

# Add package to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from squareverse.utils.managers.setup_window import SetupWindow
from squareverse.utils.managers.simulation_window import SimulationWindow


def main():
    """Main entry point for the simulation."""
    print("=" * 60)
    print("  SquareVerse - 2D Grid-Based Physics Simulation")
    print("=" * 60)
    print("\nStarting setup window...")
    
    # Show setup window
    setup = SetupWindow()
    result = setup.show()
    
    if result is None:
        print("\nSetup cancelled. Exiting.")
        return
    
    window_size, grid_size = result
    print(f"\nConfiguration:")
    print(f"  Window Size: {window_size}px")
    print(f"  Grid Size: {grid_size} cells")
    print(f"  Cell Size: {window_size // grid_size}px")
    print(f"  Total Grid Cells: {grid_size * grid_size}")
    # Loop for returning to setup if needed
    while True:
        print("\nLaunching simulation...")
        
        # Start simulation
        simulation = SimulationWindow(window_size, grid_size)
        should_return_to_setup = simulation.run()
        
        if should_return_to_setup:
            print("\nReturning to setup...")
            # Show setup window again
            setup = SetupWindow()
            result = setup.show()
            
            if result is None:
                print("\nSetup cancelled. Exiting.")
                break
            
            # Update configuration
            window_size, grid_size = result
            print(f"\nNew Configuration:")
            print(f"  Window Size: {window_size}px")
            print(f"  Grid Size: {grid_size} cells")
            print(f"  Cell Size: {window_size // grid_size}px")
            print(f"  Total Grid Cells: {grid_size * grid_size}")
        else:
            # Normal exit
            print("\nSimulation ended. Goodbye!")
            break


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSimulation interrupted by user. Exiting.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
