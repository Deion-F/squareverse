"""numba kernels: the per-tick simulation, brushes, waking and frame rendering.

All particle state lives in flat per-cell arrays (index i = y * w + x, as in sand.py); a cell holds at most one
particle and mass 0 means empty. Only awake particles (flag[i] == 1) are simulated, so settled piles cost nothing.
Everything here is compiled to machine code once and cached on disk (cache=True).

kin[i] = (vx, vy, ox, oy): velocity in cells/tick and the sub-cell offset from the cell centre, so slow velocities
still add up to moves. quad[i] = children per quadrant (up-left, up-right, down-left, down-right); they always sum
to mass[i]. solid[i] = 1 inside a solid well's body (a repulsor): nothing can enter it. hole[i] = k + 1 when cell
i is inside the core of super well k: a particle that enters it is absorbed. owner[i] = k + 1 when the particle in
cell i belongs to star k (it is bound to it; see update_stars).
With wrap on, the borders are continuous: x = -1 is x = w - 1, and so on.
stamp[i] = 2 * tick + blocked for the last tick the particle was simulated in, so the kernel can tell
whether a neighbour is free to move or jammed against something with a stale velocity.
"""

import numpy as np
from numba import njit, prange

# indices into the float64 params array handed to step()
(P_VMAX, P_MAX_STEPS, P_WALL_E, P_E, P_IMPACT_MIN, P_SLIDE_DAMP, P_SINK, P_DRAG, P_SLEEP_EPS,
 P_CHILD_MOVES, P_SLOSH, P_LEAN, P_MERGE_ON, P_MERGE_SPEED, P_MERGE_CHANCE, P_MAX_MASS,
 P_SPLIT_ON, P_BIND, P_KICK, P_SG_ON, P_CHILD_EVERY, P_ORBIT_W, P_ORBIT_GRIP, P_ORBIT_CX, P_ORBIT_CY,
 P_SLEEP_ACCEL, P_WRAP, P_ORBIT_VMIN, P_WHIRL_SPEED, P_WHIRL_GRIP, P_WHIRL_INFALL, P_WHIRL_EDGE, P_SPLIT_SPEED,
 P_SCATTER, P_REACH, P_SG_COS, P_SG_SIN, P_HEAT, P_DRAG_EDGE, P_DRAG_TURN, P_PRESSURE,
 P_FUSE_BIND, P_FUSE_PEAK, P_FUSE_TOP, P_FUSE_TAIL, P_BARRIER) = range(46)
N_PARAMS = 46

# indices into the int64 stats array filled by step()
S_MOVED, S_COLLISIONS, S_MERGES, S_SPLITS, S_SINKS, S_ABSORBED, S_HEAT = range(7)
N_STATS = 7

STAR_SHOVE_SHARE = 0.1          # a star shoves loose particles lighter than this share of it aside (star_shift)
HEAT_TAG = -1                   # ghost tag of heat (radiation): see _shed and heat_push
DX4 = np.array([1, 0, -1, 0])   # the four sides of a cell
DY4 = np.array([0, 1, 0, -1])
KIN = 5                         # kin's columns: velocity (vx, vy), where it is within its cell (ox, oy) and its heat -
                                #   the kinetic energy its collisions, contacts and internal friction have lost, held
                                #   as thermal energy (mass x cells^2 / tick^2, like kinetic energy) until it spreads
                                #   to its neighbours or is radiated away (heat_step)
WAVE_TAG = -2                   # ghost tag of gravitational waves (World._radiate_waves): they fly straight

N_SHADES = 6

# 8 directions clockwise from "down" (same order as sand.py's DIRS)
DX = np.array([0, -1, -1, -1, 0, 1, 1, 1])
DY = np.array([1, 1, 0, -1, -1, -1, 0, 1])
# (sy + 1) * 3 + (sx + 1) -> direction index (-1 = no motion)
DIR_OF = np.array([3, 4, 5, 2, -1, 6, 1, 0, 7])


@njit(cache=True)
def seed(s):
    np.random.seed(s)


@njit(cache=True)
def _cell(x, y, w, h, wrap):
    """Index of cell (x, y), wrapping round the borders when wrap is on; -1 if it is off the grid."""
    if 0 <= x < w and 0 <= y < h:
        return y * w + x
    if wrap:
        return (y % h) * w + x % w
    return -1


@njit(cache=True)
def _span(c, r, n, wrap):
    """Cells to visit along one axis for a disc of radius r around coordinate c: (start, stop, min_image). With wrap
    on the range may run past the border (take it modulo n); when the disc spans the whole axis it is every cell
    once, measured the shortest way round."""
    if wrap and 2.0 * r + 2.0 >= n:
        return 0, n, True
    a, b = int(np.floor(c - r)), int(np.floor(c + r)) + 2
    if not wrap:
        a, b = max(0, a), min(n, b)
    return a, b, False


@njit(cache=True)
def _axis(v, c, n, min_image):
    """v - c along one axis, the shortest way round a wrapped axis of n cells when min_image."""
    d = v - c
    if min_image:
        d -= n * np.floor(d / n + 0.5)
    return d


@njit(cache=True)
def _clamp_offset(o):
    if o > 0.4999:
        return 0.4999
    if o < -0.4999:
        return -0.4999
    return o


# --- waking ----------------------------------------------------------------------------------------

@njit(cache=True)
def wake(k, mass, flag):
    """Simulate the particle in cell k next tick."""
    if mass[k] != 0:
        flag[k] = 1


@njit(cache=True)
def wake_around(i, w, h, mass, flag, wrap):
    x, y = i % w, i // w
    if wrap and (x == 0 or y == 0 or x == w - 1 or y == h - 1):     # on the seam: neighbours wrap round
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                wake(((y + dy) % h) * w + (x + dx) % w, mass, flag)
        return
    for yy in range(max(0, y - 1), min(h, y + 2)):
        for xx in range(max(0, x - 1), min(w, x + 2)):
            wake(yy * w + xx, mass, flag)


@njit(cache=True)
def wake_all(mass, flag):
    for k in range(mass.size):
        wake(k, mass, flag)


