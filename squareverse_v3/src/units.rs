//! Units used everywhere: lengths in parsecs (pc), masses in solar masses (Msun), times in megayears (Myr).
//! Speeds are therefore pc / Myr (1 km/s = 1.0227 pc / Myr).

/// Newton's constant in pc^3 / (Msun Myr^2) (4.30091e-3 pc (km/s)^2 / Msun).
pub const G: f64 = 4.498_502e-3;
/// Speed of light in pc / Myr.
pub const C: f64 = 306_601.4;
/// One km/s in pc / Myr.
pub const KM_S: f64 = 1.022_712;
