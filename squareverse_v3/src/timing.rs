//! GPU time per pass from timestamp queries. A frame asks for writes for each named pass; after submitting, the
//! results are read back without stalling (the next frames pick them up), or waited for in headless runs.
//! Without TIMESTAMP_QUERY every call is a no-op and no times are reported.

use std::sync::Arc;
use std::sync::atomic::{AtomicU8, Ordering};

const MAX_PASSES: u32 = 64;

// read-back states
const IDLE: u8 = 0;
const MAPPING: u8 = 1;
const MAPPED: u8 = 2;

pub struct GpuTimer {
    inner: Option<Inner>,
    /// The last times read, (pass name, milliseconds), in the order the passes ran.
    pub last: Vec<(&'static str, f64)>,
}

struct Inner {
    set: wgpu::QuerySet,
    resolve: wgpu::Buffer,
    read: wgpu::Buffer,
    period_ns: f32,
    labels: Vec<&'static str>,
    read_labels: Vec<&'static str>,
    state: Arc<AtomicU8>,
    resolved: bool,
}

impl GpuTimer {
    pub fn new(device: &wgpu::Device, queue: &wgpu::Queue, enabled: bool) -> Self {
        let inner = enabled.then(|| {
            let bytes = (MAX_PASSES * 2 * 8) as u64;
            Inner {
                set: device.create_query_set(&wgpu::QuerySetDescriptor {
                    label: Some("timestamps"),
                    ty: wgpu::QueryType::Timestamp,
                    count: MAX_PASSES * 2,
                }),
                resolve: device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some("timestamps resolve"),
                    size: bytes,
                    usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                    mapped_at_creation: false,
                }),
                read: device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some("timestamps read"),
                    size: bytes,
                    usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                }),
                period_ns: queue.get_timestamp_period(),
                labels: Vec::new(),
                read_labels: Vec::new(),
                state: Arc::new(AtomicU8::new(IDLE)),
                resolved: false,
            }
        });
        Self { inner, last: Vec::new() }
    }

    pub fn enabled(&self) -> bool {
        self.inner.is_some()
    }

    /// Starts a frame's set of passes. Timing is skipped for this frame while the last results are still being read.
    pub fn begin(&mut self) {
        if let Some(t) = &mut self.inner {
            t.labels.clear();
            t.resolved = false;
        }
    }

    fn slot(&mut self, label: &'static str) -> Option<(&wgpu::QuerySet, u32)> {
        let t = self.inner.as_mut()?;
        if t.state.load(Ordering::Acquire) != IDLE || t.labels.len() as u32 >= MAX_PASSES {
            return None;
        }
        let i = t.labels.len() as u32;
        t.labels.push(label);
        Some((&t.set, i * 2))
    }

    pub fn compute(&mut self, label: &'static str) -> Option<wgpu::ComputePassTimestampWrites<'_>> {
        self.slot(label).map(|(set, i)| wgpu::ComputePassTimestampWrites {
            query_set: set,
            beginning_of_pass_write_index: Some(i),
            end_of_pass_write_index: Some(i + 1),
        })
    }

    pub fn render(&mut self, label: &'static str) -> Option<wgpu::RenderPassTimestampWrites<'_>> {
        self.slot(label).map(|(set, i)| wgpu::RenderPassTimestampWrites {
            query_set: set,
            beginning_of_pass_write_index: Some(i),
            end_of_pass_write_index: Some(i + 1),
        })
    }

    /// Records the copy of this frame's timestamps into the read-back buffer. Call last before finishing the encoder.
    pub fn resolve(&mut self, encoder: &mut wgpu::CommandEncoder) {
        let Some(t) = &mut self.inner else { return };
        if t.labels.is_empty() || t.state.load(Ordering::Acquire) != IDLE {
            return;
        }
        let n = t.labels.len() as u32 * 2;
        encoder.resolve_query_set(&t.set, 0..n, &t.resolve, 0);
        encoder.copy_buffer_to_buffer(&t.resolve, 0, &t.read, 0, n as u64 * 8);
        t.resolved = true;
    }

    /// After the submit: starts reading the results back.
    pub fn after_submit(&mut self) {
        let Some(t) = &mut self.inner else { return };
        if !t.resolved {
            return;
        }
        t.resolved = false;
        t.read_labels = std::mem::take(&mut t.labels);
        t.state.store(MAPPING, Ordering::Release);
        let state = t.state.clone();
        t.read.slice(..).map_async(wgpu::MapMode::Read, move |r| {
            state.store(if r.is_ok() { MAPPED } else { IDLE }, Ordering::Release);
        });
    }

    /// Picks up finished results (call once a frame, after polling the device). True when `last` was updated.
    pub fn collect(&mut self) -> bool {
        let Some(t) = &mut self.inner else { return false };
        if t.state.load(Ordering::Acquire) != MAPPED {
            return false;
        }
        {
            let Ok(data) = t.read.slice(..).get_mapped_range() else {
                t.state.store(IDLE, Ordering::Release);
                return false;
            };
            let ticks: &[u64] = bytemuck::cast_slice(&data[..t.read_labels.len() * 16]);
            self.last = t
                .read_labels
                .iter()
                .enumerate()
                .map(|(i, &l)| (l, ticks[2 * i + 1].wrapping_sub(ticks[2 * i]) as f64 * t.period_ns as f64 * 1e-6))
                .collect();
        }
        t.read.unmap();
        t.state.store(IDLE, Ordering::Release);
        true
    }

    /// The mean of the last times for passes with this name (several steps' passes share a name).
    pub fn mean_ms(&self, label: &str) -> Option<f64> {
        let v: Vec<f64> = self.last.iter().filter(|(l, _)| *l == label).map(|(_, ms)| *ms).collect();
        (!v.is_empty()).then(|| v.iter().sum::<f64>() / v.len() as f64)
    }

    /// The pass names in the last times, in first-seen order.
    pub fn labels(&self) -> Vec<&'static str> {
        let mut out: Vec<&'static str> = Vec::new();
        for (l, _) in &self.last {
            if !out.contains(l) {
                out.push(l);
            }
        }
        out
    }

    /// Total of the last times for passes with this name.
    pub fn ms(&self, label: &str) -> Option<f64> {
        let v: Vec<f64> = self.last.iter().filter(|(l, _)| *l == label).map(|(_, ms)| *ms).collect();
        (!v.is_empty()).then(|| v.iter().sum())
    }
}
