# CCE POC — Production-Readiness Audit

> Audit input for a future spec. Maps every `PREQ-*` and `POC-GATE-*` in
> [`docs/poc-prd.md`](./poc-prd.md) to concrete file-path evidence, gaps, and
> fixes. Use as the **requirements seed** for the follow-up spec that closes
> the remaining holes.

```yaml
audit_doc_version: 0.1.0
audit_date: 2026-05-25
auditor: Kiro
parent_doc: docs/poc-prd.md
status: NOT READY (deterministic nucleus correct; supply-chain pinning,
        fixture coverage, and §11 deliverables incomplete)
intent: "Inputs for a spec that closes POC-GATE-1..8 against poc-prd.md as written."
```

## 1. Executive Verdict

The deterministic core is sound. The falsifiable thesis machinery
(`src/cce/scoring.py`, RFC 8785 canonicalisation, decimal arithmetic,
record-hash byte concatenation) is implemented and tested correctly.

The POC is **not yet production-ready** because:

1. The thesis depends on **sha256-pinned analyzer digests**; the values in
   `scoring-spec.yaml` are placeholders and CI bypasses verification with
   `--verify-digests false`.
2. The matrix only scores **one** of the three required golden fixtures.
3. No **frozen `expected_record_hash`** values are committed; CI proves
   cross-runner agreement, not regression resistance.
4. **PREQ-O-1** literally diverges from the PRD (span names + exporter).
5. Section 11 deliverables `tests/network_isolation.py`, `DEMO.md`, and
   the external reviewer receipt are missing.

## 2. Status Legend

- ✅ IMPLEMENTED — matches PRD verbatim, evidence cited.
- ⚠️ PARTIAL — plumbing correct, values or coverage incomplete.
- ❌ MISSING — deliverable absent.
- 🔥 BROKEN — present but contradicts PRD wording.

## 3. Determinism Core (P0)

