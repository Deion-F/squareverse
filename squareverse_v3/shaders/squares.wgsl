// Every particle is a square snapped to the pixel grid, added (additive blending) into an HDR target, so where
// many fall on one pixel they glow. Stars are coloured by their surface temperature. Prepended with fixed.wgsl.

struct View {
    center: vec4<u32>,   // the camera, fixed point
    unit_pc: f32,
    px_per_pc: f32,
    viewport: vec2<f32>, // pixels
    square_px: f32,
    brightness: f32,
    _pad: vec2<f32>,
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
) -> VOut {
    var corners = array<vec2<f32>, 6>(
        vec2<f32>(0.0, 0.0), vec2<f32>(1.0, 0.0), vec2<f32>(0.0, 1.0),
        vec2<f32>(0.0, 1.0), vec2<f32>(1.0, 0.0), vec2<f32>(1.0, 1.0),
    );
    let d = fx_delta2(q, view.center) * (view.unit_pc * view.px_per_pc);
    // world y points up, screen y down
    let base = floor(vec2<f32>(view.viewport.x * 0.5 + d.x, view.viewport.y * 0.5 - d.y));
    let px = base + corners[vi] * view.square_px;
    var out: VOut;
    out.clip = vec4<f32>(px.x / view.viewport.x * 2.0 - 1.0, 1.0 - px.y / view.viewport.y * 2.0, 0.0, 1.0);
    let glow = pow(clamp(star.y, 1e-3, 1e5), 0.3);
    out.color = blackbody(star.x) * glow * view.brightness;
    return out;
}

@fragment
fn fs(in: VOut) -> @location(0) vec4<f32> {
    return vec4<f32>(in.color, 1.0);
}
