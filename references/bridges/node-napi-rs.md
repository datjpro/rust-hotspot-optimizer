# Node.js / Electron → Rust with napi-rs

## When to use
Node or Electron hotspots: parsing, byte/string processing, hashing, compression, heavy transforms that stay slow after V8 optimization. For browser code use `wasm-bindgen.md` instead.

## Setup
```bash
python scripts/scaffold_rust_crate.py --bridge napi --name fast_core --out native/fast_core
cd native/fast_core
npm install        # or pnpm install
npm run build      # produces fast_core.<platform>.node, index.js, index.d.ts
cargo test
```
Check the napi-rs docs for the current major version; the template uses `napi` 2.x with `#[napi]` macros.

## Pattern
1. Logic in `mod core` (plain Rust), wrapper with `#[napi]`.
2. Use `Float64Array`, `Uint8Array`, `Buffer` for bulk data to avoid per-element conversion.
3. For long calls, return a `Promise` with `AsyncTask` or `tokio` so the event loop stays free.
4. Keep names and return shapes identical to the JS originals; the generated `index.d.ts` gives TypeScript types.

## Data passing
| JS | Rust arg | Notes |
|---|---|---|
| number / boolean / string | `f64`/`i64`, `bool`, `String` | strings copy (UTF-16 → UTF-8) |
| `Float64Array` etc. | `Float64Array` | shared, near zero-copy |
| `Buffer` / `Uint8Array` | `Buffer` / `Uint8Array` | borrow as `&[u8]` |
| object | `#[napi(object)]` struct | copies fields; keep shallow |
| array of objects | avoid; flatten to typed arrays | per-object conversion is the usual hidden cost |

## Errors
Return `napi::Result<T>`; build errors with `napi::Error::new(Status::InvalidArg, "message")` matching the legacy error messages callers rely on.

## Wiring with fallback
```js
// parser.js
let impl;
try {
  if (process.env.RUST_OPT_DISABLE === "1") throw new Error("disabled");
  impl = require("./native/fast_core");        // Rust
} catch {
  impl = require("./parser.legacy");           // original JS, unchanged
}
module.exports = { parseRows: impl.parseRows };
```

## Packaging
- `napi build --platform --release` builds for the current OS/arch; CI matrix builds the rest (`@napi-rs/cli` generates per-platform npm packages).
- Electron: rebuild or use Node-API (N-API) prebuilds; N-API is ABI-stable across Node and Electron versions, which is why napi-rs is preferred over raw `node-gyp` addons.
- With pnpm, add the native package as a workspace dependency or a `file:` dependency.

## Pitfalls
- Passing arrays of objects across the boundary often costs more than the JS work.
- Blocking the main thread inside a native call freezes the app; use async tasks.
- A missing prebuilt binary for the user's platform must fall back to JS, not crash.
