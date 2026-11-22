---
name: rust-hotspot-optimizer
description: Profile an existing codebase, find the CPU/memory hotspots, and port ONLY those parts to Rust (PyO3, napi-rs, WASM, C FFI, Tauri commands, or a sidecar binary) while keeping behavior identical and proving the speedup with measured benchmarks. Use this skill whenever the user wants to optimize an old or slow project, speed up hot loops or bottlenecks, reduce CPU/RAM usage, rewrite or migrate parts of a codebase to Rust, or asks "should this be in Rust?" — even if they never say "Rust" or "hotspot" explicitly.
---

# Rust Hotspot Optimizer

Turn the slow parts of an existing project into Rust without rewriting the whole project and without guessing. The skill is a measured, reversible pipeline: **measure → select → lock behavior → port → verify → report**.

## Why the rules below exist

Most "rewrite it in Rust" efforts fail for three reasons: the wrong code was ported (the bottleneck was I/O or an algorithm), behavior drifted silently, or the FFI boundary cost ate the gain. Every rule here targets one of those failures. Follow the order of phases; skipping ahead is the usual way to waste a week.

## Core rules

1. **Measure before writing.** No code is ported without profile evidence. A guess about where time goes is wrong more often than right.
2. **Port hotspots, not projects.** The unit of work is one function or one tight module with a clean input/output boundary.
3. **Preserve the contract.** Public signatures, return shapes, error behavior, and ordering stay identical so callers never change.
4. **Keep the legacy path alive** behind a switch until the user explicitly approves removal. It is the rollback plan and the oracle for parity tests.
5. **Prove it with numbers.** Every claim of "faster" or "lighter" cites a before/after measurement from `scripts/compare_bench.py`. Never estimate results.
6. **Respect thresholds.** If the measured end-to-end gain is below the agreed threshold (default 1.5x or 20% less RAM), recommend reverting or not porting. A "no" backed by data is a valid, valuable outcome.

## Working directory

Create `.rust-opt/` at the project root and keep all state there so work survives across turns:

```
.rust-opt/
├── stack.json        # Phase 1: detected languages, frameworks, toolchain
├── goals.md          # Phase 0: metric, threshold, workload, constraints
├── baseline/         # Phase 2: raw benchmark JSON of the legacy code
├── profile.json      # Phase 2: normalized profiler output (schema in references/profiling.md)
├── hotspots.json     # Phase 3: ranked, scored candidates + user decisions
├── after/            # Phase 6: benchmark JSON of the ported code
└── report.md         # Phase 7: final report
```

Add `.rust-opt/` to `.gitignore` only if the user does not want the report committed; ask once.

## Workflow

> **Paths:** `scripts/...`, `references/...`, and `assets/...` are relative to this skill's directory (`<skill-dir>`). `.rust-opt/` lives at the target project's root.

### Phase 0 — Intake
Read the user's request and the repo first, then ask only for what is missing (one short batch, not an interrogation):
- **Goal metric**: latency, throughput, peak RAM, startup time, or battery/CPU.
- **Threshold**: what counts as success (default: ≥1.5x faster or ≥20% less RAM on the real workload).
- **Representative workload**: the command, input file, or scenario that feels slow. If none exists, help create one.
- **Constraints**: target OS/architectures, who will maintain Rust, CI/build limits, whether adding a Rust toolchain is acceptable.

Write the answers to `.rust-opt/goals.md`.

### Phase 1 — Discover
```bash
python scripts/detect_stack.py <project-root> --out .rust-opt/stack.json
```
Read `stack.json`: primary language, frameworks, recommended bridges, and which toolchain pieces are missing. If `cargo` is missing, stop and tell the user exactly what to install (see `references/pitfalls.md`, "Toolchain") rather than silently proceeding.

### Phase 2 — Baseline and profile
1. Build a **reproducible** benchmark command for the workload (fixed input, fixed seed).
2. Record the baseline:
   ```bash
   python scripts/run_baseline.py --name legacy --runs 7 --warmup 2 --out .rust-opt/baseline -- <command...>
   ```
3. Profile with the tool for the stack (`references/profiling.md`) and normalize the result into `.rust-opt/profile.json`.

**Gate:** relative stdev of the baseline must be under ~10%. If it is noisy, fix the workload or environment first (`references/benchmarking.md`).

### Phase 3 — Select hotspots
```bash
python scripts/scan_hotspots.py <project-root> --profile .rust-opt/profile.json --out .rust-opt/hotspots.json
```
The static scan finds suspicious code; the profile says what actually matters. Merge them using the scoring in `references/hotspot-selection.md`, including the **cheaper-fix check** (algorithm, caching, vectorization, batching) and the **Amdahl bound** (a function that is 5% of runtime can never give more than 1.05x).

Present a ranked table to the user: function, % of runtime, why it is slow, expected gain bound, FFI cost, risk, recommendation (port / fix cheaper / skip). **Gate:** the user approves which hotspots to port. Record approvals in `hotspots.json`.

### Phase 4 — Lock behavior (safety net)
Before touching code, capture what the legacy implementation does:
- Write golden/characterization tests from `assets/golden-test-template.md`: normal inputs, empty input, huge input, unicode, boundary numbers, malformed input, and the error cases.
- Build a parity corpus (a folder of input files) for `scripts/parity_check.py`.

