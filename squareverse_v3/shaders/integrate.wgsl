// Kick-drift-kick leapfrog with block time steps, split around the force pass. Each sub-step: `kick_drift` (the
// opening half kick for particles whose step begins now, then every particle drifts one sub-step), the tree is
// refitted or rebuilt and forces found for the particles whose step ends now, then `kick` (their closing half
// kick, and each picks its next bin). A particle's step is dt / 2^bin; it wants at most sqrt(2 eta eps / |a|)
// (GADGET's criterion), and at most eta_jerk |a| / |da/dt|, da/dt from the change in a over its last step: the
// galaxy's pull dominates |a|, so only the change sees a close encounter coming. It may move to a shorter step at the end of any step, to a longer one only where that
// step's boundaries line up with now. `counts` keeps how many particles each bin holds.
//
// Gas also gets its hydro push (hydro.wgsl), its internal energy u kicked by du/dt the same way, and, at the end of
// each of its steps, cooling and heating over the step, solved implicitly (`cool`), with a temperature floor and a
// Jeans floor (the 2D Jeans length c_s² / (G Σ) kept above 2 H, so clumps the kernel can't resolve don't form). Its
// step also stays under a Courant limit, gas_a.z H / (signal speed).

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read_write> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read> acc: array<vec4<f32>>;   // (ax, ay, phi_self, phi_central)
@group(0) @binding(4) var<storage, read_write> bins: array<vec4<u32>>;   // (bin, ax, ay at the last step's end, -)
@group(0) @binding(5) var<storage, read_write> counts: array<atomic<u32>>;
@group(0) @binding(6) var<uniform> t: Tick;
@group(0) @binding(7) var<storage, read_write> gas: array<vec4<f32>>;   // (u, Σ, H, -), (ax, ay, du/dt, vsig)
@group(0) @binding(8) var<storage, read> chem: array<vec4<f32>>;        // mass fractions (He, C/N/O, Mg/Si, Fe)
@group(0) @binding(9) var<storage, read> body: array<vec2<u32>>;

const SOLAR_Z: f32 = 0.0133;

// cooling function above 10^4 K, log10 erg cm^3 / s, at log10 T = 4.0 4.2 4.5 5.0 5.4 5.7 6.0 6.5 7.0 7.5 8.0
// (collisional ionisation equilibrium, roughly Sutherland & Dopita 1993), solar and primordial
const LOG_T = array<f32, 11>(4.0, 4.2, 4.5, 5.0, 5.4, 5.7, 6.0, 6.5, 7.0, 7.5, 8.0);
const LAMBDA_SOLAR = array<f32, 11>(-25.6, -21.8, -21.6, -21.2, -21.2, -21.6, -21.7, -22.3, -22.6, -22.7, -22.6);
const LAMBDA_PRIM = array<f32, 11>(-25.7, -21.9, -22.1, -22.3, -22.8, -22.9, -22.9, -23.0, -23.0, -22.9, -22.7);
const GAMMA_HEAT: f32 = 2e-26;   // erg / s per hydrogen atom (photoelectric heating, Koyama & Inutsuka 2002)

// Λ(T, z), erg cm^3 / s; z = metallicity / solar. Below 10^4 K Koyama & Inutsuka (2002), its metal-line term
// scaled by z.
fn cooling_lambda(temp: f32, z: f32) -> f32 {
    if (temp < 1e4) {
        return GAMMA_HEAT * (1e7 * exp(-1.184e5 / (temp + 1000.0)) + z * 1.4e-2 * sqrt(temp) * exp(-92.0 / temp));
    }
    let lt = log(temp) / log(10.0);
    if (lt >= 8.0) {
        let top = pow(10.0, LAMBDA_PRIM[10]) + z * (pow(10.0, LAMBDA_SOLAR[10]) - pow(10.0, LAMBDA_PRIM[10]));
        return top * sqrt(temp / 1e8);
    }
    var k = 0u;
    for (var j = 0u; j < 10u; j++) {
        if (lt >= LOG_T[j]) {
            k = j;
        }
    }
    let f = (lt - LOG_T[k]) / (LOG_T[k + 1u] - LOG_T[k]);
    let ls = mix(LAMBDA_SOLAR[k], LAMBDA_SOLAR[k + 1u], f);
    let lp = mix(LAMBDA_PRIM[k], LAMBDA_PRIM[k + 1u], f);
    return pow(10.0, lp) + z * (pow(10.0, ls) - pow(10.0, lp));
}

