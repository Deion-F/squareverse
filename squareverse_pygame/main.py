#!/usr/bin/env python3
"""Squareverse (pygame edition) entry point.

Prompts for universe size and grid spacing like the original squareverse_maker.py unless given on the command line.
"""

import argparse
import os
import random
import sys
import time

from squareverse import config
from squareverse.universe import Squareverse


def valid_grid_spacings(size_px):
    # same rule as the original menu
    return [i for i in range(10, size_px // 10 + 1) if size_px % i == 0 and (size_px / i) % 2 == 0]


def prompt_size():
    while True:
        answer = input("\n\nSelect Squareverse size (1 - 10): ").strip()
        if not answer:
            return config.DEFAULT_SIZE
        try:
            value = float(answer)
        except ValueError:
            print("\n\nPlease choose a valid size for Squareverse")
            continue
        if value % 1 != 0:
            print("\n\nPlease choose a whole number for Squareverse size")
        elif 1 <= value <= 10:
            return int(value)
        else:
            print("\n\nPlease choose a valid size for Squareverse")


def prompt_spacing(size_px):
    spacings = valid_grid_spacings(size_px)
    default = config.DEFAULT_GRID_SPACING if config.DEFAULT_GRID_SPACING in spacings else spacings[len(spacings) // 2]
    print(f"\n\nList of valid grid spacing {spacings}")
    while True:
        answer = input(f"\n\nSelect Squareverse grid spacing (default {default}): ").strip()
        if not answer:
            return default
        if answer.isdigit() and int(answer) in spacings:
            return int(answer)
        print(f"\n\nPlease choose one of {spacings}")


def parse_args():
    p = argparse.ArgumentParser(description="Squareverse - Squares with child-universe mass, pushing and crushing.")
    p.add_argument("--size", type=int, choices=range(1, 11), metavar="1-10", help="universe size (x 100 px)")
    p.add_argument("--spacing", type=int, help="grid spacing in px")
    p.add_argument("--squares", help="Squares to spawn at start: a number, m (max), h (1/2 max) or q (1/4 max)")
    p.add_argument("--seed", type=int, help="random seed for a reproducible run")
    p.add_argument("--tps", type=int, help=f"ticks per second, 0 = max (default {config.DEFAULT_TICKS_PER_SECOND})")
    p.add_argument("--no-smooth", action="store_true", help="disable interpolation between ticks")
    p.add_argument("--diagonals", action="store_true", help="allow the 4 diagonal directions (original HEAD had 8)")
    p.add_argument("--no-crush", action="store_true", help="trapped Squares stay (white outline) instead of dying")
    p.add_argument("--no-prompt", action="store_true", help="use defaults instead of asking for size/spacing")
    p.add_argument("--benchmark", type=int, metavar="TICKS", help="run TICKS ticks headless and print timings")
    return p.parse_args()


def benchmark(universe, ticks):
    times = []
    start_population = len(universe.squares)
    for _ in range(ticks):
        t = time.perf_counter()
        universe.tick()
        times.append((time.perf_counter() - t) * 1000)
    steady = times[1:] or times
    print(f"{start_population} Squares on a {universe.n}x{universe.n} grid, {ticks} ticks")
    print(f"first tick {times[0]:.1f} ms (includes {config.SPAWN_CHILD_CYCLES} child cycles per Square)")
    print(f"steady avg {sum(steady) / len(steady):.2f} ms   max {max(steady):.2f} ms")
    print(f"Squares remaining: {len(universe.squares)}")


def main():
    args = parse_args()
    interactive = sys.stdin.isatty() and not args.no_prompt and args.benchmark is None
    size = args.size or (prompt_size() if interactive else config.DEFAULT_SIZE)
    size_px = size * 100
    spacings = valid_grid_spacings(size_px)
    if args.spacing is not None:
        spacing = args.spacing
        if size_px % spacing:
            sys.exit(f"grid spacing must divide {size_px}; valid choices: {spacings}")
    elif interactive:
        spacing = prompt_spacing(size_px)
    else:
        spacing = config.DEFAULT_GRID_SPACING if size_px % config.DEFAULT_GRID_SPACING == 0 else spacings[0]

    rng = random.Random(args.seed)
    universe = Squareverse(size_px, spacing, rng,
                           diagonal_moves=args.diagonals or None,
                           crush_when_trapped=False if args.no_crush else None)
    if args.squares:
        if not universe.spawn(universe.spawn_amount(args.squares)):
            print("INFO: There are not enough empty grids remaining")

    if args.benchmark is not None:
        benchmark(universe, args.benchmark)
        return

    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    from squareverse.app import App   # imported late so --benchmark works without a display

    title = f"Squareverse #{rng.randint(0, 100)}"
    App(universe, title, ticks_per_second=args.tps, smooth=False if args.no_smooth else None).run()


if __name__ == "__main__":
    main()
