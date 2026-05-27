# Runbook: `CCEFirecrackerBootFailures`

**Symptom**: `rate(cce_firecracker_boot_failures_total[5m]) > 0`.
**Pager severity**: page.

## Detect
- Alert `CCEFirecrackerBootFailures`.
- `cce_job_failures_total{reason="dispatch"}` increasing.

## Diagnose
1. Pick a failed job from the audit log:
   ```
   SELECT * FROM audit_events WHERE action='score.failed'
   ORDER BY ts DESC LIMIT 10;
   ```
2. Inspect the worker logs around that timestamp:
   ```
   kubectl -n cce logs <worker-pod> --since=10m | grep -E 'firecracker|jailer'
   ```
3. Check the host KVM and cgroup state:
   ```
   ls -l /dev/kvm
   cat /sys/fs/cgroup/cpu.max
   ```
4. Verify pinned-artifact digests are still intact:
   ```
   sha256sum /opt/firecracker/firecracker /opt/firecracker/jailer \
             /opt/firecracker/vmlinux-cce /opt/firecracker/cce-rootfs.ext4
   ```
   compare against `ops/firecracker/jailer.json::*_digest`.

## Mitigate
- **Missing/permission KVM** (`/dev/kvm` not present or not 0660):
  ensure the node has the `kvm` group and re-apply the DaemonSet.
- **cgroup v1 host**: Firecracker requires cgroup v2 — pin the node
  pool to a cgroup-v2 image (Ubuntu 22.04+).
- **Digest mismatch**: the rootfs was replaced out-of-band; rebuild via
  `ops/firecracker/rootfs.build.sh` from the pinned image digest.
- **Resource exhaustion** (`ENOMEM` from jailer): drain the node
  (`kubectl drain <node>`) and let the autoscaler bring up a fresh one.

## Escalate
- 30 min unresolved → engage platform team.
- If digest mismatch is confirmed → treat as SEV-1 supply-chain incident
  and page security; do not re-enable workers until root cause known.