**Gate:** all tests pass against the legacy code. Tests that only pass after porting prove nothing.

### Phase 5 — Port
1. Pick the bridge from the table below and read its file in `references/bridges/`.
2. Scaffold:
   ```bash
   python scripts/scaffold_rust_crate.py --bridge <pyo3|napi|wasm|ffi|sidecar|tauri> --name <crate_name> --out <dir>
   ```
3. Implement the Rust function using `references/rust-porting-idioms.md` (semantic differences in strings, integers, ordering, regex, floats are where behavior drifts).
4. Wire it in behind a switch so the legacy path remains selectable (environment variable `RUST_OPT_DISABLE=1`, a feature flag, or import-time fallback). Convert Rust errors into the host language's native exceptions; never let a panic cross the boundary.
5. Port **one hotspot at a time**, one commit each, so any single change can be reverted.

### Phase 6 — Verify
```bash
python scripts/parity_check.py --legacy "<cmd>" --candidate "<cmd>" --inputs <corpus-dir>
python scripts/run_baseline.py --name rust --runs 7 --warmup 2 --out .rust-opt/after -- <command...>
python scripts/compare_bench.py .rust-opt/baseline/legacy.json .rust-opt/after/rust.json --min-speedup <threshold>
```
Decision rule:
- Parity fails → fix or revert; never ship a faster wrong answer.
- Parity passes and threshold met → keep.
- Parity passes but threshold missed → check FFI overhead and conversion cost first (`references/pitfalls.md`); if still short, revert and record why.

Run the project's full existing test suite as well.

### Phase 7 — Report and hand-off
Fill `assets/report-template.md` into `.rust-opt/report.md`. Include: measured before/after table, what was ported, what was deliberately not ported and why, remaining hotspots ranked, build/CI/packaging changes, rollback instructions. Update the project's README or build docs for the new Rust toolchain requirement. Offer to delete the legacy path only after the user confirms.

## Bridge selection

| Current stack | Preferred bridge | Reference |
|---|---|---|
| Python | PyO3 + maturin | `references/bridges/python-pyo3.md` |
| Node.js / Electron | napi-rs | `references/bridges/node-napi-rs.md` |
| Browser / web frontend | wasm-bindgen | `references/bridges/wasm-bindgen.md` |
| Tauri app | Rust command inside `src-tauri` | `references/bridges/tauri-commands.md` |
| C# / .NET / Unity | `cdylib` + P/Invoke | `references/bridges/csharp-pinvoke.md` |
| Anything else, or process isolation wanted | Sidecar binary over stdin/stdout | `references/bridges/cli-sidecar.md` |

Prefer the bridge with the lowest per-call overhead that the platform supports. When the call is coarse (one call, lots of work), even a sidecar is fine. When calls are fine-grained (millions of tiny calls), move the **whole loop** into Rust instead of porting the inner function.

## When NOT to port (say so plainly)

- The time is spent in I/O, network, database, or waiting — fix queries, caching, or concurrency instead.
- The code already calls native libraries (NumPy, pandas, OpenCV, native Node addons) — Rust will not beat them by much.
- The algorithm is the problem (O(n²) where O(n log n) exists) — fix it in the original language first; it is cheaper and often enough.
- The hotspot is under ~10% of runtime — the Amdahl bound makes it not worth the maintenance cost.
- The target platform cannot load native code (for example Unity WebGL) and WASM is not viable.
- Nobody on the project can maintain Rust and the gain is modest.

## Safety rules for generated code

- Prefer safe Rust. Every `unsafe` block gets a comment stating the invariant that makes it sound, and the report lists them.
- Add dependencies conservatively; record each crate and why in the report. Check the latest version and docs for the chosen bridge crate, since APIs change between versions.
- Do not delete legacy code, rewrite unrelated files, or change public APIs without explicit user approval.
- If something cannot be verified in the current environment (no Rust toolchain, no way to run the workload), say exactly what was not verified instead of implying success.

## Communication

Reply in the language the user writes in. Keep everything written into the project (code, comments, commit messages, `.rust-opt/` files, the report) in English unless the user asks otherwise. Explain Rust and profiling terms briefly when the user's wording suggests they are new to them.

## Output format for the user

After each phase, report in this shape: what was done, the key numbers, the gate result (pass / fail / waiting for approval), and the next step. In the final message, lead with the measured outcome (for example "parse_orders: 41.2 s → 2.9 s, 14.2x, parity 1,000/1,000, RAM −38%"), then list caveats.

## Scripts and assets

| File | Purpose |
|---|---|
| `scripts/detect_stack.py` | Detect languages, frameworks, toolchain; suggest bridges |
| `scripts/scan_hotspots.py` | Static hotspot candidates; merges profile data and scores |
| `scripts/run_baseline.py` | Repeatable wall-time and peak-RAM measurement |
| `scripts/compare_bench.py` | Before/after comparison with speedup and noise check |
| `scripts/parity_check.py` | Legacy vs candidate output comparison over a corpus |
| `scripts/scaffold_rust_crate.py` | Generate a Rust crate/module for the chosen bridge |
| `assets/golden-test-template.md` | Characterization test checklist |
| `assets/report-template.md` | Final report structure |
| `assets/templates/` | Crate templates per bridge |
