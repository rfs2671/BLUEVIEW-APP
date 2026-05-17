#!/bin/bash
# PR #15B.1 — operator helper to copy Atlas snapshot fixtures from
# the Railway container's /tmp/atlas_snapshots/ to the local
# backend/tests/fixtures/atlas_snapshots/ directory.
#
# Pre-condition: snapshots already created on Railway via
#   railway run python backend/scripts/dump_atlas_snapshot.py \
#       menahan=69e7c10013506cc459fcd046 \
#       bronx=69e6e6c30b6e05f281e5bb66 \
#       bailey=69f770d17e96889844310e69 \
#       lafayette=69f8fb5e9429c5be4b2fcb66 \
#       boyland=69f90c3209947c4967c8074f
#
# Usage:
#   ./scripts/download_atlas_snapshots.sh
#
# The script uses `railway ssh -- cat ...` per file and strips the
# leading "Using SSH key: ..." banner that the railway CLI prepends
# to its stdout.

set -e

DEST="backend/tests/fixtures/atlas_snapshots"
mkdir -p "$DEST"

# Default snapshot list (matches dump_atlas_snapshot.py invocation).
DEFAULT_NAMES=(
    "menahan_69e7c100"
    "bronx_69e6e6c3"
    "bailey_69f770d1"
    "lafayette_69f8fb5e"
    "boyland_69f90c32"
)

# Allow positional override: ./download_atlas_snapshots.sh foo_abc123
NAMES=("${@:-${DEFAULT_NAMES[@]}}")

for stem in "${NAMES[@]}"; do
    src="/tmp/atlas_snapshots/${stem}.json"
    dst="$DEST/${stem}.json"
    echo "  $stem ..."
    raw=$(MSYS_NO_PATHCONV=1 railway ssh --service Blueview2 -- cat "$src")
    # Strip any leading non-JSON banner up to the first '{'.
    cleaned="${raw#*\{}"
    cleaned="{${cleaned}"
    printf '%s' "$cleaned" > "$dst"
    echo "      wrote $dst ($(wc -c < "$dst") bytes)"
done

echo ""
echo "Snapshots ready in $DEST. Commit to git as part of PR #15B.1."
