"""pygame event loop and controls (modelled on sand.py's main())."""

import time

import pygame

from . import config
from .presets import PRESETS
from .render import Renderer
from .world import VIEW_MODES

PRESET_KEYS = {pygame.K_F1: "rain", pygame.K_F2: "disk", pygame.K_F3: "cloud", pygame.K_F4: "binary"}
ARROWS = {pygame.K_DOWN: 0, pygame.K_LEFT: 2, pygame.K_UP: 4, pygame.K_RIGHT: 6}
POUR_KEYS = {pygame.K_1 + k: m for k, m in enumerate(config.POUR_MASSES)}


class App:
    def __init__(self, world):
        self.world = world
        self.paused = False
        self.show_help = False
        self.inspector = True
        self.view = 0
        self.ticks_per_frame = 1
        self.pour_mass = config.POUR_MASSES[0]
        self.brush_px = 24
        self.render_ms = 0.0
        self.dragging = None        # index of the well being dragged

    def run(self):
        pygame.init()
        world = self.world
        screen = pygame.display.set_mode((world.pw, world.ph))
        pygame.display.set_caption("Squareverse")
        renderer = Renderer(screen)
        clock = pygame.time.Clock()

        running = True
        while running:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN:
                    running = self.on_key(e)
                elif e.type == pygame.MOUSEWHEEL:
                    self.brush_px = max(2, min(160, self.brush_px + e.y * 4))
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 2:
                    self.dragging = world.nearest_well(*e.pos, max_px=40)
                elif e.type == pygame.MOUSEBUTTONUP and e.button == 2:
                    self.dragging = None
                elif e.type == pygame.MOUSEMOTION and self.dragging is not None:
                    world.move_well(self.dragging, *e.pos)

            buttons = pygame.mouse.get_pressed()
            mx, my = pygame.mouse.get_pos()
            if buttons[0]:
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
                info = world.particle_at(mx, my)
                if info:
                    renderer.draw_inspector(info, (mx, my))
            if self.show_help:
                renderer.draw_help()
            pygame.display.flip()
            clock.tick(config.FPS)
        pygame.quit()

    def on_key(self, e):
        w = self.world
        k = e.key
        shift = e.mod & pygame.KMOD_SHIFT
        mx, my = pygame.mouse.get_pos()
        if k == pygame.K_ESCAPE:
            if self.show_help:
                self.show_help = False
                return True
            return False
        if k in ARROWS:
            w.set_gravity(ARROWS[k])
        elif k in (pygame.K_q, pygame.K_e):
            w.set_gravity(((w.gdir or 0) + (1 if k == pygame.K_e else -1)) % 8)
        elif k in (pygame.K_0, pygame.K_KP0):
            w.set_gravity(None)
        elif k in POUR_KEYS:
            self.pour_mass = POUR_KEYS[k]
        elif k == pygame.K_g:
            w.add_well(mx, my, -config.WELL_STRENGTH if shift else config.WELL_STRENGTH)
        elif k == pygame.K_x:
            nearest = w.nearest_well(mx, my)
            if nearest is not None:
                w.remove_well(nearest)
        elif k in (pygame.K_COMMA, pygame.K_PERIOD):
            nearest = w.nearest_well(mx, my)
            if nearest is not None:
                w.scale_well(nearest, 1.25 if k == pygame.K_PERIOD else 0.8)
        elif k == pygame.K_s:
            w.set_self_gravity(not w.sg_on)
        elif k in (pygame.K_k, pygame.K_l):
            w.sg_g *= 1.25 if k == pygame.K_l else 0.8
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
