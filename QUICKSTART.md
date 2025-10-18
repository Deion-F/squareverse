# SquareVerse - Quick Start Guide

Get up and running in 60 seconds! 🚀

## 1. Install Dependencies

```bash
# Install numpy
pip install numpy

# Or use the install script (Linux/macOS)
./install.sh
```

## 2. Run the Simulation

### Option A: Full Setup (Recommended)
```bash
python main.py
```
1. Choose window size with slider
2. Choose grid size with slider
3. Click "Start Simulation"

### Option B: Quick Demo
```bash
python demo.py
```
Starts immediately with preset configuration (600px window, 20x20 grid)

## 3. Use the Simulation

### Spawn Squares
1. Click "🟦 Spawn Square"
2. Enter mass (try 0.5, 1.0, 2.0, 5.0, or 10.0)
3. Square appears at random location
4. **Color Legend**:
   - 🔵 Blue = Light (low mass)
   - 🟡 Yellow/Orange = Medium 
   - 🔴 Red = Heavy (high mass)

### Start Physics
1. Spawn at least a few squares (5-10 recommended)
2. Click "▶ Start Movement"
3. Watch the magic happen! ✨
   - Heavier squares push lighter ones
   - Squares bounce off walls
   - Collisions cause momentum transfer

### Controls
- **⏸ Stop Movement**: Pause the simulation
- **🔍 Track Movement**: Select squares to track their paths
- **❌ Delete Square**: Remove a square by ID
- **🗑️ Delete All**: Clear all squares
- **⚙️ Return to Setup**: Go back to setup window to change configuration
- **⏹️ End Simulation**: Exit the program

## 4. Tips for Best Results

### For Interesting Physics
```
- Spawn 20-50 squares
- Use diverse masses: 0.5, 1.0, 2.0, 5.0, 10.0
- Let it run for 30+ seconds
- Watch for emergent patterns!
```

### For Smooth Performance
```
- Start with 600px window, 20x20 grid
- Keep squares under 100
- Close other applications
```

### Valid Grid Configurations
Make sure grid size divides evenly into window size:

| Window | Good Grid Sizes |
|--------|----------------|
| 600px  | 5, 10, 15, 20, 25, 30 |
| 800px  | 5, 10, 20, 25, 40 |
| 1000px | 5, 10, 20, 25, 50 |

## 5. What to Watch For

### Emergent Phenomena 🌟
- **Mass Segregation**: Heavy squares cluster together
- **Pushing Chains**: One collision triggers many
- **Density Patterns**: Areas become dense or sparse
- **Momentum Waves**: Energy flows through the system

### Physics in Action ⚛️
- Watch a heavy square (red) slam into a light one (blue)
- The light square gets pushed away in the direction of the heavy square!
- The heavy square continues its path without bouncing
- Squares show an "X" when they're unable to move in any direction
- Use "Track Movement" to see the path squares have taken
- Squares try alternative directions when blocked (opposite first, then random)

## 6. Troubleshooting

**"Grid size must divide evenly"**
- Adjust sliders until both numbers work together
- See table above for valid combinations

**Squares not moving**
- Click "▶ Start Movement" button
- Make sure you spawned at least one square

**Poor performance**
- Reduce number of squares
- Try smaller grid (15x15 instead of 30x30)
- Close other programs

## Example Session

```bash
# 1. Start the program
python main.py

# 2. In setup window:
#    - Set window size: 600px
#    - Set grid size: 20
#    - Click "Start Simulation"

# 3. In main window:
#    - Click "Spawn Square", enter mass: 0.5 (light blue)
#    - Click "Spawn Square", enter mass: 5.0 (dark red)
#    - Click "Spawn Square", enter mass: 1.0 (medium)
#    - Repeat until you have 10-15 squares
#    - Adjust FPS slider to desired speed (1-120)
#    - Click "Start Movement"
#    - Watch the simulation!

# 4. Try tracking:
#    - Click "Track Movement" to pause simulation
#    - Click on squares you want to track
#    - Click "Track Movement" again to resume with visible paths
#    - Watch colored lines showing recent movement history

# 5. Observe:
#    - Heavy squares push light ones
#    - Squares try to avoid getting stuck
#    - "X" appears on squares that can't move
#    - Light squares follow heavy squares' direction
#    - Patterns emerge over time
    
# 6. Try different configurations:
#    - Click "Return to Setup" to change window/grid size
#    - No need to restart the program!
```

## That's It!

You're ready to explore the physics of SquareVerse! 🎉

For more details, see the full [README.md](README.md)

---

**Have fun!** Watch as simple rules create complex behaviors! 🟦🔴🟩
