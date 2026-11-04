"""pygame event loop and controls (modelled on sand.py's main())."""

import math
import time

import pygame

from . import config
from .menu import draw_menu
from .presets import PRESETS
from .render import Renderer, mass_label, pour_label
from .ui import UI
from .usage import Usage
from .world import VIEW_MODES, super_core, super_mass_for_core

PRESET_KEYS = {pygame.K_F1: "rain", pygame.K_F2: "disk", pygame.K_F3: "cloud", pygame.K_F4: "binary",
               pygame.K_F5: "systems"}
ARROWS = {pygame.K_DOWN: 0, pygame.K_LEFT: 2, pygame.K_UP: 4, pygame.K_RIGHT: 6}
POUR_KEYS = {pygame.K_1 + k: m for k, m in enumerate(config.POUR_MASSES)}
POUR_KEYS[pygame.K_1 + len(config.POUR_MASSES)] = tuple(config.RANDOM_MASS)   # random mass in a range
HEAVY_POUR_KEYS = {pygame.K_1 + k: m for k, m in enumerate(config.HEAVY_POUR_MASSES)}   # with shift
HEAVY_POUR_KEYS[pygame.K_1 + len(config.POUR_MASSES)] = tuple(config.RANDOM_HEAVY_MASS)
HOLD_TOOLS = ("pour", "ghosts", "erase")         # mouse tools that act while the button is held; the rest once a click


