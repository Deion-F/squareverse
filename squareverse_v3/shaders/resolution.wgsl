// Adaptive resolution for the gas, once a step of dt (after feedback, when every particle's step has ended):
//
// - merging: thin, hot gas particles lighter than gas_f.y x the reference mass (gas_f.w) merge in pairs, keeping
//   mass, momentum, energy (the pair's relative motion becomes heat) and elements. Pairs are neighbours in the
//   sorted order (`merge`, even positions in the gas's run with the next one), so the pairing is the same every
//   run. The second becomes K_GONE.
// - splitting: gas heavier than gas_f.z x the reference mass (it gathered what stars gave back) splits in two,
//   a quarter of its kernel reach either side of where it was, into a free slot (a K_GONE particle: swallowed or
//   merged). The free slots and the heavy particles are listed in index order (`flag_*` and a prefix sum, then
//   `scatter_*`), and the k-th heavy one takes the k-th free slot (`split_a`, `split_b`: the arrays are split
//   between them to stay within 8 storage buffers a pass).

@group(0) @binding(0) var<uniform> c: Common;

const THIN_SHARE: f32 = 0.01;   // thin: under this share of the star formation density
const HOT_K: f32 = 1e5;

fn thin_hot(g: vec4<f32>) -> bool {
    return gas_rho(g.y) < THIN_SHARE * c.gas_b.x && gas_temperature(g.x) > HOT_K;
}
