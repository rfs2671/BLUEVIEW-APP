"""THE FILED DOCUMENT, RENDERED. One place, so a conversion moves one file.

── WHY THIS MODULE EXISTS ─────────────────────────────────────────────────

Fourteen test files asserted rules about the filed sheet by COUNTING STRINGS IN
`server.py`:

    self.assertEqual(SRC.count("+ PRESHIFT_ATTESTATION_HTML"), N_RENDERERS)

That was a true and useful claim while a hand-written branch composed the
document. It is not a claim about the DOCUMENT; it is a claim about the source
that used to build it. When five branches were deleted -- after their sheets had
rendered in production and been read -- 33 assertions across those files went
red, and not one of them was about a rule that had broken. Every rule they name
still reaches the page; it arrives from a declaration now.

A19 predicted exactly this and called it "the same shape for every conversion
after this one". Six types are still branch-rendered, so the shape has six more
turns to take.

── THE RESTATEMENT ────────────────────────────────────────────────────────

A rule about a filed document is asserted ON THE FILED DOCUMENT. `sheet(type)`
renders one, through whatever renderer that type currently uses, and the
assertion reads the output. That claim is STRONGER than the string count -- it
survives the branch, the engine, and whatever replaces the engine -- and it is
the one the file's own docstring was always making in words.

── WHAT IS DELIBERATELY NOT HERE ──────────────────────────────────────────

The clock is frozen, because two renders of one record must be comparable; see
test_the_legal_render_engine.py for why that freeze is mandatory and what it
hid the one time it patched the wrong name.

NOTHING IS MOCKED ABOVE THE RENDERER. The document comes out of
`generate_single_logbook_html`, which is the function the PDF route calls. A
helper that assembled the sheet itself would be a second renderer, and this
whole migration is about there being one.
"""

from __future__ import annotations

import asyncio
import html as _h
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import patch

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402

PROJECT = {"_id": "p1", "name": "588 Thomas",
           "address": "588 Thomas S Boyland Street",
           "company_name": "Metro Build Constructors LLC",
           "bbl": "3035400025", "nyc_bin": "3255362"}

#: A drawable mark. Geometry is never what a test varies.
STROKES = [[{"x": 1, "y": 2}, {"x": 30, "y": 20}, {"x": 60, "y": 5}]]

AFFIRMED = {"paths": STROKES, "signerName": "daniel kaplan", "affirmed": True,
            "affirmedAt": "2026-08-04T19:56:00Z",
            "affirmed_received_at": "2026-08-04T19:56:00Z"}
UNAFFIRMED = {"paths": STROKES, "signerName": "alex rivera"}

