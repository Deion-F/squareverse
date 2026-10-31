"""numba kernels: the per-tick simulation, brushes, waking and frame rendering.

All particle state lives in flat per-cell arrays (index i = y * w + x, as in sand.py); a cell holds at most one
particle and mass 0 means empty. Only awake particles (flag[i] == 1) are simulated, so settled piles cost nothing.
Everything here is compiled to machine code once and cached on disk (cache=True).

kin[i] = (vx, vy, ox, oy): velocity in cells/tick and the sub-cell offset from the cell centre, so slow velocities
still add up to moves. quad[i] = children per quadrant (up-left, up-right, down-left, down-right); they always sum
to mass[i]. solid[i] = 1 inside a normal well's body (a planet): nothing can enter it. hole[i] = k + 1 when cell
i is inside the core of super well k: a particle that enters it is absorbed.
With wrap on, the borders are continuous: x = -1 is x = w - 1, and so on.
stamp[i] = 2 * tick + blocked for the last tick the particle was simulated in, so the kernel can tell
whether a neighbour is free to move or jammed against something with a stale velocity.
"""

import numpy as np
from numba import njit

# indices into the float64 params array handed to step()
(P_VMAX, P_MAX_STEPS, P_WALL_E, P_E, P_IMPACT_MIN, P_SLIDE_DAMP, P_SINK, P_DRAG, P_SLEEP_EPS,
 P_CHILD_MOVES, P_SLOSH, P_LEAN, P_MERGE_ON, P_STICK, P_MERGE_CHANCE, P_MAX_MASS,
 P_SPLIT_ON, P_BIND, P_KICK, P_SG_ON, P_CHILD_EVERY, P_ORBIT_W, P_ORBIT_GRIP, P_ORBIT_CX, P_ORBIT_CY,
 P_SLEEP_ACCEL, P_WRAP, P_ORBIT_VMIN, P_WHIRL_SPEED, P_WHIRL_GRIP, P_WHIRL_INFALL) = range(31)
N_PARAMS = 31

