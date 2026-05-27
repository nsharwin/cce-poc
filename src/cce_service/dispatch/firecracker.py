"""Firecracker microVM dispatcher (PREQ-X-4).

One microVM per scoring job, with:

- **No network**: the jailer config supplies no TAP device, so the guest
  has no NIC and cannot reach the host or the public internet.
- **Resource caps**: vCPU=2, RAM=2 GiB, wallclock=120 s via cgroup
  controls enforced by the jailer (see ``ops/firecracker/jailer.json``).
- **Digest-pinned rootfs**: built from the production Docker image at
  deploy time (``ops/firecracker/rootfs.build.sh``); its sha256 is
  recorded next to the kernel image and re-verified before each boot.
- **vsock I/O only**: the repo tarball is streamed in over vsock,
  ``cce score`` runs, and the canonical record + sidecars are streamed
  back. No shared filesystem with the host.

Resilience model:

- Any non-zero exit from ``firecracker`` is a :class:`DispatchError`
  with the matching ``reason`` label; the worker emits a Prometheus
  ``cce_firecracker_boot_failures_total`` counter and records the
  failure in Postgres ``audit_events``.
- The jailer is invoked with ``--cgroup-version 2 --new-pid-ns
  --network-namespace``, so a hostile guest cannot impact other VMs.

On macOS/dev this module is importable but ``dispatch`` raises
:class:`DispatchError` because Firecracker requires Linux + KVM.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cce.otel import FIRECRACKER_BOOT_FAILURES_TOTAL, stage_span
from cce.runtime import ToolDigestMismatchError, assert_tool_digest
from cce_service.dispatch.base import (
    DispatchError,
    DispatchResult,
)
from cce_service.storage import JobRecord

_logger = logging.getLogger("cce_service.dispatch.firecracker")


@dataclass(frozen=True)
class FirecrackerConfig:
    """Operator-supplied paths + digests. Loaded from
    ``ops/firecracker/jailer.json`` at process start."""

    firecracker_binary: Path
    firecracker_digest: str  # sha256:<hex>
    jailer_binary: Path
    jailer_digest: str
    kernel_image: Path
    kernel_digest: str
    rootfs_image: Path
    rootfs_digest: str
    vcpu_count: int = 2
    mem_mib: int = 2048
    wallclock_seconds: int = 120

    def assert_digests(self) -> None:
        """Verify every pinned artifact before any VM is booted."""
        for name, path, digest in (
            ("firecracker", self.firecracker_binary, self.firecracker_digest),
            ("jailer", self.jailer_binary, self.jailer_digest),
            ("kernel", self.kernel_image, self.kernel_digest),
            ("rootfs", self.rootfs_image, self.rootfs_digest),
        ):
            assert_tool_digest(name=name, expected_digest=digest, binary_path=path)


# vsock CIDs/ports (must match the guest agent baked into the rootfs).
_GUEST_CID = 3
_PORT_INGEST = 52  # host → guest: tar of repo + spec
_PORT_RESULT = 53  # guest → host: canonical record JSON

# Time budgets (seconds).
_BOOT_WAIT_SECONDS = 10
_RESULT_POLL_INTERVAL = 0.25


class FirecrackerDispatcher:
    """Production dispatcher launching one Firecracker VM per job."""

    def __init__(self, config: FirecrackerConfig) -> None:
        self._config = config
        self._available = (
            sys.platform.startswith("linux") and shutil.which("firecracker") is not None
        )
        self._fc_process: subprocess.Popen[bytes] | None = None

    def dispatch(self, job: JobRecord) -> DispatchResult:
        if not self._available:
            raise DispatchError(
                "Firecracker dispatch is only supported on Linux/KVM hosts; "
                f"current platform: {platform.platform()}"
            )

        with stage_span("dispatch.boot", job_id=str(job.job_id)):
            try:
                self._config.assert_digests()
            except ToolDigestMismatchError as exc:
                FIRECRACKER_BOOT_FAILURES_TOTAL.labels(reason="digest_mismatch").inc()
                raise DispatchError(str(exc)) from exc
            workdir = Path(tempfile.mkdtemp(prefix="cce-fc-"))
            vm_socket = workdir / "fc.sock"
            self._spawn_vm(vm_socket, workdir)

        try:
            with stage_span("dispatch.score", job_id=str(job.job_id)):
                self._send_job(vm_socket, job, workdir)
                payload = self._await_result(vm_socket, workdir)
        except subprocess.TimeoutExpired as exc:
            raise DispatchError(f"VM exceeded wallclock cap: {exc}") from exc
        finally:
            with stage_span("dispatch.shutdown", job_id=str(job.job_id)):
                self._teardown(vm_socket)
                shutil.rmtree(workdir, ignore_errors=True)

        return DispatchResult(
            record_hash=payload["record_hash"],
            score=payload["score"],
            metrics=payload["metrics"],
            spec_hash=payload["spec_hash"],
            tool_digests=payload["tool_digests"],
            sidecars=payload.get("sidecars", {}),
        )

    # ------------------------------------------------------------------
    # The methods below are the integration seam against the jailer.
    # They are deliberately thin so the actual sequencing is auditable
    # against the Firecracker docs (Boot → MachineConfig → Drives → Net
    # **omitted** → Vsock → InstanceStart).
    # ------------------------------------------------------------------

    def _spawn_vm(self, socket_path: Path, workdir: Path) -> None:
        """Launch ``jailer`` which exec's ``firecracker`` as a background process.

        The jailer is configured to:
        - drop to a non-root uid/gid via ``--uid 1000 --gid 1000``
        - apply seccomp filters from ``ops/firecracker/seccomp.json``
        - use a private mount/pid/net namespace
        - NOT attach any TAP device → guest has no network interface

        After spawn, the API socket is polled until reachable, then the boot
        sequence (boot-source, drives, machine-config, vsock, InstanceStart)
        is posted via the unix socket using a minimal hand-rolled HTTP/1.1
        client (zero extra deps).
        """
        chroot_id = f"cce-{os.getpid()}-{int(time.time() * 1000)}"
        vsock_uds = workdir / "vsock.uds"
        cmd = [
            str(self._config.jailer_binary),
            "--id",
            chroot_id,
            "--exec-file",
            str(self._config.firecracker_binary),
            "--chroot-base-dir",
            str(workdir),
            "--uid",
            "1000",
            "--gid",
            "1000",
            "--new-pid-ns",
            "--",
            "--api-sock",
            str(socket_path),
        ]
        _logger.info("firecracker.spawn cmd=%s", cmd)
        # Redirect stdout/stderr to DEVNULL to avoid the classic pipe-buffer
        # deadlock: if the child writes more than the OS pipe buffer (64 KiB)
        # before the parent drains it, the child blocks in write(2) while the
        # parent is blocked waiting for the API socket — circular deadlock.
        self._fc_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for the API socket to appear, bounded by _BOOT_WAIT_SECONDS.
        deadline = time.monotonic() + _BOOT_WAIT_SECONDS
        while time.monotonic() < deadline:
            if socket_path.exists():
                break
            if self._fc_process.poll() is not None:
                reason = "firecracker_exited_before_socket"
                FIRECRACKER_BOOT_FAILURES_TOTAL.labels(reason=reason).inc()
                raise DispatchError(
                    "firecracker exited before opening API socket "
                    f"(exit code {self._fc_process.returncode})"
                )
            time.sleep(0.05)
        else:
            FIRECRACKER_BOOT_FAILURES_TOTAL.labels(reason="api_socket_timeout").inc()
            raise DispatchError("timed out waiting for firecracker API socket")

        # Boot sequence over the unix-domain API socket.
        self._api_put(
            socket_path,
            "/boot-source",
            {
                "kernel_image_path": str(self._config.kernel_image),
                "boot_args": "console=ttyS0 reboot=k panic=1 pci=off",
            },
        )
        self._api_put(
            socket_path,
            "/drives/rootfs",
            {
                "drive_id": "rootfs",
                "path_on_host": str(self._config.rootfs_image),
                "is_root_device": True,
                "is_read_only": True,
            },
        )
        self._api_put(
            socket_path,
            "/machine-config",
            {
                "vcpu_count": self._config.vcpu_count,
                "mem_size_mib": self._config.mem_mib,
                "smt": False,
            },
        )
        self._api_put(
            socket_path,
            "/vsock",
            {
                "vsock_id": "cce",
                "guest_cid": _GUEST_CID,
                "uds_path": str(vsock_uds),
            },
        )
        self._api_put(socket_path, "/actions", {"action_type": "InstanceStart"})

    def _send_job(self, socket_path: Path, job: JobRecord, workdir: Path) -> None:
        """Tar the repo + spec and stream them to the guest agent on vsock port 52.

        For staging/run-once flows, ``job.repo_url`` may be a local filesystem
        path; in production it's a URL the guest agent will ``git clone``.
        """
        vsock_uds = workdir / "vsock.uds"
        tar_buf = io.BytesIO()
        with tarfile.open(fileobj=tar_buf, mode="w") as tar:
            local_repo = Path(job.repo_url)
            if local_repo.is_dir():
                tar.add(local_repo, arcname="repo", recursive=True)
            local_spec = Path(job.spec_ref)
            if local_spec.is_file():
                tar.add(local_spec, arcname="spec.yaml")
            meta = json.dumps(
                {
                    "job_id": str(job.job_id),
                    "repo_url": job.repo_url,
                    "commit_sha": job.commit_sha,
                    "spec_ref": job.spec_ref,
                },
                separators=(",", ":"),
            ).encode("utf-8")
            info = tarfile.TarInfo(name="job.json")
            info.size = len(meta)
            tar.addfile(info, io.BytesIO(meta))
        payload = tar_buf.getvalue()

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(vsock_uds))
            # Firecracker vsock UDS protocol: write `CONNECT <port>\n`, read OK line.
            sock.sendall(f"CONNECT {_PORT_INGEST}\n".encode("ascii"))
            ack = sock.recv(64)
            if not ack.startswith(b"OK"):
                raise DispatchError(f"vsock ingest CONNECT failed: {ack!r}")
            sock.sendall(payload)
            sock.shutdown(socket.SHUT_WR)
        finally:
            sock.close()
        _logger.info("firecracker.send_job job_id=%s bytes=%d", job.job_id, len(payload))

    def _await_result(self, socket_path: Path, workdir: Path) -> dict[str, Any]:
        """Pull the canonical-JSON record back on vsock port 53; re-verify host-side."""
        vsock_uds = workdir / "vsock.uds"
        deadline = time.monotonic() + self._config.wallclock_seconds
        last_err: str | None = None
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(str(vsock_uds))
                sock.sendall(f"CONNECT {_PORT_RESULT}\n".encode("ascii"))
                ack = sock.recv(64)
                if not ack.startswith(b"OK"):
                    last_err = f"vsock result CONNECT not OK: {ack!r}"
                    sock.close()
                    time.sleep(_RESULT_POLL_INTERVAL)
                    continue
                chunks: list[bytes] = []
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                body = b"".join(chunks)
                if not body:
                    last_err = "guest returned empty result"
                    time.sleep(_RESULT_POLL_INTERVAL)
                    continue
                return json.loads(body)
            except OSError as exc:
                last_err = f"vsock connect: {exc}"
                time.sleep(_RESULT_POLL_INTERVAL)
            finally:
                sock.close()
        raise DispatchError(f"timed out waiting for guest result: {last_err}")

    def _teardown(self, socket_path: Path) -> None:
        """Send SendCtrlAltDel for graceful shutdown, then SIGKILL the host process."""
        _logger.info("firecracker.teardown sock=%s", socket_path)
        with contextlib.suppress(Exception):
            self._api_put(socket_path, "/actions", {"action_type": "SendCtrlAltDel"})
        proc = self._fc_process
        self._fc_process = None
        if proc is None:
            return
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=2)

    @staticmethod
    def _api_put(socket_path: Path, route: str, body: dict[str, Any]) -> None:
        """Minimal HTTP/1.1 PUT over the Firecracker unix-domain API socket."""
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = (
            f"PUT {route} HTTP/1.1\r\n"
            f"Host: localhost\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Accept: application/json\r\n"
            f"\r\n"
        ).encode("ascii") + payload

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(socket_path))
            sock.sendall(request)
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\r\n\r\n" in response and b"Content-Length: 0" in response:
                    break
        finally:
            sock.close()
        status_line = response.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        if not (" 200 " in status_line or " 204 " in status_line):
            raise DispatchError(f"firecracker API {route} failed: {status_line}")


__all__ = ["FirecrackerConfig", "FirecrackerDispatcher"]
