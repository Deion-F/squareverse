"""The control menu: everything you can set, and every figure the simulation reports, beside the control it belongs
to. It opens from the button in the bottom-right corner; the rarely needed controls fold away under Advanced. Each
row's (i) explains it."""

import math

from . import config
from .presets import PRESETS
from .render import mass_label
from .world import DIRS, VIEW_MODES, Spawner, Star, Well

# the mouse tools: what a left click on the universe does
TOOLS = [("pour", "Pour"), ("ghosts", "Ghosts"), ("erase", "Erase"), ("star", "Star"), ("auto", "Auto star"),
         ("repulsor", "Repulsor"),
         ("super", "Super well"), ("spawner", "Spawner"), ("locked", "Locked spawner"), ("select", "Select / move"),
         ("delete", "Delete")]
POUR_OPTIONS = ([(m, str(m)) for m in config.POUR_MASSES] + [(tuple(config.RANDOM_MASS), "Random")]     # 6 a row:
                + [(m, str(m)) for m in config.HEAVY_POUR_MASSES] + [(tuple(config.RANDOM_HEAVY_MASS), "Rnd heavy")])
WARN = (235, 190, 90)                            # a note that what the tool places won't last as it is
DANGER = config.ORBIT_BAND_NONE_COLOR            # ...that it collapses into a super well at once
REACH_MIN, REACH_MAX = 10, 400                   # the Reach slider (cells); at its top end gravity reaches everywhere

