//! Copies the DXC shader compiler (vendor/dxc) next to the exe on Windows targets, where DX12 loads it
//! (see vendor/dxc/README.md).

use std::path::PathBuf;

fn main() {
    println!("cargo:rerun-if-changed=vendor/dxc");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }
    // OUT_DIR is target/<triple>/<profile>/build/<package>-<hash>/out: the exe's folder is three up
    let out = PathBuf::from(std::env::var("OUT_DIR").expect("cargo sets OUT_DIR"));
    let Some(exe_dir) = out.ancestors().nth(3) else { return };
    for dll in ["dxcompiler.dll", "dxil.dll"] {
        let src = PathBuf::from("vendor/dxc").join(dll);
        let dst = exe_dir.join(dll);
        let same = std::fs::metadata(&dst).ok().map(|m| m.len()) == std::fs::metadata(&src).ok().map(|m| m.len());
        if !same {
            std::fs::copy(&src, &dst).unwrap_or_else(|e| panic!("copying {} to {}: {e}", src.display(), dst.display()));
        }
    }
}
