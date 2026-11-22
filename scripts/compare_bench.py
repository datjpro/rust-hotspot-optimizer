#!/usr/bin/env python3
"""Compare two run_baseline.py results (before vs after).

Usage:
    python compare_bench.py before.json after.json [--min-speedup 1.5] [--min-ram-reduction 0.2] [--md out.md]

Exit codes: 0 = threshold met, 1 = threshold missed, 2 = bad input.
"""
import argparse
import json
import sys
from pathlib import Path


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["times_s"]
        return data
    except Exception as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--min-speedup", type=float, default=1.5)
    ap.add_argument("--min-ram-reduction", type=float, default=0.20,
                    help="fraction, e.g. 0.2 = 20%% less peak RAM")
    ap.add_argument("--md", help="also write a markdown table here")
    args = ap.parse_args()

    b, a = load(args.before), load(args.after)
    bm, am = b["median_s"], a["median_s"]
    speedup = bm / am if am else float("inf")

    # Noise check: if the slowest "after" run is not faster than the fastest "before" run,
    # the ranges overlap and the gain is not clearly outside run-to-run noise.
    overlap = max(a["times_s"]) >= min(b["times_s"])
    noisy = b.get("rel_stdev", 0) > 0.10 or a.get("rel_stdev", 0) > 0.10

    ram_b, ram_a = b.get("peak_rss_kb_median"), a.get("peak_rss_kb_median")
    ram_red = (1 - ram_a / ram_b) if ram_b and ram_a else None

    speed_ok = speedup >= args.min_speedup and not (overlap and speedup < 2.0)
    ram_ok = ram_red is not None and ram_red >= args.min_ram_reduction
    verdict_ok = speed_ok or ram_ok

    lines = [
        "| Metric | Before | After | Change |",
        "|---|---|---|---|",
        f"| Median time | {bm:.4f} s | {am:.4f} s | {speedup:.2f}x faster |",
        f"| Time range | {b['min_s']:.4f}-{b['max_s']:.4f} s | {a['min_s']:.4f}-{a['max_s']:.4f} s | "
        f"{'ranges overlap' if overlap else 'ranges separate'} |",
        f"| Rel. stdev | {b.get('rel_stdev', 0):.1%} | {a.get('rel_stdev', 0):.1%} | |",
    ]
    if ram_b and ram_a:
        lines.append(f"| Peak RAM (median) | {ram_b / 1024:.1f} MB | {ram_a / 1024:.1f} MB | "
                     f"{ram_red:+.0%} {'less' if ram_red >= 0 else 'more'} |")
    else:
        lines.append("| Peak RAM | n/a | n/a | not measured |")
    table = "\n".join(lines)
    print(table)
    print()
    if noisy:
        print("NOTE: at least one side has >10% relative stdev; treat the numbers as indicative only.")
    if overlap and speedup < 2.0:
        print("NOTE: before/after time ranges overlap; the gain may be within noise. Re-run with more runs.")
    print(f"Speed threshold {args.min_speedup}x: {'MET' if speed_ok else 'MISSED'}"
          f" | RAM threshold {args.min_ram_reduction:.0%}: "
          f"{'MET' if ram_ok else ('MISSED' if ram_red is not None else 'not measured')}")
    print("VERDICT:", "KEEP (if parity passes)" if verdict_ok
          else "REVERT or investigate FFI/conversion overhead")
    if args.md:
        md_path = Path(args.md)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(table + "\n", encoding="utf-8")
    sys.exit(0 if verdict_ok else 1)


if __name__ == "__main__":
    main()
