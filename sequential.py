# -*- coding: utf-8 -*-
"""
Sequential (single-process) version of the same algorithm - baseline for
comparison.  Optionally checks that a parallel result is bit-identical.

    python sequential.py input.txt output_seq.txt [--check output_parallel.txt]
"""
from __future__ import print_function

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from solver import Solver  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("output", nargs="?", default="output_seq.txt")
    p.add_argument("--check", help="parallel output to compare with")
    a = p.parse_args()

    t0 = time.time()
    w, h, pixels, _ = Solver.parse_pgm(a.input)
    t1 = time.time()
    out = Solver.process_rows(pixels, w, h, 0, h, 0, h)
    t2 = time.time()
    stats = ["sequential  image=%dx%d" % (w, h),
             "time_read_input=%.3f s" % (t1 - t0),
             "time_compute=%.3f s" % (t2 - t1)]
    Solver(None, None, a.output).write_output(w, h, out, stats)
    print("\n".join(stats))

    if a.check:
        w2, h2, other, _ = Solver.parse_pgm(a.check)
        same = (w2, h2) == (w, h) and other == out
        print("check vs %s: %s" % (a.check, "IDENTICAL" if same else "DIFFERENT"))
        sys.exit(0 if same else 1)


if __name__ == "__main__":
    main()
