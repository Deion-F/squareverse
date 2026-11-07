# DXC (DirectX Shader Compiler)

`dxcompiler.dll` and `dxil.dll` from Microsoft's official release
[v1.9.2609](https://github.com/microsoft/DirectXShaderCompiler/releases/tag/v1.9.2609)
(`dxc_2026_09_29.zip`, sha256 `ad31b1fc8443175d204f77a611fdb3ef2ec42759bdc2f1167368de24a4a7e7f1`, the digest GitHub
lists for it; the DLLs' own hashes are in `SHA256SUMS`), `bin/x64`. Licences: `LICENSE-MS.txt`, `LICENSE-LLVM.txt`.

Why: on DX12, wgpu otherwise compiles shaders with Windows' old FXC, which takes ~170 s for Squareverse's shaders;
DXC takes seconds. `build.rs` copies these two DLLs next to the Windows exe, and `gpu::instance_descriptor` points
wgpu at `dxcompiler.dll` there (unless `WGPU_DX12_COMPILER` is set). Ship them beside the exe in a release.

To update: download a newer release's zip, check its sha256 against the digest on the release page, replace the two
DLLs from `bin/x64`, the licence files, and `SHA256SUMS`.
