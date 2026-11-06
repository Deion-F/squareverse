// Gravity on each particle: walk the tree from the root; a node far enough away (beyond its opening radius) acts
// as a softened point mass at its centre of mass plus its quadrupole, a nearer one is opened; particles act one
// by one. Plus the
// central point mass. Writes (ax, ay, phi_self, phi_central) per particle; phi_self counts each pair once per
// side, so the self-gravity energy is half its mass-weighted sum.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read> body: array<vec2<u32>>;
@group(0) @binding(3) var<storage, read> child: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read> node: array<vec4<u32>>;   // NODE_WORDS / 4 = 4 vec4s a node
@group(0) @binding(5) var<storage, read_write> acc: array<vec4<f32>>;

const STACK: u32 = 96u;

@compute @workgroup_size(128)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = flat_index(gid, c.row);
    if (i >= c.n) {
        return;
    }
    let q = pos[i];
    var a = vec2<f32>(0.0);
    var phi = 0.0;
    var stack: array<u32, STACK>;
    var sp = 0u;
    if (c.n > 1u) {
        stack[0] = 0u;
        sp = 1u;
    }
    while (sp > 0u) {
        sp -= 1u;
        let r = stack[sp];
        var m: f32;
        var d: vec2<f32>;
        if ((r & LEAF) != 0u) {
            let j = r & ~LEAF;
            if (j == i) {
                continue;
            }
            m = bitcast<f32>(body[j].x);
            d = fx_delta2(pos[j], q) * c.unit_pc;
        } else {
            let extra = node[4u * r + 2u];  // (mass, opening radius^2, sxx, sxy)
            d = fx_delta2(node[4u * r], q) * c.unit_pc;
            let far = dot(d, d) > bitcast<f32>(extra.y);
            if (!far && sp + 2u <= STACK) {
                let ch = child[r];
                stack[sp] = ch.x;
                stack[sp + 1u] = ch.y;
                sp += 2u;
                continue;
            }
            m = bitcast<f32>(extra.x);
            // the quadrupole (planar masses, 3D force law): with d from the particle to the centre of mass,
            // A = d.S.d, T = tr S: a += G/2 (-6 S d / R^5 + 15 A d / R^7 - 3 T d / R^5), phi -= G/2 (3A - T R^2) / R^5
            let sxx = bitcast<f32>(extra.z);
            let sxy = bitcast<f32>(extra.w);
            let syy = bitcast<f32>(node[4u * r + 3u].x);
            let r2 = dot(d, d) + c.eps2;
            let ir = inverseSqrt(r2);
            let ir2 = ir * ir;
            let ir5 = ir2 * ir2 * ir;
            let sd = vec2<f32>(sxx * d.x + sxy * d.y, sxy * d.x + syy * d.y);
            let aa = dot(d, sd);
            let tr = sxx + syy;
            a += (0.5 * c.g * ir5) * (-6.0 * sd + (15.0 * aa * ir2 - 3.0 * tr) * d);
            phi -= 0.5 * c.g * ir5 * (3.0 * aa - tr * r2);
        }
        let s2 = dot(d, d) + c.eps2;
        let inv = inverseSqrt(s2);
        let gm = c.g * m * inv;
        a += d * (gm * inv * inv);
        phi -= gm;
    }
    // the central mass
    let dc = fx_delta2(c.center, q) * c.unit_pc;
    let s2c = dot(dc, dc) + c.eps2_c;
    let invc = inverseSqrt(s2c);
    a += dc * (c.gm_c * invc * invc * invc);
    acc[i] = vec4<f32>(a, phi, -c.gm_c * invc);
}
