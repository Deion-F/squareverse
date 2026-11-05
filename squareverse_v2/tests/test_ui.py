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


def test_star_tool_shades_the_stable_orbit_band():
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    try:
        from sv import config
        from sv.render import Renderer
        from sv.world import World
        w = World(800, 600, 2, seed=1)
        w.set_reach(0)
        w.g_scale = 0.6
        wl = w.add_super_well(400, 300, 80000)
        r = Renderer(screen)
        r.cam.update(w, (800, 600))
        inner, outer = w.orbit_band(wl, *w.brush_star(20, 16))
        screen.fill((0, 0, 0))
        r.draw_orbit_bands(w, *w.brush_star(20, 16))
        x, y = r.cam.point(wl.x, wl.y)
        k = r.cam.k
        band = screen.get_at((round(x + (inner + outer) / 2 * k), round(y)))[:3]
        hole = screen.get_at((round(x + inner / 2 * k), round(y)))[:3]
        assert band[1] > band[0] and band[1] > 0 and hole == (0, 0, 0)   # greenish in the band, nothing inside
    finally:
        pygame.quit()


def test_auto_star_tool_draws_its_band_and_preview():
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    try:
        from sv.render import Renderer
        from sv.world import World
        w = World(800, 600, 2, seed=1)
        w.set_reach(120)
        w.g_scale = 0.6
        wl = w.add_super_well(400, 300, 80000)
        r = Renderer(screen)
        r.cam.update(w, (800, 600))
        screen.fill((0, 0, 0))
        r.draw_auto_star(w, wl.x + 50, wl.y)
        _, _, (inner, outer), _, _ = w.auto_star_plan(wl)
        x, y = r.cam.point(wl.x, wl.y)
        band = screen.get_at((round(x), round(y - (inner + outer) / 2 * r.cam.k)))[:3]
        assert band[1] > band[0]                     # the band is shaded green
    finally:
        pygame.quit()


def test_star_brush_turns_red_when_the_star_would_collapse():
    pygame.init()
    screen = pygame.display.set_mode((400, 300))
    try:
        from sv import config
        from sv.render import Renderer
        r = Renderer(screen)
        for collapse, over in (((50000.0, 266667.0), False), ((300000.0, 266667.0), True)):
            screen.fill((0, 0, 0))
            r.draw_brush("star", (200, 100), 20, collapse)
            edge = {tuple(screen.get_at((x, 100))[:3]) for x in range(217, 222)}   # (pygame draws it just inside)
            assert (tuple(config.ORBIT_BAND_NONE_COLOR) in edge) == over
            assert any(screen.get_at((x, 130))[:3] != (0, 0, 0) for x in range(100, 300)) == over   # the note
    finally:
        pygame.quit()


def test_number_field_takes_a_typed_mass_and_keeps_keys_from_shortcuts(ui):
    def frame(value, events=()):
        for e in events:
            if e.type == pygame.KEYDOWN:
                assert ui.handle_key(e)                   # no shortcut sees it while typing
            else:
                ui.handle(e)
        ui.begin()
        value = ui.number_field("m", "Mass", value, 1.0, 50e6)
        ui.end()
        return value

    v = frame(frame(1e6))                                 # lays the panel out
    box = (ui.x + ui.w - 22 - 60, ui.panel.y + 12 + 10)
    v = frame(v, click(box))
    assert ui.editing == ("m", "")
    keys = [pygame.event.Event(pygame.KEYDOWN, key=0, unicode=c) for c in "2.5m"]
    v = frame(v, keys + [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r")])
    assert v == 2.5e6 and ui.editing is None
    v = frame(v, click(box))
    v = frame(v, [pygame.event.Event(pygame.KEYDOWN, key=0, unicode="9"),
                  pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="")])
    assert v == 2.5e6                                     # Esc backs out
    assert not ui.handle_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b, unicode="b"))


def test_super_well_tool_links_mass_and_core():
    pygame.init()
    pygame.display.set_mode((800, 600))
    try:
        from sv.app import App
        from sv.world import World
        a = App(World(800, 600, 2, seed=1))
        a.tool = "super"
        a.super_mass = 3e6
        assert a.tool_radius_px() == pytest.approx(a.world.edge_for_mass(3e6) * 2)   # the cursor is its horizon
        a.scroll_size(1)
        assert a.super_mass == 4e6                                         # the wheel steps whole millions
        a.scroll_size(-5)
        assert a.super_mass == a.world.lightest_super_mass()              # ...down to the lightest there is
        a.set_super_core_px(10 * 2)
        assert a.world.edge_for_mass(a.super_mass) == pytest.approx(10, rel=0.01)   # a horizon sets its mass
        wl = a.place("super", 400, 300)
        assert wl.is_super and wl.mass == a.super_mass
        a.set_repulsor_px(80)
        rep = a.place("repulsor", 200, 300)
        assert rep.sign < 0 and rep.radius * 2 == pytest.approx(80, rel=0.01)
    finally:
        pygame.quit()


def test_placement_collapse_counts_what_is_already_there():
    from sv.world import World
    w = World(400, 300, 2, seed=1)
    most, limit = w.placement_collapse(200, 150, 30, 4096)
    assert most > limit                                    # a brush full of 4096s collapses
    assert w.placement_collapse(200, 150, 30, 16)[0] < limit
    star = w.placement_collapse(200, 150, 20, 64, star=True)
    assert star == pytest.approx(w.star_collapse_check(20, 64))            # on empty space, as the star check
    w.brush(200, 150, 30, 1024)                                            # heavy matter already there
    assert w.placement_collapse(200, 150, 20, 64, star=True)[0] > star[0]
