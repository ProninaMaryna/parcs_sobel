# -*- coding: utf-8 -*-
"""
Table + chart "execution time vs number of workers" from a CSV.

CSV columns: workers,time_s   (several rows per worker count are averaged; extra columns ignored)

    python tools/plot_results.py results/cloud.csv results/cloud_chart.png --sequential 41.2
"""
import argparse
import csv
import sys
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv")
    p.add_argument("png")
    p.add_argument("--sequential", type=float, help="sequential time, s (baseline for speedup)")
    p.add_argument("--title", default="PARCS-Python: Gaussian 5x5 + Sobel, 2000x2000")
    a = p.parse_args()

    runs = defaultdict(list)
    with open(a.csv) as f:
        for row in csv.DictReader(f):
            runs[int(row["workers"])].append(float(row["time_s"]))
    seq_runs = runs.pop(0, [])  # workers=0 rows = sequential baseline measured on master
    if seq_runs and not a.sequential:
        a.sequential = sum(seq_runs) / len(seq_runs)
        print("sequential (workers=0) runs:", ", ".join("%.2f" % x for x in seq_runs))
    ns = sorted(runs)
    ts = [sum(runs[n]) / len(runs[n]) for n in ns]
    base = a.sequential or ts[0] * ns[0]
    base_name = "T_послідовний" if a.sequential else "T_1"

    print("| Конфігурація | " + " | ".join("Запуск %d, с" % (i + 1) for i in range(max(map(len, runs.values()))))
          + " | Середнє, с | Прискорення S | Ефективність E |")
    print("|---|" + "---:|" * (max(map(len, runs.values())) + 3))
    if a.sequential:
        k = max(map(len, runs.values()))
        cells = ["%.2f" % x for x in seq_runs[:k]] + ["—"] * (k - len(seq_runs[:k]))
        print("| Послідовний | %s | %.2f | 1.00 | — |" % (" | ".join(cells), base))
    for n, t in zip(ns, ts):
        cells = " | ".join("%.2f" % x for x in runs[n])
        print("| %d воркер%s | %s | %.2f | %.2f | %.0f%% |"
              % (n, "" if n == 1 else "и", cells, t, base / t, 100 * base / t / n))

    fig, ax = plt.subplots(figsize=(7.5, 4.3), dpi=150)
    for n in ns:
        ax.scatter([n] * len(runs[n]), runs[n], s=28, facecolors="none", edgecolors="#9aa5b1", zorder=3,
                   label="окремий запуск" if n == ns[0] else None)
    ax.plot(ns, ts, "o-", color="#2a6fdb", lw=2.2, zorder=4, label="середнє")
    ax.plot(ns, [base / n for n in ns], "--", color="gray", lw=1.2,
            label="ідеал: %s / N" % base_name)
    if a.sequential:
        ax.axhline(a.sequential, color="#e07b00", lw=1, ls=":", label="послідовний: %.1f с" % a.sequential)
    for n, t in zip(ns, ts):
        ax.annotate("%.1f с\nS=%.2f" % (t, base / t), (n, t), textcoords="offset points", xytext=(0, 10),
                    ha="center", fontsize=8.5, color="#2a6fdb")
    ax.set_xlabel("Кількість воркерів")
    ax.set_ylabel("Час, с")
    ax.set_xticks(ns)
    ax.set_ylim(0, max(ts + [base]) * 1.25)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    ax.set_title(a.title)
    fig.tight_layout()
    fig.savefig(a.png)
    print("saved", a.png)


if __name__ == "__main__":
    main()