# indices into the int64 stats array filled by step()
S_MOVED, S_COLLISIONS, S_MERGES, S_SPLITS, S_SINKS, S_ABSORBED = range(6)
N_STATS = 6

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
def _clear(i, mass, kin, quad):
    mass[i] = 0
    for c in range(4):
        kin[i, c] = 0.0
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
    """Pour particles with a mass drawn uniformly from m_lo..m_hi (m_hi > 0), or erase (m_hi == 0), in a circle of
    r cells around cell (cx, cy)."""
    ri = int(r) + 1
    r2 = r * r
    for y in range(max(0, cy - ri), min(h, cy + ri + 1)):
        for x in range(max(0, cx - ri), min(w, cx + ri + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 > r2:
                continue
            i = y * w + x
            if m_hi > 0:
                if mass[i] == 0 and not solid[i] and np.random.random() < chance:
                    m = m_lo if m_lo == m_hi else np.random.randint(m_lo, m_hi + 1)
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
def _split(j, kick, w, h, tick, mass, kin, quad, shade, stamp, flag, solid, wrap):
    """Break the particle in cell j in two, the second part in a free neighbouring cell. Each quadrant's children
    are halved (odd ones go either way), so mass is conserved. Returns True on success."""
    x, y = j % w, j // w
    start = np.random.randint(0, 8)
    f = -1
    fdx = fdy = 0
    for k in range(8):
        d = (start + k) % 8
        t = _cell(x + DX[d], y + DY[d], w, h, wrap)
        if t >= 0 and mass[t] == 0 and not solid[t]:
            f, fdx, fdy = t, DX[d], DY[d]
            break
    if f < 0:
        return False
    m = np.int64(mass[j])
    ma = 0
    for c in range(4):
        q = np.int64(quad[j, c])
        a = q // 2
        if q & 1 and np.random.random() < 0.5:
            a += 1
        quad[f, c] = q - a
        quad[j, c] = a
        ma += a
    if ma == 0 or ma == m:                               # every odd child went the same way: hand one over
        src, dst = (f, j) if ma == 0 else (j, f)
        for c in range(4):
            if quad[src, c] > 0:
                quad[src, c] -= 1
                quad[dst, c] += 1
                break
        ma = 1 if ma == 0 else m - 1
    mb = m - ma
    mass[j] = ma
    mass[f] = mb
    # the parts fly apart along the j -> f line with equal and opposite momentum
    inv = 0.7071067811865476 if fdx != 0 and fdy != 0 else 1.0
    ex, ey = fdx * inv, fdy * inv
    p = kick * ma * mb / m
    kin[f, 0] = kin[j, 0] + p / mb * ex
    kin[f, 1] = kin[j, 1] + p / mb * ey
    kin[f, 2] = 0.0
    kin[f, 3] = 0.0
    kin[j, 0] -= p / ma * ex
    kin[j, 1] -= p / ma * ey
    shade[f] = shade[j]
    stamp[f] = 2 * tick
    wake(j, mass, flag)
    wake(f, mass, flag)
    return True


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


# --- the tick ----------------------------------------------------------------------------------------

@njit(cache=True)
def step(w, h, tick, P, mass, kin, quad, shade, stamp, flag, cur, order, bucket_counts, bucket, fx, fy, sgx, sgy,
         sg_block, sg_w, hole, absorbed, solid, gvx, gvy, whirls, stats):
    """Advance one tick: simulate the awake particles and flag the ones that stay awake. Returns how many ran.
    Mass swallowed by super well k is added to absorbed[k]. whirls holds each super well's whirlpool (rows of x, y,
    range, spin, pull strength, softening).

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
    nb = bucket_counts.size - 1
    bucket_counts[:] = 0
    for t in range(n):
        bucket_counts[bucket[cur[t]] + 1] += 1
    for b in range(nb):
        bucket_counts[b + 1] += bucket_counts[b]
    if tick & 1:
        for t in range(n):
            b = bucket[cur[t]]
            order[bucket_counts[b]] = cur[t]
            bucket_counts[b] += 1
    else:                                                # fill each bucket back to front: reversed memory order
        for b in range(nb):
            bucket_counts[b] = bucket_counts[b + 1]
        for t in range(n):
            b = bucket[cur[t]]
            bucket_counts[b] -= 1
            order[bucket_counts[b]] = cur[t]

    vmax = P[P_VMAX]
    vmax2 = vmax * vmax
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
    merge_on = P[P_MERGE_ON] != 0.0
    stick = P[P_STICK]
    merge_chance = P[P_MERGE_CHANCE]
    max_mass = int(P[P_MAX_MASS])
    split_on = P[P_SPLIT_ON] != 0.0
    bind = P[P_BIND]
    kick = P[P_KICK]
    sg_on = P[P_SG_ON] != 0.0
    orbit_w = P[P_ORBIT_W]
    orbit_grip = P[P_ORBIT_GRIP]
    orbit_vmin = P[P_ORBIT_VMIN]
    whirl_speed = P[P_WHIRL_SPEED]
    whirl_grip = P[P_WHIRL_GRIP]
    whirl_infall = P[P_WHIRL_INFALL]
    ocx, ocy = P[P_ORBIT_CX], P[P_ORBIT_CY]
    wrap = P[P_WRAP] != 0.0

    for t in range(n):
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

        # forces: external field + self-gravity + the children's lean
        ax = np.float64(fx[i0])
        ay = np.float64(fy[i0])
        if sg_on:
            b = (y // sg_block) * sg_w + x // sg_block
            ax += sgx[b]
            ay += sgy[b]
        if child_moves > 0 and (tick + i0) % child_every == 0:
            q0, q1, q2, q3 = _slosh(q0, q1, q2, q3, m, ax, ay, child_moves, slosh)
        if lean != 0.0:
            ax += lean * ((q1 + q3) - (q0 + q2)) / m
            ay += lean * ((q2 + q3) - (q0 + q1)) / m
        if orbit_w != 0.0:
            ox_, oy_ = orbit_accel(x - ocx, y - ocy, kin[i0, 0], kin[i0, 1], orbit_w, orbit_grip, orbit_vmin)
            ax += ox_
            ay += oy_
        for k in range(whirls.shape[0]):
            wx_, wy_ = whirl(_axis(x, whirls[k, 0], w, wrap), _axis(y, whirls[k, 1], h, wrap), kin[i0, 0], kin[i0, 1],
                             whirls[k, 2], whirls[k, 3], whirls[k, 4], whirls[k, 5], whirl_speed, whirl_grip,
                             whirl_infall)
            ax += wx_
            ay += wy_

        vx = kin[i0, 0] + ax
        vy = kin[i0, 1] + ay
        if drag > 0.0:
            vx *= 1.0 - drag
            vy *= 1.0 - drag
        v2 = vx * vx + vy * vy
        if v2 > vmax2:
            s = vmax / np.sqrt(v2)
            vx *= s
            vy *= s
        ox = kin[i0, 2] + vx
        oy = kin[i0, 3] + vy

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
                vx = -vx * wall_e if abs(vx) > impact else 0.0
                if press > 0.0 and abs(vy) < impact:
                    vy = 0.0
                ox = 0.49 * sx
                blocked = True
                continue
            if ny < 0 or ny >= h:
                press = max(0.0, ay * sy)
                impact = impact_min + press
                vy = -vy * wall_e if abs(vy) > impact else 0.0
                if press > 0.0 and abs(vx) < impact:
                    vx = 0.0
                oy = 0.49 * sy
                blocked = True
                continue
            j = ny * w + nx
            if hole[j]:                                  # into a super well's core: absorbed
                absorbed[hole[j] - 1] += m
                mass[i] = 0
                wake_around(i, w, h, mass, flag, wrap)
                stats[S_ABSORBED] += 1
                alive = False
                break
            rock = solid[j] != 0
            if mass[j] == 0 and not rock:                # free: move
                mass[i] = 0
                mass[j] = m
                i, x, y = j, nx, ny
                ox -= sx
                oy -= sy
                moved = True
                continue

            # Occupied by a particle or a planet's solid ground. Velocities below are relative to what is in the
            # way, so particles flowing together (an orbiting ring) don't brake each other; a jammed particle,
            # like the ground, counts as standing still, whatever velocity it holds.
            if rock:                                     # the ground moves with its planet's spin
                mk = np.int64(0)
                kvx, kvy = np.float64(gvx[j]), np.float64(gvy[j])
            else:
                mk = np.int64(mass[j])
                if stamp[j] & 1:
                    kvx = kvy = 0.0
                else:
                    kvx, kvy = np.float64(kin[j, 0]), np.float64(kin[j, 1])
            inv_len = 0.7071067811865476 if sx != 0 and sy != 0 else 1.0
            nxn, nyn = sx * inv_len, sy * inv_len
            u = (vx - kvx) * nxn + (vy - kvy) * nyn
            if u <= 0.0:
                break                                    # the one ahead is pulling away: wait behind it
            press = max(0.0, ax * nxn + ay * nyn)        # how hard the force pushes it into the other one
            impact = impact_min + press
            if rock:
                if u > impact:                           # bounce off the ground
                    vx -= (1.0 + wall_e) * u * nxn
                    vy -= (1.0 + wall_e) * u * nyn
                    blocked = True
                    break
            else:
                total = m + mk
                if press > 0.0 and m > mk:
                    stay = True                          # a heavier particle keeps trying to sink (sand.py)

                if u > impact:
                    if split_on and mk >= 2 and 0.5 * (m * mk / total) * u * u > bind * mk:
                        if _split(j, kick * u, w, h, tick, mass, kin, quad, shade, stamp, flag, solid, wrap):
                            stats[S_SPLITS] += 1
                            mk = np.int64(mass[j])
                            total = m + mk
                    # 1D collision along the step direction with restitution e (momentum conserved)
                    du_i = -(1.0 + e) * mk * u / total
                    du_k = (1.0 + e) * m * u / total
                    vx += du_i * nxn
                    vy += du_i * nyn
                    kin[j, 0] += du_k * nxn
                    kin[j, 1] += du_k * nyn
                    wake(j, mass, flag)
                    stats[S_COLLISIONS] += 1

                if merge_on and u < stick and total <= max_mass and np.random.random() < merge_chance:
                    kin[j, 0] = (m * vx + mk * kin[j, 0]) / total
                    kin[j, 1] = (m * vy + mk * kin[j, 1]) / total
                    mass[j] = total
                    quad[j, 0] += q0
                    quad[j, 1] += q1
                    quad[j, 2] += q2
                    quad[j, 3] += q3
                    mass[i] = 0
                    wake_around(i, w, h, mass, flag, wrap)
                    wake(j, mass, flag)
                    stats[S_MERGES] += 1
                    alive = False
                    break

                if press > 0.0 and m > mk and np.random.random() < sink * (1.0 - mk / m):
                    # pressed by the force, a heavier particle pushes through the lighter one, which takes its place
                    # (and is done this tick)
                    vx = kvx + (vx - kvx) * 0.5
                    vy = kvy + (vy - kvy) * 0.5
                    mass[i] = mass[j]
                    for c in range(4):
                        kin[i, c] = kin[j, c]
                        quad[i, c] = quad[j, c]
                    shade[i] = shade[j]
                    stamp[i] = 2 * tick
                    wake(i, mass, flag)
                    mass[j] = m
                    i, x, y = j, nx, ny
                    ox -= sx
                    oy -= sy
                    moved = True
                    stats[S_SINKS] += 1
                    break

            d = DIR_OF[(sy + 1) * 3 + sx + 1]
            e2 = _slide_target(x, y, d, w, h, mass, solid, wrap)
            if e2 >= 0:
                tx, ty = (x + DX[e2]) % w, (y + DY[e2]) % h
                j2 = ty * w + tx
                mass[i] = 0
                mass[j2] = m
                i, x, y = j2, tx, ty
                # keep the offset only along axes the particle wanted to travel anyway
                if DX[e2] != 0:
                    ox = ox - DX[e2] if DX[e2] * ox >= 0.5 else 0.0
                if DY[e2] != 0:
                    oy = oy - DY[e2] if DY[e2] * oy >= 0.5 else 0.0
                vx = kvx + (vx - kvx) * slide_damp
                vy = kvy + (vy - kvy) * slide_damp
                moved = True
                continue

            # blocked: drop whatever relative velocity still points into the obstacle
            vn = (vx - kvx) * nxn + (vy - kvy) * nyn
            if vn > 0.0:
                vx -= vn * nxn
                vy -= vn * nyn
            rx, ry = vx - kvx, vy - kvy
            if press > 0.0 and rx * rx + ry * ry < impact * impact:
                vx, vy = kvx, kvy                        # static friction: resting contact holds still
            blocked = True
            break

        if alive and hole[i]:                            # slid or was put into a core
            absorbed[hole[i] - 1] += m
            mass[i] = 0
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
        quad[i, 0] = q0
        quad[i, 1] = q1
        quad[i, 2] = q2
        quad[i, 3] = q3
        shade[i] = sh
        stamp[i] = 2 * tick + (1 if blocked else 0)
        if moved or stay or vx * vx + vy * vy > eps2 or (not blocked and ax * ax + ay * ay > accel_eps2):
            wake(i, mass, flag)
    return n


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
        absorbed[idx] += absorb_disk(cx, cy, r, w, h, mass, kin, quad, flag, wrap)[0]
        _mark_disk(cx, cy, r, w, h, wrap, hole, idx + 1)


@njit(cache=True)
def mark_solid(bodies, w, h, solid, gvx, gvy, mass, kin, quad, shade, stamp, flag, wrap):
    """Mark every normal well's body (rows of x, y, radius, spin, vx, vy) as solid ground moving with it - its own
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
                        for c in range(4):
                            kin[j, c] = kin[i, c]
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

@njit(cache=True)
def _pull(dx, dy, strength, soft):
    """One well's acceleration and potential at offset (dx, dy) from the point towards the well."""
    inv_r = 1.0 / np.sqrt(dx * dx + dy * dy + soft * soft)
    f = strength * inv_r * inv_r * inv_r
    return dx * f, dy * f, -strength * inv_r


@njit(cache=True)
def whirl(rx, ry, vx, vy, reach, spin, strength, soft, speed, grip, infall):
    """A spinning super well's whirlpool on something at (rx, ry) from it moving at (vx, vy): inside its range
    (reach) its sideways motion is driven towards spin x speed x closeness - but never past `infall` of the speed
    that would hold it in orbit there, so it still spirals in - gripped grip x closeness^2 times as hard, where
    closeness runs from 0 at the edge to 1 at the centre. It starts turning gently on entering and can hardly stay
    still next to the core. spin > 0 turns clockwise on screen; motion in or out is left alone."""
    d2 = rx * rx + ry * ry
    if d2 >= reach * reach or d2 < 1e-6:
        return 0.0, 0.0
    d = np.sqrt(d2)
    close = 1.0 - d / reach
    orbital = np.sqrt(strength * d2 / (d2 + soft * soft) ** 1.5)
    target = min(abs(spin) * speed * close, infall * orbital) * (1.0 if spin >= 0 else -1.0)
    tx, ty = -ry / d, rx / d
    a = grip * close * close * (target - (vx * tx + vy * ty))
    return a * tx, a * ty


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


@njit(cache=True)
def field(w, h, block, wells, near, gx, gy, fx, fy, phi, wrap):
    """External acceleration and potential per cell: uniform gravity (gx, gy) plus softened point wells
    (rows of x, y, strength, softening): accel = strength * d / (|d|^2 + soft^2)^1.5 at every distance (the
    gravitational attraction law). With wrap on, each well pulls the shortest way round the borders.

    Far from a well its pull changes smoothly, so every well is summed only at the centres of block x block cells
    and blended onto the cells in between; within near[k] cells of well k, where it changes fast, its exact pull
    replaces the blend. That keeps a rebuild cheap however many wells there are."""
    cw, ch = -(-w // block), -(-h // block)
    cfx = np.zeros(cw * ch)
    cfy = np.zeros(cw * ch)
    cph = np.zeros(cw * ch)
    nw = wells.shape[0]
    for by in range(ch):
        cy = by * block + (block - 1) * 0.5
        for bx in range(cw):
            cx = bx * block + (block - 1) * 0.5
            sx = sy = sp = 0.0
            for k in range(nw):
                ax, ay, p = _pull(-_axis(cx, wells[k, 0], w, wrap), -_axis(cy, wells[k, 1], h, wrap), wells[k, 2],
                                  wells[k, 3])
                sx += ax
                sy += ay
                sp += p
            b = by * cw + bx
            cfx[b] = sx
            cfy[b] = sy
            cph[b] = sp
    for y in range(h):
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
        for yy in range(y0s, y1s):
            y = yy % h
            ddy = _axis(yy, wy, h, ymin)
            by0, by1, ty, cy0, cy1 = _lerp_axis(y, block, ch, wrap)
            for xx in range(x0s, x1s):
                ddx = _axis(xx, wx, w, xmin)
                if ddx * ddx + ddy * ddy > r * r:
                    continue
                x = xx % w
                bx0, bx1, tx, cx0, cx1 = _lerp_axis(x, block, cw, wrap)
                ex, ey, ep = _pull(-ddx, -ddy, strength, soft)
                # take back what the blend gave this well here, so the exact pull replaces it
                ix = iy = ip = 0.0
                for cy, wy_ in ((cy0, 1 - ty), (cy1, ty)):
                    dyc = -_axis(cy, wy, h, wrap)
                    for cx, wx_ in ((cx0, 1 - tx), (cx1, tx)):
                        ax, ay, p = _pull(-_axis(cx, wx, w, wrap), dyc, strength, soft)
                        ix += wx_ * wy_ * ax
                        iy += wx_ * wy_ * ay
                        ip += wx_ * wy_ * p
                i = y * w + x
                fx[i] += ex - ix
                fy[i] += ey - iy
                phi[i] += ep - ip


@njit(cache=True)
def wake_disk(cx, cy, r, w, h, mass, flag, wrap):
    """Wake every particle within r cells of (cx, cy)."""
    x0, x1, xmin = _span(cx, r, w, wrap)
    y0, y1, ymin = _span(cy, r, h, wrap)
    for yy in range(y0, y1):
        dy = _axis(yy, cy, h, ymin)
        for xx in range(x0, x1):
            dx = _axis(xx, cx, w, xmin)
            if dx * dx + dy * dy <= r * r:
                wake((yy % h) * w + xx % w, mass, flag)


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


# --- rendering ---------------------------------------------------------------------------------------

@njit(cache=True)
def render(mode, mass, kin, quad, shade, flag, mass_lut, heat_lut, shade_mul, bg, vmax, rgb):
    """Fill rgb (n x 3) for one frame. mode 0 mass, 1 speed, 2 children lean, 3 awake/asleep."""
    for i in range(mass.size):
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
        elif flag[i]:
            rgb[i, 0] = 240
            rgb[i, 1] = 190
            rgb[i, 2] = 90
        else:
            rgb[i, 0] = 70
            rgb[i, 1] = 76
            rgb[i, 2] = 90
