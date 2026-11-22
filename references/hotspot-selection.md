# Hotspot selection and scoring

Read this in Phase 3. It decides **what** to port, and just as importantly **what not to**.

## Contents
1. Cheaper-fix checklist (do this first)
2. Good and bad Rust candidates
3. Scoring
4. Estimating gain honestly
5. Presenting the ranked table
6. Decision tree

## 1. Cheaper-fix checklist

Run each hotspot through this list before proposing Rust. A fix that removes the hotspot in the original language is cheaper, safer, and keeps the codebase single-language.

1. **Algorithm / data structure**: list membership in a loop (use a set/dict), repeated sorting, nested loops over the same data, quadratic string building, repeated full scans.
2. **Hoisting**: precompile regexes, parse once, allocate once, move invariants out of loops.
3. **Caching / memoization** of pure results.
4. **Batching** I/O, DB queries, serialization.
5. **Vectorization / native libraries**: NumPy/pandas/polars in Python, typed arrays in JS, `Span<T>`/Burst/Jobs in Unity C#.
6. **Concurrency** for I/O-bound work (async, thread pool).

If the profile is still dominated by the function after these, it is a real candidate.

## 2. Good and bad candidates

**Good** (CPU-bound, self-contained, data in and data out):
- Parsing and tokenizing (custom formats, large JSON/CSV/logs, markup)
- String and text processing at scale; regex-heavy pipelines with simple patterns
- Numeric loops that cannot be vectorized; simulation, physics, pathfinding, graph algorithms
- Image/audio/video buffer processing; compression, hashing, crypto primitives
- Serialization/deserialization of custom binary formats
- Diffing, search indexes, sorting with custom comparators on large data

**Bad** (poor payoff or high risk):
- I/O, network, database, disk waits
- Code dominated by calls into native libraries already (NumPy, OpenCV, native addons)
- Glue code, orchestration, UI, business rules with heavy host-framework coupling
- Code with many callbacks into the host language per iteration (FFI round-trips dominate)
- Functions with tangled global state or reflection/dynamic features
- Anything under ~10% of runtime

## 3. Scoring

For each candidate fill a row; `scan_hotspots.py` provides the static score and measured percent, you add judgment for the rest.

| Factor | How to judge | Weight |
|---|---|---|
| Runtime share | `self_percent` from the profile; below 10% = skip | high |
| CPU-bound-ness | Compute loops vs waiting; no I/O inside | high |
| Boundary cleanliness | Pure function or small module, plain data in/out | high |
| Call granularity | Few coarse calls = good; millions of tiny calls = move the loop into Rust | medium |
| Data crossing size | Bytes copied per call across the boundary vs work done per call | medium |
| Test coverage / observability | Existing tests, easy to capture golden outputs | medium |
| Semantic risk | Unicode, big integers, float rounding, ordering, regex dialect, dynamic typing | medium |
| Maintenance fit | Can the team build and debug Rust? CI impact? | medium |

Priority = (runtime share × CPU-bound-ness × boundary cleanliness) ÷ (FFI cost × semantic risk). Use it to **rank**, not as a precise number.

## 4. Estimating gain honestly

Always report the Amdahl cap (`1 / (1 - p)`). For per-function gains, typical ranges for *pure CPU loops* are rough guides, not promises; measure before quoting anything to the user:

| Source | Typical range for a ported pure-CPU hotspot |
|---|---|
| Pure Python loops | 10-100x |
| Python with partial vectorization | 1.5-5x |
| Node.js hot code (JIT already good) | 1.5-10x; more for string/byte parsing |
| Browser JS to WASM | 1-3x, sometimes slower due to copy cost |
| C# / Java (JIT/AOT) | 1-3x; often matched by better C# (Span, structs, Burst) |
| Allocation-heavy managed code | memory and GC-pause gains can exceed raw speed gains |

State the range as "typical, unverified for this code" until the benchmark exists.

## 5. Presenting the ranked table

Show the user:

| # | Function | Runtime | Why slow | Cheaper fix? | Cap (Amdahl) | FFI cost | Risk | Recommendation |
|---|---|---|---|---|---|---|---|---|

Group recommendations into **Port now**, **Fix cheaper first**, **Skip (and why)**. Ask the user to approve the "Port now" list and record it in `hotspots.json` (`"approved": true`).

## 6. Decision tree

```
Is it >= ~10% of measured runtime?          no  -> skip
Is it CPU-bound (not waiting)?              no  -> fix I/O / concurrency instead
Does a cheaper fix remove it?               yes -> do that, re-profile
Is the boundary clean (plain data in/out)?  no  -> refactor to a clean boundary first, or widen the unit
Calls many times with tiny data?            yes -> move the whole loop into Rust
Can the platform load native code / WASM?   no  -> stop, report
Otherwise                                   -> port, one hotspot at a time
```
