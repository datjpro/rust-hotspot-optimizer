#!/usr/bin/env python3
"""Static hotspot scan + optional profile merge. Produces ranked candidates for Rust porting.

The static scan only finds *suspicious* code (deep loop nests, O(n) work inside loops, repeated
parsing/regex/serialization, arithmetic-heavy loops). Profile data decides what actually matters.
Candidates that are not confirmed by a profile are marked `measured: false` and ranked lower.

Usage:
    python scan_hotspots.py <project-root> [--profile profile.json] [--out hotspots.json]
                            [--top 30] [--min-score 8] [--include-tests]

profile.json schema (see references/profiling.md):
    {"workload": "...", "samples": [{"file": "src/x.py", "function": "parse", "self_percent": 42.1,
                                      "total_percent": 55.0}]}
"""
import argparse
import ast
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "target", "venv", ".venv", "env", "__pycache__", "dist", "build",
             ".next", ".rust-opt", "bin", "obj", "Library", "Temp", "Logs", ".idea", ".vs", "vendor",
             "site-packages"}
TEST_MARKERS = ("/test/", "/tests/", "/__tests__/", ".test.", ".spec.", "_test.", "/test_", "/mocks/")
LANG_BY_EXT = {".py": "python", ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js",
               ".tsx": "js", ".cs": "csharp", ".java": "java", ".go": "go", ".c": "c", ".cpp": "c",
               ".cc": "c", ".h": "c", ".hpp": "c"}
BRIDGE_BY_LANG = {"python": "pyo3", "js": "napi", "csharp": "ffi", "java": "sidecar", "go": "sidecar",
                  "c": "ffi"}

# category -> (weight, reason, cheaper fix to try before porting)
CATS = {
    "deep_nest": (15, "nested loops (depth {n})", "check whether the nesting can be removed with a hash map, sort, or better algorithm"),
    "regex": (6, "regex/string scanning inside a loop", "precompile the pattern outside the loop or parse in one pass"),
    "json": (6, "JSON (de)serialization inside a loop", "batch the (de)serialization or use a faster parser before porting"),
    "linear_search": (8, "linear search / O(n) lookup inside a loop (O(n^2) risk)", "replace with a set/dict lookup; often removes the hotspot with no Rust"),
    "sort": (6, "sorting inside a loop", "sort once outside the loop or keep data ordered"),
    "string_concat": (5, "string concatenation inside a loop", "collect parts and join once / use a builder"),
    "alloc": (4, "allocation-heavy calls (LINQ/streams/copies) inside a loop", "hoist allocations, reuse buffers, avoid per-iteration copies"),
    "deepcopy": (8, "deep copy inside a loop", "avoid copying; pass references or use immutable data"),
    "numpy_in_loop": (6, "array-library call inside a Python loop", "vectorize the loop first; Rust gains less once vectorized"),
    "arith_loop": (8, "arithmetic-heavy loop body (good Rust candidate)", None),
    "recursion": (6, "recursive function", "check memoization or an iterative version first"),
    "big_loop_body": (5, "large loop body", None),
}

JS_SUSP = [
    ("json", r"JSON\.(parse|stringify)\s*\("),
    ("regex", r"new RegExp\(|\.(match|matchAll|replace|replaceAll|test|exec|split)\s*\("),
    ("linear_search", r"\.(indexOf|lastIndexOf|includes|find|findIndex)\s*\("),
    ("sort", r"\.sort\s*\("),
    ("alloc", r"\.\.\.\s*\w|\.slice\s*\(|\.concat\s*\(|Object\.(assign|entries|keys)\s*\("),
]
CS_SUSP = [
    ("regex", r"Regex\.|\.Split\s*\(|\.Replace\s*\("),
    ("json", r"JsonConvert\.|JsonSerializer\.|JsonUtility\."),
    ("linear_search", r"\.(Contains|IndexOf|Find|FindIndex|Any|First|FirstOrDefault|Single)\s*\("),
    ("sort", r"\.(Sort|OrderBy|OrderByDescending)\s*\("),
    ("alloc", r"\.(Select|Where|ToList|ToArray|Concat|GetComponent\w*|FindObjectOfType\w*)\s*[<(]|\bnew\s+\w+"),
    ("string_concat", r"\bstring\.Concat|\+=\s*\""),
]
JAVA_SUSP = [
    ("regex", r"Pattern\.(compile|matches)|\.(matches|split|replaceAll)\s*\("),
    ("json", r"ObjectMapper|\.readValue\s*\(|\.writeValueAsString\s*\("),
    ("linear_search", r"\.(contains|indexOf)\s*\("),
    ("sort", r"\.sort\s*\(|Collections\.sort"),
    ("alloc", r"\.stream\s*\(|\bnew\s+\w+"),
    ("string_concat", r"\+=\s*\""),
]
GO_SUSP = [
    ("regex", r"regexp\.(MustCompile|Compile|MatchString)"),
    ("json", r"json\.(Marshal|Unmarshal)"),
    ("sort", r"sort\.(Slice|Sort|Strings|Ints)"),
    ("alloc", r"fmt\.Sprintf|\bmake\s*\("),
    ("string_concat", r"\+=\s*\""),
]
C_SUSP = [("alloc", r"\b(malloc|calloc|new)\b")]
SUSP_BY_LANG = {"js": JS_SUSP, "csharp": CS_SUSP, "java": JAVA_SUSP, "go": GO_SUSP, "c": C_SUSP}