INFO = {
    "pause": "Stops the simulation; Step then advances it one tick at a time. Clear empties the universe of particles "
             "and stars (wells and spawners stay). Keys: space, N, C.",
    "speed": "How many simulation ticks run per frame of the display. More is faster, but each frame takes longer to "
             "draw, so the frame rate drops in big scenes. The step time is what one tick costs. Keys: + / -.",
    "presets": "Starting scenes. Rain: mixed masses falling under gravity. Disk: a self-gravitating dust disk turning "
               "with the global rotation in a round universe, which forms stars. Cloud: a turning cloud that "
               "clumps. Binary: two stars orbiting each other inside a ring. Systems: a black hole in the middle "
               "orbited by three stars, and a few more round it with a star or two each. Supernova: one black hole "
               "half again as heavy as goes supernova, alone in the middle. Empty: nothing. Keys: F1-F6.",
    "tool": "What a left click on the universe does. Pour / Ghosts / Erase work while you hold the button down; the "
            "others act once per click. Under the tool are only its own settings, and the cursor shows what a click "
            "places - its size, with a label saying what it is and how heavy - turning red when it would collapse "
            "into a super well at once. Ghosts are particles that pass through everything for "
            f"{config.GHOST_TICKS} ticks, then land. A star is a ball of particles held together by its own gravity; "
            "Auto star puts a star in a stable orbit round the super well clicked near, choosing its size, density, "
            "orbit and spot itself (up to three evenly spaced on one orbit; the green band shows where, a red "
            "note when there's no room); "
            "a repulsor pushes everything away; a super well (black hole) swallows what touches its core; a "
            "spawner pours particles (a locked one stays put). Select / move: click a body to see and change it, "
            "drag it to move it. Right click always erases; shift+click pours ghosts (with the Star tool, places a "
            "ghost star) or drags a body. Keys: G, "
            "shift+G, B, F, shift+F, X.",
    "brush": "The radius of the brush circle: where particles are poured or erased, and how big a placed star or "
             "spawner is. The mouse wheel changes it too.",
    "pour": "The mass of each poured particle (heavier ones sink through lighter ones and pull harder), or a random "
            "rung from {} to {} each (masses come in rungs: 1, 2, 4, 8, ...). A placed star fills its circle with a core of particles of this mass, "
            "its outer layers lighter in proportion (3/8, then 1/8 of it), so this sets what it is made of and how "
            "heavy it is. The second row is heavy matter (up to the heaviest a particle can be), for dense stars "
            "that hold together near big super wells. Packed densely enough, heavy matter collapses into a super "
            "well: with Pour, the cursor turns red when filling the brush there would do that. Keys: 1-6, shift+1-4 "
            "and shift+6 for the second row.".format(*config.RANDOM_MASS),
    "star_mass": "What the star weighs in all: its radius and particle mass set it, and typing a mass here sizes it "
                 "for you (as near as the particle mass allows; it grows with its area). Pick a heavier particle "
                 "mass for a small, dense star, a lighter one for a big, loose one.",
    "super_mass": "What the super well weighs, in steps of {} or typed (k / M for thousands / millions: 2.5M, "
                  "750k). Its core - the black disc that swallows what touches it - follows, and the cursor shows "
                  "it with its point of no return (dotted) and its whirlpool's range (faint) as they will be. min is "
                  "the lightest there can be: what dense matter collapses into, lower when gravity is stronger. At "
                  "the supernova mass (Stars and black holes) or over, it explodes moments after it is placed. The "
                  "mouse wheel steps it too. Key: B places one at the mouse.".format(
                      mass_label(config.SUPER_PLACE_STEP)),
    "super_size": "The radius of the super well's core - its horizon, where the speed it takes to get away reaches the "
                  "speed of light (faster than matter's speed limit: matter can't get away from further out, the dotted "
                  "point of no return). It grows with its mass (in proportion, until gravity's reach caps it), so the mass "
                  "changes to what that horizon takes: dragging this is the other way to set the same thing.",
    "repulsor_mass": "What the repulsor weighs: how hard it pushes. A repulsor is a solid body of fixed density, so "
                     "its size follows its mass (and the other way round below). Type one in (k / M for thousands "
                     "/ millions) or pick one. Key: shift+G places one at the mouse.",
    "repulsor_size": "The repulsor's radius. It has a fixed density, so its mass changes to what that size weighs. "
                     "The mouse wheel changes it too.",
    "gdir": "Uniform gravity pulling everything one way, like the ground in a sand game; off for space scenes. Keys: "
            "arrows, Q / E to turn it, 0 for off.",
    "strength": "Scales all gravity: the direction above, stars, wells, super wells and self-gravity. Stronger "
                "gravity also lowers the mass at which dense matter collapses into a super well. Keys: < / >.",
    "reach": "How far gravity reaches, in cells. Every pull - stars, wells, super wells, self-gravity - is at full "
             "strength out to this distance, then fades to nothing at twice it, so things must come near each other "
             "to interact and bodies further apart don't feel each other at all. Orbits within it are stable, beyond "
             "about 1.16x it they aren't. It also limits super wells' spinning ranges (to half of it across) and "
             "stars' capture rings. All the way to the right, gravity reaches everywhere (plain inverse-square).",
    "sg": "Particles pull each other (computed on a coarse mesh every few ticks), so clouds clump and disks form "
          "arms. Stars always pull and are pulled, whether this is on or not. Key: S.",
    "orbit": "Turns the whole universe round its centre like a galaxy: everything is carried round at the same "
             "angular speed, never coming to rest. New super wells spin the same way. Key: O.",
    "orbit_speed": "How fast the global rotation carries things at the edge of the window - half its shorter side "
                   "out from the centre - in cells per tick; everything turns at the same angular speed, so further "
                   "out (off-screen, in a round universe) it is faster. Keys: K / L.",
    "shape": "Window: the universe is the window's rectangle, with walls (or wrapping borders) at its edges. Round: "
             "it is a disc centred on the window that reaches past the window's corners, so anything the global "
             "rotation carries off one edge of the window carries on round its circle out of sight and comes back "
             "in on the far side, as if the universe really turned. Its edge is a rim turning with the rotation. "
             "It has about twice as many cells to simulate. The space presets are round, Rain is the window. Key: U.",
    "wrap": "Leaving one side of the universe enters from the opposite one, and gravity reaches across the seam, so "
            "there are no walls. Only for the window's rectangle: turning it on makes a round universe the "
            "window again. Key: W.",
    "zoom": "Zoom the camera out to see the whole universe (what has left the window, in a round one) or in for a "
            "closer look; the squares keep their size in the simulation. Ctrl+wheel or Z / shift+Z zoom at the "
            "mouse, middle drag or alt+drag pans, R goes back to 1x, shift+R fits the whole universe.",
    "stars": "Stars are balls of particles held together by their own gravity, whose weight fuses their core. "
             "Touching gently they merge; crashing they splash matter out of the contact; one no longer bound "
             "comes apart, and one whose core has burned up to the heaviest fuel explodes.",
    "formation": "Several times a second, dense round knots of matter that hold themselves together and whose own "
                 "weight lights fusion in their core become stars. Off: only stars you place appear.",
    "collapse": "Matter so dense that even moving at the speed limit nothing could get away from it - the mass within "
                "some distance is enough that the speed it takes to escape reaches the limit there - collapses into a "
                "super well, a black hole holding all of it, with its momentum and spin. Stars and loose matter alike: "
                "nothing but gravity's strength and reach and the speed limit decide it, so only heavy matter packed "
                "tight does (light matter never, however much piles up, at a short reach). A super well's core is "
                "that horizon: whatever crosses it is swallowed. The note is the lightest super well there can be. "
                "With the Star or Pour tool, the cursor turns amber near that and red when what it places would "
                "collapse at once. A super well reaching the supernova mass (below) explodes. Key: shift+B.",
    "explode": "How heavy a super well gets before it goes supernova: all its mass blasts out as a ring of heavy "
               "debris that cools and lands as particles. Higher lets super wells grow bigger and hold more of the "
               "universe before they blow; lower makes supernovae more frequent. A well already over a lowered "
               "limit explodes after a short grace. Spin rising with mass reaches its top at this mass.",
    "radiation": "Hot matter radiates from its surface: heat particles (pale blue) of one unit of mass's worth of "
                 "energy each, flying at the speed of light, the matter recoiling. Super wells orbiting each other "
                 "lose energy to gravitational waves - the closer and heavier, the faster (P ~ m1^2 m2^2 (m1 + m2) / "
                 "d^5) - so they spiral in and merge, sending the waves out in two beams along the line through them, "
                 "then a burst as they merge that fades as the merged core settles. Radiation and waves are energy "
                 "only - they never land as matter: the first particle they meet takes them in as heat (and a push), "
                 "and a super well that swallows them gains their mass.",
    "show_radiation": "Draw the radiation particles (pale blue). Off, they are only hidden: they still fly, push, "
                      "heat and are taken in exactly as before. Saves a little drawing time when there is a lot of it.",
    "recycle": "Radiation reaching the universe's edge comes back in from a random point of it, heading inwards, so "
               "the universe keeps all its energy. Off, it is gone for good (the note counts how much). Turn it off "
               "if radiation builds up faster than matter takes it in.",
    "merge": "Fusion. Masses come in rungs - 1, 2, 4, 8, ... up to {:,} - and two particles of the same rung can "
             "fuse into the next one up. Whether they do depends on the energy they bring, their motion against "
             "each other and their heat, against a barrier that grows with their mass: the more they bring the "
             "likelier, so hot matter fuses where it lies and heavy rungs need it hotter. Up to {} fusing gives off "
             "energy as heat (most from the light rungs); past it fusing takes energy, so matter fused that far can "
             "no longer heat itself. Key: M.".format(config.MAX_MASS, config.FUSION_PEAK),
    "split": "Fission: a particle hit hard enough breaks into two of the rung below - it takes the energy fusion "
             "gave off (past {} it gives energy instead). Key: P.".format(config.FUSION_PEAK),
    "scatter": "Loose particles that collide bounce off at a random angle of up to this much from straight "
               "back, as if they met a little off-centre, so a stream glances off whatever it hits instead of "
               "queueing up in a line behind it. 0 bounces them straight back. Stars' particles always bounce "
               "straight. Momentum is kept either way.",
    "star_damping": "Internal friction in stars: this share of the jostling of a star's particles (their motion "
                    "against the star moving and turning as a whole) fades every tick. Higher holds stars together "
                    "more stiffly, like one solid lump; lower lets them slosh and wobble, so they are easier to "
                    "deform and tear. 0 turns it off. A star's momentum is kept either way. Starts at "
                    "{:.0%}.".format(config.STAR_DAMPING),
    "lean": "Each particle carries a little universe of children that slosh about inside it; with this on they "
            "steer it. It is a random push about as strong as weak gravity, so it makes orbits wander. Key: J.",
    "view": "What the colours show: mass, speed, which way the children lean, or which particles are awake "
            "(simulated) and which are asleep. Key: V.",
    "cell": "How many pixels each particle is drawn as. Smaller squares mean more, smaller particles; the scene is "
            "resampled to keep its shape. Keys: [ / ].",
    "inspector": "Hover over a particle, star, well or spawner to see its details. Key: I.",
    "fullscreen": "Fill the screen (the window can also be resized). Key: F11.",
    "shortcuts": "Show every keyboard shortcut. Key: H.",
    "performance": "What each part of a tick costs, and what happened in the last tick: particles that moved, "
                   "collided, merged, split, sank through lighter ones or were swallowed by super wells. Below that, "
                   "where the work runs: on one core or all of them, and the gravity field and ghosts on the GPU "
                   "whenever it is faster than the cores (timed every so often, so this can change). Start with "
                   "--cpu to run on one core without the GPU, as before.",
    "selected": "The body you clicked with Select / move. Drag it to move it.",
    "spin": "How fast the super well spins, as a share of the most a black hole of its mass can (1). Its spin is "
            "the angular momentum it holds - of the matter that collapsed into it, all it swallows and the wells "
            "that merged into it - so it spins up as matter swirls in. It drags space itself round the same way "
            "(frame dragging): strongest near it, fading as its pull does, so whatever falls in spirals in instead of "
            "falling straight. Inside its faint circle space moves faster than matter can, so nothing there can "
            "hold still or go against its spin. Keys: ; / '.",
    "ghost_stars": "A placed star arrives as a ghost star: its particles fly together through everything, feeling "
                   f"gravity, for {config.GHOST_TICKS} ticks, then land as a star where it got to (any of its "
                   "particles whose cell is taken land nearby as ordinary particles). Shift+click with the Star tool "
                   "always places one; with this on, so do a click and G.",
    "orbit_stars": "A placed star sets off on a circular orbit round the super well pulling hardest on it, the way "
                   "that well spins, and the well takes the opposite push so the two don't drift off together. To "
                   "last, put it outside the faint circle (inside, the whirlpool tears it up) and far enough out "
                   "that the tide doesn't strip it (heavier wells need smaller, denser stars; wells over about 5M "
                   "can't hold any at the default reach): a pour-16 star from a 20 px brush holds 114-135 cells from an 80,000 "
                   "well. Off: it starts at rest. With the Star tool picked, a green band round "
                   "each super well shows where the star the tool would place can orbit; none means "
                   "nowhere. Auto star picks the star and the spot for you. Key: T.",
    "body_mass": "Make it lighter or heavier. A star is rebuilt as a fresh layered ball as dense as it is, growing "
                 "or shrinking with the square root of the change; a repulsor takes the size a freshly placed one of "
                 "that mass has, so its pull and reach match one made at that mass. Keys: , / .",
}


