"""WHAT THE OLD SHEET SAID THAT THE NEW ONE DOES NOT.

    python compare.py daily_jobsite

Renders every production record of one type through the CURRENT tree and diffs
its visible text against the baseline captured while that type's branch was
still the renderer. See README.md for why this exists.

RUN IT BEFORE THE BRANCH IS DELETED, not after. The baseline makes the diff
possible at any time, but a difference found while the branch still exists can
be read directly off the two renderers; found afterwards it is archaeology.

IT REPORTS MISSING WORDS, NOT MISSING MEANING. A word that survives in a
different sentence counts as present, and a section that moved reads as no
change at all. This narrows what a person has to read. It does not replace
them.
"""
import asyncio
import base64
import gzip
import html as _h
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

BASELINE = HERE / "before-conversion-2026-09-12.b64"

#: Words the redesign is KNOWN to have dropped on purpose, so a reader is not
#: made to re-clear them on every run. Each is a decision somebody made.
#:
#: NOTHING GOES ON THIS LIST TO MAKE A RUN QUIET. The status words are here
#: because they are tracked as defect A17, not because they are acceptable.
BY_DESIGN = {
    # The old dark header block and footer, replaced by the engine's
    # letterhead. Branding, not content.
    "levelog", "management", "construction", "generated", "on",
    # Section and label wording the schema deliberately restates.
    "date", "status",
}


def visible(html: str) -> str:
    s = re.sub(r'src="[^"]*"', 'src="INK"', html)
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _h.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def words(t: str) -> set:
    # CASE FOLDED. The first run of this comparison reported the job address
    # missing when the engine had merely uppercased it.
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'/-]+", t)}


async def main(log_type: str):
    import server

    base = json.loads(gzip.decompress(
        base64.b64decode(BASELINE.read_text().strip())).decode())
    if log_type not in base:
        sys.exit(f"no baseline for {log_type!r}; have: {sorted(base)}")
    rows = base[log_type]
    print(f"{log_type}: {len(rows)} records in the baseline\n")

    recs = await server.db.logbooks.find({
        "log_type": log_type, "is_deleted": {"$ne": True}}).to_list(2000)
    by_id = {str(r.get("_id")): r for r in recs}

    missing_records = [k for k in rows if k not in by_id]
    if missing_records:
        print(f"!! {len(missing_records)} baselined records are not in the "
              f"database any more; they cannot be compared\n")

    every_lost = {}
    unchanged = 0
    for rid, old in sorted(rows.items(), key=lambda kv: kv[1]["date"]):
        rec = by_id.get(rid)
        if rec is None:
            continue
        try:
            new = visible(await server.generate_single_logbook_html(rec))
        except Exception as e:
            print(f"  {old['date']}  {rid[-6:]}  !! {type(e).__name__}: {e}")
            continue
        lost = words(old["text"]) - words(new) - BY_DESIGN
        if not lost:
            unchanged += 1
            continue
        for w in lost:
            every_lost.setdefault(w, []).append(old["date"])
        print(f"  {old['date']}  {rid[-6:]}  lost {len(lost):>3}: "
              f"{sorted(lost)[:12]}")

    print(f"\n{unchanged} of {len(rows)} records say everything they said.")
    if every_lost:
        print("\nEVERY WORD LOST, and how many records lost it:")
        for w, dates in sorted(every_lost.items(),
                               key=lambda kv: -len(kv[1])):
            print(f"   {w:28} {len(dates):>4} records")
        print("\nREAD THESE. A word on this list is either a decision somebody "
              "made and can name, or content that fell off a filed document.")
    else:
        print("\nNothing was lost. That is the claim the conversion needs, and "
              "it is now a claim about the OLD sheet rather than about itself.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.new_event_loop().run_until_complete(main(sys.argv[1]))
