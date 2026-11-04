"""A small immediate-mode widget kit for the control menu (sv/menu.py).

Each frame the menu lays its rows out from the top of the panel down, and every widget call draws itself and returns
its value, changed if it was clicked or dragged. Mouse events reach the kit first (UI.handle): a click on the menu
never reaches the universe underneath it.
"""

import math

import pygame

from . import config

PANEL_W = 380                 # px
PAD = 12
ROW_H = 26
BUTTON = 44                   # the hamburger button
MARGIN = 12
INFO_W = 300                  # an explanation's width
KNOB = 7
ARROW = 18                    # a slider's nudge arrows
REPEAT_DELAY = 400            # ms an arrow is held before it repeats
REPEAT_EVERY = 70             # ms between repeats

PANEL_BG = (24, 27, 34, 238)
EDGE = (62, 68, 82)
HEADER = (36, 40, 51)
CHIP = (44, 49, 62)
ACCENT = (96, 170, 255)
ON = (78, 196, 122)
OFF = (66, 72, 86)
TEXT = config.FG
DIM = config.DIM
DARK = (16, 18, 23)


def parse_number(text):
    """A typed number: digits with an optional k / M (thousands / millions) after them, commas and spaces ignored
    ("2.5M", "300k", "1,500,000"). None if it isn't one."""
    t = text.replace(",", "").replace(" ", "").lower()
    scale = {"k": 1e3, "m": 1e6}.get(t[-1:], 1.0)
    if scale != 1.0:
        t = t[:-1]
    try:
        v = float(t) * scale
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def wrap(font, text, width):
    """Lines of text no wider than width (px)."""
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}" if line else word
            if line and font.size(trial)[0] > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


