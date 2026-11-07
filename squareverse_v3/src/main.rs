use anyhow::Result;
use clap::Parser;
use squareverse::{app, cli::Cli, gpu, headless};

/// Warnings and up, except EGL's complaint under WSL that it can't load a DRI driver before it finds D3D12.
const LOG_DEFAULT: &str = "warn,wgpu_hal::gles::egl=off";

fn main() -> Result<()> {
    gpu::prepare_platform();
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or(LOG_DEFAULT)).init();
    let cli = Cli::parse();
    if cli.list_adapters {
        let instance = wgpu::Instance::new(gpu::instance_descriptor(None));
        for a in gpu::list_adapters(&instance) {
            let s = gpu::summary(&a);
            let soft = if gpu::is_software(&a) { "  (software)" } else { "" };
            println!("{} | {} | {} | {}{}", s.name, s.backend, s.kind, s.driver, soft);
        }
        return Ok(());
    }
    if cli.headless {
        return headless::main(&cli);
    }
    app::run(cli)
}
