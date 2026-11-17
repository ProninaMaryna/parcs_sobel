# -*- coding: utf-8 -*-
"""
Run the whole benchmark against a live PARCS master from your own PC.

For every N in --workers it enables the first N workers (disables the rest)
through the PARCS REST API, submits solver.py + input, waits for the job,
downloads the output and records the timings the solver wrote into it.

    python tools/run_benchmark.py http://MASTER_PUBLIC_IP:8080 inputs/synth_2000.txt --workers 0 1 2 3 4 --runs 2

N = 0 is the sequential baseline: the master computes the whole image alone.

Results: results/cloud.csv (+ outputs in results/cloud_outputs/).
"""
import argparse
import csv
import os
import re
import sys
import time

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def workers(base):
    r = requests.get(base + "/api/worker", timeout=20)
    r.raise_for_status()
    return sorted(r.json()["workers"], key=lambda w: w["id"])


def use_workers(base, n):
    ws = workers(base)
    if len(ws) < n:
        sys.exit("Master sees only %d workers, need %d (check the Nodes page)" % (len(ws), n))
    for i, w in enumerate(ws):
        state = "enable" if i < n else "disable"
        requests.post("%s/api/worker/%d/%s" % (base, w["id"], state), timeout=20).raise_for_status()
    return ws


def job_ids(base):
    html = requests.get(base + "/jobs", timeout=20).text
    return [int(x) for x in re.findall(r'data-job-id="(\d+)"', html)]


def job_block(base, job_id):
    html = requests.get(base + "/jobs", timeout=20).text
    m = re.search(r'data-job-id="%d"(.*?)(?=data-job-id=|\Z)' % job_id, html, re.S)
    return m.group(1) if m else ""


def input_bytes(input_file, n):
    """Input with a "# workers N" header line (N = 0 -> sequential run on master)."""
    with open(input_file, "rb") as f:
        data = f.read()
    lines = [l for l in data.split(b"\n", 12)]
    head = [l for l in lines[:-1] if not l.strip().lower().startswith(b"# workers")]
    return b"\n".join([head[0], b"# workers %d" % n] + head[1:] + [lines[-1]])


def submit(base, name, solver, input_file, n):
    before = set(job_ids(base))
    with open(solver, "rb") as s:
        requests.post(base + "/api/job", data={"job_name": name},
                      files={"solution_file": ("solver.py", s),
                             "input_file": ("input.txt", input_bytes(input_file, n))},
                      timeout=600).raise_for_status()
    new = sorted(set(job_ids(base)) - before)
    if not new:
        sys.exit("Job was not created")
    return new[-1]


def wait(base, job_id, timeout=3600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = requests.get("%s/api/job/%d/output" % (base, job_id), timeout=60)
        if r.status_code == 200:
            return r.text
        block = job_block(base, job_id)
        if "error-text" in block:
            reason = re.search(r'error-text"\s*>\s*(.*?)</span>', block, re.S)
            sys.exit("Job %d FAILED: %s" % (job_id, reason.group(1).strip() if reason else "?"))
        time.sleep(2)
    sys.exit("Timeout waiting for job %d" % job_id)


def duration_ui(base, job_id):
    block = job_block(base, job_id)
    m = re.search(r"Duration:.*?i-attr-value[^>]*>\s*([\d:]+)", block, re.S)
    if not m:
        return None
    h, mi, s = (int(x) for x in m.group(1).split(":"))
    return h * 3600 + mi * 60 + s


def stat(output, key):
    m = re.search(r"#\s*%s=([\d.]+)" % key, output)
    return float(m.group(1)) if m else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("master", help="http://MASTER_IP:8080")
    p.add_argument("input")
    p.add_argument("--solver", default=os.path.join(ROOT, "solver.py"))
    p.add_argument("--workers", type=int, nargs="+", default=[0, 1, 2, 3, 4], help="0 = sequential run on master")
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--csv", default=os.path.join(ROOT, "results", "cloud.csv"))
    a = p.parse_args()
    base = a.master.rstrip("/")

    ws = workers(base)
    print("Workers registered on master: %d" % len(ws))
    for w in ws:
        print("  #%d  %s:%d  %s" % (w["id"], w["ip"], w["port"], w.get("info")))

    outdir = os.path.join(ROOT, "results", "cloud_outputs")
    os.makedirs(outdir, exist_ok=True)
    rows = []
    try:
        for n in a.workers:
            if n > 0:
                use_workers(base, n)
            for run in range(1, a.runs + 1):
                name = "sobel_seq_run%d" % run if n == 0 else "sobel_w%d_run%d" % (n, run)
                jid = submit(base, name, a.solver, a.input, n)
                print("N=%d run %d: job #%d submitted ..." % (n, run, jid), end=" ", flush=True)
                out = wait(base, jid)
                with open(os.path.join(outdir, "job%d_w%d_run%d.txt" % (jid, n, run)), "w") as f:
                    f.write(out)
                row = {"workers": n, "run": run, "job": jid,
                       "time_s": stat(out, "time_parallel_section"),
                       "read_s": stat(out, "time_read_input"),
                       "max_worker_s": stat(out, "max_worker_compute"),
                       "ui_duration_s": duration_ui(base, jid)}
                used = re.search(r"workers=(\d+)", out)
                if used and int(used.group(1)) != n:
                    print("\n  WARNING: solver used %s workers" % used.group(1))
                rows.append(row)
                print("parallel=%.2f s, slowest worker=%.2f s, UI duration=%s s"
                      % (row["time_s"], row["max_worker_s"], row["ui_duration_s"]))
    finally:
        for w in workers(base):  # leave everything enabled
            requests.post("%s/api/worker/%d/enable" % (base, w["id"]), timeout=20)

    with open(a.csv, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print("\nsaved", a.csv)


if __name__ == "__main__":
    main()
