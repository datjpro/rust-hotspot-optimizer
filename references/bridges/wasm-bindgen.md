# Browser / web frontend → Rust with WebAssembly (wasm-bindgen)

## When to use
Browser hotspots with substantial compute per call: image/audio processing, parsing large payloads, compression, physics, search. Small or chatty calls often lose to JIT-compiled JS because of copy costs.

## Setup
```bash
rustup target add wasm32-unknown-unknown
cargo install wasm-pack
python scripts/scaffold_rust_crate.py --bridge wasm --name fast_core --out wasm/fast_core
cd wasm/fast_core
wasm-pack build --release --target web      # or --target bundler for webpack/vite
```
Output goes to `pkg/` (JS glue, `.wasm`, `.d.ts`).

## Pattern
1. Logic in `mod core`; export with `#[wasm_bindgen]`.
2. One call per batch of work. Pass typed arrays (`Float64Array`, `Uint8Array`) as `&[f64]` / `&[u8]`.
3. Run long calls in a **Web Worker** so the UI thread stays responsive.
4. Initialize once at startup (`await init()`), not per call.

## Using it from the frontend
```js
import init, { sum_squares } from "./pkg/fast_core.js";
await init();
const result = sum_squares(new Float64Array(data));
```
With fallback:
```js
let sumSquares = legacySumSquares;
try { await init(); sumSquares = sum_squares; } catch { /* keep JS version */ }
```

## Data passing and cost
- `&[T]` parameters copy the typed array into WASM memory; large results copy back out. Keep the data in WASM memory across calls when possible (return a handle/struct and call methods on it).
- Strings convert between UTF-16 and UTF-8 each call.
- For many small items, pack them into one buffer with an offset table.

## Pitfalls
- Bundle size: keep dependencies lean (`opt-level = "s"` or `"z"` if size matters more than speed; `wasm-opt` shrinks further).
- No threads by default; `wasm-bindgen-rayon` needs cross-origin isolation headers.
- Panics print poorly; add `console_error_panic_hook` during development.
- Measure against the existing JS with realistic data; WASM is not automatically faster.
