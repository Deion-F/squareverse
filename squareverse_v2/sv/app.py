"""pygame event loop and controls (modelled on sand.py's main())."""

import math
import time

import pygame

from . import config
from .presets import PRESETS
from .render import Renderer
from .world import VIEW_MODES

PRESET_KEYS = {pygame.K_F1: "rain", pygame.K_F2: "disk", pygame.K_F3: "cloud", pygame.K_F4: "binary"}
ARROWS = {pygame.K_DOWN: 0, pygame.K_LEFT: 2, pygame.K_UP: 4, pygame.K_RIGHT: 6}
POUR_KEYS = {pygame.K_1 + k: m for k, m in enumerate(config.POUR_MASSES)}
POUR_KEYS[pygame.K_1 + len(config.POUR_MASSES)] = tuple(config.RANDOM_MASS)   # random mass in a range


class App:
    def __init__(self, world, fullscreen=False):
        self.world = world
        self.fullscreen = fullscreen
        self.windowed_size = (world.pw, world.ph)
        self.screen = self.renderer = None
        self.paused = False
        self.show_help = config.HELP_ON
        self.inspector = config.INSPECTOR_ON
        self.view = VIEW_MODES.index(config.VIEW)
        self.ticks_per_frame = config.TICKS_PER_FRAME
        self.pour_mass = tuple(config.RANDOM_MASS) if config.POUR_MASS == "random" else config.POUR_MASS
        self.brush_px = config.BRUSH_PX
        self.render_ms = 0.0
        self.dragging = None        # the well or spawner being dragged

    def run(self):
        pygame.init()
        world = self.world
        pygame.display.set_caption("Squareverse")
        self.set_display_mode()
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
                    running = self.on_key(e)
                elif e.type == pygame.MOUSEWHEEL:
                    self.brush_px = max(2, min(160, self.brush_px + e.y * 4))
                elif (e.type == pygame.MOUSEBUTTONDOWN and e.button == 1
                      and pygame.key.get_mods() & pygame.KMOD_SHIFT):
                    self.dragging = world.held = world.body_at(*e.pos)
                elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                    self.dragging = world.held = None
                elif e.type == pygame.MOUSEMOTION and self.dragging is not None:
                    world.move_body(self.dragging, *e.pos)
            if new_size and not self.fullscreen and new_size != (world.pw, world.ph):
                self.windowed_size = new_size
                self.screen = self.renderer.screen = pygame.display.get_surface()
                world.resize(*self.screen.get_size())
            screen, renderer = self.screen, self.renderer
            if self.dragging is not None and self.dragging not in world.wells + world.spawners:   # swallowed
                self.dragging = world.held = None

            buttons = pygame.mouse.get_pressed()
            mx, my = pygame.mouse.get_pos()
            shift = pygame.key.get_mods() & pygame.KMOD_SHIFT
            if buttons[0] and self.dragging is None:   # shift+click on a well or spawner drags it instead
                if shift:
                    world.pour_ghosts(mx, my, self.brush_px, self.pour_mass)
                else:
                    world.brush(mx, my, self.brush_px, self.pour_mass)
            elif buttons[2]:
                world.brush(mx, my, self.brush_px, 0)

            if not self.paused:
                for _ in range(self.ticks_per_frame):
                    world.step()

            t = time.perf_counter()
            renderer.draw_world(world, self.view)
            self.render_ms = (time.perf_counter() - t) * 1000
            renderer.draw_wells(world)
            pygame.draw.circle(screen, (70, 76, 90), (mx, my), self.brush_px, 1)
            renderer.draw_compass(world.gdir, (world.pw - 34, 34))
            renderer.draw_hud(world, self, clock.get_fps())
            if self.inspector:
                body = world.body_at(mx, my)
                info = world.particle_at(mx, my)
                if body is not None:
                    renderer.draw_body_inspector(world, body, (mx, my))
                elif info:
                    renderer.draw_inspector(info, (mx, my))
            if self.show_help:
                renderer.draw_help()
            pygame.display.flip()
            clock.tick(config.FPS)
        pygame.quit()

    def set_display_mode(self):
        """Open the window (resizable) or go fullscreen at the desktop resolution; the world follows its size."""
        if self.fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.screen = pygame.display.set_mode(self.windowed_size, pygame.RESIZABLE)
        if self.renderer is None:
            self.renderer = Renderer(self.screen)
        self.renderer.screen = self.screen
        if self.screen.get_size() != (self.world.pw, self.world.ph):
            self.world.resize(*self.screen.get_size())

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.set_display_mode()

    def on_key(self, e):
        w = self.world
        k = e.key
        shift = e.mod & pygame.KMOD_SHIFT
        mx, my = pygame.mouse.get_pos()
        if k == pygame.K_ESCAPE:
            if self.show_help:
                self.show_help = False
            elif self.fullscreen:
                self.toggle_fullscreen()
            else:
                return False
            return True
        if k == pygame.K_F11:
            self.toggle_fullscreen()
        elif k in ARROWS:
            w.set_gravity(ARROWS[k])
        elif k in (pygame.K_q, pygame.K_e):
            w.set_gravity(((w.gdir or 0) + (1 if k == pygame.K_e else -1)) % 8)
        elif k in (pygame.K_0, pygame.K_KP0):
            w.set_gravity(None)
        elif k in POUR_KEYS:
            self.pour_mass = POUR_KEYS[k]
        elif k == pygame.K_g:
            w.add_sized_well(mx, my, self.brush_px, self.pour_mass, -1 if shift else 1)
        elif k == pygame.K_b:
            if shift:
                w.collapse_on = not w.collapse_on
            else:   # as heavy as a brush-sized well, and never lighter than what collapse would make
                w.add_super_well(mx, my, max(w.collapse_threshold(), w.brush_mass(self.brush_px, self.pour_mass)))
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
            w.add_spawner(mx, my, self.brush_px, self.pour_mass, locked=bool(shift))
        elif k == pygame.K_w:
            w.set_wrap(not w.wrap)
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
        elif k == pygame.K_c:
            w.clear()
        elif k == pygame.K_h:
            self.show_help = not self.show_help
        return True
