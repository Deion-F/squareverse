// HDR target -> screen: Reinhard on luminance (keeps colours), then sRGB encoding when the surface doesn't do it.

struct Tone {
    exposure: f32,
    manual_srgb: u32,
    _pad: vec2<u32>,
}

@group(0) @binding(0) var hdr: texture_2d<f32>;
@group(0) @binding(1) var<uniform> tone: Tone;

@vertex
fn vs(@builtin(vertex_index) vi: u32) -> @builtin(position) vec4<f32> {
    // one triangle covering the screen
    let x = f32((vi << 1u) & 2u) * 2.0 - 1.0;
    let y = f32(vi & 2u) * 2.0 - 1.0;
    return vec4<f32>(x, y, 0.0, 1.0);
}

fn to_srgb(c: vec3<f32>) -> vec3<f32> {
    let lo = c * 12.92;
    let hi = 1.055 * pow(c, vec3<f32>(1.0 / 2.4)) - 0.055;
    return select(hi, lo, c <= vec3<f32>(0.0031308));
}

@fragment
fn fs(@builtin(position) frag: vec4<f32>) -> @location(0) vec4<f32> {
    let c = textureLoad(hdr, vec2<i32>(frag.xy), 0).rgb * tone.exposure;
    let lum = dot(c, vec3<f32>(0.2126, 0.7152, 0.0722));
    var out = c / (1.0 + lum);
    out = min(out, vec3<f32>(1.0));
    if (tone.manual_srgb != 0u) {
        out = to_srgb(out);
    }
    return vec4<f32>(out, 1.0);
}
