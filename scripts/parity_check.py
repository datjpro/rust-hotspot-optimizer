#!/usr/bin/env python3
"""Check that a candidate (Rust-backed) implementation matches the legacy one over a corpus.

Each command is run once per input file. Use {input} in the command for the file path, or omit it
to feed the file on stdin. Stdout is compared; JSON output is compared structurally with a float
tolerance. Exit code 0 = all match, 1 = mismatches, 2 = bad usage.

Usage:
    python parity_check.py --legacy "python legacy.py {input}" --candidate "python new.py {input}" \
        --inputs tests/corpus [--float-tol 1e-9] [--ignore-key timestamp] [--limit 1000]
"""
import argparse
import json
import math
import shlex
import subprocess
import sys
from pathlib import Path


def run(cmd_template, path, timeout):
    use_arg = "{input}" in cmd_template
    quoted = shlex.quote(str(path)) if sys.platform != "win32" else f'"{path}"'
    cmd = cmd_template.replace("{input}", quoted)
    stdin = None if use_arg else open(path, "rb")
    try:
        p = subprocess.run(cmd, shell=True, stdin=stdin, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return -999, "", "timeout"
    finally:
        if stdin:
            stdin.close()


def strip_keys(obj, keys):
    if isinstance(obj, dict):
        return {k: strip_keys(v, keys) for k, v in obj.items() if k not in keys}
    if isinstance(obj, list):
        return [strip_keys(v, keys) for v in obj]
    return obj


def equal(a, b, tol):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a is b
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if math.isnan(a) and math.isnan(b):
                return True
            return math.isclose(a, b, rel_tol=tol, abs_tol=tol)
        return False
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def compare(out_a, out_b, tol, ignore):
    try:
        ja, jb = json.loads(out_a), json.loads(out_b)
        return equal(strip_keys(ja, ignore), strip_keys(jb, ignore), tol)
    except ValueError:
        return out_a.strip() == out_b.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--inputs", required=True, help="directory of input files (recursive)")
    ap.add_argument("--float-tol", type=float, default=1e-9)
    ap.add_argument("--ignore-key", action="append", default=[], help="JSON keys to ignore (repeatable)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--report", help="write JSON report here")
    args = ap.parse_args()

    root = Path(args.inputs)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if args.limit:
        files = files[: args.limit]
    if not files:
        print(f"error: no input files in {root}", file=sys.stderr)
        sys.exit(2)

    ignore = set(args.ignore_key)
    mismatches, ok = [], 0
    for f in files:
        rc_l, out_l, err_l = run(args.legacy, f, args.timeout)
        rc_c, out_c, err_c = run(args.candidate, f, args.timeout)
        # Behavior includes failing the same way: both must succeed or both must fail.
        if (rc_l == 0) != (rc_c == 0):
            mismatches.append({"input": str(f), "reason": f"exit codes differ: legacy={rc_l} candidate={rc_c}",
                               "legacy_stderr": err_l[-300:], "candidate_stderr": err_c[-300:]})
        elif rc_l == 0 and not compare(out_l, out_c, args.float_tol, ignore):
            mismatches.append({"input": str(f), "reason": "stdout differs",
                               "legacy": out_l[:300], "candidate": out_c[:300]})
        else:
            ok += 1

    print(f"parity: {ok}/{len(files)} match")
    for m in mismatches[:10]:
        print(f"  MISMATCH {m['input']}: {m['reason']}")
    if len(mismatches) > 10:
        print(f"  ... and {len(mismatches) - 10} more")
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"total": len(files), "ok": ok, "mismatches": mismatches},
                                          indent=2), encoding="utf-8")
    sys.exit(0 if not mismatches else 1)


if __name__ == "__main__":
    main()
