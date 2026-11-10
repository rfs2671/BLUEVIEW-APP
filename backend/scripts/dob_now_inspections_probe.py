"""READ-ONLY OPERATOR PROBE: DOB NOW: Inspections for the given BINs.

    PYTHONUTF8=1 python backend/scripts/dob_now_inspections_probe.py 3430621 3255362
    PYTHONUTF8=1 python backend/scripts/dob_now_inspections_probe.py 3430621 3255362 --record B01141294S5PL
    PYTHONUTF8=1 python backend/scripts/dob_now_inspections_probe.py 3430621 --json

Runs LOCALLY against the public portal (a810-lmpaca.nyc.gov/CitizenAccessBuildings):
searches every BIN given, reads each record once (deduped across BINs), replays
the async postback that fills its inspection list, and prints the normalized
results, the evidence items they make, and the sources checked / unreachable /
not loaded. It needs no database, opens none, and writes nothing anywhere
(stdout only). It does not need DOB_NOW_PORTAL_ENABLED: that flag gates the
server, and this is an operator running it by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import dob_now_inspections as D  # noqa: E402
from lib import dob_now_portal as P  # noqa: E402
from lib import source_coverage as SC  # noqa: E402
from probe_helpers import counted  # noqa: E402


def _json(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return str(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bins", nargs="+", help="every BIN of the site (current and obsolete)")
    ap.add_argument("--record", action="append", default=[], help="read only these record ids (repeatable)")
    ap.add_argument("--delay", type=float, default=P.DEFAULT_DELAY, help="seconds between requests (polite)")
    ap.add_argument("--json", action="store_true", help="print the whole result as JSON")
    args = ap.parse_args(argv)

    portal = P.Portal(delay=max(args.delay, 0.5))
    result = P.check_bins(args.bins, portal, only=args.record or None)
    items, cov = D.to_evidence(result.get("records") or [], "probe")
    if args.json:
        print(json.dumps({"result": result, "items": items, "coverage": cov}, default=_json, indent=1))
        return 0

    print(f"DOB NOW: Inspections — BINs {', '.join(result['bins'])} — state: {result['state']}"
          + (f" ({result.get('why')})" if result.get("why") else ""))
    for b, s in (result.get("searched") or {}).items():
        print(f"  search BIN {b}: {s['found']} record(s) on {s['pages']} page(s); portal states {s['stated_total']}")
    print("\n".join(D.answer_lines(result)) or "  (no records read)")
    by_kind = (", ".join(f"{k} {counted(items, 'kind', lambda v, k=k: v == k)}" for k in ("verified", "confirmed"))
               if items else "none")
    print(f"\nEvidence items: {len(items)}  (by kind: {by_kind})")
    for i in items:
        print(f"  {i['kind']:9} {i['claim']:6} {str(i['on'] or 'undated'):10} {i['node'] or '-':22} "
              f"{','.join(i['levels']) or '-':12} {i['ref']}")
    print(f"\nCoverage: lists loaded {cov['lists_loaded']}, not loaded {cov['lists_not_loaded'] or 'none'}; "
          f"floor cells {cov['floor_cells']}; results making no claim {cov['no_claim'] or 'none'}")
    print("\n".join(SC.coverage_lines([P.coverage_entry(result)], topic="inspections")))
    for u in result.get("unreachable") or []:
        print(f"  UNREACHABLE / NOT LOADED: {u['what']}: {u['why']}")
    log = list(portal.log)
    print(f"\nRequests made: {len(log)} (read-only GET + async-postback POST replays)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
