//! Drawing: every particle a square, added into an HDR target (so crowded pixels glow), then tonemapped to the
//! screen. Positions stay fixed point all the way into the vertex shader, which subtracts the camera in integers.

use crate::fixed::{Fixed2, TWO_32};
use crate::sim::Sim;
use crate::timing::GpuTimer;

pub const HDR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct ViewUniform {
    center: [u32; 4],
    unit_pc: f32,
    px_per_pc: f32,
    viewport: [f32; 2],
    square_px: f32,
    brightness: f32,
    extrap_myr: f32,
    _pad: f32,
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct ToneUniform {
    exposure: f32,
    manual_srgb: u32,
    _pad: [u32; 2],
}

/// Where the camera looks: its centre in pc from the box's origin, and its zoom.
#[derive(Clone, Copy, Debug)]
pub struct Camera {
    pub center_pc: (f64, f64),
    pub px_per_pc: f64,
}

impl Camera {
    /// The world point (pc) under a pixel.
    pub fn world_at(&self, px: (f64, f64), viewport: (f64, f64)) -> (f64, f64) {
        (
            self.center_pc.0 + (px.0 - viewport.0 / 2.0) / self.px_per_pc,
            self.center_pc.1 + (viewport.1 / 2.0 - px.1) / self.px_per_pc,
        )
    }

    /// Zooms by `factor`, keeping the world point under `px` where it is.
    pub fn zoom_at(&mut self, factor: f64, px: (f64, f64), viewport: (f64, f64)) {
        let w = self.world_at(px, viewport);
        self.px_per_pc = (self.px_per_pc * factor).clamp(1e-7, 1e7);
        self.center_pc = (
            w.0 - (px.0 - viewport.0 / 2.0) / self.px_per_pc,
            w.1 - (viewport.1 / 2.0 - px.1) / self.px_per_pc,
        );
    }

    /// Moves the view by a mouse drag of (dx, dy) pixels.
    pub fn drag(&mut self, dx: f64, dy: f64) {
        self.center_pc.0 -= dx / self.px_per_pc;
        self.center_pc.1 += dy / self.px_per_pc;
    }
}

/// How things look (menu settings).
#[derive(Clone, Copy, Debug)]
pub struct Look {
    pub square_px: f32,
    pub brightness: f32,
    pub exposure: f32,
}

struct Hdr {
    view: wgpu::TextureView,
    bind: wgpu::BindGroup,
    size: (u32, u32),
}

pub struct Renderer {
    squares: wgpu::RenderPipeline,
    tonemap: wgpu::RenderPipeline,
    view_buf: wgpu::Buffer,
    view_bind: wgpu::BindGroup,
    tone_buf: wgpu::Buffer,
    tone_layout: wgpu::BindGroupLayout,
    hdr: Option<Hdr>,
    manual_srgb: bool,
}

impl Renderer {
    pub fn new(device: &wgpu::Device, surface_format: wgpu::TextureFormat) -> Self {
        let uniform = |label, size| {
            device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(label),
                size,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            })
        };
        let view_buf = uniform("view", std::mem::size_of::<ViewUniform>() as u64);
        let tone_buf = uniform("tone", std::mem::size_of::<ToneUniform>() as u64);

        let squares_module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("squares"),
            source: wgpu::ShaderSource::Wgsl(
                format!("{}\n{}", include_str!("../shaders/fixed.wgsl"), include_str!("../shaders/squares.wgsl")).into(),
            ),
        });
        let add = wgpu::BlendComponent {
            src_factor: wgpu::BlendFactor::One,
            dst_factor: wgpu::BlendFactor::One,
            operation: wgpu::BlendOperation::Add,
        };
        let squares = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("squares"),
            layout: None,
            vertex: wgpu::VertexState {
                module: &squares_module,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[
                    Some(wgpu::VertexBufferLayout {
                        array_stride: 16,
                        step_mode: wgpu::VertexStepMode::Instance,
                        attributes: &wgpu::vertex_attr_array![0 => Uint32x4],
                    }),
                    // (vx, vy, temperature, luminosity)
                    Some(wgpu::VertexBufferLayout {
                        array_stride: 16,
                        step_mode: wgpu::VertexStepMode::Instance,
                        attributes: &[
                            wgpu::VertexAttribute { format: wgpu::VertexFormat::Float32x2, offset: 8, shader_location: 1 },
                            wgpu::VertexAttribute { format: wgpu::VertexFormat::Float32x2, offset: 0, shader_location: 2 },
                        ],
                    }),
                ],
            },
            primitive: Default::default(),
            depth_stencil: None,
            multisample: Default::default(),
            fragment: Some(wgpu::FragmentState {
                module: &squares_module,
                entry_point: Some("fs"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format: HDR_FORMAT,
                    blend: Some(wgpu::BlendState { color: add, alpha: add }),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            multiview_mask: None,
            cache: None,
        });
        let view_bind = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("view"),
            layout: &squares.get_bind_group_layout(0),
            entries: &[wgpu::BindGroupEntry { binding: 0, resource: view_buf.as_entire_binding() }],
        });

        let tone_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("tonemap"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: false },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
            ],
        });
        let tone_module = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("tonemap"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/tonemap.wgsl").into()),
        });
        let tone_pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("tonemap"),
            bind_group_layouts: &[Some(&tone_layout)],
            ..Default::default()
        });
        let tonemap = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("tonemap"),
            layout: Some(&tone_pipeline_layout),
            vertex: wgpu::VertexState {
                module: &tone_module,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            primitive: Default::default(),
            depth_stencil: None,
            multisample: Default::default(),
            fragment: Some(wgpu::FragmentState {
                module: &tone_module,
                entry_point: Some("fs"),
                compilation_options: Default::default(),
                targets: &[Some(surface_format.into())],
            }),
            multiview_mask: None,
            cache: None,
        });
        Self {
            squares,
            tonemap,
            view_buf,
            view_bind,
            tone_buf,
            tone_layout,
            hdr: None,
            manual_srgb: !surface_format.is_srgb(),
        }
    }

    fn ensure_hdr(&mut self, device: &wgpu::Device, size: (u32, u32)) {
        if self.hdr.as_ref().is_some_and(|h| h.size == size) {
            return;
        }
        let tex = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("hdr"),
            size: wgpu::Extent3d { width: size.0.max(1), height: size.1.max(1), depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: HDR_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            view_formats: &[],
        });
        let view = tex.create_view(&Default::default());
        let bind = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("tonemap"),
            layout: &self.tone_layout,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: wgpu::BindingResource::TextureView(&view) },
                wgpu::BindGroupEntry { binding: 1, resource: self.tone_buf.as_entire_binding() },
            ],
        });
        self.hdr = Some(Hdr { view, bind, size });
    }

    /// Draws the particles, each moved on by `extrap_myr` at its velocity (the window's display clock runs smoothly
    /// while the sim advances in uneven bites; the gap is a fraction of a Myr).
    #[allow(clippy::too_many_arguments)]
    pub fn draw(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        target: &wgpu::TextureView,
        size: (u32, u32),
        sim: &Sim,
        camera: &Camera,
        look: &Look,
        extrap_myr: f64,
        timer: &mut GpuTimer,
    ) {
        self.ensure_hdr(device, size);
        let view = ViewUniform {
            center: Fixed2::from_pc(camera.center_pc.0, camera.center_pc.1, sim.cfg.box_pc).words(),
            unit_pc: (sim.cfg.box_pc / TWO_32) as f32,
            px_per_pc: camera.px_per_pc as f32,
            viewport: [size.0 as f32, size.1 as f32],
            square_px: look.square_px,
            brightness: look.brightness,
            extrap_myr: extrap_myr as f32,
            _pad: 0.0,
        };
        queue.write_buffer(&self.view_buf, 0, bytemuck::bytes_of(&view));
        let tone = ToneUniform { exposure: look.exposure, manual_srgb: self.manual_srgb as u32, _pad: [0; 2] };
        queue.write_buffer(&self.tone_buf, 0, bytemuck::bytes_of(&tone));
        let hdr = self.hdr.as_ref().expect("made above");

        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("squares"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &hdr.view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations { load: wgpu::LoadOp::Clear(wgpu::Color::BLACK), store: wgpu::StoreOp::Store },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: timer.render("draw"),
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_pipeline(&self.squares);
            pass.set_bind_group(0, &self.view_bind, &[]);
            pass.set_vertex_buffer(0, sim.pos_buffer().slice(..));
            pass.set_vertex_buffer(1, sim.kin_buffer().slice(..));
            pass.draw(0..6, 0..sim.n);
        }
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("tonemap"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: target,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations { load: wgpu::LoadOp::Clear(wgpu::Color::BLACK), store: wgpu::StoreOp::Store },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: timer.render("tonemap"),
            occlusion_query_set: None,
            multiview_mask: None,
        });
        pass.set_pipeline(&self.tonemap);
        pass.set_bind_group(0, &hdr.bind, &[]);
        pass.draw(0..3, 0..1);
    }
}
