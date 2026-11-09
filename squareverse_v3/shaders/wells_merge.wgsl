// Two super wells closer than wells_a.x pc and bound to each other become one, one thread for all pairs (at most
// MAX_WELLS wells, in list order, so the same every run): mass and momentum kept, the heavier one's place, and its
// last acceleration the mass-weighted mean of the two (else its next half kick would still carry the partner's pull:
// momentum drifted 3.6% in the test). Below the resolution, the last hardening and the gravitational-wave inspiral
// (Peters 1964) are taken as instant.

@group(0) @binding(0) var<uniform> c: Common;
@group(0) @binding(1) var<storage, read> pos: array<vec4<u32>>;
@group(0) @binding(2) var<storage, read_write> kin: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read_write> body: array<vec2<u32>>;
@group(0) @binding(4) var<storage, read_write> acc: array<vec4<f32>>;
@group(0) @binding(5) var<storage, read_write> wsink: array<atomic<u32>>;

const MAX_WELLS: u32 = 256u;

fn well_count() -> u32 {
    return min(atomicLoad(&wsink[0]), MAX_WELLS);
}

@compute @workgroup_size(1)
fn merge() {
    let count = well_count();
    for (var a = 0u; a < count; a++) {
        let ia = atomicLoad(&wsink[1u + a]);
        for (var b = a + 1u; b < count; b++) {
            let ib = atomicLoad(&wsink[1u + b]);
            let ba = body[ia];
            let bb = body[ib];
            if (kind_of(ba) != K_WELL || kind_of(bb) != K_WELL) {
                continue;
            }
            let ma = bitcast<f32>(ba.x);
            let mb = bitcast<f32>(bb.x);
            let d = length(fx_delta2(pos[ib], pos[ia]) * c.unit_pc);
            let dv = kin[ib].xy - kin[ia].xy;
            if (d >= c.wells_a.x || 0.5 * dot(dv, dv) >= c.g * (ma + mb) / max(d, 1e-3)) {
                continue;
            }
            // the heavier keeps its place
            var keep = ia;
            var lose = ib;
            if (mb > ma) {
                keep = ib;
                lose = ia;
            }
            let mk = bitcast<f32>(body[keep].x);
            let ml = bitcast<f32>(body[lose].x);
            let v = (mk * kin[keep].xy + ml * kin[lose].xy) / (mk + ml);
            body[keep] = vec2<u32>(bitcast<u32>(mk + ml), body[keep].y);
            let ak = acc[keep];
            acc[keep] = vec4<f32>((mk * ak.xy + ml * acc[lose].xy) / (mk + ml), ak.zw);
            acc[lose] = vec4<f32>(0.0);
            kin[keep] = vec4<f32>(v, kin[keep].zw);
            body[lose] = vec2<u32>(0u, (K_GONE << KIND_SHIFT) | (body[lose].y & ID_MASK));
            kin[lose] = vec4<f32>(0.0, 0.0, 3000.0, 0.0);
        }
    }
}
