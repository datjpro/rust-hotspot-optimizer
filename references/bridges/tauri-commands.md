# Tauri app → Rust commands (no FFI)

## When to use
The project is a Tauri app (`src-tauri/` exists). The backend is already Rust, so a hotspot that currently runs in the JS/TS frontend (or in a slow backend path) can become a native Rust command with no binding layer.

## Setup
```bash
python scripts/scaffold_rust_crate.py --bridge tauri --name fast_core --out src-tauri/src
```
This writes `src-tauri/src/commands.rs` from the template. Rename it to the module name you want, then register it as shown in its header comment:
```rust
mod fast_core;
tauri::Builder::default()
    .invoke_handler(tauri::generate_handler![fast_core::sum_squares])
```
Check the Tauri docs for your version (v1 vs v2 differ in setup, permissions, and the `invoke` import path).

## Pattern
1. Logic in `mod core` (plain Rust, unit-testable).
2. Expose it as an `async` `#[tauri::command]` using `tauri::async_runtime::spawn_blocking` so CPU work stays off the main thread.
3. Call from the frontend with `invoke("sum_squares", { values })`.
4. Return `Result<T, String>` (or a serializable error type) and surface it in the UI the way the old JS error was surfaced.

## Data passing
- Arguments and results cross the IPC boundary as JSON: great for small payloads, slow for large arrays or binary data.
- For big inputs pass a **file path** (or id) and let Rust read the file; for big outputs write a file or return bytes with `tauri::ipc::Response`.
- Streaming or progress: emit events (`app.emit`) or use channels instead of one giant response.

## Fallback and rollback
Keep the original frontend function and choose at runtime:
```ts
import { invoke } from "@tauri-apps/api/core";
export async function sumSquares(values: number[]) {
  if (import.meta.env.VITE_RUST_OPT_DISABLE === "1") return legacySumSquares(values);
  return invoke<number>("sum_squares", { values });
}
```

## Pitfalls
- Sync commands run on the main thread and freeze the UI if they are slow.
- Permissions (v2 capabilities) must allow the command if you use plugins; plain app commands need none beyond registration.
- Do not hold large state in `Mutex` across `.await` points; copy what you need or use channels.
- Per-keystroke or per-frame `invoke` calls are dominated by IPC latency; batch.
