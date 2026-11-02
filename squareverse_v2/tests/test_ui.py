"""The menu's widget kit (sv/ui.py), driven headless with posted mouse events."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from sv.ui import UI


@pytest.fixture
def ui():
    pygame.init()
    ui = UI(pygame.display.set_mode((800, 600)))
    ui.open = True
    yield ui
    pygame.quit()


def frame(ui, value, events=()):
    """One frame: the events reach the kit, then the panel lays out a single slider. Returns its value."""
    for e in events:
        ui.handle(e)
    ui.begin()
    value = ui.slider("s", "Slider", value, 0.0, 10.0, step=1.0)
    ui.end()
    return value


def click(pos):
    return [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=pos)]


def test_click_released_in_the_same_frame_does_not_stick(ui):
    v = frame(ui, frame(ui, 5.0))                         # lays the panel out (it fits itself to its rows)
    up = pygame.Rect(ui.x + ui.w - 22 - 4 - 18, ui.panel.y + 12 + 1, 18, 18).center   # the slider's ▶ arrow
    v = frame(ui, v, click(up))                           # down and up arrive together, as on a slow frame
    assert v == 6.0 and ui.active is None                 # one step, and nothing left held
    for _ in range(30):
        v = frame(ui, v)
    assert v == 6.0                                       # no repeating afterwards
    track = (ui.x + 6 + 50, ui.panel.y + 12 + 30)
    frame(ui, v, click(track))
    assert ui.active is None                              # nor does the slider keep dragging


def test_super_well_arms_never_seem_to_turn_backwards(ui):
    from sv import config
    from sv.render import Renderer
    from sv.world import Well
    r = Renderer(ui.screen)
    wl = Well(0.0, 0.0, 1.0, is_super=True, spin=1.0)
    angles = [r._arm_angle(wl)]
    for turn in (0.1, 0.5, 2.0, 2.1, 6.0):                           # however far it turned since the last frame
        wl.phase += turn
        angles.append(r._arm_angle(wl))
    steps = [b - a for a, b in zip(angles, angles[1:])]
    assert steps[0] == pytest.approx(0.1, rel=0.01)                  # slow turns are drawn as they are
    assert all(0 < s < config.SUPER_SPIN_FRAME_MAX for s in steps)   # fast ones eased, still forwards...
    assert steps == sorted(steps)                                    # ...and faster still looks faster
