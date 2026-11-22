# rust-hotspot-optimizer

An Agent Skill that profiles an existing codebase, identifies genuine CPU/memory hotspots, and ports **only those hotspots** to Rust while preserving identical behavior and proving the speedup with measured benchmarks.

Pipeline: **measure → select → lock behavior → port → verify → report**.

## Supported Bridges

| Host Stack | Bridge | Template & Guide |
|---|---|---|
| Python | PyO3 + maturin | `references/bridges/python-pyo3.md` · `assets/templates/pyo3/` |
| Node.js / Electron | napi-rs | `references/bridges/node-napi-rs.md` · `assets/templates/napi/` |
| Browser / Web | wasm-bindgen | `references/bridges/wasm-bindgen.md` · `assets/templates/wasm/` |
| Tauri | Rust command in `src-tauri` | `references/bridges/tauri-commands.md` · `assets/templates/tauri/` |
| C# / .NET / Unity | `cdylib` + P/Invoke | `references/bridges/csharp-pinvoke.md` · `assets/templates/ffi/` |
| Other / isolated process | CLI sidecar (stdin/stdout JSON) | `references/bridges/cli-sidecar.md` · `assets/templates/sidecar/` |

## Repository Layout

```text
rust-hotspot-optimizer/
├── SKILL.md                  # Entry point & 8-phase workflow instructions
├── references/               # Progressive-disclosure guides (profiling, selection, idioms, pitfalls, bridges)
├── scripts/                  # Zero-dependency Python CLI helpers
│   ├── detect_stack.py       # Detect languages, frameworks, toolchain & recommended bridges
│   ├── scan_hotspots.py      # Static hotspot scanner + profiler merge & Amdahl scoring
│   ├── run_baseline.py       # Repeatable wall-time & peak RSS measurement (Unix + Windows)
│   ├── compare_bench.py      # Before/after statistical comparison & threshold verdict
│   ├── parity_check.py       # Corpus-based behavior parity checker (JSON/text + float tol)
│   ├── scaffold_rust_crate.py# Generate Rust crate from assets/templates/<bridge>/
│   └── package_skill.py      # Validate & repackage into a distributable .skill zip
├── assets/                   # Golden test checklist, report template, and 6 bridge crate templates
└── tests/                    # Unit tests for all scripts
```

## Installation

- **Antigravity / Agent Skills (workspace or global):** Copy or symlink this repository into `.agents/skills/rust-hotspot-optimizer/` (workspace) or `~/.gemini/config/skills/rust-hotspot-optimizer/` (global).
- **Packaged `.skill` bundle:** Build a fresh archive with:
  ```bash
  python scripts/package_skill.py --out dist/rust-hotspot-optimizer.skill
  ```

## Development & Testing

All scripts use only the Python 3 standard library. Run the test suite with:

```bash
python -m unittest discover -s tests -v
```
