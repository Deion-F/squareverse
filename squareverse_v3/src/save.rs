//! Saving and loading a universe (phase 8), and the presets made from saves.
//!
//! A file is "SQV3", a u32 length and a JSON header (the config, steps run, a name), then the particles (positions,
//! velocities and colours, masses and kinds, stars' records, gas, elements) as one lz4-compressed block. Loading
//! builds a new sim from them (`Sim::from_initial`) whose clock carries on from the saved step, so a run saved and
//! loaded goes on as it would have, bar the time-step bins, which start afresh.
//!
//! Presets are saves kept in the `presets` folder next to the program (or the working folder), listed in the menu.

use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};

use crate::gpu::Gpu;
use crate::sim::init::{Initial, KIND_SHIFT, Kind};
use crate::sim::{Sim, SimConfig, State};

const MAGIC: &[u8; 4] = b"SQV3";

#[derive(Serialize, Deserialize)]
pub struct Header {
    pub version: u32,
    pub name: String,
    pub config: SimConfig,
    pub steps: u64,
    pub single_stars: bool,
    pub particles: u32,
}

/// The particles of a state as starting conditions (ids kept: a state is in id order).
pub fn initial_of(s: &State, single_stars: bool) -> Initial {
    let n = s.pos.len();
    let mut out = Initial::with_capacity(n);
    out.single_stars = single_stars;
    for i in 0..n {
        out.pos.push(s.pos[i].words());
        out.kin.push([s.vel[i][0], s.vel[i][1], s.star[i][0], s.star[i][1]]);
        out.body.push([s.mass[i].to_bits(), s.kind[i] << KIND_SHIFT | i as u32]);
        out.about.push(s.about[i]);
        let g = s.gas[i];
        out.gas.push([g[0], g[1], g[2], g[3], 0.0, 0.0, 0.0, 0.0]);
        out.chem.push(s.chem[i]);
        if s.kind[i] == Kind::Well as u32 {
            out.wells += 1;
        }
    }
    out
}

fn bytes<T: bytemuck::Pod>(v: &[T]) -> &[u8] {
    bytemuck::cast_slice(v)
}

/// Writes the sim (at the end of a step: velocities in step) to `path`.
pub fn save(gpu: &Gpu, sim: &Sim, path: &Path, name: &str) -> Result<()> {
    let s = sim.read_state(gpu)?;
    let init = initial_of(&s, sim.single_stars());
    let header = Header { version: 1, name: name.into(), config: sim.cfg.clone(), steps: sim.steps, single_stars: init.single_stars, particles: init.len() as u32 };
    let json = serde_json::to_vec(&header)?;
    let mut raw = Vec::with_capacity(init.len() * 88);
    for part in [bytes(&init.pos), bytes(&init.kin), bytes(&init.body), bytes(&init.about), bytes(&init.chem)] {
        raw.extend_from_slice(part);
    }
    let gas4: Vec<[f32; 4]> = init.gas.iter().map(|g| [g[0], g[1], g[2], g[3]]).collect();
    raw.extend_from_slice(bytes(&gas4));
    let packed = lz4_flex::compress_prepend_size(&raw);
    let mut out = Vec::with_capacity(8 + json.len() + packed.len());
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&(json.len() as u32).to_le_bytes());
    out.extend_from_slice(&json);
    out.extend_from_slice(&packed);
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).ok();
    }
    std::fs::write(path, out).with_context(|| format!("writing {}", path.display()))
}

/// Reads a save's header and particles.
pub fn read(path: &Path) -> Result<(Header, Initial)> {
    let data = std::fs::read(path).with_context(|| format!("reading {}", path.display()))?;
    if data.len() < 8 || &data[..4] != MAGIC {
        bail!("{} is not a Squareverse v3 save", path.display());
    }
    let hl = u32::from_le_bytes(data[4..8].try_into()?) as usize;
    let header: Header = serde_json::from_slice(&data[8..8 + hl])?;
    let raw = lz4_flex::decompress_size_prepended(&data[8 + hl..]).context("unpacking the particles")?;
    let n = header.particles as usize;
    let mut at = 0;
    let mut take = |size: usize| {
        let s = &raw[at..at + n * size];
        at += n * size;
        s
    };
    let mut init = Initial::with_capacity(n);
    init.single_stars = header.single_stars;
    init.pos = bytemuck::pod_collect_to_vec(take(16));
    init.kin = bytemuck::pod_collect_to_vec(take(16));
    init.body = bytemuck::pod_collect_to_vec(take(8));
    init.about = bytemuck::pod_collect_to_vec(take(16));
    init.chem = bytemuck::pod_collect_to_vec(take(16));
    let gas4: Vec<[f32; 4]> = bytemuck::pod_collect_to_vec(take(16));
    init.gas = gas4.iter().map(|g| [g[0], g[1], g[2], g[3], 0.0, 0.0, 0.0, 0.0]).collect();
    init.wells = init.body.iter().filter(|b| b[1] >> KIND_SHIFT == Kind::Well as u32).count() as u32;
    Ok((header, init))
}

/// Loads a save as a new sim, carrying on from its step.
pub fn load(gpu: &Gpu, path: &Path) -> Result<Sim> {
    let (h, init) = read(path)?;
    let cfg = SimConfig { start_steps: h.steps, ..h.config };
    Sim::from_initial(gpu, cfg, &init)
}

/// The presets folder: `presets` beside the program if it exists there, else in the working folder.
pub fn presets_dir() -> PathBuf {
    if let Ok(exe) = std::env::current_exe()
        && let Some(dir) = exe.parent()
    {
        let p = dir.join("presets");
        if p.is_dir() {
            return p;
        }
    }
    PathBuf::from("presets")
}

/// Where quick saves go: `saves/quick.sqv` in the working folder.
pub fn quick_path() -> PathBuf {
    PathBuf::from("saves").join("quick.sqv")
}

/// The presets there, by name (file stem), sorted.
pub fn list_presets() -> Vec<(String, PathBuf)> {
    let mut out: Vec<(String, PathBuf)> = std::fs::read_dir(presets_dir())
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "sqv"))
        .map(|p| (p.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default(), p))
        .collect();
    out.sort();
    out
}

/// A file name from a preset name (letters, digits, spaces, - and _ kept).
pub fn preset_path(name: &str) -> PathBuf {
    let clean: String = name.chars().map(|c| if c.is_alphanumeric() || c == '-' || c == '_' || c == ' ' { c } else { '_' }).collect();
    presets_dir().join(format!("{}.sqv", clean.trim()))
}
