# External Reproductions (POC-GATE-4)

POC-GATE-4 closes when at least one external reviewer reproduces a
documented `record_hash` byte-for-byte on their own machine. Each
reproduction is a small, signed text receipt committed under this
directory.

## Protocol

1. Clone the repo at the tagged commit referenced in `DEFERRED.md` (e.g.
   the same commit that updated `ops/nightly-streak.json` to streak `7`).
2. Build the pinned container:
   ```bash
   docker build --build-arg SCC_SHA256=<see ops/firecracker/digests.json> -t cce-poc:repro .
   ```
3. Score the canonical fixture inside the network-isolated container:
   ```bash
   cd tests/fixtures/simple_python
   git init -q --initial-branch=main
   git -c user.email=cce@example.test -c user.name="CCE Test" \
       -c committer.date="2026-01-01T00:00:00+0000" \
       -c author.date="2026-01-01T00:00:00+0000" \
       commit --allow-empty -m fixture --date "2026-01-01T00:00:00+0000"
   git add . && git commit -q --amend --no-edit
   cd -

   docker run --rm --network=none \
     -e CCE_REQUIRE_NETWORK_ISOLATED=1 \
     -v "$PWD:/work:ro" \
     -v "$PWD/cce-out:/work/cce-out" \
     cce-poc:repro \
     score --spec /work/scoring-spec.yaml \
           --repo /work/tests/fixtures/simple_python \
           --mode repo \
           --out /work/cce-out
   ```
4. Verify the sidecar:
   ```bash
   cd cce-out
   sha256sum -c sha256:<hex>.sha256
   ```
5. Reply with a signed text receipt (PGP/SSH/sigstore, your choice)
   and open a PR adding it as `<YYYY-MM-DD>-<your-handle>.txt`.

## Receipt format

Plain text, one record per file. The PR description must include a
signature over the file's SHA-256 (key fingerprint must already be
linked from a public profile so the maintainers can verify it):

```
# CCE POC reproduction receipt
# Reviewer: <handle> <pubkey-id-or-fingerprint>
# Date:     YYYY-MM-DD (UTC)
# Repo:     https://github.com/nsharwin/cce-poc
# Commit:   <git-sha>
# Image:    cce-poc@sha256:<image-digest>
# Host OS:  <uname -a output, one line>
# Fixture:  tests/fixtures/simple_python

record_hash = sha256:<hex>
```

## Why this matters

The deterministic scoring core is only as trustworthy as the *evidence*
that an arbitrary third party can recompute the same `record_hash` from
the same inputs. One receipt is the minimum bar to close
POC-GATE-4; the maintainers welcome additional receipts from
heterogeneous platforms (different CPU vendor, different Linux distro)
to thicken the evidence.

## Regenerating `expected_record_hash.txt`

Each fixture under `tests/fixtures/<name>/` carries a frozen
`expected_record_hash.txt` (one line, `sha256:<64-hex>\n`). CI's
`Frozen_Hash_Gate` step compares the live `record_hash` produced by
`cce score` against the contents of this file, so the file must be
regenerated lock-step with any commit that bumps `Scoring_Spec.spec_hash`
or any digest under `Scoring_Spec.pinned_tools`.

The procedure below is the same incantation operators run when bumping
`scoring-spec.yaml`; external reviewers can run it verbatim to confirm a
hash before signing a receipt.

### Prerequisites

- A working tree at the commit whose `expected_record_hash.txt` you want
  to regenerate.
- `Scoring_Spec.pinned_tools` already populated with real digests (i.e.
  `scripts/sync_pinned_tools.py` has run against a real
  `ops/firecracker/digests.json`).
- `uv` installed (or `cce` available on `PATH` from the production image
  via `cce-entrypoint`).

### Deterministic git-init protocol

Every fixture's `record_hash` depends on the fixture's `HEAD` commit
sha. To keep `HEAD` byte-identical across runs, the four
`GIT_AUTHOR_*` / `GIT_COMMITTER_*` env vars below MUST be exported
before `git commit`:

```bash
export GIT_AUTHOR_NAME="CCE Test"
export GIT_AUTHOR_EMAIL="cce@example.test"
export GIT_AUTHOR_DATE="2026-01-01T00:00:00+0000"
export GIT_COMMITTER_NAME="CCE Test"
export GIT_COMMITTER_EMAIL="cce@example.test"
export GIT_COMMITTER_DATE="2026-01-01T00:00:00+0000"
```

These match the values used by `.github/workflows/poc-determinism.yml`
and `.github/workflows/nightly-stability.yml`. Any deviation (different
date, different name, different email) will produce a different `HEAD`
sha and therefore a different `record_hash`.

### Procedure (loop over all three Golden_Fixtures)

Run from the repository root:

```bash
for fixture in simple_python simple_typescript perf_100k; do
  fixture_dir="tests/fixtures/${fixture}"

  # perf_100k is generated; the other two ship with committed sources.
  if [ "$fixture" = "perf_100k" ]; then
    rm -rf "${fixture_dir}/repo"
    python -m tests.fixtures.perf_100k.generate --out "${fixture_dir}/repo"
    repo_dir="${fixture_dir}/repo"
  else
    repo_dir="${fixture_dir}"
  fi

  # Deterministic git init + single fixture commit.
  pushd "$repo_dir" >/dev/null
    rm -rf .git
    git init -q --initial-branch=main
    git config user.email "cce@example.test"
    git config user.name "CCE Test"
    GIT_AUTHOR_NAME="CCE Test" \
    GIT_AUTHOR_EMAIL="cce@example.test" \
    GIT_AUTHOR_DATE="2026-01-01T00:00:00+0000" \
    GIT_COMMITTER_NAME="CCE Test" \
    GIT_COMMITTER_EMAIL="cce@example.test" \
    GIT_COMMITTER_DATE="2026-01-01T00:00:00+0000" \
      git add . && \
      git -c user.email=cce@example.test -c user.name="CCE Test" \
        commit -q -m fixture
  popd >/dev/null

  # Score with digest verification enabled (the default).
  # DO NOT pass `--verify-digests false`; that flag is the bypass that
  # `Scoring_Spec` real-digest enforcement was designed to remove.
  HASH=$(uv run cce score \
    --spec ./scoring-spec.yaml \
    --repo "$repo_dir" \
    --mode repo \
    --out ./cce-out)

  echo "$HASH" > "${fixture_dir}/expected_record_hash.txt"
  echo "wrote ${fixture_dir}/expected_record_hash.txt = $HASH"
done
```

### Notes

- `--verify-digests` defaults to `true` in `cce score`. Do NOT pass
  `--verify-digests false`; CI's `Frozen_Hash_Gate` runs with verification
  enabled, so a hash regenerated with verification disabled would not
  match what CI computes.
- The `perf_100k` repo is regenerated from
  `tests/fixtures/perf_100k/generate.py` rather than committed, so the
  `python -m tests.fixtures.perf_100k.generate --out tests/fixtures/perf_100k/repo`
  step is mandatory before scoring that fixture.
- The resulting three files (`tests/fixtures/simple_python/expected_record_hash.txt`,
  `tests/fixtures/simple_typescript/expected_record_hash.txt`,
  `tests/fixtures/perf_100k/expected_record_hash.txt`) MUST be staged in
  the same commit that updated `scoring-spec.yaml`, so the `record_hash`
  delta is recorded as an audited bump rather than a CI regression.
- Each file's contents MUST match the regex `^sha256:[0-9a-f]{64}\n$`
  (72 bytes total: 7 ASCII for `sha256:`, 64 ASCII for the hex digest, 1
  ASCII for the trailing newline).

