"""pygame drawing: static grid background, Squares (optionally interpolated between ticks), HUD and inspector."""

import pygame

from . import config

HELP_LINES = (
    ("Space / M / left-click", "start or stop movement"),
    ("N", "single tick while stopped"),
    ("S", "spawn Squares (type a number, m, h or q)"),
    ("1 / 2 / 3", "spawn 1/4 max / 1/2 max / fill all empty cells"),
    ("D / right-click", "delete the Square under the cursor"),
    ("A", "delete all Squares"),
    ("+ / -", "faster / slower tick rate"),
    ("L", "toggle smooth movement"),
    ("I", "toggle child-universe inspector (hover a Square)"),
    ("H", "toggle HUD"),
    ("C", "toggle this controls list"),
    ("E / Esc", "end the simulation"),
)


class Renderer:
    def __init__(self, screen, universe):
        self.screen = screen
        self.universe = universe
        self.font = pygame.font.Font(None, 18)
        self.small_font = pygame.font.Font(None, 16)
        self.background = self._build_background()

    def _build_background(self):
        u = self.universe
        s = u.spacing
        surface = pygame.Surface(self.screen.get_size()).convert()
        surface.fill(config.BACKGROUND_COLOR)
        end = u.size_px + s
        for i in range(u.n + 1):
            p = s + i * s
            pygame.draw.line(surface, config.GRID_COLOR, (p, s), (p, end))
            pygame.draw.line(surface, config.GRID_COLOR, (s, p), (end, p))
        return surface

    def cell_at(self, pos):
        s = self.universe.spacing
        return (pos[0] - s) // s, (pos[1] - s) // s

    def draw(self, alpha, hud_lines=None, inspect=None, prompt=None, message=None, show_help=False):
        screen = self.screen
        screen.blit(self.background, (0, 0))
        self._draw_squares(alpha)
        if hud_lines:
            self._draw_panel(hud_lines, (6, 6))
        if inspect is not None and inspect.alive:
            self._draw_inspector(inspect)
        if message:
            self._draw_centered_banner(message, 0.82)
        if prompt:
            self._draw_centered_banner(prompt, 0.5)
        if show_help:
            self._draw_help()
        pygame.display.flip()

    def _draw_squares(self, alpha):
        u = self.universe
        s = u.spacing
        rect = pygame.draw.rect
        screen = self.screen
        blocked_color = config.BLOCKED_OUTLINE_COLOR
        if alpha < 1.0:
            # replay the tick in its animation waves so Squares never pass through each other
            wave_time = alpha * u.wave_count
            drawn = [(sq, sq.position_at(wave_time, u.wave_count)) for sq in u.squares.values()]
            drawn += [(sq, sq.position_at(wave_time, u.wave_count)) for sq, death_wave in u.dying if wave_time < death_wave]
        else:
            drawn = [(sq, (sq.col, sq.row)) for sq in u.squares.values()]
        for sq, (col, row) in drawn:
            x = round(s + col * s)
            y = round(s + row * s)
            rect(screen, sq.body_color, (x, y, s, s))
            rect(screen, blocked_color if sq.blocked else sq.outline_color, (x, y, s + 1, s + 1), 1)

    def _text_block(self, lines, font):
        surfaces = [font.render(line, True, (235, 235, 235)) for line in lines]
        width = max(surf.get_width() for surf in surfaces) + 12
        height = sum(surf.get_height() + 2 for surf in surfaces) + 8
        return surfaces, width, height

    def _draw_panel(self, lines, pos, font=None):
        surfaces, width, height = self._text_block(lines, font or self.font)
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 170))
        y = 4
        for surf in surfaces:
            panel.blit(surf, (6, y))
            y += surf.get_height() + 2
        self.screen.blit(panel, pos)
        return width, height

    def _draw_centered_banner(self, text, y_fraction):
        surfaces, width, height = self._text_block([text], self.font)
        w, h = self.screen.get_size()
        self._draw_panel([text], ((w - width) // 2, int(h * y_fraction) - height // 2))

    def _draw_help(self):
        font = self.small_font
        keys = [font.render(k, True, (255, 220, 120)) for k, _ in HELP_LINES]
        descs = [font.render(d, True, (235, 235, 235)) for _, d in HELP_LINES]
        key_w = max(k.get_width() for k in keys) + 16
        line_h = max(k.get_height() for k in keys) + 3
        width = key_w + max(d.get_width() for d in descs) + 16
        height = line_h * len(HELP_LINES) + 12
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 200))
        for i, (k, d) in enumerate(zip(keys, descs)):
            panel.blit(k, (8, 6 + i * line_h))
            panel.blit(d, (key_w, 6 + i * line_h))
        w, h = self.screen.get_size()
        self.screen.blit(panel, ((w - width) // 2, (h - height) // 2))

    def _draw_inspector(self, sq):
        children = sq.children
        n = children.n
        cell = max(5, min(12, 144 // n))
        counts = children.counts()
        lines = [
            f"Square #{sq.id}   mass {sq.mass}",
            f"momentum: {sq.previous_direction or '-'}",
            f"up {counts['up']}  down {counts['down']}  left {counts['left']}  right {counts['right']}",
        ]
        surfaces, text_w, text_h = self._text_block(lines, self.small_font)
        grid_px = n * cell
        width = max(text_w, grid_px + 12)
        height = text_h + grid_px + 8

        mx, my = pygame.mouse.get_pos()
        sw, sh = self.screen.get_size()
        x = mx + 16 if mx + 16 + width < sw else mx - 16 - width
        y = my + 16 if my + 16 + height < sh else my - 16 - height
        x, y = max(0, x), max(0, y)

        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 200))
        ty = 4
        for surf in surfaces:
            panel.blit(surf, (6, ty))
            ty += surf.get_height() + 2
        gx, gy = 6, text_h
        pygame.draw.rect(panel, sq.body_color, (gx, gy, grid_px, grid_px))
        child_color = (25, 25, 25) if sq.body_color[0] > 127 else (230, 230, 230)
        for col, row, _ in children.children:
            pygame.draw.rect(panel, child_color, (gx + col * cell + 1, gy + row * cell + 1, cell - 1, cell - 1))
        half = children.half * cell
        pygame.draw.line(panel, (255, 60, 60), (gx + half, gy), (gx + half, gy + grid_px))
        pygame.draw.line(panel, (255, 60, 60), (gx, gy + half), (gx + grid_px, gy + half))
        pygame.draw.rect(panel, (200, 200, 200), (gx, gy, grid_px + 1, grid_px + 1), 1)
        self.screen.blit(panel, (x, y))
