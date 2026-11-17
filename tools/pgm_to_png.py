# -*- coding: utf-8 -*-
"""
Convert PARCS input/output (ASCII PGM with "#" comments) to PNG.

    python tools/pgm_to_png.py output.txt edges.png
    python tools/pgm_to_png.py input.txt before.png output.txt after.png --side-by-side compare.png
"""
import argparse
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from solver import Solver  # noqa: E402


def load(path):
    w, h, pixels, _ = Solver.parse_pgm(path)
    return Image.frombytes("L", (w, h), bytes(pixels))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pairs", nargs="+", help="pgm png [pgm png ...]")
    p.add_argument("--side-by-side", help="also save all images next to each other")
    a = p.parse_args()
    images = []
    for src, dst in zip(a.pairs[::2], a.pairs[1::2]):
        im = load(src)
        im.save(dst)
        images.append(im)
        print("saved", dst)
    if a.side_by_side and images:
        w = sum(i.width for i in images)
        h = max(i.height for i in images)
        canvas = Image.new("L", (w, h), 0)
        x = 0
        for im in images:
            canvas.paste(im, (x, 0))
            x += im.width
        canvas.save(a.side_by_side)
        print("saved", a.side_by_side)


if __name__ == "__main__":
    main()
