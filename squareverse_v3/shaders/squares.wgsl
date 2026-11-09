// Every particle is a square snapped to the pixel grid, added (additive blending) into an HDR target, so where
// many fall on one pixel they glow. Stars are coloured by their surface temperature. Prepended with fixed.wgsl.
//
// Level of detail (`lod`, 0 zoomed out on a galaxy or more, 1 at ~100x closer): stars' squares grow with their
// luminosity (spreading the same light), and remnants fade in: white dwarfs blue-white, neutron stars as faint
// violet points, stellar black holes as dark red ones.

struct View {
    center: vec4<u32>,   // the camera, fixed point
    unit_pc: f32,
    px_per_pc: f32,
    viewport: vec2<f32>, // pixels
    square_px: f32,
    brightness: f32,
    extrap_myr: f32,     // draw each particle this far along its velocity
    flags: u32,          // 1: draw the dark matter, 2: hide the gas
    lod: f32,
    _a: f32,
    _b: f32,
    _c: f32,
}

@group(0) @binding(0) var<uniform> view: View;

struct VOut {
    @builtin(position) clip: vec4<f32>,
    @location(0) color: vec3<f32>,
}

// Black-body colour (Tanner Helland's fit, 1,000 - 40,000 K), as linear RGB.
fn blackbody(t: f32) -> vec3<f32> {
    let x = clamp(t, 1000.0, 40000.0) / 100.0;
    var r = 255.0;
    var g: f32;
    var b = 255.0;
    if (x <= 66.0) {
        g = 99.4708025861 * log(x) - 161.1195681661;
        if (x <= 19.0) {
            b = 0.0;
        } else {
            b = 138.5177312231 * log(x - 10.0) - 305.0447927307;
        }
    } else {
        r = 329.698727446 * pow(x - 60.0, -0.1332047592);
        g = 288.1221695283 * pow(x - 60.0, -0.0755148492);
    }
    return pow(clamp(vec3<f32>(r, g, b) / 255.0, vec3<f32>(0.0), vec3<f32>(1.0)), vec3<f32>(2.2));
}

@vertex
fn vs(
    @builtin(vertex_index) vi: u32,
    @location(0) q: vec4<u32>,
    @location(1) star: vec2<f32>,  // (surface temperature K, luminosity Lsun)
    @location(2) vel: vec2<f32>,   // pc / Myr
    @location(3) body: vec2<u32>,  // (mass bits, kind << 28 | id)
) -> VOut {
    var corners = array<vec2<f32>, 6>(
        vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 0.0), vec2<f32>(0.0, 1.0),
        vec2<f32>(0.0, 1.0), vec2<f32>(1.0, 0.0), vec2<f32>(1.0, 1.0),
    );
    let d = (fx_delta2(q, view.center) * view.unit_pc + vel * view.extrap_myr) * view.px_per_pc;
    // world y points up, screen y down
    let base = floor(vec2<f32>(view.viewport.x * 0.5 + d.x, view.viewport.y * 0.5 - d.y));
    let kind = body.y >> 28u;
    var size = view.square_px;
    var color: vec3<f32>;
    if (kind == 1u) {
        // dark matter: unseen unless asked for
        color = vec3<f32>(0.35, 0.2, 0.6) * view.brightness * f32(view.flags & 1u);
    } else if (kind == 7u) {
        // gas by temperature (star.x) and surface density (star.y): cold neutral dim blue, ~10^4 K the pink of
        // hydrogen-alpha, hot (10^6 K and up) blue-white
        let lt = log(max(star.x, 10.0)) / log(10.0);
        let cold = vec3<f32>(0.12, 0.16, 0.4);
        let warm = vec3<f32>(1.0, 0.22, 0.4);
        let hot = vec3<f32>(0.45, 0.65, 1.0);
        var tint = mix(cold, warm, smoothstep(3.3, 4.0, lt));
        tint = mix(tint, hot, smoothstep(5.0, 6.5, lt));
        let glow = 0.25 * sqrt(clamp(star.y, 0.0, 400.0));
        color = tint * glow * view.brightness * f32((view.flags & 2u) == 0u);
    } else if (kind == 2u && bitcast<f32>(body.x) < 1000.0) {
        color = vec3<f32>(0.0);   // a stellar-mass well (a single star's black hole): not seen
    } else if (kind == 2u) {
        // a super well: a white marker, a few pixels across at any zoom
        size = max(3.0 * view.square_px, 5.0);
        color = vec3<f32>(3.0, 2.6, 2.2);
    } else if (kind == 6u) {
        color = vec3<f32>(0.0);   // swallowed
    } else if (kind == 4u || kind == 5u) {
        // a neutron star or a stellar black hole: only seen close up
        let tint = select(vec3<f32>(0.5, 0.06, 0.04), vec3<f32>(0.35, 0.3, 0.9), kind == 4u);
        color = tint * smoothstep(0.4, 0.9, view.lod) * view.brightness;
    } else if (star.y <= 0.0 && kind != 3u) {
        color = vec3<f32>(0.0);
    } else {
        var glow = pow(clamp(star.y, 1e-3, 1e5), 0.3);
        if (kind == 3u) {
            glow = max(glow, 0.3 * smoothstep(0.4, 0.9, view.lod));   // white dwarfs show up close
        }
        // close up, brighter stars are bigger squares, with the same light spread over them
        let grow = 1.0 + view.lod * clamp(0.6 * (log(max(star.y, 1e-3)) / log(10.0) + 1.0), 0.0, 3.0);
        size = floor(view.square_px * grow + 0.5);
        color = blackbody(star.x) * glow * view.brightness * (view.square_px * view.square_px) / (size * size);
    }
    var out: VOut;
    if (all(color == vec3<f32>(0.0))) {
        out.clip = vec4<f32>(2.0, 2.0, 2.0, 1.0);   // off screen
        out.color = color;
        return out;
    }
    let px = base - floor(0.5 * (size - view.square_px)) + corners[vi] * size;
    out.clip = vec4<f32>(px.x / view.viewport.x * 2.0 - 1.0, 1.0 - px.y / view.viewport.y * 2.0, 0.0, 1.0);
    out.color = color;
    return out;
}

@fragment
fn fs(in: VOut) -> @location(0) vec4<f32> {
    return vec4<f32>(in.color, 1.0);
}
