"""numba kernels: the per-tick simulation, brushes, waking and frame rendering.

All particle state lives in flat per-cell arrays (index i = y * w + x, as in sand.py); a cell holds at most one
particle and mass 0 means empty. Only awake particles (flag[i] == 1) are simulated, so settled piles cost nothing.
Everything here is compiled to machine code once and cached on disk (cache=True).

kin[i] = (vx, vy, ox, oy): velocity in cells/tick and the sub-cell offset from the cell centre, so slow velocities
still add up to moves. quad[i] = children per quadrant (up-left, up-right, down-left, down-right); they always sum
to mass[i]. stamp[i] = 2 * tick + blocked for the last tick the particle was simulated in, so the kernel can tell
whether a neighbour is free to move or jammed against something with a stale velocity.
"""

import numpy as np
from numba import njit

# indices into the float64 params array handed to step()
(P_VMAX, P_MAX_STEPS, P_WALL_E, P_E, P_IMPACT_MIN, P_SLIDE_DAMP, P_SINK, P_DRAG, P_SLEEP_EPS,
 P_CHILD_MOVES, P_SLOSH, P_LEAN, P_MERGE_ON, P_STICK, P_MERGE_CHANCE, P_MAX_MASS,
 P_SPLIT_ON, P_BIND, P_KICK, P_SG_ON, P_CHILD_EVERY) = range(21)
N_PARAMS = 21

# indices into the int64 stats array filled by step()
S_MOVED, S_COLLISIONS, S_MERGES, S_SPLITS, S_SINKS = range(5)
N_STATS = 5

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
def wake_around(i, w, h, mass, flag):
    x, y = i % w, i // w
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
def place_many(idx, masses, vxs, vys, mass, kin, quad, shade, stamp, flag):
    """Place particles into the given cells, skipping occupied ones. Returns how many were placed."""
    placed = 0
    for t in range(idx.size):
        i = idx[t]
        if mass[i] == 0:
            place(i, masses[t], vxs[t], vys[t], mass, kin, quad, shade, stamp)
            wake(i, mass, flag)
            placed += 1
    return placed


@njit(cache=True)
def brush(cx, cy, r, m, chance, w, h, mass, kin, quad, shade, stamp, flag):
    """Pour particles of mass m (m > 0) or erase (m == 0) in a circle of r cells around cell (cx, cy)."""
    ri = int(r) + 1
    r2 = r * r
    for y in range(max(0, cy - ri), min(h, cy + ri + 1)):
        for x in range(max(0, cx - ri), min(w, cx + ri + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 > r2:
                continue
            i = y * w + x
            if m > 0:
                if mass[i] == 0 and np.random.random() < chance:
                    place(i, m, 0.0, 0.0, mass, kin, quad, shade, stamp)
                    wake(i, mass, flag)
            elif mass[i] != 0:
                _clear(i, mass, kin, quad)
                wake_around(i, w, h, mass, flag)


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
def _slide_target(x, y, d, w, h, mass):
    """sand.py's slide_target for direction index d: slide off diagonally, else topple sideways when there is a
    drop just past the neighbouring cell. Returns the direction index to move in, or -1."""
    first = 1 if np.random.random() < 0.5 else -1
    for k in range(2):
        side = first if k == 0 else -first
        e = (d + side + 8) % 8
        tx, ty = x + DX[e], y + DY[e]
        if 0 <= tx < w and 0 <= ty < h and mass[ty * w + tx] == 0:
            return e
    for k in range(2):
        side = first if k == 0 else -first
        e = (d + side + 8) % 8
        p = (d + 2 * side + 8) % 8
        px, py = x + DX[p], y + DY[p]
        qx, qy = px + DX[e], py + DY[e]
        if (0 <= px < w and 0 <= py < h and mass[py * w + px] == 0
                and 0 <= qx < w and 0 <= qy < h and mass[qy * w + qx] == 0):
            return p
    return -1


@njit(cache=True)
def _split(j, kick, w, h, tick, mass, kin, quad, shade, stamp, flag):
    """Break the particle in cell j in two, the second part in a free neighbouring cell. Each quadrant's children
    are halved (odd ones go either way), so mass is conserved. Returns True on success."""
    x, y = j % w, j // w
    start = np.random.randint(0, 8)
    f = -1
    fdx = fdy = 0
    for k in range(8):
        d = (start + k) % 8
        tx, ty = x + DX[d], y + DY[d]
        if 0 <= tx < w and 0 <= ty < h and mass[ty * w + tx] == 0:
            f, fdx, fdy = ty * w + tx, DX[d], DY[d]
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


# --- the tick ----------------------------------------------------------------------------------------

@njit(cache=True)
def step(w, h, tick, P, mass, kin, quad, shade, stamp, flag, cur, order, bucket_counts, bucket, fx, fy, sgx, sgy,
         sg_block, sg_w, stats):
    """Advance one tick: simulate the awake particles and flag the ones that stay awake. Returns how many ran.

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
            if mass[j] == 0:                             # free: move
                mass[i] = 0
                mass[j] = m
                i, x, y = j, nx, ny
                ox -= sx
                oy -= sy
                moved = True
                continue

            # occupied. Velocities below are relative to the particle in the way, so particles flowing together
            # (an orbiting ring) don't brake each other; a jammed one counts as standing still, whatever
            # velocity it holds.
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
            total = m + mk
            if press > 0.0 and m > mk:
                stay = True                              # a heavier particle keeps trying to sink (sand.py)

            if u > impact:
                if split_on and mk >= 2 and 0.5 * (m * mk / total) * u * u > bind * mk:
                    if _split(j, kick * u, w, h, tick, mass, kin, quad, shade, stamp, flag):
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
                wake_around(i, w, h, mass, flag)
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
            e2 = _slide_target(x, y, d, w, h, mass)
            if e2 >= 0:
                tx, ty = x + DX[e2], y + DY[e2]
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

        if moved:
            stats[S_MOVED] += 1
            wake_around(i0, w, h, mass, flag)   # the cell it left
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
        if moved or stay or vx * vx + vy * vy > eps2 or (not blocked and ax * ax + ay * ay > eps2):
            wake(i, mass, flag)
    return n


# --- gravity fields ----------------------------------------------------------------------------------

@njit(cache=True)
def field(w, h, wells, gx, gy, fx, fy, phi):
    """External acceleration and potential per cell: uniform gravity (gx, gy) plus softened point wells
    (rows of x, y, strength, softening): accel = strength * d / (|d|^2 + soft^2)^1.5."""
    for y in range(h):
        for x in range(w):
            ax, ay = gx, gy
            p = -(gx * x + gy * y)
            for k in range(wells.shape[0]):
                dx, dy = wells[k, 0] - x, wells[k, 1] - y
                inv_r = 1.0 / np.sqrt(dx * dx + dy * dy + wells[k, 3] * wells[k, 3])
                f = wells[k, 2] * inv_r * inv_r * inv_r
                ax += dx * f
                ay += dy * f
                p -= wells[k, 2] * inv_r
            i = y * w + x
            fx[i] = ax
            fy[i] = ay
            phi[i] = p


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
