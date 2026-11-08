use std::path::PathBuf;

use clap::Parser;

#[derive(Parser, Debug, Clone)]
#[command(name = "squareverse", version, about = "Squareverse v3: galaxies and the universe they live in, on the GPU")]
pub struct Cli {
    /// Run without a window and print (or write) a JSON report.
    #[arg(long)]
    pub headless: bool,
    /// Headless: steps of dt to run (after a short warm-up).
    #[arg(long, default_value_t = 50)]
    pub steps: u32,
    /// Headless: write the JSON report here instead of printing it.
    #[arg(long)]
    pub report: Option<PathBuf>,
    /// Headless: after the run, draw one frame (1280 x 800, the default view) into this PNG file.
    #[arg(long)]
    pub snapshot: Option<PathBuf>,
    /// The starting scene (default: galaxy).
    #[arg(long, value_enum)]
    pub scene: Option<crate::sim::Scene>,
    /// The galaxy disc's Toomre Q (default 1.5; ~1 grows spiral arms).
    #[arg(long)]
    pub toomre_q: Option<f64>,
    /// Number of particles (default: chosen for the GPU).
    #[arg(long)]
    pub particles: Option<u32>,
    #[arg(long, default_value_t = 1)]
    pub seed: u64,
    /// The longest time step, Myr (default 2).
    #[arg(long)]
    pub dt: Option<f64>,
    /// Time-step bins: steps run from dt down to dt / 2^(levels - 1) (default 5; 1: one fixed step).
    #[arg(long, value_parser = clap::value_parser!(u32).range(1..=8))]
    pub levels: Option<u32>,
    /// Time-step accuracy: each particle steps at most sqrt(2 eta softening / |a|) (default 0.025).
    #[arg(long)]
    pub eta: Option<f64>,
    /// Time-step accuracy: and at most eta_jerk |a| / |da/dt| (default 0.05; 0: off).
    #[arg(long)]
    pub eta_jerk: Option<f64>,
    /// The stars' softening, pc (default: 50 in the galaxy, 20 in the test disc).
    #[arg(long)]
    pub softening: Option<f64>,
    /// Dark matter's softening, pc (default 1000).
    #[arg(long)]
    pub dm_softening: Option<f64>,
    /// The galaxy's share of particles that are dark matter (default 0.4).
    #[arg(long)]
    pub halo_share: Option<f64>,
    /// Galaxy component masses, Msun (defaults: disc 4e10, bulge 1e10, halo 3.5e11, central well 4e6).
    #[arg(long)]
    pub disc_mass: Option<f64>,
    #[arg(long)]
    pub bulge_mass: Option<f64>,
    #[arg(long)]
    pub halo_mass: Option<f64>,
    #[arg(long)]
    pub well_mass: Option<f64>,
    /// Gas switches: no supernova / mass-return feedback, no cooling, no star formation.
    #[arg(long)]
    pub no_feedback: bool,
    #[arg(long)]
    pub no_cooling: bool,
    #[arg(long)]
    pub no_star_formation: bool,
    /// The galaxy's gas mass, Msun (default 1e10; 0: no gas).
    #[arg(long)]
    pub gas_mass: Option<f64>,
    /// Opening angle of the gravity tree (smaller: more accurate, slower).
    #[arg(long)]
    pub theta: Option<f64>,
    /// Tree nodes smaller than this many softening lengths act as one mass at any distance (0: off).
    #[arg(long)]
    pub open_small: Option<f64>,
    /// How the force pass walks the tree (default: chosen for the GPU).
    #[arg(long, value_enum)]
    pub walk: Option<crate::sim::Walk>,
    /// Sub-steps between full tree rebuilds (refits in between).
    #[arg(long)]
    pub rebuild_every: Option<u32>,
    /// Use only a GPU whose name contains this (any case).
    #[arg(long)]
    pub adapter: Option<String>,
    /// Allow software (CPU) adapters such as llvmpipe.
    #[arg(long)]
    pub allow_cpu: bool,
    /// List the GPU adapters and exit.
    #[arg(long)]
    pub list_adapters: bool,
    /// Frame-rate target: 60 or 30.
    #[arg(long, default_value_t = 60, value_parser = parse_fps)]
    pub fps: u32,
    #[arg(long)]
    pub fullscreen: bool,
    /// Window: close after this many frames and print the frame rate achieved (for measuring).
    #[arg(long)]
    pub exit_after_frames: Option<u64>,
}

fn parse_fps(s: &str) -> Result<u32, String> {
    match s {
        "60" => Ok(60),
        "30" => Ok(30),
        _ => Err("the frame-rate target is 60 or 30".into()),
    }
}
