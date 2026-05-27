"""Hostile fixture: attempt to reach the public internet.

A correctly isolated Firecracker microVM (no TAP device) must make any
``socket.connect`` call fail with EHOSTUNREACH/EHOSTDOWN. The dispatch
test asserts that this script's process exit code is non-zero when run
inside the guest.
"""

from __future__ import annotations

import socket
import sys


def main() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2.0)
    try:
        sock.connect(("1.1.1.1", 53))
        return 0  # leak — the test expects this branch NEVER to be taken
    except OSError:
        return 42
    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
