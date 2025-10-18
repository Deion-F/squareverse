# SquareVerse - 2D Grid-Based Physics Simulation

A real-time physics simulation where squares with different masses interact on a 2D grid. Watch emergent phenomena as heavier squares push lighter ones out of the way in dynamic collisions!

## Features

### Core Physics
- **Grid-based movement**: Squares move one cell at a time across a 2D grid
- **Mass-based collisions**: Heavier squares push lighter ones during collisions
- **Realistic physics**: Conservation of momentum and energy in collisions
- **Wall bouncing**: Squares bounce off grid boundaries

### User Interface
1. **Initial Setup Window**
   - Select window size (100px to 1000px in 100px increments)
   - Select grid size (must divide evenly into window size)
   - Modern, stylish UI with real-time validation

2. **Main Simulation Window**
   - Clear grid visualization
   - Color-coded squares based on mass (blue = light, red = heavy)
   - Real-time statistics (FPS, square count)
   - Intuitive control panel

3. **Control Panel**
   - 🟦 **Spawn Square**: Add squares with custom mass values
   - ▶ **Start/Stop Movement**: Toggle physics simulation
   - ❌ **Delete Square**: Remove individual squares by ID
   - 🗑️ **Delete All**: Clear all squares from the grid
   - ⏹️ **End Simulation**: Close and cleanup

### Technical Features
- **Multi-threading**: Physics calculations run in separate thread for smooth performance
- **Optimized rendering**: 60 FPS display with efficient canvas updates
- **Memory management**: Proper cleanup on deletion and exit
- **Efficient data structures**: Fast collision detection and position queries

### Visual Features
- **Mass-based coloring**: Light blue (low mass) to dark red (high mass)
- **Mass labels**: Each square displays its mass value when space permits
- **Stalled indicator**: Squares show an "X" when unable to move due to blockage
- **Grid visualization**: Clear cell boundaries for easy tracking
- **Smooth animation**: Real-time movement at 20 physics updates per second
- **Movement tracking**: Select and track squares to visualize their recent paths

## Installation

### Prerequisites
- Python 3.8 or higher
- tkinter (usually included with Python)

### Install Required Packages

```bash
# Install dependencies
pip install -r requirements.txt
```

Or install packages individually:

```bash
pip install numpy
```

**Note**: tkinter comes pre-installed with most Python distributions. If it's missing:
- **Ubuntu/Debian**: `sudo apt-get install python3-tk`
- **Fedora**: `sudo dnf install python3-tkinter`
- **macOS**: Included with Python from python.org
- **Windows**: Included with Python installer

## Usage

### Running the Simulation

```bash
# From the project root directory
python main.py
```

Or:

```bash
# Make it executable (Linux/macOS)
chmod +x main.py
./main.py
```

### Step-by-Step Guide

1. **Launch the application**
   ```bash
   python main.py
   ```

2. **Configure your simulation** (Setup Window)
   - Adjust window size slider (100px to 1000px)
   - Adjust grid size slider (5 to 60 cells)
   - Ensure grid size divides evenly into window size
   - Click "Start Simulation"

3. **Spawn squares** (Main Window)
   - Click "🟦 Spawn Square"
   - Enter mass value (0.1 to 10.0)
   - Square appears at random empty position

4. **Start physics**
   - Click "▶ Start Movement"
   - Watch squares move and collide
   - Observe heavier squares pushing lighter ones

5. **Interact with simulation**
   - Pause/resume with "⏸ Stop Movement"
   - Adjust simulation speed with the FPS slider (1-120 FPS)
   - Delete specific squares by ID
   - Clear all squares with "Delete All"

6. **Track square movement**
   - Click "🔍 Track Movement" to pause simulation and enter tracking mode
   - Click on specific squares to track their movement
   - Selected squares get highlighted with a yellow border
   - Click "🔍 Track Movement" again to resume simulation
   - Observe colored paths showing recent movement history (up to 10 positions)
   - Toggle the button again to clear tracked paths

7. **Return to setup**
   - Click "⚙️ Return to Setup" to go back to the setup window
   - Adjust window size and grid size
   - Launch simulation with new settings
   - No need to restart the application

8. **End simulation**
   - Click "⏹️ End Simulation"
   - Confirm exit if simulation is running

## Configuration Options

### Window Size
- **Range**: 100px to 1000px
- **Increment**: 100px
- **Recommended**: 600px for most systems

### Grid Size
- **Range**: 5 to 60 cells per side
- **Constraint**: Must divide evenly into window size
- **Recommended**: 20 cells for good balance

### Valid Combinations Examples
| Window Size | Valid Grid Sizes |
|-------------|------------------|
| 600px       | 5, 10, 12, 15, 20, 24, 25, 30, 40, 50, 60 |
| 800px       | 5, 8, 10, 16, 20, 25, 32, 40, 50 |
| 1000px      | 5, 8, 10, 20, 25, 40, 50 |

