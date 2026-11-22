#!/usr/bin/env python3
"""Detect languages, frameworks, and toolchain for a project and suggest Rust bridges.

Usage:
    python detect_stack.py <project-root> [--out stack.json]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", "target", "venv", ".venv", "env", "__pycache__", "dist",
    "build", ".next", ".rust-opt", "bin", "obj", "Library", "Temp", "Logs", ".idea", ".vs",
}

EXT_LANG = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".cs": "csharp",
    ".java": "java", ".kt": "kotlin", ".go": "go", ".rs": "rust", ".c": "c", ".cpp": "cpp",
    ".cc": "cpp", ".h": "c", ".hpp": "cpp", ".rb": "ruby", ".php": "php", ".swift": "swift",
}

BRIDGES = {
    "python": ["pyo3"],
    "javascript": ["napi", "wasm"],
    "typescript": ["napi", "wasm"],
    "csharp": ["ffi"],
    "java": ["sidecar"],
    "kotlin": ["sidecar"],
    "go": ["sidecar", "ffi"],
    "ruby": ["sidecar"],
    "php": ["sidecar"],
    "cpp": ["ffi"],
    "c": ["ffi"],
}

TOOLS = {
    "cargo": ["cargo", "--version"],
    "rustc": ["rustc", "--version"],
    "maturin": ["maturin", "--version"],
    "wasm-pack": ["wasm-pack", "--version"],
    "node": ["node", "--version"],
    "pnpm": ["pnpm", "--version"],
    "npm": ["npm", "--version"],
    "python": [sys.executable, "--version"],
    "dotnet": ["dotnet", "--version"],
}


def tool_version(cmd):
    if cmd[0] != sys.executable and shutil.which(cmd[0]) is None:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return None


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            yield Path(dirpath) / f


def count_lines(path):
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--out")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"error: {root} is not a directory")

    lines = Counter()
    files = Counter()
    manifests = []
    for p in walk(root):
        lang = EXT_LANG.get(p.suffix.lower())
        if lang:
            files[lang] += 1
            lines[lang] += count_lines(p)
        if p.name in {"package.json", "pyproject.toml", "requirements.txt", "setup.py",
                      "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "CMakeLists.txt",
                      "tauri.conf.json", "ProjectVersion.txt"} or p.suffix in {".csproj", ".sln"}:
            manifests.append(str(p.relative_to(root)))

    frameworks = []
    pkg = read_json(root / "package.json")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    for name, label in [("electron", "electron"), ("next", "nextjs"), ("vite", "vite"),
                        ("react", "react"), ("vue", "vue"), ("@tauri-apps/api", "tauri"),
                        ("express", "express"), ("fastify", "fastify")]:
        if name in deps:
            frameworks.append(label)
    if (root / "src-tauri").is_dir() or any(m.endswith("tauri.conf.json") for m in manifests):
        frameworks.append("tauri")
    if (root / "ProjectSettings" / "ProjectVersion.txt").exists():
        frameworks.append("unity")
    req = ""
    for name in ("requirements.txt", "pyproject.toml"):
        if (root / name).exists():
            req += (root / name).read_text(encoding="utf-8", errors="ignore").lower()
    for lib in ("numpy", "pandas", "fastapi", "flask", "django", "opencv", "torch", "polars"):
        if lib in req:
            frameworks.append(lib)
    frameworks = sorted(set(frameworks))

    primary = lines.most_common(1)[0][0] if lines else None
    bridges = []
    if "tauri" in frameworks:
        bridges.append("tauri")
    if "unity" in frameworks:
        bridges.append("ffi")
        notes = ["Unity WebGL cannot load native plugins; check the build target before choosing FFI."]
    else:
        notes = []
    for b in BRIDGES.get(primary, []):
        if b not in bridges:
            bridges.append(b)
    if "numpy" in frameworks or "pandas" in frameworks or "polars" in frameworks:
        notes.append("NumPy/pandas/polars already run native code; vectorize first and port only "
                     "the pure-Python loops that remain.")
    if not bridges:
        bridges.append("sidecar")

    toolchain = {name: tool_version(cmd) for name, cmd in TOOLS.items()}
    missing = []
    if not toolchain["cargo"]:
        missing.append("cargo/rustc (install via https://rustup.rs; on Windows also MSVC Build Tools)")
    if "pyo3" in bridges and not toolchain["maturin"]:
        missing.append("maturin (pip install maturin)")
    if "wasm" in bridges and not toolchain["wasm-pack"]:
        missing.append("wasm-pack (only if the WASM bridge is chosen)")

    result = {
        "root": str(root),
        "primary_language": primary,
        "languages": {k: {"files": files[k], "lines": lines[k]} for k, _ in lines.most_common()},
        "frameworks": frameworks,
        "manifests": sorted(manifests)[:50],
        "recommended_bridges": bridges,
        "toolchain": toolchain,
        "missing_toolchain": missing,
        "notes": notes,
    }
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