// heating less cooling per mass, (pc/Myr)^2 / Myr, at density rho_cgs (g/cm^3)
// photoelectric heating per hydrogen atom: from dust, so in the universe (gas_e.z) it scales with the metallicity
fn heating(z: f32) -> f32 {
    return GAMMA_HEAT * select(1.0, min(z, 1.0), c.gas_e.z > 0.5);
}

fn net_heating(u: f32, rho_cgs: f32, n_h: f32, z: f32) -> f32 {
    let erg_g_s = (heating(z) * n_h - n_h * n_h * cooling_lambda(gas_temperature(u), z)) / rho_cgs;
    return erg_g_s * 3301.0;   // erg/g/s -> (pc/Myr)^2 / Myr
}

// u after dt of heating and cooling: u1 = u0 + dt rate(u1), by bisection in log u
fn cool(u0: f32, sigma: f32, z: f32, dt: f32, u_min: f32) -> f32 {
    let rho_cgs = gas_rho(max(sigma, 1e-6)) * 6.77e-23;
    let n_h = 0.71 * rho_cgs / 1.6726e-24;
    var lo = log(u_min);
    var hi = log(max(u0, u_min) + dt * 3301.0 * heating(z) * n_h / rho_cgs + 1e-6);
    if (exp(lo) - u0 - dt * net_heating(exp(lo), rho_cgs, n_h, z) >= 0.0) {
        return u_min;
    }
    for (var it = 0u; it < 32u; it++) {
        let mid = 0.5 * (lo + hi);
        let um = exp(mid);
        if (um - u0 - dt * net_heating(um, rho_cgs, n_h, z) > 0.0) {
            hi = mid;
        } else {
            lo = mid;
        }
    }
    return exp(0.5 * (lo + hi));
}

// the least u: the temperature floor, and the Jeans floor c_s² > 2 G Σ H
// and, after reionisation (UV background on, z below cosmo_q.z), 10^4 K for gas thinner than the self-shielding
// density gas_e.w (photoionisation heating keeps it there)
fn u_floor(g: vec4<f32>) -> f32 {
    let gm = c.gas_a.w * (c.gas_a.w - 1.0);
    var t_min = c.gas_c.x;
    if (c.cosmo_q.y > 0.5 && 1.0 / c.cosmo.x - 1.0 < c.cosmo_q.z && gas_rho(g.y) < c.gas_e.w) {
        t_min = max(t_min, 1e4);
    }
    return max(max(u_of_temperature(t_min), 2.0 * c.g * g.y * g.z / gm), eos_u(g.y));
}

// Expansion: peculiar velocities decay as 1/a (dv/dt = g - H v), and the gas cools adiabatically, the sheet's area
// growing as a² (du/dt = -2 (gamma - 1) H u). Factors over time h; 1 in a static box.
fn hubble_drag(h: f32) -> f32 {
    return exp(-c.cosmo.y * h);
}

fn adiabatic(h: f32) -> f32 {
    return exp(-2.0 * (c.gas_a.w - 1.0) * c.cosmo.y * h);
}

// The share of its hydro push and heating a gas particle takes over a step of bin b: all of it, unless its Courant
// step is shorter than the shortest step there is (dense gas held up by its Jeans floor, or next to gas heated far
// above it): then as much as that step can follow, so the explicit update stays stable (the unresolved gas reacts
// slower instead of blowing up; it ran away in the universe at z ~ 2, 2026-11-08).
fn hydro_share(g: vec4<f32>, gh: vec4<f32>, b: u32) -> f32 {
    let want = c.gas_a.z * g.z / max(gh.w, 1e-3);
    return min(1.0, want / bin_dt(b));
}

fn is_gas(i: u32) -> bool {
    return kind_of(body[i]) == K_GAS;
}

fn bin_dt(b: u32) -> f32 {
    return c.dt / f32(1u << b);
}

// the lowest bin whose step is no longer than `want` Myr
fn bin_for(want: f32) -> u32 {
    let ratio = c.dt / want;
    if (!(ratio > 1.0)) {
        return 0u;
    }
    return u32(min(ceil(log2(ratio)), f32(c.levels - 1u)));
}