#: PER-TYPE DATA, FILLED RATHER THAN MINIMAL.
#:
#: A fixture that leaves a field out renders an absence, and an assertion that
#: a cell is missing then passes for the wrong reason. Every key a declaration
#: or a branch reads is present here with a value that is recognisable in the
#: output.
DATA: Dict[str, dict] = {
    "preshift_signin": {
        "workers": [
            # ONE SIGNED ROW AND ONE UNSIGNED, because a roster where every
            # cell is the same exercises neither branch of the cell. The mark
            # is INLINE: `signin_id` resolution reads the `signins`
            # collection, which this stub does not carry, and a row that fell
            # back to "recorded and not drawable" would make an assertion
            # about a drawn signature pass on the fallback.
            {"name": "wilmer carrillo", "company": "aaz",
             "osha_number": "11112222", "had_injury": "no",
             "inspected_ppe": "yes", "signin_id": "s1",
             "signature": {"paths": STROKES}},
            {"name": "segundo pilamunga", "company": "quality plumbing",
             "osha_number": "33334444", "had_injury": "yes",
             "inspected_ppe": "no"},
        ],
    },
    "osha_log": {
        "entries": [
            {"worker_name": "wilmer carrillo", "company": "aaz",
             "certification_type": "SST", "card_number": "11112222",
             "expiration": "2027-03-01", "signed": True},
        ],
    },
    "toolbox_talk": {
        "location": "gate", "company_name": "aaz", "performed_by": "carl cp",
        "meeting_time": "07:30 AM", "checked_topics": {"hard_hats": True},
        "attendees": [
            {"name": "wilmer carrillo", "title": "foreman", "company": "aaz",
             "time": "07:15", "added_from": "gate", "signed": True},
        ],
    },
    "scaffold_maintenance": {
        "scaffold_id": "S-4", "location": "north elevation",
        "inspection_result": "pass",
        "questions": {"planking_secure": "YES", "guardrails_intact": "YES"},
        "notes": "nothing outstanding",
    },
    "site_superintendent_log": {
        "presence": {"printed_name": "daniel kaplan", "arrived_at": "07:00",
                     "departed_at": "15:30"},
    },
    "daily_jobsite": {
        "weather": "Clear", "weather_temp": "70F",
        "general_description": "formwork on the third floor",
        "equipment_on_site": {"compressor": True},
        "checklist_items": {"street_frontage": {"result": "pass"}},
        "activities": [{"trade": "carpentry", "workers_count": "6",
                        "work_description": "formwork",
                        "work_locations": "third floor"}],
        "observations": [],
    },
    "subcontractor_orientation": {
        "worker_name": "alex rivera", "worker_company": "Premier Builders Inc.",
        "worker_trade": "carpenter", "language_provided": "English",
        "completed_at": "2026-09-09T07:00:00",
        "checklist": {"hard_hats": True, "safety_boots": True,
                      "no_horseplay": False},
        "worker_signature": UNAFFIRMED,
    },
    # ── THE SIX WITH NO PRODUCTION RECORDS ─────────────────────────
    #
    # DERIVED FROM THE UNION of what the branch reads and what the
    # declaration binds, then written out as a literal so a reviewer
    # can look at the record and say whether it is a plausible permit.
    # The first version filled 6 of the 9 paths a hot work permit
    # needs and none of crane's checklist, so both renderers drew the
    # same emptiness and the comparison agreed about nothing.
    #
    # EACH ONE CARRIES ITS OWN ADVERSE CASE. A record where every
    # answer is yes cannot show that a no prints as a no.
    # FDNY 3504. One precaution answered NO and four yes: a permit
    # where every box is ticked cannot show that a refusal prints as
    # a refusal.
    "hot_work": {"end_time": "14:00",
     "fire_watch_end_time": "14:30",
     "fire_watch_name": "carl cp",
     "location": "Roof bulkhead",
     "precautions": {"area_cleared": True,
                     "combustibles_covered": False,
                     "fire_extinguisher_present": True,
                     "fire_watch_assigned": True,
                     "sprinklers_operational": True},
     "start_time": "08:00",
     "work_type": "Brazing",
     "worker_cert_number": "FDNY-W-4471",
     "worker_name": "wilmer carrillo"},

    # One load at a short radius and one at a long one,
    # because the radius is what makes a weight safe or not.
    "crane_operations": {"crane_id": "CR-7",
     "crane_type": "Mobile",
     "load_entries": [{"description": "Steel beam",
                       "load_weight": "2.1 t",
                       "radius": "38 ft",
                       "time": "07:30"},
                      {"description": "Rebar bundle",
                       "load_weight": "0.8 t",
                       "radius": "52 ft",
                       "time": "09:15"}],
     "operator_license": "NYC-CO-88213",
     "operator_name": "segundo pilamunga",
     "pre_operation_checklist": {"brakes": True,
                                 "hooks_latches": True,
                                 "load_chart": False,
                                 "outriggers": True,
                                 "wire_ropes": True}},

    # One slump test PASS and one FAIL. A pour record
    # where every test passed cannot show that a failure
    # prints as a failure.
    "concrete_operations": {"concrete_supplier": "aaz concrete",
     "formwork_checklist": {"bracing_adequate": True,
                            "formwork_clean": False,
                            "shores_plumb": True},
     "mix_design": "4000 psi",
     "pour_location": "Third floor slab",
     "slump_tests": [{"pass": True,
                      "time": "08:10",
                      "value": "4.5 in"},
                     {"pass": False,
                      "time": "11:40",
                      "value": "6.0 in"}],
     "temperature": "58F",
     "volume_ordered": "42 cy",
     "weather_conditions": "Overcast"},

    # Two adjacent buildings, one of them moving. A
    # monitoring log where nothing moved cannot show
    # that a reading over the threshold says so.
    "excavation_monitoring": {"adjacent_buildings": [{"address": "586 Thomas S Boyland",
                             "baseline_reading": "0.00 in",
                             "current_reading": "0.02 in",
                             "delta": "+0.02 in"},
                            {"address": "590 Thomas S Boyland",
                             "baseline_reading": "0.00 in",
                             "current_reading": "0.31 in",
                             "delta": "+0.31 in"}],
     "atmospheric_testing": True,
     "excavation_depth": "8 ft",
     "groundwater_observed": False,
     "protection_system": "Sloping and benching",
     "soil_type": "Type B",
     "vibration_current": "0.21 in/sec",
     # THE FLAG, WHICH IS WHAT MAKES THE STATUS A COMPARISON AND NOT
     # ARITHMETIC. `vibration_status` refuses to derive a verdict from the two
     # readings -- that would be this renderer doing sums on a compliance
     # record -- so a fixture without it prints "Status — Not recorded" for a
     # reading well under its threshold. The app computes it
     # (`isOverThreshold`); 0.21 against 0.50 is False.
     "vibration_over_threshold": False,
     "vibration_threshold": "0.50 in/sec"},

    # One harness that PASSED with no defect, and one lanyard
    # REMOVED FROM SERVICE -- which `inspection_result` must
    # not fold into Fail: one says the harness failed a check,
    # the other says it is off the site.
    "fall_protection": {"activities": [{"action_taken": "",
                     "anchor_point": "Roof davit",
                     "company": "aaz",
                     "defect_found": "",
                     "equipment_id": "H-4",
                     "equipment_type": "Harness",
                     "impact_loaded": False,
                     "manufacture_date": "2024-03-11",
                     "result": "pass",
                     "worker_name": "wilmer carrillo"},
                    {"action_taken": "Tagged and removed from site",
                     "anchor_point": "Beam clamp",
                     "company": "quality plumbing",
                     "defect_found": "Frayed webbing at the thimble",
                     "equipment_id": "L-9",
                     "equipment_type": "Lanyard",
                     "impact_loaded": True,
                     "manufacture_date": "2019-08-02",
                     "result": "removed from service",
                     "worker_name": "segundo pilamunga"}]},

    # Every one of the thirteen fields the branch reads.
    # This sheet is almost entirely yes/no answers, and
    # an unanswered one is not a No.
    "ssc_daily_safety_log": {"corrective_actions_taken": "None required",
     "fire_protection_in_place": True,
     "housekeeping_satisfactory": True,
     "incident_details": "",
     "incidents_reported": False,
     "ppe_compliance": True,
     "project_address": "588 Thomas S Boyland",
     "safety_meetings_held": True,
     "safety_violations_observed": "no",
     "site_conditions": "Dry and secure",
     "ssp_number": "SSP-2026-0441",
     "weather": "Clear",
     "workers_on_site_count": "26"},
}


