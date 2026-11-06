//! GPU radix sort of 48-bit keys with u32 values (`shaders/radix.wgsl`, `shaders/scan.wgsl`): stable and
//! deterministic. `keys[0]` / `vals[0]` hold the input and, after the six passes, the sorted result.

use crate::kernels::{Bind, Groups, Kernel, storage, uniform};

pub const TILE: u32 = 256;
const PASSES: u32 = 6;
const SCAN_BLOCK: u32 = 1024;

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Pass {
    n: u32,
    tiles: u32,
    row_groups: u32,
    index: u32,
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Level {
    n: u32,
    row_groups: u32,
    _a: u32,
    _b: u32,
}

/// Exclusive prefix sum over a u32 buffer, in levels of 1,024.
pub struct Scan {
    kernel: Kernel,
    /// (bind group with data = this level and sums = the next, groups) from the bottom level up
    levels: Vec<(wgpu::BindGroup, Groups)>,
    _buffers: Vec<wgpu::Buffer>,
}

impl Scan {
    pub fn new(device: &wgpu::Device, data: &wgpu::Buffer, n: u32) -> Self {
        let kernel = Kernel::new(
            device,
            "scan",
            include_str!("../shaders/scan.wgsl"),
            &[Bind::Uniform, Bind::Write, Bind::Write],
            &["scan_blocks", "add_blocks"],
        );
        let mut buffers = Vec::new();
        let mut levels = Vec::new();
        let mut len = n;
        let mut level_data: Option<usize> = None; // None: the caller's buffer
        loop {
            let blocks = len.div_ceil(SCAN_BLOCK).max(1);
            let groups = Groups::count(blocks);
            let sums = storage(device, "scan sums", blocks as u64 * 4);
            let u = uniform(device, "scan level", &Level { n: len, row_groups: groups.x, _a: 0, _b: 0 });
            let data_buf = match level_data {
                None => data,
                Some(i) => &buffers[i],
            };
            let bg = kernel.bind(device, "scan", &[&u, data_buf, &sums]);
            levels.push((bg, groups));
            buffers.push(u);
            buffers.push(sums);
            level_data = Some(buffers.len() - 1);
            if blocks == 1 {
                break;
            }
            len = blocks;
        }
        Self { kernel, levels, _buffers: buffers }
    }

    pub fn encode(&self, pass: &mut wgpu::ComputePass) {
        for (bg, g) in &self.levels {
            self.kernel.run(pass, "scan_blocks", bg, *g);
        }
        // add each level's scanned block sums back, top level down (the top one has a single block: nothing to add)
        for (bg, g) in self.levels.iter().rev().skip(1) {
            self.kernel.run(pass, "add_blocks", bg, *g);
        }
    }
}

pub struct RadixSort {
    pub keys: [wgpu::Buffer; 2],
    pub vals: [wgpu::Buffer; 2],
    kernel: Kernel,
    /// per pass: (local sort bind group, scatter bind group)
    passes: Vec<(wgpu::BindGroup, wgpu::BindGroup)>,
    scan: Scan,
    groups: Groups,
    _buffers: Vec<wgpu::Buffer>,
}

impl RadixSort {
    pub fn new(device: &wgpu::Device, n: u32) -> Self {
        let kernel = Kernel::new(
            device,
            "radix",
            include_str!("../shaders/radix.wgsl"),
            &[Bind::Uniform, Bind::Read, Bind::Read, Bind::Write, Bind::Write, Bind::Write],
            &["local_sort", "scatter"],
        );
        let tiles = n.div_ceil(TILE).max(1);
        let groups = Groups::count(tiles);
        let keys = [storage(device, "keys 0", n as u64 * 8), storage(device, "keys 1", n as u64 * 8)];
        let vals = [storage(device, "vals 0", n as u64 * 4), storage(device, "vals 1", n as u64 * 4)];
        let keys_tmp = storage(device, "keys tmp", n as u64 * 8);
        let vals_tmp = storage(device, "vals tmp", n as u64 * 4);
        let hist = storage(device, "hist", 256 * tiles as u64 * 4);
        let scan = Scan::new(device, &hist, 256 * tiles);
        let mut buffers = Vec::new();
        let mut passes = Vec::new();
        for p in 0..PASSES {
            let (src, dst) = ((p % 2) as usize, ((p + 1) % 2) as usize);
            let u = uniform(device, "radix pass", &Pass { n, tiles, row_groups: groups.x, index: p });
            let local = kernel.bind(device, "radix local", &[&u, &keys[src], &vals[src], &keys_tmp, &vals_tmp, &hist]);
            let scatter = kernel.bind(device, "radix scatter", &[&u, &keys_tmp, &vals_tmp, &keys[dst], &vals[dst], &hist]);
            passes.push((local, scatter));
            buffers.push(u);
        }
        buffers.extend([keys_tmp, vals_tmp, hist]);
        Self { keys, vals, kernel, passes, scan, groups, _buffers: buffers }
    }

    pub fn encode(&self, pass: &mut wgpu::ComputePass) {
        for (local, scatter) in &self.passes {
            self.kernel.run(pass, "local_sort", local, self.groups);
            self.scan.encode(pass);
            self.kernel.run(pass, "scatter", scatter, self.groups);
        }
    }
}