### Square Mass
- **Range**: 0.1 to 10.0
- **Effect**: 
  - Higher mass = harder to push, pushes others more
  - Lower mass = easier to push, gets pushed more
  - Mass affects color (blue → red as mass increases)

## Physics Mechanics

### Collision Detection
- Grid-based spatial hashing for O(1) collision detection
- Detects when multiple squares occupy the same cell
- Prevents squares from "passing through" each other with movement planning

### Collision Resolution
1. **Movement Planning**: Heavy squares get priority for their desired positions
   - Heavier squares always push lighter squares out of the way
   - Lighter squares are pushed in the direction of the heavier square's movement
2. **Position Separation**: Lighter square is pushed away by heavier square
3. **Fallback Movement**: When blocked, squares attempt:
   - Original desired direction
   - Opposite direction
   - Other cardinal directions randomly
   - Mark as "stalled" with "X" only when all directions blocked

### Movement
- Squares move one grid cell per physics update
- Random initial velocities (-1, 0, or 1) in x and y directions
- Bounces off walls by reversing velocity
- No diagonal movement - only cardinal directions (up, down, left, right)

## Project Structure

```
squareverse/
├── main.py                          # Entry point
├── requirements.txt                 # Python dependencies
├── README.md                        # This file
└── squareverse/                     # Main package
    ├── __init__.py
    ├── core/                        # Core simulation components
    │   ├── __init__.py
    │   ├── square.py                # Square entity class
    │   ├── physics_engine.py        # Physics calculations
    │   └── grid_world.py            # Grid management
    └── utils/                       # UI components
        ├── __init__.py
        └── managers/
            ├── __init__.py
            ├── setup_window.py      # Initial setup UI
            └── simulation_window.py # Main simulation UI
```

## Performance Optimization

### Multi-threading
- Physics calculations run in separate thread
- Main thread handles UI rendering at 60 FPS
- Thread-safe operations ensure data consistency

### Efficient Rendering
- Only redraws squares, not the entire grid
- Canvas tags for selective updates
- Minimal overhead per frame

### Data Structures
- Position-based hashing for fast collision detection
- List-based square storage for iteration
- Set-based occupied position tracking

## Emergent Phenomena

Watch for these interesting behaviors:

1. **Mass Segregation**: Heavier squares tend to cluster together
2. **Pushing Chains**: One heavy square can push multiple light squares
3. **Collision Cascades**: Chain reactions from single collisions
4. **Density Patterns**: Natural formation of dense and sparse regions
5. **Momentum Transfer**: Energy propagation through the system
6. **Path Formation**: Using the tracking feature, observe how squares find paths through congestion
7. **Stalling Patterns**: Squares displaying "X" when blocked from all directions
8. **Direction Preference**: Observe how squares attempt alternative directions when blocked

## Tips for Best Experience

### For Smooth Performance
- Start with 600px window and 20 cell grid
- Keep square count under 100 for best FPS
- Close other applications if experiencing lag

### For Interesting Physics
- Create a mix of masses (0.5, 1.0, 2.0, 5.0)
- Spawn more than 50% of grid capacity
- Let simulation run for 30+ seconds to see patterns

### For Visual Appeal
- Use larger window (800px or 1000px)
- Smaller grid size (15-20 cells) for bigger squares
- Diverse mass range for color variety

## Troubleshooting

### "Grid size must divide evenly into window size"
- Adjust either value until division is clean
- See "Valid Combinations Examples" above

### Application won't start
- Verify Python 3.8+ is installed: `python --version`
- Install tkinter if missing (see Installation section)
- Check numpy installation: `pip list | grep numpy`

### Poor performance / Low FPS
- Reduce number of squares
- Use smaller grid size
- Close other applications
- Try smaller window size

### Squares not moving
- Click "▶ Start Movement" button
- Ensure at least one square is spawned
- Check that simulation isn't paused

## Technical Details

### Threading Model
- **Main Thread**: UI rendering and event handling
- **Physics Thread**: Physics calculations (20 Hz)
- **Communication**: Shared data structures with careful synchronization

### Physics Update Rate
- Adjustable from 1-120 updates per second via FPS slider
- Default: 20 updates per second (50ms per update)
- Balances accuracy with performance
- Independent of rendering FPS (60 FPS)

### Rendering Rate
- Target 60 FPS for smooth visualization
- Actual FPS displayed in statistics
- May vary based on system performance

## Contributing

Feel free to extend the simulation with:
- Different collision models
- Additional forces (gravity, friction)
- New visual effects
- Performance optimizations
- Alternative UI frameworks

## License

This project is open source and available for educational purposes.

## Acknowledgments

Built with:
- **Python**: Core language
- **tkinter**: GUI framework
- **numpy**: Numerical computations
- **threading**: Concurrent execution

---

**Enjoy exploring the emergent physics of SquareVerse!** 🟦🔴🟩
