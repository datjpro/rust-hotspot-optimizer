# Golden / characterization test template

Purpose: freeze the **current** behavior of a hotspot before porting, so the Rust version can be proven equivalent. The legacy code is the oracle, even where it looks buggy; changing behavior is a separate decision for the user, not a side effect of optimization.

Fill one copy per hotspot and save as `.rust-opt/golden/<function>.md`.

## 1. Contract

- Function: `<module.function>`
- Signature: `<args and types> -> <return type>`
- Side effects (files, globals, in-place mutation, logging): `<none | list>`
- Errors raised and when: `<type: condition>`
- Determinism: `<deterministic | depends on time/random/env>` (fix seeds/clocks for tests)

## 2. Input categories (cover every row that applies)

| Category | Example inputs | Captured? |
|---|---|---|
| Typical real data (sampled from production-like input) | | [ ] |
| Empty / zero-length / single element | | [ ] |
| Very large (the benchmark workload) | | [ ] |
| Boundary numbers (0, -1, max int, 2^53+1, very small/large floats, NaN, inf, -0.0) | | [ ] |
| Unicode (accents, emoji, combining marks, RTL, surrogate pairs, mixed case) | | [ ] |
| Whitespace, newlines (`\n`, `\r\n`), trailing separators, BOM | | [ ] |
| Duplicates and ordering (ties, equal keys, stable-sort expectations) | | [ ] |
| Malformed / invalid input (each error the legacy code raises) | | [ ] |
| Null / None / undefined / missing fields | | [ ] |
| Mutation: input object modified in place? | | [ ] |
| Dates/time zones, locale-sensitive behavior | | [ ] |

## 3. Capturing the oracle

1. Create the corpus folder `tests/corpus/<function>/` with one input per file (`case-001.json`, ...). Include at least 30 varied cases plus the large benchmark input.
2. Write a tiny **driver** for the legacy implementation: reads one input file, calls the function, prints the result as JSON (sorted keys, stable formatting) to stdout. Errors: print message to stderr and exit non-zero.
3. Write the same driver for the candidate (Rust-backed) path. Both drivers must differ only in which implementation they call.
4. Run `python scripts/parity_check.py --legacy "<legacy driver> {input}" --candidate "<candidate driver> {input}" --inputs tests/corpus/<function>`. Before porting, run the legacy driver against itself to check that the harness is deterministic (it must pass 100%).

## 4. Comparison rules

- Floats: tolerance `<1e-9 | exact>`; reason: `<why>`
- Ordering: `<must match | set-equal>`
- Ignored fields (timestamps, ids): `<none | list>` (`--ignore-key`)
- Error behavior: both must fail on the same inputs (the harness checks exit codes); messages `<must match | need not match>`

## 5. Gate

- [ ] Legacy driver is deterministic and passes against itself
- [ ] Corpus covers every applicable category above
- [ ] Existing project tests pass on the legacy code
- [ ] Parity corpus and drivers committed (or stored where the user chooses)
