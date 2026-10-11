"""Set a job's WhatsApp groups' "Languages spoken" (bot_config.languages).
DRY RUN unless --apply.

    railway run python scripts/group_languages_set.py --project 588 --langs en,yi
    railway run python scripts/group_languages_set.py --project 588 --langs en,yi --apply

The same setting as Group settings -> Languages spoken in the app, for every
group of the job (or the ones whose name contains --group). 588 is EN+YI
(Oct 11): no Whisper hint, every note also goes straight to English, and a
note heard as English whose direct English says something else is flagged.
Nothing is sent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


def parse_langs(value: str):
    from lib import wa_voice
    langs = wa_voice.group_languages([v.strip().lower() for v in value.split(",") if v.strip()])
    if langs is None:
        raise SystemExit(f"--langs must be a comma list of {', '.join(wa_voice.GROUP_LANGS)}")
    return langs


async def main_async(a) -> int:
    import server
    from scripts.wa_provenance import _find_project
    db = server.db
    langs = parse_langs(a.langs)
    p = await _find_project(db, a.project)
    q = {"project_id": str(p["_id"])}
    groups = await db.whatsapp_groups.find(q).to_list(200)
    if a.group:
        groups = [g for g in groups if a.group.lower() in str(g.get("group_name") or "").lower()]
    print(f"{p.get('name')}: {len(groups)} group(s) -> {'+'.join(l.upper() for l in langs) or 'any'}"
          f"{'' if a.apply else ' (dry run)'}")
    for g in groups:
        before = ((g.get("bot_config") or {}).get("languages")) or []
        print(f"  {g.get('group_name') or g['_id']}: "
              f"{'+'.join(l.upper() for l in before) or 'any'} -> "
              f"{'+'.join(l.upper() for l in langs) or 'any'}")
        if a.apply and before != langs:
            await db.whatsapp_groups.update_one({"_id": g["_id"]},
                                                {"$set": {"bot_config.languages": langs}})
    print("applied" if a.apply else "nothing written; --apply to write")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="project id, or part of its name/address")
    ap.add_argument("--langs", required=True, help="comma list of en, es, yi (e.g. en,yi)")
    ap.add_argument("--group", default="", help="only groups whose name contains this")
    ap.add_argument("--apply", action="store_true", help="write the setting")
    return asyncio.run(main_async(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
