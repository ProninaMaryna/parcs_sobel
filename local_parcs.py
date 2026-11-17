# -*- coding: utf-8 -*-
"""
Local emulator of the PARCS-Python master: runs solver.py with N worker
processes on this machine, so the solution can be debugged before it goes
to the cloud.  Each fake worker is a separate OS process; a remote call
returns a future with a ``.value`` attribute, just like a Pyro4 async proxy.

    python local_parcs.py input.txt output.txt --workers 4
    python local_parcs.py input.txt --bench 1 2 3 4      # timing table
"""
from __future__ import print_function

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import solver  # noqa: E402


def _remote_call(name, args):
    return getattr(solver.Solver, name)(*args)


class _Future(object):
    def __init__(self, fut):
        self._fut = fut

    @property
    def value(self):
        return self._fut.result()


class FakeWorker(object):
    def __init__(self, executor):
        self._ex = executor

    def __getattr__(self, name):
        def call(*args):
            return _Future(self._ex.submit(_remote_call, name, args))
        return call


def run(input_file, output_file, n):
    executors = [ProcessPoolExecutor(max_workers=1) for _ in range(n)]
    try:
        # warm up processes so process start-up is not measured
        for ex in executors:
            ex.submit(int, 0).result()
        workers = [FakeWorker(ex) for ex in executors]
        s = solver.Solver(workers, input_file, output_file)
        t = time.time()
        s.solve()
        return time.time() - t
    finally:
        for ex in executors:
            ex.shutdown()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("output", nargs="?", default="output_local.txt")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--bench", type=int, nargs="*", help="list of worker counts to benchmark")
    p.add_argument("--csv", default=None, help="append benchmark rows to this CSV")
    a = p.parse_args()

    if not a.bench:
        print("Total time: %.3f s" % run(a.input, a.output, a.workers))
        return

    rows = []
    for n in a.bench:
        t = run(a.input, a.output, n)
        rows.append((n, t))
        print(">>> workers=%d  time=%.3f s" % (n, t))
    t1 = rows[0][1]
    print("\nworkers | time, s | speedup | efficiency")
    for n, t in rows:
        print("%7d | %7.3f | %7.2f | %9.2f" % (n, t, t1 / t, t1 / t / n))
    if a.csv:
        new = not os.path.exists(a.csv)
        with open(a.csv, "a") as f:
            if new:
                f.write("workers,time_s\n")
            for n, t in rows:
                f.write("%d,%.3f\n" % (n, t))


if __name__ == "__main__":
    main()
