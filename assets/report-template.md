# Rust hotspot optimization report

**Project:** `<name>`  **Date:** `<YYYY-MM-DD>`  **Commit (before):** `<hash>`  **Commit (after):** `<hash>`

## 1. Outcome (lead with the numbers)

| Hotspot | Before | After | Speedup | Peak RAM change | Parity |
|---|---|---|---|---|---|
| `<module.function>` | `<median s>` | `<median s>` | `<N>x` | `<±N%>` | `<ok>/<total>` |

**End-to-end workload:** `<command>` — before `<s>`, after `<s>` (`<N>x`). Goal was `<metric and threshold>`: **met / not met**.

## 2. What was ported

For each hotspot: why it was chosen (profile share, bottleneck type), the Rust module and bridge used, how it is wired in, and the switch that selects the legacy path (`RUST_OPT_DISABLE=1` or equivalent).

## 3. What was deliberately not ported

| Candidate | Share of runtime | Reason (cheaper fix applied / below threshold / I/O-bound / boundary cost / platform limit) |
|---|---|---|

## 4. Remaining hotspots

Ranked list from the post-port profile with the Amdahl cap for each, and a recommendation (port next / fix cheaper / leave).

## 5. Verification

- Parity corpus: `<N>` inputs, tolerance `<value>`, ignored fields `<list>`
- Existing test suite: `<pass/fail, counts>`
- Rust: `cargo test`, `cargo clippy -D warnings`, `cargo fmt --check`: `<results>`
- Benchmark method: `<runs>` runs, `<warmup>` warmup, release build, machine `<description>`, rel-stdev before/after `<%>`/`<%>`
- **Not verified:** `<anything that could not be run here, e.g. other OS builds>`

## 6. Risks and caveats

Semantic differences accepted (floating-point order, Unicode handling, ordering), `unsafe` blocks and their invariants, new dependencies and licenses, platforms without a prebuilt binary.

## 7. Build, CI, and packaging changes

Toolchain requirements (Rust version, maturin/napi/wasm-pack), commands to build, CI matrix changes, where binaries are produced and shipped, README sections updated.

## 8. Rollback

Exact steps: set `<switch>`, or revert commits `<hashes>`; legacy code kept at `<path>` until the user approves removal.