class UI:
    def __init__(self, screen):
        self.screen = screen
        self.font = pygame.font.Font(None, 20)
        self.small = pygame.font.Font(None, 17)
        self.title = pygame.font.Font(None, 22)
        self._text = {}
        self.open = False             # the menu is expanded
        self.sections = {}            # section key -> expanded
        self.click = None             # where the left button went down this frame, until a widget takes it
        self.active = None            # the slider being dragged, or (key, -1 / +1) for an arrow held down
        self._repeat_at = 0           # when a held arrow next repeats (ms)
        self.info = None              # (key, title, text) of the explanation on show
        self.info_y = 0
        self.info_rect = None
        self.scroll = 0
        self.content_h = 0
        self.panel = None             # the panel as last drawn (None while the menu is closed)
        self.editing = None           # (key, text typed so far) of the number box being typed in
        self.typed = None             # (key, number) just entered in a number box, until the box takes it
        self._edit_seen = False       # the box being typed in was laid out this frame
        self.x = self.w = self.y = self.y0 = 0
        self._bg = None

    # --- input ------------------------------------------------------------------------------------

    def button_rect(self):
        sw, sh = self.screen.get_size()
        return pygame.Rect(sw - MARGIN - BUTTON, sh - MARGIN - BUTTON, BUTTON, BUTTON)

    def over(self, pos):
        """Whether pos is on the menu: its button, its panel or an explanation."""
        return any(r is not None and r.collidepoint(pos) for r in (self.button_rect(), self.panel, self.info_rect))

    def captures(self, pos):
        """Whether the mouse at pos belongs to the menu this frame (over it, or dragging one of its sliders)."""
        return self.active is not None or self.over(pos)

    def handle(self, e):
        """Take a mouse event if it is the menu's. Returns True if it was."""
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            typing = self.editing is not None
            self._commit()                               # a click anywhere enters what was typed...
            if self.over(e.pos):
                self.click = e.pos
                return True
            if typing or self.info is not None:          # ...and one off the menu does only that, or closes an
                self.info = self.info_rect = None        #   explanation
                return True
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.active = None
        elif e.type == pygame.MOUSEWHEEL and self.panel is not None and self.panel.collidepoint(pygame.mouse.get_pos()):
            self.scroll -= e.y * 40
            return True
        return False

    def handle_key(self, e):
        """Take a key press while a number box is being typed in: it takes them all, so no shortcut fires. Enter
        enters the number, Esc backs out. Returns True if it took the key."""
        if self.editing is None:
            return False
        key, text = self.editing
        if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit()
        elif e.key == pygame.K_ESCAPE:
            self.editing = None
        elif e.key == pygame.K_BACKSPACE:
            self.editing = (key, text[:-1])
        elif e.unicode and e.unicode in "0123456789.,kKmM" and len(text) < 14:
            self.editing = (key, text + e.unicode)
        return True

    def _commit(self):
        """Enter what was typed in the number box being typed in (nothing if it isn't a number), and stop typing."""
        if self.editing is not None:
            key, text = self.editing
            v = parse_number(text)
            if v is not None:
                self.typed = (key, v)
            self.editing = None

    def take_click(self, rect, clip=True):
        """Whether this frame's click landed on rect (inside the visible panel, if clip); it is used up if so."""
        if self.click is None or not rect.collidepoint(self.click):
            return False
        if clip and (self.panel is None or not self.panel.collidepoint(self.click)):
            return False
        self.click = None
        return True

    # --- drawing helpers --------------------------------------------------------------------------

    def text(self, s, x, y, color=TEXT, font=None, right=False):
        """Draw s at (x, y) (its right end at x if right). Returns its width."""
        font = font or self.font
        key = (s, color, id(font))
        surf = self._text.get(key)
        if surf is None:
            if len(self._text) > 800:
                self._text.clear()
            surf = self._text[key] = font.render(s, True, color)
        self.screen.blit(surf, (x - surf.get_width() if right else x, y))
        return surf.get_width()

    def _row(self, h):
        y = self.y
        self.y += h
        return y

    def _visible(self, y, h):
        return self.panel is not None and y + h >= self.panel.top and y <= self.panel.bottom

    def _info_button(self, key, title, info, y, h):
        """The little (i) at the right of a row: click it to read what the row does."""
        if not info:
            return
        c = (self.x + self.w - 8, y + h // 2)
        shown = self.info is not None and self.info[0] == key
        pygame.draw.circle(self.screen, ACCENT if shown else CHIP, c, 8)
        pygame.draw.circle(self.screen, ACCENT, c, 8, 1)
        self.text("i", c[0] - 2, c[1] - 6, DARK if shown else ACCENT, self.small)
        if self.take_click(pygame.Rect(c[0] - 10, c[1] - 10, 20, 20)):
            self.info = None if shown else (key, title, info)
            self.info_y = y

    def _chip(self, rect, label, selected, font=None, color=None):
        pygame.draw.rect(self.screen, color or (ACCENT if selected else CHIP), rect, border_radius=5)
        if not selected and color is None:
            pygame.draw.rect(self.screen, EDGE, rect, 1, border_radius=5)
        font = font or self.small
        tw, th = font.size(label)
        self.text(label, rect.centerx - tw // 2, rect.centery - th // 2 + 1, DARK if selected else TEXT, font)

    # --- the menu button and panel ------------------------------------------------------------------

    def hamburger(self, badge=None):
        """The menu button in the bottom-right corner: three bars, a cross while open. badge: a word to show
        beside it (like PAUSED)."""
        r = self.button_rect()
        hover = r.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(self.screen, HEADER if hover or self.open else (30, 34, 43), r, border_radius=8)
        pygame.draw.rect(self.screen, ACCENT if self.open else EDGE, r, 1, border_radius=8)
        cx, cy = r.center
        if self.open:
            for s in (1, -1):
                pygame.draw.line(self.screen, TEXT, (cx - 9, cy - 9 * s), (cx + 9, cy + 9 * s), 3)
        else:
            for dy in (-8, 0, 8):
                pygame.draw.line(self.screen, TEXT, (cx - 11, cy + dy), (cx + 11, cy + dy), 3)
        if badge:
            tw, th = self.small.size(badge)
            b = pygame.Rect(r.left - tw - 26, r.centery - 12, tw + 16, 24)
            pygame.draw.rect(self.screen, (30, 34, 43), b, border_radius=12)
            pygame.draw.rect(self.screen, EDGE, b, 1, border_radius=12)
            self.text(badge, b.x + 8, b.centery - th // 2 + 1, TEXT, self.small)
        if self.take_click(r, clip=False):
            self.open = not self.open
            if not self.open:
                self.info = self.info_rect = None

    def begin(self):
        """Start laying out the panel, above the menu button."""
        sw, sh = self.screen.get_size()
        bottom = sh - MARGIN - BUTTON - 8
        avail = bottom - MARGIN
        h = min(self.content_h or avail, avail)
        self.scroll = min(max(self.scroll, 0), max(0, self.content_h - h))
        self.panel = pygame.Rect(sw - MARGIN - PANEL_W, bottom - h, PANEL_W, h)
        if self._bg is None or self._bg.get_size() != self.panel.size:
            self._bg = pygame.Surface(self.panel.size, pygame.SRCALPHA)
            self._bg.fill(PANEL_BG)
        self.screen.blit(self._bg, self.panel.topleft)
        self.screen.set_clip(self.panel)
        self.x, self.w = self.panel.x + PAD, PANEL_W - 2 * PAD - (8 if self.content_h > h else 0)
        self.y = self.y0 = self.panel.y + PAD - self.scroll

    def end(self):
        """Finish the panel: its frame, a scroll bar if it doesn't all fit, and the explanation on show."""
        self.content_h = self.y - self.y0 + PAD
        self.screen.set_clip(None)
        p = self.panel
        pygame.draw.rect(self.screen, EDGE, p, 1, border_radius=6)
        if self.content_h > p.height:
            bar = max(30, p.height * p.height // self.content_h)
            top = p.y + (p.height - bar) * self.scroll // max(1, self.content_h - p.height)
            pygame.draw.rect(self.screen, OFF, (p.right - 7, top, 4, bar), border_radius=2)
        self._draw_info()
        if self.click is not None and p.collidepoint(self.click):
            self.click = None                            # a click on empty panel does nothing
        if not self._edit_seen:                          # its box is gone (another tool, a folded section)
            self.editing = None
        self._edit_seen = False
        self.typed = None
        self._let_go()

    def _let_go(self):
        """Drop a held slider or arrow once the button is up. Its release can come in the same frame's events as the
        click (when frames are slow), before the widget has taken the click and started holding, so the release
        alone can't end the hold; the click still counts once."""
        if self.active is not None and not pygame.mouse.get_pressed()[0]:
            self.active = None

    def closed(self):
        """The menu is closed this frame: nothing of it but the button takes the mouse."""
        self.panel = self.info_rect = None
        self.info = None
        self.click = None
        self.editing = self.typed = None
        self._let_go()

    def _draw_info(self):
        self.info_rect = None
        if self.info is None:
            return
        _, title, text = self.info
        lines = wrap(self.small, text, INFO_W - 24)
        line_h = self.small.get_linesize()
        h = 36 + line_h * len(lines)
        sw, sh = self.screen.get_size()
        y = min(max(self.info_y, MARGIN), sh - MARGIN - h)
        r = pygame.Rect(self.panel.x - INFO_W - 8, y, INFO_W, h)
        pygame.draw.rect(self.screen, (32, 37, 49), r, border_radius=6)
        pygame.draw.rect(self.screen, ACCENT, r, 1, border_radius=6)
        self.text(title, r.x + 12, r.y + 10, TEXT, self.title)
        for k, line in enumerate(lines):
            self.text(line, r.x + 12, r.y + 30 + k * line_h, TEXT, self.small)
        self.info_rect = r

    # --- widgets ----------------------------------------------------------------------------------

    def section(self, key, title, default=True, level=0, info=None):
        """A header that folds the rows under it away (with an (i) if info is given). Returns whether it is
        open."""
        is_open = self.sections.setdefault(key, default)
        h = 30 if level == 0 else 24
        y = self._row(h + (6 if level == 0 else 4))
        if level == 0:
            r = pygame.Rect(self.panel.x + 4, y, PANEL_W - 8, h)
            pygame.draw.rect(self.screen, HEADER, r, border_radius=5)
        else:
            r = pygame.Rect(self.x, y, self.w, h)
            pygame.draw.line(self.screen, EDGE, (r.x, r.bottom - 2), (r.right, r.bottom - 2))
        cx, cy = r.x + (12 if level == 0 else 6), r.centery
        tri = ([(cx - 4, cy - 3), (cx + 4, cy - 3), (cx, cy + 3)] if is_open
               else [(cx - 2, cy - 5), (cx + 3, cy), (cx - 2, cy + 5)])
        pygame.draw.polygon(self.screen, ACCENT, tri)
        font = self.title if level == 0 else self.font
        self.text(title, cx + 12, cy - font.get_height() // 2 + 1, TEXT, font)
        self._info_button(key, title, info, y, h)
        if self.take_click(r):
            self.sections[key] = is_open = not is_open
        return is_open

    def toggle(self, key, label, value, info=None, note=None):
        """An ON / OFF switch; clicking anywhere on its row flips it. Returns the value."""
        y = self._row(ROW_H + 2)
        if not self._visible(y, ROW_H):
            return value
        tx = self.x + self.text(label, self.x, y + 5)
        if note:
            self.text(note, tx + 8, y + 7, DIM, self.small)
        sw = pygame.Rect(self.x + self.w - 22 - 46, y + 3, 46, 20)
        pygame.draw.rect(self.screen, ON if value else OFF, sw, border_radius=10)
        knob = (sw.right - 10 if value else sw.x + 10, sw.centery)
        pygame.draw.circle(self.screen, TEXT, knob, 7)
        self.text("ON" if value else "OFF", sw.x + 6 if value else sw.right - 25, sw.y + 4,
                  DARK if value else DIM, self.small)
        self._info_button(key, label, info, y, ROW_H)
        if self.take_click(pygame.Rect(self.x, y, self.w - 22, ROW_H)):
            value = not value
        return value

    def slider(self, key, label, value, lo, hi, info=None, fmt="{:.2f}", log=False, integer=False, note=None,
               step=None):
        """A draggable slider from lo to hi (spaced by ratio if log). fmt formats the value shown: a format string or
        a function. With a step, arrows beside the value nudge it down / up to the next multiple of step (held, they
        repeat). Returns the value."""
        show = fmt if callable(fmt) else fmt.format
        h = 42
        y = self._row(h + 2)
        track = pygame.Rect(self.x + 6, y + 28, self.w - 22 - 12, 4)
        arrows = None
        if step:
            slot = max(self.font.size(show(v))[0] for v in (lo, hi))
            up = pygame.Rect(self.x + self.w - 22 - 4 - ARROW, y + 1, ARROW, 18)
            down = pygame.Rect(up.x - 6 - slot - 6 - ARROW, y + 1, ARROW, 18)
            arrows = ((down, -1), (up, 1))
            for r, way in arrows:
                if self.take_click(r):
                    self.active = (key, way)
                    self._repeat_at = pygame.time.get_ticks() + REPEAT_DELAY
                    value = self._nudge(value, way, step, lo, hi, integer)
            if self.active == (key, -1) or self.active == (key, 1):
                now = pygame.time.get_ticks()
                if now >= self._repeat_at:
                    self._repeat_at = now + REPEAT_EVERY
                    value = self._nudge(value, self.active[1], step, lo, hi, integer)

        def to_t(v):
            if log:
                return (math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo))
            return (v - lo) / (hi - lo)

        if self.take_click(pygame.Rect(self.x, y + 18, self.w - 22, 22)):
            self.active = key
        if self.active == key:
            t = min(max((pygame.mouse.get_pos()[0] - track.x) / track.width, 0.0), 1.0)
            value = math.exp(math.log(lo) + t * (math.log(hi) - math.log(lo))) if log else lo + t * (hi - lo)
            if integer:
                value = int(round(value))
        if not self._visible(y, h):
            return value
        tx = self.x + self.text(label, self.x, y + 3)
        if note:
            self.text(note, tx + 8, y + 5, DIM, self.small)
        if arrows:
            self.text(show(value), arrows[1][0].x - 6, y + 3, ACCENT, right=True)
            for r, way in arrows:
                held = self.active == (key, way)
                at_end = value <= lo if way < 0 else value >= hi
                pygame.draw.rect(self.screen, ACCENT if held else CHIP, r, border_radius=4)
                pygame.draw.rect(self.screen, EDGE, r, 1, border_radius=4)
                col = DARK if held else (DIM if at_end else TEXT)
                cx, cy = r.centerx, r.centery
                pygame.draw.polygon(self.screen, col, [(cx + 3 * way, cy), (cx - 3 * way, cy - 5),
                                                       (cx - 3 * way, cy + 5)])
        else:
            self.text(show(value), self.x + self.w - 26, y + 3, ACCENT, right=True)
        t = min(max(to_t(value), 0.0), 1.0)
        kx = track.x + int(t * track.width)
        pygame.draw.rect(self.screen, OFF, track, border_radius=2)
        pygame.draw.rect(self.screen, ACCENT, (track.x, track.y, kx - track.x, track.height), border_radius=2)
        pygame.draw.circle(self.screen, TEXT if self.active == key else (220, 226, 236), (kx, track.centery), KNOB)
        pygame.draw.circle(self.screen, ACCENT, (kx, track.centery), KNOB, 2)
        self._info_button(key, label, info, y, 22)
        return value

    @staticmethod
    def _nudge(value, way, step, lo, hi, integer):
        """value moved one step down (way -1) or up (+1), onto the step grid, kept in [lo, hi]."""
        k = value / step
        k = math.floor(k + 1e-6) + 1 if way > 0 else math.ceil(k - 1e-6) - 1
        value = min(max(round(k * step, 6), lo), hi)
        return int(round(value)) if integer else value

    def number_field(self, key, label, value, lo, hi, info=None, fmt=str, note=None):
        """A number you can type: click the box, type it (k / M for thousands / millions, see parse_number), Enter or
        a click elsewhere to set it, Esc to back out. fmt formats the value shown. Returns the value (a typed one
        kept in [lo, hi])."""
        if self.typed is not None and self.typed[0] == key:
            value = min(max(self.typed[1], lo), hi)
            self.typed = None
        y = self._row(ROW_H + 2)
        box = pygame.Rect(self.x + self.w - 22 - 120, y + 2, 120, ROW_H - 4)
        if self.take_click(box):
            self.editing = (key, "")
        editing = self.editing is not None and self.editing[0] == key
        self._edit_seen |= editing
        if not self._visible(y, ROW_H):
            return value
        tx = self.x + self.text(label, self.x, y + 5)
        if note:
            self.text(note, tx + 8, y + 7, DIM, self.small)
        pygame.draw.rect(self.screen, DARK, box, border_radius=4)
        pygame.draw.rect(self.screen, ACCENT if editing else EDGE, box, 1, border_radius=4)
        if editing:
            text = self.editing[1]
            caret = "|" if pygame.time.get_ticks() // 500 % 2 == 0 else ""
            if text:
                self.text(text + caret, box.x + 8, box.y + 4)
            else:
                self.text(caret + "e.g. 2.5M, 300k", box.x + 8, box.y + 5, DIM, self.small)
        else:
            self.text(fmt(value), box.right - 8, box.y + 4, ACCENT, right=True)
            self.text("type", box.x + 6, box.y + 5, DIM, self.small)
        self._info_button(key, label, info, y, ROW_H)
        return value

    def choice(self, key, label, options, value, info=None, columns=None):
        """Buttons for one of several options, the chosen one lit. options: (value, text) pairs. columns: lay them
        out in that many equal columns (else as many as fit). Returns the value."""
        y0 = self.y
        if label:
            y = self._row(22)
            if self._visible(y, 22):
                self.text(label, self.x, y + 3)
                self._info_button(key, label, info, y, 20)
        picked = self._chips(key, options, lambda v: v == value, columns, info if not label else None, label)
        return value if picked is None else picked

    def buttons(self, key, items, info=None, title=None, columns=None):
        """A row of push buttons: items are (value, text) or (value, text, lit). Returns the value clicked, or
        None."""
        opts = [(it[0], it[1]) for it in items]
        lit = {it[0] for it in items if len(it) > 2 and it[2]}
        return self._chips(key, opts, lambda v: v in lit, columns, info, title or "")

    def _chips(self, key, options, selected, columns, info, title):
        width = self.w - (22 if info else 0)
        gap, h = 6, 24
        if columns:
            cw = (width - gap * (columns - 1)) / columns
            rows = [options[k:k + columns] for k in range(0, len(options), columns)]
            widths = [[cw] * len(r) for r in rows]
        else:
            rows, widths, cur, cur_w, used = [], [], [], [], 0
            for opt in options:
                bw = self.small.size(opt[1])[0] + 18
                if cur and used + gap + bw > width:
                    rows.append(cur)
                    widths.append(cur_w)
                    cur, cur_w, used = [], [], 0
                cur.append(opt)
                cur_w.append(bw)
                used += (gap if len(cur) > 1 else 0) + bw
            if cur:
                rows.append(cur)
                widths.append(cur_w)
        picked = None
        for n, (row, ws) in enumerate(zip(rows, widths)):
            y = self._row(h + gap)
            x = self.x
            for (val, text), bw in zip(row, ws):
                r = pygame.Rect(int(x), y, int(bw), h)
                if self._visible(y, h):
                    self._chip(r, text, selected(val))
                if self.take_click(r):
                    picked = val
                x += bw + gap
            if n == 0 and self._visible(y, h):
                self._info_button(key, title, info, y, h)
        return picked

    def direction_pad(self, key, label, value, directions, info=None, note=None):
        """A 3 x 3 pad of arrows for a direction (an index into directions, (dx, dy) on screen), the middle one
        for none. Returns the value."""
        size, gap = 28, 4
        h = 3 * size + 2 * gap
        y = self._row(h + 6)
        px = self.x + self.w - 22 - 3 * size - 2 * gap - 8
        if self._visible(y, h):
            self.text(label, self.x, y + 3)
            if note:
                for k, line in enumerate(wrap(self.small, note, px - self.x - 10)):
                    self.text(line, self.x, y + 24 + k * self.small.get_linesize(), DIM, self.small)
            self._info_button(key, label, info, y, 20)
        picked = value
        for gy in (-1, 0, 1):
            for gx in (-1, 0, 1):
                d = None if gx == gy == 0 else directions.index((gx, gy))
                r = pygame.Rect(px + (gx + 1) * (size + gap), y + (gy + 1) * (size + gap), size, size)
                lit = d == value
                if self._visible(y, h):
                    pygame.draw.rect(self.screen, ACCENT if lit else CHIP, r, border_radius=5)
                    pygame.draw.rect(self.screen, EDGE, r, 1, border_radius=5)
                    col = DARK if lit else TEXT
                    if d is None:
                        self.text("off", r.centerx - 8, r.centery - 6, col, self.small)
                    else:
                        n = math.hypot(gx, gy)
                        ux, uy = gx / n, gy / n
                        tip = (r.centerx + ux * 8, r.centery + uy * 8)
                        pygame.draw.line(self.screen, col, (r.centerx - ux * 7, r.centery - uy * 7), tip, 2)
                        for side in (2.5, -2.5):
                            a = math.atan2(uy, ux) + math.pi + side / 4.5
                            pygame.draw.line(self.screen, col, tip, (tip[0] + 6 * math.cos(a), tip[1] + 6 * math.sin(a)), 2)
                if self.take_click(r):
                    picked = d
        return picked

    def stats(self, items):
        """Read-only figures: (label, value) pairs, flowing onto as many lines as they need."""
        line_h, gap = 18, 14
        x, lines = 0, [[]]
        for label, value in items:
            wv = self.small.size(label)[0] + 4 + self.small.size(value)[0]
            if lines[-1] and x + gap + wv > self.w:
                lines.append([])
                x = 0
            x += (gap if lines[-1] else 0) + wv
            lines[-1].append((label, value))
        y = self._row(line_h * len(lines) + 4)
        if not self._visible(y, line_h * len(lines)):
            return
        for k, line in enumerate(lines):
            x = self.x
            for label, value in line:
                x += self.text(label, x, y + k * line_h, DIM, self.small) + 4
                x += self.text(value, x, y + k * line_h, TEXT, self.small) + gap

    def note(self, text, color=DIM):
        """A line or two of small explanatory text."""
        lines = wrap(self.small, text, self.w)
        line_h = self.small.get_linesize()
        y = self._row(line_h * len(lines) + 4)
        if self._visible(y, line_h * len(lines)):
            for k, line in enumerate(lines):
                self.text(line, self.x, y + k * line_h, color, self.small)

    def gap(self, h=6):
        self._row(h)
