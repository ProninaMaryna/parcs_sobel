# -*- coding: utf-8 -*-
"""
Make a PARCS input file (ASCII PGM, P2) from a photo, or a synthetic test image.

    python tools/make_input.py photo.jpg inputs/photo_2000.txt --width 2000
    python tools/make_input.py --synthetic 2000x2000 inputs/synth_2000.txt
    ... --workers 2     # add "# workers 2" line: solver uses only 2 workers
"""
import argparse
import math
import random


def synthetic(w, h, seed=42):
    """Shapes + smooth background + noise: plenty of edges to detect."""
    from PIL import Image, ImageDraw, ImageFilter
    rnd = random.Random(seed)
    bg = bytearray(int(128 + 60 * math.sin(x / 37.0) * math.cos(y / 53.0))
                   for y in range(h) for x in range(w))
    im = Image.frombytes("L", (w, h), bytes(bg))
    d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = rnd.uniform(0, w), rnd.uniform(0, h)
        r = rnd.uniform(0.02, 0.15) * min(w, h)
        if rnd.random() < 0.5:
            d.ellipse([x - r, y - r, x + r, y + r], fill=rnd.randint(0, 255))
        else:
            d.rectangle([x - r, y - r * 0.6, x + r * 1.5, y + r], fill=rnd.randint(0, 255))
    noise = Image.effect_noise((w, h), 12).filter(ImageFilter.GaussianBlur(0.5))
    im = Image.blend(im, noise, 0.08)
    return bytearray(im.tobytes())


def write_pgm(path, w, h, pixels, workers=0):
    with open(path, "w") as f:
        f.write("P2\n")
        if workers:
            f.write("# workers %d\n" % workers)
        f.write("%d %d\n255\n" % (w, h))
        for y in range(h):
            f.write(" ".join(str(v) for v in pixels[y * w:(y + 1) * w]))
            f.write("\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src", nargs="?", help="source image (jpg/png/...)")
    p.add_argument("dst")
    p.add_argument("--width", type=int, default=0, help="resize to this width (keeps aspect)")
    p.add_argument("--synthetic", help="WxH, generate a test image instead of reading src")
    p.add_argument("--workers", type=int, default=0)
    a = p.parse_args()

    if a.synthetic:
        w, h = (int(v) for v in a.synthetic.lower().split("x"))
        pixels = synthetic(w, h)
    else:
        from PIL import Image  # pip install pillow
        im = Image.open(a.src).convert("L")
        if a.width:
            im = im.resize((a.width, round(im.height * a.width / im.width)), Image.LANCZOS)
        w, h = im.size
        pixels = bytearray(im.tobytes())
    write_pgm(a.dst, w, h, pixels, a.workers)
    print("written %s (%dx%d)" % (a.dst, w, h))


if __name__ == "__main__":
    main()