```yaml
- id: PREQ-S-1
  status: IMPLEMENTED
  evidence:
    - "src/cce/scoring.py:1-11  # imports: hashlib, re, decimal, contextlib, typing, cce.canonical, cce.spec only"
    - "src/cce/scoring.py:118-123  # _decimal_context() bounds side-effects"
  notes: |
    Grep over scoring.py for `time|random|os|open\(|subprocess|requests|urllib|now\(|datetime`
    returns zero matches. All instrumentation lives in cli.py / otel.py outside the scoring fn.
  gaps: []
  risk: none

- id: PREQ-S-2
  status: IMPLEMENTED
  evidence:
    - "src/cce/scoring.py:14-15  # getcontext().prec = 28; rounding = ROUND_HALF_EVEN"
    - "src/cce/spec.py:174-181   # _reject_floats walks YAML and refuses any float"
    - "tests/test_scoring_core.py:14-25  # asserts context state during normalise"
  gaps: []
  risk: none

- id: PREQ-S-3
  status: IMPLEMENTED
  evidence:
    - "src/cce/canonical.py:8-10  # rfc8785.dumps(value)"
    - "requirements.lock.txt:56-59  # rfc8785==0.1.4 with two sha256 hashes"
    - "Dockerfile:36  # pip install --require-hashes --no-deps"
  gaps: []
  risk: none

- id: PREQ-S-4
  status: IMPLEMENTED
  evidence:
    - "src/cce/scoring.py:103-110  # 4x digest.update with no separators"
    - "tests/test_scoring_core.py:28-49  # independent re-implementation asserts equality"
    - "tests/test_scoring_core.py:52-72  # proves computed_at is excluded"
  gaps: []
  risk: none

- id: PREQ-S-5
  status: IMPLEMENTED
  evidence:
    - "src/cce/spec.py:101-119  # rejects any method != piecewise_linear_frozen_cuts"
    - "src/cce/scoring.py:23-46  # normalise_metric reads only rule.cuts/rule.normalised"
  gaps: []
  risk: none

- id: PREQ-S-6
  status: IMPLEMENTED
  evidence:
    - "tests/determinism_100x.py:7-22  # 100 builds, varying computed_at, asserts len(hashes)==1"
    - ".github/workflows/poc-determinism.yml:35-36  # runs gate on every push/PR"
  gaps: []
  risk: none

- id: PREQ-S-7
  status: PARTIAL
  evidence:
    - ".github/workflows/poc-determinism.yml:13-25   # matrix linux-x86_64 / linux-arm64 / macos-arm64"
    - ".github/workflows/poc-determinism.yml:127-152 # compare-hashes asserts |unique| == 1"
  gaps:
    - "Score steps run with --verify-digests false (workflow lines 60, 113) due to placeholder digests."
    - "Cross-runner equality is proven only for fixtures actually exercised; only simple_python is."
  risk: blocker  # invalidates the thesis until digests + fixtures are real
```

## 4. Analyzer Pinning

```yaml
- id: PREQ-A-1
  status: PARTIAL
  evidence:
    - "src/cce/spec.py:151-167          # validates 5x digest shape sha256:<64 hex>"
    - "src/cce/runtime.py:42-65         # assert_tool_digest hashes binary, raises on mismatch"
    - "src/cce/analyzers/registry.py:70-90  # AnalyzerRegistry.assert_digests dispatch"
    - "tests/test_analyzer_digests.py:21-94 # tamper + happy path through analyse_repo"
  gaps:
    - "scoring-spec.yaml:30-36 carries placeholder digests (2222..., 3333..., 4444..., 5555..., 6666...) and spec_hash sha256:0000..."
    - "default_registry (src/cce/analyzers/registry.py:93-115) only registers builtin Python AST + tree_sitter_language_pack, neither of which has tool_digest_key/binary_resolver, so assert_digests is a no-op in the POC dev image"
    - ".github/workflows/poc-determinism.yml:60,113 and nightly-stability.yml:65 pass --verify-digests false"
    - "TS parser at runtime is tree_sitter_language_pack==0.7.2 (bundled grammars); the pinned_tools.grammars.typescript digest is a label without a binary it actually maps to"
  risk: blocker

- id: PREQ-A-2
  status: PARTIAL
  evidence:
    - "Dockerfile:12     # FROM python:3.12-slim-bookworm@sha256:93ab4b7f..."
    - "Dockerfile:17-31  # apt-get with pinned GIT_VERSION/CA_CERTIFICATES_VERSION/CURL_VERSION"
    - "Dockerfile:36     # pip --require-hashes --no-deps"
    - "requirements.lock.txt  # full sha256 hashes for every wheel/sdist transitively"
  gaps:
    - "Dockerfile:43-44 ARG SCC_SHA256=0000... defaults to zero string; build aborts unless operator passes --build-arg SCC_SHA256=<real>"
    - "Image cannot be reproducibly built from `git clone + docker build .` alone; out-of-tree knowledge required"
  risk: blocker  # for the 'operator can rebuild from sources alone' promise

- id: PREQ-A-3
  status: IMPLEMENTED
  evidence:
    - ".github/workflows/poc-determinism.yml:104-110  # docker run --network=none curl asserted to fail"
    - ".github/workflows/poc-determinism.yml:112-126  # score under --network=none + CCE_REQUIRE_NETWORK_ISOLATED=1"
    - "src/cce/runtime.py:71-99   # in-process backstop"
    - "src/cce/cli.py:76-82       # --assert-network-isolated / env trigger"
    - "tests/test_runtime.py:14-43"
  gaps: []
  risk: none

- id: PREQ-A-4
  status: IMPLEMENTED
  evidence:
    - "tests/test_grammar_stability.py:32-64  # parametrised over python + typescript fixtures"
    - "tests/_grammar_spans.py:18-45         # deterministic pre-order DFS over named nodes"
    - "tests/fixtures/grammar_spans/*.json   # frozen RFC 8785 goldens"
    - "CCE_UPDATE_GRAMMAR_GOLDENS=1 deliberately fails the rewrite (tests/test_grammar_stability.py:51-58)"
  gaps: []
  risk: none
```

## 5. Git Safety

```yaml
- id: PREQ-X-1
  status: IMPLEMENTED
  evidence:
    - "Dockerfile:17,23-30                       # git=1:2.50.1-0+deb12u1 from bookworm-backports"
    - "src/cce/git_ops.py:79-95                  # _assert_git_min_version tuple compare"
    - "tests/test_git_ops.py:18-44               # equal/newer/older/suffixed cases"
    - "scoring-spec.yaml:39  git_min_version: 2.50.1"

- id: PREQ-X-2
  status: IMPLEMENTED
  evidence:
    - "src/cce/git_ops.py:18-23  # _HARDENED_GIT_FLAGS verbatim from PRD wording"
    - "src/cce/git_ops.py:46-60  # clone --no-local --depth=1 --filter=blob:none --no-checkout, then hardened checkout"
    - "src/cce/git_ops.py:97-138 # _assert_local_safety rejects populated .gitmodules + escaping symlinks"
    - "tests/test_git_ops.py:65-122"
    - "tests/test_submodule_trap.py:51-86"

- id: PREQ-X-3
  status: IMPLEMENTED
  evidence:
    - ".github/workflows/poc-determinism.yml:104-110"
    - "compare-hashes.needs: [deterministic-core, container-isolation] (workflow:130)"

- id: PREQ-X-4
  status: IMPLEMENTED  # P1
  evidence:
    - "DEFERRED.md:18-20                                       # Firecracker dispatcher closure note"
    - "src/cce_service/dispatch/firecracker.py"
    - "ops/firecracker/{jailer.json,kernel.config,rootfs.build.sh}"
    - "tests/service/test_firecracker_dispatch.py"
  notes: |
    Live FC microVM CI job is continue-on-error: true (.github/workflows/nightly-stability.yml:75)
    until the self-hosted [self-hosted, linux, kvm] runner is provisioned.
```

## 6. Storage

```yaml
- id: PREQ-D-1
  status: IMPLEMENTED
  evidence:
    - "src/cce/cli.py:316-321"
    - "tests/test_cli.py:84-86"

- id: PREQ-D-2
  status: IMPLEMENTED
  evidence:
    - "src/cce/cli.py:317-321"
    - "tests/test_cli.py:115-129  # raw bytes == canonical_json_bytes(raw); files[] sorted by path"

- id: PREQ-D-3
  status: IMPLEMENTED  # P1
  evidence:
    - "src/cce/cli.py:322-326     # GNU-coreutils format <hex>  <name>.json"
    - "src/cce/cli.py:194-247     # cce verify --sidecar accepts new + legacy"
    - "tests/test_cli.py:131-186"
```

## 7. Observability

```yaml
- id: PREQ-O-1
  status: BROKEN  # priority P1 in PRD; literal contract miss
  evidence:
    - "src/cce/cli.py:87,98,126,150  # spans actually emitted: prepared_repo, analyze, score, write_outputs"
    - "src/cce/otel.py:77-89          # OTLPSpanExporter (HTTP), not ConsoleSpanExporter"
  gaps:
    - "Span names diverge from PRD's cce.load_spec / cce.clone / cce.parse / cce.measure / cce.score (only cce.score matches)"
    - "PRD demands 'OTel SDK stdout exporter'; code wires OTLP HTTP. POC dev image has no SDK installed -> _NoopTracer -> zero spans emitted to stdout in CI"
    - "cce.parse vs cce.measure are not separable in current architecture (analyse_repo wraps both)"
  risk: medium  # P1 priority but a literal miss

- id: PREQ-O-2
  status: IMPLEMENTED
  evidence:
    - "src/cce/cli.py:340-343  # _print_timings to sys.stderr"
    - "Stages timed: cce.load_spec, cce.clone, cce.measure, cce.score, cce.total"
```

## 8. POC Acceptance Gates (§7)

```yaml
- id: POC-GATE-1
  status: IMPLEMENTED
  evidence: tests/determinism_100x.py + .github/workflows/poc-determinism.yml:35-36

- id: POC-GATE-2
  status: PARTIAL
  evidence: matrix runs only tests/fixtures/simple_python (poc-determinism.yml:64-86)
  gaps:
    - "simple_typescript not exercised in matrix (grep simple_typescript|perf_100k in .github/workflows returns 0 matches)"
    - "100k LoC fixture not exercised in matrix"
    - "No per-fixture frozen expected_record_hash files committed under tests/fixtures/<name>/"

- id: POC-GATE-3
  status: PARTIAL
  evidence: nightly-stability.yml:36-72 (one fixture); ops/nightly-streak.json
  gaps:
    - "Same single-fixture limitation as POC-GATE-2"
    - "Firecracker microVM job continue-on-error: true (workflow:78)"

- id: POC-GATE-4
  status: MISSING
  evidence:
    - "docs/reproductions/README.md  # protocol committed"
    - "no docs/reproductions/<YYYY-MM-DD>-<reviewer>.txt receipt"
  notes: "Asynchronous; tracked in DEFERRED.md GA-flip item 6"

- id: POC-GATE-5
  status: IMPLEMENTED
  evidence: .github/workflows/poc-determinism.yml:104-110

- id: POC-GATE-6
  status: IMPLEMENTED
  evidence:
    - "tests/test_submodule_trap.py:51-86  # dual contract (exit 12 OR safe no-op)"
    - "tests/fixtures/submodule_trap/.gitmodules"

- id: POC-GATE-7
  status: IMPLEMENTED
  evidence: tests/test_grammar_stability.py + tests/fixtures/grammar_spans/*.json
  notes: |
    Runs as part of full pytest in poc-determinism.yml:32-33; not wired as a
    standalone job. Acceptable per PRD wording.

- id: POC-GATE-8
  status: IMPLEMENTED
  evidence:
    - "tests/perf/test_100k_loc.py:42-65  # wall <= 90s, RSS <= 2 GiB"
    - ".github/workflows/perf-gate.yml:33-36"
```

## 9. §11 Deliverables Checklist

```yaml
- deliverable: "cce CLI binary (uv tool install .)"
  status: IMPLEMENTED
  evidence: pyproject.toml (cce = cce.cli:entrypoint); src/cce/cli.py:35-37

- deliverable: "Dockerfile (digest-pinned base, hash-pinned deps)"
  status: PARTIAL
  evidence: Dockerfile:12,17-31,36
  gap: "SCC_SHA256 placeholder (Dockerfile:43-55) requires out-of-tree --build-arg"

- deliverable: "scoring-spec.yaml v0.1.0 with real sha256 digests"
  status: MISSING
  evidence: scoring-spec.yaml:30-36 placeholder digests; spec_hash sha256:0000...

- deliverable: "3 golden fixture repos with frozen expected record_hash files"
  status: PARTIAL
  evidence: tests/fixtures/{simple_python,simple_typescript,perf_100k}/ exist
  gap: "No expected_record_hash file anywhere (file_search 'expected_record_hash' -> 0 results)"

- deliverable: "tests/determinism_100x.py"
  status: IMPLEMENTED

- deliverable: "tests/grammar_stability.py"
  status: PARTIAL
  notes: "File is tests/test_grammar_stability.py (pytest convention). Functional content matches PRD; literal name diverges."

- deliverable: "tests/network_isolation.py"
  status: MISSING
  notes: "Verification is workflow-only (poc-determinism.yml:104-110) plus mocked unit tests in tests/test_runtime.py. No tests/network_isolation.py exists."

- deliverable: "tests/submodule_trap.py"
  status: PARTIAL
  notes: "File is tests/test_submodule_trap.py."

- deliverable: ".github/workflows/poc-determinism.yml"
  status: IMPLEMENTED

- deliverable: "DEFERRED.md"
  status: IMPLEMENTED

- deliverable: "README.md with end-to-end external-reviewer reproduction steps"
  status: IMPLEMENTED

- deliverable: "DEMO.md + recorded demo"
  status: MISSING
  evidence: file_search 'DEMO.md' returned 0 results
```

## 10. §13 LLM Agent Rules

```yaml
- rule: "Float banned in scoring path"
  status: IMPLEMENTED
  evidence: src/cce/scoring.py imports + src/cce/spec.py:174-181 _reject_floats

- rule: "No network calls after cce.clone"
  status: IMPLEMENTED
  evidence: --network=none + assert_network_isolated probe (the only socket.connect in src/cce, by design)

- rule: "Sort collections before canonicalisation"
  status: IMPLEMENTED
  evidence:
    - "src/cce/scoring.py:97       # dict(sorted(spec.tool_digests.items()))"
    - "src/cce/analyzer.py:98      # files sorted by relative posix path"
    - "src/cce/spec.py             # METRIC_NAMES tuple iterated in fixed order"
    - "tests/test_cli.py:127       # pins the sort"

- rule: "Pin by digest not tag"
  status: PARTIAL
  evidence: Dockerfile FROM digest + requirements.lock.txt hashes
  gap: "scoring-spec.yaml pinned_tools placeholders + Dockerfile SCC_SHA256 placeholder + --verify-digests=false in CI"
```

## 11. Risk-Ranked Defect List (spec inputs)

```yaml
hard_blockers:
  - id: AUDIT-1
    title: "Real sha256 digests for pinned_tools + spec_hash"
    requirements_touched: [PREQ-A-1, PREQ-A-2, PREQ-S-7, POC-GATE-2, POC-GATE-3]
    fix: |
      Run ops/firecracker/rootfs.build.sh on Linux+KVM to materialise real
      lizard / scc / tree-sitter digests. Run scripts/sync_pinned_tools.py to
      rewrite scoring-spec.yaml::pinned_tools and spec_hash. Drop
      --verify-digests false from poc-determinism.yml and nightly-stability.yml.
      Wire register_production_backends(...) in production image entrypoint so
      AnalyzerRegistry.assert_digests is non-trivial in CI.
    deferred_md_link: "GA-flip item 1"

  - id: AUDIT-2
    title: "Multi-fixture matrix coverage"
    requirements_touched: [POC-GATE-2, POC-GATE-3, §11.golden_corpus]
    fix: |
      Extend deterministic-core matrix in poc-determinism.yml to score
      simple_typescript and perf_100k in addition to simple_python. Same for
      nightly-stability.yml. Commit
      tests/fixtures/<name>/expected_record_hash.txt and add a CI step that
      asserts produced hash == committed value. Update streak-tracker to
      require all three fixtures green.

  - id: AUDIT-3
    title: "Dockerfile SCC_SHA256 placeholder"
    requirements_touched: [PREQ-A-2]
    fix: |
      After AUDIT-1 produces a real scc digest, replace the placeholder in
      Dockerfile (line 44) with the real value so `git clone + docker build .`
      succeeds without out-of-tree --build-arg.

  - id: AUDIT-4
    title: "External reviewer receipt"
    requirements_touched: [POC-GATE-4]
    fix: |
      Solicit one external reviewer per docs/reproductions/README.md. Commit
      docs/reproductions/<YYYY-MM-DD>-<reviewer>.txt with their record_hash
      and signed assertion. Flip POC-GATE-4 to CLOSED in DEFERRED.md.

medium_risk:
  - id: AUDIT-5
    title: "PREQ-O-1 literal contract violation"
    requirements_touched: [PREQ-O-1]
    fix: |
      Decide and execute one of:
      (a) Rename stage_span() calls in src/cce/cli.py to PRD wording:
          cce.load_spec, cce.clone, cce.parse, cce.measure, cce.score.
          Split analyse_repo into parse + measure phases (or alias them).
      (b) Amend docs/poc-prd.md PREQ-O-1 to ratify current names
          (prepared_repo / analyze / score / write_outputs).
      Either way, add ConsoleSpanExporter fallback in src/cce/otel.py::init_otel
      so the dev image emits to stdout when OTEL_EXPORTER_OTLP_ENDPOINT is unset.
      Mark span emission required in CI (assert at least one cce.* span on
      stdout for a known invocation).

  - id: AUDIT-6
    title: "Section 11 deliverables hygiene"
    requirements_touched: [§11.deliverables]
    fix: |
      - Add tests/network_isolation.py covering the in-process probe and a
        subprocess-spawned curl-equivalent under PYTEST_NETWORK_ISOLATED.
      - Either rename test_grammar_stability.py / test_submodule_trap.py to
        the PRD names (with conftest.py to keep pytest discovery), or amend
        PRD §11 to use the test_*.py form.
      - Author DEMO.md with reproduction script + recording link.

frozen_expected_hashes:
  - id: AUDIT-7
    title: "Commit per-fixture expected_record_hash files"
    requirements_touched: [§11.golden_corpus, POC-GATE-2, POC-GATE-3]
    fix: |
      For each fixture under tests/fixtures/{simple_python,simple_typescript,perf_100k}:
      - Generate a deterministic git commit (env-pinned author/date).
      - Run cce score --verify-digests true (after AUDIT-1).
      - Commit the produced record_hash to tests/fixtures/<name>/expected_record_hash.txt.
      - Add CI assertion: produced hash == committed value (per fixture, per runner).
```

## 12. Verified-Clean P0 Invariants

These are working as advertised; the follow-up spec **must not regress them**.

- Scoring purity (PREQ-S-1)
- Decimal prec=28 / ROUND_HALF_EVEN (PREQ-S-2)
- RFC 8785 + pinned `rfc8785` (PREQ-S-3)
- Record-hash byte concatenation, no separators (PREQ-S-4)
- Frozen normalisation cuts (PREQ-S-5)
- 100x determinism (PREQ-S-6)
- Hardened git clone + checkout (PREQ-X-1, PREQ-X-2)
- Network isolation + curl-fail check (PREQ-A-3, PREQ-X-3, POC-GATE-5)
- Submodule trap dual contract (POC-GATE-6)
- Grammar stability (PREQ-A-4, POC-GATE-7)
- Perf budget on 100k LoC (POC-GATE-8)
- Sidecar contract — RFC 8785 raw + GNU coreutils .sha256 (PREQ-D-1/2/3)

## 13. Spec Seed (next step)

The follow-up spec should take AUDIT-1 through AUDIT-7 above as its
requirements. Suggested ordering:

```yaml
spec_milestones:
  - id: SPEC-M-1
    deliverable: "AUDIT-1 + AUDIT-3 — real digests in scoring-spec.yaml + Dockerfile"
    blocks: [SPEC-M-2, SPEC-M-3]
  - id: SPEC-M-2
    deliverable: "AUDIT-2 + AUDIT-7 — multi-fixture matrix + frozen expected hashes"
    blocks: [SPEC-M-4]
  - id: SPEC-M-3
    deliverable: "AUDIT-5 — PREQ-O-1 reconciliation (rename or PRD amend) + ConsoleSpanExporter"
  - id: SPEC-M-4
    deliverable: "AUDIT-6 — tests/network_isolation.py + DEMO.md + filename hygiene"
  - id: SPEC-M-5
    deliverable: "AUDIT-4 — external reviewer receipt"
```

Once SPEC-M-1..5 land, every gate in `docs/poc-prd.md §7` is provably
green and the falsifiable thesis can be signed off.