// the bin the acceleration asks for
fn wanted_bin(a: vec2<f32>) -> u32 {
    return bin_for(sqrt(c.eta_eps / max(length(a), 1e-30)));
}

@compute @workgroup_size(256)
fn kick_drift(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let k = kin[i];
    var v = k.xy;
    let b = bins[i].x;
    if (bin_starts(c.levels, b, t.s) && kind_of(body[i]) != K_GONE) {
        let h = 0.5 * bin_dt(b);
        v *= hubble_drag(h);
        if (is_gas(i)) {
            let g = gas[2u * i];
            let gh = gas[2u * i + 1u];
            let f = hydro_share(g, gh, b);
            v += (acc[i].xy + gh.xy * f) * h;
            gas[2u * i] = vec4<f32>(max(g.x * adiabatic(h) + gh.z * f * h, u_floor(g)), g.yzw);
        } else {
            v += acc[i].xy * h;
        }
        kin[i] = vec4<f32>(v, k.zw);
    }
    pos[i] = fx_add2(pos[i], v * (c.dt_min * c.inv_unit_pc));
}

@compute @workgroup_size(256)
fn kick(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let st = bins[i];
    let b = st.x;
    if (!bin_ends(c.levels, b, t.s) || kind_of(body[i]) == K_GONE) {
        return;
    }
    var a = acc[i].xy;
    let k = kin[i];
    var kz = k.zw;
    let gas_here = is_gas(i);
    var courant = 0u;
    if (gas_here) {
        let g = gas[2u * i];
        let gh = gas[2u * i + 1u];
        let f = hydro_share(g, gh, b);
        a += gh.xy * f;
        let floor_u = u_floor(g);
        var u = max(g.x * adiabatic(0.5 * bin_dt(b)) + gh.z * f * 0.5 * bin_dt(b), floor_u);
        if (c.gas_c.y > 0.5) {
            let ch = chem[i];
            u = cool(u, g.y, (ch.y + ch.z + ch.w) / SOLAR_Z, bin_dt(b), floor_u);
        }
        gas[2u * i] = vec4<f32>(u, g.yzw);
        kz = vec2<f32>(gas_temperature(u), g.y);   // drawn by temperature and surface density
        courant = bin_for(c.gas_a.z * g.z / max(gh.w, 1e-3));
    }
    kin[i] = vec4<f32>(k.xy * hubble_drag(0.5 * bin_dt(b)) + a * (0.5 * bin_dt(b)), kz);
    var want = max(wanted_bin(a), courant);
    let da = length(a - bitcast<vec2<f32>>(st.yz));
    if (c.eta_jerk > 0.0 && da > 0.0) {
        want = max(want, bin_for(c.eta_jerk * bin_dt(b) * length(a) / da));
    }
    var nb = want;
    if (want < b) {
        // longer steps only as far as their boundaries line up with the end of this sub-step
        let te = t.s + 1u;
        nb = b;
        loop {
            if (nb <= want || (te & (bin_period(c.levels, nb - 1u) - 1u)) != 0u) {
                break;
            }
            nb -= 1u;
        }
    }
    bins[i] = vec4<u32>(nb, bitcast<vec2<u32>>(a), 0u);
    if (nb != b) {
        atomicSub(&counts[b], 1u);
        atomicAdd(&counts[nb], 1u);
    }
}

// the first bins, from the first forces (counts must start at zero)
@compute @workgroup_size(256)
fn init_bins(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    var a = acc[i].xy;
    var b = 0u;
    if (kind_of(body[i]) == K_GONE) {
        // spare slots and the like: the longest step, so they don't count as work in the short ones
        bins[i] = vec4<u32>(0u, 0u, 0u, 0u);
        atomicAdd(&counts[0], 1u);
        return;
    }
    if (is_gas(i)) {
        let g = gas[2u * i];
        let gh = gas[2u * i + 1u];
        a += gh.xy;
        b = bin_for(c.gas_a.z * g.z / max(gh.w, 1e-3));
    }
    b = max(b, wanted_bin(a));
    bins[i] = vec4<u32>(b, bitcast<vec2<u32>>(a), 0u);
    atomicAdd(&counts[b], 1u);
}
