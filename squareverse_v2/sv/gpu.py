"""Optional GPU acceleration through wgpu (WebGPU), which runs on whatever the machine has: Vulkan, Metal, Direct3D 12
or OpenGL, on any vendor's GPU.

Only work that is the same for every cell or ghost lives here: the wells' field (kernels.field) and moving the ghosts
(kernels.step_ghosts). The particles' own tick stays on the CPU: each particle's move depends on the ones before it.
These are float32 ports of those kernels, so results match them to float32 precision, not bit for bit.

Whether the GPU is actually faster depends on the machine: copying data to and from an integrated GPU (or through a
translation layer, as under WSL) can cost more than it saves. So the World times both ways and keeps the faster (see
Chooser) unless told to always use the GPU.
"""

import os
import time
import warnings

import numpy as np

# adapters that are really the CPU emulating a GPU: never worth it
SOFTWARE = ("llvmpipe", "lavapipe", "softpipe", "swiftshader", "basic render", "warp")
KIND_RANK = {"DiscreteGPU": 3, "IntegratedGPU": 2, "VirtualGPU": 1, "Unknown": 1}
BACKEND_RANK = {"Vulkan": 2, "Metal": 2, "D3D12": 2, "OpenGL": 1}
WG = 256                                         # threads per workgroup
MAX_GROUPS = 65535                               # per dispatch dimension (the WebGPU minimum)


def _prepare_wsl():
    """Under WSL the GPU is only reachable through Mesa's D3D12 driver (OpenGL), which Mesa doesn't pick by itself.
    With an NVIDIA GPU present (its CUDA library is passed through), prefer it over an integrated one."""
    if not os.path.exists("/dev/dxg"):
        return
    os.environ.setdefault("GALLIUM_DRIVER", "d3d12")
    os.environ.setdefault("EGL_LOG_LEVEL", "fatal")      # Mesa warns about /dev/dri, which WSL doesn't use
    if os.path.exists("/usr/lib/wsl/lib/libcuda.so"):
        os.environ.setdefault("MESA_D3D12_DEFAULT_ADAPTER_NAME", "NVIDIA")


def open_device(name=None):
    """Open the best GPU there is: discrete before integrated, native APIs before OpenGL, never a software one. name:
    only an adapter whose name contains it (any case). Returns (Gpu, None), or (None, why not)."""
    _prepare_wsl()
    try:
        import wgpu
    except ImportError:
        return None, "wgpu isn't installed (pip install wgpu)"
    try:
        adapters = wgpu.gpu.enumerate_adapters_sync()
    except Exception as e:                       # no driver at all
        return None, f"no GPU driver ({e})"
    best, best_rank = None, None
    for a in adapters:
        info = a.info
        label = info["device"].lower()
        if info["adapter_type"] == "CPU" or any(s in label for s in SOFTWARE):
            continue
        if name and name.lower() not in label:
            continue
        rank = (KIND_RANK.get(info["adapter_type"], 0), BACKEND_RANK.get(info["backend_type"], 0))
        if best is None or rank > best_rank:
            best, best_rank = a, rank
    if best is None:
        return None, f"no GPU named {name!r}" if name else "no hardware GPU found"
    try:
        return Gpu(best), None
    except Exception as e:
        return None, f"{best.info['device']} failed to start ({e})"


# --- shaders -----------------------------------------------------------------------------------------
# Ports of the numba helpers they are named after (kernels._axis, fade, _pull, _lerp_axis, whirl, orbit_accel,
# _star_pull), in float32. A dispatch can be wider than MAX_GROUPS workgroups, so the index folds in id.y.

def _fade_constants():
    """kernels.fade's constants, for the shaders' port of it."""
    from . import kernels as k
    return "".join(f"const {name}: f32 = {value!r};\n" for name, value in
                   (("TAPER", k.REACH_TAPER), ("TL", k._TL), ("A0", k._A0), ("A1", k._A1), ("A2", k._A2),
                    ("A3", k._A3), ("H_END", float(k._H_END)), ("H_IN", float(k._H_IN))))


