# -*- coding: utf-8 -*-
"""
PARCS-Python solution: parallel edge detection (Gaussian blur 5x5 + Sobel operator).

Topic 5.3 "Parallel edge detection" (Sobel).

Input  : grayscale image in ASCII PGM format (P2), uploaded as the "Input File".
         Optional comment line in the header:  "# workers K"  -> use only the first K workers;
         "# workers 0" -> sequential baseline computed by the master alone.
Output : ASCII PGM (P2) with the gradient magnitude image. Timing info is written
         as "#" comment lines in the header (valid PGM, any viewer ignores them).

Idea   : the image is split into N horizontal strips (N = number of workers).
         Each worker receives its strip plus a 3-row "halo" above and below
         (2 rows for the 5x5 Gaussian + 1 row for the 3x3 Sobel), so it can
         compute its rows completely independently.  Master only splits the
         image, sends strips, and glues the results back together.

The code runs both on Python 2.7 (the hummer12007/parcs-node docker image)
and on Python 3 (local testing).
"""
from __future__ import division, print_function

import binascii
import sys
import time

try:
    from Pyro4 import expose
except ImportError:  # local run without Pyro4 installed
    def expose(f):
        return f

HALO = 3  # 2 rows for Gaussian 5x5 + 1 row for Sobel 3x3

# 5x5 Gaussian kernel (sigma ~ 1.0), sum = 273
GAUSS = (
    (1, 4, 7, 4, 1),
    (4, 16, 26, 16, 4),
    (7, 26, 41, 26, 7),
    (4, 16, 26, 16, 4),
    (1, 4, 7, 4, 1),
)
GAUSS_SUM = 273


def _native_str(s):
    """Pyro/serpent may hand us unicode (py2) or bytes (py3); normalize to native str."""
    if isinstance(s, str):
        return s
    if isinstance(s, dict) and s.get('encoding') == 'base64':  # serpent-encoded bytes
        import base64
        s = base64.b64decode(s['data'])
    if sys.version_info[0] == 2:
        return s.encode('ascii')
    return s.decode('ascii')


def _pack(pixels):
    """bytearray -> compact ASCII hex string (safe for any Pyro serializer)."""
    return _native_str(binascii.hexlify(bytes(pixels)))


def _unpack(s):
    return bytearray(binascii.unhexlify(_native_str(s)))


