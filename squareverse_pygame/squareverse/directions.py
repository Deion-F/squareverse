"""Direction tables shared by the parent and child Squareverses (grid units, y grows downwards)."""

CARDINAL = ("up", "down", "left", "right")
DIAGONAL = ("d_left_up", "d_left_down", "d_right_up", "d_right_down")

DELTA = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
    "d_left_up": (-1, -1),
    "d_left_down": (-1, 1),
    "d_right_up": (1, -1),
    "d_right_down": (1, 1),
}

# Original god_script.py mapped d_right_down -> d_left_down (bug B6); fixed here.
INVERSE = {
    "up": "down",
    "down": "up",
    "left": "right",
    "right": "left",
    "d_left_up": "d_right_down",
    "d_right_down": "d_left_up",
    "d_left_down": "d_right_up",
    "d_right_up": "d_left_down",
}
