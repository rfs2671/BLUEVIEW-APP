#!/bin/bash
# Standing probes for ruling 154 (read-only). Usage: bash run.sh <backend tree> <out dir>
# Needs C:/Users/asddd/bv-worktrees/loc867_out/{prod_common.py,prod_snapshot.json} and census154/schedules_all.json
# (census154_fetch.py refreshes the schedule snapshot: `railway run python census154_fetch.py <out.json>`, a read-only find).
set -e; export PYTHONUTF8=1
T=$1; O=$2; mkdir -p $O; H=$(dirname "$0")
python $H/value_grid.py $T $O/vgrid.json              # prints: <claims> <bound>
python $H/census.py $T $O/census.json                  # per-schedule count-shaped bound claims
python $H/untagged_and_countrule.py $T $O/untagged.json