def kind(body):
    if isinstance(body, Star):
        return "Star"
    if isinstance(body, Spawner):
        return "Locked spawner" if body.locked else "Spawner"
    return "Super well" if body.is_super else ("Repulsor" if body.sign < 0 else "Solid well")


def draw_tool_settings(ui, app):
    """The settings of the mouse tool picked, and only what changes what it places. A body's mass and size are
    linked: set either one and the other follows, so what a click places is always known beforehand."""
    w, tool = app.world, app.tool
    cells = lambda px: f"{px:.0f} px ({max(1.0, px / w.cell):.0f} cells)"   # noqa: E731
    if tool == "super":
        lo, hi = app.super_mass_range()
        step = config.SUPER_PLACE_STEP
        opts = [(lo, f"{mass_label(lo)} min")] + [(m, mass_label(m))
                                                    for m in range(step, min(10 * step, int(w.explode_mass)), step)]
        app.super_mass = ui.choice("super_mass", "Mass", opts, app.super_mass, INFO["super_mass"], columns=5)
        app.super_mass = ui.number_field("super_typed", "Or type a mass", app.super_mass, lo, hi, INFO["super_mass"],
                                         fmt=mass_label)
        core = app.super_core_px()
        size = ui.slider("super_size", "Horizon", core, w.edge_for_mass(lo) * w.cell, w.edge_for_mass(hi) * w.cell,
                         INFO["super_size"], lambda v: f"{v / w.cell:.2f} cells", step=0.25 * w.cell)
        if size != core:
            app.set_super_core_px(size)
        m = app.placed_super_mass()
        wl = Well(0.0, 0.0, m, is_super=True, edge=w.edge_for_mass(m))
        ui.stats([("mass", f"{m:,.0f}"), ("core", f"{wl.core():.1f}"), ("no return", f"{w.horizon(wl):.0f} cells")])
        if m >= w.explode_mass:
            ui.note(f"At or over the supernova mass ({mass_label(w.explode_mass)}): it explodes moments after it is "
                    "placed.", WARN)
    elif tool == "repulsor":
        lo, hi = app.repulsor_mass_range()
        app.repulsor_mass = ui.choice("repulsor_mass", "Mass", [(m, mass_label(m)) for m in config.REPULSOR_PLACE_MASSES],
                                      app.repulsor_mass, INFO["repulsor_mass"], columns=6)
        app.repulsor_mass = ui.number_field("repulsor_typed", "Or type a mass", app.repulsor_mass, lo, hi,
                                            INFO["repulsor_mass"], fmt=mass_label)
        px = app.repulsor_px()
        size = ui.slider("repulsor_size", "Size", px, *config.REPULSOR_SIZE_PX, INFO["repulsor_size"], cells, log=True,
                         step=4)
        if size != px:
            app.set_repulsor_px(size)
    elif tool == "auto":
        ui.note("Click near a super well: Auto star picks the star's size, particle mass and orbit itself. The green "
                "band round each super well shows where it would go.")
    elif tool in ("select", "delete"):
        ui.note("Click a star, well or spawner to select it (drag to move it)." if tool == "select" else
                "Click a star, well or spawner to delete it (X deletes the one nearest the mouse).")
    else:
        lo, hi = config.PLACE_SIZE_PX
        label = {"star": "Size", "spawner": "Size", "locked": "Size"}.get(tool, "Brush size")
        app.brush_px = ui.slider("brush", label, app.brush_px, lo, hi, INFO["brush"], cells, integer=True, step=1)
        if tool != "erase":
            app.pour_mass = ui.choice("pour", "Particle mass" + (" (its core)" if tool == "star" else ""),
                                      POUR_OPTIONS, app.pour_mass, INFO["pour"], columns=6)
        if tool == "star":
            mass = app.star_mass()
            typed = ui.number_field("star_mass", "Star mass", mass, 1, 1e9, INFO["star_mass"], fmt=mass_label)
            if typed != mass:
                app.set_star_mass(typed)
            if w.collapse_on:
                most = app.largest_star_px()
                if most is None:
                    ui.note("Every star of this particle mass collapses into a super well at once: pick a lighter "
                            "one.", DANGER)
                elif app.brush_px > most:
                    ui.note(f"Collapses into a super well at once: at this particle mass a star holds together up to "
                            f"{most} px ({mass_label(app.star_mass(most))} mass).", DANGER)
                elif most < hi:
                    ui.note(f"Holds together up to {most} px ({mass_label(app.star_mass(most))} mass) at this "
                            "particle mass.")
            app.ghost_stars = ui.toggle("ghost_stars", "Stars arrive as ghosts", app.ghost_stars, INFO["ghost_stars"],
                                        note=f"{len(w.ghost_stars)} arriving" if w.ghost_stars else None)
            app.orbit_stars = ui.toggle("orbit_stars", "Stars start in orbit", app.orbit_stars, INFO["orbit_stars"])
        elif tool in ("spawner", "locked"):
            r = max(1.0, app.brush_px / w.cell)
            ui.stats([("pours", f"{math.pi * r * r * config.SPAWNER_RATE * config.FPS:,.0f} particles/s")])


