#!/usr/bin/env bash
# Build the read-only ext4 rootfs for the CCE Firecracker worker pool.
#
# This script converts the production CCE Docker image (digest-pinned in
# Dockerfile + scoring-spec.yaml::worker_image) into an ext4 image that
# Firecracker can mount as `/dev/vda`. Determinism notes:
#   - the docker image is pulled by digest, never tag
#   - the ext4 image is built with `mkfs.ext4 -F -d <chroot>` and a fixed
#     UUID so two builds from the same digest produce byte-identical
#     rootfs images (verified by sha256 in CI)
#   - `cce-rootfs.sha256` is emitted next to the .ext4 file; the
#     deploy pipeline patches it into ops/firecracker/jailer.json
#
# Usage:
#   ROOTFS_OUT=/opt/firecracker/cce-rootfs.ext4 \
#   IMAGE_DIGEST=sha256:93ab4b7f... \
#   ops/firecracker/rootfs.build.sh

set -euo pipefail

: "${ROOTFS_OUT:?ROOTFS_OUT is required}"
: "${IMAGE_DIGEST:?IMAGE_DIGEST is required (full sha256:<hex>)}"
SIZE_MIB="${SIZE_MIB:-1024}"
ROOTFS_UUID="${ROOTFS_UUID:-2026cce0-0000-0000-0000-000000000000}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo ">>> pulling cce-poc@${IMAGE_DIGEST}"
docker pull "cce-poc@${IMAGE_DIGEST}"

echo ">>> exporting container fs to ${work}/rootfs/"
cid="$(docker create "cce-poc@${IMAGE_DIGEST}")"
mkdir -p "$work/rootfs"
docker export "$cid" | tar -C "$work/rootfs" -xf -
docker rm "$cid" >/dev/null

# Drop /proc, /sys, /dev — those are guest-mounted at boot.
rm -rf "$work/rootfs"/{proc,sys,dev}
mkdir -p "$work/rootfs"/{proc,sys,dev}

echo ">>> creating ${SIZE_MIB} MiB ext4 image at ${ROOTFS_OUT}"
dd if=/dev/zero of="$ROOTFS_OUT" bs=1M count="$SIZE_MIB" status=none
mkfs.ext4 -F -L cce-rootfs -U "$ROOTFS_UUID" -d "$work/rootfs" "$ROOTFS_OUT" >/dev/null

echo ">>> computing rootfs sha256"
sha256sum "$ROOTFS_OUT" | awk '{print "sha256:" $1}' > "${ROOTFS_OUT}.sha256"
echo "rootfs digest: $(cat "${ROOTFS_OUT}.sha256")"

# --- Emit ops/firecracker/digests.json --------------------------------------
# Compute sha256 of every pinned tool inside the just-built rootfs so that
# scripts/sync_pinned_tools.py can patch scoring-spec.yaml::pinned_tools.
#
# Layout assumptions (matches Dockerfile):
#   /usr/local/bin/lizard            (pip console script, hash-pinned wheel)
#   /usr/local/bin/scc               (release tarball, sha256-verified)
#   tree_sitter core .so + grammar .so under the installed tree-sitter-language-pack
DIGESTS_OUT="${DIGESTS_OUT:-$(dirname "$ROOTFS_OUT")/digests.json}"
echo ">>> computing tool digests into ${DIGESTS_OUT}"

_sha() {
  local target="$1"
  if [[ ! -f "$target" ]]; then
    echo "missing pinned tool: $target" >&2
    exit 1
  fi
  printf 'sha256:%s' "$(sha256sum "$target" | awk '{print $1}')"
}

rootfs="$work/rootfs"
lizard_bin="${rootfs}/usr/local/bin/lizard"
scc_bin="${rootfs}/usr/local/bin/scc"

# Locate tree_sitter core .so and grammar .so files inside the rootfs.
# The grammars ship as part of `tree-sitter-language-pack` (a single wheel that
# packages every language as `<lang>.abi3.so` under
# `tree_sitter_language_pack/bindings/`). Earlier iterations of this script
# expected per-language wheels (`tree_sitter_python/_binding.so`); those are
# not what `requirements.lock.txt` actually pins.
tree_sitter_core="$(find "${rootfs}/usr/local/lib/python3.12" -name '_binding*.so' -path '*/tree_sitter/*' | head -n1)"
python_grammar="$(find "${rootfs}/usr/local/lib/python3.12" -name 'python.abi3.so' -path '*/tree_sitter_language_pack/bindings/*' | head -n1)"
typescript_grammar="$(find "${rootfs}/usr/local/lib/python3.12" -name 'typescript.abi3.so' -path '*/tree_sitter_language_pack/bindings/*' | head -n1)"

cat > "$DIGESTS_OUT" <<JSON
{
  "rootfs": "$(cat "${ROOTFS_OUT}.sha256")",
  "lizard": "$(_sha "$lizard_bin")",
  "scc": "$(_sha "$scc_bin")",
  "tree_sitter_core": "$(_sha "$tree_sitter_core")",
  "grammars": {
    "python": "$(_sha "$python_grammar")",
    "typescript": "$(_sha "$typescript_grammar")"
  }
}
JSON
echo "digests.json:"
cat "$DIGESTS_OUT"