COMMON = _fade_constants() + """
fn pmod(a: f32, n: f32) -> f32 { return a - n * floor(a / n); }
fn pmodi(a: i32, n: i32) -> i32 {             // a mod n for a in [-n, 2n): % of a negative is unreliable in GLSL
    if (a < 0) { return a + n; }
    if (a >= n) { return a - n; }
    return a;
}
fn axis(v: f32, c: f32, n: f32, min_image: bool) -> f32 {
    var d = v - c;
    if (min_image) { d -= n * floor(d / n + 0.5); }
    return d;
}
fn taper_h(u: f32) -> f32 {
    return -A0 / u + A1 * log(u) + A2 * u + 0.5 * A3 * u * u;
}
fn fade(rho: f32, kinv: f32) -> vec2<f32> {
    let u = rho * kinv;
    if (u <= 1.0) { return vec2<f32>(1.0, 1.0 - u + u * H_IN); }
    if (u >= TAPER) { return vec2<f32>(0.0); }
    let t = (u - 1.0) / TL;
    return vec2<f32>(1.0 - t * t * (3.0 - 2.0 * t), u * (H_END - taper_h(u)));
}
fn pull(dx: f32, dy: f32, strength: f32, soft: f32, kinv: f32) -> vec3<f32> {
    let rho = sqrt(dx * dx + dy * dy + soft * soft);
    let ff = fade(rho, kinv);
    let inv_r = 1.0 / rho;
    let f = strength * inv_r * inv_r * inv_r * ff.x;
    return vec3<f32>(dx * f, dy * f, -strength * inv_r * ff.y);
}
struct Lerp { b0: i32, b1: i32, t: f32, c0: f32, c1: f32 }
fn lerp_axis(v: f32, block: f32, nb: i32, wrap: bool) -> Lerp {
    let u = (v - (block - 1.0) * 0.5) / block;
    var b0 = i32(floor(u));
    var t = u - f32(b0);
    if (wrap) {
        let c0 = f32(b0) * block + (block - 1.0) * 0.5;
        return Lerp(pmodi(b0, nb), pmodi(b0 + 1, nb), t, c0, c0 + block);
    }
    if (b0 < 0) { b0 = 0; t = 0.0; }
    if (b0 >= nb - 1) { b0 = nb - 1; t = 0.0; }
    let b1 = min(b0 + 1, nb - 1);
    return Lerp(b0, b1, t, f32(b0) * block + (block - 1.0) * 0.5, f32(b1) * block + (block - 1.0) * 0.5);
}
fn index(id: vec3<u32>) -> u32 { return id.x + id.y * (65535u * 256u); }
"""

