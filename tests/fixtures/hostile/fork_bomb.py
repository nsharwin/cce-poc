"""Hostile fixture: fork bomb capped by guest cgroup pids.max.

The Firecracker rootfs sets ``/sys/fs/cgroup/pids.max=128`` inside the
guest; this script will eventually fail with ``OSError: EAGAIN`` once
the limit is hit, instead of bringing the host down.

DO NOT execute this on the host.
"""

from __future__ import annotations

import os


def main() -> int:  # pragma: no cover - never executed in unit tests
    while True:
        try:
            os.fork()
        except OSError:
            return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
