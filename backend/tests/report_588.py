"""The 588 job's records for Oct 2-15, 2026, as the server reads them.

The punch items are the real 588 walk (tests/fixtures/punch_walk_6a868363.json,
47 items, Oct 13). The check-ins, filed daily logs, group chat, commitments,
DOB/DOT record and upcoming events are a fixture shaped like 588's: the four
subs on the job (Arkon framing, Quality Plumbing risers, Power Direct
electrical rough, J&G scaffolding) with made-up crews, days, words and
photos. No phone numbers; no links.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
START, END = date(2026, 10, 2), date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 22, 0, tzinfo=timezone.utc)        # Thu 6 PM New York
JOB = "588 Thomas S Boyland St"
ADDRESS = "588 Thomas S Boyland St, Brooklyn, NY"
GC = "Blueview Construction"

WORKDAYS = [START + timedelta(days=i) for i in range(14) if (START + timedelta(days=i)).weekday() < 5]

# Workers on site per day, by sub (each a distinct worker id).
CREWS = {
    "Arkon Builders": dict(zip(WORKDAYS, [12, 13, 14, 14, 15, 14, 15, 16, 15, 16])),
    "Quality Plumbing": {d: n for d, n in zip(WORKDAYS[1:], [4, 4, 5, 5, 6, 6, 5, 6, 6])},
    "Power Direct": {d: n for d, n in zip(WORKDAYS[4:], [5, 6, 7, 7, 8, 8])},
    "J&G Scaffolding": {WORKDAYS[0]: 4, WORKDAYS[1]: 4, WORKDAYS[2]: 3, WORKDAYS[9]: 7},
}

# Each crew's line in the filed daily log: (work, locations).
WORK = {
    "Arkon Builders": ("Framing", lambda d: "Floors 1-2" if d <= date(2026, 10, 9) else "Floors 3-4"),
    "Quality Plumbing": ("Riser install", lambda d: "Floors 1-3"),
    "Power Direct": ("Electrical rough-in", lambda d: "Floors 1-2"),
    "J&G Scaffolding": ("Scaffolding", lambda d: "Front facade" if d < date(2026, 10, 15) else "Rear facade"),
}
TRADE = {"Arkon Builders": "Framing", "Quality Plumbing": "Plumbing", "Power Direct": "Electrical",
         "J&G Scaffolding": "Scaffolding"}
NO_LOG = {date(2026, 10, 7)}                                     # a day nobody filed the log

# Photos in the daily logs: (sub, day) -> the vision verdict the fixture
# gives it.
PHOTOS = {
    ("Arkon Builders", date(2026, 10, 2)): {"ok": True, "kind": "progress", "score": 7,
                                            "caption": "Metal stud framing started on the 1st floor"},
    ("Arkon Builders", date(2026, 10, 9)): {"ok": True, "kind": "progress", "score": 8,
                                            "caption": "Studs and top track in place on the 2nd floor"},
    ("Arkon Builders", date(2026, 10, 15)): {"ok": True, "kind": "progress", "score": 9,
                                             "caption": "Framing on the 4th floor, corridor walls up"},
    ("Arkon Builders", date(2026, 10, 12)): {"ok": False, "kind": "people", "score": 2,
                                             "caption": "Crew standing in the corridor"},
    ("Quality Plumbing", date(2026, 10, 5)): {"ok": True, "kind": "progress", "score": 6,
                                              "caption": "Riser sleeves set at the 1st floor slab"},
    ("Quality Plumbing", date(2026, 10, 14)): {"ok": True, "kind": "progress", "score": 8,
                                               "caption": "Copper risers installed through the 3rd floor"},
    ("Quality Plumbing", date(2026, 10, 9)): {"ok": False, "kind": "blurry", "score": 1,
                                              "caption": "Out of focus"},
    ("Power Direct", date(2026, 10, 8)): {"ok": True, "kind": "progress", "score": 6,
                                          "caption": "Boxes and conduit going in on the 1st floor"},
    ("Power Direct", date(2026, 10, 15)): {"ok": True, "kind": "progress", "score": 8,
                                           "caption": "Rough-in wiring pulled on the 2nd floor"},
    ("Power Direct", date(2026, 10, 13)): {"ok": False, "kind": "document", "score": 0,
                                           "caption": "A drawing"},
    ("J&G Scaffolding", date(2026, 10, 2)): {"ok": True, "kind": "progress", "score": 7,
                                             "caption": "Scaffold going up on the front facade"},
    ("J&G Scaffolding", date(2026, 10, 15)): {"ok": True, "kind": "progress", "score": 7,
                                              "caption": "Scaffold set at the rear facade"},
}


def photo_key(sub: str, d: date) -> str:
    slug = "".join(c for c in sub.lower() if c.isalnum())[:10]
    return f"logbooks/fixture588/{slug}-{d.isoformat()}.jpg"


def _at(d: date, h: int = 7, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=NY).astimezone(timezone.utc)


def checkins():
    out = []
    for sub, days in CREWS.items():
        tag = "".join(w[0] for w in sub.split()).lower()
        for d, n in days.items():
            for w in range(n):
                out.append({"worker_id": f"{tag}{w}", "worker_name": f"{sub.split()[0]} worker {w + 1}",
                            "worker_company": sub, "check_in_time": _at(d, 7, w % 50)})
            # A second check-in of the same worker the same day counts once.
            out.append({"worker_id": f"{tag}0", "worker_company": sub, "check_in_time": _at(d, 12)})
    return out


def logbooks():
    out = []
    for d in WORKDAYS:
        if d in NO_LOG:
            continue
        acts = []
        for sub, days in CREWS.items():
            if d not in days:
                continue
            work, where = WORK[sub]
            photos = []
            if (sub, d) in PHOTOS:
                k = photo_key(sub, d)
                photos.append({"original_r2_key": k, "enhanced_r2_key": None, "thumb_r2_key": None})
            acts.append({"company": sub, "trade": TRADE[sub], "num_workers": days[d],
                         "work_description": work, "work_locations": where(d), "photos": photos})
        obs = []
        if d == date(2026, 10, 6):
            obs.append({"description": "Concrete delivery for stair 2 pushed to next week by the supplier."})
        if d == date(2026, 10, 9):
            obs.append({"description": "Power Direct short 2 workers today; rough-in on the 2nd floor behind."})
        if d == date(2026, 10, 13):
            obs.append({"description": "Punch walkthrough of floors 1-4 with the owner's rep."})
        if d == date(2026, 10, 2):
            obs.append({"description": "N/A"})
        out.append({"_id": f"log-{d.isoformat()}", "project_id": "p588", "log_type": "daily_jobsite",
                    "status": "submitted", "date": d.isoformat(),
                    "data": {"activities": acts, "observations": obs}})
    return out


def chat():
    rows = [
        (date(2026, 10, 5), 8, "Site super", "Scaffold on the front is up, J&G finishing netting tomorrow"),
        (date(2026, 10, 8), 15, "Site super", "Arkon done framing 2nd floor tomorrow, moving to 3rd floor Monday"),
        (date(2026, 10, 12), 9, "Site super", "Quality Plumbing needs the 3rd floor cleared for risers Wednesday"),
        (date(2026, 10, 14), 16, "PM", "Plumbing inspection for the risers is booked for Tuesday the 20th"),
        (date(2026, 10, 15), 10, "Levelog", "bot line, never in the report"),
        (date(2026, 10, 15), 11, "Site super", "ok"),
    ]
    out = []
    for d, h, who, text in rows:
        out.append({"sender": "bot" if who == "Levelog" else f"jid-{who}", "sender_name": who,
                    "body": text, "timestamp": _at(d, h)})
    out.append({"sender": "jid-x", "sender_name": "Foreman", "body": "(voice note — not processed)",
                "timestamp": _at(date(2026, 10, 13), 9), "skipped": "voice_empty"})
    return out


def commitments():
    def c(owner, sub, what, due, made):
        return {"status": "open", "summary": what, "owner": {"name": owner, "sub_company": sub},
                "due": {"due_at": due.isoformat()}, "created_at": _at(made)}
    return [
        c("Power Direct", "Power Direct", "Send revised electrical shop drawings", date(2026, 10, 9),
          date(2026, 10, 5)),
        c("Quality Plumbing", "Quality Plumbing", "Pressure test risers fl 1-3", date(2026, 10, 12),
          date(2026, 10, 6)),
        c("Arkon Builders", "Arkon Builders", "Fire-blocking at the shaft walls, 2nd floor",
          date(2026, 10, 13), date(2026, 10, 8)),
        c("J&G Scaffolding", "J&G Scaffolding", "Netting on the front scaffold", date(2026, 10, 8),
          date(2026, 10, 5)),
        c("Quality Plumbing", "Quality Plumbing", "Riser photos for the inspector", date(2026, 10, 19),
          date(2026, 10, 14)),
        {"status": "done", "summary": "Clear the 3rd floor", "owner": {"name": "Arkon Builders"},
         "due": {"due_at": "2026-10-13"}, "created_at": _at(date(2026, 10, 12))},
    ]


def records():
    return [{"record_type": "dot_permit", "number": "X01-2026278-A11", "issue_date": "2026-10-08",
             "status": "ISSUED", "detected_at": _at(date(2026, 10, 8))}]


def events():
    return [{"date": "2026-10-20", "time": "9:00 AM", "kind": "inspection", "agency": "DOB",
             "title": "Plumbing inspection, risers fl 1-3", "status": "open"},
            {"date": "2026-10-23", "kind": "delivery", "title": "Concrete delivery for stair 2",
             "status": "open"}]


def punch_items():
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "fixtures", "punch_walk_6a868363.json"), encoding="utf-8") as f:
        walk = json.load(f)
    out = []
    for it in walk["items"]:
        at = datetime.fromisoformat(it["at"]).replace(tzinfo=timezone.utc)
        out.append({"pid": it["n"], "text": it.get("text") or "", "floor": it.get("floor"),
                    "area": it.get("area"), "photo_key": it.get("photo_key"), "status": "open",
                    "created_at": at})
    return out


# ── THE PREVIOUS PERIOD, THE CITY'S RECORDS AND A SCHEDULE ────────────────────
#
# Added with the unified report. Like everything above, a fixture SHAPED like
# 588 -- made-up subs, days, words and dates -- not records from the live job.

PREV_START, PREV_END = date(2026, 9, 18), date(2026, 10, 1)
PREV_WORKDAYS = [PREV_START + timedelta(days=i) for i in range(14)
                 if (PREV_START + timedelta(days=i)).weekday() < 5]
PREV_CREWS = {
    "Metro Demolition": {d: 9 for d in PREV_WORKDAYS[:6]},                     # off the job by Sep 25
    "Arkon Builders": {d: n for d, n in zip(PREV_WORKDAYS[4:], [8, 9, 10, 10, 11, 11])},
    "J&G Scaffolding": {PREV_WORKDAYS[8]: 3, PREV_WORKDAYS[9]: 3},
}
PREV_WORK = {"Metro Demolition": ("Interior demolition", "Floors 1-4"),
             "Arkon Builders": ("Framing", "Floor 1"),
             "J&G Scaffolding": ("Scaffolding", "Front facade")}
PREV_TRADE = {"Metro Demolition": "Demolition", "Arkon Builders": "Framing", "J&G Scaffolding": "Scaffolding"}


def previous_checkins():
    out = []
    for sub, days in PREV_CREWS.items():
        tag = "p" + "".join(w[0] for w in sub.split()).lower()
        for d, n in days.items():
            for w in range(n):
                out.append({"worker_id": f"{tag}{w}", "worker_name": f"{sub.split()[0]} worker {w + 1}",
                            "worker_company": sub, "check_in_time": _at(d, 7, w % 50)})
    return out


def previous_logbooks():
    out = []
    for d in PREV_WORKDAYS:
        acts = []
        for sub, days in PREV_CREWS.items():
            if d in days:
                work, where = PREV_WORK[sub]
                acts.append({"company": sub, "trade": PREV_TRADE[sub], "num_workers": days[d],
                             "work_description": work, "work_locations": where, "photos": []})
        if acts:
            out.append({"_id": f"log-{d.isoformat()}", "project_id": "p588", "log_type": "daily_jobsite",
                        "status": "submitted", "date": d.isoformat(), "data": {"activities": acts}})
    return out


def _hist(*pairs):
    return [{"status": st, "at": at, "source": src} for st, at, src in pairs]


def dob_rows():
    """The city's records for the job, each with its status history (what the
    sync now writes): a stop-work order issued before the period and lifted in
    it, a violation issued and still open, a permit that expires soon, a
    violation resolved in the period, and an old record the first sync found
    (no history: issued years ago, never "new")."""
    return [
        {"_id": "d1", "record_type": "swo", "raw_dob_id": "swo:SWO-2026-0041", "stop_work_order_number": "SWO-2026-0041",
         "violation_date": "2026-09-20", "violation_subtype": "SWO_PARTIAL", "current_status": "RESCINDED",
         "dob_link": "https://a810-bisweb.nyc.gov/example/swo-0041", "detected_at": _at(date(2026, 9, 21)),
         "status_changed_at": _at(date(2026, 10, 6)), "previous_status": "ACTIVE",
         "status_history": _hist(("ACTIVE", _at(date(2026, 9, 21)), "first_seen"),
                                 ("RESCINDED", _at(date(2026, 10, 6)), "sync"))},
        {"_id": "d2", "record_type": "violation", "raw_dob_id": "viol:35123456", "violation_number": "35123456",
         "violation_date": "2026-10-08", "current_status": "ACTIVE", "violation_type": "ECB",
         "dob_link": "https://a810-bisweb.nyc.gov/example/35123456", "detected_at": _at(date(2026, 10, 9)),
         "status_history": _hist(("ACTIVE", _at(date(2026, 10, 9)), "first_seen"))},
        {"_id": "d3", "record_type": "permit", "raw_dob_id": "permit:B00123456-I1", "job_number": "B00123456-I1",
         "permit_status": "ISSUED", "current_status": "ISSUED", "issuance_date": "2026-03-02",
         "expiration_date": "2026-11-10", "detected_at": _at(date(2026, 4, 1)),
         "status_history": _hist(("ISSUED", _at(date(2026, 4, 1)), "first_seen"))},
        {"_id": "d4", "record_type": "violation", "raw_dob_id": "viol:29887711", "violation_number": "29887711",
         "violation_date": "2025-11-14", "current_status": "RESOLVED",
         "detected_at": _at(date(2026, 9, 25)), "status_changed_at": _at(date(2026, 10, 12)),
         "previous_status": "ACTIVE",
         "status_history": _hist(("ACTIVE", _at(date(2026, 9, 25)), "first_seen"),
                                 ("RESOLVED", _at(date(2026, 10, 12)), "sync"))},
        {"_id": "d5", "record_type": "violation", "raw_dob_id": "viol:11002299", "violation_number": "11002299",
         "violation_date": "2019-06-03", "current_status": "RESOLVED", "detected_at": _at(date(2026, 10, 3)),
         "is_seed_transition": False},
    ]


def dot_rows():
    return [{"_id": "t1", "record_type": "dot_permit", "raw_id": "X01-2026278-A11", "number": "X01-2026278-A11",
             "issue_date": "2026-10-08", "status": "ISSUED", "current_status": "ISSUED",
             "expiration_date": "2027-01-08", "detected_at": _at(date(2026, 10, 8)),
             "status_history": _hist(("ISSUED", _at(date(2026, 10, 8)), "first_seen"))}]


def city_events():
    return [{"source": "city", "date": "2026-10-28", "kind": "hearing", "agency": "OATH",
             "title": "OATH hearing, violation 35123456", "status": "open"},
            # A date read out of a chat message is NOT a city date: never in the report.
            {"source": "chat", "date": "2026-10-20", "kind": "inspection", "agency": "DOB",
             "title": "Plumbing inspection, risers fl 1-3", "status": "open"}]


SYNC = {"tracking": True, "dob": NOW, "dob_complete": True, "dot": NOW}


def schedule_doc():
    """A schedule as a scheduler would export it to Excel, read by the real
    importer: planned and current dates, actuals, a reported percent on some
    rows, a data date of Oct 14."""
    import io
    import openpyxl
    from lib import schedule_import
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Schedule"
    ws.append(["Project: 588 Thomas S Boyland (fixture)", None, None, None, None, None, None, None, None])
    ws.append(["Status date", "2026-10-14"])
    ws.append(["ID", "Task Name", "Baseline Start", "Baseline Finish", "Start", "Finish", "Actual Start",
               "Actual Finish", "% Complete"])
    D = date
    rows = [
        ("1", "Mobilization & demolition", D(2026, 8, 31), D(2026, 9, 25), D(2026, 8, 31), D(2026, 9, 25),
         D(2026, 8, 31), D(2026, 9, 25), 100),
        ("2", "Interior demolition complete", D(2026, 9, 25), D(2026, 9, 25), D(2026, 9, 25), D(2026, 9, 25),
         None, D(2026, 9, 25), 100),
        ("3", "Metal stud framing floor 1", D(2026, 9, 28), D(2026, 10, 9), D(2026, 9, 28), D(2026, 10, 9),
         D(2026, 9, 28), D(2026, 10, 9), 100),
        ("4", "Metal stud framing floor 2", D(2026, 10, 5), D(2026, 10, 16), D(2026, 10, 5), D(2026, 10, 16),
         D(2026, 10, 5), None, 85),
        ("5", "Metal stud framing floor 3", D(2026, 10, 12), D(2026, 10, 23), D(2026, 10, 13), D(2026, 10, 27),
         D(2026, 10, 13), None, 40),
        ("6", "Metal stud framing floor 4", D(2026, 10, 19), D(2026, 10, 30), D(2026, 10, 22), D(2026, 11, 5),
         None, None, 0),
        ("7", "Plumbing risers floors 1-3", D(2026, 10, 5), D(2026, 10, 20), D(2026, 10, 5), D(2026, 10, 22),
         D(2026, 10, 5), None, 70),
        ("8", "Electrical rough-in floor 1", D(2026, 10, 8), D(2026, 10, 21), D(2026, 10, 8), D(2026, 10, 21),
         D(2026, 10, 8), None, 55),
        ("9", "Rough plumbing inspection", D(2026, 10, 20), D(2026, 10, 20), D(2026, 10, 20), D(2026, 10, 20),
         None, None, 0),
        ("10", "Framing complete, floors 1-4", D(2026, 10, 30), D(2026, 10, 30), D(2026, 11, 5), D(2026, 11, 5),
         None, None, 0),
        ("11", "Substantial completion", D(2027, 2, 26), D(2027, 2, 26), D(2027, 3, 12), D(2027, 3, 12),
         None, None, 0),
    ]
    for r in rows:
        ws.append([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]])
    buf = io.BytesIO()
    wb.save(buf)
    doc = schedule_import.parse_schedule("588 Master Schedule.xlsx", buf.getvalue())
    for a in doc["activities"]:             # the three "complete / framing complete" rows are milestones
        if a["name"] in ("Interior demolition complete", "Rough plumbing inspection",
                         "Framing complete, floors 1-4", "Substantial completion"):
            a["kind"] = "milestone"
    return doc


def rows():
    return dict(checkins=checkins(), logbooks=logbooks(), chat=chat(), records=records(),
                events=events(), commitments=commitments(), punch_items=punch_items())


def verdicts():
    return {photo_key(s, d): v for (s, d), v in PHOTOS.items()}


def unified_rows(*, schedule=False):
    """The rows the unified report reads for Oct 2-15 and the period before it.
    The chat, commitments and punch items of `rows()` are NOT among them: the
    report does not read them."""
    out = dict(checkins=checkins() + previous_checkins(), logbooks=logbooks() + previous_logbooks(),
               dob_rows=dob_rows(), dot_rows=dot_rows(), events=city_events(), sync=SYNC,
               first_activity=date(2026, 8, 31))
    if schedule:
        out["schedule"] = schedule_doc()
        out["schedule_meta"] = {"source_name": "588 Master Schedule.xlsx", "confirmed_by": "Site PM"}
    return out


def report(*, schedule=False, **over):
    from lib import progress_report as P
    args = dict(job=JOB, address=ADDRESS, gc=GC, start=START, end=END, now=NOW, kind="biweekly",
                **unified_rows(schedule=bool(schedule)))
    if isinstance(schedule, dict):                   # a schedule document of the test's own
        args["schedule"] = schedule
    args.update(over)
    rep = P.compute(**args)
    rep["photos"] = P.pick_photos(P.to_judge(rep["photo_candidates"]), verdicts())
    return rep
