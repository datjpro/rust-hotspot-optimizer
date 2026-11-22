# Any language → Rust sidecar binary (stdin/stdout)

## When to use
- The host language has no good binding story (Ruby, PHP, Java, Go, shell scripts, legacy runtimes).
- The hotspot is a **coarse** job: one call processes a large input and takes long enough that process spawn cost (a few ms) does not matter.
- You want crash isolation or to reuse the same binary from several languages and from the command line.

## Setup
```bash
python scripts/scaffold_rust_crate.py --bridge sidecar --name fast_core --out tools/fast_core
cd tools/fast_core
cargo build --release
echo '{"values":[1,2,3]}' | target/release/fast_core      # {"result":14.0}
```

## Contract design
- **Input**: one JSON document on stdin, or a file path argument for large data. **Output**: one JSON document on stdout, nothing else.
- **Errors**: message on stderr, non-zero exit code (the template uses 2 = bad input, 3 = output error). The host maps these to its own exceptions.
- Version the schema (`"version": 1`) once more than one caller exists.
- For large payloads prefer files or newline-delimited JSON streaming over one huge string.
- For many small requests keep one long-lived process and speak a line-delimited protocol instead of spawning per request.

## Host-side wiring (Python example, any language is similar)
```python
import json, os, subprocess

def sum_squares(values):
    if os.environ.get("RUST_OPT_DISABLE") == "1":
        return _sum_squares_legacy(values)
    proc = subprocess.run([BIN_PATH], input=json.dumps({"values": values}),
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise ValueError(proc.stderr.strip())
    return json.loads(proc.stdout)["result"]
```

## Packaging
Ship the binary per platform next to the app, or build it in CI and download at install. Provide the legacy path as fallback when the binary for the platform is missing.

## Pitfalls
- Spawn + serialization overhead makes per-item calls slow; batch.
- JSON floats are decimal text; expect last-digit differences unless you compare with a tolerance.
- stdout must contain only the payload: log to stderr.
- Make the binary path configurable and resolve it relative to the app, not the working directory.