class Solver:
    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name
        self.workers = workers
        self.has_workers_line = False
        print("Inited")

    # ------------------------------------------------------------------ master
    def solve(self):
        print("Job Started")
        t0 = time.time()
        width, height, pixels, limit = self.read_input()
        t_read = time.time()

        if limit == 0 and self.has_workers_line:
            # "# workers 0": sequential baseline, master computes the whole image alone
            result = Solver.process_rows(pixels, width, height, 0, height, 0, height)
            t_done = time.time()
            stats = [
                "parcs-sobel  image=%dx%d  workers=0 (sequential on master)" % (width, height),
                "time_read_input=%.3f s" % (t_read - t0),
                "time_parallel_section=%.3f s (sequential compute)" % (t_done - t_read),
                "worker_compute_times=-",
                "max_worker_compute=%.3f s" % (t_done - t_read),
            ]
            self.write_output(width, height, result, stats)
            print("\n".join(stats))
            print("Job Finished")
            return

        workers = self.workers
        if limit and 0 < limit < len(workers):
            workers = workers[:limit]
        n = len(workers)
        print("Workers %d (registered %d), image %dx%d" % (n, len(self.workers), width, height))

        # split rows into n almost equal strips
        bounds = []
        base, extra = divmod(height, n)
        start = 0
        for i in range(n):
            end = start + base + (1 if i < extra else 0)
            bounds.append((start, end))
            start = end

        # map: send every worker its strip + halo; calls are asynchronous
        mapped = []
        for i in range(n):
            a, b = bounds[i]
            lo = max(0, a - HALO)
            hi = min(height, b + HALO)
            chunk = _pack(pixels[lo * width:hi * width])
            mapped.append(workers[i].mymap(chunk, width, height, lo, hi, a, b))
        t_sent = time.time()

        # reduce: wait for all futures and glue the strips
        result, worker_times = self.myreduce(mapped)
        t_done = time.time()

        stats = [
            "parcs-sobel  image=%dx%d  workers=%d" % (width, height, n),
            "time_read_input=%.3f s" % (t_read - t0),
            "time_parallel_section=%.3f s (send+compute+gather)" % (t_done - t_read),
            "worker_compute_times=%s" % ", ".join("%.3f" % x for x in worker_times),
            "max_worker_compute=%.3f s" % max(worker_times),
        ]
        self.write_output(width, height, result, stats)
        print("\n".join(stats))
        print("Job Finished")

    # ------------------------------------------------------------------ worker
    @staticmethod
    @expose
    def mymap(chunk, width, height, lo, hi, a, b):
        """Compute Gaussian blur + Sobel magnitude for global rows [a, b).

        chunk holds global rows [lo, hi) (strip + halo).  Image borders are
        handled by clamping coordinates (replicate padding), exactly as the
        sequential version does, so the result is bit-identical.
        """
        t = time.time()
        src = _unpack(chunk)
        out = Solver.process_rows(src, width, height, lo, hi, a, b)
        return [_pack(out), time.time() - t]

    @staticmethod
    @expose
    def myreduce(mapped):
        parts = []
        times = []
        for future in mapped:
            packed, t = future.value
            parts.append(_unpack(packed))
            times.append(t)
        result = bytearray()
        for p in parts:
            result += p
        return result, times

    # ------------------------------------------------------------- algorithm
    @staticmethod
    def process_rows(src, width, height, lo, hi, a, b):
        """Pure algorithm, shared by the parallel and the sequential version."""
        last_row = height - 1
        last_col = width - 1

        # column index tables with replicate padding
        xs = range(width)
        cols5 = [[min(max(x + d, 0), last_col) for d in (-2, -1, 0, 1, 2)] for x in xs]

        # 1) Gaussian blur for rows [ba, bb) = rows needed by Sobel
        ba = max(0, a - 1)
        bb = min(height, b + 1)
        blurred = bytearray((bb - ba) * width)
        for y in range(ba, bb):
            rows = []
            for d in (-2, -1, 0, 1, 2):
                yy = y + d
                yy = 0 if yy < 0 else (last_row if yy > last_row else yy)
                off = (yy - lo) * width
                rows.append(src[off:off + width])
            r0, r1, r2, r3, r4 = rows
            k0, k1, k2, k3, k4 = GAUSS
            o = (y - ba) * width
            for x in xs:
                c0, c1, c2, c3, c4 = cols5[x]
                s = (k0[0] * r0[c0] + k0[1] * r0[c1] + k0[2] * r0[c2] + k0[3] * r0[c3] + k0[4] * r0[c4] +
                     k1[0] * r1[c0] + k1[1] * r1[c1] + k1[2] * r1[c2] + k1[3] * r1[c3] + k1[4] * r1[c4] +
                     k2[0] * r2[c0] + k2[1] * r2[c1] + k2[2] * r2[c2] + k2[3] * r2[c3] + k2[4] * r2[c4] +
                     k3[0] * r3[c0] + k3[1] * r3[c1] + k3[2] * r3[c2] + k3[3] * r3[c3] + k3[4] * r3[c4] +
                     k4[0] * r4[c0] + k4[1] * r4[c1] + k4[2] * r4[c2] + k4[3] * r4[c3] + k4[4] * r4[c4])
                blurred[o + x] = (s + GAUSS_SUM // 2) // GAUSS_SUM

        # 2) Sobel operator on the blurred rows -> gradient magnitude
        #    Gx = [-1 0 1; -2 0 2; -1 0 1],  Gy = [-1 -2 -1; 0 0 0; 1 2 1]
        out = bytearray((b - a) * width)
        for y in range(a, b):
            ym = max(y - 1, 0) - ba
            yp = min(y + 1, last_row) - ba
            y0 = y - ba
            up = blurred[ym * width:(ym + 1) * width]
            mid = blurred[y0 * width:(y0 + 1) * width]
            dn = blurred[yp * width:(yp + 1) * width]
            o = (y - a) * width
            for x in xs:
                xl = x - 1 if x > 0 else 0
                xr = x + 1 if x < last_col else last_col
                gx = (up[xr] + 2 * mid[xr] + dn[xr]) - (up[xl] + 2 * mid[xl] + dn[xl])
                gy = (dn[xl] + 2 * dn[x] + dn[xr]) - (up[xl] + 2 * up[x] + up[xr])
                m = int((gx * gx + gy * gy) ** 0.5)
                out[o + x] = 255 if m > 255 else m
        return out

    # -------------------------------------------------------------------- I/O
    def read_input(self):
        self.has_workers_line = Solver.workers_line(self.input_file_name)
        return Solver.parse_pgm(self.input_file_name)

    @staticmethod
    def workers_line(path):
        """True if the header contains a "# workers K" line (K = 0 -> sequential run)."""
        f = open(path, 'r')
        found = False
        for _ in range(10):
            line = f.readline().strip()
            if line.startswith('#') and line[1:].split()[:1] == ['workers']:
                found = True
                break
        f.close()
        return found

    @staticmethod
    def parse_pgm(path):
        f = open(path, 'r')
        tokens = []
        limit = 0
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                parts = line[1:].split()
                if len(parts) == 2 and parts[0].lower() == 'workers':
                    limit = int(parts[1])
                continue
            tokens.extend(line.split())
        f.close()
        if tokens[0] != 'P2':
            raise ValueError("Input must be an ASCII PGM (P2) file")
        width, height, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
        data = tokens[4:4 + width * height]
        if len(data) != width * height:
            raise ValueError("Expected %d pixels, got %d" % (width * height, len(data)))
        if maxval == 255:
            pixels = bytearray(int(v) for v in data)
        else:
            pixels = bytearray(int(v) * 255 // maxval for v in data)
        return width, height, pixels, limit

    def write_output(self, width, height, pixels, stats):
        f = open(self.output_file_name, 'w')
        f.write("P2\n")
        for s in stats:
            f.write("# %s\n" % s)
        f.write("%d %d\n255\n" % (width, height))
        for y in range(height):
            row = pixels[y * width:(y + 1) * width]
            f.write(" ".join(str(v) for v in row))
            f.write("\n")
        f.close()
        print("output done")