def draw_menu(ui, app, fps):
    """Lay out the whole menu for this frame (and act on whatever was clicked)."""
    w = app.world
    s = w.stats
    ui.hamburger("PAUSED" if app.paused else None)
    if not ui.open:
        ui.closed()
        return
    ui.begin()

    if ui.section("sim", "Simulation"):
        ui.stats([("particles", f"{w.particle_count():,}"), ("particle mass", f"{w.total_mass():,}"),
                  ("tick", f"{w.tick_count:,}"), ("", f"{fps:.0f} fps")])
        hit = ui.buttons("pause", [("pause", "Paused" if app.paused else "Pause", app.paused), ("step", "Step"),
                                   ("clear", "Clear")], INFO["pause"], "Pause, step, clear", columns=3)
        if hit == "pause":
            app.paused = not app.paused
        elif hit == "step":
            w.step()
        elif hit == "clear":
            w.clear()
        app.ticks_per_frame = ui.slider("speed", "Speed", app.ticks_per_frame, 1, config.MAX_TICKS_PER_FRAME,
                                        INFO["speed"], "{} per frame", integer=True, step=1,
                                        note=f"step {w.step_ms:.1f} ms")
        hit = ui.choice("presets", "Presets", [(p, p.capitalize()) for p in ("rain", "disk", "cloud", "binary",
                                                                              "systems", "supernova", "empty")], None,
                        INFO["presets"], columns=3)
        if hit:
            PRESETS[hit](w)
            app.selected = None
        ui.gap()

    if ui.section("tool", "Mouse tool"):
        app.tool = ui.choice("tool", "Left click", TOOLS, app.tool, INFO["tool"], columns=3)
        ui.gap(4)
        draw_tool_settings(ui, app)
        ui.gap()

    body = app.selected
    if body is not None and ui.section("selected", f"Selected: {kind(body)}", info=INFO["selected"]):
        if isinstance(body, Star):
            ui.stats([("mass", f"{body.mass:,.0f}"), ("particles", f"{body.count:,}"),
                      ("radius", f"{body.radius:.1f}"), ("ring", f"{body.ring:.1f}"),
                      ("holds", f"{body.smooth / body.peak:.0%}" if body.peak else "-"),
                      ("speed", f"{math.hypot(body.vx, body.vy):.2f}")])
        elif isinstance(body, Spawner):
            ui.stats([("rate", f"{body.rate * config.FPS:,.0f}/s"), ("speed", f"{math.hypot(body.vx, body.vy):.2f}")])
            body.locked = ui.toggle("locked", "Locked in place", body.locked)
        else:
            ui.stats([("mass", f"{body.mass:,.0f}"), ("speed", f"{math.hypot(body.vx, body.vy):.2f}")]
                     + ([("core", f"{body.core():.1f}"), ("faint circle", f"{w.well_range(body):.0f} cells")]
                        if body.is_super else []))
        if not isinstance(body, Spawner) and not getattr(body, "is_super", False):
            hit = ui.buttons("body_mass", [(0.8, "Lighter"), (1.25, "Heavier")], INFO["body_mass"], "Mass",
                             columns=2)
            if hit:
                w.scale_well(body, hit)
        if getattr(body, "is_super", False):
            way = ui.choice("spin_way", "Spin direction", [(1, "Clockwise"), (-1, "Counter-clockwise")],
                            1 if body.spin >= 0 else -1, INFO["spin"], columns=2)
            if way != (1 if body.spin >= 0 else -1):
                w.set_spin(body, -body.spin)
            spin = ui.slider("spin", "Spin", abs(body.spin), 0.0, config.SUPER_SPIN_MAX, INFO["spin"], "{:.2f}",
                             step=0.05)
            if spin != abs(body.spin):
                w.set_spin(body, way * spin)
        hit = ui.buttons("body", [("delete", "Delete"), ("deselect", "Deselect")], columns=2)
        if hit == "delete":
            w.remove_body(body)
        if hit:
            app.selected = None
        ui.gap()

    if ui.section("gravity", "Gravity"):
        gdir = ui.direction_pad("gdir", "Direction", w.gdir, DIRS, INFO["gdir"],
                                note="Pick a direction for uniform gravity, or the middle for none.")
        if gdir != w.gdir:
            w.set_gravity(gdir)
        g = ui.slider("strength", "Strength", w.g_scale, 1 / 16, 16, INFO["strength"], "x {:.2f}", log=True,
                      step=0.1)
        if g != w.g_scale:
            w.set_gravity_scale(g)
        everywhere = REACH_MAX                           # the slider's top end: no fading at all
        reach = ui.slider("reach", "Reach", w.reach_len or everywhere, REACH_MIN, everywhere, INFO["reach"],
                          lambda v: "everywhere" if v >= everywhere else f"{v:.0f} cells", log=True, integer=True,
                          step=5)
        reach = 0 if reach >= everywhere else reach
        if reach != w.reach_len:
            w.set_reach(reach)
        sg = ui.toggle("sg", "Self-gravity", w.sg_on, INFO["sg"], note=f"{w.gravity_ms:.1f} ms" if w.sg_on else None)
        if sg != w.sg_on:
            w.set_self_gravity(sg)
        ui.gap()

    if ui.section("space", "Universe and rotation"):
        shape = ui.choice("shape", "Shape", [(False, "Window"), (True, "Round")], w.round, INFO["shape"], columns=2)
        if shape != w.round:
            w.set_round(shape)
        orbit = ui.choice("orbit", "Global rotation", [(0, "Off"), (1, "Clockwise"), (-1, "Counter-clockwise")],
                          w.orbit, INFO["orbit"], columns=3)
        if orbit != w.orbit:
            w.set_orbit(orbit)
        edge = w.orbit_edge_speed()
        v = ui.slider("orbit_speed", "Rotation speed", edge, 0.6, 8.0, INFO["orbit_speed"], "{:.2f} cells/tick",
                      log=True, note="" if w.orbit else "(off)", step=0.1)
        if v != edge:
            w.set_orbit_edge_speed(v)
        wrap = ui.toggle("wrap", "Wrap borders", w.wrap, INFO["wrap"],
                         note="no walls" if w.wrap else "round rim" if w.round else "walls")
        if wrap != w.wrap:
            w.set_wrap(wrap)
        cam = app.cam
        z = ui.slider("zoom", "Zoom", cam.zoom, cam.min_zoom(), config.ZOOM_MAX, INFO["zoom"], "{:.2f}x", log=True,
                      step=0.1)
        if z != cam.zoom:
            cam.zoom_at(z / cam.zoom, cam.sw / 2, cam.sh / 2)
        hit = ui.buttons("camera", [("fit", "Fit universe"), ("reset", "1x, centred")], INFO["zoom"], "View",
                         columns=2)
        if hit == "fit":
            cam.fit()
        elif hit == "reset":
            cam.reset()
        ui.gap()

    if ui.section("stars", "Stars and black holes", info=INFO["stars"]):
        ui.stats([("stars", f"{len(w.stars)}"), ("holding", f"{w.star_mass():,}"), ("formed", f"{w.stars_formed}"),
                  ("exploded", f"{w.star_explosions}"), ("torn apart", f"{w.stars_torn}")])
        w.star_form_on = ui.toggle("formation", "Star formation", w.star_form_on, INFO["formation"])
        w.radiation_on = ui.toggle("radiation", "Radiation (heat)", w.radiation_on, INFO["radiation"],
                                   note=f"{w.heat_count() + w.wave_count():,} in flight" if w.radiation_on else None)
        w.show_radiation = ui.toggle("show_radiation", "Draw radiation", w.show_radiation, INFO["show_radiation"])
        w.radiation_recycle = ui.toggle("recycle", "Radiation comes back", w.radiation_recycle, INFO["recycle"],
                                        note=None if w.radiation_recycle else f"{w.radiation_lost:,} quanta gone")
        w.collapse_on = ui.toggle("collapse", "Collapse into super wells", w.collapse_on, INFO["collapse"],
                                  note=f"lightest {w.lightest_super_mass():,.0f}")
        step = config.SUPER_EXPLODE_STEP
        boom = ui.slider("explode", "Supernova at", w.explode_mass, *config.SUPER_EXPLODE_RANGE, INFO["explode"],
                         lambda v: f"{v / 1e6:g}M mass", log=True, step=step)
        w.explode_mass = int(round(boom / step) * step)
        ui.stats([("super wells", f"{sum(wl.is_super for wl in w.wells)}"), ("holding", f"{w.super_mass():,}"),
                  ("supernovae", f"{w.explosions}")])
        ui.gap()

    if ui.section("advanced", "Advanced", default=False):
        if ui.section("adv_particles", "Particles", level=1):
            w.merge_on = ui.toggle("merge", "Fusion", w.merge_on, INFO["merge"],
                                   note=f"{s[2] + w.fused:,} last tick")
            w.split_on = ui.toggle("split", "Fission", w.split_on, INFO["split"], note=f"{s[3]:,} last tick")
            w.lean_on = ui.toggle("lean", "Children steer", w.lean_on, INFO["lean"])
            w.scatter = math.radians(ui.slider("scatter", "Bounce angle", math.degrees(w.scatter), 0, 45,
                                               INFO["scatter"], "up to {:.0f}°", step=1))
        if ui.section("adv_stars", "Stars", level=1):
            w.star_damping = ui.slider("star_damping", "Star damping", w.star_damping, 0.0, 0.5,
                                       INFO["star_damping"], "{:.0%} a tick", step=0.01)
        if ui.section("adv_display", "Display", level=1):
            app.view = ui.choice("view", "Colour by", list(enumerate(VIEW_MODES)), app.view, INFO["view"],
                                 columns=4)
            cell = ui.choice("cell", "Square size (px)", [(c, str(c)) for c in config.CELL_SIZES], w.cell,
                             INFO["cell"], columns=10)
            if cell != w.cell:
                w.set_cell(cell)
            app.inspector = ui.toggle("inspector", "Inspector on hover", app.inspector, INFO["inspector"])
            if ui.toggle("fullscreen", "Fullscreen", app.fullscreen, INFO["fullscreen"]) != app.fullscreen:
                app.toggle_fullscreen()
            app.show_help = ui.toggle("shortcuts", "Keyboard shortcuts", app.show_help, INFO["shortcuts"])
        if ui.section("adv_perf", "Performance and last tick", level=1, info=INFO["performance"]):
            ui.stats([("step", f"{w.step_ms:.1f} ms"), ("gravity", f"{w.gravity_ms:.1f} ms"),
                      ("render", f"{app.render_ms:.1f} ms"), ("awake", f"{w.awake_count():,}")])
            ui.stats([("moved", f"{s[0]:,}"), ("collisions", f"{s[1]:,}"), ("merges", f"{s[2]:,}"),
                      ("splits", f"{s[3]:,}"), ("sinks", f"{s[4]:,}"), ("absorbed", f"{s[5]:,}")])
            ui.stats([("heat sent out", f"{w.heat_made:,}"), ("fusions", f"{w.fused:,}"),
                      ("heat in flight", f"{w.heat_count():,}")])
            rest, kinetic, heat, bound = w.energy()
            ui.stats([("energy: in motion", f"{kinetic:,.0f}"), ("as heat", f"{heat:,.0f}"),
                      ("bound in fusion", f"{-bound:,.0f}")])
            ui.stats([("waves sent out", f"{w.waves_made:,}"), ("waves in flight", f"{w.wave_count():,}")])
            ui.stats([("ghosts", f"{w.ghost_count():,} (mass {w.ghost_mass():,})"),
                      ("repulsors", f"{sum(not wl.is_super for wl in w.wells)}"),
                      ("spawners", f"{len(w.spawners)}")])
            ui.stats([(job, where if ms is None else f"{where} ({ms:.1f} ms)")
                      for job, where, ms in w.where_work_runs()]
                     + [("GPU", str(w.gpu) if w.gpu is not None else "off")])
    ui.end()
