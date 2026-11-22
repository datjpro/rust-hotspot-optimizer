# Benchmarking method

Read this in Phases 2 and 6. A comparison is only as trustworthy as its method.

## Rules

1. **Same input, same machine, same conditions** for before and after. Run both in the same session, alternating if the machine is noisy.
2. **Release builds only** on the Rust side, and the host in its normal production mode (no debug flags, no profilers attached).
3. **Warm up** (`--warmup 2` or more) so JITs, caches, and lazy imports do not skew the first runs. Decide whether cold start matters to the user; if it does, measure it separately.
4. **Enough runs**: 7 or more, and report the **median** plus the range. Means hide outliers.
5. **Noise gate**: relative stdev above ~10% means the numbers are unreliable. Close other programs, plug in laptops, pin CPU frequency if you can, raise runs, or enlarge the workload.
6. **Include the boundary**: measure end-to-end through the host, so conversion and FFI costs are counted. A fast Rust function behind a slow boundary is not a win.
7. **Check output equality** in the same run (`parity_check.py`). A benchmark of a wrong result is meaningless.
8. **Measure memory** (`peak_rss_kb_median`) whenever RAM is a goal or the port changes data layout.

## Layers of measurement

| Layer | Tool | Answers |
|---|---|---|
| End-to-end | `scripts/run_baseline.py` + `compare_bench.py` | Did the user-visible goal improve? (the one that counts) |
| Function-level in host | host micro-benchmark (`timeit`, `benchmark.js`, BenchmarkDotNet) | Did the function get faster including the boundary? |
| Rust-only | `criterion` or `cargo bench` | How fast is the core? Is the Rust code itself efficient? |
| Profile after | `cargo flamegraph`, `samply`, host profiler | What is the new bottleneck? |

Use `hyperfine` if installed (`hyperfine --warmup 2 --runs 10 'cmd'`); `run_baseline.py` exists so the workflow works without extra installs and on Windows.

## Interpreting the comparison

- Report `before median → after median (Nx)` and the RAM change.
- If before/after ranges overlap, the gain is not clearly outside noise; re-run with more runs or a bigger workload.
- Speedup below the agreed threshold: investigate in this order: (1) boundary conversion cost, (2) too many small calls, (3) debug build, (4) parallelism disabled, (5) the profile shows the function was less than expected. If none apply, recommend reverting.
- Do not extrapolate. A 20x function speedup on a 30% hotspot is at most 1.43x overall.

## Reproducibility record

Store with every result: the exact command, input identity (path, size, hash), machine description, toolchain versions, commit hash. `run_baseline.py` captures command and environment; add the rest to `.rust-opt/goals.md`.
