# Profiling and baseline guide

Read this in Phase 2. The goal: know **where the time or memory goes** on a realistic workload, and store it in `.rust-opt/profile.json`.

## Contents
1. Build a representative workload
2. Profilers by stack
3. Normalized `profile.json` schema
4. Reading results (self vs total time, Amdahl)
5. Memory profiling

## 1. Build a representative workload

A profile of the wrong workload is worse than no profile.
- Use the real command or a real-size input. A toy input hides algorithmic costs and exaggerates startup costs.
- Fix everything that varies: input file, random seed, number of threads, network (mock it), cache state (decide warm vs cold and stay consistent).
- Keep the run between ~1 and ~60 seconds. Shorter: loop it inside the benchmark. Longer: shrink the input but keep its shape.
- Record the exact command in `.rust-opt/goals.md`.

## 2. Profilers by stack

| Stack | CPU profile | Memory profile |
|---|---|---|
| Python | `python -m cProfile -o out.prof app.py` then `pstats`; `py-spy record -o prof.json --format speedscope -- python app.py` (sampling, no code change, works on Windows); `scalene app.py` (CPU + memory + native vs Python split); `line_profiler` for line-level | `tracemalloc`, `scalene`, `memray` |
| Node.js / Electron | `node --cpu-prof app.js` (open `.cpuprofile` in Chrome DevTools); `clinic flame -- node app.js`; `0x app.js` | `node --heap-prof`, DevTools heap snapshot |
| Browser | DevTools Performance panel; record and look at "Bottom-Up" | DevTools Memory panel |
| .NET / C# | `dotnet-trace collect`, `dotnet-counters`; Visual Studio Performance Profiler; BenchmarkDotNet for micro-benchmarks | `dotnet-gcdump`, VS memory tools |
| Unity | Unity Profiler (CPU Usage, enable Deep Profile only when needed), Profile Analyzer package; check GC.Alloc column | Memory Profiler package |
| Java / Kotlin | JFR (`-XX:+FlightRecorder`), async-profiler | JFR allocation events, heap dumps |
| Go | `pprof` (`go test -bench . -cpuprofile`, `net/http/pprof`) | `pprof -alloc_space` |
| C / C++ | `perf record`, VTune, Visual Studio profiler, Instruments | `heaptrack`, Valgrind massif |
| Windows (any) | Windows Performance Recorder + Analyzer, Visual Studio profiler | same |
| Rust (after porting) | `cargo flamegraph`, `samply`, `criterion` | `dhat`, `heaptrack` |

If no profiler is available and the user cannot install one, fall back to manual timing: wrap suspect functions with high-resolution timers (`time.perf_counter`, `performance.now`, `Stopwatch`), aggregate over many calls, and say clearly that the data is coarse.

## 3. Normalized `profile.json` schema

`scan_hotspots.py --profile` reads this file. Convert whatever the profiler produced into it by hand or with a short script:

```json
{
  "workload": "python app.py data/orders_1m.csv",
  "total_seconds": 41.8,
  "samples": [
    {"file": "src/parser.py", "function": "parse_rows", "self_percent": 58.2, "total_percent": 71.0},
    {"file": "src/report.py", "function": "build", "self_percent": 9.4, "total_percent": 12.0}
  ]
}
```

- `self_percent`: time inside the function itself, excluding callees. Rank by this.
- `total_percent`: including callees. Useful for choosing the *boundary* to port (a parent whose children are all hot may be the better unit).
- Include the top 15-25 entries; the long tail does not matter.
- Function names should match source names (`Class.method` or `method` both work).

## 4. Reading results

- **Self time** shows where the work actually happens; **total time** shows which call tree to cut at.
- **Amdahl's law:** if a function takes fraction `p` of runtime and you make it `s` times faster, the whole program speeds up by `1 / ((1 - p) + p / s)`. Even with infinite `s`, the cap is `1 / (1 - p)`. A function at 20% can never give more than 1.25x overall.
- Wide, flat profiles (no function above ~10%) mean there is no single hotspot; Rust porting is unlikely to pay off. Say so.
- Time in the interpreter's own machinery (GC, import, JIT warm-up, startup) is not a Rust target. Fix workload shape or startup separately.
- Time waiting on I/O, locks, network or the database shows up as idle/blocked: not a Rust target.

## 5. Memory profiling

Memory goals (peak RSS, allocations, GC pauses) need their own measurement:
- Peak RSS comes from `scripts/run_baseline.py` (`peak_rss_kb_median`).
- For GC-heavy hosts (C#, JS, Java), count allocations per frame/request, not just peak. Rust helps when the cost is object churn and boxing; it does not help if the data itself is large.
- Record the baseline before porting; compare after with `compare_bench.py`.