def logbook(log_type: str, *, status: str = "submitted",
            cp_signature: Optional[dict] = AFFIRMED,
            amended: bool = False, data: Optional[dict] = None,
            **extra) -> dict:
    """One filed record of `log_type`, filled."""
    lb = {
        "_id": "lb1", "project_id": "p1", "date": "2026-09-09",
        "log_type": log_type, "cp_name": "daniel kaplan", "status": status,
        "data": dict(DATA.get(log_type) or {}),
    }
    if cp_signature is not None:
        lb["cp_signature"] = cp_signature
    if data:
        lb["data"].update(data)
    if amended:
        lb["is_amendment"] = True
        lb["amendment_reason"] = "the crew count was transcribed wrong"
        lb["created_by_name"] = "Rosa Delgado"
        lb["created_at"] = "2026-09-11T14:02:00Z"
    lb.update(extra)
    return lb


class _Cur:
    def __init__(self, rows): self._rows = rows
    def sort(self, *a, **k): return self
    def limit(self, *a, **k): return self
    async def to_list(self, *a, **k): return list(self._rows)

    # ASYNC-ITERABLE, BECAUSE THE CALLER ITERATES IT THAT WAY. Without this
    # the pre-shift affirmation count raises inside its own try/except, logs a
    # warning nobody reads in a test run, and falls back to zero -- so an
    # assertion about the affirmation footer would pass on a sheet whose count
    # never ran. A stub that fails softly is a fixture asserting the fallback.
    def __aiter__(self):
        async def gen():
            for r in self._rows:
                yield r
        return gen()


class _Coll:
    def __init__(self, rows=None): self._rows = rows or []
    def find(self, *a, **k): return _Cur(self._rows)
    async def find_one(self, *a, **k): return dict(PROJECT)
    async def count_documents(self, *a, **k): return 0
    def aggregate(self, *a, **k): return _Cur([])


class _DB:
    def __init__(self, rows=None): self._rows = rows or {}
    def __getattr__(self, name): return _Coll(self._rows.get(name))


def render(lb: dict, *, rows: Optional[dict] = None) -> str:
    """The whole filed document, clock frozen."""
    stack = [patch.object(server, "db", _DB(rows or {})),
             patch.object(server, "to_query_id", lambda v: v),
             patch.object(server, "eastern_datetime", lambda *a, **k: "FROZEN")]
    for p in stack:
        p.start()
    try:
        return asyncio.run(server.generate_single_logbook_html(lb))
    finally:
        for p in reversed(stack):
            p.stop()


def sheet(log_type: str, **kw) -> str:
    """The filed document for one type, rendered from a filled fixture."""
    rows = kw.pop("rows", None)
    return render(logbook(log_type, **kw), rows=rows)


def visible(html: str) -> str:
    """The text a reader sees, with images and ink kept as TOKENS.

    THE TOKENS COME FIRST. The baseline instrument tokenised `src=` and then
    stripped the tag it lived in, so `[IMAGE]` never survived and every
    comparison built on it was blind to every signature on the page. Same
    order here, for the same reason.
    """
    s = re.sub(r"<img\b[^>]*>", " [IMAGE] ", html, flags=re.I)
    s = re.sub(r"<svg\b.*?</svg>", " [INK] ", s, flags=re.S | re.I)
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", _h.unescape(s)).strip()


def cells(html: str, header: str) -> List[str]:
    """Every body cell of the column headed `header`, as visible text.

    BOTH MARKUPS. The branch emits a bare `<th>`; the table primitive emits
    `<th style=...>`, and both end `>Label</th>`.
    """
    i = html.index(f">{header}</th>")
    head_start = html.rindex("<tr", 0, i)
    head_end = html.index("</tr>", i)
    heads = re.findall(r"<th[^>]*>(.*?)</th>",
                       html[head_start:head_end], flags=re.S)
    col = [re.sub(r"<[^>]+>", "", h).strip() for h in heads].index(header)
    table_end = html.index("</table>", i)
    body = html[head_end:table_end]
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, flags=re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
        if len(tds) > col:
            out.append(visible(tds[col]))
    return out
