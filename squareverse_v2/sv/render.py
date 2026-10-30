"""pygame drawing: the particle grid (one buffer blit, as in sand.py), wells, HUD, help and inspector."""

import math

import pygame

from . import config
from .world import DIR_NAMES, DIRS, VIEW_MODES

HELP = [
    ("LMB / RMB / wheel", "pour / erase / brush size"),
    ("1-5", "pour mass " + " / ".join(str(m) for m in config.POUR_MASSES)),
    ("G / shift+G", "place well / repulsor at cursor"),
    ("MMB drag", "move a well"),
    ("X", "delete nearest well"),
    (", / .", "weaker / stronger nearest well"),
    ("arrows, Q/E, 0", "global gravity direction, rotate, off"),
    ("S", "self-gravity on/off"),
    ("K / L", "self-gravity weaker / stronger"),
    ("M / P", "merging / splitting on/off"),
    ("J", "children steer their parent on/off"),
    ("V", "view: " + " / ".join(VIEW_MODES)),
    ("I", "inspector (hover a particle)"),
    ("[ / ]", "square size"),
    ("+ / -", "ticks per frame"),
    ("space / N", "pause / single tick"),
    ("F1-F4", "presets: rain, disk, cloud, binary"),
    ("C / H / Esc", "clear / help / quit"),
]


def grid_overlay(world):
    """Thin background-coloured lines that separate the squares (sand.py)."""
    cell = world.cell
    if cell < 4:
        return None
    pw, ph = world.w * cell, world.h * cell
    surf = pygame.Surface((pw, ph), pygame.SRCALPHA)
    for x in range(cell - 1, pw, cell):
        pygame.draw.line(surf, config.BG, (x, 0), (x, ph))
    for y in range(cell - 1, ph, cell):
        pygame.draw.line(surf, config.BG, (0, y), (pw, y))
    return surf


class Renderer:
    def __init__(self, screen):
        self.screen = screen
        self.font = pygame.font.Font(None, 20)
        self.small = pygame.font.Font(None, 18)
        self.overlay = None
        self.overlay_cell = None

    def draw_world(self, world, mode):
        world.render(mode)
        small = pygame.image.frombuffer(world.rgb, (world.w, world.h), "RGB")
        self.screen.fill(config.BG)
        self.screen.blit(pygame.transform.scale(small, (world.w * world.cell, world.h * world.cell)), (0, 0))
        if self.overlay_cell != world.cell:
            self.overlay, self.overlay_cell = grid_overlay(world), world.cell
        if self.overlay:
            self.screen.blit(self.overlay, (0, 0))

    def draw_wells(self, world):
        for x, y, s in world.wells:
            color = config.WELL_COLOR if s > 0 else config.REPULSOR_COLOR
            center = (int(x * world.cell), int(y * world.cell))
            radius = int(5 + 2.5 * math.sqrt(abs(s)))
            pygame.draw.circle(self.screen, color, center, radius, 1)
            pygame.draw.circle(self.screen, color, center, 3)

    def draw_compass(self, gdir, center, radius=22):
        screen = self.screen
        pygame.draw.circle(screen, (34, 38, 46), center, radius)
        pygame.draw.circle(screen, (60, 66, 78), center, radius, 1)
        if gdir is None:
            pygame.draw.circle(screen, config.DIM, center, 3)
            return
        dx, dy = DIRS[gdir]
        ang = math.atan2(dy, dx)
        cx, cy = center
        tip = (cx + math.cos(ang) * (radius - 6), cy + math.sin(ang) * (radius - 6))
        tail = (cx - math.cos(ang) * (radius - 8), cy - math.sin(ang) * (radius - 8))
        pygame.draw.line(screen, config.FG, tail, tip, 2)
        for side in (2.5, -2.5):
            wing = (tip[0] - math.cos(ang + side / 4.5) * 8, tip[1] - math.sin(ang + side / 4.5) * 8)
            pygame.draw.line(screen, config.FG, tip, wing, 2)

    def panel(self, lines, topleft, font=None, alpha=200):
        font = font or self.font
        surfs = [font.render(t, True, col) for t, col in lines]
        pw = max(s.get_width() for s in surfs) + 20
        ph = sum(s.get_height() + 2 for s in surfs) + 14
        x, y = topleft
        sw, sh = self.screen.get_size()
        x, y = max(0, min(x, sw - pw)), max(0, min(y, sh - ph))
        bg = pygame.Surface((pw, ph), pygame.SRCALPHA)
        bg.fill((*config.BG, alpha))
        self.screen.blit(bg, (x, y))
        ty = y + 8
        for s in surfs:
            self.screen.blit(s, (x + 10, ty))
            ty += s.get_height() + 2
        return pw, ph

    def draw_hud(self, world, app, fps):
        on = lambda flag: "ON" if flag else "off"
        s = world.stats
        grav = "off" if world.gdir is None else DIR_NAMES[world.gdir]
        lines = [
            (f"particles {world.particle_count():,}   awake {world.awake_count():,}   mass {world.total_mass():,}"
             f"   tick {world.tick_count:,}   {fps:.0f} fps" + ("   PAUSED" if app.paused else ""), config.FG),
            (f"step {world.step_ms:.1f} ms   gravity {world.gravity_ms:.1f} ms   render {app.render_ms:.1f} ms"
             f"   ticks/frame {app.ticks_per_frame}   square {world.cell}px   view {VIEW_MODES[app.view]}",
             config.FG),
            (f"gravity {grav}   wells {len(world.wells)}   self-gravity {on(world.sg_on)} (G {world.sg_g:.4f})"
             f"   merge {on(world.merge_on)}   split {on(world.split_on)}   lean {on(world.lean_on)}"
             f"   pour mass {app.pour_mass}", config.FG),
            (f"last tick: moved {s[0]:,}  collisions {s[1]:,}  merges {s[2]:,}  splits {s[3]:,}  sinks {s[4]:,}",
             config.DIM),
        ]
        if not app.show_help:
            lines.append(("H for controls", config.DIM))
        self.panel(lines, (10, 10))

    def draw_help(self):
        keys = [self.small.render(k, True, (255, 220, 120)) for k, _ in HELP]
        descs = [self.small.render(d, True, config.FG) for _, d in HELP]
        key_w = max(k.get_width() for k in keys) + 16
        line_h = max(k.get_height() for k in keys) + 3
        width = key_w + max(d.get_width() for d in descs) + 16
        height = line_h * len(HELP) + 12
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill((*config.BG, 225))
        for i, (k, d) in enumerate(zip(keys, descs)):
            panel.blit(k, (8, 6 + i * line_h))
            panel.blit(d, (key_w, 6 + i * line_h))
        sw, sh = self.screen.get_size()
        self.screen.blit(panel, (sw - width - 10, sh - height - 10))

    def draw_inspector(self, info, pos):
        ul, ur, dl, dr = info["quad"]
        vx, vy = info["v"]
        lines = [
            (f"mass {info['mass']}   cell {info['cell']}   {'awake' if info['awake'] else 'asleep'}", config.FG),
            (f"v ({vx:+.2f}, {vy:+.2f})  |v| {math.hypot(vx, vy):.2f}", config.FG),
            (f"children  {ul:>4} {ur:<4}", config.DIM),
            (f"          {dl:>4} {dr:<4}", config.DIM),
        ]
        self.panel(lines, (pos[0] + 16, pos[1] + 16), self.small)
