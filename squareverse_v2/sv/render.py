"""pygame drawing: the particle grid (one buffer blit, as in sand.py), wells, HUD, help and inspector."""

import math

import pygame

from . import config
from .world import DIR_NAMES, DIRS, VIEW_MODES, Well

HELP = [
    ("LMB / RMB / wheel", "pour / erase / brush size"),
    ("shift+LMB", f"pour ghosts: feel gravity but pass through everything for {config.GHOST_TICKS} ticks"),
    ("1-5 / 6", "pour mass " + " / ".join(str(m) for m in config.POUR_MASSES)
     + " / random {}-{}".format(*config.RANDOM_MASS)),
    ("G / shift+G", "place planet well / repulsor: brush size, solid, weighs its area x pour mass"),
    ("F / shift+F", "place particle spawner: brush size sets the rate; shift locks it in place"),
    ("B", "place super well (swallows what touches its core; overlapping ones merge)"),
    ("shift+B", "collapse: dense mass becomes a super well, on/off"),
    ("shift+drag on a body", "move a well or spawner (wells attract each other; heavy ones are slow)"),
    ("X", "delete nearest well or spawner"),
    (", / .", "lighter / heavier nearest well"),
    ("; / '", "nearest super well spins slower / faster"),
    ("< / >", "all gravity weaker / stronger (collapse threshold follows)"),
    ("arrows, Q/E, 0", "global gravity direction, rotate, off"),
    ("S", "self-gravity on/off"),
    ("O", "global orbit: off / clockwise / counterclockwise"),
    ("W", "continuous borders (leave one side, enter the opposite) on/off"),
    ("K / L", "global orbit slower / faster"),
    ("M / P", "merging / splitting on/off"),
    ("J", "children steer their parent on/off"),
    ("V", "view: " + " / ".join(VIEW_MODES)),
    ("I", "inspector (hover a particle)"),
    ("[ / ]", "square size"),
    ("+ / -", "ticks per frame"),
    ("space / N", "pause / single tick"),
    ("F1-F4", "presets: rain, disk, cloud, binary"),
    ("F11", "fullscreen (the window can also be resized)"),
    ("C / H / Esc", "clear / help / quit"),
]


