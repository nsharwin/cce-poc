#!/bin/bash
set -euo pipefail

apt-get update -qq >/dev/null
apt-get install -y --no-install-recommends e2fsprogs coreutils tar findutils >/dev/null

mkdir -p /tmp/rootfs
tar -C /tmp/rootfs -xf /work/rootfs.tar

rm -rf /tmp/rootfs/proc /tmp/rootfs/sys /tmp/rootfs/dev
mkdir -p /tmp/rootfs/proc /tmp/rootfs/sys /tmp/rootfs/dev

ROOTFS_OUT=/tmp/cce-rootfs.ext4
SIZE_MIB=1024
ROOTFS_UUID=2026cce0-0000-0000-0000-000000000000

dd if=/dev/zero of="$ROOTFS_OUT" bs=1M count="$SIZE_MIB" status=none
mkfs.ext4 -F -L cce-rootfs -U "$ROOTFS_UUID" -d /tmp/rootfs "$ROOTFS_OUT" >/dev/null

ROOTFS_SHA="sha256:$(sha256sum "$ROOTFS_OUT" | awk '{print $1}')"
echo "rootfs digest: $ROOTFS_SHA"

_sha() {
  local target="$1"
  if [[ ! -f "$target" ]]; then
    echo "missing pinned tool: $target" >&2
    exit 1
  fi
  printf 'sha256:%s' "$(sha256sum "$target" | awk '{print $1}')"
}

rootfs=/tmp/rootfs
LIZARD_BIN="${rootfs}/usr/local/bin/lizard"
SCC_BIN="${rootfs}/usr/local/bin/scc"

TS_CORE="$(find "${rootfs}/usr/local/lib/python3.12" -name '_binding*.so' -path '*/tree_sitter/*' | head -n1)"
PY_GRAMMAR="$(find "${rootfs}/usr/local/lib/python3.12" -name 'python.abi3.so' -path '*/tree_sitter_language_pack/bindings/*' | head -n1)"
TS_GRAMMAR="$(find "${rootfs}/usr/local/lib/python3.12" -name 'typescript.abi3.so' -path '*/tree_sitter_language_pack/bindings/*' | head -n1)"

echo "tree_sitter core:    ${TS_CORE#$rootfs}"
echo "python grammar:      ${PY_GRAMMAR#$rootfs}"
echo "typescript grammar:  ${TS_GRAMMAR#$rootfs}"

cat > /work/digests.json <<JSON
{
  "rootfs": "${ROOTFS_SHA}",
  "lizard": "$(_sha "$LIZARD_BIN")",
  "scc": "$(_sha "$SCC_BIN")",
  "tree_sitter_core": "$(_sha "$TS_CORE")",
  "grammars": {
    "python": "$(_sha "$PY_GRAMMAR")",
    "typescript": "$(_sha "$TS_GRAMMAR")"
  }
}
JSON

echo "$ROOTFS_SHA" > /work/cce-rootfs.ext4.sha256

echo "===== digests.json ====="
cat /work/digests.json