@njit(cache=True)
def wake_blocks(changed, block, cw, w, h, mass, flag):
    """Wake every particle inside a self-gravity block whose field changed noticeably."""
    for y in range(h):
        row = (y // block) * cw
        for x in range(w):
            if changed[row + x // block]:
                wake(y * w + x, mass, flag)


# --- particle bookkeeping --------------------------------------------------------------------------

@njit(cache=True)
def _put(src, dst, mass, kin, quad, shade, stamp, owner):
    """Move the particle in cell src to the empty cell dst (with its star, if any)."""
    mass[dst] = mass[src]
    for c in range(KIN):
        kin[dst, c] = kin[src, c]
    for c in range(4):
        quad[dst, c] = quad[src, c]
    shade[dst] = shade[src]
    stamp[dst] = stamp[src]
    owner[dst] = owner[src]
    _clear(src, mass, kin, quad)
    owner[src] = 0


@njit(cache=True)
def _swap(a, b, mass, kin, quad, shade, stamp, owner):
    """Swap the particles in cells a and b."""
    mass[a], mass[b] = mass[b], mass[a]
    for c in range(KIN):
        kin[a, c], kin[b, c] = kin[b, c], kin[a, c]
    for c in range(4):
        quad[a, c], quad[b, c] = quad[b, c], quad[a, c]
    shade[a], shade[b] = shade[b], shade[a]
    stamp[a], stamp[b] = stamp[b], stamp[a]
    owner[a], owner[b] = owner[b], owner[a]


@njit(cache=True)
def _clear(i, mass, kin, quad):
    mass[i] = 0
    for c in range(KIN):
        kin[i, c] = 0.0
    for c in range(4):
        quad[i, c] = 0


@njit(cache=True)
def _init_quad(i, m, quad):
    """Scatter m children over the 4 quadrants at random (exactly for small m, roughly even for large m)."""
    base = (m - 64) // 4 if m > 64 else 0
    for c in range(4):
        quad[i, c] = base
    for _ in range(m - 4 * base):
        quad[i, np.random.randint(0, 4)] += 1


@njit(cache=True)
def place(i, m, vx, vy, mass, kin, quad, shade, stamp):
    """Put a particle of mass m into empty cell i."""
    mass[i] = m
    kin[i, 0] = vx
    kin[i, 1] = vy
    kin[i, 2] = 0.0
    kin[i, 3] = 0.0
    kin[i, 4] = 0.0
    _init_quad(i, m, quad)
    shade[i] = np.random.randint(0, N_SHADES)
    stamp[i] = 0


@njit(cache=True)
def place_many(idx, masses, vxs, vys, mass, kin, quad, shade, stamp, flag, solid):
    """Place particles into the given cells, skipping occupied and solid ones. Returns how many were placed."""
    placed = 0
    for t in range(idx.size):
        i = idx[t]
        if mass[i] == 0 and not solid[i]:
            place(i, masses[t], vxs[t], vys[t], mass, kin, quad, shade, stamp)
            wake(i, mass, flag)
            placed += 1
    return placed


@njit(cache=True)
def brush(cx, cy, r, m_lo, m_hi, chance, w, h, mass, kin, quad, shade, stamp, flag, solid, wrap):
    """Pour particles of mass m_lo, or of a random rung (mass 2^k) from m_lo to m_hi when they differ (m_hi > 0), or
    erase (m_hi == 0), in a circle of r cells around cell (cx, cy)."""
    k_lo, k_hi = 0, 0
    while (1 << k_lo) < m_lo:
        k_lo += 1
    while (1 << (k_hi + 1)) <= m_hi:
        k_hi += 1
    ri = int(r) + 1
    r2 = r * r
    for y in range(max(0, cy - ri), min(h, cy + ri + 1)):
        for x in range(max(0, cx - ri), min(w, cx + ri + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 > r2:
                continue
            i = y * w + x
            if m_hi > 0:
                if mass[i] == 0 and not solid[i] and np.random.random() < chance:
                    m = m_lo if m_lo == m_hi else 1 << np.random.randint(k_lo, max(k_lo, k_hi) + 1)
                    place(i, m, 0.0, 0.0, mass, kin, quad, shade, stamp)
                    wake(i, mass, flag)
            elif mass[i] != 0:
                _clear(i, mass, kin, quad)
                wake_around(i, w, h, mass, flag, wrap)


# --- children ----------------------------------------------------------------------------------------

@njit(cache=True)
def _slosh(q0, q1, q2, q3, m, ax, ay, moves, slosh):
    """Move a few children to a neighbouring quadrant, preferring the side opposite the acceleration.
    Takes and returns the 4 quadrant counts (up-left, up-right, down-left, down-right)."""
    a = np.sqrt(ax * ax + ay * ay)
    bx = ax / a if a > 0.0 else 0.0
    by = ay / a if a > 0.0 else 0.0
    for _ in range(moves):
        r = np.random.random() * m                       # pick a child...
        if r < q0:
            c = 0
        elif r < q0 + q1:
            c = 1
        elif r < q0 + q1 + q2:
            c = 2
        else:
            c = 3
        r = np.random.random()                           # ...an axis (r < 0.5) and whether it goes
        if r < 0.5:
            dst = c ^ 1                                  # other column
            p = 0.5 - slosh * bx * (1.0 if dst & 1 else -1.0)
        else:
            dst = c ^ 2                                  # other row
            p = 0.5 - slosh * by * (1.0 if dst & 2 else -1.0)
        if 2.0 * r - (0.0 if r < 0.5 else 1.0) < p:
            if c == 0:
                q0 -= 1
            elif c == 1:
                q1 -= 1
            elif c == 2:
                q2 -= 1
            else:
                q3 -= 1
            if dst == 0:
                q0 += 1
            elif dst == 1:
                q1 += 1
            elif dst == 2:
                q2 += 1
            else:
                q3 += 1
    return q0, q1, q2, q3


# --- collisions --------------------------------------------------------------------------------------

@njit(cache=True)
def _slide_target(x, y, d, w, h, mass, solid, wrap):
    """sand.py's slide_target for direction index d: slide off diagonally, else topple sideways when there is a
    drop just past the neighbouring cell. Returns the direction index to move in, or -1."""
    first = 1 if np.random.random() < 0.5 else -1
    for k in range(2):
        side = first if k == 0 else -first
        e = (d + side + 8) % 8
        j = _cell(x + DX[e], y + DY[e], w, h, wrap)
        if j >= 0 and mass[j] == 0 and not solid[j]:
            return e
    for k in range(2):
        side = first if k == 0 else -first
        e = (d + side + 8) % 8
        p = (d + 2 * side + 8) % 8
        jp = _cell(x + DX[p], y + DY[p], w, h, wrap)
        jq = _cell(x + DX[p] + DX[e], y + DY[p] + DY[e], w, h, wrap)
        if jp >= 0 and jq >= 0 and mass[jp] == 0 and not solid[jp] and mass[jq] == 0 and not solid[jq]:
            return p
    return -1


@njit(cache=True)
def _split(j, w, h, tick, mass, kin, quad, shade, stamp, flag, solid, wrap):
    """Break the particle in cell j into two of the rung below (exactly half its mass each), the second in a free
    neighbouring cell, both moving as it moved and sharing its heat; its children are shared out so each half's add
    up to its mass. Returns True on success (False: no free cell next to it)."""
    x, y = j % w, j // w
    start = np.random.randint(0, 8)
    f = -1
    for k in range(8):
        d = (start + k) % 8
        t = _cell(x + DX[d], y + DY[d], w, h, wrap)
        if t >= 0 and mass[t] == 0 and not solid[t]:
            f = t
            break
    if f < 0:
        return False
    m = np.int64(mass[j])
    half = m // 2
    moved = 0
    for c in range(4):
        a = np.int64(quad[j, c]) // 2
        quad[f, c] = a
        quad[j, c] -= a
        moved += a
    c = np.random.randint(0, 4)
    while moved < half:                                  # the odd children: one more each from wherever there is one
        if quad[j, c] > 0:
            quad[j, c] -= 1
            quad[f, c] += 1
            moved += 1
        c = (c + 1) % 4
    mass[j] = m - half
    mass[f] = half
    kin[f, 0] = kin[j, 0]
    kin[f, 1] = kin[j, 1]
    kin[f, 2] = 0.0
    kin[f, 3] = 0.0
    kin[f, 4] = kin[j, 4] * 0.5                          # its heat shared out by mass
    kin[j, 4] -= kin[f, 4]
    shade[f] = shade[j]
    stamp[f] = 2 * tick
    wake(j, mass, flag)
    wake(f, mass, flag)
    return True


@njit(cache=True)
def _shed(j, base, share, w, mass, kin, quad, heat, stats):
    """Radiation: the particle in cell j loses share x base of mass (rounded at random, so it averages out) as heat,
    taken from its children, largest quadrant first; it keeps at least 1. The heat is noted as a row of heat (x, y,
    vx, vy, mass) - the next free one, counted in stats[S_HEAT] - for the World to send out as heat particles. Nothing
    is shed when the rows are full."""
    loss = np.int64(base * share + np.random.random())
    m = np.int64(mass[j])
    k = stats[S_HEAT]
    if loss <= 0 or loss >= m or k >= heat.shape[0]:
        return
    left = loss
    while left > 0:
        c = 0
        for q in range(1, 4):
            if quad[j, q] > quad[j, c]:
                c = q
        take = min(left, np.int64(quad[j, c]))
        quad[j, c] -= take
        left -= take
    mass[j] = m - loss
    heat[k, 0] = j % w
    heat[k, 1] = j // w
    heat[k, 2] = kin[j, 0]
    heat[k, 3] = kin[j, 1]
    heat[k, 4] = loss
    stats[S_HEAT] = k + 1


# --- global orbit ------------------------------------------------------------------------------------

@njit(cache=True)
def orbit_accel(rx, ry, vx, vy, om, grip, vmin):
    """The global orbit's push on something at (rx, ry) from the centre moving at (vx, vy). It is nudged (grip)
    towards circling the centre at max(vmin, |om| r) - smoothly - in the orbit's direction (om > 0 clockwise on
    screen), which also damps drifting in or out, and given exactly the inward pull its own circling needs: nothing
    pulls a slow one in, so the universe turns without piling up in the middle, and nothing ever comes to rest."""
    r2 = rx * rx + ry * ry
    if r2 < 0.25:
        return 0.0, 0.0
    r = np.sqrt(r2)
    way = 1.0 if om > 0 else -1.0
    tx, ty = -ry / r * way, rx / r * way                 # unit tangent in the direction of turning
    target = np.sqrt(om * om * r2 + vmin * vmin)
    vt = max(vx * tx + vy * ty, 0.0)
    c = vt * vt / r                                      # exactly the inward pull its own circling needs
    return -c * rx / r + grip * (target * tx - vx), -c * ry / r + grip * (target * ty - vy)


@njit(cache=True)
def orbit_push(rx, ry, vx, vy, om, grip, vmin, whirls, host, share):
    """The global orbit's push on something at (rx, ry) from the centre moving at (vx, vy): its own (orbit_accel),
    or, bound to a super well (host >= 0: the row of whirls it is most tightly bound to, counting the orbit's shear
    against it: orbit_shear; share: bound_share), that well's push (whirls columns 11 and 12).
    So a well and all it holds turn with the universe together and their orbits round it are left alone - the
    orbit's own push, applied to each separately, braked every orbit towards its flow and pulled them all towards
    the centre."""
    ox, oy = 0.0, 0.0
    if share < 1.0:
        ox, oy = orbit_accel(rx, ry, vx, vy, om, grip, vmin)
    if host >= 0:
        ox += share * (whirls[host, 11] - ox)
        oy += share * (whirls[host, 12] - oy)
    return ox, oy


@njit(cache=True)
def orbit_shear(fx, fy, whirls, k):
    """The global orbit's shear between something where its flow is (fx, fy) and super well k (whirls columns 14 and
    15: the flow where the well is), as energy per unit mass: the flow pulls them apart with about this much, so it
    counts against how bound the thing is to the well - far out at the edge of the well's reach, barely bound, the
    orbit still turns it itself."""
    dx, dy = fx - whirls[k, 14], fy - whirls[k, 15]
    return 0.5 * (dx * dx + dy * dy)


@njit(cache=True)
def bound_share(e, phi):
    """Whether something is bound to a well, 1 or 0: e is its energy against the well (kinetic + potential + the
    orbit's shear, per unit mass), phi the well's potential there. (A share that rose with how bound it was, 1 only as
    bound as a circular orbit round a plain inverse-square pull, left stable orbits round a softened, fading pull -
    less bound than that - with part of the orbit's own push, which threw them out; the shear already stops matter
    barely bound far out at the edge of a well's reach from counting.)"""
    return 1.0 if e < 0.0 and phi < 0.0 else 0.0


@njit(cache=True)
def sg_block_at(x, y, w, h, sg_block, sg_w, c, s, ocx, ocy, wrap):
    """The self-gravity mesh block to read for something at (x, y). The mesh is binned only every few ticks; with the
    global orbit on, the matter has turned on with the universe since, by an angle whose cosine and sine are c and s,
    so the block read is where the matter now round (x, y) was then (else a clump carried round is held back by
    its own gravity, pulling it to where it was)."""
    if s != 0.0:
        rx, ry = x - ocx, y - ocy
        x = ocx + c * rx + s * ry
        y = ocy - s * rx + c * ry
        if wrap:
            x %= w
            y %= h
    return (min(max(int(y), 0), h - 1) // sg_block) * sg_w + min(max(int(x), 0), w - 1) // sg_block


@njit(cache=True)
def orbit_flow(rx, ry, om, vmin):
    """The velocity the global orbit carries things at (rx, ry) from the centre at (see orbit_accel): round the
    centre at max(vmin, |om| r) in the orbit's direction."""
    r2 = rx * rx + ry * ry
    if r2 < 0.25:
        return 0.0, 0.0
    r = np.sqrt(r2)
    k = np.sqrt(om * om * r2 + vmin * vmin) / r * (1.0 if om > 0 else -1.0)
    return -ry * k, rx * k


# --- the tick ----------------------------------------------------------------------------------------

@njit(cache=True)
def _pressure_push(x, y, m, hq, pressure, w, h, mass, kin, solid, wrap):
    """Heat pressure on the particle of mass m and heat hq in cell (x, y): each particle's pressure is its heat (as a
    2D gas's: energy per area, a cell each) x `pressure`, and each particle touching it on a side pushes it away with
    the two's mean pressure - equal and opposite, so momentum is kept; solid ground and the window's edge push back
    as hard as it pushes them. Evenly hot matter is pushed alike from every side and stays put; where it is hotter
    on one side, or open (a surface), it is pushed out: hot matter expands, its heat doing the work (_advance takes
    the energy of motion it gains out of hq), and a hot core holds up what lies on it. Returns the acceleration."""
    ax = ay = 0.0
    pi = max(hq, 0.0)
    for d in range(4):
        j = _cell(x + DX4[d], y + DY4[d], w, h, wrap)
        if j < 0 or solid[j]:
            pj = pi                                      # ground or the window's edge: as hard back
        elif mass[j] == 0:
            continue
        else:
            pj = max(np.float64(kin[j, 4]), 0.0)
        f = 0.5 * (pi + pj)
        ax -= f * DX4[d]
        ay -= f * DY4[d]
    return ax * pressure / m, ay * pressure / m


@njit(cache=True)
def _cap_speed(kin, j, vmax):
    """The particle in cell j, handed momentum by a heavier one that lost it against it (a star's: the "give" in
    _advance), is slowed to vmax if that sent it faster. The momentum a heavy particle loses would send a light one
    off at thousands of cells a tick, with energy that was never there (p^2 / 2m): it is not kept, as heat or
    otherwise."""
    v2 = np.float64(kin[j, 0]) ** 2 + np.float64(kin[j, 1]) ** 2
    if v2 > vmax * vmax:
        s = vmax / np.sqrt(v2)
        kin[j, 0] *= s
        kin[j, 1] *= s


@njit(cache=True)
def _rung(m):
    """Which rung a mass is (m = 2^rung), or -1 for a mass between rungs."""
    k = 0
    while (1 << k) < m:
        k += 1
    return k if (1 << k) == m else -1


@njit(cache=True)
def _binding(m, bind, peak, top, tail):
    """The binding energy a particle of rung mass m holds (0 for one between rungs): m x bind (the peak's, per unit
    of mass) x a share that rises as 1 - (1 - rung / peak)^2 to 1 at the peak rung, then falls by `tail` by the top
    rung. Fusing two of a rung into the next gives off the difference (_advance, heat_step)."""
    k = _rung(m)
    if k < 0:
        return 0.0
    if k <= peak:
        f = 1.0 - (1.0 - k / max(peak, 1.0)) ** 2
    else:
        f = 1.0 - tail * (k - peak) / max(top - peak, 1.0)
    return m * bind * f


@njit(cache=True)
def _barrier(ma, mb, k):
    """The barrier particles of masses ma and mb must get over to fuse (or a particle to break into them): k x ma mb
    / (ma^1/3 + mb^1/3) - it grows with their masses, so heavy rungs need hotter, faster matter."""
    return k * ma * mb / (ma ** (1.0 / 3.0) + mb ** (1.0 / 3.0))


@njit(cache=True)
def _fuse_energy(ma, mb, u2, qa, qb):
    """The energy two particles bring to fusing: their motion against each other (u2: relative speed squared) and
    their heat (qa, qb: their temperatures, heat per unit mass, counted for their reduced mass ma mb / (ma + mb))."""
    mu = ma * mb / (ma + mb)
    return mu * (0.5 * u2 + max(qa, 0.0) / ma + max(qb, 0.0) / mb)


@njit(cache=True)
def _tunnel(barrier, energy):
    """Whether something bringing `energy` gets over `barrier` this time: with a chance of exp(-barrier / energy) -
    never with none, more often the more it brings, the way fusion tunnels through a barrier."""
    return energy > 0.0 and np.random.random() < np.exp(-barrier / energy)


@njit(cache=True)
def _unkicked(gain, kick):
    """Heat gained (gain) less what of it is this tick's outside forces' kick still unspent (kick): a particle resting
    on another under gravity is kicked into it and stopped every tick, without moving - no work done, so no heat.
    Returns (the heat, the kick left)."""
    if gain <= 0.0 or kick <= 0.0:
        return gain, kick
    take = min(gain, kick)
    return gain - take, kick - take


@njit(cache=True)
def _pair_ke(m, vx, vy, mk, kin, j, rock, kvx, kvy):
    """The kinetic energy of a particle of mass m moving at (vx, vy) and the one of mass mk in cell j it has run
    into - or, for solid ground (rock) moving at (kvx, kvy), its own against the ground."""
    if rock:
        return 0.5 * m * ((vx - kvx) ** 2 + (vy - kvy) ** 2)
    return 0.5 * m * (vx * vx + vy * vy) + 0.5 * mk * (np.float64(kin[j, 0]) ** 2 + np.float64(kin[j, 1]) ** 2)


@njit(cache=True)
def _heat_loss(e0, m, vx, vy, mk, kin, j, rock, kvx, kvy):
    """A contact has ended: the kinetic energy it lost since it was e0 (_pair_ke) becomes heat, shared by mass - the
    other particle's share added to its heat here, the moving one's returned (all of it against solid ground). Some
    contact rules hand out a little energy instead (a jammed particle counts as standing still, whatever velocity it
    holds): that comes out of their heat, so kinetic energy + heat is kept exactly. A particle's heat can dip a
    little below 0 for a moment that way (in a crash, ~0.5% of them for ~25 ticks), until conduction evens it out."""
    loss = e0 - _pair_ke(m, vx, vy, mk, kin, j, rock, kvx, kvy)
    if rock:
        return loss
    kin[j, 4] += loss * mk / (m + mk)
    return loss * m / (m + mk)


@njit(cache=True)
def _advance(order, t0, t1, w, h, tick, P, mass, kin, quad, shade, stamp, flag, fx, fy, sgx, sgy, sg_block, sg_w,
             hole, absorbed, solid, gvx, gvy, whirls, stars, sfx, sfy, s_block, s_cw, s_ch, owner, star_v, star_f,
             stats, blob, blob_v, heat):
    """Simulate the particles in cells order[t0:t1], in that order, for one tick (see step): move each, collide it
    with what is in its way, and wake what it disturbs. Merging and splitting shed P_HEAT of the mass as heat
    (_shed, into heat)."""
    vmax = P[P_VMAX]
    vmax2 = vmax * vmax
    pressure = P[P_PRESSURE]
    max_steps = int(P[P_MAX_STEPS])
    wall_e = P[P_WALL_E]
    e = P[P_E]
    impact_min = P[P_IMPACT_MIN]
    slide_damp = P[P_SLIDE_DAMP]
    sink = P[P_SINK]
    drag = P[P_DRAG]
    eps2 = P[P_SLEEP_EPS] * P[P_SLEEP_EPS]
    accel_eps2 = P[P_SLEEP_ACCEL] * P[P_SLEEP_ACCEL]
    child_moves = int(P[P_CHILD_MOVES])
    child_every = max(1, int(P[P_CHILD_EVERY]))
    slosh = P[P_SLOSH]
    lean = P[P_LEAN]
    merge_on = P[P_MERGE_ON] != 0.0                  # fusion and fission (see _binding, _tunnel)
    max_mass = int(P[P_MAX_MASS])
    split_on = P[P_SPLIT_ON] != 0.0
    f_bind, f_peak, f_top, f_tail, f_barrier = P[P_FUSE_BIND], P[P_FUSE_PEAK], P[P_FUSE_TOP], P[P_FUSE_TAIL], P[P_BARRIER]
    scatter = P[P_SCATTER]
    kinv = P[P_REACH]                                # 1 / how far gravity reaches (0: all the way)
    sg_c, sg_s = P[P_SG_COS], P[P_SG_SIN]            # how far the universe has turned since the mesh was binned
    sg_on = P[P_SG_ON] != 0.0
    orbit_w = P[P_ORBIT_W]
    orbit_grip = P[P_ORBIT_GRIP]
    orbit_vmin = P[P_ORBIT_VMIN]
    ocx, ocy = P[P_ORBIT_CX], P[P_ORBIT_CY]
    wrap = P[P_WRAP] != 0.0

    for t in range(t0, t1):
        i0 = order[t]
        if stamp[i0] >> 1 == tick or mass[i0] == 0:
            continue                                     # already simulated this tick, or merged away
        # Lift the particle into locals; while it travels only mass[] tracks its cell, the other rows are
        # written once at the end. Cells it merely passes through need no waking: they were empty before and after.
        m = np.int64(mass[i0])
        x, y = i0 % w, i0 // w
        q0, q1 = np.int64(quad[i0, 0]), np.int64(quad[i0, 1])
        q2, q3 = np.int64(quad[i0, 2]), np.int64(quad[i0, 3])
        sh = shade[i0]
        own = owner[i0]                                  # its star (0: none)
        vx0, vy0, ox0, oy0 = kin[i0, 0], kin[i0, 1], kin[i0, 2], kin[i0, 3]
        hq = np.float64(kin[i0, 4])                      # its heat: gains whatever kinetic energy its contacts lose

        # forces: external field + self-gravity + the children's lean
        ax = np.float64(fx[i0])
        ay = np.float64(fy[i0])
        if sg_on or own > 0:
            b = sg_block_at(x, y, w, h, sg_block, sg_w, sg_c, sg_s, ocx, ocy, wrap)
            ax += sgx[b]
            ay += sgy[b]
        if child_moves > 0 and (tick + i0) % child_every == 0:
            q0, q1, q2, q3 = _slosh(q0, q1, q2, q3, m, ax, ay, child_moves, slosh)
        if lean != 0.0:
            ax += lean * ((q1 + q3) - (q0 + q2)) / m
            ay += lean * ((q2 + q3) - (q0 + q1)) / m
        whirled = False                                  # inside a whirlpool: never sleeps or sticks
        turn = carry_x = carry_y = 0.0                   # how far turning space turns and carries it this tick
        host, e_host, phi_host = -1, 0.0, 0.0            # the super well it is most tightly bound to (orbit_push)
        flx, fly = orbit_flow(x - ocx, y - ocy, orbit_w, orbit_vmin) if orbit_w != 0.0 else (0.0, 0.0)
        for k in range(whirls.shape[0]):                 # each super well: its pull, exact from where it is now (it
            rx_, ry_ = _axis(x, whirls[k, 0], w, wrap), _axis(y, whirls[k, 1], h, wrap)   # isn't on the field),
            gx_, gy_, phi_ = _pull(-rx_, -ry_, whirls[k, 4], whirls[k, 5], kinv)            # its whirlpool and the
            if own == 0:                                 # the well feels its pull back (stars pull as wholes)
                kw = int(whirls[k, 13])
                absorbed[kw, 3] -= m * gx_
                absorbed[kw, 4] -= m * gy_
            e_ = 0.5 * ((vx0 - whirls[k, 9]) ** 2 + (vy0 - whirls[k, 10]) ** 2) + phi_
            if orbit_w != 0.0:
                e_ += orbit_shear(flx, fly, whirls, k)
            if e_ < e_host:
                host, e_host, phi_host = k, e_, phi_
            ax += gx_                                    # space it turns
            ay += gy_
            om_ = frame_turn(rx_, ry_, whirls[k, 6], whirls[k, 7], whirls[k, 5], kinv, vmax)
            whirled = whirled or om_ * om_ * (rx_ * rx_ + ry_ * ry_) > eps2   # carried round: it doesn't sleep
            if om_ != 0.0 and own == 0:                  # (a star's particles are carried with it: carry_stars)
                cx_, cy_ = frame_carry(rx_, ry_, om_)
                carry_x += cx_
                carry_y += cy_
                turn += om_
        if orbit_w != 0.0:
            ox_, oy_ = orbit_push(x - ocx, y - ocy, vx0, vy0, orbit_w, orbit_grip, orbit_vmin, whirls, host,
                                  bound_share(e_host, phi_host))
            ax += ox_
            ay += oy_
        if stars.shape[0] > 0:
            sx_, sy_, px_, py_ = _star_pull(x, y, own, stars, sfx, sfy, s_block, s_cw, s_ch, w, h, wrap, kinv)
            if _held_up(x, y, own, px_, py_, w, h, mass, owner, wrap) >= 0:
                # the particle of its star it rests on pushes back (a normal force) only against what presses it in:
                # its star's pull plus the outside pull relative to how the star as a whole accelerates (a tide).
                # Without an outward tug that is the whole of its star's pull, so a star keeps its shape, still or
                # moving; a tide pulling it outwards is held by that pull, and lifts it off only when stronger
                p_ = np.sqrt(px_ * px_ + py_ * py_)
                nx_, ny_ = px_ / p_, py_ / p_
                press = p_ + (ax + sx_ - px_ - star_v[own - 1, 4]) * nx_ + (ay + sy_ - py_ - star_v[own - 1, 5]) * ny_
                press = min(max(press, 0.0), p_)
                sx_ -= press * nx_
                sy_ -= press * ny_
                star_f[own - 1, 0] += m * (px_ - press * nx_)    # what is left of its star's pull acts on it
                star_f[own - 1, 1] += m * (py_ - press * ny_)
            elif own > 0:
                star_f[own - 1, 0] += m * px_
                star_f[own - 1, 1] += m * py_
            if own > 0:
                star_f[own - 1, 2] += m
                sx_ += star_v[own - 1, 2]
                sy_ += star_v[own - 1, 3]
            ax += sx_
            ay += sy_

        # the energy of motion this tick's outside forces (gravity, the orbit, ...) hand it: if what is in the way
        # takes it straight back, they did no work - it hasn't moved - and it isn't heat (_unkicked)
        kicked = max(0.0, 0.5 * m * ((vx0 + ax) ** 2 + (vy0 + ay) ** 2 - vx0 * vx0 - vy0 * vy0))
        if pressure != 0.0:                              # heat pressure (_pressure_push): the energy of motion it
            pax, pay = _pressure_push(x, y, m, hq, pressure, w, h, mass, kin, solid, wrap)   # adds comes out of its
            vax, vay = vx0 + ax, vy0 + ay                # heat - and goes back to it if what is in the way stops it -
            # at most half its heat a tick: a tick is coarse for hot matter, whose push in one would outrun its heat
            de = 0.5 * m * (2.0 * (vax * pax + vay * pay) + pax * pax + pay * pay)
            room = 0.5 * max(hq, 0.0)
            if de > room:
                p2 = pax * pax + pay * pay
                b = vax * pax + vay * pay
                f = (-b + np.sqrt(b * b + 2.0 * room * p2 / m)) / p2 if p2 > 0.0 else 0.0
                pax *= f
                pay *= f
                de = room
            hq -= de
            ax += pax
            ay += pay
        vx = vx0 + ax
        vy = vy0 + ay
        if turn != 0.0:                                  # turning space turns which way it is heading too
            tc, ts = np.cos(turn), np.sin(turn)
            vx, vy = tc * vx - ts * vy, ts * vx + tc * vy
        if drag > 0.0:
            vx *= 1.0 - drag
            vy *= 1.0 - drag
        v2 = vx * vx + vy * vy
        if v2 > vmax2:
            s = vmax / np.sqrt(v2)
            vx *= s
            vy *= s
            g_, kicked = _unkicked(0.5 * m * (v2 - vmax2), kicked)   # nothing goes faster than light: the rest is heat
            hq += g_
        ox = ox0 + vx + carry_x                          # its own motion, and space carrying it
        oy = oy0 + vy + carry_y
        if own > 0:                                      # in a star: only its motion relative to the star
            ox -= star_v[own - 1, 0]
            oy -= star_v[own - 1, 1]
        elif blob_v[blob[i0], 2] != 0.0:                 # in a blob carried by the orbit: likewise
            ox -= blob_v[blob[i0], 0]
            oy -= blob_v[blob[i0], 1]

        i = i0
        moved = blocked = stay = False
        alive = True
        for _ in range(max_steps):
            sx = 1 if ox >= 0.5 else (-1 if ox <= -0.5 else 0)
            sy = 1 if oy >= 0.5 else (-1 if oy <= -0.5 else 0)
            if sx == 0 and sy == 0:
                break
            nx, ny = x + sx, y + sy
            if wrap:                                     # continuous borders: carry on from the other side
                nx %= w
                ny %= h
            # The window edge: bounce, or when the force presses the particle against it, rest there with static
            # friction. One tick's worth of pressing acceleration is resting contact, not an impact.
            if nx < 0 or nx >= w:
                press = max(0.0, ax * sx)
                impact = impact_min + press
                ke_ = vx * vx + vy * vy
                vx = -vx * wall_e if abs(vx) > impact else 0.0
                if press > 0.0 and abs(vy) < impact:
                    vy = 0.0
                g_, kicked = _unkicked(0.5 * m * (ke_ - vx * vx - vy * vy), kicked)
                hq += g_
                ox = 0.49 * sx
                blocked = True
                continue
            if ny < 0 or ny >= h:
                press = max(0.0, ay * sy)
                impact = impact_min + press
                ke_ = vx * vx + vy * vy
                vy = -vy * wall_e if abs(vy) > impact else 0.0
                if press > 0.0 and abs(vx) < impact:
                    vx = 0.0
                g_, kicked = _unkicked(0.5 * m * (ke_ - vx * vx - vy * vy), kicked)
                hq += g_
                oy = 0.49 * sy
                blocked = True
                continue
            j = ny * w + nx
            if hole[j]:                                  # into a super well's core: absorbed
                _absorb(absorbed, hole[j] - 1, m, vx, vy, nx, ny)
                mass[i] = 0
                owner[i] = 0
                wake_around(i, w, h, mass, flag, wrap)
                stats[S_ABSORBED] += 1
                alive = False
                break
            rock = solid[j] != 0
            if mass[j] == 0 and not rock:                # free: move
                mass[i] = 0
                mass[j] = m
                owner[i] = 0
                owner[j] = own
                i, x, y = j, nx, ny
                ox -= sx
                oy -= sy
                moved = True
                continue

            # Occupied by a particle or a solid well's ground. Velocities below are relative to what is in the
            # way, so particles flowing together (an orbiting ring) don't brake each other; a jammed particle,
            # like the ground, counts as standing still, whatever velocity it holds - or, in a star, as moving
            # with the star, so a star travels as one, and with the global orbit on, as turning with the universe,
            # so a packed clump is carried round as one instead of being held still by its own friction.
            if rock:                                     # the ground moves with its well's spin
                mk = np.int64(0)
                kvx, kvy = np.float64(gvx[j]), np.float64(gvy[j])
            else:
                mk = np.int64(mass[j])
                if stamp[j] & 1:
                    o = owner[j]
                    if o > 0:
                        kvx, kvy = star_v[o - 1, 0], star_v[o - 1, 1]
                    elif blob_v[blob[j], 2] != 0.0:
                        kvx, kvy = blob_v[blob[j], 0], blob_v[blob[j], 1]
                    elif orbit_w != 0.0:
                        kvx, kvy = orbit_flow(nx - ocx, ny - ocy, orbit_w, orbit_vmin)
                    else:
                        kvx = kvy = 0.0
                else:
                    kvx, kvy = np.float64(kin[j, 0]), np.float64(kin[j, 1])
            inv_len = 0.7071067811865476 if sx != 0 and sy != 0 else 1.0
            nxn, nyn = sx * inv_len, sy * inv_len
            u = (vx - kvx) * nxn + (vy - kvy) * nyn
            if u <= 0.0:
                break                                    # the one ahead is pulling away: wait behind it
            # the pair's kinetic energy now (against the ground for solid ground, which takes any momentum): what
            # the contact below loses of it (or gains), however it ends, goes to their heat (_heat_loss)
            e0 = _pair_ke(m, vx, vy, mk, kin, j, rock, kvx, kvy)
            press = max(0.0, ax * nxn + ay * nyn)        # how hard the force pushes it into the other one
            impact = impact_min + press
            if rock:
                if u > impact:                           # bounce off the ground
                    vx -= (1.0 + wall_e) * u * nxn
                    vy -= (1.0 + wall_e) * u * nyn
                    g_, kicked = _unkicked(_heat_loss(e0, m, vx, vy, mk, kin, j, rock, kvx, kvy), kicked)
                    hq += g_
                    blocked = True
                    break
            else:
                total = m + mk
                if press > 0.0 and m > mk and own == 0 and owner[j] == 0:
                    stay = True                          # a heavier particle keeps trying to sink (sand.py)

                # fusion and fission happen in collisions (and, between touching particles at rest, in heat_step):
                # the energy the two bring - their motion against each other and their heat - against the barrier
                # (_tunnel), and enough of it for what a break costs or a fusion past the peak takes (_binding).
                # Resting and slow contacts just push. A collision that breaks a particle doesn't also fuse.
                split = False
                ef = _fuse_energy(m, mk, u * u, hq, kin[j, 4]) if u > impact else 0.0
                if u > impact:
                    if split_on and mk >= 2 and _rung(mk) > 0:
                        cost = _binding(mk, f_bind, f_peak, f_top, f_tail) - \
                            2.0 * _binding(mk // 2, f_bind, f_peak, f_top, f_tail)   # (< 0 past the peak: it gives)
                        if ef > cost and _tunnel(_barrier(mk // 2, mk // 2, f_barrier), ef):
                            kin[j, 4] -= cost                    # what breaking it takes comes out of its heat
                            if _split(j, w, h, tick, mass, kin, quad, shade, stamp, flag, solid, wrap):
                                stats[S_SPLITS] += 1
                                split = True
                                mk = np.int64(mass[j])
                                total = m + mk
                                e0 = _pair_ke(m, vx, vy, mk, kin, j, rock, kvx, kvy)
                            else:
                                kin[j, 4] += cost                # no room to break into: it stays whole
                    # 1D collision with restitution e (momentum conserved) along the step direction - for loose
                    # particles tilted by a random angle up to scatter, as if they met a little off-centre, so a
                    # stream glances off what it hits instead of queueing up in a line behind it
                    cnx, cny, cu = nxn, nyn, u
                    if scatter > 0.0 and own == 0 and owner[j] == 0:
                        a = (2.0 * np.random.random() - 1.0) * scatter
                        ca, sa = np.cos(a), np.sin(a)
                        tnx, tny = nxn * ca - nyn * sa, nxn * sa + nyn * ca
                        tu = (vx - kvx) * tnx + (vy - kvy) * tny
                        if tu > 0.0:
                            cnx, cny, cu = tnx, tny, tu
                    du_i = -(1.0 + e) * mk * cu / total
                    du_k = (1.0 + e) * m * cu / total
                    vx += du_i * cnx
                    vy += du_i * cny
                    kin[j, 0] += du_k * cnx
                    kin[j, 1] += du_k * cny
                    if own > 0 or owner[j] > 0:
                        kvx += du_k * nxn                # when a star's particle is in it the bounce is kept, so a
                        kvy += du_k * nyn                # star keeps its momentum and moves as one
                    wake(j, mass, flag)
                    stats[S_COLLISIONS] += 1

                q_ = 0.0
                fuse = merge_on and not split and u > impact and m == mk and total <= max_mass and _rung(m) >= 0
                if fuse:                                 # the same rung: they may fuse into the next one up
                    q_ = _binding(total, f_bind, f_peak, f_top, f_tail) - 2.0 * _binding(m, f_bind, f_peak, f_top,
                                                                                         f_tail)
                    fuse = ef + q_ >= 0.0 and _tunnel(_barrier(m, m, f_barrier), ef)
                if fuse:
                    kin[j, 0] = (m * vx + mk * kin[j, 0]) / total
                    kin[j, 1] = (m * vy + mk * kin[j, 1]) / total
                    g_, kicked = _unkicked(e0 - 0.5 * total * (kin[j, 0] ** 2 + kin[j, 1] ** 2), kicked)
                    kin[j, 4] += hq + g_ + q_            # the binding energy it gives off (or takes) is heat
                    mass[j] = total
                    quad[j, 0] += q0
                    quad[j, 1] += q1
                    quad[j, 2] += q2
                    quad[j, 3] += q3
                    mass[i] = 0
                    owner[i] = 0
                    wake_around(i, w, h, mass, flag, wrap)
                    wake(j, mass, flag)
                    stats[S_MERGES] += 1
                    alive = False
                    break

                if (press > 0.0 and m > mk and own == 0 and owner[j] == 0
                        and np.random.random() < sink * (1.0 - mk / m)):
                    # pressed by the force, a heavier particle pushes through the lighter one, which takes its place
                    # (and is done this tick). Stars' particles layer by star_sink instead, keeping momentum.
                    vx = kvx + (vx - kvx) * 0.5
                    vy = kvy + (vy - kvy) * 0.5
                    mass[i] = mass[j]
                    for c in range(KIN):
                        kin[i, c] = kin[j, c]
                    for c in range(4):
                        quad[i, c] = quad[j, c]
                    shade[i] = shade[j]
                    stamp[i] = 2 * tick
                    owner[i] = owner[j]
                    wake(i, mass, flag)
                    g_, kicked = _unkicked(e0 - 0.5 * m * (vx * vx + vy * vy) - 0.5 * mk * (kin[i, 0] ** 2 + kin[i, 1] ** 2),
                                         kicked)
                    hq += g_
                    mass[j] = m
                    owner[j] = own
                    i, x, y = j, nx, ny
                    ox -= sx
                    oy -= sy
                    moved = True
                    stats[S_SINKS] += 1
                    break

            # sliding off or held by what is in the way changes the velocity: when a star's particle is in it, what it
            # loses goes to the other one, so stars keep their momentum
            pvx, pvy = vx, vy
            give = mk > 0 and (own > 0 or owner[j] > 0)
            d = DIR_OF[(sy + 1) * 3 + sx + 1]
            e2 = _slide_target(x, y, d, w, h, mass, solid, wrap)
            if e2 >= 0:
                tx, ty = (x + DX[e2]) % w, (y + DY[e2]) % h
                j2 = ty * w + tx
                mass[i] = 0
                mass[j2] = m
                owner[i] = 0
                owner[j2] = own
                i, x, y = j2, tx, ty
                # keep the offset only along axes the particle wanted to travel anyway
                if DX[e2] != 0:
                    ox = ox - DX[e2] if DX[e2] * ox >= 0.5 else 0.0
                if DY[e2] != 0:
                    oy = oy - DY[e2] if DY[e2] * oy >= 0.5 else 0.0
                vx = kvx + (vx - kvx) * slide_damp
                vy = kvy + (vy - kvy) * slide_damp
                if give:
                    kin[j, 0] -= m * (vx - pvx) / mk
                    kin[j, 1] -= m * (vy - pvy) / mk
                    _cap_speed(kin, j, vmax)
                    wake(j, mass, flag)
                g_, kicked = _unkicked(_heat_loss(e0, m, vx, vy, mk, kin, j, rock, kvx, kvy), kicked)
                hq += g_
                moved = True
                continue

            # blocked: drop whatever relative velocity still points into the obstacle
            vn = (vx - kvx) * nxn + (vy - kvy) * nyn
            if vn > 0.0:
                vx -= vn * nxn
                vy -= vn * nyn
            rx, ry = vx - kvx, vy - kvy
            if press > 0.0 and rx * rx + ry * ry < impact * impact and not whirled:
                vx, vy = kvx, kvy                        # static friction: resting contact holds still
            if give:
                kin[j, 0] -= m * (vx - pvx) / mk
                kin[j, 1] -= m * (vy - pvy) / mk
                _cap_speed(kin, j, vmax)
                wake(j, mass, flag)
            g_, kicked = _unkicked(_heat_loss(e0, m, vx, vy, mk, kin, j, rock, kvx, kvy), kicked)
            hq += g_
            blocked = True
            break

        if alive and hole[i]:                            # slid or was put into a core
            _absorb(absorbed, hole[i] - 1, m, vx, vy, x, y)
            mass[i] = 0
            owner[i] = 0
            wake_around(i, w, h, mass, flag, wrap)
            stats[S_ABSORBED] += 1
            alive = False
        if moved:
            stats[S_MOVED] += 1
            wake_around(i0, w, h, mass, flag, wrap)   # the cell it left
        if not alive:
            continue
        kin[i, 0] = vx
        kin[i, 1] = vy
        kin[i, 2] = _clamp_offset(ox)
        kin[i, 3] = _clamp_offset(oy)
        kin[i, 4] = hq
        quad[i, 0] = q0
        quad[i, 1] = q1
        quad[i, 2] = q2
        quad[i, 3] = q3
        shade[i] = sh
        stamp[i] = 2 * tick + (1 if blocked else 0)
        if moved or stay or whirled or turn != 0.0 or vx * vx + vy * vy > eps2 or (not blocked and ax * ax + ay * ay > accel_eps2):
            wake(i, mass, flag)


@njit(cache=True)
def _sort_by_bucket(cur, base, n, bucket, bucket_counts, order, tick):
    """Stable counting sort of the cells cur[base:base + n] by potential bucket into order[base:base + n]; on even
    ticks each bucket is filled back to front (reversed memory order), so neither side is favoured."""
    nb = bucket_counts.size - 1
    bucket_counts[:] = 0
    for t in range(base, base + n):
        bucket_counts[bucket[cur[t]] + 1] += 1
    for b in range(nb):
        bucket_counts[b + 1] += bucket_counts[b]
    if tick & 1:
        for t in range(base, base + n):
            b = bucket[cur[t]]
            order[base + bucket_counts[b]] = cur[t]
            bucket_counts[b] += 1
    else:                                                # fill each bucket back to front: reversed memory order
        for b in range(nb):
            bucket_counts[b] = bucket_counts[b + 1]
        for t in range(base, base + n):
            b = bucket[cur[t]]
            bucket_counts[b] -= 1
            order[base + bucket_counts[b]] = cur[t]


@njit(cache=True)
def step(w, h, tick, P, mass, kin, quad, shade, stamp, flag, cur, order, bucket_counts, bucket, fx, fy, sgx, sgy,
         sg_block, sg_w, hole, absorbed, solid, gvx, gvy, whirls, stars, sfx, sfy, s_block, s_cw, s_ch, owner,
         star_v, star_f, stats, blob, blob_v, heat):
    """Advance one tick: simulate the awake particles and flag the ones that stay awake. Returns how many ran.
    Heat shed by merging and splitting is noted in heat's first stats[S_HEAT] rows (see _shed).
    Mass swallowed by super well k is added to absorbed[k]. whirls holds each super well's whirlpool (rows of x, y,
    range, spin, pull strength, softening, the share of circling speed it turns space at - signed by its spin - how
    far that reaches, and its point of no return: see World.whirls); stars, sfx and sfy the stars' pull (see _star_pull); star_v[k] star k's
    velocity as it will be after this tick (and star_v[k, 4:6] its acceleration, for the normal force that holds a
    particle resting on another of its star against a tide). A star's particles (owner, which follows them as they move) only move
    here as fast as they move relative to it: star_shift carries the star as a whole. Jammed, they count as moving
    with it. A star's pull on its own particles has no reaction, so
    what it adds up to is taken back: star_v[k, 2:4] is added to each of star k's particles (the last tick's total
    over their mass), and this tick's total pull and the mass it acted on are summed into star_f[k]. Stars' particles
    feel self-gravity (the pull of the matter that belongs to no star) even when it is off for the rest, so a star
    is pulled back by what it pulls. Likewise blob[i] is the blob the particle starting in cell i belongs to (see
    carry_blobs) and blob_v[b] its velocity and whether the global orbit carries it (1): if so its particles only move
    here as fast as they move relative to it, and jammed, they count as moving with it.

    Particles are processed lowest potential first (bucket[i] is the cell's potential rank), which generalises
    sand.py's "leading grains first" ordering to any field. Within a bucket they go in memory order, which keeps
    memory access mostly sequential; the direction alternates every tick so neither side is favoured.
    """
    # gather the awake cells in memory order, then stable counting sort by potential bucket
    n = 0
    for k in range(mass.size):
        if flag[k]:
            flag[k] = 0
            if mass[k] != 0:
                cur[n] = k
                n += 1
    _sort_by_bucket(cur, 0, n, bucket, bucket_counts, order, tick)
    _advance(order, 0, n, w, h, tick, P, mass, kin, quad, shade, stamp, flag, fx, fy, sgx, sgy, sg_block, sg_w, hole,
             absorbed, solid, gvx, gvy, whirls, stars, sfx, sfy, s_block, s_cw, s_ch, owner, star_v, star_f, stats,
             blob, blob_v, heat)
    return n


@njit(cache=True)
def _sort_by_key(cur, base, n, bucket, order, tick):
    """_sort_by_bucket's order, by sorting keys (bucket, then place in memory order): far cheaper for a few cells
    than walking every bucket."""
    keys = np.empty(n, np.int64)
    for t in range(n):
        keys[t] = np.int64(bucket[cur[base + t]]) * n + (t if tick & 1 else n - 1 - t)
    keys.sort()
    for t in range(n):
        p = keys[t] % n
        order[base + t] = cur[base + (p if tick & 1 else n - 1 - p)]


@njit(cache=True)
def _tile(t, nx, ny, w, h):
    """Tile t's columns c0..c1 and rows r0..r1 (before the cut) and where its cells start in cur and order."""
    a, b = t % nx, t // nx
    c0, c1 = a * w // nx, (a + 1) * w // nx
    r0, r1 = b * h // ny, (b + 1) * h // ny
    return c0, c1, r0, r1, r0 * w + c0 * (r1 - r0)


@njit(cache=True, parallel=True)
def step_tiles(w, h, tick, P, nx, ny, cut_x, cut_y, mass, kin, quad, shade, stamp, flag, cur, order, bucket, fx, fy,
               sgx, sgy, sg_block, sg_w, hole, absorbed, solid, gvx, gvy, whirls, stars, sfx, sfy, s_block, s_cw, s_ch,
               owner, star_v, star_f, stats, counts, blob, blob_v, heat):
    """step() on all cores. The universe is cut into nx x ny tiles (each count 1 or even; nx x 1 is strips of
    columns), starting cut_x / cut_y cells along. Every tile is gathered and sorted as step() does the whole universe;
    then the tiles run in up to four rounds - even columns of tiles in even rows, odd columns in even rows, and so on -
    side by side within a round. A particle reaches at most MAX_STEPS + 1 cells from where it starts (moving, sliding,
    splitting, waking), so with tiles at least 2 x (MAX_STEPS + 2) across, two tiles in the same round, a whole tile
    apart, never touch the same cell. One that crosses into a tile still to run has already run this tick (its
    stamp), as in step(). Tile t collects its own absorbed[t], star_f[t], stats[t] and heat[t] rows (the caller adds
    them up) and counts[t] particles. Returns how many ran. Tiles carry very different loads, so call it with
    numba.set_parallel_chunksize(1): threads then take the next tile as they finish one."""
    for t in prange(nx * ny):
        c0, c1, r0, r1, base = _tile(t, nx, ny, w, h)
        n = 0
        for r in range(r0, r1):
            row = ((r + cut_y) % h) * w
            for c in range(c0, c1):
                k = row + (c + cut_x) % w
                if flag[k]:
                    flag[k] = 0
                    if mass[k] != 0:
                        cur[base + n] = k
                        n += 1
        _sort_by_key(cur, base, n, bucket, order, tick)
        counts[t] = n
        absorbed[t, :, :] = 0
        star_f[t, :, :] = 0.0
        stats[t, :] = 0
    mx, my = max(1, nx // 2), max(1, ny // 2)            # tiles per round along each axis
    for rnd in range(4):
        px, py = rnd & 1, rnd >> 1
        if (px and nx == 1) or (py and ny == 1):
            continue
        for p in prange(mx * my):
            t = (2 * (p // mx) + py if ny > 1 else 0) * nx + (2 * (p % mx) + px if nx > 1 else 0)
            base = _tile(t, nx, ny, w, h)[4]
            _advance(order, base, base + counts[t], w, h, tick, P, mass, kin, quad, shade, stamp, flag, fx, fy, sgx,
                     sgy, sg_block, sg_w, hole, absorbed[t], solid, gvx, gvy, whirls, stars, sfx, sfy, s_block, s_cw,
                     s_ch, owner, star_v, star_f[t], stats[t], blob, blob_v, heat[t])
    return counts.sum()


# --- clumps -----------------------------------------------------------------------------------------

@njit(cache=True)
def label_clumps(mass, w, h, labels, stack):
    """Number each clump of touching particles (8-neighbours, not across a wrapped border): labels[i] = 1, 2, ...
    for occupied cells, 0 for empty ones. Returns how many clumps there are."""
    labels[:] = 0
    n = 0
    for s in range(mass.size):
        if mass[s] == 0 or labels[s] != 0:
            continue
        n += 1
        labels[s] = n
        top = 0
        stack[top] = s
        top += 1
        while top > 0:
            top -= 1
            i = stack[top]
            x, y = i % w, i // w
            for dy in range(-1, 2):
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                for dx in range(-1, 2):
                    xx = x + dx
                    if xx < 0 or xx >= w:
                        continue
                    j = yy * w + xx
                    if mass[j] != 0 and labels[j] == 0:
                        labels[j] = n
                        stack[top] = j
                        top += 1
    return n


# --- ghosts ----------------------------------------------------------------------------------------
# Particles poured with shift+click live off the grid for a while: free points that feel gravity (wells, global
# gravity, the orbit, whirlpools and the self-gravity of the grid's particles, not of each other) but collide with
# nothing, so a fresh pour can't pile up and collapse. Then they land in the nearest free cell.

@njit(cache=True)
def _ghost_cell(gx, gy, w, h):
    x = min(max(int(np.floor(gx + 0.5)), 0), w - 1)
    y = min(max(int(np.floor(gy + 0.5)), 0), h - 1)
    return y * w + x


@njit(cache=True)
def _move_ghosts(k0, k1, gx, gy, gvx, gvy, gm, gage, w, h, P, fx, fy, sgx, sgy, sg_block, sg_w, hole, hit, whirls,
                 stars, sfx, sfy, s_block, s_cw, s_ch, react):
    """Move ghosts k0 to k1 - 1 one tick (see step_ghosts). hit[k] becomes the hole number of the super well core
    ghost k crossed (where it stopped), else 0. react[well] adds up the ghosts' pull back on each super well."""
    vmax = P[P_VMAX]
    drag = P[P_DRAG]
    wall_e = P[P_WALL_E]
    wrap = P[P_WRAP] != 0.0
    sg_on = P[P_SG_ON] != 0.0
    orbit_w = P[P_ORBIT_W]
    ocx, ocy = P[P_ORBIT_CX], P[P_ORBIT_CY]
    for k in range(k0, k1):
        hit[k] = 0
        if gm[k] == 0:
            continue
        s0 = np.sqrt(gvx[k] * gvx[k] + gvy[k] * gvy[k])   # (faster than vmax: light - see below)
        i = _ghost_cell(gx[k], gy[k], w, h)
        ax = np.float64(fx[i])
        ay = np.float64(fy[i])
        if sg_on:
            b = sg_block_at(i % w, i // w, w, h, sg_block, sg_w, P[P_SG_COS], P[P_SG_SIN], ocx, ocy, wrap)
            ax += sgx[b]
            ay += sgy[b]
        turn = carry_x = carry_y = 0.0
        host, e_host, phi_host = -1, 0.0, 0.0
        flx, fly = orbit_flow(gx[k] - ocx, gy[k] - ocy, orbit_w, P[P_ORBIT_VMIN]) if orbit_w != 0.0 else (0.0, 0.0)
        for j in range(whirls.shape[0]):                 # each super well's exact pull and whirlpool, and the space
            rx_, ry_ = _axis(gx[k], whirls[j, 0], w, wrap), _axis(gy[k], whirls[j, 1], h, wrap)   # it turns
            px_, py_, phi_ = _pull(-rx_, -ry_, whirls[j, 4], whirls[j, 5], P[P_REACH])
            kw = int(whirls[j, 13])
            react[kw, 0] -= gm[k] * px_
            react[kw, 1] -= gm[k] * py_
            e_ = 0.5 * ((gvx[k] - whirls[j, 9]) ** 2 + (gvy[k] - whirls[j, 10]) ** 2) + phi_
            if orbit_w != 0.0:
                e_ += orbit_shear(flx, fly, whirls, j)
            if e_ < e_host:
                host, e_host, phi_host = j, e_, phi_
            ax += px_
            ay += py_
            om_ = frame_turn(rx_, ry_, whirls[j, 6], whirls[j, 7], whirls[j, 5], P[P_REACH], vmax)
            if om_ != 0.0:
                cx_, cy_ = frame_carry(rx_, ry_, om_)
                carry_x += cx_
                carry_y += cy_
                turn += om_
        if orbit_w != 0.0:
            ox_, oy_ = orbit_push(gx[k] - ocx, gy[k] - ocy, gvx[k], gvy[k], orbit_w, P[P_ORBIT_GRIP],
                                  P[P_ORBIT_VMIN], whirls, host, bound_share(e_host, phi_host))
            ax += ox_
            ay += oy_
        if stars.shape[0] > 0:
            sx_, sy_, _, _ = _star_pull(gx[k], gy[k], 0, stars, sfx, sfy, s_block, s_cw, s_ch, w, h, wrap, P[P_REACH])
            ax += sx_
            ay += sy_
        vx = (gvx[k] + ax) * (1.0 - drag)
        vy = (gvy[k] + ay) * (1.0 - drag)
        if turn != 0.0:                                  # turning space turns which way it is heading too
            tc, ts = np.cos(turn), np.sin(turn)
            vx, vy = tc * vx - ts * vy, ts * vx + tc * vy
        v = np.sqrt(vx * vx + vy * vy)
        if s0 > vmax * (1.0 + 1e-9):                     # light (only it outruns matter): it flies at its own speed,
            vx *= s0 / max(v, 1e-12)                     #   gravity only turning it
            vy *= s0 / max(v, 1e-12)
            v = s0
        elif v > vmax:
            vx *= vmax / v
            vy *= vmax / v
            v = vmax
        # move in steps of at most one cell, so a fast ghost can't jump over a small core - its own motion and space
        # carrying it
        n = max(1, int(np.ceil(np.sqrt((vx + carry_x) ** 2 + (vy + carry_y) ** 2))))
        for _ in range(n):
            x = gx[k] + (vx + carry_x) / n
            y = gy[k] + (vy + carry_y) / n
            if wrap:
                x %= w
                y %= h
            else:
                if x < 0.0 or x > w - 1.0:
                    x = min(max(x, 0.0), w - 1.0)
                    vx = -vx * wall_e
                if y < 0.0 or y > h - 1.0:
                    y = min(max(y, 0.0), h - 1.0)
                    vy = -vy * wall_e
            gx[k], gy[k] = x, y
            c = _ghost_cell(x, y, w, h)
            if hole[c]:
                hit[k] = hole[c]
                break
        gvx[k], gvy[k] = vx, vy
        gage[k] += 1


@njit(cache=True)
def _absorb(absorbed, k, m, vx, vy, x, y):
    """Super well k swallows mass m at (x, y) moving at (vx, vy): absorbed[k] adds up the mass, momentum and angular
    momentum (column 5, about the origin, > 0 clockwise) it swallows - the well takes them all on
    (World._collect_absorbed). Its columns 3 and 4 add up the pull of the matter on the well."""
    absorbed[k, 0] += m
    absorbed[k, 1] += m * vx
    absorbed[k, 2] += m * vy
    absorbed[k, 5] += m * (x * vy - y * vx)


@njit(cache=True)
def _swallow_ghosts(gx, gy, gm, gvx, gvy, hit, absorbed):
    """The ghosts that crossed a core (hit) are swallowed: their mass and momentum go to that well's absorbed and gm
    becomes 0. Returns how many."""
    swallowed = 0
    for k in range(gm.size):
        if hit[k]:
            _absorb(absorbed, hit[k] - 1, gm[k], gvx[k], gvy[k], gx[k], gy[k])
            gm[k] = 0
            swallowed += 1
    return swallowed


@njit(cache=True)
def step_ghosts(gx, gy, gvx, gvy, gm, gage, w, h, P, fx, fy, sgx, sgy, sg_block, sg_w, hole, absorbed, whirls, stars,
                sfx, sfy, s_block, s_cw, s_ch):
    """Move the ghosts one tick. One that crosses a super well's core is swallowed (its mass goes to absorbed[k]
    and gm becomes 0); at a solid border a ghost bounces off the edge. Returns how many were swallowed."""
    hit = np.empty(gm.size, np.int16)
    chunks = min(gm.size, 256)                           # (step_ghosts_par's chunks, so its sums come out the same)
    react = np.zeros((absorbed.shape[0], 2))
    for c in range(chunks):
        react[:] = 0.0
        _move_ghosts(c * gm.size // chunks, (c + 1) * gm.size // chunks, gx, gy, gvx, gvy, gm, gage, w, h, P, fx, fy,
                     sgx, sgy, sg_block, sg_w, hole, hit, whirls, stars, sfx, sfy, s_block, s_cw, s_ch, react)
        absorbed[:, 3:5] += react
    return _swallow_ghosts(gx, gy, gm, gvx, gvy, hit, absorbed)


@njit(cache=True, parallel=True)
def step_ghosts_par(gx, gy, gvx, gvy, gm, gage, w, h, P, fx, fy, sgx, sgy, sg_block, sg_w, hole, absorbed, whirls,
                    stars, sfx, sfy, s_block, s_cw, s_ch):
    """step_ghosts() on all cores, with the same result: each ghost moves on its own, and the swallowed ones are
    added up afterwards in order."""
    hit = np.empty(gm.size, np.int16)
    chunks = min(gm.size, 256)
    react = np.zeros((max(chunks, 1), absorbed.shape[0], 2))
    for c in prange(chunks):
        _move_ghosts(c * gm.size // chunks, (c + 1) * gm.size // chunks, gx, gy, gvx, gvy, gm, gage, w, h, P, fx, fy,
                     sgx, sgy, sg_block, sg_w, hole, hit, whirls, stars, sfx, sfy, s_block, s_cw, s_ch, react[c])
    for c in range(chunks):                              # (in order: the same sums as step_ghosts)
        absorbed[:, 3:5] += react[c]
    return _swallow_ghosts(gx, gy, gm, gvx, gvy, hit, absorbed)


@njit(cache=True)
def _add_children(i, m, quad):
    """Scatter m more children over particle i's 4 quadrants (as _init_quad does)."""
    base = (m - 64) // 4 if m > 64 else 0
    for c in range(4):
        quad[i, c] += base
    for _ in range(m - 4 * base):
        quad[i, np.random.randint(0, 4)] += 1


@njit(cache=True)
def land_ghosts(gx, gy, gvx, gvy, gm, gage, life, near, spread, reach, max_mass, w, h, mass, kin, quad, shade, stamp,
                flag, solid, hole, wrap):
    """Ghosts at least `life` ticks old become ordinary particles where they are: in a free cell of the nearest ring
    of cells round them that has one, within `near` cells, picked at random so a crowd landing together spreads
    evenly. With no free cell that close, one joins a particle there of its own rung, making the next one up (under
    max_mass; momentum and children are kept) - masses come in rungs. With neither, it stays a ghost and tries
    again next tick, looking a cell further out (up to `reach`) for every `spread` ticks it has waited - so matter
    lands at the nearest room, not far from where it was. Returns how many landed."""
    landed = 0
    for k in range(gm.size):
        if gm[k] == 0 or gage[k] < life:
            continue
        c = _ghost_cell(gx[k], gy[k], w, h)
        cx, cy = c % w, c // w
        out = min(reach, near + (gage[k] - life) // max(spread, 1))
        lightest = -1
        for d in range(out + 1):
            found = -1
            seen = 0
            for dy in range(-d, d + 1):
                step = 1 if abs(dy) == d else 2 * d          # inner rows: only the ring's two edge cells
                for dx in range(-d, d + 1, max(1, step)):
                    j = _cell(cx + dx, cy + dy, w, h, wrap)
                    if j < 0 or solid[j] or hole[j]:
                        continue
                    if mass[j] == 0:
                        seen += 1
                        if np.random.randint(0, seen) == 0:  # reservoir sampling: each free cell equally likely
                            found = j
                    elif d <= near and mass[j] == gm[k] and 2 * gm[k] <= max_mass and lightest < 0:
                        lightest = j
            if found >= 0:
                place(found, gm[k], gvx[k], gvy[k], mass, kin, quad, shade, stamp)
                wake(found, mass, flag)
                gm[k] = 0
                landed += 1
                break
            if d == near and lightest >= 0:              # no room this close: join a particle instead
                j = lightest
                total = mass[j] + gm[k]
                kin[j, 0] = (mass[j] * kin[j, 0] + gm[k] * gvx[k]) / total
                kin[j, 1] = (mass[j] * kin[j, 1] + gm[k] * gvy[k]) / total
                _add_children(j, gm[k], quad)
                mass[j] = total
                wake(j, mass, flag)
                gm[k] = 0
                landed += 1
                break
    return landed


@njit(cache=True)
def paint(idx, color, rgb):
    """Paint cells idx one colour (a round universe's rim, after render)."""
    for k in range(idx.size):
        i = idx[k]
        rgb[i, 0], rgb[i, 1], rgb[i, 2] = color[0], color[1], color[2]


@njit(cache=True)
def fly_waves(k, steps, gx, gy, gvx, gvy, gm, gage, w, h, hole, rim_mask, absorbed, life, wrap):
    """Move gravitational waves (ghosts k) one tick, `steps` steps of a cell or less: straight on, unbent by anything.
    One crossing a super well's core is swallowed (its mass goes to absorbed); one reaching the edge of the universe
    (rim_mask: a round one's outside, or empty) stops on the last cell inside, its age set to `life` so it lands.
    Every one ages a tick. Returns how many were swallowed. (World._fly_waves.)"""
    swallowed = 0
    for n in range(k.size):
        g = k[n]
        x, y, vx, vy = gx[g], gy[g], gvx[g], gvy[g]
        for s in range(1, steps + 1):
            nx = x + vx * (s / steps)
            ny = y + vy * (s / steps)
            if wrap:
                nx = nx % w
                ny = ny % h
            edge = nx < 0 or nx > w - 1 or ny < 0 or ny > h - 1
            nx = min(max(nx, 0.0), w - 1.0)
            ny = min(max(ny, 0.0), h - 1.0)
            i = int(np.floor(ny + 0.5)) * w + int(np.floor(nx + 0.5))
            if rim_mask.size and rim_mask[i] != 0:
                edge = True
            if hole[i] > 0:
                _absorb(absorbed, hole[i] - 1, gm[g], gvx[g], gvy[g], gx[g], gy[g])
                gm[g] = 0
                swallowed += 1
                break
            if edge:                                     # (radiation_step: back in at the edge, or gone)
                gx[g] = nx
                gy[g] = ny
                break
            gx[g] = nx
            gy[g] = ny
        gage[g] += 1
    return swallowed


@njit(cache=True)
def heat_push(gx, gy, gvx, gvy, gm, gtag, tag, coupling, min_speed, vmax, w, h, mass, kin, owner, flag):
    """Radiation pressure: each ghost tagged `tag` (heat or waves) still faster than min_speed against the free
    particle in its cell (not a star's) pushes it the way it is going, handing over `coupling` of what a head-on
    elastic collision would - so a light particle is blown away while a heavy one barely moves and soaks the heat up
    - and slows by as much (momentum is kept). A pushed particle is woken and kept under vmax."""
    for k in range(gm.size):
        if gtag[k] != tag or gm[k] == 0:
            continue
        i = _ghost_cell(gx[k], gy[k], w, h)
        if mass[i] == 0 or owner[i] != 0:
            continue
        rx, ry = gvx[k] - kin[i, 0], gvy[k] - kin[i, 1]
        u = np.sqrt(rx * rx + ry * ry)
        if u < min_speed:
            continue
        mh, mt = np.float64(gm[k]), np.float64(mass[i])
        dp = coupling * 2.0 * mh * mt / (mh + mt) * u     # momentum handed over, along the relative motion
        ex, ey = rx / u, ry / u
        vx, vy = kin[i, 0] + dp / mt * ex, kin[i, 1] + dp / mt * ey
        s = np.sqrt(vx * vx + vy * vy)
        if s > vmax:
            vx, vy = vx * vmax / s, vy * vmax / s
        kin[i, 0], kin[i, 1] = vx, vy
        gvx[k] -= dp / mh * ex
        gvy[k] -= dp / mh * ey
        sg = np.sqrt(gvx[k] * gvx[k] + gvy[k] * gvy[k])
        if sg > vmax:                                     # waves skip step_ghosts' clamp: keep them (and so the
            gvx[k] *= vmax / sg                           #   steps fly_waves takes a tick) bounded here
            gvy[k] *= vmax / sg
        wake(i, mass, flag)


@njit(cache=True)
def heat_step(w, h, mass, kin, quad, owner, flag, solid, conduct, radiate, cost, speed, rows, pool, block, fuse_on,
              max_mass, f_bind, f_peak, f_top, f_tail, f_barrier, wrap):
    """Heat moves (kin[:, 4]: see KIN), and touching particles fuse. Fusion: two touching particles of the same rung
    may fuse into the next one up, by the same rule as in a collision (_advance): the energy they bring - their heat
    and their motion against each other - against the barrier (_tunnel), and enough of it if the fusion takes energy
    (past the peak: _binding); the binding energy it gives off is the product's heat, and so is the energy of their
    motion against each other. So matter hot enough fuses where it lies - in a hot core, with nothing colliding.
    Conduction: touching particles even out their temperatures (heat per unit
    mass) by `conduct` of the difference, weighted so a light particle warms fast and a heavy one slowly - heat
    flows, never appears. Radiation: a particle with open sides (empty cells next to it, not solid ground) loses
    `radiate` of its heat per open side of four into pool[] - the radiation gathering in its block x block square
    of cells - and the square sends it out as radiation, the lightest particles (mass 1), one each time it holds
    `cost` (a heat particle's rest energy and the speed it flies off at: World.radiation_cost), from where the
    particle that tipped it over is. (One costs far more than ordinary matter holds - mass x VMAX^2 against heat of a
    few x its mass - so each particle sending its own never sent any.) It leaves through one of the open sides, within
    60 degrees of straight out, at `speed` (light's), and the particle recoils with its momentum (cost / speed: E /
    c), the energy of that recoil coming out of its heat too. Each is noted as a row of rows (x, y, direction x, y,
    1) for World._radiate. Returns (how many rows, how many fused)."""
    bw = (w + block - 1) // block
    fused = 0
    n = 0
    for i in range(w * h):
        if mass[i] == 0:
            continue
        m = np.float64(mass[i])
        x, y = i % w, i // w
        for d in range(2):                               # right and down: each touching pair once
            j = _cell(x + 1, y, w, h, wrap) if d == 0 else _cell(x, y + 1, w, h, wrap)
            if j < 0 or mass[j] == 0:
                continue
            mj = np.float64(mass[j])
            f = conduct * (kin[i, 4] / m - kin[j, 4] / mj) * m * mj / (m + mj)
            kin[i, 4] -= f
            kin[j, 4] += f
            if fuse_on and mass[j] == mass[i] and 2 * mass[i] <= max_mass and _rung(mass[i]) >= 0:
                dvx, dvy = np.float64(kin[i, 0] - kin[j, 0]), np.float64(kin[i, 1] - kin[j, 1])
                u2 = dvx * dvx + dvy * dvy
                ef = _fuse_energy(m, m, u2, kin[i, 4], kin[j, 4])
                q = _binding(2 * mass[i], f_bind, f_peak, f_top, f_tail) - 2.0 * _binding(mass[i], f_bind, f_peak,
                                                                                         f_top, f_tail)
                if ef + q >= 0.0 and _tunnel(_barrier(m, m, f_barrier), ef):
                    kin[i, 0] = 0.5 * (kin[i, 0] + kin[j, 0])
                    kin[i, 1] = 0.5 * (kin[i, 1] + kin[j, 1])
                    kin[i, 4] += kin[j, 4] + 0.25 * m * u2 + q   # (their motion against each other: m/2 x u2/2)
                    for c in range(4):
                        quad[i, c] += quad[j, c]
                    mass[i] = 2 * mass[i]
                    m = 2.0 * m
                    _clear(j, mass, kin, quad)
                    owner[j] = 0
                    wake(i, mass, flag)
                    wake_around(j, w, h, mass, flag, wrap)
                    fused += 1
        if radiate <= 0.0 or kin[i, 4] <= 0.0:
            continue
        sides = 0
        for d in range(4):
            j = _cell(x + DX4[d], y + DY4[d], w, h, wrap)
            if j >= 0 and mass[j] == 0 and not solid[j]:
                sides += 1
        if sides == 0:
            continue
        lost = radiate * 0.25 * sides * kin[i, 4]
        kin[i, 4] -= lost
        b = (y // block) * bw + x // block
        pool[b] += lost
        while pool[b] >= cost and n < rows.shape[0]:
            pick = np.random.randint(0, sides)          # which open side it leaves through
            for d in range(4):
                j = _cell(x + DX4[d], y + DY4[d], w, h, wrap)
                if j >= 0 and mass[j] == 0 and not solid[j]:
                    if pick == 0:
                        break
                    pick -= 1
            a = (2.0 * np.random.random() - 1.0) * np.pi / 3.0
            ex = DX4[d] * np.cos(a) - DY4[d] * np.sin(a)
            ey = DX4[d] * np.sin(a) + DY4[d] * np.cos(a)
            rows[n, 0] = x
            rows[n, 1] = y
            rows[n, 2] = ex
            rows[n, 3] = ey
            rows[n, 4] = 1.0
            n += 1
            pool[b] -= cost
            vx, vy = np.float64(kin[i, 0]), np.float64(kin[i, 1])
            nvx, nvy = vx - cost / speed * ex / m, vy - cost / speed * ey / m      # the recoil
            kin[i, 0], kin[i, 1] = nvx, nvy
            kin[i, 4] -= 0.5 * m * (nvx * nvx + nvy * nvy - vx * vx - vy * vy)
    return n, fused


@njit(cache=True)
def radiation_step(gx, gy, gvx, gvy, gm, gtag, tag, quantum, w, h, mass, kin, flag, cx, cy, radius, wrap, recycle):
    """Radiation (ghosts tagged `tag`: energy only, gm quanta of `quantum` each - see World._radiate) after it has
    moved this tick: the first particle along its way this tick takes it in - its momentum (gm x quantum / its speed,
    E / c) and the rest of its energy as heat - and it is gone. Reaching the universe's edge (the circle of `radius`
    round (cx, cy); radius 0: the window's border, unless it wraps, when there is none), it is gone too - or, with
    `recycle`, comes back in at a random point of the edge, heading inwards (within 60 degrees of straight in) as
    fast, so the universe keeps its energy. Returns (how many were taken in, how many quanta left the universe, how
    many came back in)."""
    taken = 0
    lost = 0
    back = 0
    for k in range(gm.size):
        if gtag[k] != tag or gm[k] == 0:
            continue
        sp = np.sqrt(gvx[k] * gvx[k] + gvy[k] * gvy[k])
        n = max(1, int(np.ceil(sp)))
        hit = -1
        for t in range(1, n + 1):                        # along this tick's way (not where it started)
            px = gx[k] - gvx[k] * (n - t) / n
            py = gy[k] - gvy[k] * (n - t) / n
            if wrap:
                px, py = px % w, py % h
            c = _ghost_cell(px, py, w, h)
            if mass[c] > 0:
                hit = c
                break
        if hit >= 0:
            mt = np.float64(mass[hit])
            e = gm[k] * quantum
            vx, vy = np.float64(kin[hit, 0]), np.float64(kin[hit, 1])
            p = e / max(sp, 1e-9)
            nvx, nvy = vx + p * gvx[k] / max(sp, 1e-9) / mt, vy + p * gvy[k] / max(sp, 1e-9) / mt
            kin[hit, 0], kin[hit, 1] = nvx, nvy
            kin[hit, 4] += e - 0.5 * mt * (nvx * nvx + nvy * nvy - vx * vx - vy * vy)
            wake(hit, mass, flag)
            gm[k] = 0
            taken += 1
            continue
        if wrap:
            continue
        if radius > 0.0:
            out = (gx[k] - cx) ** 2 + (gy[k] - cy) ** 2 >= (radius - 0.5) ** 2
        else:
            out = gx[k] <= 0.0 or gx[k] >= w - 1.0 or gy[k] <= 0.0 or gy[k] >= h - 1.0
        if not out:
            continue
        if not recycle:
            lost += gm[k]
            gm[k] = 0
            continue
        if radius > 0.0:                                 # back in from a random point of the rim
            th = np.random.random() * 2.0 * np.pi
            nx, ny = -np.cos(th), -np.sin(th)
            gx[k] = cx + (radius - 1.5) * np.cos(th)
            gy[k] = cy + (radius - 1.5) * np.sin(th)
        else:                                            # ... or of the window's border
            u = np.random.random() * 2.0 * (w + h)
            if u < w:
                gx[k], gy[k], nx, ny = u, 0.5, 0.0, 1.0
            elif u < 2 * w:
                gx[k], gy[k], nx, ny = u - w, h - 1.5, 0.0, -1.0
            elif u < 2 * w + h:
                gx[k], gy[k], nx, ny = 0.5, u - 2 * w, 1.0, 0.0
            else:
                gx[k], gy[k], nx, ny = w - 1.5, u - 2 * w - h, -1.0, 0.0
        a = (2.0 * np.random.random() - 1.0) * np.pi / 3.0
        gvx[k] = sp * (nx * np.cos(a) - ny * np.sin(a))
        gvy[k] = sp * (nx * np.sin(a) + ny * np.cos(a))
        back += 1
    return taken, lost, back


@njit(cache=True)
def render_ghosts(gx, gy, gm, gtag, w, h, mass_lut, tint, heat_color, wave_color, rgb, hide_rad=False):
    """Draw the ghosts see-through: their mass colour washed towards tint, blended half over what is there; heat
    (tag HEAT_TAG) glows heat_color and gravitational waves (WAVE_TAG) wave_color, solid. hide_rad: radiation
    isn't drawn (it still acts as ever)."""
    for k in range(gm.size):
        if gm[k] == 0:
            continue
        if hide_rad and (gtag[k] == HEAT_TAG or gtag[k] == WAVE_TAG):
            continue
        i = _ghost_cell(gx[k], gy[k], w, h)
        if gtag[k] == HEAT_TAG or gtag[k] == WAVE_TAG:
            glow = heat_color if gtag[k] == HEAT_TAG else wave_color
            for c in range(3):
                rgb[i, c] = glow[c]
            continue
        for c in range(3):
            col = (mass_lut[gm[k], c] + tint[c]) >> 1
            rgb[i, c] = (np.int32(rgb[i, c]) + col) >> 1


@njit(cache=True)
def blast_push(cx, cy, r_in, r_out, reach, push, drag, wind, vcap, w, h, mass, kin, stamp, flag, solid, wrap):
    """A supernova's shock front sweeping from r_in to r_out round (cx, cy): every particle in that ring is given an
    outward speed push * drag * (1 - r / reach) (at most vcap), unless it is already moving outwards faster. Particles
    already inside r_in lose `drag` of their outward speed each tick, so a shoved one coasts about `push` cells (less
    further out) before it stops. With `wind` the push doesn't fade with distance (push * drag everywhere, at most
    vcap) and keeps blowing behind the front, so everything inside it is swept outwards into a shell and the cavity
    stays clear against whatever pulls it back while the front runs. Returns how many particles were shoved."""
    shoved = 0
    x0, x1, xmin = _span(cx, r_out, w, wrap)
    y0, y1, ymin = _span(cy, r_out, h, wrap)
    for yy in range(y0, y1):
        dy = _axis(yy, cy, h, ymin)
        for xx in range(x0, x1):
            dx = _axis(xx, cx, w, xmin)
            d2 = dx * dx + dy * dy
            if d2 > r_out * r_out or d2 < 1.0:
                continue
            i = (yy % h) * w + xx % w
            if mass[i] == 0:
                continue
            d = np.sqrt(d2)
            ux, uy = dx / d, dy / d
            vr = kin[i, 0] * ux + kin[i, 1] * uy
            if d >= r_in or wind:
                v = min(push * drag * (1.0 if wind else max(0.0, 1.0 - d / reach)), vcap)
                if vr < v:
                    kin[i, 0] += (v - vr) * ux
                    kin[i, 1] += (v - vr) * uy
                    stamp[i] &= ~np.uint32(1)            # no longer wedged
                    wake_around(i, w, h, mass, flag, wrap)
                    shoved += 1
            elif vr > 0.0:
                kin[i, 0] -= drag * vr * ux
                kin[i, 1] -= drag * vr * uy
                flag[i] = 1
    return shoved


# --- super wells -------------------------------------------------------------------------------------

@njit(cache=True)
def absorb_disk(cx, cy, r, w, h, mass, kin, quad, flag, wrap):
    """Remove every particle within r cells of (cx, cy). Returns their total mass, momentum (px, py) and angular
    momentum about (cx, cy) (> 0 = clockwise on screen)."""
    total = 0
    px = py = lz = 0.0
    x0, x1, xmin = _span(cx, r, w, wrap)
    y0, y1, ymin = _span(cy, r, h, wrap)
    for yy in range(y0, y1):
        dy = _axis(yy, cy, h, ymin)
        for xx in range(x0, x1):
            dx = _axis(xx, cx, w, xmin)
            if dx * dx + dy * dy > r * r:
                continue
            i = (yy % h) * w + xx % w
            if mass[i]:
                total += np.int64(mass[i])
                px += mass[i] * kin[i, 0]
                py += mass[i] * kin[i, 1]
                lz += mass[i] * (dx * kin[i, 1] - dy * kin[i, 0])
                _clear(i, mass, kin, quad)
                wake_around(i, w, h, mass, flag, wrap)
    return total, px, py, lz


@njit(cache=True)
def mass_rings(cx, cy, rmax, w, h, mass, wrap):
    """The mass in each ring round (cx, cy) out to rmax cells: ring k holds the particles from k to k + 1 cells out
    (World.collapse_check adds them up into the mass within each distance)."""
    rings = np.zeros(int(rmax) + 1)
    x0, x1, xmin = _span(cx, rmax, w, wrap)
    y0, y1, ymin = _span(cy, rmax, h, wrap)
    for yy in range(y0, y1):
        dy = _axis(yy, cy, h, ymin)
        for xx in range(x0, x1):
            i = (yy % h) * w + xx % w
            if mass[i] == 0:
                continue
            dx = _axis(xx, cx, w, xmin)
            k = int(np.sqrt(dx * dx + dy * dy))
            if k <= rmax:
                rings[k] += mass[i]
    return rings


@njit(cache=True)
def _mark_disk(cx, cy, r, w, h, wrap, grid, value):
    """grid[cell] = value for every cell within r of (cx, cy)."""
    x0, x1, xmin = _span(cx, r, w, wrap)
    y0, y1, ymin = _span(cy, r, h, wrap)
    for yy in range(y0, y1):
        dy = _axis(yy, cy, h, ymin)
        for xx in range(x0, x1):
            dx = _axis(xx, cx, w, xmin)
            if dx * dx + dy * dy <= r * r:
                grid[(yy % h) * w + xx % w] = value


@njit(cache=True)
def mark_holes(cores, w, h, hole, mass, kin, quad, flag, absorbed, wrap):
    """Mark the core cells of each super well (rows of index, x, y, core radius) in hole[], swallowing any particle
    already there into absorbed[index]."""
    hole[:] = 0
    for k in range(cores.shape[0]):
        idx = int(cores[k, 0])
        cx, cy, r = cores[k, 1], cores[k, 2], cores[k, 3]
        m_, px_, py_, lz_ = absorb_disk(cx, cy, r, w, h, mass, kin, quad, flag, wrap)
        absorbed[idx, 0] += m_
        absorbed[idx, 1] += px_
        absorbed[idx, 2] += py_
        absorbed[idx, 5] += lz_ + cx * py_ - cy * px_    # (about the origin, as _absorb counts it)
        _mark_disk(cx, cy, r, w, h, wrap, hole, idx + 1)


@njit(cache=True)
def mark_solid(bodies, w, h, solid, gvx, gvy, mass, kin, quad, shade, stamp, flag, wrap):
    """Mark every solid well's body (rows of x, y, radius, spin, vx, vy) as solid ground moving with it - its own
    velocity plus its spin (rad/tick, > 0 clockwise on screen) - and push any particle inside it straight out, away
    from that well's centre, into the first free cell beyond the surface."""
    solid[:] = 0
    for k in range(bodies.shape[0]):
        cx, cy, r, om, bvx, bvy = bodies[k, 0], bodies[k, 1], bodies[k, 2], bodies[k, 3], bodies[k, 4], bodies[k, 5]
        x0, x1, xmin = _span(cx, r, w, wrap)
        y0, y1, ymin = _span(cy, r, h, wrap)
        for yy in range(y0, y1):
            ry = _axis(yy, cy, h, ymin)
            for xx in range(x0, x1):
                rx = _axis(xx, cx, w, xmin)
                if rx * rx + ry * ry <= r * r:
                    i = (yy % h) * w + xx % w
                    solid[i] = 1
                    gvx[i] = bvx - om * ry
                    gvy[i] = bvy + om * rx
    for k in range(bodies.shape[0]):
        cx, cy, r = bodies[k, 0], bodies[k, 1], bodies[k, 2]
        x0, x1, xmin = _span(cx, r, w, wrap)
        y0, y1, ymin = _span(cy, r, h, wrap)
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                i = (yy % h) * w + xx % w
                if not (solid[i] and mass[i]):
                    continue
                dx, dy = _axis(xx, cx, w, xmin), _axis(yy, cy, h, ymin)
                d = np.sqrt(dx * dx + dy * dy)
                if d < 1e-6:
                    a = np.random.random() * 2.0 * np.pi
                    dx, dy, d = np.cos(a), np.sin(a), 1.0
                dx, dy = dx / d, dy / d
                t = 1.0
                while t < w + h:
                    j = _cell(int(round(xx + dx * t)), int(round(yy + dy * t)), w, h, wrap)
                    if j < 0:
                        break                            # nowhere to go: it stays stuck inside
                    if not solid[j] and mass[j] == 0:
                        mass[j] = mass[i]
                        for c in range(KIN):
                            kin[j, c] = kin[i, c]
                        for c in range(4):
                            quad[j, c] = quad[i, c]
                        kin[j, 2] = 0.0
                        kin[j, 3] = 0.0
                        shade[j] = shade[i]
                        stamp[j] = stamp[i]
                        _clear(i, mass, kin, quad)
                        wake(j, mass, flag)
                        break
                    t += 1.0


# --- gravity fields ----------------------------------------------------------------------------------

# Gravity only reaches so far: every pull is the softened inverse-square law faded by fade() - at full strength
# out to the reach R, then less and less, to nothing at REACH_TAPER x R - so things must come close to interact
# strongly, orbits within R are as stable as with no fading at all (beyond about 1.16 R, where the pull falls faster
# than 1 / r^3, none is), and bodies further apart than that don't feel each other at all.
WHIRL_BOUND = 0.05              # a whirlpool never leaves anything with more than - this energy (per mass) in its
                                #   well's pull: whatever it spins round stays bound (see whirl). (A constant here
                                #   too, for the same reason as REACH_TAPER below)
REACH_TAPER = 2.0               # (a constant here, not in config: the cached kernels would keep an old value)
_TL = REACH_TAPER - 1.0         # the taper's length, in reach lengths
# the taper's share of the pull as a cubic in u = rho / R (a smoothstep from 1 at u = 1 down to 0 at REACH_TAPER) ...
_A0 = 1.0 - 3.0 / _TL ** 2 - 2.0 / _TL ** 3
_A1 = 6.0 / _TL ** 2 + 6.0 / _TL ** 3
_A2 = -3.0 / _TL ** 2 - 6.0 / _TL ** 3
_A3 = 2.0 / _TL ** 3


@njit(cache=True)
def _taper_h(u):
    """... and the integral of that share / u^2 (whose differences give the potential), up to a constant."""
    return -_A0 / u + _A1 * np.log(u) + _A2 * u + 0.5 * _A3 * u * u


_H_END = _taper_h(REACH_TAPER)
_H_IN = _H_END - _taper_h(1.0)  # the whole taper's integral (in 1 / R)


@njit(cache=True)
def fade(rho, kinv):
    """Shares of the plain inverse-square pull and of its potential left at softened distance rho when gravity
    reaches 1 / kinv cells (kinv = 0: all the way): the whole pull out to there, then smoothly less to none at
    REACH_TAPER times as far; the potential is what that pull climbs out of (S / rho x this share), none beyond."""
    u = rho * kinv
    if u <= 1.0:
        return 1.0, 1.0 - u + u * _H_IN
    if u >= REACH_TAPER:
        return 0.0, 0.0
    t = (u - 1.0) / _TL
    return 1.0 - t * t * (3.0 - 2.0 * t), u * (_H_END - _taper_h(u))


@njit(cache=True)
def _pull(dx, dy, strength, soft, kinv):
    """One well's acceleration and potential at offset (dx, dy) from the point towards the well."""
    rho = np.sqrt(dx * dx + dy * dy + soft * soft)
    ff, fp = fade(rho, kinv)
    inv_r = 1.0 / rho
    f = strength * inv_r * inv_r * inv_r * ff
    return dx * f, dy * f, -strength * inv_r * fp


@njit(cache=True)
def frame_turn(rx, ry, jterm, reach, soft, kinv, vmax):
    """How fast a spinning super well turns space itself round at (rx, ry) from it (rad/tick, > 0 clockwise on
    screen): frame dragging, jterm / rho^3 - jterm = 2 G J / c^2, J the angular momentum it holds (Lense-Thirring) -
    faded as its pull is, out to `reach`, and never carrying anything faster than vmax (the fastest matter moves:
    where it would, matter can't hold still or go against the spin at all). Everything there is carried round with
    space - where it is and which way it is heading turned together (frame_carry) - so its motion through space is
    unchanged and nothing is sped up: something falling straight in through turning space spirals in, dragged round
    the way the well spins."""
    if jterm == 0.0:
        return 0.0
    d2 = rx * rx + ry * ry
    if d2 >= reach * reach:
        return 0.0
    rho = np.sqrt(d2 + soft * soft)
    om = jterm * fade(rho, kinv)[0] / (rho * rho * rho)
    cap = vmax / max(np.sqrt(d2), 1e-9)
    return min(max(om, -cap), cap)


@njit(cache=True)
def frame_carry(rx, ry, om):
    """How far turning space carries something at (rx, ry) from a super well in a tick when it turns om there."""
    c, s = np.cos(om), np.sin(om)
    return c * rx - s * ry - rx, s * rx + c * ry - ry


@njit(cache=True)
def _lerp_axis(v, block, nb, wrap):
    """Bilinear interpolation along one axis from block centres: (block 0, block 1, weight of block 1, centre 0,
    centre 1), centres in cell coordinates."""
    u = (v - (block - 1) * 0.5) / block
    b0 = int(np.floor(u))
    t = u - b0
    if wrap:
        b1 = (b0 + 1) % nb
        c0 = b0 * block + (block - 1) * 0.5
        return b0 % nb, b1, t, c0, c0 + block
    if b0 < 0:
        b0, t = 0, 0.0
    if b0 >= nb - 1:
        b0, t = nb - 1, 0.0
    b1 = min(b0 + 1, nb - 1)
    return b0, b1, t, b0 * block + (block - 1) * 0.5, b1 * block + (block - 1) * 0.5


@njit(cache=True, parallel=True)
def field(w, h, block, wells, near, gx, gy, fx, fy, phi, wrap, kinv):
    """External acceleration and potential per cell: uniform gravity (gx, gy) plus softened point wells
    (rows of x, y, strength, softening): accel = strength * d / (|d|^2 + soft^2)^1.5 (the gravitational attraction
    law), faded with distance as fade() says. With wrap on, each well pulls the shortest way round the borders.

    Far from a well its pull changes smoothly, so every well is summed only at the centres of block x block cells
    and blended onto the cells in between; within near[k] cells of well k, where it changes fast, its exact pull
    replaces the blend. That keeps a rebuild cheap however many wells there are. Rows are shared out between cores;
    each cell is still summed in the same order, so the result doesn't depend on how many there are."""
    cw, ch = -(-w // block), -(-h // block)
    cfx = np.zeros(cw * ch)
    cfy = np.zeros(cw * ch)
    cph = np.zeros(cw * ch)
    nw = wells.shape[0]
    for by in prange(ch):
        cy = by * block + (block - 1) * 0.5
        for bx in range(cw):
            cx = bx * block + (block - 1) * 0.5
            sx = sy = sp = 0.0
            for k in range(nw):
                ax, ay, p = _pull(-_axis(cx, wells[k, 0], w, wrap), -_axis(cy, wells[k, 1], h, wrap), wells[k, 2],
                                  wells[k, 3], kinv)
                sx += ax
                sy += ay
                sp += p
            b = by * cw + bx
            cfx[b] = sx
            cfy[b] = sy
            cph[b] = sp
    for y in prange(h):
        y0, y1, ty, _, _ = _lerp_axis(y, block, ch, wrap)
        for x in range(w):
            x0, x1, tx, _, _ = _lerp_axis(x, block, cw, wrap)
            a, b, c, d = y0 * cw + x0, y0 * cw + x1, y1 * cw + x0, y1 * cw + x1
            wa, wb, wc, wd = (1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty
            i = y * w + x
            fx[i] = gx + wa * cfx[a] + wb * cfx[b] + wc * cfx[c] + wd * cfx[d]
            fy[i] = gy + wa * cfy[a] + wb * cfy[b] + wc * cfy[c] + wd * cfy[d]
            phi[i] = -(gx * x + gy * y) + wa * cph[a] + wb * cph[b] + wc * cph[c] + wd * cph[d]
    for k in range(nw):
        wx, wy, strength, soft = wells[k, 0], wells[k, 1], wells[k, 2], wells[k, 3]
        r = near[k]
        x0s, x1s, xmin = _span(wx, r, w, wrap)
        y0s, y1s, ymin = _span(wy, r, h, wrap)
        for yy in prange(y0s, y1s):                  # one well's rows are distinct cells (see _span)
            y = yy % h
            ddy = _axis(yy, wy, h, ymin)
            by0, by1, ty, cy0, cy1 = _lerp_axis(y, block, ch, wrap)
            for xx in range(x0s, x1s):
                ddx = _axis(xx, wx, w, xmin)
                if ddx * ddx + ddy * ddy > r * r:
                    continue
                x = xx % w
                bx0, bx1, tx, cx0, cx1 = _lerp_axis(x, block, cw, wrap)
                ex, ey, ep = _pull(-ddx, -ddy, strength, soft, kinv)
                # take back what the blend gave this well here, so the exact pull replaces it
                ix = iy = ip = 0.0
                for cy, wy_ in ((cy0, 1 - ty), (cy1, ty)):
                    dyc = -_axis(cy, wy, h, wrap)
                    for cx, wx_ in ((cx0, 1 - tx), (cx1, tx)):
                        ax, ay, p = _pull(-_axis(cx, wx, w, wrap), dyc, strength, soft, kinv)
                        ix += wx_ * wy_ * ax
                        iy += wx_ * wy_ * ay
                        ip += wx_ * wy_ * p
                i = y * w + x
                fx[i] += ex - ix
                fy[i] += ey - iy
                phi[i] += ep - ip


@njit(cache=True)
def _in_disc(xx, cx, dy, r):
    dx = xx - cx
    return dx * dx + dy * dy <= r * r


@njit(cache=True)
def _wake_disc_row(yy, cx, cy, r, x0, x1, xmin, ymin, w, h, mass, flag):
    """wake_disk() along row yy of its span: the cells of a row inside a disc are one run, so it finds the run's ends
    (the same test per cell) and wakes what lies between without testing each cell."""
    dy = _axis(yy, cy, h, ymin)
    row = (yy % h) * w
    if xmin:                                             # the disc spans the whole wrapped axis: cell by cell
        for xx in range(x0, x1):
            dx = _axis(xx, cx, w, True)
            if dx * dx + dy * dy <= r * r:
                wake(row + xx, mass, flag)
        return
    if dy * dy > r * r or x0 >= x1:
        return
    m = min(max(np.int64(np.floor(cx)), x0), x1 - 1)    # the cell nearest the centre (or the next one) is in the
    if not _in_disc(m, cx, dy, r):                      #   run if anything is
        m = min(m + 1, x1 - 1)
        if not _in_disc(m, cx, dy, r):
            return
    s = np.sqrt(max(r * r - dy * dy, 0.0))
    lo = min(max(np.int64(np.floor(cx - s)), x0), m)
    if _in_disc(lo, cx, dy, r):
        while lo > x0 and _in_disc(lo - 1, cx, dy, r):
            lo -= 1
    else:
        while not _in_disc(lo, cx, dy, r):
            lo += 1
    hi = max(min(np.int64(np.floor(cx + s)) + 1, x1 - 1), m)
    if _in_disc(hi, cx, dy, r):
        while hi < x1 - 1 and _in_disc(hi + 1, cx, dy, r):
            hi += 1
    else:
        while not _in_disc(hi, cx, dy, r):
            hi -= 1
    if lo >= 0 and hi < w:
        m, f = mass[row + lo:row + hi + 1], flag[row + lo:row + hi + 1]
        for k in range(m.size):                          # (flag is 0 or 1: or-ing in vectorizes, a branch didn't)
            f[k] |= np.uint8(m[k] != 0)
    else:
        for xx in range(lo, hi + 1):
            wake(row + xx % w, mass, flag)


@njit(cache=True)
def wake_disk(cx, cy, r, w, h, mass, flag, wrap):
    """Wake every particle within r cells of (cx, cy)."""
    x0, x1, xmin = _span(cx, r, w, wrap)
    y0, y1, ymin = _span(cy, r, h, wrap)
    for yy in range(y0, y1):
        _wake_disc_row(yy, cx, cy, r, x0, x1, xmin, ymin, w, h, mass, flag)


@njit(cache=True, parallel=True)
def wake_disk_par(cx, cy, r, w, h, mass, flag, wrap):
    """wake_disk() on all cores (the same result: each row of the disc is different cells)."""
    x0, x1, xmin = _span(cx, r, w, wrap)
    y0, y1, ymin = _span(cy, r, h, wrap)
    for yy in prange(y0, y1):
        _wake_disc_row(yy, cx, cy, r, x0, x1, xmin, ymin, w, h, mass, flag)


@njit(cache=True)
def wake_disks(discs, w, h, mass, flag, wrap):
    """wake_disk() for each row of discs (x, y, r)."""
    for k in range(discs.shape[0]):
        wake_disk(discs[k, 0], discs[k, 1], discs[k, 2], w, h, mass, flag, wrap)


@njit(cache=True, parallel=True)
def bucketize(edges, values, out):
    """np.searchsorted(edges, values) (edges sorted; side "left") into out, on all cores."""
    for i in prange(values.size):
        v = values[i]
        lo, hi = 0, edges.size
        while lo < hi:
            mid = (lo + hi) >> 1
            if edges[mid] < v:
                lo = mid + 1
            else:
                hi = mid
        out[i] = lo


# --- self-gravity binning ----------------------------------------------------------------------------

@njit(cache=True)
def bin_mass(mass, w, h, block, cw, rho):
    rho[:] = 0.0
    for y in range(h):
        row = (y // block) * cw
        base = y * w
        for x in range(w):
            m = mass[base + x]
            if m:
                rho[row + x // block] += m


@njit(cache=True)
def bin_free_mass(mass, owner, w, h, block, cw, rho):
    """bin_mass of the particles that belong to no star (a star pulls as a whole, see _star_pull)."""
    rho[:] = 0.0
    for y in range(h):
        row = (y // block) * cw
        base = y * w
        for x in range(w):
            m = mass[base + x]
            if m and owner[base + x] == 0:
                rho[row + x // block] += m


# --- stars -----------------------------------------------------------------------------------------
# A star is a ball of ordinary particles held together by its own gravity. Each tick update_stars works out which
# particles are bound to it, and it pulls as a softened point of their total mass at their centre of mass.

@njit(cache=True)
def _star_pull(x, y, own, stars, sfx, sfy, block, cw, ch, w, h, wrap, kinv):
    """The stars' pull at (x, y): their far field, summed at block centres (star_field) and blended, plus, within
    each star's near radius, its exact pull in place of what the blend gave it there. stars rows: x, y, strength,
    softening^2, near radius^2. Returns the pull and, separately, the part of it that comes from star own - 1 (own
    > 0: the particle's own star)."""
    bx0, bx1, tx, cx0, cx1 = _lerp_axis(x, block, cw, wrap)
    by0, by1, ty, cy0, cy1 = _lerp_axis(y, block, ch, wrap)
    wa, wb, wc, wd = (1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty
    a, b, c, d = by0 * cw + bx0, by0 * cw + bx1, by1 * cw + bx0, by1 * cw + bx1
    ax = wa * sfx[a] + wb * sfx[b] + wc * sfx[c] + wd * sfx[d]
    ay = wa * sfy[a] + wb * sfy[b] + wc * sfy[c] + wd * sfy[d]
    ox = oy = 0.0
    for k in range(stars.shape[0]):
        dx = _axis(stars[k, 0], x, w, wrap)
        dy = _axis(stars[k, 1], y, h, wrap)
        if dx * dx + dy * dy > stars[k, 4]:
            continue
        s, s2 = stars[k, 2], stars[k, 3]
        rho = np.sqrt(dx * dx + dy * dy + s2)
        f = s / (rho * rho * rho) * fade(rho, kinv)[0]
        ax += dx * f
        ay += dy * f
        if k == own - 1:
            ox, oy = dx * f, dy * f
        for cy, wy_ in ((cy0, 1 - ty), (cy1, ty)):
            ey = _axis(stars[k, 1], cy, h, wrap)
            for cx, wx_ in ((cx0, 1 - tx), (cx1, tx)):
                ex = _axis(stars[k, 0], cx, w, wrap)
                rho = np.sqrt(ex * ex + ey * ey + s2)
                f = s / (rho * rho * rho) * fade(rho, kinv)[0] * wx_ * wy_
                ax -= ex * f
                ay -= ey * f
    return ax, ay, ox, oy


@njit(cache=True)
def _held_up(x, y, own, px, py, w, h, mass, owner, wrap):
    """The cell a particle of star own - 1 at (x, y) rests on: the neighbour its star's pull (px, py) points to, if
    a particle of the same star is there; else -1."""
    p = np.sqrt(px * px + py * py)
    if own <= 0 or p == 0.0:
        return -1
    j = _cell(x + (1 if px > 0.383 * p else (-1 if px < -0.383 * p else 0)),
              y + (1 if py > 0.383 * p else (-1 if py < -0.383 * p else 0)), w, h, wrap)
    if j >= 0 and mass[j] != 0 and owner[j] == own:
        return j
    return -1


@njit(cache=True)
def star_sink(stars, chance, w, h, mass, kin, quad, shade, stamp, owner, wrap):
    """Layering inside stars (rows of x, y, radius): a particle resting on a lighter particle of its own star, on
    the side facing the star's centre, swaps places with it with chance x (1 - lighter / heavier), so heavy matter
    sinks to the core. Both move with the star, so this doesn't disturb its motion. Returns how many swapped."""
    swaps = 0
    for k in range(stars.shape[0]):
        cx, cy, r = stars[k, 0], stars[k, 1], stars[k, 2]
        x0, x1, xmin = _span(cx, r, w, wrap)
        y0, y1, ymin = _span(cy, r, h, wrap)
        for yy in range(y0, y1):
            dy = _axis(yy, cy, h, ymin)
            for xx in range(x0, x1):
                dx = _axis(xx, cx, w, xmin)
                if dx * dx + dy * dy > r * r:
                    continue
                i = (yy % h) * w + xx % w
                if owner[i] != k + 1 or mass[i] == 0:
                    continue
                j = _held_up(xx % w, yy % h, k + 1, -dx, -dy, w, h, mass, owner, wrap)
                if j < 0 or mass[j] >= mass[i] or np.random.random() >= chance * (1.0 - mass[j] / mass[i]):
                    continue
                mass[i], mass[j] = mass[j], mass[i]
                shade[i], shade[j] = shade[j], shade[i]
                stamp[i], stamp[j] = stamp[j], stamp[i]
                for c in range(KIN):
                    kin[i, c], kin[j, c] = kin[j, c], kin[i, c]
                for c in range(4):
                    quad[i, c], quad[j, c] = quad[j, c], quad[i, c]
                swaps += 1
    return swaps


@njit(cache=True)
def star_field(stars, w, h, block, cw, ch, sfx, sfy, wrap, kinv):
    """Every star's pull (rows as in _star_pull) at the centre of every block x block cells."""
    for by in range(ch):
        cy = by * block + (block - 1) * 0.5
        for bx in range(cw):
            cx = bx * block + (block - 1) * 0.5
            sx = sy = 0.0
            for k in range(stars.shape[0]):
                dx = _axis(stars[k, 0], cx, w, wrap)
                dy = _axis(stars[k, 1], cy, h, wrap)
                rho = np.sqrt(dx * dx + dy * dy + stars[k, 3])
                f = stars[k, 2] / (rho * rho * rho) * fade(rho, kinv)[0]
                sx += dx * f
                sy += dy * f
            sfx[by * cw + bx] = sx
            sfy[by * cw + bx] = sy


@njit(cache=True, parallel=True)
def star_field_par(stars, w, h, block, cw, ch, sfx, sfy, wrap, kinv):
    """star_field() on all cores, a row of blocks each (the same sums in the same order)."""
    for by in prange(ch):
        cy = by * block + (block - 1) * 0.5
        for bx in range(cw):
            cx = bx * block + (block - 1) * 0.5
            sx = sy = 0.0
            for k in range(stars.shape[0]):
                dx = _axis(stars[k, 0], cx, w, wrap)
                dy = _axis(stars[k, 1], cy, h, wrap)
                rho = np.sqrt(dx * dx + dy * dy + stars[k, 3])
                f = stars[k, 2] / (rho * rho * rho) * fade(rho, kinv)[0]
                sx += dx * f
                sy += dy * f
            sfx[by * cw + bx] = sx
            sfy[by * cw + bx] = sy


@njit(cache=True)
def remap_owner(owner, table):
    """owner[i] = table[owner[i]] (stars renumbered or merged: World._remap_owner), without numpy's temporary."""
    for i in range(owner.size):
        o = owner[i]
        if o != 0:
            owner[i] = table[o]


@njit(cache=True)
def disc_moments(x, y, r, w, h, mass, wrap):
    """Over the cells within r of cell (x, y) (whole numbers; as World._disk_cells counts them): the mass, and its
    moments mass x dx and mass x dy. Sums of whole numbers, so exactly numpy's (World._knot_centre)."""
    m = mx = my = 0.0
    for yy in range(y - r, y + r + 2):
        for xx in range(x - r, x + r + 2):
            dx, dy = xx - x, yy - y
            if dx * dx + dy * dy > r * r:
                continue
            i = _cell(xx, yy, w, h, wrap)
            if i >= 0 and mass[i] != 0:
                mi = np.float64(mass[i])
                m += mi
                mx += dx * mi
                my += dy * mi
    return m, mx, my


@njit(cache=True)
def packed_radius(x, y, r_max, fill, w, h, mass, wrap):
    """World._packed_radius on cell (x, y): the largest whole radius up to r_max of a disc at least `fill` full of
    particles. A cell counts from the smallest whole radius it is within (ceil of its distance: on whole offsets
    that is the smallest k with k^2 >= dx^2 + dy^2, as np.ceil(np.hypot()) gives)."""
    cells = np.zeros(r_max + 1, np.int64)
    full = np.zeros(r_max + 1, np.int64)
    for yy in range(y - r_max, y + r_max + 2):
        for xx in range(x - r_max, x + r_max + 2):
            dx, dy = xx - x, yy - y
            d2 = dx * dx + dy * dy
            if d2 > r_max * r_max:
                continue
            i = _cell(xx, yy, w, h, wrap)
            if i < 0:
                continue
            k = np.int64(np.sqrt(np.float64(d2)))
            while k * k < d2:
                k += 1
            while k > 0 and (k - 1) * (k - 1) >= d2:
                k -= 1
            cells[k] += 1
            if mass[i] != 0:
                full[k] += 1
    nc = nf = 0
    nc += cells[0]
    nf += full[0]
    for k in range(1, r_max + 1):
        nc += cells[k]
        nf += full[k]
        if not np.float64(nf) >= fill * np.float64(max(nc, 1)):
            return k - 1
    return r_max


@njit(cache=True)
def _median(a):
    """np.median of a (not empty): the middle value, or the mean of the middle two, as numpy works it out."""
    s = np.sort(a)
    n = s.size
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


@njit(cache=True)
def layered(lm, r, cuts, gap, k, pure):
    """World.layered on log masses lm at shares r of the knot's radius, divided at each of cuts in turn (the same
    medians, means and comparisons, without numpy's ~40 calls a cut)."""
    for f in cuts:
        na = 0
        for q in range(r.size):
            na += r[q] <= f
        nb = r.size - na
        if na < k or nb < k:
            continue
        a, b = np.empty(na), np.empty(nb)
        ia = ib = 0
        for q in range(r.size):
            if r[q] <= f:
                a[ia] = lm[q]
                ia += 1
            else:
                b[ib] = lm[q]
                ib += 1
        ma, mb = _median(a), _median(b)
        if ma - mb < gap:
            continue
        t = (ma + mb) / 2
        above = below = 0
        for v in a:
            above += v > t
        for v in b:
            below += v <= t
        if above / na >= pure and below / nb >= pure:
            return True
    return False


@njit(cache=True)
def update_stars(stars, w, h, mass, kin, owner, best, sums, wrap, kinv):
    """Work out which particles belong to which star. stars rows: x, y (where its centre is expected), vx, vy, pull
    strength, softening^2, ring radius. A particle inside a star's ring belongs to it when it is bound to it (its
    speed relative to the star is below escape speed there); bound to several, to the one whose ring it is deepest
    inside (as a share of the ring: rings are cut down to Roche lobes, so a small star keeps its own matter next to
    a big one). Sets owner[i] = k + 1 for star k (0 for none; best is scratch) and fills sums rows with: mass,
    mass dx, mass dy, mass vx, mass vy, count, count dx, count dy, count d^2, angular momentum about the centre
    (> 0 clockwise), moment of inertia - dx, dy measured from the expected centre (for the mass, to where each
    particle is within its cell)."""
    owner[:] = 0
    sums[:] = 0.0
    for k in range(stars.shape[0]):
        cx, cy, vx, vy, s, s2, r = stars[k, 0], stars[k, 1], stars[k, 2], stars[k, 3], stars[k, 4], stars[k, 5], \
            stars[k, 6]
        x0, x1, xmin = _span(cx, r, w, wrap)
        y0, y1, ymin = _span(cy, r, h, wrap)
        for yy in range(y0, y1):
            dy = _axis(yy, cy, h, ymin)
            for xx in range(x0, x1):
                dx = _axis(xx, cx, w, xmin)
                d2 = dx * dx + dy * dy
                if d2 > r * r:
                    continue
                i = (yy % h) * w + xx % w
                if mass[i] == 0:
                    continue
                ux, uy = kin[i, 0] - vx, kin[i, 1] - vy
                rho = np.sqrt(d2 + s2)
                if 0.5 * (ux * ux + uy * uy) >= s / rho * fade(rho, kinv)[1]:
                    continue                             # not bound to it
                depth = d2 / (r * r)
                if owner[i] == 0 or depth < best[i]:
                    owner[i] = k + 1
                    best[i] = depth
    for k in range(stars.shape[0]):
        cx, cy, vx, vy, r = stars[k, 0], stars[k, 1], stars[k, 2], stars[k, 3], stars[k, 6]
        x0, x1, xmin = _span(cx, r, w, wrap)
        y0, y1, ymin = _span(cy, r, h, wrap)
        for yy in range(y0, y1):
            dy = _axis(yy, cy, h, ymin)
            for xx in range(x0, x1):
                dx = _axis(xx, cx, w, xmin)
                d2 = dx * dx + dy * dy
                if d2 > r * r:
                    continue
                i = (yy % h) * w + xx % w
                if owner[i] != k + 1:
                    continue
                m = np.float64(mass[i])
                ux, uy = kin[i, 0] - vx, kin[i, 1] - vy
                sums[k, 0] += m
                sums[k, 1] += m * (dx + kin[i, 2])         # where it is within its cell, too
                sums[k, 2] += m * (dy + kin[i, 3])
                sums[k, 3] += m * kin[i, 0]
                sums[k, 4] += m * kin[i, 1]
                sums[k, 5] += 1.0
                sums[k, 6] += dx
                sums[k, 7] += dy
                sums[k, 8] += d2
                sums[k, 9] += m * (dx * uy - dy * ux)
                sums[k, 10] += m * d2


@njit(cache=True, parallel=True)
def update_stars_par(stars, w, h, mass, kin, owner, best, sums, wrap, kinv):
    """update_stars() on all cores, the same result: which star a particle goes to, a grid row at a time (each cell
    still sees the stars in turn), then each star's sums, a star at a time (each in the same order)."""
    owner[:] = 0
    sums[:] = 0.0
    n = stars.shape[0]
    spans = np.empty((n, 6), np.int64)
    for k in range(n):
        x0, x1, xmin = _span(stars[k, 0], stars[k, 6], w, wrap)
        y0, y1, ymin = _span(stars[k, 1], stars[k, 6], h, wrap)
        spans[k, 0], spans[k, 1], spans[k, 2], spans[k, 3], spans[k, 4], spans[k, 5] = x0, x1, xmin, y0, y1, ymin
    for g in prange(h):
        for k in range(n):
            yy = spans[k, 3] + (g - spans[k, 3]) % h     # the one of its rows (if any) on grid row g
            if yy >= spans[k, 4]:
                continue
            cx, cy, vx, vy, s, s2, r = stars[k, 0], stars[k, 1], stars[k, 2], stars[k, 3], stars[k, 4], \
                stars[k, 5], stars[k, 6]
            dy = _axis(yy, cy, h, spans[k, 5] != 0)
            for xx in range(spans[k, 0], spans[k, 1]):
                dx = _axis(xx, cx, w, spans[k, 2] != 0)
                d2 = dx * dx + dy * dy
                if d2 > r * r:
                    continue
                i = (yy % h) * w + xx % w
                if mass[i] == 0:
                    continue
                ux, uy = kin[i, 0] - vx, kin[i, 1] - vy
                rho = np.sqrt(d2 + s2)
                if 0.5 * (ux * ux + uy * uy) >= s / rho * fade(rho, kinv)[1]:
                    continue
                depth = d2 / (r * r)
                if owner[i] == 0 or depth < best[i]:
                    owner[i] = k + 1
                    best[i] = depth
    for k in prange(n):
        cx, cy, vx, vy, r = stars[k, 0], stars[k, 1], stars[k, 2], stars[k, 3], stars[k, 6]
        x0, x1, xmin = spans[k, 0], spans[k, 1], spans[k, 2] != 0
        y0, y1, ymin = spans[k, 3], spans[k, 4], spans[k, 5] != 0
        for yy in range(y0, y1):
            dy = _axis(yy, cy, h, ymin)
            for xx in range(x0, x1):
                dx = _axis(xx, cx, w, xmin)
                d2 = dx * dx + dy * dy
                if d2 > r * r:
                    continue
                i = (yy % h) * w + xx % w
                if owner[i] != k + 1:
                    continue
                m = np.float64(mass[i])
                ux, uy = kin[i, 0] - vx, kin[i, 1] - vy
                sums[k, 0] += m
                sums[k, 1] += m * (dx + kin[i, 2])
                sums[k, 2] += m * (dy + kin[i, 3])
                sums[k, 3] += m * kin[i, 0]
                sums[k, 4] += m * kin[i, 1]
                sums[k, 5] += 1.0
                sums[k, 6] += dx
                sums[k, 7] += dy
                sums[k, 8] += d2
                sums[k, 9] += m * (dx * uy - dy * ux)
                sums[k, 10] += m * d2


@njit(cache=True)
def star_shock(ax, ay, ra, bx, by, rb, ka, kb, speed, w, h, mass, kin, owner, stamp, flag, wrap):
    """Two stars (k = ka, kb; owner value k + 1) overlap: the particles of either one inside both their circles (at
    (ax, ay) radius ra and (bx, by) radius rb) are shocked. Each splashes out of the contact sideways - square to
    the line between the stars, on its own side of it, give or take 45 degrees - at 0.5 to 1 x speed relative to
    their common motion (momentum is kept), and belongs to neither star until it is found bound again. Returns the
    mass shocked."""
    dx, dy = _axis(bx, ax, w, wrap), _axis(by, ay, h, wrap)
    d = max(np.sqrt(dx * dx + dy * dy), 1e-9)
    t = min(max((d * d + ra * ra - rb * rb) / (2.0 * d), 0.0), d)    # middle of the contact, along a -> b
    mx, my = ax + dx / d * t, ay + dy / d * t
    side = np.arctan2(dx, -dy)                           # square to a -> b
    x0, x1, xmin = _span(ax, ra, w, wrap)
    y0, y1, ymin = _span(ay, ra, h, wrap)
    cells = np.empty((y1 - y0) * (x1 - x0), np.int64)
    n = 0
    total = px = py = 0.0
    for yy in range(y0, y1):
        ry = _axis(yy, ay, h, ymin)
        for xx in range(x0, x1):
            rx = _axis(xx, ax, w, xmin)
            if rx * rx + ry * ry > ra * ra:
                continue
            ox, oy = _axis(xx, bx, w, wrap), _axis(yy, by, h, wrap)
            if ox * ox + oy * oy > rb * rb:
                continue
            i = (yy % h) * w + xx % w
            if mass[i] == 0 or (owner[i] != ka + 1 and owner[i] != kb + 1):
                continue
            cells[n] = i
            n += 1
            total += mass[i]
            px += mass[i] * kin[i, 0]
            py += mass[i] * kin[i, 1]
    if n == 0:
        return 0
    vcx, vcy = px / total, py / total
    sx = sy = 0.0
    for t in range(n):
        i = cells[t]
        lateral = _axis(i % w, mx, w, wrap) * -dy + _axis(i // w, my, h, wrap) * dx
        if lateral == 0.0:
            lateral = np.random.random() - 0.5
        ang = side + (0.0 if lateral > 0.0 else np.pi) + (np.random.random() - 0.5) * (np.pi / 2.0)
        v = speed * (0.5 + 0.5 * np.random.random())
        kin[i, 0] = v * np.cos(ang)
        kin[i, 1] = v * np.sin(ang)
        sx += mass[i] * kin[i, 0]
        sy += mass[i] * kin[i, 1]
    for t in range(n):
        i = cells[t]
        kin[i, 0] += vcx - sx / total                    # the splash adds no momentum
        kin[i, 1] += vcy - sy / total
        stamp[i] &= ~np.uint32(1)                        # no longer wedged
        owner[i] = 0
        wake_around(i, w, h, mass, flag, wrap)
    return np.int64(total)


@njit(cache=True)
def star_order(stars, nb, w, h, base, bucket, wrap):
    """Rank the cells round each star (rows of x, y, radius) for leading-particles-first processing in its own frame
    (where its particles move, see step): innermost first, so matter falls onto it in order. Other cells keep their
    rank in base."""
    for k in range(stars.shape[0]):
        cx, cy, r = stars[k, 0], stars[k, 1], stars[k, 2]
        c = _cell(int(round(cx)), int(round(cy)), w, h, wrap)
        b0 = np.int64(base[c]) if c >= 0 else np.int64(0)
        x0, x1, xmin = _span(cx, r, w, wrap)
        y0, y1, ymin = _span(cy, r, h, wrap)
        for yy in range(y0, y1):
            dy = _axis(yy, cy, h, ymin)
            for xx in range(x0, x1):
                dx = _axis(xx, cx, w, xmin)
                d2 = dx * dx + dy * dy
                if d2 > r * r:
                    continue
                bucket[(yy % h) * w + xx % w] = min(b0 + np.int64(2.0 * np.sqrt(d2)), nb - 1)


@njit(cache=True)
def _block_sum(a, lo, n):
    """a[lo:lo + n].sum() for n <= 128, as numpy adds a block up (eight running sums below 128)."""
    if n < 8:
        res = 0.0
        for i in range(lo, lo + n):
            res += a[i]
        return res
    r0, r1, r2, r3 = a[lo], a[lo + 1], a[lo + 2], a[lo + 3]
    r4, r5, r6, r7 = a[lo + 4], a[lo + 5], a[lo + 6], a[lo + 7]
    i = 8
    while i < n - n % 8:
        r0 += a[lo + i]
        r1 += a[lo + i + 1]
        r2 += a[lo + i + 2]
        r3 += a[lo + i + 3]
        r4 += a[lo + i + 4]
        r5 += a[lo + i + 5]
        r6 += a[lo + i + 6]
        r7 += a[lo + i + 7]
        i += 8
    res = ((r0 + r1) + (r2 + r3)) + ((r4 + r5) + (r6 + r7))
    while i < n:
        res += a[lo + i]
        i += 1
    return res


@njit(cache=True)
def _pairwise_sum(a):
    """a.sum() exactly as numpy adds it up - halves (cut at a multiple of 8) added pairwise down to blocks of at most
    128 - so a kernel can replace numpy arithmetic bit for bit. (Without recursion: a cached recursive kernel
    crashed when loaded back from numba's disk cache.)"""
    n = a.size
    if n <= 128:
        return _block_sum(a, 0, n)
    los = np.empty(128, np.int64)                      # pending halves (lo, n; n < 0: add the last two sums)
    ns = np.empty(128, np.int64)
    sums = np.empty(128)
    top = 1
    los[0], ns[0] = 0, n
    k = 0
    while top > 0:
        top -= 1
        lo, m = los[top], ns[top]
        if m < 0:
            k -= 1
            sums[k - 1] += sums[k]
        elif m <= 128:
            sums[k] = _block_sum(a, lo, m)
            k += 1
        else:
            m2 = m // 2
            m2 -= m2 % 8
            los[top], ns[top] = 0, -1
            los[top + 1], ns[top + 1] = lo + m2, m - m2
            los[top + 2], ns[top + 2] = lo, m2
            top += 3
    return sums[0]


@njit(cache=True)
def damp_star(idx, x, y, damping, lock, w, h, mass, kin, wrap):
    """World._damp_stars for one star, whose particles are in cells idx, centred on (x, y): its particles' motion
    relative to it, apart from its moving and turning as a whole (not turning either when lock), fades by damping.
    The same arithmetic as the numpy it replaced, in the same order (~5 us a star, not ~130)."""
    n = idx.size
    m = np.empty(n)
    dx = np.empty(n)
    dy = np.empty(n)
    vx = np.empty(n)
    vy = np.empty(n)
    t = np.empty(n)
    for j in range(n):
        i = idx[j]
        m[j] = np.float64(mass[i])
        dx[j] = (i % w) - x
        dy[j] = (i // w) - y
        if wrap:
            dx[j] -= w * np.floor(dx[j] / w + 0.5)
            dy[j] -= h * np.floor(dy[j] / h + 0.5)
        vx[j] = np.float64(kin[i, 0])
        vy[j] = np.float64(kin[i, 1])
    total = _pairwise_sum(m)
    for j in range(n):
        t[j] = m[j] * dx[j]
    cx = _pairwise_sum(t) / total               # about their centre of mass
    for j in range(n):
        dx[j] -= cx
        t[j] = m[j] * dy[j]
    cy = _pairwise_sum(t) / total
    for j in range(n):
        dy[j] -= cy
        t[j] = m[j] * vx[j]
    ux = _pairwise_sum(t) / total
    for j in range(n):
        t[j] = m[j] * vy[j]
    uy = _pairwise_sum(t) / total
    for j in range(n):
        t[j] = m[j] * (dx[j] * dx[j] + dy[j] * dy[j])
    inertia = _pairwise_sum(t)
    om = 0.0
    if inertia > 0:                                    # its spin, as a solid body
        for j in range(n):
            t[j] = m[j] * (dx[j] * (vy[j] - uy) - dy[j] * (vx[j] - ux))
        om = _pairwise_sum(t) / inertia
    if lock:
        om = 0.0
    keep2 = 1.0 - (1.0 - damping) ** 2
    for j in range(n):                                 # (from the values read above: a cell listed twice gets the
        i = idx[j]                                     #   same, as numpy's fancy -= gave it)
        jx, jy = (vx[j] - ux) + om * dy[j], (vy[j] - uy) - om * dx[j]
        kin[i, 0] = np.float32(vx[j] - damping * jx)
        kin[i, 1] = np.float32(vy[j] - damping * jy)
        kin[i, 4] += np.float32(0.5 * m[j] * (jx * jx + jy * jy) * keep2)   # the jostling it calms becomes heat


@njit(cache=True)
def owned_cells(cx, cy, r, k, w, h, owner, wrap):
    """The cells within r of (cx, cy) - as World._disk_cells counts them, in the same order - that hold star k's
    particles (owner k + 1). (World._star_cells ran on numpy temporaries at ~0.2 ms a star, several times a tick.)"""
    x0, x1 = np.int64(np.floor(cx - r)), np.int64(np.floor(cx + r)) + 2
    y0, y1 = np.int64(np.floor(cy - r)), np.int64(np.floor(cy + r)) + 2
    out = np.empty(max(0, (x1 - x0) * (y1 - y0)), np.int64)
    n = 0
    for yy in range(y0, y1):
        dy = yy - cy
        for xx in range(x0, x1):
            dx = xx - cx
            if dx * dx + dy * dy > r * r:
                continue
            if wrap:
                x_, y_ = xx % w, yy % h
            elif xx < 0 or xx >= w or yy < 0 or yy >= h:
                continue
            else:
                x_, y_ = xx, yy
            i = y_ * w + x_
            if owner[i] == k + 1:
                out[n] = i
                n += 1
    return out[:n]


@njit(cache=True)
def star_motion(stars, w, h, mass, kin, owner, out, wrap):
    """Each star's body - its particles (owner k + 1 within radius r of (x, y): rows of x, y, r) that rest on another
    of its particles, towards its centre - not the loose matter round it: out rows get their mass and momentum (and,
    in out[k, 3:6], those of all its particles)."""
    out[:] = 0.0
    for k in range(stars.shape[0]):
        cx, cy, r = stars[k, 0], stars[k, 1], stars[k, 2]
        x0, x1, xmin = _span(cx, r, w, wrap)
        y0, y1, ymin = _span(cy, r, h, wrap)
        for yy in range(y0, y1):
            dy = _axis(yy, cy, h, ymin)
            for xx in range(x0, x1):
                dx = _axis(xx, cx, w, xmin)
                if dx * dx + dy * dy > r * r:
                    continue
                i = (yy % h) * w + xx % w
                if owner[i] == k + 1 and mass[i] != 0:
                    m = np.float64(mass[i])
                    c = 0 if _held_up(xx % w, yy % h, k + 1, -dx, -dy, w, h, mass, owner, wrap) >= 0 else 3
                    out[k, c] += m
                    out[k, c + 1] += m * kin[i, 0]
                    out[k, c + 2] += m * kin[i, 1]


@njit(cache=True, parallel=True)
def star_motion_par(stars, w, h, mass, kin, owner, out, wrap):
    """star_motion() on all cores, a star at a time (the same sums)."""
    out[:] = 0.0
    for k in prange(stars.shape[0]):
        cx, cy, r = stars[k, 0], stars[k, 1], stars[k, 2]
        x0, x1, xmin = _span(cx, r, w, wrap)
        y0, y1, ymin = _span(cy, r, h, wrap)
        for yy in range(y0, y1):
            dy = _axis(yy, cy, h, ymin)
            for xx in range(x0, x1):
                dx = _axis(xx, cx, w, xmin)
                if dx * dx + dy * dy > r * r:
                    continue
                i = (yy % h) * w + xx % w
                if owner[i] == k + 1 and mass[i] != 0:
                    m = np.float64(mass[i])
                    c = 0 if _held_up(xx % w, yy % h, k + 1, -dx, -dy, w, h, mass, owner, wrap) >= 0 else 3
                    out[k, c] += m
                    out[k, c + 1] += m * kin[i, 0]
                    out[k, c + 2] += m * kin[i, 1]


@njit(cache=True)
def star_shift(k, sx, sy, cx, cy, r, e, wall_e, w, h, mass, kin, quad, shade, stamp, flag, owner, solid, hole,
               absorbed, push, star_mass, wrap):
    """Carry star k (its particles, owner k + 1, within r of (cx, cy)) one cell along (sx, sy), front first: each
    particle moves into the next cell if it is free. Into matter not of the star it collides (restitution e): from
    loose matter the knock it takes is added to push (momentum, for the star as a whole: World.carry_stars spreads it
    over all its particles, as pressure would, rather than one front particle being slowed and left behind), from
    another star's particle it takes it itself, so crashing stars crumple into each other; loose matter lighter
    than STAR_SHOVE_SHARE of the star (star_mass) is shoved aside - the star moves as one body, so it is the star's
    mass that shoves, not the one particle's - and anything else blocks it. Blocked, or bouncing off solid ground or the border (wall_e), it stays
    behind and its star's pull brings it back. One carried into a super well's core is swallowed. Returns how many
    moved."""
    x0, x1, xmin = _span(cx, r, w, wrap)
    y0, y1, ymin = _span(cy, r, h, wrap)
    cells = np.empty((y1 - y0) * (x1 - x0), np.int64)
    ahead = np.empty(cells.size)
    n = 0
    for yy in range(y0, y1):
        dy = _axis(yy, cy, h, ymin)
        for xx in range(x0, x1):
            dx = _axis(xx, cx, w, xmin)
            if dx * dx + dy * dy > r * r:
                continue
            i = (yy % h) * w + xx % w
            if owner[i] == k + 1 and mass[i] != 0:
                cells[n] = i
                ahead[n] = -(dx * sx + dy * sy)
                n += 1
    inv = 0.7071067811865476 if sx != 0 and sy != 0 else 1.0
    nx_, ny_ = sx * inv, sy * inv
    moved = 0
    for t in np.argsort(ahead[:n]):
        i = cells[t]
        x, y = i % w + sx, i // w + sy
        if wrap:
            x, y = x % w, y % h
        elif x < 0 or x >= w or y < 0 or y >= h:
            if (x < 0 or x >= w) and kin[i, 0] * sx > 0.0:
                kin[i, 0] = -kin[i, 0] * wall_e
            if (y < 0 or y >= h) and kin[i, 1] * sy > 0.0:
                kin[i, 1] = -kin[i, 1] * wall_e
            continue
        j = y * w + x
        if hole[j]:
            _absorb(absorbed, hole[j] - 1, mass[i], kin[i, 0], kin[i, 1], x, y)
            _clear(i, mass, kin, quad)
            owner[i] = 0
            wake_around(i, w, h, mass, flag, wrap)
            continue
        u = kin[i, 0] * nx_ + kin[i, 1] * ny_
        if solid[j]:
            if u > 0.0:
                kin[i, 0] -= (1.0 + wall_e) * u * nx_
                kin[i, 1] -= (1.0 + wall_e) * u * ny_
            continue
        if mass[j] != 0:
            if owner[j] == k + 1:
                continue                                 # (its own particle ahead hasn't moved: wait behind it)
            u -= kin[j, 0] * nx_ + kin[j, 1] * ny_       # ploughing into other matter: they collide
            if u > 0.0:
                mi, mj = np.float64(mass[i]), np.float64(mass[j])
                du_i = -(1.0 + e) * mj * u / (mi + mj)
                du_j = (1.0 + e) * mi * u / (mi + mj)
                if owner[j] == 0:                        # loose matter: the star as a whole takes the knock (push,
                    push[0] += mi * du_i * nx_           # spread over it by the World), not this particle alone
                    push[1] += mi * du_i * ny_
                else:                                    # another star's: these particles meet (so crashing stars
                    kin[i, 0] += du_i * nx_              # crumple into each other rather than bounce off whole)
                    kin[i, 1] += du_i * ny_
                kin[j, 0] += du_j * nx_
                kin[j, 1] += du_j * ny_
                stamp[j] &= ~np.uint32(1)
                flag[j] = 1
            if owner[j] != 0 or mass[j] >= star_mass * STAR_SHOVE_SHARE:
                continue                                 # another star's, or too heavy to shove: it blocks the way
            # lighter loose matter is shoved out of the way rather than standing like a wall: ahead or aside into a
            # free cell if there is one, else it slips past behind (the two swap) - densely poured dust has no room
            to = -1
            for ox_, oy_ in ((sx, sy), (-sy, sx), (sy, -sx)):
                t = _cell(x + ox_, y + oy_, w, h, wrap)
                if t >= 0 and mass[t] == 0 and not solid[t] and not hole[t]:
                    to = t
                    break
            if to >= 0:
                _put(j, to, mass, kin, quad, shade, stamp, owner)
                flag[to] = 1
            else:
                _swap(i, j, mass, kin, quad, shade, stamp, owner)
                flag[i] = 1
                flag[j] = 1
                wake_around(i, w, h, mass, flag, wrap)
                moved += 1
                continue
        _put(i, j, mass, kin, quad, shade, stamp, owner)
        owner[j] = k + 1
        flag[j] = 1
        wake_around(i, w, h, mass, flag, wrap)
        moved += 1
    return moved


@njit(cache=True)
def _carry_star(k, plan, nsteps, steps, e, wall_e, w, h, mass, kin, quad, shade, stamp, flag, owner, solid, hole,
                absorbed, push, wrap):
    """World.carry_stars' work on the grid for star k (plan row: x, y, r, cos and sin of its turn or 0 and 0 for
    none, its mass): turn its particles' velocities (in float32, as numpy did), carry it nsteps[k] cells
    (star_shift, steps[k]) and share the knocks it took (push) out over all of it."""
    x, y, r, c, sn, star_mass = plan[k, 0], plan[k, 1], plan[k, 2], plan[k, 3], plan[k, 4], plan[k, 5]
    if c != 0.0 or sn != 0.0:
        c32, s32 = np.float32(c), np.float32(sn)
        for i in owned_cells(x, y, r, k, w, h, owner, wrap):
            vx, vy = kin[i, 0], kin[i, 1]
            kin[i, 0] = c32 * vx - s32 * vy
            kin[i, 1] = s32 * vx + c32 * vy
    cx = cy = 0
    for q in range(nsteps[k]):
        sx, sy = steps[k, q, 0], steps[k, q, 1]
        star_shift(k, sx, sy, x + cx, y + cy, r, e, wall_e, w, h, mass, kin, quad, shade, stamp, flag, owner, solid,
                   hole, absorbed, push, star_mass, wrap)
        cx += sx
        cy += sy
    if push[0] != 0.0 or push[1] != 0.0:
        idx = owned_cells(x + cx, y + cy, r, k, w, h, owner, wrap)
        held = 0
        for i in idx:
            held += np.int64(mass[i])
        if held > 0:
            px, py = push[0] / np.float64(held), push[1] / np.float64(held)
            for i in idx:                                # (float32 += float64, as numpy does it)
                kin[i, 0] = np.float32(np.float64(kin[i, 0]) + px)
                kin[i, 1] = np.float32(np.float64(kin[i, 1]) + py)


@njit(cache=True)
def carry_stars(plan, nsteps, steps, e, wall_e, w, h, mass, kin, quad, shade, stamp, flag, owner, solid, hole,
                absorbed, push, wrap):
    """_carry_star() for every star in turn (push: a row per star)."""
    for k in range(plan.shape[0]):
        _carry_star(k, plan, nsteps, steps, e, wall_e, w, h, mass, kin, quad, shade, stamp, flag, owner, solid, hole,
                    absorbed, push[k], wrap)


@njit(cache=True)
def carry_levels(plan, nsteps, steps, w, h, wrap):
    """When each star can be carried (carry_stars_par): the cells star k touches lie within r + 3 of the line it
    is carried along; two stars whose such regions overlap are carried in their turn (the later one at a later
    level), the rest side by side. A region reaching half way round a wrapped grid overlaps everything."""
    n = plan.shape[0]
    mx, my, rad = np.empty(n), np.empty(n), np.empty(n)
    for k in range(n):
        cx = cy = 0
        for q in range(nsteps[k]):
            cx += steps[k, q, 0]
            cy += steps[k, q, 1]
        mx[k], my[k] = plan[k, 0] + 0.5 * cx, plan[k, 1] + 0.5 * cy
        rad[k] = plan[k, 2] + 4.0 + 0.5 * np.sqrt(np.float64(cx * cx + cy * cy))
    level = np.zeros(n, np.int64)
    for k in range(n):
        whole = wrap and 4.0 * rad[k] >= min(w, h)
        for j in range(k):
            if level[j] < level[k]:                      # (it would come before k anyway)
                continue
            if not (whole or (wrap and 4.0 * rad[j] >= min(w, h))):
                dx = _axis(mx[j], mx[k], w, wrap)
                dy = _axis(my[j], my[k], h, wrap)
                if dx * dx + dy * dy >= (rad[j] + rad[k]) * (rad[j] + rad[k]):
                    continue
            level[k] = level[j] + 1
    return level


@njit(cache=True, parallel=True)
def carry_stars_par(order, starts, plan, nsteps, steps, e, wall_e, w, h, mass, kin, quad, shade, stamp, flag, owner,
                    solid, hole, absorbed, push, wrap):
    """carry_stars() on all cores, the same result: the stars of a level (order[starts[l]:starts[l + 1]], from
    carry_levels) touch different cells, so they are carried side by side, and stars that share cells still go in
    their turn. absorbed and push: a row per star."""
    for lv in range(starts.size - 1):
        for q in prange(starts[lv], starts[lv + 1]):
            k = order[q]
            _carry_star(k, plan, nsteps, steps, e, wall_e, w, h, mass, kin, quad, shade, stamp, flag, owner, solid,
                        hole, absorbed[k], push[k], wrap)


# --- blobs carried by the global orbit ------------------------------------------------------------------
# A packed clump of matter can't keep up with the global orbit moving a particle at a time: its own gravity pulls its
# particles into the gaps the first ones leave, and it churns in place. So, as stars carry themselves, packed blobs
# are carried round as a whole (World._carry_blobs) and their particles only move relative to the blob in step().

@njit(cache=True)
def find_blobs(occupied, mass, owner, w, h, wrap, labels, stack, offx, offy):
    """Number every group of touching particles (8-neighbours, across a wrapped border too) that belong to no star:
    labels[i] = 1, 2, ... for their cells, 0 elsewhere. occupied: the cells holding a particle, in order. Returns a
    row per group: cells, mass, centre of mass x and y, and radius of gyration (cells; how spread out it is).
    offx / offy: scratch."""
    labels[:] = 0
    rows = np.zeros((64, 5))
    n = 0
    for s in occupied:
        if owner[s] != 0 or labels[s] != 0:
            continue
        n += 1
        labels[s] = n
        offx[s] = 0
        offy[s] = 0
        top = 1
        stack[0] = s
        cnt = 0
        m = sx = sy = sxx = mx = my = 0.0
        while top > 0:
            top -= 1
            i = stack[top]
            x, y = i % w, i // w
            px, py = offx[i], offy[i]                    # where it is from the first cell, not wrapped
            mi = np.float64(mass[i])
            cnt += 1
            m += mi
            mx += mi * px
            my += mi * py
            sx += px
            sy += py
            sxx += px * px + py * py
            for dy in range(-1, 2):
                yy = y + dy
                if yy < 0 or yy >= h:
                    if not wrap:
                        continue
                    yy += h if yy < 0 else -h
                for dx in range(-1, 2):
                    xx = x + dx
                    if xx < 0 or xx >= w:
                        if not wrap:
                            continue
                        xx += w if xx < 0 else -w
                    j = yy * w + xx
                    if mass[j] != 0 and owner[j] == 0 and labels[j] == 0:
                        labels[j] = n
                        offx[j] = px + dx
                        offy[j] = py + dy
                        stack[top] = j
                        top += 1
        if n > rows.shape[0]:
            grown = np.zeros((2 * rows.shape[0], 5))
            grown[:rows.shape[0]] = rows
            rows = grown
        cx, cy = s % w + mx / m, s // w + my / m
        if wrap:
            cx %= w
            cy %= h
        rows[n - 1, 0] = cnt
        rows[n - 1, 1] = m
        rows[n - 1, 2] = cx
        rows[n - 1, 3] = cy
        rows[n - 1, 4] = np.sqrt(max(sxx / cnt - (sx / cnt) ** 2 - (sy / cnt) ** 2, 0.0))
    return rows[:n]


@njit(cache=True)
def carry_blobs(occupied, labels, moves, e, wall_e, w, h, mass, kin, quad, shade, stamp, flag, solid, hole, absorbed,
                wrap):
    """Carry each blob b (labels, as find_blobs numbered them from `occupied`) moves[b] cells (x, y) as a whole: a cell
    at a time, diagonally while both are left, front first, as star_shift carries a star - each particle moves into the
    next cell if it is free. One that is blocked stays behind: by matter not of the blob it collides with it
    (restitution e), by solid ground or the border it bounces (wall_e). One carried into a super well's core is
    swallowed. The labels move with the particles. Returns how many moves were made."""
    nb = moves.shape[0]
    start = np.zeros(nb + 1, np.int64)
    for i in occupied:                                   # only these can be labelled: no sweep of the whole grid
        b = labels[i]
        if b > 0 and (moves[b, 0] != 0 or moves[b, 1] != 0):
            start[b + 1] += 1
    for b in range(nb):
        start[b + 1] += start[b]
    cells = np.empty(start[nb], np.int64)
    fill = start.copy()
    for i in occupied:
        b = labels[i]
        if b > 0 and (moves[b, 0] != 0 or moves[b, 1] != 0):
            cells[fill[b]] = i
            fill[b] += 1
    moved = 0
    for b in range(1, nb):
        c0, c1 = start[b], start[b + 1]
        if c1 == c0:
            continue
        dx, dy = moves[b, 0], moves[b, 1]
        ahead = np.empty(c1 - c0)
        while dx != 0 or dy != 0:
            sx = 1 if dx > 0 else (-1 if dx < 0 else 0)
            sy = 1 if dy > 0 else (-1 if dy < 0 else 0)
            dx -= sx
            dy -= sy
            x0, y0 = cells[c0] % w, cells[c0] // w
            for t in range(c0, c1):                      # front first: furthest along (sx, sy) from any one cell
                i = cells[t]
                ahead[t - c0] = -(_axis(i % w, x0, w, wrap) * sx + _axis(i // w, y0, h, wrap) * sy)
            inv = 0.7071067811865476 if sx != 0 and sy != 0 else 1.0
            nx_, ny_ = sx * inv, sy * inv
            for q in np.argsort(ahead):
                t = c0 + q
                i = cells[t]
                if labels[i] != b or mass[i] == 0:       # swallowed on an earlier step
                    continue
                x, y = i % w + sx, i // w + sy
                if wrap:
                    x, y = x % w, y % h
                elif x < 0 or x >= w or y < 0 or y >= h:
                    if (x < 0 or x >= w) and kin[i, 0] * sx > 0.0:
                        kin[i, 0] = -kin[i, 0] * wall_e
                    if (y < 0 or y >= h) and kin[i, 1] * sy > 0.0:
                        kin[i, 1] = -kin[i, 1] * wall_e
                    continue
                j = y * w + x
                if hole[j]:
                    _absorb(absorbed, hole[j] - 1, mass[i], kin[i, 0], kin[i, 1], i % w, i // w)
                    _clear(i, mass, kin, quad)
                    labels[i] = 0
                    wake_around(i, w, h, mass, flag, wrap)
                    continue
                u = kin[i, 0] * nx_ + kin[i, 1] * ny_
                if solid[j]:
                    if u > 0.0:
                        kin[i, 0] -= (1.0 + wall_e) * u * nx_
                        kin[i, 1] -= (1.0 + wall_e) * u * ny_
                    continue
                if mass[j] != 0:
                    if labels[j] != b:                   # ploughing into other matter: they collide
                        u -= kin[j, 0] * nx_ + kin[j, 1] * ny_
                        if u > 0.0:
                            mi, mj = np.float64(mass[i]), np.float64(mass[j])
                            du_i = -(1.0 + e) * mj * u / (mi + mj)
                            du_j = (1.0 + e) * mi * u / (mi + mj)
                            kin[i, 0] += du_i * nx_
                            kin[i, 1] += du_i * ny_
                            kin[j, 0] += du_j * nx_
                            kin[j, 1] += du_j * ny_
                            stamp[j] &= ~np.uint32(1)
                            flag[j] = 1
                    continue
                mass[j] = mass[i]
                for c in range(KIN):
                    kin[j, c] = kin[i, c]
                for c in range(4):
                    quad[j, c] = quad[i, c]
                shade[j] = shade[i]
                stamp[j] = stamp[i]
                labels[j] = b
                _clear(i, mass, kin, quad)
                labels[i] = 0
                flag[j] = 1
                wake_around(i, w, h, mass, flag, wrap)
                cells[t] = j
                moved += 1
    return moved


# --- rendering ---------------------------------------------------------------------------------------

@njit(cache=True, inline="always")
def _render_cell(i, mode, mass, kin, quad, flag, mass_lut, heat_lut, shade_mul, shade, bg, vmax, rgb):
    m = mass[i]
    if m == 0:
        rgb[i, 0] = bg[0]
        rgb[i, 1] = bg[1]
        rgb[i, 2] = bg[2]
    elif mode == 0:
        k = shade_mul[shade[i]]
        for c in range(3):
            rgb[i, c] = min(255, (mass_lut[m, c] * k) >> 8)
    elif mode == 1:
        s = np.sqrt(kin[i, 0] * kin[i, 0] + kin[i, 1] * kin[i, 1]) / vmax
        idx = min(255, int(s * 255.0))
        for c in range(3):
            rgb[i, c] = heat_lut[idx, c]
    elif mode == 2:
        fm = np.float64(m)
        lx = ((np.int64(quad[i, 1]) + quad[i, 3]) - (np.int64(quad[i, 0]) + quad[i, 2])) / fm
        ly = ((np.int64(quad[i, 2]) + quad[i, 3]) - (np.int64(quad[i, 0]) + quad[i, 1])) / fm
        rgb[i, 0] = int(128.0 + 120.0 * lx)
        rgb[i, 1] = int(150.0 - 50.0 * (abs(lx) + abs(ly)))
        rgb[i, 2] = int(128.0 + 120.0 * ly)
    elif mode == 4:                                      # heat: as hot as its heat per unit mass would be fast
        s = np.sqrt(2.0 * max(np.float64(kin[i, 4]), 0.0) / m) / vmax
        idx = min(255, int(s * 255.0))
        for c in range(3):
            rgb[i, c] = heat_lut[idx, c]
    elif flag[i]:
        rgb[i, 0] = 240
        rgb[i, 1] = 190
        rgb[i, 2] = 90
    else:
        rgb[i, 0] = 70
        rgb[i, 1] = 76
        rgb[i, 2] = 90


@njit(cache=True)
def render(mode, mass, kin, quad, shade, flag, mass_lut, heat_lut, shade_mul, bg, vmax, rgb):
    """Fill rgb (n x 3) for one frame. mode 0 mass, 1 speed, 2 children lean, 3 awake/asleep."""
    for i in range(mass.size):
        _render_cell(i, mode, mass, kin, quad, flag, mass_lut, heat_lut, shade_mul, shade, bg, vmax, rgb)


@njit(cache=True, parallel=True)
def render_par(mode, mass, kin, quad, shade, flag, mass_lut, heat_lut, shade_mul, bg, vmax, rgb):
    """render() on all cores (the same picture: every cell is drawn on its own)."""
    for i in prange(mass.size):
        _render_cell(i, mode, mass, kin, quad, flag, mass_lut, heat_lut, shade_mul, shade, bg, vmax, rgb)


@njit(cache=True, parallel=True)
def occupied_par(mass, chunks):
    """np.flatnonzero(mass) on all cores, in the same (rising) order: each of `chunks` runs counts its own
    particles, then writes them after those of the runs before it."""
    n = mass.size
    size = -(-n // chunks)
    counts = np.zeros(chunks + 1, np.int64)
    for c in prange(chunks):
        k = 0
        for i in range(c * size, min(n, (c + 1) * size)):
            if mass[i]:
                k += 1
        counts[c + 1] = k
    for c in range(chunks):
        counts[c + 1] += counts[c]
    out = np.empty(counts[chunks], np.int64)
    for c in prange(chunks):
        k = counts[c]
        for i in range(c * size, min(n, (c + 1) * size)):
            if mass[i]:
                out[k] = i
                k += 1
    return out