def pour_label(m):
    return "{}-{} random".format(*m) if isinstance(m, tuple) else str(m)


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
        self.overlay_key = None

    def draw_world(self, world, mode):
        world.render(mode)
        small = pygame.image.frombuffer(world.rgb, (world.w, world.h), "RGB")
        self.screen.fill(config.BG)
        self.screen.blit(pygame.transform.scale(small, (world.w * world.cell, world.h * world.cell)), (0, 0))
        key = (world.cell, world.w, world.h)
        if self.overlay_key != key:
            self.overlay, self.overlay_key = grid_overlay(world), key
        if self.overlay:
            self.screen.blit(self.overlay, (0, 0))

    def draw_wells(self, world):
        # with continuous borders a well near an edge shows on the other side too
        pw, ph = world.w * world.cell, world.h * world.cell
        shifts = [(sx, sy) for sx in (-pw, 0, pw) for sy in (-ph, 0, ph)] if world.wrap else [(0, 0)]
        for wl in world.wells:
            radius = max(3, int(world.well_radius_px(wl)))
            extent = max(radius, world.well_range(wl) * world.cell) + 2
            for sx, sy in shifts:
                center = (int(wl.x * world.cell) + sx, int(wl.y * world.cell) + sy)
                if (-extent <= center[0] <= pw + extent and -extent <= center[1] <= ph + extent):
                    self._draw_well(world, wl, center, radius)
        for sp in world.spawners:
            radius = max(3, int(sp.radius * world.cell))
            for sx, sy in shifts:
                center = (int(sp.x * world.cell) + sx, int(sp.y * world.cell) + sy)
                if -radius <= center[0] <= pw + radius and -radius <= center[1] <= ph + radius:
                    self._draw_spawner(sp, center, radius)

    def _draw_spawner(self, sp, center, radius):
        """A dashed circle with a plus in the middle; a locked spawner gets a square round the plus."""
        screen, color = self.screen, config.SPAWNER_COLOR
        dashes = max(12, int(2 * math.pi * radius / 10))
        for d in range(0, dashes, 2):
            a0, a1 = 2 * math.pi * d / dashes, 2 * math.pi * (d + 1) / dashes
            pygame.draw.line(screen, color, (center[0] + radius * math.cos(a0), center[1] + radius * math.sin(a0)),
                             (center[0] + radius * math.cos(a1), center[1] + radius * math.sin(a1)))
        cx, cy = center
        pygame.draw.line(screen, color, (cx - 4, cy), (cx + 4, cy))
        pygame.draw.line(screen, color, (cx, cy - 4), (cx, cy + 4))
        if sp.locked:
            pygame.draw.rect(screen, color, (cx - 6, cy - 6, 13, 13), 1)

    def _draw_well(self, world, wl, center, radius):
        screen = self.screen
        if wl.is_super:
            # dotted circle round its range (strong pull and spin), then the black core with a faint rim
            reach = world.well_range(wl) * world.cell
            dots = max(24, int(2 * math.pi * reach / 9))
            for d in range(dots):
                a = 2 * math.pi * d / dots
                pos = (int(center[0] + reach * math.cos(a)), int(center[1] + reach * math.sin(a)))
                pygame.draw.circle(screen, config.SUPER_RANGE_COLOR, pos, 1)
            self._draw_spin_arms(wl, center, radius)
            pygame.draw.circle(screen, (0, 0, 0), center, radius)
            pygame.draw.circle(screen, config.SUPER_RIM_COLOR, center, radius + 1, 1)
        elif wl.wave >= 0:
            # dissolving: drawn on its own surface with the swept part cut out and the wave front glowing
            surf = pygame.Surface((2 * radius + 2, 2 * radius + 2), pygame.SRCALPHA)
            local = (radius + 1, radius + 1)
            self._draw_planet(surf, wl, local, radius)
            cell = world.cell
            ex, ey = local[0] + wl.wave_dx * cell, local[1] + wl.wave_dy * cell
            er = wl.wave * cell
            pygame.draw.circle(surf, (0, 0, 0, 0), (ex, ey), er)
            steps = max(24, int(er))
            for s in range(steps):
                a0, a1 = 2 * math.pi * s / steps, 2 * math.pi * (s + 1) / steps
                p0 = (ex + er * math.cos(a0), ey + er * math.sin(a0))
                p1 = (ex + er * math.cos(a1), ey + er * math.sin(a1))
                if all(math.hypot(px - local[0], py - local[1]) <= radius for px, py in (p0, p1)):
                    pygame.draw.line(surf, config.DISSOLVE_COLOR, p0, p1, 2)
            screen.blit(surf, (center[0] - local[0], center[1] - local[1]))
        else:
            self._draw_planet(screen, wl, center, radius)

    def _draw_planet(self, surf, wl, center, radius):
        """A solid planet: filled body with craters turning with its spin, rim coloured by attract / repel."""
        color = config.WELL_COLOR if wl.sign > 0 else config.REPULSOR_COLOR
        pygame.draw.circle(surf, config.PLANET_COLOR, center, radius)
        if radius >= 5:
            for k, (dist, size) in enumerate(((0.55, 0.16), (0.6, 0.11), (0.3, 0.12), (0.72, 0.08))):
                a = wl.phase + k * 2.1
                pos = (center[0] + radius * dist * math.cos(a), center[1] + radius * dist * math.sin(a))
                pygame.draw.circle(surf, config.CRATER_COLOR, pos, max(1, int(radius * size)))
        pygame.draw.circle(surf, color, center, radius, 1)

    def _draw_spin_arms(self, wl, center, core):
        """Three spiral arms round a super well's core, trailing like a whirlpool and turning with its spin, each
        tipped with an arrowhead in the direction it turns; brighter and turning faster the faster it spins."""
        way = 1 if wl.spin >= 0 else -1
        outer, inner = core * 3.0 + 16, core * 1.3 + 2
        k = 0.45 + 0.55 * min(1.0, abs(wl.spin))
        color = tuple(int(c * k) for c in config.SUPER_SPIN_COLOR)
        for arm in range(3):
            base = wl.phase + arm * 2 * math.pi / 3
            pts = []
            for s in range(9):
                t = s / 8                                # 0 at the outer end, 1 at the core
                r = outer + (inner - outer) * t
                a = base + way * 1.6 * t                 # the inner end leads: arms trail the spin
                pts.append((center[0] + r * math.cos(a), center[1] + r * math.sin(a)))
            pygame.draw.lines(self.screen, color, False, pts, 2)
            # arrowhead at the inner end, pointing along the way it turns
            (x1, y1), (x0, y0) = pts[-1], pts[-2]
            ang = math.atan2(y1 - y0, x1 - x0)
            for side in (2.6, -2.6):
                tip = (x1 + 6 * math.cos(ang + side), y1 + 6 * math.sin(ang + side))
                pygame.draw.line(self.screen, color, (x1, y1), tip, 2)

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
        supers = sum(wl.is_super for wl in world.wells)
        orbit = {0: "off", 1: "clockwise", -1: "counterclockwise"}[world.orbit]
        if world.orbit:
            orbit += f" ({world.orbit_edge_speed():.1f} cells/tick at the edge)"
        lines = [
            (f"particles {world.particle_count():,}   awake {world.awake_count():,}   mass {world.total_mass():,}"
             f"   tick {world.tick_count:,}   {fps:.0f} fps" + ("   PAUSED" if app.paused else ""), config.FG),
            (f"step {world.step_ms:.1f} ms   gravity {world.gravity_ms:.1f} ms   render {app.render_ms:.1f} ms"
             f"   ticks/frame {app.ticks_per_frame}   square {world.cell}px   view {VIEW_MODES[app.view]}",
             config.FG),
            (f"gravity {grav}   strength x{world.g_scale:.2f}   orbit {orbit}"
             f"   borders {'wrap' if world.wrap else 'solid'}   self-gravity {on(world.sg_on)}"
             f"   merge {on(world.merge_on)}   split {on(world.split_on)}   lean {on(world.lean_on)}"
             f"   pour mass {pour_label(app.pour_mass)}", config.FG),
            (f"wells {sum(not wl.is_super for wl in world.wells)}   spawners {len(world.spawners)}"
             f"   ghosts {world.ghost_count():,} (mass {world.ghost_mass():,})"
             f"   super wells {supers}"
             f" holding {world.super_mass():,}   collapse {on(world.collapse_on)}"
             f" at {world.collapse_threshold():,.0f} mass   explode at {config.SUPER_EXPLODE_MASS:,}"
             f" ({world.explosions} so far)   planets formed {world.planets_formed}", config.FG),
            (f"last tick: moved {s[0]:,}  collisions {s[1]:,}  merges {s[2]:,}  splits {s[3]:,}  sinks {s[4]:,}"
             f"  absorbed {s[5]:,}", config.DIM),
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

    def draw_body_inspector(self, world, body, pos):
        if isinstance(body, Well):
            return self.draw_well_inspector(world, body, pos)
        lines = [
            (f"{'locked ' if body.locked else ''}spawner   {body.rate * config.FPS:,.0f} particles/s"
             f"   mass {pour_label(body.masses)}", config.FG),
            (f"cell ({body.x:.0f}, {body.y:.0f})   v ({body.vx:+.2f}, {body.vy:+.2f})", config.FG),
        ]
        self.panel(lines, (pos[0] + 16, pos[1] + 16), self.small)

    def draw_well_inspector(self, world, wl, pos):
        kind = "super well" if wl.is_super else ("repulsor" if wl.sign < 0 else "well")
        lines = [
            (f"{kind}   mass {wl.mass:,.0f}   cell ({wl.x:.0f}, {wl.y:.0f})", config.FG),
            (f"v ({wl.vx:+.3f}, {wl.vy:+.3f})   mobility {wl.mobility():.3f}", config.FG),
            (f"range {world.well_range(wl):.0f} cells   spin {abs(wl.spin):.2f} (; / ') "
             f"{'clockwise' if wl.spin > 0 else 'counterclockwise'}" if wl.is_super else
             f"spin {abs(wl.omega) * config.FPS:.2f} rad/s {'clockwise' if wl.omega > 0 else 'counterclockwise'}   "
             f"reach {world.reach(wl):.0f} cells", config.DIM),
        ]
        self.panel(lines, (pos[0] + 16, pos[1] + 16), self.small)

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
