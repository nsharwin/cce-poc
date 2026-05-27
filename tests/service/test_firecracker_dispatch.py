"""Dispatch-level tests for the Firecracker driver and the consumer.

Real microVM boot requires Linux + KVM, so the production driver
:class:`FirecrackerDispatcher` is unit-tested for its *protocol*
behavior (digest verification, host-platform refusal). End-to-end
boot tests live in the CI-only ``firecracker-e2e.yml`` workflow.

The :class:`InProcessDispatcher` is exercised against a local fixture
to validate the queue → dispatcher → storage flow that the production
driver also goes through.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cce.runtime import ToolDigestMismatchError, compute_file_sha256
from cce_service.dispatch import DispatchError, InProcessDispatcher
from cce_service.dispatch.firecracker import (
    FirecrackerConfig,
    FirecrackerDispatcher,
)
from cce_service.storage import (
    InMemoryAuditRepo,
    InMemoryJobRepo,
    InMemoryRecordRepo,
    JobRecord,
    JobStatus,
)
from cce_service.workers.consumer import InMemoryQueue, JobConsumer

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "scoring-spec.yaml"
SIMPLE_PY = REPO_ROOT / "tests" / "fixtures" / "simple_python"


def _local_clone(repo_url: str, commit_sha: str, dest: Path) -> Path:
    # Pretend the URL maps to the local fixture so we can score without
    # touching the network.
    return SIMPLE_PY


def test_inprocess_dispatcher_produces_record() -> None:
    dispatcher = InProcessDispatcher(spec_path=SPEC_PATH, repo_clone=_local_clone)
    job = JobRecord(
        repo_url="https://example.test/simple_python",
        commit_sha="0" * 40,
        spec_ref="v0.1.0",
    )
    result = dispatcher.dispatch(job)
    assert result.record_hash.startswith("sha256:")
    assert "lizard" in result.tool_digests
    assert result.score == "0.7700" or result.score.startswith("0.")


def test_consumer_persists_success(tmp_path: Path) -> None:
    dispatcher = InProcessDispatcher(spec_path=SPEC_PATH, repo_clone=_local_clone)
    jobs = InMemoryJobRepo()
    records = InMemoryRecordRepo()
    audits = InMemoryAuditRepo()
    queue = InMemoryQueue()

    consumer = JobConsumer(
        source=queue,
        dispatcher=dispatcher,
        jobs=jobs,
        records=records,
        audits=audits,
    )
    job = JobRecord(
        repo_url="https://example.test/simple_python",
        commit_sha="0" * 40,
        spec_ref="v0.1.0",
    )
    jobs.create(job)
    queue.put(job)

    processed = consumer.run_once(timeout=0.5)
    assert processed is not None
    assert processed.status == JobStatus.SUCCEEDED
    assert processed.record_hash is not None
    assert records.get(processed.record_hash) is not None
    actions = [e.action for e in audits._events]  # type: ignore[attr-defined]
    assert "score.succeeded" in actions


def test_consumer_records_failure_on_dispatch_error() -> None:
    class _Boom:
        def dispatch(self, job: JobRecord):  # type: ignore[no-untyped-def]
            raise DispatchError("boom")

    jobs = InMemoryJobRepo()
    records = InMemoryRecordRepo()
    audits = InMemoryAuditRepo()
    queue = InMemoryQueue()
    job = JobRecord(repo_url="https://x/y", commit_sha="0" * 40, spec_ref="v")
    jobs.create(job)
    queue.put(job)

    consumer = JobConsumer(
        source=queue,
        dispatcher=_Boom(),
        jobs=jobs,
        records=records,
        audits=audits,
    )
    processed = consumer.run_once(timeout=0.5)
    assert processed is not None
    assert processed.status == JobStatus.FAILED
    assert "boom" in (processed.error or "")
    actions = [e.action for e in audits._events]  # type: ignore[attr-defined]
    assert "score.failed" in actions


def test_firecracker_dispatch_refuses_off_linux(tmp_path: Path) -> None:
    # Build a fake config with digest-pinned (but fake) artifacts; the
    # dispatcher must refuse before any digest check on macOS/Windows.
    fake = tmp_path / "fake"
    fake.write_bytes(b"x")
    digest = compute_file_sha256(fake)
    cfg = FirecrackerConfig(
        firecracker_binary=fake, firecracker_digest=digest,
        jailer_binary=fake, jailer_digest=digest,
        kernel_image=fake, kernel_digest=digest,
        rootfs_image=fake, rootfs_digest=digest,
    )
    dispatcher = FirecrackerDispatcher(cfg)
    if sys.platform.startswith("linux"):
        pytest.skip("on linux dispatch attempts a real boot")
    with pytest.raises(DispatchError):
        dispatcher.dispatch(
            JobRecord(repo_url="https://x/y", commit_sha="0" * 40, spec_ref="v")
        )


def test_firecracker_config_digest_tamper(tmp_path: Path) -> None:
    fake = tmp_path / "fake"
    fake.write_bytes(b"pristine")
    pristine_digest = compute_file_sha256(fake)
    fake.write_bytes(b"tampered")
    cfg = FirecrackerConfig(
        firecracker_binary=fake, firecracker_digest=pristine_digest,
        jailer_binary=fake, jailer_digest=pristine_digest,
        kernel_image=fake, kernel_digest=pristine_digest,
        rootfs_image=fake, rootfs_digest=pristine_digest,
    )
    with pytest.raises(ToolDigestMismatchError):
        cfg.assert_digests()
