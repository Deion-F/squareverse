"""Tunable settings. Defaults mirror the original Tkinter/MongoDB version where one existed."""

# --- Parent Squareverse ------------------------------------------------------
DEFAULT_SIZE = 8              # menu value 1-10, universe is SIZE * 100 px (original default 8 -> 800 px)
DEFAULT_GRID_SPACING = 25     # px per cell (original default 25)
DIAGONAL_MOVES = False        # original HEAD allowed 8 directions; the agreed ladder uses the 4 cardinal ones
CRUSH_WHEN_TRAPPED = True     # original: a Square that fails every ladder attempt is destroyed

# --- Child Squareverse (mini universe inside every Square) ----------------------
CHILD_GRID = 24               # original: 300 px / 25 px spacing -> 12 x 12 cells
CHILD_COUNT_RANGE = (2, 192)  # children per Square (= its mass); original HEAD used random mass 0-255
SPAWN_CHILD_CYCLES = 5        # original a41bbab: 5 child cycles before an idle Square picks a direction
MOVE_CHILD_CYCLES = 1         # original a41bbab: 1 child cycle after every successful parent move

# --- Display -----------------------------------------------------------------
BACKGROUND_COLOR = (82, 69, 56)
GRID_COLOR = (0, 0, 0)
BLOCKED_OUTLINE_COLOR = (255, 255, 255)   # original sets the outline to "White" when a Square is blocked
DEFAULT_TICKS_PER_SECOND = 8
MAX_FPS = 120
SMOOTH_MOVEMENT = True        # interpolate Squares between ticks