# fp: w, h, block, cw, ch, wells, gx, gy, wrap, kinv. wells: rows of x, y, strength, softening, near radius.
FIELD = COMMON + """
@group(0) @binding(0) var<storage, read> fp: array<f32>;
@group(0) @binding(1) var<storage, read> wells: array<f32>;
@group(0) @binding(2) var<storage, read_write> coarse: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read_write> fx: array<f32>;
@group(0) @binding(4) var<storage, read_write> fy: array<f32>;
@group(0) @binding(5) var<storage, read_write> phi: array<f32>;

@compute @workgroup_size(256)
fn blocks(@builtin(global_invocation_id) id: vec3<u32>) {
    let w = fp[0]; let h = fp[1]; let block = fp[2]; let cw = i32(fp[3]); let ch = i32(fp[4]);
    let b = i32(index(id));
    if (b >= cw * ch) { return; }
    let wrap = fp[8] != 0.0; let kinv = fp[9];
    let cx = f32(b % cw) * block + (block - 1.0) * 0.5;
    let cy = f32(b / cw) * block + (block - 1.0) * 0.5;
    var s = vec3<f32>(0.0);
    for (var k = 0; k < i32(fp[5]); k++) {
        let o = k * 5;
        s += pull(-axis(cx, wells[o], w, wrap), -axis(cy, wells[o + 1], h, wrap), wells[o + 2], wells[o + 3], kinv);
    }
    coarse[b] = vec4<f32>(s, 0.0);
}

@compute @workgroup_size(256)
fn cells(@builtin(global_invocation_id) id: vec3<u32>) {
    let w = fp[0]; let h = fp[1]; let block = fp[2]; let cw = i32(fp[3]); let ch = i32(fp[4]);
    let iw = i32(w);
    let i = i32(index(id));
    if (i >= iw * i32(h)) { return; }
    let wrap = fp[8] != 0.0; let kinv = fp[9]; let gx = fp[6]; let gy = fp[7];
    let x = f32(i % iw); let y = f32(i / iw);
    let ly = lerp_axis(y, block, ch, wrap);
    let lx = lerp_axis(x, block, cw, wrap);
    let tx = lx.t; let ty = ly.t;
    var v = (1.0 - tx) * (1.0 - ty) * coarse[ly.b0 * cw + lx.b0].xyz + tx * (1.0 - ty) * coarse[ly.b0 * cw + lx.b1].xyz
          + (1.0 - tx) * ty * coarse[ly.b1 * cw + lx.b0].xyz + tx * ty * coarse[ly.b1 * cw + lx.b1].xyz;
    v += vec3<f32>(gx, gy, -(gx * x + gy * y));
    // within near of a well its exact pull replaces what the blend gave it (kernels.field's last pass)
    for (var k = 0; k < i32(fp[5]); k++) {
        let o = k * 5;
        let wx = wells[o]; let wy = wells[o + 1]; let strength = wells[o + 2]; let soft = wells[o + 3];
        let r = wells[o + 4];
        let ddx = axis(x, wx, w, wrap); let ddy = axis(y, wy, h, wrap);
        if (ddx * ddx + ddy * ddy > r * r) { continue; }
        v += pull(-ddx, -ddy, strength, soft, kinv);
        let dy0 = -axis(ly.c0, wy, h, wrap); let dy1 = -axis(ly.c1, wy, h, wrap);
        let dx0 = -axis(lx.c0, wx, w, wrap); let dx1 = -axis(lx.c1, wx, w, wrap);
        v -= (1.0 - tx) * (1.0 - ty) * pull(dx0, dy0, strength, soft, kinv)
           + tx * (1.0 - ty) * pull(dx1, dy0, strength, soft, kinv)
           + (1.0 - tx) * ty * pull(dx0, dy1, strength, soft, kinv) + tx * ty * pull(dx1, dy1, strength, soft, kinv);
    }
    fx[i] = v.x; fy[i] = v.y; phi[i] = v.z;
}
"""

