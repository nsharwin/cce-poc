# CCE POC

Proof of concept for deterministic code complexity scoring. This slice implements the P0 scoring core from the POC PRD:

- `PREQ-S-1`: scoring primitives are pure and have no I/O, clocks, randomness, or environment reads.
- `PREQ-S-2`: scoring arithmetic uses `decimal.Decimal` with precision 28 and `ROUND_HALF_EVEN`.
- `PREQ-S-3`: JSON hashing uses RFC 8785 JCS via the pinned `rfc8785` package.
- `PREQ-S-4`: `record_hash` is computed as `sha256(spec_hash || commit_sha || canonical_metrics_json || tool_digests_json)`.
- `PREQ-S-5`: normalization cuts come from `scoring-spec.yaml`.
- `PREQ-S-6`: `tests/determinism_100x.py` asserts 100 sequential runs produce one hash.
- `PREQ-D-1`, `PREQ-D-2`, `PREQ-D-3`: CLI writes record, raw analyzer output, and a sibling JSON checksum.
- `PREQ-O-2`: CLI prints stage timings on stderr.

## Setup

```bash
uv sync
uv run pytest -q
uv run pytest tests/determinism_100x.py -q
```

## CLI

Score a local git repository:

```bash
uv run cce score --spec ./scoring-spec.yaml --repo /path/to/repo --mode repo
```

Score a specific commit:

```bash
uv run cce score --spec ./scoring-spec.yaml --repo /path/to/repo --mode commit --commit <40-hex-sha>
```

Verify a record:

```bash
uv run cce verify --record ./cce-out/<record_hash>.json
```

The CLI writes:

- `./cce-out/<record_hash>.json`
- `./cce-out/<record_hash>.raw.json`
- `./cce-out/<record_hash>.sha256`

## Current Boundary

This is the deterministic scoring nucleus plus a deterministic built-in source analyzer for Python and TypeScript fixtures. It does not yet claim final analyzer equivalence with pinned `tree-sitter`, `lizard`, or `scc` binaries. Those gaps are tracked in `DEFERRED.md`.
