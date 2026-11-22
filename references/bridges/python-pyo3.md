# Python → Rust with PyO3 + maturin

## When to use
Python hotspots that are pure-Python CPU loops (parsing, text processing, numeric loops that NumPy cannot vectorize). Not for code that is already NumPy/pandas-vectorized.

## Setup
```bash
pip install maturin
python scripts/scaffold_rust_crate.py --bridge pyo3 --name fast_core --out rust/fast_core
cd rust/fast_core
maturin develop --release     # builds and installs into the active virtualenv
cargo test                    # unit tests of the pure Rust core
```
Check the PyO3 user guide for the newest version; the template targets the `Bound<'_, PyModule>` API.

## Pattern
1. Keep logic in `mod core` (no `pyo3` types). Wrap with `#[pyfunction]`.
2. Match the legacy Python signature, return type, and exceptions.
3. Release the GIL for long pure-Rust work (`py.allow_threads(|| ...)`, called `detach` in newer versions).
4. Register functions in the `#[pymodule]`.

## Data passing
| Python | Rust arg | Cost |
|---|---|---|
| `int`, `float`, `bool`, `str` | `i64`, `f64`, `bool`, `&str` / `String` | cheap scalar; `String` copies |
| `list[float]` | `Vec<f64>` | copies each element; fine for moderate sizes |
| NumPy array | `PyReadonlyArray1<f64>` from the `numpy` crate | zero-copy, best for bulk numeric data |
| `bytes` | `&[u8]` | zero-copy borrow |
| `dict` | `HashMap<String, T>` or a `#[derive(FromPyObject)]` struct | copies; keep small |

## Errors
Return `PyResult<T>`; map failures to the exception types the legacy code raised:
```rust
use pyo3::exceptions::PyValueError;
fn parse(line: &str) -> PyResult<i64> {
    line.trim().parse::<i64>().map_err(|e| PyValueError::new_err(format!("bad number: {e}")))
}
```

## Wiring with fallback (keep legacy selectable)
```python
# parser.py
import os
try:
    if os.environ.get("RUST_OPT_DISABLE") == "1":
        raise ImportError("Rust acceleration disabled")
    from fast_core import parse_rows as _parse_rows   # Rust
    BACKEND = "rust"
except ImportError:
    from ._parser_legacy import parse_rows as _parse_rows  # original implementation, unchanged
    BACKEND = "python"

def parse_rows(rows):
    return _parse_rows(rows)
```
Move the original function to `_parser_legacy.py` unchanged. Parity tests import both.

## Packaging
- Local: `maturin build --release` creates a wheel in `target/wheels/`.
- Multi-platform: GitHub Actions `PyO3/maturin-action` or `cibuildwheel`.
- Declare the build in `pyproject.toml` (`build-backend = "maturin"`) for mixed Python/Rust projects, or ship the Rust crate as a separate wheel dependency.

## Pitfalls
- Per-element calls from Python loops are slower than Python. Pass the whole collection.
- `cargo test` fails to link if `extension-module` is always on; the template keeps it behind a feature for that reason.
- Do not set `panic = "abort"`.
