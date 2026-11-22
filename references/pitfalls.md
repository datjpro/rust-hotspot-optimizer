# Pitfalls and failure modes

Read this when a port is slower than expected, fails to build, or before shipping.

## Contents
1. Toolchain
2. Boundary (FFI) cost
3. Concurrency and runtime interaction
4. Build, packaging, and CI
5. Platform limits
6. Safety and maintenance
7. Quick diagnosis table

## 1. Toolchain

- **Rust**: install with `rustup` (https://rustup.rs). On Windows, rustup also needs the **MSVC Build Tools** ("Desktop development with C++"). Verify: `cargo --version`, `rustc --version`.
- **Python bridge**: `pip install maturin`. **Node bridge**: Node 18+ and `@napi-rs/cli`. **WASM**: `cargo install wasm-pack` and the `wasm32-unknown-unknown` target (`rustup target add wasm32-unknown-unknown`).
- If the sandbox or user machine cannot install Rust, do not fake results: deliver the scaffolded crate, state that it was not compiled or benchmarked, and list the exact commands for the user to run.

## 2. Boundary (FFI) cost

The most common reason a port disappoints.
- Every call converts arguments and results. Converting a `list[str]` of a million items can cost more than the work itself.
- **Fix by batching**: one call with all the data, not one call per item. Better: move the entire loop (and the loop's data preparation) into Rust.
- Pass bulk numeric data as typed buffers (NumPy arrays, `Float64Array`, `double[]`, bytes) to avoid per-element conversion.
- Return compact results (a summary, indices, a single buffer), not millions of host objects.
- Do not call back into the host from inside the Rust hot loop; each callback pays the boundary twice.

## 3. Concurrency and runtime interaction

- **Python GIL**: release it during pure-Rust work (`py.allow_threads` / `detach`) or other threads stall. Do not touch Python objects while released.
- **Node**: heavy work on the main thread blocks the event loop. Use napi `AsyncTask` / `spawn_blocking` / worker threads for long calls.
- **Tauri / async hosts**: use `spawn_blocking` for CPU-heavy commands so the UI stays responsive.
- **Unity**: native calls on the main thread block the frame; for long work use a background thread and poll for results. Native code must not call Unity APIs.
- **rayon inside a host with its own thread pool** can oversubscribe cores; make thread count configurable.

## 4. Build, packaging, and CI

- Native artifacts are **per platform and architecture** (Windows x64/arm64, macOS x64/arm64, Linux glibc/musl). Decide the target matrix with the user in Phase 0.
- Python: build wheels with `maturin build --release` locally; use `maturin-action` / `cibuildwheel` in CI for multi-platform wheels. Node: napi-rs generates per-platform packages with the CLI. Unity: one plugin per platform in `Assets/Plugins/<platform>/`, with import settings per platform.
- Add the Rust build to CI and to the README ("requires Rust 1.xx+"). Pin the toolchain with `rust-toolchain.toml`.
- Commit `Cargo.lock` for binaries and cdylibs.
- Keep a **pure-host fallback** so a platform without a prebuilt binary still works (slowly) instead of crashing at import.

## 5. Platform limits

- **Unity WebGL** cannot load arbitrary native plugins; consider porting to a WASM-compatible approach or leave the hotspot in C# (Burst/Jobs).
- **iOS** requires static linking; **Android** needs per-ABI `.so` files (`cargo-ndk`).
- **Sandboxed / serverless** environments may forbid loading native modules or spawning subprocesses; check before choosing a sidecar or addon.
- **Browser WASM** has no threads by default and a copy cost for every typed-array transfer.

## 6. Safety and maintenance

- Keep `unsafe` to the FFI shim; document the safety contract on each exported function (see the `ffi` template).
- Run `cargo clippy -- -D warnings` and `cargo fmt --check`.
- Run tests under Miri or sanitizers if the port contains `unsafe` beyond the boundary shim.
- Record who can maintain the Rust code. A tiny, well-tested Rust module that nobody can debug is a liability; say this in the report if it applies.
- Licenses: list new crate licenses in the report if the project has license constraints.

## 7. Quick diagnosis table

| Symptom | Likely cause | Action |
|---|---|---|
| Rust version is slower | Debug build; per-item boundary calls; conversion of big lists | Build `--release`; batch; typed buffers |
| Speedup is real but end-to-end gain is tiny | Hotspot share was small (Amdahl) | Re-profile; port the next hotspot or stop |
| Parity mismatches on text | Byte vs char vs UTF-16 semantics; normalization | See idioms section 3; add Unicode golden cases |
| Parity mismatches on floats | Summation order, parallel reduction | Use tolerance; or keep sequential order |
| Parity mismatches on ordering | `HashMap` order; unstable sort | `IndexMap`/`BTreeMap`; stable sort |
| Process crashes in host | Panic across FFI; null pointer; wrong calling convention | `catch_unwind`; check signatures; `extern "C"` |
| UI freezes after porting | CPU work on UI/main thread | Offload to a worker / `spawn_blocking` |
| Works locally, fails in CI/users | Missing platform build; glibc/musl mismatch | Build matrix; fallback path |
| Memory grew | Copies of large inputs at the boundary; leaked buffers | Borrow/zero-copy; free what Rust allocates for the host |
