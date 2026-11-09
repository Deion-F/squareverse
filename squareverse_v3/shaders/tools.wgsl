// The window's tools (phase 8), applied between steps of dt (every particle's step has ended), so they act like
// a change of the starting conditions. Prepended with fixed.wgsl and common.wgsl.
//
// - `brush` (tools_brush): every particle of the kinds asked for within a radius of a point is kicked (its velocity
//   changed), deleted (made K_GONE, massless) or moved; or the particle with a given id gets a new mass.
// - `spawn_a`, `spawn_b` (tools_spawn): new particles, made on the CPU, written into free slots (K_GONE particles:
//   spares kept for this, swallowed and merged ones), at the shortest time step so they settle in at once.

@group(0) @binding(0) var<uniform> c: Common;

struct Edit {
    point: vec4<u32>,     // fixed point
    unit_pc: f32,         // pc per hi unit now
    radius_pc: f32,
    mode: u32,            // 0 kick, 1 delete, 2 move, 3 set the mass of `target_id`
    kinds: u32,           // bit k: kind k is touched
    dv: vec2<f32>,        // pc / Myr
    dpos: vec2<f32>,      // pc
    target_id: u32,
    value: f32,
    count: u32,           // spawn: new particles
    _a: u32,
}