class App:
    def __init__(self, world, fullscreen=False):
        self.world = world
        self.fullscreen = fullscreen
        self.windowed_size = (world.vpw, world.vph)
        self.screen = self.renderer = None
        self.paused = False
        self.show_help = config.HELP_ON
        self.inspector = config.INSPECTOR_ON
        self.view = VIEW_MODES.index(config.VIEW)
        self.ticks_per_frame = config.TICKS_PER_FRAME
        self.pour_mass = tuple(config.RANDOM_MASS) if config.POUR_MASS == "random" else config.POUR_MASS
        self.brush_px = config.BRUSH_PX         # pour, erase, ghosts, a star, a spawner (radius, px at zoom 1)
        self.super_mass = config.SUPER_PLACE_MASS       # a placed super well; its core follows
        self.repulsor_mass = config.REPULSOR_PLACE_MASS   # a placed repulsor; its size follows
        self._star_px_cache = (None, None)      # (what it was worked out for, largest_star_px())
        self.ghost_stars = config.GHOST_STARS   # placed stars arrive as ghost stars
        self.orbit_stars = config.ORBIT_STARS   # placed stars set off in orbit round the nearest super well
        self.render_ms = 0.0
        self.dragging = None        # the body being dragged
        self.tool = "pour"          # what a left click on the universe does (see menu.TOOLS)
        self.selected = None        # the body picked with the select tool
        self.pressing = False       # the left button went down on the universe (not the menu) and is still down
        self.panning = False        # the view is being dragged (middle button, or alt + left)
        self.ui = None
        self.usage = None

    @property
    def cam(self):
        return self.renderer.cam

    def mouse_world(self, pos=None):
        """The universe px (at zoom 1, as the World takes) under the mouse, or under a window px."""
        return self.cam.to_world(*(pos or pygame.mouse.get_pos()))

    def run(self):
        pygame.init()
        world = self.world
        pygame.display.set_caption("Squareverse")
        self.set_display_mode()
        self.usage = Usage().start()
        clock = pygame.time.Clock()

        running = True
        while running:
            new_size = None
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.VIDEORESIZE:
                    new_size = (e.w, e.h)   # applied once below, after a burst of resize events (sand.py)
                elif e.type == pygame.KEYDOWN:
                    if not self.ui.handle_key(e):   # (a number being typed in the menu takes every key)
                        running = self.on_key(e)
                elif self.ui.handle(e):     # the menu's: it never reaches the universe
                    continue
                elif e.type == pygame.MOUSEWHEEL:
                    if pygame.key.get_mods() & pygame.KMOD_CTRL:
                        self.cam.zoom_at(config.ZOOM_STEP ** e.y, *pygame.mouse.get_pos())
                    else:
                        self.scroll_size(e.y)
                elif e.type == pygame.MOUSEBUTTONDOWN and (e.button == 2 or e.button == 1
                                                           and pygame.key.get_mods() & pygame.KMOD_ALT):
                    self.panning = True
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    self.pressing = True
                    body = None
                    if pygame.key.get_mods() & pygame.KMOD_SHIFT:   # shift+click drags a body, else pours ghosts
                        body = world.body_at(*self.mouse_world(e.pos))
                        if body is None and self.tool == "star":     # ...or with the Star tool places a ghost star
                            self.place("ghost star", *self.mouse_world(e.pos))
                            self.pressing = False
                    elif self.tool not in HOLD_TOOLS:
                        body = self.click_tool(*self.mouse_world(e.pos))
                    self.dragging = world.held = body
                elif e.type == pygame.MOUSEBUTTONUP and e.button in (1, 2):
                    if self.panning:
                        self.panning = False
                        continue
                    self.pressing = False
                    self.dragging = world.held = None
                elif e.type == pygame.MOUSEMOTION and self.panning:
                    self.cam.pan(*e.rel)
                elif e.type == pygame.MOUSEMOTION and self.dragging is not None:
                    world.move_body(self.dragging, *self.mouse_world(e.pos))
            if new_size and not self.fullscreen and new_size != (world.vpw, world.vph):
                self.windowed_size = new_size
                self.screen = self.renderer.screen = self.ui.screen = pygame.display.get_surface()
                world.resize(*self.screen.get_size())
            screen, renderer = self.screen, self.renderer
            bodies = world.stars + world.wells + world.spawners
            if self.dragging is not None and self.dragging not in bodies:   # gone (swallowed, merged, exploded)
                self.dragging = world.held = None
            if self.selected is not None and self.selected not in bodies:
                self.selected = None

            self.cam.update(world, self.screen.get_size())
            buttons = pygame.mouse.get_pressed()
            mx, my = pygame.mouse.get_pos()          # window px; (wx, wy) the universe px under them
            wx, wy = self.mouse_world((mx, my))
            on_menu = self.ui.captures((mx, my))
            shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
            if buttons[0] and self.pressing and self.dragging is None and not on_menu:
                if shift or self.tool == "ghosts":
                    world.pour_ghosts(wx, wy, self.brush_px, self.pour_mass)
                elif self.tool == "pour":
                    world.brush(wx, wy, self.brush_px, self.pour_mass)
                elif self.tool == "erase":
                    world.brush(wx, wy, self.brush_px, 0)
            elif buttons[2] and not on_menu:
                world.brush(wx, wy, self.brush_px, 0)

            if not self.paused:
                for _ in range(self.ticks_per_frame):
                    world.step()

            t = time.perf_counter()
            renderer.draw_world(world, self.view)
            self.render_ms = (time.perf_counter() - t) * 1000
            if self.tool == "star":                     # where the star it would place could orbit
                renderer.draw_orbit_bands(world, *world.brush_star(self.brush_px, self.pour_mass))
            elif self.tool == "auto":                   # where it would put one
                renderer.draw_auto_star(world, wx / world.cell, wy / world.cell)
            renderer.draw_wells(world)
            if self.selected is not None:
                renderer.draw_selection(world, self.selected)
            if not on_menu and not self.panning:
                if self.tool == "super":
                    renderer.draw_super_preview(world, (mx, my), self.placed_super_mass())
                collapse = None                         # would what it places collapse into a super well at once?
                if world.collapse_on and self.tool in ("star", "pour") and not (shift and self.tool == "pour"):
                    collapse = world.placement_collapse(wx, wy, self.brush_px, self.pour_mass, self.tool == "star")
                renderer.draw_brush(self.tool, (mx, my), max(1, round(self.tool_radius_px() * self.cam.zoom)), collapse,
                                    *self.cursor_note())
            sw = screen.get_width()
            renderer.draw_compass(world.gdir, (sw - 34, 34))
            renderer.draw_usage(world, self.usage, None if self.ui.open else sw - 64)
            if self.inspector and not on_menu:
                body = world.body_at(wx, wy)
                info = world.particle_at(wx, wy)
                if body is not None:
                    renderer.draw_body_inspector(world, body, (mx, my))
                elif info:
                    renderer.draw_inspector(info, (mx, my))
            renderer.draw_status(world, self, clock.get_fps())
            if self.show_help:
                renderer.draw_help()
            draw_menu(self.ui, self, clock.get_fps())
            pygame.display.flip()
            clock.tick(config.FPS)
        self.usage.stop()
        pygame.quit()

    def zoom(self, factor):
        """Zoom by factor at the mouse (or the window's centre when it is over the menu or outside)."""
        pos = pygame.mouse.get_pos()
        if self.ui.captures(pos) or not pygame.mouse.get_focused():
            pos = (self.screen.get_width() / 2, self.screen.get_height() / 2)
        self.cam.zoom_at(factor, *pos)

    def place(self, what, mx, my):
        """Put a body at a pixel: a star of the brush's size (a ghost star if what says so, or ghost_stars is on;
        in orbit round the super well pulling hardest there if orbit_stars is on), a repulsor of repulsor_mass, a
        super well of super_mass (placed_super_mass), or a spawner of the brush's size (locked or not)."""
        w = self.world
        if what == "auto":
            return w.add_auto_star(mx, my)
        if what in ("star", "ghost star"):
            return w.add_star(mx, my, self.brush_px, self.pour_mass, ghost=what == "ghost star" or self.ghost_stars,
                              orbit=self.orbit_stars)
        if what == "repulsor":
            return w.add_well(mx, my, self.repulsor_mass, w.well_radius(self.repulsor_mass), -1)
        if what == "super":
            return w.add_super_well(mx, my, self.placed_super_mass())
        return w.add_spawner(mx, my, self.brush_px, self.pour_mass, locked=what == "locked")

    def tool_radius_px(self):
        """How big what the mouse tool places will be (px at zoom 1): a super well's core, a repulsor's body, or
        anything else (a star included) the brush."""
        if self.tool == "super":
            return self.super_core_px()
        if self.tool == "repulsor":
            return self.repulsor_px()
        return self.brush_px

    def scroll_size(self, steps):
        """The mouse wheel: the size of what the tool places, 4 px a step - or with the Super well tool its mass,
        SUPER_PLACE_STEP a step onto whole steps (its core follows; below the first step lies the least it can
        weigh)."""
        if self.tool == "super":
            step = config.SUPER_PLACE_STEP
            k = self.super_mass / step
            k = math.floor(k + 1e-9) + steps if steps > 0 else math.ceil(k - 1e-9) + steps
            self.super_mass = self.clamp_super(k * step)
        elif self.tool == "repulsor":
            self.set_repulsor_px(self.repulsor_px() + steps * 4)
        else:
            self.brush_px = min(max(self.brush_px + steps * 4, config.PLACE_SIZE_PX[0]), config.PLACE_SIZE_PX[1])

    # --- what the placing tools place: each one's mass and size, linked ---------------------------------

    def super_mass_range(self):
        """The lightest super well that can be placed (what collapse makes) and the heaviest."""
        return self.world.collapse_threshold(), float(config.SUPER_EXPLODE_RANGE[1])

    def clamp_super(self, mass):
        lo, hi = self.super_mass_range()
        return min(max(mass, lo), hi)

    def placed_super_mass(self):
        """What a placed super well weighs: super_mass, kept in super_mass_range (the least moves with gravity)."""
        return self.clamp_super(self.super_mass)

    def super_core_px(self):
        return super_core(self.placed_super_mass()) * self.world.cell

    def set_super_core_px(self, px):
        """Size the super well by its core (px): its mass becomes what that core takes (to 3 figures)."""
        m = super_mass_for_core(px / self.world.cell)
        self.super_mass = self.clamp_super(float(f"{m:.3g}") if m > 0 else 0.0)

    def repulsor_px(self):
        return self.world.well_radius(self.repulsor_mass) * self.world.cell

    def repulsor_mass_range(self):
        """The repulsor masses REPULSOR_SIZE_PX allows at the current cell size."""
        return tuple(math.pi * max(1.0, px / self.world.cell) ** 2 * config.WELL_DENSITY
                     for px in config.REPULSOR_SIZE_PX)

    def set_repulsor_px(self, px):
        """Size the repulsor (px): its mass becomes what that size weighs (to 3 figures)."""
        lo, hi = config.REPULSOR_SIZE_PX
        r = max(1.0, min(max(px, lo), hi) / self.world.cell)
        self.repulsor_mass = float(f"{math.pi * r * r * config.WELL_DENSITY:.3g}")

    def star_mass(self, px=None):
        """What the star the Star tool places weighs, with the brush (or px) and the particle mass."""
        return self.world.brush_star(self.brush_px if px is None else px, self.pour_mass)[1]

    def set_star_mass(self, mass):
        """Size the brush for a star as near this mass as the particle mass allows (its mass grows with its area)."""
        lo, hi = config.PLACE_SIZE_PX
        while hi - lo > 1:                              # the largest brush whose star is no heavier
            mid = (lo + hi) // 2
            lo, hi = (mid, hi) if self.star_mass(mid) <= mass else (lo, mid)
        self.brush_px = min((lo, hi), key=lambda px: abs(self.star_mass(px) - mass))

    def largest_star_px(self):
        """The largest brush (px) whose star holds together at the particle mass - a bigger one collapses into a
        super well at once (World.star_collapse_check); the largest brush there is when every star holds (or
        collapse is off), None when none does."""
        w = self.world
        key = (self.pour_mass, w.cell, w.star_collapse_limit(), w.collapse_on)
        if self._star_px_cache[0] == key:
            return self._star_px_cache[1]
        lo, hi = config.PLACE_SIZE_PX

        def holds(px):
            most, limit = w.star_collapse_check(px, self.pour_mass)
            return most < limit
        if not w.collapse_on or holds(hi):
            px = hi
        elif not holds(lo):
            px = None
        else:
            while hi - lo > 1:
                mid = (lo + hi) // 2
                lo, hi = (mid, hi) if holds(mid) else (lo, mid)
            px = lo
        self._star_px_cache = (key, px)
        return px

    def cursor_note(self):
        """What a click with the mouse tool places, for the label under the cursor, and a warning about it ((text,
        colour), or None)."""
        w, tool = self.world, self.tool
        if tool == "super":
            m = self.placed_super_mass()
            warn = (f"over the supernova mass ({mass_label(w.explode_mass)}): it will explode",
                    (235, 190, 90)) if m >= w.explode_mass else None
            return f"super well {mass_label(m)}   core {super_core(m):.1f} cells", warn
        if tool == "repulsor":
            return (f"repulsor {mass_label(self.repulsor_mass)}   radius {self.repulsor_px() / w.cell:.1f} cells",
                    None)
        if tool == "star":
            return (f"{'ghost ' if self.ghost_stars else ''}star {mass_label(self.star_mass())}   radius "
                    f"{max(1.0, self.brush_px / w.cell):.1f} cells   particles {pour_label(self.pour_mass)}", None)
        if tool in ("spawner", "locked"):
            r = max(1.0, self.brush_px / w.cell)
            rate = math.pi * r * r * config.SPAWNER_RATE * config.FPS
            return (f"{'locked ' if tool == 'locked' else ''}spawner {rate:,.0f}/s of mass "
                    f"{pour_label(self.pour_mass)}", None)
        return None, None

    def click_tool(self, mx, my):
        """A left click on the universe with a one-click tool. Returns the body to drag, if any."""
        w = self.world
        if self.tool == "select":
            self.selected = w.body_at(mx, my)
            return self.selected
        if self.tool == "delete":
            body = w.body_at(mx, my)
            if body is not None:
                w.remove_body(body)
            return None
        self.place(self.tool, mx, my)
        return None

    def set_display_mode(self):
        """Open the window (resizable) or go fullscreen at the desktop resolution; the world follows its size."""
        if self.fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        if self.renderer is None:
            self.renderer = Renderer(self.screen)
            self.ui = UI(self.screen)
        self.renderer.screen = self.ui.screen = self.screen
        if self.screen.get_size() != (self.world.vpw, self.world.vph):
            self.world.resize(*self.screen.get_size())
        self.renderer.cam.update(self.world, self.screen.get_size())

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.set_display_mode()

    def on_key(self, e):
        w = self.world
        k = e.key
        shift = e.mod & pygame.KMOD_SHIFT
        mx, my = self.mouse_world()                  # universe px under the mouse
        if k == pygame.K_ESCAPE:
            if self.show_help:
                self.show_help = False
            elif self.ui.open:
                self.ui.open = False
            elif self.fullscreen:
                self.toggle_fullscreen()
            else:
                return False
            return True
        if k == pygame.K_F11:
            self.toggle_fullscreen()
        elif k == pygame.K_TAB:
            self.ui.open = not self.ui.open
        elif k in ARROWS:
            w.set_gravity(ARROWS[k])
        elif k in (pygame.K_q, pygame.K_e):
            w.set_gravity(((w.gdir or 0) + (1 if k == pygame.K_e else -1)) % 8)
        elif k in (pygame.K_0, pygame.K_KP0):
            w.set_gravity(None)
        elif shift and k in HEAVY_POUR_KEYS:
            self.pour_mass = HEAVY_POUR_KEYS[k]
        elif k in POUR_KEYS:
            self.pour_mass = POUR_KEYS[k]
        elif k == pygame.K_g:
            self.place("repulsor" if shift else "star", mx, my)
        elif k == pygame.K_b:
            if shift:
                w.collapse_on = not w.collapse_on
            else:
                self.place("super", mx, my)
        elif k == pygame.K_t:
            self.orbit_stars = not self.orbit_stars
        elif k == pygame.K_x:
            nearest = w.nearest_body(mx, my)
            if nearest is not None:
                self.dragging = None
                w.remove_body(nearest)
        elif k in (pygame.K_LESS, pygame.K_GREATER) or (shift and k in (pygame.K_COMMA, pygame.K_PERIOD)):
            up = k in (pygame.K_GREATER, pygame.K_PERIOD)
            w.scale_gravity(config.G_SCALE_STEP if up else 1 / config.G_SCALE_STEP)
        elif k in (pygame.K_COMMA, pygame.K_PERIOD):
            nearest = w.nearest_well(mx, my, normal_only=True)
            if nearest is not None:
                w.scale_well(nearest, 1.25 if k == pygame.K_PERIOD else 0.8)
        elif k in (pygame.K_SEMICOLON, pygame.K_QUOTE):
            supers = [wl for wl in w.wells if wl.is_super]
            if supers:
                nearest = min(supers, key=lambda wl: math.hypot(wl.x * w.cell - mx, wl.y * w.cell - my))
                w.scale_spin(nearest, config.SUPER_SPIN_STEP if k == pygame.K_QUOTE else 1 / config.SUPER_SPIN_STEP)
        elif k == pygame.K_s:
            w.set_self_gravity(not w.sg_on)
        elif k == pygame.K_f:
            self.place("locked" if shift else "spawner", mx, my)
        elif k == pygame.K_w:
            w.set_wrap(not w.wrap)
        elif k == pygame.K_u:
            w.set_round(not w.round)
        elif k == pygame.K_z:
            self.zoom(config.ZOOM_STEP if shift else 1 / config.ZOOM_STEP)
        elif k == pygame.K_r:
            if shift:
                self.cam.fit()
            else:
                self.cam.reset()
        elif k == pygame.K_o:
            w.set_orbit({0: 1, 1: -1, -1: 0}[w.orbit])
        elif k in (pygame.K_k, pygame.K_l):
            w.scale_orbit(config.ORBIT_STEP if k == pygame.K_l else 1 / config.ORBIT_STEP)
        elif k == pygame.K_m:
            w.merge_on = not w.merge_on
        elif k == pygame.K_p:
            w.split_on = not w.split_on
        elif k == pygame.K_j:
            w.lean_on = not w.lean_on
        elif k == pygame.K_v:
            self.view = (self.view + 1) % len(VIEW_MODES)
        elif k == pygame.K_i:
            self.inspector = not self.inspector
        elif k in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
            sizes = config.CELL_SIZES
            idx = sizes.index(w.cell) + (1 if k == pygame.K_RIGHTBRACKET else -1)
            if 0 <= idx < len(sizes):
                w.set_cell(sizes[idx])
        elif k in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.ticks_per_frame = min(config.MAX_TICKS_PER_FRAME, self.ticks_per_frame + 1)
        elif k in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.ticks_per_frame = max(1, self.ticks_per_frame - 1)
        elif k == pygame.K_SPACE:
            self.paused = not self.paused
        elif k == pygame.K_n and self.paused:
            w.step()
        elif k in PRESET_KEYS:
            PRESETS[PRESET_KEYS[k]](w)
            self.selected = None
        elif k == pygame.K_c:
            w.clear()
        elif k == pygame.K_h:
            self.show_help = not self.show_help
        return True
