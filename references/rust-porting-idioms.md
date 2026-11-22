# Rust porting idioms and semantic traps

Read this in Phase 5 before writing the Rust version. Behavior drift almost always comes from semantic differences, not from logic errors.

## Contents
1. Structure of the port
2. Types and ownership
3. Semantic differences to check
4. Performance idioms
5. Error handling
6. Release profile
7. Dependencies

## 1. Structure of the port

- Put the algorithm in a **pure Rust module with no host types** (`mod core`), and keep the binding layer thin. This makes `cargo test` possible without the host runtime and lets you swap bridges later.
- Port the smallest unit that includes the hot loop. Keep the same function name, argument order, return shape, and error cases.
- Translate the legacy code **literally first**, get parity, *then* optimize. Clever rewrites before parity create unexplainable diffs.

## 2. Types and ownership

| Host data | Rust parameter | Notes |
|---|---|---|
| string | `&str` | UTF-8 in Rust; see section 3 for indexing/length semantics |
| bytes / buffer | `&[u8]` | borrow, don't copy |
| list of numbers | `&[f64]`, `&[i64]` | typed arrays (JS `Float64Array`, NumPy) allow zero-copy |
| list of strings | `Vec<String>` or `&[&str]` | conversion cost is per element; batch |
| dict / object | struct with `serde` or `HashMap` | decide ordering needs (see below) |
| optional / None / null / undefined | `Option<T>` | map explicitly, don't use sentinel values |

- Borrow inputs (`&T`), return owned outputs. Avoid `.clone()` and `.to_string()` inside loops; if the borrow checker fights you, restructure with indices instead of cloning.
- Use `Vec::with_capacity(n)` when the output size is known; reuse buffers across iterations.
- Prefer iterators (`iter().map().sum()`) over index loops; they optimize well and skip bounds checks.

## 3. Semantic differences to check

Each of these has caused a silent parity bug. Write a golden test for every one that applies.

- **Integer overflow and size**: Python ints are unbounded; JS numbers are f64 (exact only to 2^53); C# `int` wraps unless `checked`. Rust panics in debug and wraps in release unless you use `checked_*`, `wrapping_*`, or `saturating_*`. Pick the operation that matches legacy behavior and use `i64`/`u64`/`i128` deliberately.
- **Floating point**: summation order changes results. Parallel reductions (`rayon`) are not bit-identical to a sequential loop. Compare with a tolerance (`parity_check.py --float-tol`) and say so in the report. `NaN` ordering and `-0.0` behave differently across languages.
- **Strings and Unicode**: Python `len()` counts code points; JS counts UTF-16 units; Rust `str::len()` counts UTF-8 **bytes**. Use `.chars().count()` for code points, and decide how to treat grapheme clusters. Slicing on non-char boundaries panics in Rust.
- **Case and normalization**: `to_lowercase()` / Unicode normalization rules differ from the host's. Locale-sensitive host functions (C# culture, JS `localeCompare`) have no direct equivalent.
- **Regex dialect**: the `regex` crate has no backreferences or lookaround and guarantees linear time. Use `fancy-regex` when legacy patterns need those, or rewrite the pattern and test it.
- **Ordering**: Python `dict` and JS objects keep insertion order; Rust `HashMap` is random. Use `indexmap::IndexMap` or `BTreeMap` to match. `Vec::sort` is stable; `sort_unstable` is not.
- **Sorting and comparison**: string comparison in Rust is bytewise. Host languages may compare by code point, UTF-16 unit, or locale.
- **Truthiness and defaults**: Python/JS truthiness (`0`, `""`, empty list, `None`) does not exist in Rust; every branch must be explicit.
- **Dates and time zones**: use `chrono` or `time` and replicate the legacy rule (naive vs aware, rounding, DST). Prefer passing timestamps instead of reimplementing calendars.
- **Mutability and aliasing**: if the host mutates arguments in place (Python lists, JS arrays), the Rust version must do the same visible thing, or document that it returns a new value and update the wrapper.
- **Exceptions vs Results**: see section 5.

## 4. Performance idioms

- Move the **whole loop** into Rust when the host calls the function many times with small inputs. Crossing the boundary per element destroys the gain.
- `rayon` (`par_iter`) for independent per-item work on large inputs; measure, since small inputs get slower. Keep thread count controllable.
- Avoid allocating `String` per item in hot paths; work on `&str` slices or bytes.
- Use `HashMap` with a faster hasher (`ahash`, `rustc-hash`) when keys are trusted and hashing shows up in the profile; keep the default hasher for untrusted input (hash-flooding).
- Parse with `serde_json` (or `simd-json` after measuring); avoid building intermediate `serde_json::Value` when a typed struct works.
- Do not use `unsafe` for speed until a profile shows bounds checks matter; then prefer `get_unchecked` in a small, commented, tested block.

## 5. Error handling

- Return `Result<T, E>` inside Rust. Convert at the boundary to the host's native error type with the **same message and type** callers already catch (PyO3: `PyValueError`; napi: `napi::Error`; FFI: status codes; sidecar: exit code + stderr).
- Never let a panic cross the boundary. PyO3 and napi convert panics into host exceptions; for raw FFI wrap each export in `std::panic::catch_unwind` (the template does this).
- Do not use `unwrap()`/`expect()` on data that comes from the host.

## 6. Release profile

```toml
[profile.release]
opt-level = 3
lto = "fat"
codegen-units = 1
strip = true
# panic = "abort"   # only for standalone binaries; NOT for PyO3 / FFI libraries
```

- `target-cpu=native` makes builds non-portable; do not use it for anything you distribute.
- Always benchmark `--release`. Debug builds are 10-100x slower and invalidate every comparison.

## 7. Dependencies

Keep the dependency list short and justified in the report. Prefer well-maintained crates (`serde`, `rayon`, `regex`, `indexmap`, `memchr`, `thiserror`). Check the current version and docs for the bridge crate (`pyo3`, `napi`, `wasm-bindgen`) before writing code, because their APIs change between releases.
