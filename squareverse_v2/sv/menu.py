"""The control menu: everything you can set, and every figure the simulation reports, beside the control it belongs
to. It opens from the button in the bottom-right corner; the rarely needed controls fold away under Advanced. Each
row's (i) explains it."""

import math

from . import config
from .presets import PRESETS
from .world import DIRS, VIEW_MODES, Spawner, Star

# the mouse tools: what a left click on the universe does
TOOLS = [("pour", "Pour"), ("ghosts", "Ghosts"), ("erase", "Erase"), ("star", "Star"), ("repulsor", "Repulsor"),
         ("super", "Super well"), ("spawner", "Spawner"), ("locked", "Locked spawner"), ("select", "Select / move"),
         ("delete", "Delete")]
POUR_OPTIONS = [(m, str(m)) for m in config.POUR_MASSES] + [(tuple(config.RANDOM_MASS), "Random")]
REACH_MIN, REACH_MAX = 10, 400                   # the Reach slider (cells); at its top end gravity reaches everywhere

INFO = {
    "pause": "Stops the simulation; Step then advances it one tick at a time. Clear empties the universe of particles "
             "and stars (wells and spawners stay). Keys: space, N, C.",
    "speed": "How many simulation ticks run per frame of the display. More is faster, but each frame takes longer to "
             "draw, so the frame rate drops in big scenes. The step time is what one tick costs. Keys: + / -.",
    "presets": "Starting scenes. Rain: mixed masses falling under gravity. Disk: a self-gravitating dust disk turning "
               "with the global rotation in a round universe, which forms stars. Cloud: a turning cloud that "
               "clumps. Binary: two stars orbiting each other inside a ring. Systems: a black hole in the middle "
               "orbited by three stars, and a few more round it with a star or two each. Empty: nothing. "
               "Keys: F1-F5.",
    "tool": "What a left click on the universe does. Pour / Ghosts / Erase work while you hold the button down; the "
            "others act once per click, at the brush's size. Ghosts are particles that pass through everything for "
            f"{config.GHOST_TICKS} ticks, then land. A star is a ball of particles held together by its own gravity; "
            "a repulsor pushes everything away; a super well (black hole) swallows what touches its core; a "
            "spawner pours particles (a locked one stays put). Select / move: click a body to see and change it, "
            "drag it to move it. Right click always erases; shift+click pours ghosts (with the Star tool, places a "
            "ghost star) or drags a body. Keys: G, "
            "shift+G, B, F, shift+F, X.",
    "brush": "The size of the brush circle: where particles are poured or erased, and how big a placed star, "
             "repulsor or spawner is. The mouse wheel changes it too.",
    "pour": "The mass of each poured particle (heavier ones sink through lighter ones and pull harder), or a random "
            "mass from {} to {} each. A placed star fills the brush circle with a core of particles of this mass, "
            "its outer layers lighter in proportion (3/8, then 1/8 of it), so this sets what it is made of and how "
            "heavy it is. A repulsor weighs the brush's area x this, its size following its mass: the brush's size "
            "at pour mass 1, bigger for heavier pours. Keys: 1-6.".format(
                *config.RANDOM_MASS),
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
    "stars": "Stars are balls of particles: a heavy core in a light envelope, held together by their own gravity. "
             "Touching gently they merge; crashing they splash matter out of the contact; one that loses too much "
             "explodes, or is torn apart by a heavier neighbour's tide.",
    "formation": "Every second, dense round knots of matter with a heavy core inside a lighter envelope that hold "
                 "themselves together become stars. Off: only stars you place appear.",
    "collapse": "Matter (stars included) packed densely enough collapses into a super well: a black hole that "
                "swallows what touches its core. The threshold is the mass in a 20 x 20 cell window, and falls as "
                "gravity gets stronger. A super well reaching the supernova mass (below) explodes. Key: shift+B.",
    "explode": "How heavy a super well gets before it goes supernova: all its mass blasts out as a ring of heavy "
               "debris that cools and lands as particles. Higher lets super wells grow bigger and hold more of the "
               "universe before they blow; lower makes supernovae more frequent. A well already over a lowered "
               "limit explodes after a short grace. Spin rising with mass reaches its top at this mass.",
    "radiation": "Merging and splitting lose {:.0%} of the mass involved as heat: a few light, fast particles that fly "
                 "through everything for {} ticks, blowing light matter they pass away (a heavy particle barely "
                 "moves and soaks the heat up), then land as ordinary light particles. Stars fuse their light "
                 "particles into heavier ones, losing {:.0%} as heat, so they blow a wind of light matter away. Super "
                 "wells spiralling into each other send out gravitational waves: two beams along the line "
                 "through them that turn as they circle, ever stronger as they near, then a burst as they merge "
                 "that fades as the merged core settles - up to {:.1%} of their mass, flying straight through "
                 "everything at the speed limit. Both glow pale blue. No mass is lost: heat and waves are mass, "
                 "carried off as particles.".format(config.HEAT_SHARE, config.HEAT_TICKS, config.FUSION_HEAT_SHARE,
                                     config.SUPER_GW_INSPIRAL + config.SUPER_GW_MERGER + config.SUPER_GW_RINGDOWN),
    "merge": "Particles colliding fast enough sometimes merge into one heavier particle (mass and momentum are "
             "kept). Key: M.",
    "split": "Particles hit hard enough break in two. Key: P.",
    "scatter": "Loose particles that collide bounce off at a random angle of up to this much from straight "
               "back, as if they met a little off-centre, so a stream glances off whatever it hits instead of "
               "queueing up in a line behind it. 0 bounces them straight back. Stars' particles always bounce "
               "straight. Momentum is kept either way.",
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
    "spin_mass": "A new super well starts spinning at {} and spins faster as it grows, reaching {} when it is about "
                 "to go supernova. The faster it spins, the more matter it flings out into a ring instead of "
                 "swallowing, so a well grows steadily instead of running away, several share the universe, and "
                 "one blowing up rarely sets off its neighbours at once. Setting a well's spin by hand stops it "
                 "following its mass. Turning this off sets every super well back to {}.".format(
                     config.SUPER_SPIN_PLACED, config.SUPER_SPIN_FULL, config.SUPER_SPIN_PLACED),
    "spin": "How fast the super well whirls the space inside its dotted circle round. Above 1 it whirls matter "
            "faster than it would orbit and flings it out into a ring instead of drawing it in. Keys: ; / '.",
    "ghost_stars": "A placed star arrives as a ghost star: its particles fly together through everything, feeling "
                   f"gravity, for {config.GHOST_TICKS} ticks, then land as a star where it got to (any of its "
                   "particles whose cell is taken land nearby as ordinary particles). Shift+click with the Star tool "
                   "always places one; with this on, so do a click and G.",
    "orbit_stars": "A placed star sets off on a circular orbit round the super well pulling hardest on it, the way "
                   "that well spins, and the well takes the opposite push so the two don't drift off together. To "
                   "last, put it outside the dotted circle (inside, the whirlpool tears it up) and far enough out "
                   "that the tide doesn't strip it: a pour-16 star from the default brush holds about 130 cells "
                   "from an 80,000 well (B at pour mass 1), with gravity reaching everywhere. Off: it starts at "
                   "rest. With the Star tool picked, a green band round each super well shows where the star "
                   "the brush and pour mass would place can orbit; none means nowhere. Key: T.",
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
                                                                              "systems", "empty")], None,
                        INFO["presets"], columns=3)
        if hit:
            PRESETS[hit](w)
            app.selected = None
        ui.gap()

    if ui.section("tool", "Mouse tool"):
        app.tool = ui.choice("tool", "Left click", TOOLS, app.tool, INFO["tool"], columns=3)
        app.brush_px = ui.slider("brush", "Brush size", app.brush_px, 2, 160, INFO["brush"], "{} px",
                                 integer=True, step=1)
        app.pour_mass = ui.choice("pour", "Pour mass", POUR_OPTIONS, app.pour_mass, INFO["pour"], columns=6)
        app.ghost_stars = ui.toggle("ghost_stars", "Stars arrive as ghosts", app.ghost_stars, INFO["ghost_stars"],
                                    note=f"{len(w.ghost_stars)} arriving" if w.ghost_stars else None)
        app.orbit_stars = ui.toggle("orbit_stars", "Stars start in orbit", app.orbit_stars, INFO["orbit_stars"])
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
                     + ([("range", f"{w.well_range(body):.0f} cells")] if body.is_super else []))
        if not isinstance(body, Spawner) and not getattr(body, "is_super", False):
            hit = ui.buttons("body_mass", [(0.8, "Lighter"), (1.25, "Heavier")], INFO["body_mass"], "Mass",
                             columns=2)
            if hit:
                w.scale_well(body, hit)
        if getattr(body, "is_super", False):
            way = ui.choice("spin_way", "Spin direction", [(1, "Clockwise"), (-1, "Counter-clockwise")],
                            1 if body.spin >= 0 else -1, INFO["spin"], columns=2)
            if way != (1 if body.spin >= 0 else -1):
                body.spin = -body.spin                   # a turn the other way keeps it following its mass
            following = w.spin_follows_mass and body.auto_spin
            spin = ui.slider("spin", "Spin", abs(body.spin), 0.05, config.SUPER_SPIN_MAX, INFO["spin"], "{:.2f}",
                             log=True, step=0.1, note="follows mass" if following else None)
            if spin != abs(body.spin):
                w.set_spin(body, way * spin)
            if w.spin_follows_mass:
                body.auto_spin = ui.toggle("auto_spin", "Spin follows its mass", body.auto_spin, INFO["spin_mass"])
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
        w.collapse_on = ui.toggle("collapse", "Collapse into super wells", w.collapse_on, INFO["collapse"],
                                  note=f"at {w.collapse_threshold():,.0f}")
        step = config.SUPER_EXPLODE_STEP
        boom = ui.slider("explode", "Supernova at", w.explode_mass, *config.SUPER_EXPLODE_RANGE, INFO["explode"],
                         lambda v: f"{v / 1e6:g}M mass", log=True, step=step)
        w.explode_mass = int(round(boom / step) * step)
        follows = ui.toggle("spin_mass", "Spin rises with mass", w.spin_follows_mass, INFO["spin_mass"],
                            note=f"{config.SUPER_SPIN_PLACED:g} to {config.SUPER_SPIN_FULL:g}")
        if follows != w.spin_follows_mass:
            w.set_spin_follows_mass(follows)
        ui.stats([("super wells", f"{sum(wl.is_super for wl in w.wells)}"), ("holding", f"{w.super_mass():,}"),
                  ("supernovae", f"{w.explosions}")])
        ui.gap()

    if ui.section("advanced", "Advanced", default=False):
        if ui.section("adv_particles", "Particles", level=1):
            w.merge_on = ui.toggle("merge", "Merging", w.merge_on, INFO["merge"], note=f"{s[2]:,} last tick")
            w.split_on = ui.toggle("split", "Splitting", w.split_on, INFO["split"], note=f"{s[3]:,} last tick")
            w.lean_on = ui.toggle("lean", "Children steer", w.lean_on, INFO["lean"])
            w.scatter = math.radians(ui.slider("scatter", "Bounce angle", math.degrees(w.scatter), 0, 45,
                                               INFO["scatter"], "up to {:.0f}°", step=1))
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
            ui.stats([("waves sent out", f"{w.waves_made:,}"), ("waves in flight", f"{w.wave_count():,}")])
            ui.stats([("ghosts", f"{w.ghost_count():,} (mass {w.ghost_mass():,})"),
                      ("repulsors", f"{sum(not wl.is_super for wl in w.wells)}"),
                      ("spawners", f"{len(w.spawners)}")])
            ui.stats([(job, where if ms is None else f"{where} ({ms:.1f} ms)")
                      for job, where, ms in w.where_work_runs()]
                     + [("GPU", str(w.gpu) if w.gpu is not None else "off")])
    ui.end()
