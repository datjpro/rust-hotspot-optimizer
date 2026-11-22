# C# / .NET / Unity → Rust with a C ABI (`cdylib` + P/Invoke)

## When to use
C# hotspots in .NET apps or Unity games: pathfinding, procedural generation, mesh/texture processing, parsing, simulation. First confirm the cheaper C# options (Span<T>, structs, object pooling, Burst/Jobs in Unity); they often close the gap without a native plugin.

## Setup
```bash
python scripts/scaffold_rust_crate.py --bridge ffi --name fast_core --out native/fast_core
cd native/fast_core
cargo build --release     # target/release/fast_core.dll | libfast_core.so | libfast_core.dylib
cargo test
```
The scaffold also writes `NativeMethods.cs` (P/Invoke declarations plus a safe wrapper).

## Pattern
1. Logic in `mod core`. Export `extern "C"` functions with `#[no_mangle]`.
2. Signatures use only C-compatible types: integers, floats, pointers, lengths. No `String`, `Vec`, or generics.
3. Return a **status code**; write results through caller-provided output pointers or buffers.
4. Wrap each export in `catch_unwind` (the template does) so a Rust bug is an error code, not a process crash.
5. The caller allocates and frees its own buffers. If Rust allocates for the caller, export a matching `free` function.

## Data passing
| C# | Rust | Notes |
|---|---|---|
| `int`, `long`, `double`, `bool` (as `byte`) | `i32`, `i64`, `f64`, `u8` | blittable, cheap |
| `double[]` / `float[]` / `byte[]` | `*const f64` + `usize` len | pinned during the call, zero-copy |
| `NativeArray<T>` (Unity) | pointer from `GetUnsafePtr` + len | zero-copy; use with care |
| `string` | UTF-8 `byte[]` + len | marshal explicitly; avoid default `CharSet` surprises |
| structs | `#[repr(C)]` structs | field order and padding must match |

Avoid callbacks from Rust into C#; if unavoidable, use `[UnmanagedFunctionPointer]` delegates kept alive for the call.

## Wiring with fallback
```csharp
public static double SumSquares(double[] values)
{
    if (Environment.GetEnvironmentVariable("RUST_OPT_DISABLE") == "1") return SumSquaresLegacy(values);
    try { return FastCoreNative.SumSquares(values); }
    catch (DllNotFoundException) { return SumSquaresLegacy(values); }
    catch (EntryPointNotFoundException) { return SumSquaresLegacy(values); }
}
```

## Unity specifics
- Place libraries in `Assets/Plugins/<platform>/` (e.g. `x86_64`, `Android/arm64-v8a`) and set per-platform import settings.
- The editor keeps native libraries loaded; to rebuild the Rust library, close the editor or use a copy-on-build script.
- **IL2CPP / iOS**: needs static linking and `__Internal` for P/Invoke names. **WebGL**: native plugins are not supported; stay with C#/Burst.
- Never call Unity APIs from native code. Do the heavy work in Rust on buffers, return results to C#.
- Use background threads for long calls; a native call on the main thread blocks the frame.

## Pitfalls
- Calling convention mismatch (`Cdecl` vs `StdCall`) corrupts the stack on 32-bit; default to `Cdecl` + `extern "C"`.
- `bool` size differs between C# and Rust; use `u8`/`byte`.
- A fine-grained call per entity per frame loses to pure C#. Pass whole arrays and process in one call.
