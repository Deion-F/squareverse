"""pygame drawing: the particle grid (one buffer blit, as in sand.py, through the camera), wells, help, inspector and
the usage readout."""

import math

import pygame

from . import config
from .world import DIRS, VIEW_MODES, Star, Well

HELP = [
    ("menu button / Tab", "open the control menu (bottom right): every setting, with an (i) explaining it"),
    ("LMB / RMB / wheel", "use the mouse tool (pour by default; pick one in the menu) / erase / brush size"),
    ("shift+LMB", f"pour ghosts: feel gravity but pass through everything for {config.GHOST_TICKS} ticks"),
    ("1-5 / 6", "pour mass " + " / ".join(str(m) for m in config.POUR_MASSES)
     + " / random {}-{}".format(*config.RANDOM_MASS)),
    ("G / shift+G", "place star (a ball of particles, core of pour-mass particles, held by its own gravity) / solid "
                    "repulsor"),
    ("shift+LMB, Star tool", "place a ghost star: flies through everything, lands as a star"),
    ("F / shift+F", "place particle spawner: brush size sets the rate; shift locks it in place"),
    ("B", "place super well (swallows what touches its core; overlapping ones merge)"),
    ("shift+B", "collapse: dense mass becomes a super well, on/off"),
    ("shift+drag on a body", "move a well or spawner, or pull a star along (heavy super wells are slow)"),
    ("X", "delete nearest star (and its particles), well or spawner"),
    (", / .", "lighter / heavier nearest star or repulsor (it resizes to match its new mass)"),
    ("; / '", "nearest super well spins slower / faster"),
    ("< / >", "all gravity weaker / stronger (collapse threshold follows)"),
    ("arrows, Q/E, 0", "global gravity direction, rotate, off"),
    ("S", "self-gravity on/off"),
    ("O", "global orbit: off / clockwise / counterclockwise"),
    ("W", "continuous borders (leave one side, enter the opposite) on/off; not in a round universe"),
    ("K / L", "global orbit slower / faster"),
    ("M / P", "merging / splitting on/off"),
    ("J", "children steer their parent on/off"),
    ("V", "view: " + " / ".join(VIEW_MODES)),
    ("I", "inspector (hover a particle)"),
    ("[ / ]", "square size"),
    ("ctrl+wheel, Z / shift+Z", "zoom out / in at the mouse (the whole universe, not the square size)"),
    ("middle drag, alt+drag", "pan the view; R resets it (1x, centred), shift+R fits the whole universe"),
    ("U", "universe: the window's rectangle / round, reaching past the window (rotation stays on its circles)"),
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


class Camera:
    """Where the window looks into the universe: zoom (window px per universe px; 1 shows the squares at their size)
    and the universe point at the window's centre, as an offset (universe px) from the universe's centre. It never
    zooms out past where the whole universe fits, nor pans past its edges."""

    def __init__(self):
        self.zoom = 1.0
        self.ox = self.oy = 0.0
        self.sw = self.sh = self.upw = self.uph = 1
        self.cell = 1

    def update(self, world, screen_size):
        self.sw, self.sh = screen_size
        self.cell = world.cell
        self.upw, self.uph = world.w * world.cell, world.h * world.cell
        self.clamp()

    @property
    def k(self):
        """Window px per cell."""
        return self.cell * self.zoom

    def min_zoom(self):
        return min(1.0, self.sw / self.upw, self.sh / self.uph)

    def clamp(self):
        self.zoom = min(max(self.zoom, self.min_zoom()), config.ZOOM_MAX)
        lx = max(0.0, (self.upw - self.sw / self.zoom) / 2)
        ly = max(0.0, (self.uph - self.sh / self.zoom) / 2)
        self.ox, self.oy = min(max(self.ox, -lx), lx), min(max(self.oy, -ly), ly)

    def to_world(self, sx, sy):
        """The universe px (at zoom 1, as the World's methods take) under a window px."""
        return (self.upw / 2 + self.ox + (sx - self.sw / 2) / self.zoom,
                self.uph / 2 + self.oy + (sy - self.sh / 2) / self.zoom)

    def point(self, x, y):
        """The window px of a point in cells."""
        return (self.sw / 2 + (x * self.cell - self.upw / 2 - self.ox) * self.zoom,
                self.sh / 2 + (y * self.cell - self.uph / 2 - self.oy) * self.zoom)

    def zoom_at(self, factor, sx, sy):
        """Zoom by factor keeping the universe point under window px (sx, sy) where it is."""
        wx, wy = self.to_world(sx, sy)
        self.zoom *= factor
        if abs(self.zoom - 1.0) < 0.02:                  # land on 1 exactly: the squares at their own size
            self.zoom = 1.0
        self.zoom = min(max(self.zoom, self.min_zoom()), config.ZOOM_MAX)
        self.ox = wx - self.upw / 2 - (sx - self.sw / 2) / self.zoom
        self.oy = wy - self.uph / 2 - (sy - self.sh / 2) / self.zoom
        self.clamp()

    def pan(self, dx, dy):
        """Drag the view by (dx, dy) window px."""
        self.ox -= dx / self.zoom
        self.oy -= dy / self.zoom
        self.clamp()

    def reset(self):
        self.zoom, self.ox, self.oy = 1.0, 0.0, 0.0
        self.clamp()

    def fit(self):
        self.zoom, self.ox, self.oy = self.min_zoom(), 0.0, 0.0
        self.clamp()


class Renderer:
    def __init__(self, screen):
        self.screen = screen
        self.cam = Camera()
        self.font = pygame.font.Font(None, 20)
        self.small = pygame.font.Font(None, 18)
        self.overlay = None
        self.overlay_key = None
        self._glows = {}            # star coronas by (radius, colour)
        self._arms = {}             # super well id -> (its phase last frame, the angle its arms are drawn at)

    def draw_world(self, world, mode):
        """The cells the camera sees, scaled to the window (averaged when zoomed out past a px per cell)."""
        cam = self.cam
        world.render(mode)
        self.screen.fill(config.OUTSIDE)
        small = pygame.image.frombuffer(world.rgb, (world.w, world.h), "RGB")
        k = cam.k
        (ax, ay), (bx, by) = cam.to_world(0, 0), cam.to_world(cam.sw, cam.sh)
        x0, y0 = max(0, int(ax // world.cell)), max(0, int(ay // world.cell))
        x1, y1 = min(world.w, int(-(-bx // world.cell))), min(world.h, int(-(-by // world.cell)))
        if x1 <= x0 or y1 <= y0:
            return
        sub = small.subsurface((x0, y0, x1 - x0, y1 - y0))
        size = (max(1, round((x1 - x0) * k)), max(1, round((y1 - y0) * k)))
        scale = pygame.transform.smoothscale if k < 1 else pygame.transform.scale
        corner = tuple(round(c) for c in cam.point(x0, y0))
        self.screen.blit(scale(sub, size), corner)
        if cam.zoom == 1.0:                              # the lines between squares, at their own size only
            key = (world.cell, world.w, world.h)
            if self.overlay_key != key:
                self.overlay, self.overlay_key = grid_overlay(world), key
            if self.overlay:
                self.screen.blit(self.overlay, tuple(round(c) for c in cam.point(0, 0)))

    def draw_wells(self, world):
        cam, k = self.cam, self.cam.k
        sw, sh = self.screen.get_size()
        # with continuous borders a well near an edge shows on the other side too
        pw, ph = world.w * k, world.h * k
        shifts = [(sx, sy) for sx in (-pw, 0, pw) for sy in (-ph, 0, ph)] if world.wrap else [(0, 0)]

        def at(b, sx, sy):
            x, y = cam.point(b.x, b.y)
            return int(x + sx), int(y + sy)

        def visible(c, r):
            return -r <= c[0] <= sw + r and -r <= c[1] <= sh + r

        for st in world.stars:
            ring = int(st.ring * k)
            for sx, sy in shifts:
                center = at(st, sx, sy)
                if visible(center, ring):
                    self._draw_star_marks(st, center, ring)
        arms = {}
        for wl in world.wells:
            if wl.is_super:
                arms[id(wl)] = self._arm_angle(wl)
            radius = max(3, int(world.well_radius_px(wl) * cam.zoom))
            extent = max(radius, world.well_range(wl) * k) + 2
            for sx, sy in shifts:
                center = at(wl, sx, sy)
                if visible(center, extent):
                    self._draw_well(world, wl, center, radius)
        self._arms = {key: self._arms[key] for key in arms}
        for sp in world.spawners:
            radius = max(3, int(sp.radius * k))
            for sx, sy in shifts:
                center = at(sp, sx, sy)
                if visible(center, radius):
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
            reach = world.well_range(wl) * self.cam.k
            dots = max(24, int(2 * math.pi * reach / 9))
            for d in range(dots):
                a = 2 * math.pi * d / dots
                pos = (int(center[0] + reach * math.cos(a)), int(center[1] + reach * math.sin(a)))
                pygame.draw.circle(screen, config.SUPER_RANGE_COLOR, pos, 1)
            self._draw_spin_arms(wl, center, radius, self._arms[id(wl)][1])
            pygame.draw.circle(screen, (0, 0, 0), center, radius)
            pygame.draw.circle(screen, config.SUPER_RIM_COLOR, center, radius + 1, 1)
        else:
            self._draw_star_glow(wl, center, radius)
            self._draw_star(screen, wl, center, radius)

    def _draw_star_marks(self, st, center, ring):
        """A star is its particles; on top of them a small dot marks its centre of mass and a faint ring the reach of
        its capture, both in its colour."""
        color = self._star_color(st)
        faint = tuple(int(b + (c - b) * config.STAR_RING_FADE) for b, c in zip(config.BG, color))
        if ring > 3:
            pygame.draw.circle(self.screen, faint, center, ring, 1)
        pygame.draw.circle(self.screen, config.BG, center, 3)
        pygame.draw.circle(self.screen, tuple(c + (255 - c) // 2 for c in color), center, 2)

    def _star_color(self, wl):
        """A star's colour: red-orange when light, through yellow and white to blue-white when very heavy; a
        repulsor glows cold blue."""
        if getattr(wl, "sign", 1) < 0:
            return config.REPULSOR_COLOR
        lo, hi = config.STAR_COLOR_MASS
        t = min(1.0, max(0.0, (math.log10(max(wl.mass, 1.0)) - lo) / (hi - lo))) * (len(config.STAR_COLORS) - 1)
        k = min(int(t), len(config.STAR_COLORS) - 2)
        f = t - k
        a, b = config.STAR_COLORS[k], config.STAR_COLORS[k + 1]
        return tuple(int(a[c] + (b[c] - a[c]) * f) for c in range(3))

    def _draw_star_glow(self, wl, center, radius):
        """A solid well's corona: a soft glow round its body, added onto whatever is behind it."""
        color = self._star_color(wl)
        key = (radius, color)
        glow = self._glows.get(key)
        if glow is None:
            if len(self._glows) > 64:
                self._glows.clear()
            outer = int(radius * config.STAR_GLOW_SIZE) + 6
            glow = pygame.Surface((2 * outer, 2 * outer))
            for r in range(outer, radius - 1, -1):
                k = config.STAR_GLOW * (1.0 - (r - radius) / (outer - radius + 1e-9)) ** 2
                pygame.draw.circle(glow, tuple(int(c * k) for c in color), (outer, outer), r)
            self._glows[key] = glow
        half = glow.get_width() // 2
        self.screen.blit(glow, (center[0] - half, center[1] - half), special_flags=pygame.BLEND_RGB_ADD)

    def _draw_star(self, surf, wl, center, radius):
        """A solid well's glowing body: brightest at the middle and darker towards the edge (limb darkening), with
        spots turning with its spin."""
        color = self._star_color(wl)
        hot = tuple(c + (255 - c) // 2 for c in color)
        edge = tuple(int(c * 0.8) for c in color)
        steps = max(1, min(radius, 10))
        for s in range(steps):                           # from the edge in: darker limb, white-hot middle
            t = s / steps
            col = tuple(int(edge[c] + (color[c] - edge[c]) * min(1.0, 2 * t)) for c in range(3))
            if t > 0.5:
                col = tuple(int(col[c] + (hot[c] - col[c]) * (2 * t - 1)) for c in range(3))
            pygame.draw.circle(surf, col, center, max(1, round(radius * (1.0 - t))))
        if radius >= 5:
            spot = tuple(int(c * 0.6) for c in color)
            for k, (dist, size) in enumerate(((0.55, 0.13), (0.6, 0.09), (0.3, 0.1), (0.72, 0.07))):
                a = wl.phase + k * 2.1
                pos = (center[0] + radius * dist * math.cos(a), center[1] + radius * dist * math.sin(a))
                pygame.draw.circle(surf, spot, pos, max(1, int(radius * size)))

    def _arm_angle(self, wl):
        """The angle to draw a super well's arms at this frame: turned on by as much as the well has turned since the
        last frame (World.whirl_omega each tick) - eased to under SUPER_SPIN_FRAME_MAX when that is more, which
        keeps the faster one spinning still looking faster without seeming to turn backwards."""
        last, angle = self._arms.get(id(wl), (wl.phase, wl.phase))
        cap = config.SUPER_SPIN_FRAME_MAX
        angle += cap * math.tanh((wl.phase - last) / cap)
        self._arms[id(wl)] = (wl.phase, angle)
        return angle

    def _draw_spin_arms(self, wl, center, core, angle):
        """Three spiral arms round a super well's core at angle, trailing like a whirlpool and turning as fast as it
        carries matter round, each tipped with an arrowhead in the direction it turns; brighter the faster it
        spins."""
        way = 1 if wl.spin >= 0 else -1
        outer, inner = core * 3.0 + 16, core * 1.3 + 2
        k = 0.45 + 0.55 * min(1.0, abs(wl.spin))
        color = tuple(int(c * k) for c in config.SUPER_SPIN_COLOR)
        for arm in range(3):
            base = angle + arm * 2 * math.pi / 3
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

    def draw_selection(self, world, body):
        """A bright dashed circle round the selected body."""
        cam = self.cam
        r = max(8, int((world.well_radius_px(body) * cam.zoom if isinstance(body, Well) else body.radius * cam.k) + 6))
        c = tuple(int(v) for v in cam.point(body.x, body.y))
        steps = max(16, int(2 * math.pi * r / 8))
        for d in range(0, steps, 2):
            a0, a1 = 2 * math.pi * d / steps, 2 * math.pi * (d + 1) / steps
            pygame.draw.line(self.screen, (120, 190, 255), (c[0] + r * math.cos(a0), c[1] + r * math.sin(a0)),
                             (c[0] + r * math.cos(a1), c[1] + r * math.sin(a1)), 2)

    def draw_brush(self, tool, pos, radius):
        """The brush circle at the mouse, coloured by what a click will do: pour, erase, or place a body."""
        if tool in ("select", "delete"):
            color = (120, 190, 255) if tool == "select" else (230, 110, 110)
            pygame.draw.circle(self.screen, color, pos, 6, 1)
            return
        color = {"erase": (150, 80, 80), "star": (230, 150, 80), "repulsor": config.REPULSOR_COLOR,
                 "super": config.SUPER_RANGE_COLOR, "spawner": config.SPAWNER_COLOR,
                 "locked": config.SPAWNER_COLOR}.get(tool, (70, 76, 90))
        pygame.draw.circle(self.screen, color, pos, radius, 1)

    def draw_status(self, world, app, fps):
        """Always in the top-left corner: how many particles there are, how many ticks run per second, and the frame
        rate (and the zoom, when not 1x)."""
        rate = 0.0 if app.paused else fps * app.ticks_per_frame
        text = f"particles {world.particle_count():,}   tick rate {rate:,.0f}/s   {fps:.0f} fps"
        if self.cam.zoom != 1.0:
            text += f"   zoom {self.cam.zoom:.2f}x"
        if app.paused:
            text += "   PAUSED"
        surf = self.font.render(text, True, config.FG)
        bg = pygame.Surface((surf.get_width() + 16, surf.get_height() + 10), pygame.SRCALPHA)
        bg.fill((*config.BG, 190))
        self.screen.blit(bg, (8, 8))
        self.screen.blit(surf, (16, 13))

    def draw_usage(self, world, usage, right=None):
        """Always shown: in the top-right corner, ending at x = right, or (right None: the menu is open there) under
        the status line. CPU use (the machine's, and the simulation's share of all its cores), GPU use (the busiest
        engine, every process) and all the mass in the universe."""
        def pct(v, none="..."):
            return none if v is None else f"{v:.0f}%"
        cpu = f"CPU {pct(usage.cpu)}" + (f" (sim {pct(usage.sim)})" if usage.sim is not None else "")
        gpu = f"GPU {pct(usage.gpu, usage.gpu_note)}"
        text = f"{cpu}   {gpu}   mass {world.universe_mass():,}"
        surf = self.font.render(text, True, config.FG)
        bg = pygame.Surface((surf.get_width() + 16, surf.get_height() + 10), pygame.SRCALPHA)
        bg.fill((*config.BG, 190))
        x, y = (8, 40) if right is None else (right - bg.get_width(), 8)
        self.screen.blit(bg, (x, y))
        self.screen.blit(surf, (x + 8, y + 5))

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
        self.screen.blit(panel, (10, 40))

    def draw_body_inspector(self, world, body, pos):
        if isinstance(body, Star):
            return self.draw_star_inspector(world, body, pos)
        if isinstance(body, Well):
            return self.draw_well_inspector(world, body, pos)
        lines = [
            (f"{'locked ' if body.locked else ''}spawner   {body.rate * config.FPS:,.0f} particles/s"
             f"   mass {pour_label(body.masses)}", config.FG),
            (f"cell ({body.x:.0f}, {body.y:.0f})   v ({body.vx:+.2f}, {body.vy:+.2f})", config.FG),
        ]
        self.panel(lines, (pos[0] + 16, pos[1] + 16), self.small)

    def draw_star_inspector(self, world, st, pos):
        hold = st.smooth / st.peak if st.peak > 0 else 1.0
        lines = [
            (f"star   mass {st.mass:,.0f} in {st.count:,} particles   cell ({st.x:.0f}, {st.y:.0f})", config.FG),
            (f"v ({st.vx:+.3f}, {st.vy:+.3f})   radius {st.radius:.1f}   capture ring {st.ring:.1f} cells", config.FG),
            (f"holds {hold:.0%} of the most it held lately (unstable below {config.STAR_UNSTABLE_SHARE:.0%})"
             f"   spin {abs(st.omega) * config.FPS:.2f} rad/s"
             + (f"   tide from a {'super well' if isinstance(st.tide, Well) else 'star'}" if st.tide else ""),
             config.DIM),
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
