#!/usr/bin/env bash
# Boot one Firecracker microVM, score a repo through it, print the record_hash.
#
# This is the operator-runnable wrapper used by both:
#   - .github/workflows/nightly-stability.yml::firecracker-microvm
#   - manual reproduction on a Linux+KVM host
#
# It exercises the exact code path the worker uses (FirecrackerDispatcher),
# so any boot/dispatch regression surfaces here before it hits production.
#
# Required env:
#   CCE_FC_JAILER_BINARY   - path to `jailer`
#   CCE_FC_FIRECRACKER_BINARY - path to `firecracker`
#   CCE_FC_KERNEL_IMAGE    - path to vmlinux kernel image
#   CCE_FC_KERNEL_DIGEST   - sha256:<hex> of the kernel image
#   CCE_FC_ROOTFS_IMAGE    - path to the .ext4 rootfs from rootfs.build.sh
#   CCE_FC_ROOTFS_DIGEST   - sha256:<hex> of the rootfs
#   CCE_FC_FIRECRACKER_DIGEST - sha256:<hex> of firecracker binary
#   CCE_FC_JAILER_DIGEST   - sha256:<hex> of jailer binary
#
# Optional:
#   CCE_FIXTURE_REPO - path to repo to score (default: tests/fixtures/simple_python)
#   CCE_SPEC         - path to scoring-spec.yaml (default: ./scoring-spec.yaml)
#   CCE_OUT          - output dir for record_hash.txt (default: ./fc-out)

set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "run-once.sh requires Linux+KVM (got $(uname -s))" >&2
  exit 2
fi
if [[ ! -e /dev/kvm ]]; then
  echo "run-once.sh requires /dev/kvm (KVM not enabled on this host)" >&2
  exit 2
fi

: "${CCE_FC_JAILER_BINARY:?required}"
: "${CCE_FC_FIRECRACKER_BINARY:?required}"
: "${CCE_FC_KERNEL_IMAGE:?required}"
: "${CCE_FC_KERNEL_DIGEST:?required}"
: "${CCE_FC_ROOTFS_IMAGE:?required}"
: "${CCE_FC_ROOTFS_DIGEST:?required}"
: "${CCE_FC_FIRECRACKER_DIGEST:?required}"
: "${CCE_FC_JAILER_DIGEST:?required}"

CCE_FIXTURE_REPO="${CCE_FIXTURE_REPO:-tests/fixtures/simple_python}"
CCE_SPEC="${CCE_SPEC:-./scoring-spec.yaml}"
CCE_OUT="${CCE_OUT:-./fc-out}"

mkdir -p "${CCE_OUT}"

uv run python - <<PY
import os, sys, uuid
from pathlib import Path

from cce_service.dispatch.firecracker import FirecrackerConfig, FirecrackerDispatcher
from cce_service.storage import JobRecord

cfg = FirecrackerConfig(
    firecracker_binary=Path(os.environ["CCE_FC_FIRECRACKER_BINARY"]),
    firecracker_digest=os.environ["CCE_FC_FIRECRACKER_DIGEST"],
    jailer_binary=Path(os.environ["CCE_FC_JAILER_BINARY"]),
    jailer_digest=os.environ["CCE_FC_JAILER_DIGEST"],
    kernel_image=Path(os.environ["CCE_FC_KERNEL_IMAGE"]),
    kernel_digest=os.environ["CCE_FC_KERNEL_DIGEST"],
    rootfs_image=Path(os.environ["CCE_FC_ROOTFS_IMAGE"]),
    rootfs_digest=os.environ["CCE_FC_ROOTFS_DIGEST"],
)
dispatcher = FirecrackerDispatcher(cfg)

job = JobRecord(
    job_id=uuid.uuid4(),
    repo_url=os.environ["CCE_FIXTURE_REPO"],
    spec_ref=os.environ["CCE_SPEC"],
)
result = dispatcher.dispatch(job)
out_dir = Path(os.environ["CCE_OUT"])
(out_dir / "record_hash.txt").write_text(result.record_hash + "\n", encoding="utf-8")
print(result.record_hash)
PY
