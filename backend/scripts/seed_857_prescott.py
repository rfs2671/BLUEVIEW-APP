"""Seed a throwaway test project for one day's device testing.

DRY RUN BY DEFAULT. Nothing is written without --execute.

    python seed_857_prescott.py                      # plan only, writes nothing
    python seed_857_prescott.py --execute            # write
    python seed_857_prescott.py --execute --base-url http://localhost:8000

EVERYTHING GOES THROUGH THE REAL HTTP ENDPOINTS. No direct collection writes.
That is the whole point: the Daily Jobsite Log's Step 1 reads crews out of gate
check-in data, so a seed that inserted differently-shaped rows would make the
device test validate against fiction.

  project   POST /api/projects              (create_project, admin)
  roster    PUT  /api/projects/{id}         (update_project — server mints the
                                             trade_assignments row ids)
  tag       POST /api/projects/{id}/nfc-tags
  check-in  POST /api/checkin/register-and-checkin   <-- the LIVE GATE endpoint
  log       POST /api/logbooks + POST /api/logbooks/{id}/finalize

WHY register-and-checkin AND NOT /checkin/submit: submit is the returning-worker
path and requires the worker to already exist with cert evidence on file.
register-and-checkin is what checkin.html calls for a first-time worker on a
site (backend/checkin.html), and it is the only path that creates the worker,
builds certifications from card data, resolves the roster, and writes the
checkins row in one call — i.e. the row Step 1 will read.

Run the teardown script tonight. It is scoped to this project id only.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:                                        # pragma: no cover
    sys.exit("pip install requests")

PROJECT_NAME = "857 Prescott Pl"
PROJECT_ADDRESS = "857 Prescott Pl, Brooklyn, NY 11213"

# cast_in_place, deliberately. The rules graph splits the superstructure into a
# cast-in-place loop and a CFS loop; leaving it unset returns BOTH (86 chips)
# and structural_system_set=false, which is the "not configured" case rather
# than the ranking case. Picking a branch is what gives the chips something to
# rank against, and cast-in-place is the larger loop on this graph (78 chips vs
# 70), so more of the catalogue is exercised.
STRUCTURAL_SYSTEM = "cast_in_place"

# Yesterday's logged activity. VERIFIED against the real graph, not guessed:
#   rank_activities(structural_system='cast_in_place',
#                   prior_activity_ids=['building_envelope_closed'])
# puts exactly three chips in the `suggested` band —
#   building_envelope_closed   (concurrent / multi-day work stays offered)
#   insulation                 (opened by the rule)
#   drywall                    (opened by the rule)
# — which is short enough to eyeball on a phone and mid-sequence enough to be
# a real test rather than the cold-start list.
PRIOR_ACTIVITY = "building_envelope_closed"

TAG_ID = "TEST-857-GATE-01"

# One company on TWO trades (Vanguard) so the per-subcontractor photo bucket can
# be tested ACROSS rows — the cap is 10 per sub aggregated, not 10 per row.
ROSTER = [
    {"trade": "Concrete", "company": "Vanguard Concrete Corp"},
    {"trade": "Formwork", "company": "Vanguard Concrete Corp"},
    {"trade": "Electrical", "company": "Kestrel Electric LLC"},
    {"trade": "HVAC / Mechanical", "company": "Air Star Mechanical"},
    {"trade": "Carpentry", "company": "Northside Carpentry"},
]

# EASTERN, NOT UTC. The jobsite is in New York and the whole system buckets
# days on Eastern midnight — get_day_range_est() in server.py exists for exactly
# this reason and says so: "use this instead of parsing the date as UTC
# midnight, which buckets a late-evening Eastern check-in into the next calendar
# day." The CP's phone also sends its LOCAL date.
#
# The first version used datetime.now(timezone.utc).date(). Run at 20:51 in New
# York, UTC has already rolled over, so "UTC yesterday" IS New York TODAY — the
# prior-day log landed on today's date and the ranker, which reads priors with
# {"$lt": day}, would never have seen it. Any run between 8pm and midnight
# Eastern hit this; a morning run would have looked fine, which is worse.
_EASTERN = ZoneInfo("America/New_York")
_TODAY = datetime.now(_EASTERN).date()

# MM/DD/YYYY, NOT ISO. build_worker_certifications parses card dates with
# _parse_mdy (server.py) which is strptime("%m/%d/%Y") and returns None on
# anything else. The first version sent .isoformat(), so every expiry parsed as
# None: no expiry was stored, EXPIRED_SST could never fire, and the worker
# seeded 95 days past expiry displayed as "unverified" instead of "expired".
_MDY = "%m/%d/%Y"
FUTURE = (_TODAY + timedelta(days=420)).strftime(_MDY)
PAST = (_TODAY - timedelta(days=95)).strftime(_MDY)
ISSUED = (_TODAY - timedelta(days=800)).strftime(_MDY)


def sst(expiration, card_class="FULL", number=None, name=None, issued=ISSUED):
    """osha_data exactly as the vision endpoint returns it after a card scan.

    THE FULL OCR CONTRACT. The extractor returns name, sst_number, card_type,
    card_class, issued, expiration and box_2d; build_worker_certifications reads
    the first six. `box_2d` is the card-crop bounding box and is deliberately
    absent — there is no card image on a seeded check-in.

    The first version sent only card_type / card_class / expiration /
    sst_number. `name` missing meant name_ok was False (server.py:1998), which
    forces needs_review True (server.py:2042) -> SST_UNKNOWN for EVERY worker
    regardless of their card data. That is why all 13 read "unverified SST" and
    the three intended states never appeared.

    NOTE ON WHAT THIS DOES NOT PROVE: card PHOTO presence does not drive the
    flag — every completeness signal comes from this dict, not from image bytes.
    A seeded worker is therefore not a test of the photo-upload-failure path.
    """
    return {
        "name": name,
        "sst_number": number or f"SST{uuid.uuid4().hex[:8].upper()}",
        "card_type": "SST",
        "card_class": card_class,
        "issued": issued,
        "expiration": expiration,
    }


# 13 workers. `flag` is documentation for the dry-run print, not sent.
WORKERS = [
    # ── deliberately flagged ────────────────────────────────────────────────
    {"name": "Hector Ramirez", "phone": "3475550101", "trade": "Concrete",
     "company": "Vanguard Concrete Corp", "osha_data": sst(PAST),
     "flag": "EXPIRED SST  -> sst_status 'expired', shows on the review screen"},
    {"name": "Dmitri Volkov", "phone": "3475550102", "trade": "Electrical",
     "company": "Kestrel Electric LLC", "osha_data": sst("illegible", card_class=None),
     "flag": "UNKNOWN card -> sst_status 'unknown' (class + expiry unreadable)"},
    {"name": "Samuel Boateng", "phone": "3475550103", "trade": None,
     "company": None, "osha_data": sst(FUTURE), "trade_not_listed": True,
     "flag": "NO TRADE     -> needs_trade_assignment true, CP assigns on /review"},
    # ── clean ───────────────────────────────────────────────────────────────
    {"name": "Luis Alvarez", "phone": "3475550104", "trade": "Concrete",
     "company": "Vanguard Concrete Corp", "osha_data": sst(FUTURE)},
    {"name": "Marcus Bell", "phone": "3475550105", "trade": "Concrete",
     "company": "Vanguard Concrete Corp", "osha_data": sst(FUTURE)},
    {"name": "Tomasz Nowak", "phone": "3475550106", "trade": "Formwork",
     "company": "Vanguard Concrete Corp", "osha_data": sst(FUTURE)},
    {"name": "Andre Duval", "phone": "3475550107", "trade": "Formwork",
     "company": "Vanguard Concrete Corp", "osha_data": sst(FUTURE)},
    {"name": "Kevin O'Rourke", "phone": "3475550108", "trade": "Electrical",
     "company": "Kestrel Electric LLC", "osha_data": sst(FUTURE)},
    {"name": "Ravi Chandra", "phone": "3475550109", "trade": "Electrical",
     "company": "Kestrel Electric LLC", "osha_data": sst(FUTURE)},
    {"name": "Joseph Kim", "phone": "3475550110", "trade": "HVAC / Mechanical",
     "company": "Air Star Mechanical", "osha_data": sst(FUTURE)},
    {"name": "Ernesto Diaz", "phone": "3475550111", "trade": "HVAC / Mechanical",
     "company": "Air Star Mechanical", "osha_data": sst(FUTURE)},
    {"name": "Patrick Shea", "phone": "3475550112", "trade": "Carpentry",
     "company": "Northside Carpentry", "osha_data": sst(FUTURE)},
    {"name": "Owen Bradley", "phone": "3475550113", "trade": "Carpentry",
     "company": "Northside Carpentry", "osha_data": sst(FUTURE)},
]

# The OCR `name` is the name printed ON THE CARD, so it is the worker's own.
# Filled here rather than repeated in every row above. Without it name_ok is
# False and EVERY worker lands in SST_UNKNOWN no matter what else is on the
# card — which is exactly what made all 13 read "unverified SST".
for _w in WORKERS:
    if _w["osha_data"].get("name") is None:
        _w["osha_data"]["name"] = _w["name"]

SIGNATURE = {
    "paths": [[[10, 40], [40, 10], [70, 45], [100, 12]]],
    "signerName": "Test CP",
    "affirmed": True,
}


class Api:
    def __init__(self, base, execute):
        self.base = base.rstrip("/")
        self.execute = execute
        self.token = None
        self.s = requests.Session()

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def post(self, path, body, auth=True, label="", already_filed_ok=False):
        """POST, with 423 optionally treated as an OUTCOME rather than a failure.

        423 FROM /api/logbooks MEANS ALREADY FILED. An END_OF_DAY log is one
        record per day by design (server.py: "the daily narrative is one record
        per day; corrections go through /amend"), so re-running this seed
        against a project whose prior-day log is already filed is not an error —
        it is the normal second run. The script advertises that:

            PROJECT ALREADY EXISTS -> {pid}  (not duplicating)
            Re-running only adds check-ins and the prior-day log to it.

        It checked for an existing PROJECT and never for an existing LOG, so the
        second run died on the 423 the server raises deliberately. The server is
        right; this was wrong.

        Returns None when the row was already filed, so the caller can record
        the skip. Every other 4xx/5xx still stops the run — a seed that
        swallowed real failures would be worse than one that stopped.
        """
        if not self.execute:
            print(f"  [DRY-RUN] POST {path}  {label}")
            return {"id": f"dry-{uuid.uuid4().hex[:8]}", "_dry": True}
        r = self.s.post(f"{self.base}{path}", json=body,
                        headers=self._h() if auth else {}, timeout=60)
        if already_filed_ok and r.status_code == 423:
            return None
        if r.status_code >= 400:
            raise SystemExit(f"POST {path} -> {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else {}

    def get_or_none(self, path):
        """GET that returns None instead of stopping the run.

        Used only by the closing verification, which must be able to say "I
        could not confirm" rather than take the whole seed down after every
        write has already succeeded.
        """
        try:
            r = self.s.get(f"{self.base}{path}", headers=self._h(), timeout=60)
        except Exception:
            return None
        if r.status_code >= 400:
            return None
        return r.json() if r.content else {}

    def put(self, path, body, label=""):
        if not self.execute:
            print(f"  [DRY-RUN] PUT  {path}  {label}")
            return {"_dry": True}
        r = self.s.put(f"{self.base}{path}", json=body, headers=self._h(), timeout=60)
        if r.status_code >= 400:
            raise SystemExit(f"PUT {path} -> {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else {}

    def get(self, path):
        r = self.s.get(f"{self.base}{path}", headers=self._h(), timeout=60)
        if r.status_code >= 400:
            raise SystemExit(f"GET {path} -> {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else {}

    def all_projects(self):
        """Every project visible to this account, as a list of dicts.

        GET /api/projects goes through paginated_query and returns
        {items, total, limit, skip, has_more} — NOT a bare list. Iterating the
        raw response yields dict KEYS, i.e. strings, which is why the first
        version died on `'str' object has no attribute 'get'`.

        Paginated at 50 by default, so page 1 is not the whole answer: an
        existing 857 Prescott Pl sitting past the first page would look absent
        and the seed would happily create a second one. Walk the pages.

        Tolerates a bare list too, so this keeps working if the endpoint is ever
        un-paginated — and raises with the ACTUAL shape rather than an
        AttributeError if it becomes something else again.
        """
        out, skip = [], 0
        while True:
            page = self.get(f"/api/projects?limit=200&skip={skip}")
            if isinstance(page, list):
                items, has_more = page, False
            elif isinstance(page, dict) and isinstance(page.get("items"), list):
                items = page["items"]
                has_more = bool(page.get("has_more"))
            else:
                raise SystemExit(
                    "GET /api/projects returned an unexpected shape: "
                    f"{type(page).__name__} "
                    f"keys={list(page)[:8] if isinstance(page, dict) else 'n/a'}"
                )
            bad = [i for i in items if not isinstance(i, dict)]
            if bad:
                raise SystemExit(
                    f"GET /api/projects items are not dicts: {type(bad[0]).__name__}"
                )
            out.extend(items)
            if not has_more or not items:
                return out
            skip += len(items)


def _read_priors(api, pid):
    """Every daily_jobsite on the project, narrowed and widened.

    The endpoint defaults to limit=50 sorted by date, so on a project with a
    long history the prior could sit off the first page and the caller would
    report a cold start that is not real.
    """
    return api.get_or_none(
        f"/api/logbooks/project/{pid}?log_type=daily_jobsite&limit=500")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true",
                    help="write (default: dry run, writes nothing)")
    ap.add_argument("--base-url", default="https://api.levelog.com")
    ap.add_argument("--email", default="1@1.com")
    ap.add_argument("--password", required=True)
    a = ap.parse_args()

    api = Api(a.base_url, a.execute)
    mode = "EXECUTE" if a.execute else "DRY-RUN"
    print(f"=== seed 857 Prescott Pl — {mode} — {a.base_url} ===\n")

    # ── 1. auth ─────────────────────────────────────────────────────────────
    # Always real, even in a dry run: if the credentials are wrong there is no
    # point printing a plan that could never run.
    r = api.s.post(f"{api.base}/api/auth/login",
                   json={"email": a.email, "password": a.password}, timeout=60)
    if r.status_code >= 400:
        raise SystemExit(f"login failed {r.status_code}: {r.text[:300]}")
    body = r.json()
    if not isinstance(body, dict):
        raise SystemExit(f"login returned {type(body).__name__}, expected an object")
    # TokenResponse declares `token` (server.py). The first version reached for
    # `access_token` first and only found `token` through a fallback — it worked
    # by luck, not because it was right. Correct key first, fallback kept for a
    # deployment that predates the model.
    api.token = body.get("token") or body.get("access_token")
    if not api.token:
        raise SystemExit(f"login returned no token; keys were {list(body)}")
    print(f"  authenticated as {a.email}\n")

    # ── 2. project (find or create — never duplicate) ───────────────────────
    all_projects = api.all_projects()
    print(f"  {len(all_projects)} project(s) visible to this account")
    existing = [p for p in all_projects
                if str(p.get("name", "")).strip().lower() == PROJECT_NAME.lower()
                and not p.get("is_deleted")]
    if existing:
        pid = existing[0].get("id") or existing[0].get("_id")
        print(f"  PROJECT ALREADY EXISTS -> {pid}  (not duplicating)")
        print("  Re-running only adds check-ins and the prior-day log to it.\n")
    else:
        created = api.post("/api/projects", {
            "name": PROJECT_NAME,
            "address": PROJECT_ADDRESS,
            "location": PROJECT_ADDRESS,
            "status": "active",
            "structural_system": STRUCTURAL_SYSTEM,
        }, label=PROJECT_NAME)
        pid = created.get("id") or created.get("_id")
        print(f"  PROJECT created -> {pid}  structural_system={STRUCTURAL_SYSTEM}\n")

    # ── 3. roster + structural system ───────────────────────────────────────
    # Sent through update_project so the row ids are SERVER-minted, exactly as
    # the admin screen does it. The activity rows the CP fills reference those
    # ids, so client-minted ones would not resolve.
    api.put(f"/api/projects/{pid}", {
        "structural_system": STRUCTURAL_SYSTEM,
        "trade_assignments": ROSTER,
    }, label=f"{len(ROSTER)} roster rows")
    for row in ROSTER:
        print(f"      {row['trade']:20} {row['company']}")
    print("      ^ Vanguard appears on TWO trades — that is the photo-bucket case\n")

    # ── 4. the gate tag ─────────────────────────────────────────────────────
    api.post(f"/api/projects/{pid}/nfc-tags",
             {"tag_id": TAG_ID, "location_description": "Test gate"},
             label=TAG_ID)
    print(f"  NFC TAG {TAG_ID}\n")

    # ── 5. check-ins, through the LIVE GATE ─────────────────────────────────
    print(f"  CHECK-INS via POST /api/checkin/register-and-checkin ({len(WORKERS)}):")
    for w in WORKERS:
        body = {
            "project_id": pid,
            "tag_id": TAG_ID,
            "name": w["name"],
            "phone": w["phone"],
            "osha_number": w["osha_data"]["sst_number"],
            "osha_data": w["osha_data"],
            "language_provided": "en",
            "safety_orientation": {"site_rules": True, "ppe": True, "emergency": True},
        }
        if w.get("trade"):
            body["trade"] = w["trade"]
        if w.get("company"):
            body["company"] = w["company"]
        if w.get("trade_not_listed"):
            body["trade_not_listed"] = True
        api.post("/api/checkin/register-and-checkin", body, auth=False,
                 label=w["name"])
        note = f'   <-- {w["flag"]}' if w.get("flag") else ""
        print(f"      {w['name']:20} {str(w.get('trade') or '(none)'):20}{note}")
    print()

    # ── 6. yesterday's finalized log, so the ranker has a prior ─────────────
    today = _TODAY.isoformat()
    yday = (_TODAY - timedelta(days=1)).isoformat()
    # The ranker reads priors with {"$lt": day} — STRICTLY before the day being
    # logged — so that re-opening today's log does not rank off itself. A prior
    # dated today is invisible and the chips fall back to cold start. Assert the
    # relationship rather than trusting the arithmetic; it was wrong once.
    if not yday < today:
        raise SystemExit(
            f"REFUSING: prior-day date {yday} is not strictly before {today}. "
            "The ranker would never read it."
        )
    log = api.post("/api/logbooks", {
        "project_id": pid,
        "log_type": "daily_jobsite",
        "date": yday,
        "cp_name": "Test CP",
        "cp_signature": SIGNATURE,
        "status": "submitted",
        "data": {
            "project_address": PROJECT_ADDRESS,
            "weather": "Cloudy", "weather_temp": "61F", "weather_wind": "8 mph",
            "general_description": "Envelope closed on floors 3-5.",
            "activities": [{
                "activity_id": f"act_seed_{uuid.uuid4().hex[:6]}",
                "subcontractor_id": None,
                "crew_id": "C1",
                "company": "Northside Carpentry",
                "num_workers": "2",
                "work_description": "Envelope closed",
                "work_locations": "Floors 3-5",
                "photos": [],
                # THE FIELD THE RANKER READS (server.py _activity_chip_ids).
                #
                # A LIST, matching what the U1 stepper writes. It used to be the
                # legacy single-string `activity_chip_id`, and that was the only
                # thing in the whole system writing it — so the chip test was
                # the seed handing the ranker the field the ranker wanted, and
                # it passed while every log a real CP filed contributed nothing.
                # Writing what the editor writes is what makes the test mean
                # something.
                "activity_ids": [PRIOR_ACTIVITY],
            }],
            "equipment_on_site": {}, "checklist_items": {}, "observations": [],
        },
    }, label=f"daily_jobsite {yday} — {PRIOR_ACTIVITY}", already_filed_ok=True)
    skipped_days = []
    if log is None:
        # ALREADY FILED. Not an error and not a success either — see the
        # verification below, which reads the priors back rather than assuming
        # this one is usable.
        skipped_days.append(yday)
        print(f"  PRIOR-DAY LOG {yday}  ALREADY FILED — not re-created")
    else:
        lid = log.get("id") or log.get("_id")
        api.post(f"/api/logbooks/{lid}/finalize", {}, label="finalize")
        print(f"  PRIOR-DAY LOG {yday}  activity_ids=[{PRIOR_ACTIVITY}]  -> {lid}")

    # ── DID THE RANKER ACTUALLY GET A PRIOR? ────────────────────────────────
    #
    # "ALREADY FILED" AND "THE RANKER HAS HISTORY" ARE DIFFERENT FACTS, and
    # conflating them is what makes a cold seed indistinguishable from a project
    # with no history — the failure that has cost time twice.
    #
    # The ranker needs a log that is BOTH dated strictly before today AND
    # carrying activity_ids on at least one activity (server.py
    # _activity_chip_ids). A pre-existing log can satisfy the first and not the
    # second: an older seed wrote the legacy single-string `activity_chip_id`,
    # and a log filed by a real CP who described work without tapping a chip
    # carries none at all. Either way the skip above would print "already
    # filed" while the ranker stayed cold.
    #
    # So this READS THE PRIORS BACK instead of inferring from the skip.
    print()
    print("  RANKER PRIORS — verified by reading them back, not inferred:")
    if not api.execute:
        # A DRY RUN HAS WRITTEN NOTHING, and `pid` may be a minted dry id. Any
        # verdict here would describe a project that does not exist — the exact
        # false confidence this whole block was added to remove.
        print("    [DRY-RUN] not checked — nothing was written.")
        rows = None
        truncated = False
    else:
        rows = _read_priors(api, pid)
        truncated = bool(isinstance(rows, dict) and rows.get("has_more"))
    # NARROWED AND WIDENED. The endpoint defaults to limit=50 sorted by date,
    # so on a project with a long history the prior could sit off the first
    # page and this would report a cold start that is not real. log_type filters
    # server-side; limit=500 is the endpoint's documented ceiling.
    if not api.execute:
        pass
    elif rows is None:
        print("    COULD NOT VERIFY — the logbooks read failed. Everything above")
        print("    was written; this line alone is unconfirmed. Re-run to check.")
    else:
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("logbooks") or rows.get("data") or []
        usable = []
        for lg in rows if isinstance(rows, list) else []:
            if lg.get("log_type") != "daily_jobsite":
                continue
            d = str(lg.get("date") or "")
            if not d or not (d < today):          # STRICTLY before today
                continue
            acts = ((lg.get("data") or {}).get("activities")) or []
            ids = [i for a in acts for i in ((a or {}).get("activity_ids") or [])]
            if ids:
                usable.append((d, sorted(set(ids))))
        usable.sort()
        if usable:
            for d, ids in usable[-3:]:
                print(f"    {d}  activity_ids={ids}")
            print(f"    -> {len(usable)} usable prior(s). THE RANKER HAS HISTORY;")
            print("       today's chips will be ranked, not cold start.")
        elif truncated:
            # NOT ASSERTED FROM A PARTIAL PAGE. Saying "cold start" here when
            # the read was truncated would be the same conflation this check
            # exists to prevent, one level up.
            print("    NONE FOUND, but the read was TRUNCATED (has_more=true).")
            print("    -> CANNOT SAY whether the ranker has history. Re-read with")
            print("       a higher skip before concluding anything.")
        else:
            print("    NONE. No daily_jobsite before today carries activity_ids.")
            print("    -> THE RANKER WILL COLD-START. Today's chips will be the")
            print("       cold-start set, which looks identical to a project with")
            print("       no history. If that is not what you wanted, the")
            print("       prior-day log needs activity_ids on an activity.")
    if skipped_days:
        print()
        print(f"  SKIPPED (already filed, not re-created): {', '.join(skipped_days)}")
    print(f"      today (America/New_York) is {today}")
    print(f"      the ranker reads priors with date < {today}, so {yday} qualifies")
    print("      today's suggested chips should be exactly:")
    print("        building_envelope_closed, insulation, drywall\n")

    print("=" * 66)
    print(f"PROJECT ID: {pid}")
    print("Give this id to the teardown script tonight.")
    if not a.execute:
        print("\nDRY RUN — nothing was written. Re-run with --execute.")


if __name__ == "__main__":
    main()
