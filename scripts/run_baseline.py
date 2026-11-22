#!/usr/bin/env python3
"""Run a command repeatedly and record wall time and peak memory as JSON.

Usage:
    python run_baseline.py --name legacy --runs 7 --warmup 2 --out .rust-opt/baseline -- python app.py data.csv

Everything after `--` is the command. Output: <out>/<name>.json
Peak RSS uses os.wait4 on Unix and Win32 GetProcessMemoryInfo (ctypes) on Windows.
"""
import argparse
import ctypes
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path


def _win32_peak_rss_kb(handle):
    """Query PeakWorkingSetSize in KiB from a Windows process handle (works after exit)."""
    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_uint32),
            ("PageFaultCount", ctypes.c_uint32),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    try:
        fn = ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), ctypes.c_uint32]
        fn.restype = ctypes.c_int
        if fn(int(handle), ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize // 1024 if counters.PeakWorkingSetSize else None
    except Exception:
        return None
    return None


def run_once(cmd):
    start = time.perf_counter()
    rss_kb = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        sys.exit(f"error: failed to launch command {cmd!r}: {exc}")
    if hasattr(os, "wait4"):
        _, status, usage = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
        rss_kb = usage.ru_maxrss // 1024 if sys.platform == "darwin" else usage.ru_maxrss
        returncode = proc.returncode
    elif sys.platform == "win32":
        proc.wait()
        rss_kb = _win32_peak_rss_kb(proc._handle)
        returncode = proc.returncode
    else:
        peak = 0
        try:
            import psutil
            ps = psutil.Process(proc.pid)
            while proc.poll() is None:
                try:
                    peak = max(peak, ps.memory_info().rss)
                except psutil.Error:
                    break
                time.sleep(0.01)
            rss_kb = peak // 1024 if peak else None
        except ImportError:
            pass
        proc.wait()
        returncode = proc.returncode
    elapsed = time.perf_counter() - start
    return elapsed, rss_kb, returncode


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        sys.exit("error: separate the command with `--`")
    idx = argv.index("--")
    own, cmd = argv[:idx], argv[idx + 1:]
    if not cmd:
        sys.exit("error: no command given after `--`")

    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--out", default=".rust-opt/baseline")
    ap.add_argument("--max-rel-stdev", type=float, default=0.10,
                    help="warn when stdev/mean exceeds this (default 0.10)")
    args = ap.parse_args(own)

    for i in range(args.warmup):
        _, _, rc = run_once(cmd)
        if rc != 0:
            sys.exit(f"error: command failed during warmup (exit {rc}). Fix the command first.")

    times, rss = [], []
    for i in range(args.runs):
        t, r, rc = run_once(cmd)
        if rc != 0:
            sys.exit(f"error: run {i + 1} failed with exit code {rc}")
        times.append(t)
        if r is not None:
            rss.append(r)
        print(f"run {i + 1}/{args.runs}: {t:.4f}s" + (f", peak {r / 1024:.1f} MB" if r else ""))

    mean = statistics.mean(times)
    stdev = statistics.stdev(times) if len(times) > 1 else 0.0
    result = {
        "name": args.name,
        "command": cmd,
        "runs": args.runs,
        "warmup": args.warmup,
        "times_s": times,
        "mean_s": mean,
        "median_s": statistics.median(times),
        "min_s": min(times),
        "max_s": max(times),
        "stdev_s": stdev,
        "rel_stdev": stdev / mean if mean else 0.0,
        "peak_rss_kb_median": int(statistics.median(rss)) if rss else None,
        "peak_rss_kb_max": max(rss) if rss else None,
        "env": {"platform": platform.platform(), "python": platform.python_version(),
                "cpu_count": os.cpu_count()},
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.name}.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nmedian {result['median_s']:.4f}s  mean {mean:.4f}s  rel-stdev {result['rel_stdev']:.1%}")
    if result["rel_stdev"] > args.max_rel_stdev:
        print("WARNING: noisy baseline. Close other programs, raise --runs, or fix the workload "
              "(see references/benchmarking.md) before trusting comparisons.")
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
