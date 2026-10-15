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


def rows():
    return dict(checkins=checkins(), logbooks=logbooks(), chat=chat(), records=records(),
                events=events(), commitments=commitments(), punch_items=punch_items())


def verdicts():
    return {photo_key(s, d): v for (s, d), v in PHOTOS.items()}


def report(summary=None):
    from lib import progress_report as P
    rep = P.compute(job=JOB, address=ADDRESS, gc=GC, start=START, end=END, now=NOW, **rows())
    rep["photos"] = P.pick_photos(P.to_judge(rep["photo_candidates"]), verdicts())
    rep["summary"] = summary if summary is not None else P.summary_fallback(rep)
    return rep