# gp: see Gpu.step_ghosts. aux: the self-gravity mesh (x then y), the stars' block field (x then y), the whirlpools
# (rows of 16: World.whirls) and the stars (rows of 5), at the offsets gp gives.
GHOSTS = COMMON + """
@group(0) @binding(0) var<storage, read> gp: array<f32>;
@group(0) @binding(1) var<storage, read> aux: array<f32>;
@group(0) @binding(2) var<storage, read> fx: array<f32>;
@group(0) @binding(3) var<storage, read> fy: array<f32>;
@group(0) @binding(4) var<storage, read> hole: array<i32>;
@group(0) @binding(5) var<storage, read_write> ghosts: array<vec4<f32>>;
@group(0) @binding(6) var<storage, read_write> state: array<i32>;

fn ghost_cell(x: f32, y: f32, w: i32, h: i32) -> i32 {
    return clamp(i32(floor(y + 0.5)), 0, h - 1) * w + clamp(i32(floor(x + 0.5)), 0, w - 1);
}

fn orbit_accel(rx: f32, ry: f32, vx: f32, vy: f32, om: f32, grip: f32, vmin: f32) -> vec2<f32> {
    let r2 = rx * rx + ry * ry;
    if (r2 < 0.25) { return vec2<f32>(0.0); }
    let r = sqrt(r2);
    let way = select(-1.0, 1.0, om > 0.0);
    let tx = -ry / r * way; let ty = rx / r * way;
    let target_ = sqrt(om * om * r2 + vmin * vmin);
    let vt = max(vx * tx + vy * ty, 0.0);
    let c = vt * vt / r;
    return vec2<f32>(-c * rx / r + grip * (target_ * tx - vx), -c * ry / r + grip * (target_ * ty - vy));
}

fn orbit_flow(rx: f32, ry: f32, om: f32, vmin: f32) -> vec2<f32> {
    let r2 = rx * rx + ry * ry;
    if (r2 < 0.25) { return vec2<f32>(0.0); }
    let k = sqrt(om * om * r2 + vmin * vmin) / sqrt(r2) * select(-1.0, 1.0, om > 0.0);
    return vec2<f32>(-ry * k, rx * k);
}

fn whirl(rx: f32, ry: f32, vx: f32, vy: f32, o: i32, kinv: f32, phi: f32) -> vec2<f32> {
    let reach = aux[o + 2]; let spin = aux[o + 3]; let strength = aux[o + 4]; let soft = aux[o + 5];
    let d2 = rx * rx + ry * ry;
    if (d2 >= reach * reach || d2 < 1e-6) { return vec2<f32>(0.0); }
    let d = sqrt(d2);
    let rim = min(1.0, (1.0 - d / reach) / max(gp[15], 1e-9));
    let s2 = d2 + soft * soft;
    let orbital = sqrt(strength * d2 / (s2 * sqrt(s2)) * fade(sqrt(s2), kinv).x);
    let fling = select(1.0, max(1.0, abs(spin)), d < aux[o + 8]);   // it only flings within its point of no return
    let target_ = min(abs(spin) * gp[12], gp[14] * orbital * fling) * rim * select(-1.0, 1.0, spin >= 0.0);
    let tx = -ry / d; let ty = rx / d;
    let vt = vx * tx + vy * ty;
    var a = gp[13] * rim * (target_ - vt);
    let nvt = vt + a;
    if (nvt * nvt > vt * vt) {                   // speeding it up: never so far it could get away (kernels.whirl)
        let room = -2.0 * (phi + gp[33]) - (vx * vx + vy * vy - vt * vt);
        if (room <= vt * vt) { a = 0.0; }
        else if (nvt * nvt > room) { a = sqrt(room) * select(-1.0, 1.0, nvt >= 0.0) - vt; }
    }
    return vec2<f32>(a * tx, a * ty);
}

// kernels.frame_turn: how fast a super well turns space round here (rad/tick)
fn frame_turn(rx: f32, ry: f32, o: i32, kinv: f32, vmax: f32) -> f32 {
    let share = aux[o + 6]; let reach = aux[o + 7]; let strength = aux[o + 4]; let soft = aux[o + 5];
    let d2 = rx * rx + ry * ry;
    if (share == 0.0 || d2 >= reach * reach) { return 0.0; }
    let s2 = d2 + soft * soft;
    let rho = sqrt(s2);
    let d = sqrt(d2);
    let band = aux[o + 2] * gp[15];             // the whirlpool takes over within its range
    let om = share * sqrt(strength / (s2 * rho) * fade(rho, kinv).x)
             * min(1.0, (1.0 - d / reach) / max(gp[31], 1e-9))
             * clamp((d - aux[o + 2] + band) / max(band, 1e-9), 0.0, 1.0);
    let cap = select(vmax / d, gp[32], d * gp[32] <= vmax);
    return clamp(om, -cap, cap);
}

fn star_pull(x: f32, y: f32, w: f32, h: f32, wrap: bool, kinv: f32) -> vec2<f32> {
    let block = gp[21]; let cw = i32(gp[22]); let ch = i32(gp[23]);
    let sfx = i32(gp[26]); let sfy = sfx + cw * ch;
    let lx = lerp_axis(x, block, cw, wrap); let ly = lerp_axis(y, block, ch, wrap);
    let tx = lx.t; let ty = ly.t;
    let wa = (1.0 - tx) * (1.0 - ty); let wb = tx * (1.0 - ty); let wc = (1.0 - tx) * ty; let wd = tx * ty;
    let a = ly.b0 * cw + lx.b0; let b = ly.b0 * cw + lx.b1; let c = ly.b1 * cw + lx.b0; let d = ly.b1 * cw + lx.b1;
    var acc = vec2<f32>(wa * aux[sfx + a] + wb * aux[sfx + b] + wc * aux[sfx + c] + wd * aux[sfx + d],
                        wa * aux[sfy + a] + wb * aux[sfy + b] + wc * aux[sfy + c] + wd * aux[sfy + d]);
    for (var k = 0; k < i32(gp[20]); k++) {
        let o = i32(gp[28]) + k * 5;
        let dx = axis(aux[o], x, w, wrap); let dy = axis(aux[o + 1], y, h, wrap);
        if (dx * dx + dy * dy > aux[o + 4]) { continue; }
        let s = aux[o + 2]; let s2 = aux[o + 3];
        var rho = sqrt(dx * dx + dy * dy + s2);
        var f = s / (rho * rho * rho) * fade(rho, kinv).x;
        acc += vec2<f32>(dx, dy) * f;
        for (var j = 0; j < 4; j++) {
            let cy = select(ly.c0, ly.c1, j >= 2); let wy_ = select(1.0 - ty, ty, j >= 2);
            let cx = select(lx.c0, lx.c1, (j & 1) == 1); let wx_ = select(1.0 - tx, tx, (j & 1) == 1);
            let ex = axis(aux[o], cx, w, wrap); let ey = axis(aux[o + 1], cy, h, wrap);
            rho = sqrt(ex * ex + ey * ey + s2);
            f = s / (rho * rho * rho) * fade(rho, kinv).x * wx_ * wy_;
            acc -= vec2<f32>(ex, ey) * f;
        }
    }
    return acc;
}

@compute @workgroup_size(256)
fn step(@builtin(global_invocation_id) id: vec3<u32>) {
    let k = i32(index(id));
    if (k >= i32(gp[24])) { return; }
    let m = state[k];
    state[k] = 0;                                // becomes the hole number of a core it crosses
    if (m == 0) { return; }
    let w = gp[0]; let h = gp[1]; let iw = i32(w); let ih = i32(h);
    let vmax = gp[2]; let drag = gp[3]; let wall_e = gp[4]; let wrap = gp[5] != 0.0; let kinv = gp[16];
    var g = ghosts[k];
    let i = ghost_cell(g.x, g.y, iw, ih);
    var a = vec2<f32>(fx[i], fy[i]);
    if (gp[6] != 0.0) {                          // kernels.sg_block_at: read where the matter was when binned
        var sx = f32(i % iw); var sy = f32(i / iw);
        if (gp[30] != 0.0) {
            let rx = sx - gp[10]; let ry = sy - gp[11];
            sx = gp[10] + gp[29] * rx + gp[30] * ry;
            sy = gp[11] - gp[30] * rx + gp[29] * ry;
            if (wrap) { sx = pmod(sx, w); sy = pmod(sy, h); }
        }
        let blk = i32(gp[17]); let sw = i32(gp[18]);
        let b = (clamp(i32(sy), 0, ih - 1) / blk) * sw + clamp(i32(sx), 0, iw - 1) / blk;
        a += vec2<f32>(aux[b], aux[i32(gp[25]) + b]);
    }
    var turn = 0.0; var carry = vec2<f32>(0.0);
    var host = -1; var e_host = 0.0; var phi_host = 0.0;   // the super well it is most tightly bound to (orbit_push)
    var fl = vec2<f32>(0.0);
    if (gp[7] != 0.0) { fl = orbit_flow(g.x - gp[10], g.y - gp[11], gp[7], gp[9]); }
    for (var j = 0; j < i32(gp[19]); j++) {      // each super well's exact pull and whirlpool, and the space it turns
        let o = i32(gp[27]) + j * 16;
        let rx = axis(g.x, aux[o], w, wrap); let ry = axis(g.y, aux[o + 1], h, wrap);
        let p = pull(-rx, -ry, aux[o + 4], aux[o + 5], kinv);
        let dvx = g.z - aux[o + 9]; let dvy = g.w - aux[o + 10];
        var e = 0.5 * (dvx * dvx + dvy * dvy) + p.z;
        if (gp[7] != 0.0) {                      // kernels.orbit_shear
            let df = fl - vec2<f32>(aux[o + 14], aux[o + 15]);
            e += 0.5 * dot(df, df);
        }
        if (e < e_host) { host = o; e_host = e; phi_host = p.z; }
        a += p.xy + whirl(rx, ry, g.z, g.w, o, kinv, p.z);
        let om = frame_turn(rx, ry, o, kinv, vmax);
        if (om != 0.0) {
            let c = cos(om); let s = sin(om);
            carry += vec2<f32>(c * rx - s * ry - rx, s * rx + c * ry - ry);
            turn += om;
        }
    }
    if (gp[7] != 0.0) {                          // kernels.orbit_push: bound to a super well, it gets that well's push
        var share = 0.0;                         // kernels.bound_share
        if (host >= 0 && phi_host < 0.0) { share = 1.0; }
        var o_ = vec2<f32>(0.0);
        if (share < 1.0) { o_ = orbit_accel(g.x - gp[10], g.y - gp[11], g.z, g.w, gp[7], gp[8], gp[9]); }
        if (host >= 0) { o_ += share * (vec2<f32>(aux[host + 11], aux[host + 12]) - o_); }
        a += o_;
    }
    if (gp[20] > 0.0) {
        a += star_pull(g.x, g.y, w, h, wrap, kinv);
    }
    var vx = (g.z + a.x) * (1.0 - drag);
    var vy = (g.w + a.y) * (1.0 - drag);
    if (turn != 0.0) {                           // turning space turns which way it is heading too
        let tc = cos(turn); let ts = sin(turn);
        let tvx = tc * vx - ts * vy;
        vy = ts * vx + tc * vy;
        vx = tvx;
    }
    var v = sqrt(vx * vx + vy * vy);
    if (v > vmax) {
        vx *= vmax / v;
        vy *= vmax / v;
        v = vmax;
    }
    // move in steps of at most one cell, so a fast ghost can't jump over a small core - its own motion and space
    // carrying it
    let n = max(1, i32(ceil(length(vec2<f32>(vx, vy) + carry))));
    var x = g.x; var y = g.y;
    for (var s = 0; s < n; s++) {
        x = x + (vx + carry.x) / f32(n);
        y = y + (vy + carry.y) / f32(n);
        if (wrap) {
            x = pmod(x, w);
            y = pmod(y, h);
        } else {
            if (x < 0.0 || x > w - 1.0) { x = clamp(x, 0.0, w - 1.0); vx = -vx * wall_e; }
            if (y < 0.0 || y > h - 1.0) { y = clamp(y, 0.0, h - 1.0); vy = -vy * wall_e; }
        }
        let c = ghost_cell(x, y, iw, ih);
        if (hole[c] != 0) {
            state[k] = hole[c];
            break;
        }
    }
    ghosts[k] = vec4<f32>(x, y, vx, vy);
}
"""


