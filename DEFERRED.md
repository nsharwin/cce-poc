# Deferred POC Gaps

This file records POC PRD requirements not completed by the current implementation slice. Determinism gates are not weakened; incomplete requirements stay visible here until implemented.

## Analyzer Pinning

- `PREQ-A-1` / `REQ-A-1` (partial): TypeScript now uses real `tree-sitter-language-pack` grammar. Python keeps using `ast`. `lizard` and `scc` metrics and artifact digest verification are not wired yet — wheel digests are still validated for shape only.
- `PREQ-A-2` / `REQ-A-2`: Digest-pinned Dockerfile with hash-pinned apt and pip installs is not present yet.
- `PREQ-A-3` / `REQ-A-3`: Runtime `--network=none` enforcement is not implemented yet.
- `PREQ-A-4` / `REQ-A-4`: ✅ Closed. Grammar-stability gate lives in `tests/test_grammar_stability.py` with frozen RFC 8785 goldens under `tests/fixtures/grammar_spans/`, shared walker at `tests/_grammar_spans.py`, and regen via `CCE_UPDATE_GRAMMAR_GOLDENS=1` / `scripts/regenerate_grammar_spans.py`.

## Cross-Machine Gates

- `PREQ-S-7` / `REQ-S-7`: GitHub Actions matrix workflow is scaffolded, but matching record-hash artifact comparison across runners is not implemented yet.
- `POC-GATE-3`: Seven-day nightly stability run is not implemented yet.
- `POC-GATE-4`: External reviewer reproduction is pending.
- `POC-GATE-8`: 100k LoC performance fixture and timing gate are pending.

## Git And Isolation

- `PREQ-X-1` / `REQ-X-2`: Git version check for `>= 2.50.1` is not enforced yet.
- `PREQ-X-2` / `REQ-X-3`: Remote clone uses the required hardened flags, but local commit mode currently trusts an existing local checkout when reading files.
- `PREQ-X-3` / `REQ-X-5`: CI curl egress failure check after clone is not implemented yet.
- `PREQ-X-4` / `REQ-X-1`: Docker-vs-Firecracker isolation gap still needs a fuller design note once Docker exists.
- `POC-GATE-6`: Submodule-trap fixture and test are not implemented yet.

## Storage Sidecars

- `PREQ-D-2` / `REQ-D-3`: ✅ Closed. `<record_hash>.raw.json` written as RFC 8785 canonical bytes by `src/cce/cli.py::_write_outputs`; byte contract pinned in `tests/test_cli.py::test_sidecar_files_have_canonical_contents`.
- `PREQ-D-3` / `REQ-D-4`: ✅ Closed. `<record_hash>.sha256` sibling emitted as `sha256:<hex>\n` of the canonical record bytes by the same `_write_outputs`; same test asserts byte contract.

## Observability

- `PREQ-O-1` / `REQ-O-1`: OpenTelemetry stdout exporter spans are not implemented yet. The CLI currently prints wall-clock stage timings only.

## Parent PRD Items Out Of POC Scope

- `REQ-S-6`: PR delta scoring.
- `REQ-L-*`: LLM narrative lane.
- `REQ-I-*`: GitHub App, GitLab, Bitbucket integrations.
- `REQ-D-2`: ClickHouse storage.
- `REQ-D-5`: Audit log export.
- `REQ-O-2`: Distributed trace propagation.
- `NFR-SCALE-*`, `NFR-AVAIL-*`, `NFR-COMP-*`: Production scale, availability, and compliance targets.
