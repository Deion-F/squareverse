use std::path::PathBuf;

use clap::Parser;

#[derive(Parser, Debug, Clone)]
#[command(name = "squareverse", version, about = "Squareverse v3: galaxies and the universe they live in, on the GPU")]
pub struct Cli {
    /// Run without a window and print (or write) a JSON report.
    #[arg(long)]
    pub headless: bool,
    /// Headless: steps to run (after a short warm-up).
    #[arg(long, default_value_t = 300)]
    pub steps: u32,
    /// Headless: write the JSON report here instead of printing it.
    #[arg(long)]
    pub report: Option<PathBuf>,
    /// Headless: after the run, draw one frame (1280 x 800, the default view) into this PNG file.
    #[arg(long)]
    pub snapshot: Option<PathBuf>,
    /// Number of particles (default: chosen for the GPU).
    #[arg(long)]
    pub particles: Option<u32>,
    #[arg(long, default_value_t = 1)]
    pub seed: u64,
    /// Myr per step.
    #[arg(long)]
    pub dt: Option<f64>,
    /// Opening angle of the gravity tree (smaller: more accurate, slower).
    #[arg(long)]
    pub theta: Option<f64>,
    /// How the force pass walks the tree (default: chosen for the GPU).
    #[arg(long, value_enum)]
    pub walk: Option<crate::sim::Walk>,
    /// Steps between full tree rebuilds (refits in between).
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