LOOP_RE = re.compile(r"\b(for|while|foreach)\b\s*\(|^\s*do\s*\{?\s*$|"
                     r"\.(forEach|map|filter|reduce|flatMap|some|every)\s*\(")
GO_LOOP_RE = re.compile(r"^\s*for\b.*\{\s*$")
NOT_FUNCS = {"if", "for", "while", "switch", "catch", "return", "else", "foreach", "using", "lock", "fixed",
             "sizeof", "typeof", "new", "do", "try", "finally", "synchronized", "function", "await", "throw"}
FUNC_PATTERNS = {
    "js": [r"\bfunction\s*\*?\s*(\w+)\s*\(",
           r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*(?::\s*[\w<>\[\]\|, ]+)?\s*=>|\w+\s*=>)",
           r"^\s*(?:(?:static|async|public|private|protected|get|set)\s+)*(\w+)\s*\([^)]*\)\s*(?::\s*[\w<>\[\]\|, ]+)?\s*\{?\s*$"],
    "csharp": [r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|abstract|async|unsafe|sealed|extern|partial)\s+)*[\w<>\[\],\.\?]+\s+(\w+)\s*\([^;]*$"],
    "java": [r"^\s*(?:(?:public|private|protected|static|final|synchronized|abstract|native)\s+)*[\w<>\[\],\.\?]+\s+(\w+)\s*\([^;]*$"],
    "go": [r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\("],
    "c": [r"^\s*[\w:<>\*&\s]+?\s+[\*&]?(\w+)\s*\([^;]*\)\s*(?:const)?\s*\{?\s*$"],
}


# ----------------------------- Python (AST) -----------------------------

def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def classify_py_call(call):
    name = dotted(call.func)
    last = name.rsplit(".", 1)[-1]
    if name.startswith("re.") or last in {"findall", "finditer", "fullmatch"}:
        return "regex"
    if name in {"json.loads", "json.dumps", "json.load", "json.dump"}:
        return "json"
    if last in {"index", "count", "remove"} and "." in name:
        return "linear_search"
    if last in {"sorted", "sort"}:
        return "sort"
    if name in {"copy.deepcopy", "deepcopy"}:
        return "deepcopy"
    if name.startswith(("np.", "numpy.", "pd.", "pandas.")):
        return "numpy_in_loop"
    return None


def analyze_py_function(fn):
    stats = {"max_depth": 0, "loops": 0, "susp": Counter(), "arith": 0, "loop_lines": 0, "recursion": False}
    loop_line_set = set()

    def visit(node, depth):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            d = depth
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
                d = depth + 1
            elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                d = depth + len(child.generators)
            if d > depth:
                stats["loops"] += 1
                stats["max_depth"] = max(stats["max_depth"], d)
            if d > 0 and hasattr(child, "lineno"):
                loop_line_set.add(child.lineno)
            if isinstance(child, ast.Call):
                if dotted(child.func) == fn.name:
                    stats["recursion"] = True
                if d > 0:
                    cat = classify_py_call(child)
                    if cat:
                        stats["susp"][cat] += 1
            if d > 0:
                if isinstance(child, ast.BinOp):
                    stats["arith"] += 1
                if (isinstance(child, ast.AugAssign) and isinstance(child.op, ast.Add)
                        and isinstance(child.value, (ast.JoinedStr, ast.Constant))
                        and (isinstance(child.value, ast.JoinedStr) or isinstance(child.value.value, str))):
                    stats["susp"]["string_concat"] += 1
            visit(child, d)

    visit(fn, 0)
    stats["loop_lines"] = len(loop_line_set)
    return stats


def scan_python(path, rel):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, ValueError):
        return []
    out = []

    def walk(body, prefix):
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                st = analyze_py_function(node)
                if st["loops"] or st["recursion"]:
                    end = getattr(node, "end_lineno", node.lineno)
                    out.append(make_candidate(rel, "python", f"{prefix}{node.name}", node.name,
                                              node.lineno, end, st))
                walk(node.body, f"{prefix}{node.name}.")

    walk(tree.body, "")
    return out


# --------------------------- Brace languages ---------------------------

def clean_line(line, state):
    out, i, n, in_str = [], 0, len(line), None
    while i < n:
        c = line[i]
        if state["block"]:
            j = line.find("*/", i)
            if j == -1:
                break
            state["block"] = False
            i = j + 2
            continue
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "\"'`":
            in_str = c
            i += 1
            continue
        if c == "/" and i + 1 < n and line[i + 1] == "/":
            break
        if c == "/" and i + 1 < n and line[i + 1] == "*":
            state["block"] = True
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def new_func_stats(name, start):
    return {"name": name, "start": start, "end": start, "max_depth": 0, "loops": 0, "susp": Counter(),
            "arith": 0, "loop_lines": 0, "recursion": False}


def scan_braces(path, rel, lang):
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    if len(lines) > 20000 or any(len(l) > 2000 for l in lines[:50]):  # minified/generated
        return []
    susp = [(c, re.compile(p)) for c, p in SUSP_BY_LANG.get(lang, [])]
    func_res = [re.compile(p) for p in FUNC_PATTERNS.get(lang, [])]
    loop_re = GO_LOOP_RE if lang == "go" else LOOP_RE
    state = {"block": False}
    depth = 0
    loops = []      # dicts: open_depth, started (body brace seen)
    funcs = []      # dicts: open_depth, stats
    top = new_func_stats("<top-level>", 1)
    pending_func = None
    done = []
    awaiting_stmt = False

    def cur():
        return funcs[-1]["stats"] if funcs else top

    for ln, raw in enumerate(lines, 1):
        line = clean_line(raw, state)
        if not line.strip():
            continue
        stats = cur()
        stats["end"] = ln

        if pending_func is None:
            for rx in func_res:
                m = rx.search(line)
                if m and m.group(1) not in NOT_FUNCS and not loop_re.search(line):
                    pending_func = (m.group(1), ln)
                    break
        elif ";" in line and "{" not in line:
            pending_func = None

        is_loop_header = bool(loop_re.search(line))
        in_loop_before = bool(loops) or awaiting_stmt
        if is_loop_header:
            loops.append({"open_depth": depth, "started": False, "line": ln})
            stats["loops"] += 1
            nest = len(loops)
            stats["max_depth"] = max(stats["max_depth"], nest)

        # Per-iteration work: lines inside an already-open loop body.
        if in_loop_before:
            stats["loop_lines"] += 1
            for cat, rx in susp:
                if rx.search(line):
                    stats["susp"][cat] += 1
            if re.search(r"[\w\)\]]\s*[-+*/%]\s*[\w\(]", line):
                stats["arith"] += 1
            if re.search(r"\w\s*\+=\s*", line) and ('"' in raw or "'" in raw) and "string_concat" in dict(CATS):
                stats["susp"]["string_concat"] += 1
        awaiting_stmt = False

        for ch in line:
            if ch == "{":
                if pending_func:
                    funcs.append({"open_depth": depth, "stats": new_func_stats(pending_func[0], pending_func[1])})
                    top_stats = funcs[-1]["stats"]
                    top_stats["end"] = ln
                    pending_func = None
                for lp in loops:
                    if not lp["started"] and lp["open_depth"] == depth:
                        lp["started"] = True
                depth += 1
            elif ch == "}":
                depth = max(0, depth - 1)
                while loops and loops[-1]["started"] and depth <= loops[-1]["open_depth"]:
                    loops.pop()
                while funcs and depth <= funcs[-1]["open_depth"]:
                    f = funcs.pop()["stats"]
                    f["end"] = ln
                    done.append(f)
        # single-statement loops (no braces)
        if loops and not loops[-1]["started"]:
            stripped = line.rstrip()
            if stripped.endswith(";") or (is_loop_header and stripped.endswith((")", "),", ");"))
                                          and "{" not in line and "=>" in line):
                loops.pop()
            elif is_loop_header and not stripped.endswith("{"):
                awaiting_stmt = True

    for f in funcs:
        done.append(f["stats"])
    done.append(top)
    out = []
    for f in done:
        if f["loops"] or f["recursion"]:
            out.append(make_candidate(rel, lang, f["name"], f["name"], f["start"], f["end"], f))
    return out


# ------------------------------- Scoring -------------------------------

def make_candidate(rel, lang, qualified, simple, start, end, st):
    reasons, hints, score = [], [], 0
    if st["max_depth"] >= 2:
        w, text, hint = CATS["deep_nest"]
        score += w * (st["max_depth"] - 1)
        reasons.append(text.format(n=st["max_depth"]))
        hints.append(hint)
    for cat, n in st["susp"].items():
        w, text, hint = CATS[cat]
        score += w + min(n - 1, 3)
        reasons.append(text + (f" (x{n})" if n > 1 else ""))
        if hint:
            hints.append(hint)
    if st["loops"] and st["arith"] >= 5 and not (st["susp"].get("numpy_in_loop")):
        score += CATS["arith_loop"][0]
        reasons.append(CATS["arith_loop"][1])
    if st["recursion"]:
        score += CATS["recursion"][0]
        reasons.append(CATS["recursion"][1])
        hints.append(CATS["recursion"][2])
    if st["loop_lines"] >= 25:
        score += CATS["big_loop_body"][0]
        reasons.append(CATS["big_loop_body"][1])
    if st["loops"]:
        score += 5
    score = min(score, 100)
    return {"id": f"{rel}:{qualified}", "file": rel, "function": qualified, "name": simple,
            "language": lang, "line_start": start, "line_end": end,
            "static_score": score, "reasons": reasons, "cheaper_fix_first": sorted(set(hints)),
            "suggested_bridge": BRIDGE_BY_LANG.get(lang, "sidecar"),
            "measured": False, "self_percent": None, "total_percent": None}


def norm(p):
    return p.replace("\\", "/").lstrip("./")


def merge_profile(cands, profile):
    samples = profile.get("samples", [])
    by_id = {c["id"]: c for c in cands}
    for s in samples:
        sf, sn = norm(s.get("file", "")), str(s.get("function", "")).split(".")[-1]
        matches = [c for c in cands if c["name"].split(".")[-1] == sn and
                   (not sf or norm(c["file"]).endswith(sf) or sf.endswith(norm(c["file"])))]
        if matches:
            for c in matches[:1]:
                c["measured"] = True
                c["self_percent"] = s.get("self_percent")
                c["total_percent"] = s.get("total_percent")
        else:
            cid = f"{sf}:{s.get('function')}"
            if cid not in by_id:
                cands.append({"id": cid, "file": sf, "function": s.get("function"), "name": sn,
                              "language": "unknown", "line_start": None, "line_end": None,
                              "static_score": 0, "reasons": ["appears in profile; not flagged by static scan"],
                              "cheaper_fix_first": [], "suggested_bridge": None, "measured": True,
                              "self_percent": s.get("self_percent"), "total_percent": s.get("total_percent")})
    return cands


def finalize(c):
    pct = c["self_percent"] if c["measured"] and c["self_percent"] is not None else None
    if pct is not None:
        c["priority"] = round(pct + 0.2 * c["static_score"], 2)
        bound = None if pct >= 100 else round(1 / (1 - pct / 100), 2)
        c["amdahl_max_speedup"] = bound
        if pct < 10:
            c["recommendation"] = f"skip: only {pct}% of runtime (end-to-end gain capped at {bound}x)"
        elif c["cheaper_fix_first"]:
            c["recommendation"] = "try the cheaper fix first; port only if the profile is still dominated by it"
        else:
            c["recommendation"] = "port candidate (ask user to approve)"
    else:
        c["priority"] = round(0.3 * c["static_score"], 2)
        c["amdahl_max_speedup"] = None
        c["recommendation"] = "unmeasured: confirm with a profiler before deciding"
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--profile")
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--min-score", type=int, default=8)
    ap.add_argument("--include-tests", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"error: {root} is not a directory")

    cands = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            p = Path(dirpath) / f
            lang = LANG_BY_EXT.get(p.suffix.lower())
            if not lang or f.endswith((".min.js", ".d.ts", ".designer.cs", ".g.cs")):
                continue
            rel = p.relative_to(root).as_posix()
            if not args.include_tests and any(m in "/" + rel for m in TEST_MARKERS):
                continue
            scanned += 1
            found = scan_python(p, rel) if lang == "python" else scan_braces(p, rel, lang)
            cands.extend(c for c in found if c["static_score"] >= args.min_score)

    profile_used = False
    if args.profile:
        try:
            profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
            cands = merge_profile(cands, profile)
            profile_used = True
        except (OSError, ValueError) as exc:
            print(f"warning: could not read profile ({exc}); results are static-only", file=sys.stderr)

    cands = [finalize(c) for c in cands]
    cands.sort(key=lambda c: c["priority"], reverse=True)
    cands = cands[: args.top]
    result = {"root": str(root), "files_scanned": scanned, "profile_used": profile_used,
              "note": None if profile_used else "STATIC ONLY: no profile merged. Do not port anything "
                                                "until a profiler confirms the candidates.",
              "candidates": cands}
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"scanned {scanned} files, {len(cands)} candidates (profile merged: {profile_used})")
    if not profile_used:
        print("NOTE: static only. Confirm with a profiler before porting.")
    for i, c in enumerate(cands[:15], 1):
        pct = f"{c['self_percent']:.1f}%" if c["measured"] and c["self_percent"] is not None else "n/a"
        print(f"{i:>2}. prio {c['priority']:>6}  runtime {pct:>6}  {c['id']}  [{'; '.join(c['reasons'][:2])}]")


if __name__ == "__main__":
    main()
