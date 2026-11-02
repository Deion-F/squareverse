#!/usr/bin/env python3
"""Squareverse v2: a particle sandbox for gravity wells, self-gravity, mass layering, merging and splitting.

Run without arguments for the interactive sandbox (H shows the controls), or with --benchmark for headless timings.
"""

import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

try:
    import numba  # noqa: F401
    import numpy  # noqa: F401
except ModuleNotFoundError:
    # numpy / numba live in the repository's virtualenv; relaunch with that interpreter (as sand.py does)
    venv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".venv")
    venv_py = os.path.join(venv, "Scripts" if os.name == "nt" else "bin", "python")
    if os.path.exists(venv_py) and os.path.abspath(sys.prefix) != venv:
        os.execv(venv_py, [venv_py, os.path.abspath(__file__), *sys.argv[1:]])
    sys.exit("numpy/numba are missing. Install with:  pip install -r requirements.txt")

import argparse
import time

import numpy as np

from sv import config
from sv.presets import PRESETS
from sv.world import World, warmup


def parse_args():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--size", default=f"{config.WINDOW[0]}x{config.WINDOW[1]}", help="window size WxH in px")
    p.add_argument("--fullscreen", action="store_true", help="start fullscreen (F11 toggles)")
    p.add_argument("--cell", type=int, default=config.DEFAULT_CELL, choices=config.CELL_SIZES,
                   help="px per particle")
    p.add_argument("--preset", default=config.DEFAULT_PRESET, choices=sorted(PRESETS), help="starting scene")
    p.add_argument("--particles", type=int, help="particle count for the preset (default: fills its region)")
    p.add_argument("--seed", type=int, help="random seed for a reproducible run")
    p.add_argument("--benchmark", type=int, metavar="TICKS", help="run TICKS ticks headless and print timings")
    speed = p.add_mutually_exclusive_group()
    speed.add_argument("--cpu", action="store_true",
                       help="run as before acceleration: the particles on one core, no GPU (a --seed run repeats)")
    speed.add_argument("--no-gpu", action="store_true", help="use all CPU cores, but not the GPU")
    speed.add_argument("--gpu", action="store_true",
                       help="always give the GPU the work it can do, even where the CPU cores measure faster")
    p.add_argument("--gpu-name", metavar="NAME", help="use the GPU whose name contains NAME (default: the best one)")
    return p.parse_args()


def accelerate(world, args):
    """Share the work out over all CPU cores and the best GPU there is (see World.accelerate), unless --cpu."""
    if args.cpu:
        print("acceleration off (--cpu): one core, no GPU")
        return
    gpu = None
    if not args.no_gpu:
        from sv.gpu import open_device
        gpu, why = open_device(args.gpu_name)
        print(f"GPU: {gpu}" + ("" if args.gpu else ", where it is faster than the CPU cores") if gpu
              else f"GPU: off, {why}")
    world.accelerate(cores=True, gpu=gpu, force_gpu=args.gpu)


def benchmark(world, ticks):
    import pygame   # only for the blit timing; no window is opened
    step, grav, awake = [], [], []
    for _ in range(ticks):
        world.step()
        step.append(world.step_ms)
        grav.append(world.gravity_ms)
        awake.append(world.awake_count())
    t = time.perf_counter()
    for _ in range(50):
        world.render(0)
        small = pygame.image.frombuffer(world.rgb, (world.w, world.h), "RGB")
        pygame.transform.scale(small, (world.w * world.cell, world.h * world.cell))
    render_ms = (time.perf_counter() - t) * 1000 / 50
    step = np.array(step[1:] or step)
    grav = np.array(grav[1:] or grav)
    print(f"{world.particle_count():,} particles on {world.w}x{world.h} cells, {ticks} ticks")
    print("work: " + ", ".join(f"{job} on {where}" for job, where, _ in world.where_work_runs()))
    print(f"step     mean {step.mean():6.2f} ms   max {step.max():6.2f} ms")
    print(f"gravity  mean {grav.mean():6.2f} ms   max {grav.max():6.2f} ms")
    print(f"render   mean {render_ms:6.2f} ms (kernel + blit + scale)")
    print(f"awake    mean {int(np.mean(awake)):,}   last {awake[-1]:,}")
    print(f"total mass {world.total_mass():,}")


def main():
    args = parse_args()
    pw, ph = (int(v) for v in args.size.lower().split("x"))
    t = time.perf_counter()
    print("compiling kernels (first run only, cached afterwards)...", end=" ", flush=True)
    warmup(cores=not args.cpu)
    print(f"{time.perf_counter() - t:.1f} s")
    world = World(pw, ph, args.cell, seed=args.seed)
    accelerate(world, args)
    PRESETS[args.preset](world, args.particles)

    if args.benchmark is not None:
        benchmark(world, args.benchmark)
        return

    from sv.app import App   # imported late so --benchmark works without a display
    App(world, fullscreen=args.fullscreen).run()


if __name__ == "__main__":
    main()
