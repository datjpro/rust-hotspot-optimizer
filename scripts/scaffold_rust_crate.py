#!/usr/bin/env python3
"""Generate a Rust crate/module for the chosen bridge from assets/templates/<bridge>/.

Usage:
    python scaffold_rust_crate.py --bridge pyo3 --name fast_parser --out ./rust/fast_parser [--force]

Bridges: pyo3, napi, wasm, ffi, sidecar, tauri
Template files end in `.tmpl`; the suffix is removed. Placeholders:
    {{crate_name}}        snake_case name (also the module / library name)
    {{crate_name_kebab}}  kebab-case name
    {{CrateNamePascal}}   PascalCase name
Existing files are never overwritten unless --force is given.
"""
import argparse
import re
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "assets" / "templates"

NEXT_STEPS = {
    "pyo3": [
        "cd {out} && pip install maturin",
        "maturin develop --release        # builds and installs into the active virtualenv",
        "cargo test                       # pure-Rust unit tests (no Python needed)",
        "Wire into Python with an import-time fallback (see references/bridges/python-pyo3.md)",
    ],
    "napi": [
        "cd {out} && npm install          # or pnpm install",
        "npm run build                    # produces the .node binary plus index.js / index.d.ts",
        "cargo test",
        "Wire into JS with a try/require fallback (see references/bridges/node-napi-rs.md)",
    ],
    "wasm": [
        "cd {out} && cargo install wasm-pack   # once",
        "wasm-pack build --release --target web",
        "Import the generated pkg/ from the frontend (see references/bridges/wasm-bindgen.md)",
    ],
    "ffi": [
        "cd {out} && cargo build --release  # target/release/lib{name}.so | {name}.dll | lib{name}.dylib",
        "cargo test",
        "Copy NativeMethods.cs next to your C# code and the library next to the executable "
        "or into Unity Assets/Plugins/<platform>/ (see references/bridges/csharp-pinvoke.md)",
    ],
    "sidecar": [
        "cd {out} && cargo build --release",
        "echo '{{\"values\":[1,2,3]}}' | target/release/{name}",
        "Spawn the binary from the host and parse stdout JSON (see references/bridges/cli-sidecar.md)",
    ],
    "tauri": [
        "Copy the generated file into src-tauri/src/ and register the command as shown in its header comment",
        "cargo test   (inside src-tauri)",
        "See references/bridges/tauri-commands.md",
    ],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bridge", required=True, choices=sorted(NEXT_STEPS))
    ap.add_argument("--name", required=True, help="crate name, e.g. fast_parser")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    snake = re.sub(r"[-\s]+", "_", args.name.strip()).lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", snake):
        sys.exit("error: --name must start with a letter and contain only letters, digits, - or _")
    subs = {
        "{{crate_name}}": snake,
        "{{crate_name_kebab}}": snake.replace("_", "-"),
        "{{CrateNamePascal}}": "".join(w.capitalize() for w in snake.split("_")),
    }

    src = TEMPLATES / args.bridge
    if not src.is_dir():
        sys.exit(f"error: template directory not found: {src}")
    out = Path(args.out)

    plan = []
    for f in sorted(src.rglob("*")):
        if f.is_file():
            rel = f.relative_to(src)
            if rel.name.endswith(".tmpl"):
                rel = rel.with_name(rel.name[:-5])
            plan.append((f, out / rel))

    clashes = [str(dst) for _, dst in plan if dst.exists()]
    if clashes and not args.force:
        sys.exit("error: refusing to overwrite existing files (use --force):\n  " + "\n  ".join(clashes))

    for srcfile, dst in plan:
        text = srcfile.read_text(encoding="utf-8")
        for k, v in subs.items():
            text = text.replace(k, v)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8")
        print(f"created {dst}")

    print("\nNext steps:")
    for i, step in enumerate(NEXT_STEPS[args.bridge], 1):
        print(f"  {i}. " + step.format(out=out, name=snake))
    print("\nReplace the example `sum_squares` with the real hotspot, keep the host-visible signature "
          "identical to the legacy function, and keep the legacy path selectable.")


if __name__ == "__main__":
    main()
