"""pygame event loop: fixed-rate simulation ticks, frame-rate rendering, keyboard/mouse controls."""

import time

import pygame

from . import config
from .render import Renderer

TICK_RATES = (1, 2, 4, 8, 15, 30, 60, 0)   # ticks per second; 0 = as fast as possible (one tick per frame)


class App:
    def __init__(self, universe, title, ticks_per_second=None, smooth=None):
        self.universe = universe
        self.title = title
        tps = config.DEFAULT_TICKS_PER_SECOND if ticks_per_second is None else ticks_per_second
        if tps == 0:
            self.rate_index = TICK_RATES.index(0)
        else:   # nearest preset
            self.rate_index = min(range(len(TICK_RATES) - 1), key=lambda i: abs(TICK_RATES[i] - tps))
        self.smooth = config.SMOOTH_MOVEMENT if smooth is None else smooth
        self.moving = False
        self.show_hud = True
        self.show_help = False
        self.inspector = True
        self.prompt = None          # text typed into the spawn prompt, or None when closed
        self.message = None
        self.message_until = 0.0
        self.sim_ms = 0.0
        self.accumulator = 0.0

    @property
    def tps(self):
        return TICK_RATES[self.rate_index]

    def flash(self, text, seconds=3.0):
        self.message = text
        self.message_until = time.monotonic() + seconds
        print(f"INFO: {text}")

    def run(self):
        pygame.init()
        u = self.universe
        side = u.size_px + 2 * u.spacing
        screen = pygame.display.set_mode((side, side))
        pygame.display.set_caption(self.title)
        renderer = Renderer(screen, u)
        clock = pygame.time.Clock()
        self.flash("Space to start moving  -  C for controls", 4)

        running = True
        while running:
            dt = clock.tick(config.MAX_FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    running = self.on_key(event, renderer)
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    self.on_click(event, renderer)

            alpha = 1.0
            if self.moving:
                if self.tps == 0:
                    self.step()
                else:
                    interval = 1.0 / self.tps
                    self.accumulator = min(self.accumulator + dt, 2 * interval)   # never spiral when ticks are slow
                    while self.accumulator >= interval:
                        self.step()
                        self.accumulator -= interval
                    if self.smooth:
                        alpha = self.accumulator / interval

            if self.message and time.monotonic() > self.message_until:
                self.message = None
            inspect = None
            if self.inspector:
                inspect = u.square_at(*renderer.cell_at(pygame.mouse.get_pos()))
            renderer.draw(
                alpha,
                hud_lines=self.hud_lines(clock) if self.show_hud else None,
                inspect=inspect,
                prompt=None if self.prompt is None else
                f"Spawn how many Squares? (m = max, h = 1/2 max, q = 1/4 max)  {self.prompt}_",
                message=self.message,
                show_help=self.show_help,
            )
        pygame.quit()
        print(f"\n{self.title} ended after {u.tick_count} ticks with {len(u.squares)} Squares\n")

    def step(self):
        start = time.perf_counter()
        self.universe.tick()
        self.sim_ms = (time.perf_counter() - start) * 1000

    def hud_lines(self, clock):
        u = self.universe
        s = u.last_stats
        rate = "max" if self.tps == 0 else f"{self.tps}/s"
        state = "MOVING" if self.moving else "STOPPED"
        return [
            f"{state}   Squares {len(u.squares)}/{u.max_number_of_squares}   tick {u.tick_count}   rate {rate}"
            f"{'  smooth' if self.smooth else ''}",
            f"fps {clock.get_fps():.0f}   sim {self.sim_ms:.1f} ms/tick",
            f"last tick: moved {s.moved}  pushed {s.pushed}  crushed {s.crushed}  border {s.border_kills}"
            f"  trapped {s.trapped}",
        ]

    def spawn(self, choice):
        u = self.universe
        try:
            count = u.spawn_amount(choice)
        except ValueError:
            self.flash(f"'{choice}' is not a number, m, h or q")
            return
        if u.spawn(count):
            self.flash(f"Spawned {count} Squares")
        else:
            self.flash(f"There are not enough empty grids remaining "
                       f"({u.max_number_of_squares - len(u.squares)} empty, {count} requested)")

    def on_key(self, event, renderer):
        key = event.key
        if self.prompt is not None:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                text, self.prompt = self.prompt, None
                if text:
                    self.spawn(text)
            elif key == pygame.K_ESCAPE:
                self.prompt = None
            elif key == pygame.K_BACKSPACE:
                self.prompt = self.prompt[:-1]
            elif event.unicode and (event.unicode.isdigit() or event.unicode.lower() in "mhq"):
                self.prompt += event.unicode.lower()
            return True

        if key in (pygame.K_ESCAPE, pygame.K_e):
            if self.show_help and key == pygame.K_ESCAPE:
                self.show_help = False
                return True
            return False
        if key in (pygame.K_SPACE, pygame.K_m):
            self.toggle_moving()
        elif key in (pygame.K_n, pygame.K_RIGHT) and not self.moving:
            self.step()
        elif key == pygame.K_s:
            self.prompt = ""
        elif key in (pygame.K_1, pygame.K_KP1):
            self.spawn("q")
        elif key in (pygame.K_2, pygame.K_KP2):
            self.spawn("h")
        elif key in (pygame.K_3, pygame.K_KP3):
            self.spawn("m")
        elif key == pygame.K_d:
            self.delete_under_cursor(renderer)
        elif key == pygame.K_a:
            count = len(self.universe.squares)
            self.universe.destroy_all()
            self.flash(f"Deleted {count} Squares")
        elif key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.rate_index = min(self.rate_index + 1, len(TICK_RATES) - 1)
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.rate_index = max(self.rate_index - 1, 0)
        elif key == pygame.K_l:
            self.smooth = not self.smooth
        elif key == pygame.K_i:
            self.inspector = not self.inspector
        elif key == pygame.K_h:
            self.show_hud = not self.show_hud
        elif key == pygame.K_c:
            self.show_help = not self.show_help
        return True

    def on_click(self, event, renderer):
        if event.button == 1:
            self.toggle_moving()
        elif event.button == 3:
            self.delete_under_cursor(renderer)

    def toggle_moving(self):
        self.moving = not self.moving
        self.accumulator = 0.0
        if not self.moving:
            self.universe.clear_animation()   # freeze Squares where they are instead of mid-animation

    def delete_under_cursor(self, renderer):
        square = self.universe.square_at(*renderer.cell_at(pygame.mouse.get_pos()))
        if square is not None:
            self.universe.destroy(square)