class Gpu:
    """One GPU device with the field and ghost pipelines, and the buffers they use (kept between calls, regrown
    when too small). The wells' field is kept on the GPU after field(), so step_ghosts() needn't upload it again."""

    def __init__(self, adapter):
        import wgpu
        self.wgpu = wgpu
        info = adapter.info
        self.name, self.backend, self.kind = info["device"], info["backend_type"], info["adapter_type"]
        self.device = adapter.request_device_sync()
        field = self._layout(["read", "read", "rw", "rw", "rw", "rw"])
        ghosts = self._layout(["read"] * 5 + ["rw"] * 2)
        self.p_blocks = self._pipeline(FIELD, "blocks", field)
        self.p_cells = self._pipeline(FIELD, "cells", field)
        self.p_ghosts = self._pipeline(GHOSTS, "step", ghosts)
        self.bufs = {}
        self.field_key = None                    # which field the fx / fy buffers hold (see step_ghosts)
        self.hole_key = None

    def __str__(self):
        return f"{self.name} ({self.backend})"

    def _layout(self, access):
        """A bind group layout of storage buffers, read-only or read-write ("rw") in binding order: shared by all of a
        shader's entry points, whichever bindings each uses."""
        t = self.wgpu.BufferBindingType
        return self.device.create_bind_group_layout(entries=[
            {"binding": k, "visibility": self.wgpu.ShaderStage.COMPUTE,
             "buffer": {"type": t.storage if a == "rw" else t.read_only_storage}} for k, a in enumerate(access)])

    def _pipeline(self, code, entry, layout):
        module = self.device.create_shader_module(code=code)
        return self.device.create_compute_pipeline(
            layout=self.device.create_pipeline_layout(bind_group_layouts=[layout]),
            compute={"module": module, "entry_point": entry}), layout

    def _buf(self, name, nbytes):
        """A storage buffer of at least nbytes (and 16), regrown when too small."""
        nbytes = max(16, int(nbytes))
        b = self.bufs.get(name)
        if b is None or b.size < nbytes:
            u = self.wgpu.BufferUsage
            b = self.device.create_buffer(size=nbytes, usage=u.STORAGE | u.COPY_SRC | u.COPY_DST)
            self.bufs[name] = b
        return b

    def _upload(self, name, array):
        a = np.ascontiguousarray(array)
        b = self._buf(name, a.nbytes)
        if a.nbytes:
            self.device.queue.write_buffer(b, 0, a)
        return b

    def _read(self, name, out):
        """Copy buffer name back into the array out (its size)."""
        data = self.device.queue.read_buffer(self.bufs[name], 0, out.nbytes)
        out.reshape(-1)[:] = np.frombuffer(data, out.dtype)

    def _run(self, pipeline, buffers, n):
        pipeline, layout = pipeline
        bg = self.device.create_bind_group(layout=layout, entries=[
            {"binding": k, "resource": {"buffer": b, "offset": 0, "size": b.size}} for k, b in enumerate(buffers)])
        groups = -(-n // WG)
        enc = self.device.create_command_encoder()
        p = enc.begin_compute_pass()
        p.set_pipeline(pipeline)
        p.set_bind_group(0, bg)
        p.dispatch_workgroups(min(groups, MAX_GROUPS), -(-groups // MAX_GROUPS))
        p.end()
        self.device.queue.submit([enc.finish()])

    def field(self, w, h, block, wells, near, gx, gy, wrap, kinv, fx, fy, phi, key=None):
        """kernels.field on the GPU, into the float32 arrays fx, fy and phi. key: names this field for step_ghosts."""
        cw, ch = -(-w // block), -(-h // block)
        fp = self._upload("fp", np.array([w, h, block, cw, ch, len(wells), gx, gy, wrap, kinv], np.float32))
        rows = np.zeros((len(wells), 5), np.float32)
        if len(wells):
            rows[:, :4] = wells
            rows[:, 4] = near
        wb = self._upload("wells", rows)
        coarse = self._buf("coarse", cw * ch * 16)
        bx, by, bp = (self._buf(k, w * h * 4) for k in ("fx", "fy", "phi"))
        self._run(self.p_blocks, [fp, wb, coarse, bx, by, bp], cw * ch)
        self._run(self.p_cells, [fp, wb, coarse, bx, by, bp], w * h)
        self._read("fx", fx)
        self._read("fy", fy)
        self._read("phi", phi)
        self.field_key = key

    def step_ghosts(self, gx, gy, gvx, gvy, gm, gage, w, h, P, fx, fy, sgx, sgy, sg_block, sg_w, hole, absorbed,
                    whirls, stars, sfx, sfy, s_block, s_cw, s_ch, field_key=None, hole_key=None):
        """kernels.step_ghosts on the GPU (the same arguments). field_key / hole_key: what the World calls its current
        field and core map, so they are only uploaded when they have changed (None: always). Returns how many ghosts
        were swallowed."""
        from . import kernels as k
        n = gm.size
        if field_key is None or field_key != self.field_key:
            self._upload("fx", fx)
            self._upload("fy", fy)
            self.field_key = field_key
        if hole_key is None or hole_key != self.hole_key:
            self._upload("hole", hole.astype(np.int32))
            self.hole_key = hole_key
        nsg, nsf = sgx.size, sfx.size
        # (the shader doesn't add up the ghosts' pull back on the super wells, absorbed[:, 3:5], as the CPU does)
        aux = np.concatenate([sgx, sgy, sfx, sfy, whirls.ravel(), stars.ravel()]).astype(np.float32)
        gp = np.array([w, h, P[k.P_VMAX], P[k.P_DRAG], P[k.P_WALL_E], P[k.P_WRAP], P[k.P_SG_ON], P[k.P_ORBIT_W],
                       P[k.P_ORBIT_GRIP], P[k.P_ORBIT_VMIN], P[k.P_ORBIT_CX], P[k.P_ORBIT_CY], P[k.P_WHIRL_SPEED],
                       P[k.P_WHIRL_GRIP], P[k.P_WHIRL_INFALL], P[k.P_WHIRL_EDGE], P[k.P_REACH],
                       sg_block, sg_w, whirls.shape[0], stars.shape[0], s_block, s_cw, s_ch, n,
                       nsg, 2 * nsg, 2 * nsg + 2 * nsf, 2 * nsg + 2 * nsf + whirls.size, P[k.P_SG_COS],
                       P[k.P_SG_SIN], P[k.P_DRAG_EDGE], P[k.P_DRAG_TURN], k.WHIRL_BOUND], np.float32)
        state = np.empty((n, 4), np.float32)
        state[:, 0], state[:, 1], state[:, 2], state[:, 3] = gx, gy, gvx, gvy
        bufs = [self._upload("gp", gp), self._upload("aux", aux), self.bufs["fx"], self.bufs["fy"],
                self.bufs["hole"], self._upload("ghosts", state), self._upload("gstate", gm.astype(np.int32))]
        self._run(self.p_ghosts, bufs, n)
        self._read("ghosts", state)
        hit = np.empty(n, np.int32)
        self._read("gstate", hit)
        gx[:], gy[:], gvx[:], gvy[:] = state[:, 0], state[:, 1], state[:, 2], state[:, 3]
        gage[gm != 0] += 1
        return k._swallow_ghosts(gm, gvx, gvy, hit.astype(np.int16), absorbed)


class Chooser:
    """Times two (or more) ways of doing the same job and keeps using the faster. Each way is timed TRIALS times
    (after one call that only warms it up: compiling, making buffers), then the faster runs alone for RETRY calls,
    or until the job's size (size_of its arguments: how many wells, how many ghosts) has halved or doubled, and then
    all are timed again, since which way wins depends on the load. force: always use that way. A way that fails (a
    GPU driver giving up, say) is dropped with a warning and the job done another way; the ways must leave their
    arguments as they were when they fail."""
    TRIALS = 5
    RETRY = 900

    def __init__(self, ways, force=None, size_of=None):
        self.ways = ways                         # {name: callable}
        self.force = force
        self.size_of = size_of
        self.size = None                         # the job's size when the ways were last timed
        self.choice = force or next(iter(ways))
        self.ms = dict.fromkeys(ways)            # each way's latest time per call (ms; the median while trying)
        self.warm = set()
        self._try_all()

    def _try_all(self):
        self.plan = [] if self.force else [k for _ in range(self.TRIALS) for k in self.ways]
        self.times = {k: [] for k in self.ways}
        self.left = self.RETRY

    def __call__(self, *args):
        if self.size_of is not None and not self.force:
            size = self.size_of(*args) + 1
            if self.size is None or not self.size / 2 <= size <= self.size * 2:
                if self.size is not None and not self.plan:
                    self._try_all()
                self.size = size
        way = self.plan[0] if self.plan else self.choice
        t = time.perf_counter()
        try:
            r = self.ways[way](*args)
        except Exception as e:
            if len(self.ways) == 1:
                raise
            warnings.warn(f"{way} failed, not using it again: {e}")
            del self.ways[way]
            self.ms.pop(way, None)
            self.force = None
            self.choice = next(iter(self.ways))
            self._try_all()
            self.plan = []
            return self(*args)
        dt = (time.perf_counter() - t) * 1000
        if way not in self.warm:
            self.warm.add(way)
            return r
        self.ms[way] = dt
        if self.plan:
            self.plan.pop(0)
            self.times[way].append(dt)
            if not self.plan:
                self.ms = {k: float(np.median(v)) for k, v in self.times.items()}
                self.choice = min(self.ms, key=self.ms.get)
        elif not self.force:
            self.left -= 1
            if self.left <= 0:
                self._try_all()
        return r
