"""THE CANNED SET. EVERY VALUE IN THIS FILE IS FICTION.

Not a fixture, not a seed, not "sample data we could promote later": a closed
set of invented records that exists so a DEMO principal can be shown the real
admin screens with no database behind them. Nothing here describes a real
building, a real worker, a real company or a real DOB record, and nothing here
may ever be reached by a principal who is not a demo.

── WHAT THIS MODULE IS NOT ────────────────────────────────────────────────

It is NOT the guard. Nothing in `lib/demo` decides who may see it; the
request-layer gate does that, and this module would happily hand its payloads
to anyone who imported it. That split is deliberate — the fiction and the
authorization are reviewed by different eyes — but it means the rule has to be
written down on this side too: **a non-demo principal must never reach these
functions.** If you are wiring a route to them, the `is_demo(user)` test goes at
the route, before the call, and it fails closed.

It is NOT a database. Nothing here reads Mongo, opens a socket, touches R2, or
asks for the time. The set is closed, which is what makes it safe to serve to
an unapproved account: a demo cannot cost a cent and cannot leak a row.

It is NOT a place for anything real. No real company id, no real tenant's
address, no real worker's name, no deliverable email address, no reachable
phone number, no card photograph, no R2 key. Every identifier starts with
`demo`, every company name carries the word Demo, every address is at
`example.invalid` (RFC 2606 reserves it so it can never resolve), every phone
sits in the 555-01xx fictional block, and a test sweeps the whole SERVED
SURFACE — not just these constants — for all of it.

── THE ONE INHERITED FACT ─────────────────────────────────────────────────

The project is the seed already in `server.py` as `_DEMO_PROJECT`, served by
GET /demo/project: "Sample Project — 852 East 176th Street", BIN 2115914,
§3310 class major_a, and the {5 permits, 2 violations, 1 complaint, 8
inspections} summary. Everything here is built OUTWARD from it and stays
consistent with it — same project id `demo`, same name, same address, same
class, same counts. The BIN and the street address are the operator's chosen
seed and are the only values in this file that read like a real address on
purpose; they name a demo project and no tenant of this app.

── DATES ARE OFFSETS, NOT DATES ───────────────────────────────────────────

Nothing here stores a calendar date. Every date is written as an integer offset
in days, under a key that names the field it produces, and `shaping.py` resolves
it against a `today` the CALLER passes:

    _<field>_days_ago: N   ->  <field> = today - N days
    _<field>_in_days:  N   ->  <field> = today + N days

    ...rendered as an ISO date string, or as a UTC datetime when the field name
    ends in `_at`, because that is how the real documents store each.

Every `_`-prefixed key is dropped once resolved, so nothing downstream ever
sees the offsets. Two reasons for the whole scheme, and the second is the one
that matters:

  * a stored date makes a test flaky the moment the suite runs on another day,
    and a demo whose tests are flaky gets its tests deleted;
  * a fixed date makes the DEMO stale. A prospect opening the app in March to
    find its most recent log filed last September has learned something true
    about the product, and it is not what we wanted to show him.

`DEMO_ANCHOR` is the default `today`. It exists so the tests have a fixed frame
and so a caller who forgets to pass one gets a coherent set rather than a
crash — never so that a live demo runs on it.

── THE CLASSIFICATION IS DERIVED, NOT ASSERTED ────────────────────────────

`project_class` here is `major_a`, and the measurements beside it (12 storeys,
140 ft) are the measurements that PRODUCE major_a through
`server.classify_project`. A test re-derives it rather than comparing the
string, because a demo that claims a class its own numbers contradict is a
compliance product failing its own demo — and because the required-logbook set,
which is the largest thing on the CP's home screen, is computed from that class.

── AND THE SHEETS CARRY THE REAL FIELD NAMES ──────────────────────────────

`DEMO_LOGBOOK_DATA` uses the exact keys each editor writes and each filed-sheet
renderer reads (`lib/legal_render/schema.py`). This is not pedantry: several
sections VANISH from the filed document when their key is absent
(`scaffold_maintenance` prints no checklist at all without `data.answers`), and
several rows are DROPPED when a `row_requires` field is blank (a pre-shift
worker row with no `name`, an OSHA register row with no `worker_name`). A demo
sheet built from plausible-sounding key names renders as a page of blank rules,
which is the one thing worse than showing nothing.
"""

from __future__ import annotations

from datetime import date

# ── IDENTITY ────────────────────────────────────────────────────────────────
#
# `demo` for the project because that is the id `_DEMO_PROJECT` already uses and
# GET /demo/project already returns; changing it would orphan the seed. Every
# other id is prefixed `demo-` so that a row appearing somewhere it should not —
# a log line, an error report, a screenshot in a bug ticket — is identifiable as
# fiction at a glance by someone who has never read this file.
DEMO_PROJECT_ID = "demo"
DEMO_COMPANY_ID = "demo-company"
DEMO_COMPANY_NAME = "Demo Construction LLC"
DEMO_USER_ID = "demo-user"
DEMO_CP_NAME = "Alex Moreno"

#: The day the set is written around. Not "today" — see the header.
DEMO_ANCHOR = date(2026, 9, 15)

#: The days the demo presents as FINISHED. Every daily required log is filed and
#: frozen on each of them, so the deficiency screens have nothing to raise.
DEMO_CLOSED_DAY_OFFSETS = (-3, -2, -1)

#: The day in progress. Some logs are open drafts here, which is what makes the
#: demo look like a site rather than an archive.
DEMO_OPEN_DAY_OFFSET = 0

#: Reserved by RFC 2606 precisely so that it can never be delivered to.
DEMO_EMAIL_DOMAIN = "example.invalid"
DEMO_REPORT_EMAIL = f"demo.reports@{DEMO_EMAIL_DOMAIN}"

#: The fictional subscriber block (555-0100…555-0199) is the only phone range
#: guaranteed to reach nobody. Stored E.164 because that is the form
#: `normalize_phone` writes and therefore the form a real row holds.
DEMO_SITE_PHONE = "+12125550100"


# ── THE PROJECT ─────────────────────────────────────────────────────────────
#
# Field-for-field the shape GET /projects/{project_id} returns. That handler
# filters through `ProjectResponse`, which is an ALLOW-LIST — anything the model
# does not declare is dropped silently before it reaches a screen — so every
# declared field is given a value here, including the ones that are honestly
# empty (no Dropbox link, no completion, no legal hold). "Absent" and "empty"
# render differently and only one of them is true of this project.
#
# The five keys after the model's fields — is_demo, dob_summary,
# recent_activity, special_inspections, note — are `_DEMO_PROJECT`'s own. They
# are not on ProjectResponse and would be dropped if this were ever served
# through it; GET /demo/project has no response model, which is how the seed
# carries them today.
#
# THE TOGGLES ARE HERE AND NOT ON ProjectResponse EITHER, and that is not our
# oversight: `scaffold_erected` and `superintendent_log_active` are read off the
# project DOCUMENT by `get_required_logbooks` and have never been declared on
# the response model. They are stored here because the required set is computed
# from them, and a demo whose scaffold log appears with no scaffold toggle
# behind it is a demo that cannot explain itself.
DEMO_PROJECT = {
    # ── ProjectResponse ────────────────────────────────────────────────────
    "id": DEMO_PROJECT_ID,
    "name": "Sample Project — 852 East 176th Street",
    "location": "Bronx, NY",
    "address": "852 East 176th Street, Bronx, NY 10460",
    "status": "active",
    "nickname": "Sample Project",
    "company_id": DEMO_COMPANY_ID,
    "company_name": DEMO_COMPANY_NAME,
    "nfc_tags": [
        # {tag_id, location} is the denormalised array the project document
        # holds; GET /projects/{id}/nfc-tags joins `provisional` and
        # `created_by_role` onto each row from the nfc_tags collection, so both
        # are supplied — a demo row missing them would render as provisional.
        {"tag_id": "demo-tag-main-gate", "location": "Main gate — East 176th",
         "provisional": False, "created_by_role": "admin"},
        {"tag_id": "demo-tag-hoist", "location": "Hoist landing — level 3",
         "provisional": False, "created_by_role": "admin"},
    ],
    # Dead fields on the real model, kept because project/[id].jsx still reads
    # them. Their values say "no Dropbox folder is linked", which is true: a
    # demo has no Dropbox account behind it and must not appear to.
    "dropbox_folder": None,
    "dropbox_enabled": False,
    "dropbox_folder_path": None,
    "dropbox_last_synced": None,
    "dropbox_sync": None,
    "_created_at_days_ago": 212,
    "nyc_bin": "2115914",
    # NO BBL, AND THE ABSENCE IS DELIBERATE. A BBL is a real cadastral key; the
    # seed's BIN is the operator's chosen fiction and one invented land
    # identifier is enough. `bbl_source` stays None too, so no screen claims a
    # provenance for a value that does not exist.
    "bbl": None,
    "bbl_source": None,
    "bbl_last_synced": None,
    "_last_dob_sync_at_days_ago": 0,
    "track_dob_status": True,
    "report_email_list": [DEMO_REPORT_EMAIL],
    "report_send_time": "18:00",
    # ── §3310 ──────────────────────────────────────────────────────────────
    # 12 storeys and 140 ft: both over the Major Building thresholds (10
    # storeys / 125 ft) and both under the SSM thresholds (15 / 200), so
    # classify_project returns exactly major_a. A test re-derives it.
    "project_class": "major_a",
    "suggested_class": "major_a",
    "building_stories": 12,
    "building_height": 140,
    "footprint_sqft": 18500,
    "has_full_demolition": False,
    "demolition_stories": None,
    "has_sub_cellar": False,
    "has_cellar": True,
    "has_mezzanine": False,
    "has_roof_bulkhead": True,
    "remembered_other_locations": ["Sidewalk shed", "Hoist run", "Cellar"],
    # Computed in shaping.py from the registry rather than typed here: a
    # hand-typed list would be a second model of the same rule, and two models
    # of one rule drift. This key exists because ProjectResponse declares it.
    "required_logbooks": [],
    "ssp_number": "DEMO-SSP-0001",
    "_ssp_filing_date_days_ago": 205,
    "_ssp_expiration_date_in_days": 160,
    "site_device_subfolders": ["Field Set"],
    "trade_assignments": [
        {"id": "demo-trade-01", "company": "Demo Concrete Corp", "trade": "Concrete"},
        {"id": "demo-trade-02", "company": "Demo Steel Erectors", "trade": "Structural Steel"},
        {"id": "demo-trade-03", "company": "Demo Interiors LLC", "trade": "Carpentry"},
    ],
    # NO COORDINATES. The check-in geofence is dead code on every real project,
    # and a demo project carrying a lat/lng would be the first one in the app to
    # imply otherwise. The radius keeps the model's default so the settings
    # screen renders a number rather than an empty control.
    "lat": None,
    "lng": None,
    "geofence_radius_m": 150,
    # `ProjectGate`'s fields — {gate_id, label, lat, lng} — and NOT {id, name}.
    # A gate row is what /checkin/{project_id}/{gate_id} is built from, so a row
    # keyed differently is a gate the check-in page cannot open. No coordinates,
    # for the same reason the project carries none.
    "gates": [{"gate_id": "demo-gate-01", "label": "Main gate",
               "lat": None, "lng": None},
              {"gate_id": "demo-gate-02", "label": "Hoist landing",
               "lat": None, "lng": None}],
    "job_completion_date": None,
    "job_completion_co_number": None,
    "completed_by": None,
    "completion_source": None,
    "no_completion_attested": False,
    "no_completion_reason": None,
    "no_completion_attested_by": None,
    "no_completion_attested_at": None,
    "legal_hold": False,
    "legal_hold_reason": None,
    "legal_hold_by": None,
    "legal_hold_at": None,
    "purge_eligible_at": None,
    # ── THE TOGGLES get_required_logbooks READS ────────────────────────────
    # A scaffold is up and a construction superintendent is assigned; there is
    # no crane, no open excavation, no hot-work permit and no declared work at
    # height. Those four False values keep four log tiles OFF the CP's screen,
    # which is as much a part of an honest demo as the nine that are on it.
    "scaffold_erected": True,
    "superintendent_log_active": True,
    "crane_on_site": False,
    "excavation_active": False,
    "hot_work_permitted": False,
    "fall_protection_active": False,
    # ── _DEMO_PROJECT's own keys, carried forward ──────────────────────────
    "is_demo": True,
    # THE COUNTS AND THE ROWS ARE ONE FACT SHOWN TWICE. DEMO_DOB_RECORDS below
    # holds exactly 5 permits, 2 violations, 1 complaint and 8 inspections, and
    # a test compares the two. Change one, change the other.
    "dob_summary": {"permits": 5, "violations": 2, "complaints": 1, "inspections": 8},
    "recent_activity": [
        {"type": "permit", "title": "New Building — ALT-1", "status": "ISSUED",
         "_date_days_ago": 124},
        {"type": "violation", "title": "Work without permit", "status": "RESOLVED",
         "_date_days_ago": 166},
        {"type": "inspection", "title": "Foundation — passed", "status": "PASSED",
         "_date_days_ago": 180},
    ],
    "special_inspections": [
        {"inspection_type": "firestopping", "status": "proposed"},
        {"inspection_type": "structural_steel", "status": "proposed"},
        {"inspection_type": "energy_nycecc", "status": "proposed"},
    ],
    "note": "This is a read-only demo. Contact us to activate full access.",
}


# ── THE CREW ────────────────────────────────────────────────────────────────
#
# Six workers, three subcontractors and one site-safety hire. Shaped for
# `WorkerResponse`, which GET /workers/{id} returns. The LIST endpoint projects
# a strict subset (WORKER_LIST_FIELDS) and shaping.py applies that projection
# rather than sending a list row the real app has never sent.
#
# ── THE CARD NUMBERS ARE SHAPED TO PASS, AND THAT IS A REQUIREMENT ─────────
#
# `card_number_finding` is evaluated at READ time and rendered in the register's
# Review column as "Unexpected card format". It fires on an SST row whose number
# is not ten [A-Z0-9] characters with at least one digit. A demo card that trips
# it puts a data-entry warning in front of a prospect on the screen we are
# selling, so every SST number here is exactly ten characters and carries digits.
#
# `class_source` is "color_and_text" on every SST card: two independent signals
# agreeing is the ONE state `_sst_cert_state` will call valid. Anything weaker
# resolves to "unknown", and a whole demo roster reading "unknown" is the product
# telling a prospect it cannot read cards.
#
# NO CARD IMAGES. `osha_card_image` is None on every worker. A base64 photograph
# is a real artefact of a real person; there is no such person here, and
# fabricating one would be fabricating an identity document.

#: The fifteen canonical orientation items, from LABEL_SETS["orientation_items"].
#: A worker's `safety_orientations` row stores the CHECKLIST HE WAS TAKEN
#: THROUGH — `register_and_checkin` writes {project_id, project_name, checklist,
#: completed_at} — so the same map backs both the worker document and the
#: orientation sheet. Two copies of one attendance would be two answers to
#: "was this man oriented".
_ORIENTATION_CHECKLIST = {
    "hard_hats": True, "safety_boots": True, "safety_glasses": True,
    "high_vis": True, "no_horseplay": True, "report_hazards": True,
    "fall_protection_required": True, "harness_inspection": True,
    "ladder_safety": True, "scaffold_rules": True, "emergency_exits": True,
    "first_aid": True, "emergency_contact": True, "incident_reporting": True,
    "no_drugs_alcohol": True,
}

DEMO_WORKERS = [
    {
        "id": "demo-worker-01",
        "name": "Luis Ferreira",
        "phone": "+12125550101",
        "trade": "Concrete",
        "company": "Demo Concrete Corp",
        "company_id": DEMO_COMPANY_ID,
        "status": "active",
        "osha_number": "DEMOOSHA01",
        "osha_data": {"card_class": "OSHA 30", "card_holder": "Luis Ferreira"},
        "osha_card_image": None,
        "safety_orientations": [
            {"project_id": DEMO_PROJECT_ID,
             "project_name": "Sample Project — 852 East 176th Street",
             "checklist": _ORIENTATION_CHECKLIST,
             "_completed_at_days_ago": 41},
        ],
        "certifications": [
            {"type": "SST_FULL", "card_number": "DEMOSST001",
             "_issue_date_days_ago": 400, "_expiration_date_in_days": 330,
             "verified": True, "class_source": "color_and_text"},
            {"type": "OSHA_30", "card_number": "DEMOOSHA01",
             "_issue_date_days_ago": 900, "verified": True},
        ],
        "signature": None,
        "_created_at_days_ago": 41,
    },
    {
        "id": "demo-worker-02",
        "name": "Andre Whitfield",
        "phone": "+12125550102",
        "trade": "Carpentry",
        "company": "Demo Interiors LLC",
        "company_id": DEMO_COMPANY_ID,
        "status": "active",
        "osha_number": "DEMOOSHA02",
        "osha_data": {"card_class": "OSHA 10", "card_holder": "Andre Whitfield"},
        "osha_card_image": None,
        "safety_orientations": [
            {"project_id": DEMO_PROJECT_ID,
             "project_name": "Sample Project — 852 East 176th Street",
             "checklist": _ORIENTATION_CHECKLIST,
             "_completed_at_days_ago": 38},
        ],
        "certifications": [
            # THE ONE THAT EXPIRES SOON, and it is the type most likely to. A
            # temporary SST card is the shortest-lived real NYC credential —
            # which is exactly why dropping it from an expiring count was once
            # the worst place to drop it — so it is the honest card to put on
            # the expiry surfaces.
            {"type": "SST_TEMPORARY", "card_number": "DEMOSST002",
             "_issue_date_days_ago": 160, "_expiration_date_in_days": 21,
             "verified": True, "class_source": "color_and_text"},
            {"type": "OSHA_10", "card_number": "DEMOOSHA02",
             "_issue_date_days_ago": 700, "verified": True},
        ],
        "signature": None,
        "_created_at_days_ago": 38,
    },
    {
        "id": "demo-worker-03",
        "name": "Kwame Boateng",
        "phone": "+12125550103",
        "trade": "Structural Steel",
        "company": "Demo Steel Erectors",
        "company_id": DEMO_COMPANY_ID,
        "status": "active",
        "osha_number": "DEMOOSHA03",
        "osha_data": {"card_class": "OSHA 30", "card_holder": "Kwame Boateng"},
        "osha_card_image": None,
        "safety_orientations": [
            {"project_id": DEMO_PROJECT_ID,
             "project_name": "Sample Project — 852 East 176th Street",
             "checklist": _ORIENTATION_CHECKLIST,
             "_completed_at_days_ago": 30},
        ],
        "certifications": [
            {"type": "SST_SUPERVISOR", "card_number": "DEMOSST003",
             "_issue_date_days_ago": 280, "_expiration_date_in_days": 450,
             "verified": True, "class_source": "color_and_text"},
            {"type": "OSHA_30", "card_number": "DEMOOSHA03",
             "_issue_date_days_ago": 1100, "verified": True},
        ],
        "signature": None,
        "_created_at_days_ago": 30,
    },
    {
        "id": "demo-worker-04",
        "name": "Ana Sotelo",
        "phone": "+12125550104",
        "trade": "Site Safety",
        "company": DEMO_COMPANY_NAME,
        "company_id": DEMO_COMPANY_ID,
        "status": "active",
        "osha_number": "DEMOOSHA04",
        "osha_data": {"card_class": "OSHA 30", "card_holder": "Ana Sotelo"},
        "osha_card_image": None,
        "safety_orientations": [
            {"project_id": DEMO_PROJECT_ID,
             "project_name": "Sample Project — 852 East 176th Street",
             "checklist": _ORIENTATION_CHECKLIST,
             "_completed_at_days_ago": 96},
        ],
        "certifications": [
            {"type": "SST_SUPERVISOR", "card_number": "DEMOSST004",
             "_issue_date_days_ago": 520, "_expiration_date_in_days": 210,
             "verified": True, "class_source": "color_and_text"},
            {"type": "OSHA_30", "card_number": "DEMOOSHA04",
             "_issue_date_days_ago": 1400, "verified": True},
        ],
        "signature": None,
        "_created_at_days_ago": 96,
    },
    {
        "id": "demo-worker-05",
        "name": "Piotr Nowak",
        "phone": "+12125550105",
        "trade": "Concrete",
        "company": "Demo Concrete Corp",
        "company_id": DEMO_COMPANY_ID,
        "status": "active",
        "osha_number": "DEMOOSHA05",
        "osha_data": {"card_class": "OSHA 30", "card_holder": "Piotr Nowak"},
        "osha_card_image": None,
        "safety_orientations": [
            {"project_id": DEMO_PROJECT_ID,
             "project_name": "Sample Project — 852 East 176th Street",
             "checklist": _ORIENTATION_CHECKLIST,
             "_completed_at_days_ago": 41},
        ],
        "certifications": [
            {"type": "SST_FULL", "card_number": "DEMOSST005",
             "_issue_date_days_ago": 210, "_expiration_date_in_days": 520,
             "verified": True, "class_source": "color_and_text"},
            {"type": "OSHA_30", "card_number": "DEMOOSHA05",
             "_issue_date_days_ago": 800, "verified": True},
        ],
        "signature": None,
        "_created_at_days_ago": 41,
    },
    {
        # The new man. His orientation sheet is the `subcontractor_orientation`
        # document three days back, and he is NOT among today's check-ins: a
        # roster where every name tapped in is a spreadsheet, not a site.
        "id": "demo-worker-06",
        "name": "Devon Clarke",
        "phone": "+12125550106",
        "trade": "Carpentry",
        "company": "Demo Interiors LLC",
        "company_id": DEMO_COMPANY_ID,
        "status": "active",
        "osha_number": "DEMOOSHA06",
        "osha_data": {"card_class": "OSHA 10", "card_holder": "Devon Clarke"},
        "osha_card_image": None,
        "safety_orientations": [
            {"project_id": DEMO_PROJECT_ID,
             "project_name": "Sample Project — 852 East 176th Street",
             "checklist": _ORIENTATION_CHECKLIST,
             "_completed_at_days_ago": 3},
        ],
        "certifications": [
            {"type": "SST_FULL", "card_number": "DEMOSST006",
             "_issue_date_days_ago": 95, "_expiration_date_in_days": 640,
             "verified": True, "class_source": "color_and_text"},
            {"type": "OSHA_10", "card_number": "DEMOOSHA06",
             "_issue_date_days_ago": 300, "verified": True},
        ],
        "signature": None,
        "_created_at_days_ago": 3,
    },
]

#: `validate_worker_certifications`'s shape, STATED rather than computed.
#:
#: IT IS NOT COMPUTED HERE ON PURPOSE. That function lives in server.py, and
#: server.py imports lib/ — importing it back would be a cycle — and it reads
#: `datetime.now(timezone.utc)` to age the cards, which would put a clock inside
#: a module whose whole claim is that it has none. The roster above is built to
#: clear with no warnings, so the constant and the function agree by
#: construction. If a card here is ever made deliberately expired, this stops
#: being true and the validation has to be stated per worker instead.
DEMO_CERT_VALIDATION = {
    "cleared": True,
    "blocks": [],
    "warnings": [],
    "sst_state": "valid",
}


# ── THE DAY AT THE GATE ─────────────────────────────────────────────────────
#
# One day's check-ins against the crew above, shaped for `CheckInResponse`.
# GET /checkins wraps them in the standard pagination envelope;
# GET /checkins/project/{id} returns a bare list with `worker_trade` joined from
# the project's trade assignments rather than from the worker document — one
# man holds different trades on different jobs, and an admin list showing
# another site's trade is invisibly wrong.
#
# FIVE OF SIX, AND ONE STILL ON SITE. Ana Sotelo has not tapped out, so the
# "currently on site" tile has a non-zero number to show.
DEMO_CHECKINS = [
    {"id": "demo-checkin-01", "worker_id": "demo-worker-01",
     "_in": (6, 42), "_out": (15, 8)},
    {"id": "demo-checkin-02", "worker_id": "demo-worker-05",
     "_in": (6, 44), "_out": (15, 6)},
    {"id": "demo-checkin-03", "worker_id": "demo-worker-03",
     "_in": (6, 51), "_out": (15, 12)},
    {"id": "demo-checkin-04", "worker_id": "demo-worker-02",
     "_in": (7, 3), "_out": (14, 55)},
    {"id": "demo-checkin-05", "worker_id": "demo-worker-04",
     "_in": (6, 30), "_out": None},
]


# ── THE LOGBOOKS ────────────────────────────────────────────────────────────
#
# THE PLAN IS A TABLE, NOT FORTY HAND-WRITTEN DOCUMENTS. Each row is
# (log_type, day offset, status) and shaping.py expands it. Written this way
# because the invariant a reader needs to check — "is every required daily log
# filed on every day the demo presents as closed" — is legible in a table and
# invisible in forty dicts.
#
# ── WHY THESE TYPES ────────────────────────────────────────────────────────
#
# Exactly `get_required_logbooks("major_a", DEMO_PROJECT)`, which resolves to
# nine: five that apply to every class with no toggle (daily_jobsite,
# preshift_signin, toolbox_talk, subcontractor_orientation, osha_log), two that
# major_a itself demands (ssc_daily_safety_log, concrete_operations — the
# Concrete Safety Manager's instrument), and two the project's own toggles
# switch on (scaffold_maintenance from `scaffold_erected`,
# site_superintendent_log from `superintendent_log_active`). A required type
# with no document is a red tile on the CP's home screen, so all nine appear.
#
# ── AND WHY NOT EVERY TYPE EVERY DAY ───────────────────────────────────────
#
# `toolbox_talk` is WEEKLY and appears once. Filing it five times a week is the
# 588 Thomas defect — 33 talks in 35 working days, because a by-date tile said
# "pending" every morning — and a demo that stages a defect teaches it.
# `subcontractor_orientation` is as-needed and appears once, for the one worker
# who started this week; it is one sheet PER WORKER, not per day.
#: The day-offset marker meaning "the Monday of the work week containing
#: `today`". Used by the weekly log — see the plan below.
WEEK_START = "week_start"

_DAILY_TYPES = (
    "daily_jobsite",
    "preshift_signin",
    "site_superintendent_log",
    "osha_log",
    "scaffold_maintenance",
    "ssc_daily_safety_log",
    "concrete_operations",
)

# ── THE REQUIRED SET, AND WHY IT IS A LITERAL ──────────────────────────────
#
# `get_required_logbooks` lives in server.py, and server.py imports lib/ —
# importing it back would be a cycle, and this module's whole claim is that it
# imports nothing that does I/O. Re-implementing the rule here would be worse
# still: two models of one rule, which is the exact defect
# get_required_logbooks was written to end (the registry said one thing, the
# function implemented another, and the crane log was unreachable on every
# project this app has ever had for as long as they disagreed).
#
# So the answer is STATED, and the suite RECONCILES it: a test asserts this
# tuple equals `server.get_required_logbooks(DEMO_PROJECT["project_class"],
# DEMO_PROJECT)`. Change the registry and the test names this constant. That is
# the reconciliation point, and it is a test rather than a comment because a
# comment cannot fail.
#
# Registry order, which is the display order the CP's list renders in.
DEMO_REQUIRED_LOGBOOKS = (
    "daily_jobsite",
    "preshift_signin",
    "site_superintendent_log",
    "toolbox_talk",
    "subcontractor_orientation",
    "osha_log",
    "scaffold_maintenance",
    "ssc_daily_safety_log",
    "concrete_operations",
)

#: `logbook_activations(DEMO_PROJECT)`'s answer — one row per registry type that
#: carries a toggle, with this project's state of it. Stated and reconciled by a
#: test for the same reason as the set above. The four False rows are the four
#: tiles the demo does NOT show, and they are why the screen can explain itself.
#:
#: HOT WORK HAS TWO ROWS, because it carries two facts: the admin's standing
#: permit statement and the CP's dated "hot work is happening today". The demo
#: project has neither — `hot_work_permitted` is False above — so the day row
#: is off AND unavailable, which is the state the screen explains with "an
#: admin switches this one on". The demo does not declare a hot-work day: the
#: dated row would then need a `hot_work_days` fiction and a period row to
#: match it, and a demo that shows a hot-work tile on a site with no permit
#: would be demonstrating the defect this pair was built to remove.
DEMO_ACTIVATIONS = [
    {"log_type": "site_superintendent_log",
     "label": "Construction Superintendent Log",
     "field": "superintendent_log_active", "active": True,
     "activated_by": "admin", "scope": "standing"},
    {"log_type": "scaffold_maintenance", "label": "Scaffold Maintenance Log",
     "field": "scaffold_erected", "active": True, "activated_by": "cp",
     "scope": "standing"},
    {"log_type": "hot_work", "label": "Hot Work Permit Log",
     "field": "hot_work_permitted", "active": False, "activated_by": "admin",
     "scope": "standing"},
    {"log_type": "hot_work", "label": "Hot Work Permit Log — today",
     "field": "hot_work_days", "active": False, "activated_by": "cp",
     "scope": "day", "available": False},
    {"log_type": "crane_operations", "label": "Crane Operations Log",
     "field": "crane_on_site", "active": False, "activated_by": "cp",
     "scope": "standing"},
    {"log_type": "excavation_monitoring", "label": "Excavation Monitoring Log",
     "field": "excavation_active", "active": False, "activated_by": "cp",
     "scope": "standing"},
    {"log_type": "fall_protection", "label": "Fall Protection Equipment Log",
     "field": "fall_protection_active", "active": False, "activated_by": "cp",
     "scope": "standing"},
]

#: `_logbook_filing_rights`'s rows: who may file the one log whose filing is
#: restricted to a named person. BC 3301.13.13 is the construction
#: superintendent's OWN record, and the project has registered one.
#:
#: `may_file` is True: the demo principal is looking at his own demo company and
#: nothing here should refuse him. A False would hide the tile behind
#: `_visible_required_logbooks` and the demo would be a log short of the class
#: it claims — the required set above assumes nothing is withheld.
DEMO_FILING_RIGHTS = [
    {"log_type": "site_superintendent_log", "may_file": True,
     "registered_name": "Marcus Hale", "reason": None},
]

#: (log_type, day_offset, status). `is_locked` is deliberately NOT in this
#: table: it is derived in shaping.py exactly as create_logbook derives it —
#: submitted AND immediate-class — because a demo row that locks an end-of-day
#: log shows a CP a document he could not have edited that afternoon.
DEMO_LOGBOOK_PLAN = (
    [(t, off, "submitted") for off in DEMO_CLOSED_DAY_OFFSETS for t in _DAILY_TYPES]
    + [
        # Today, in progress. The two END_OF_DAY narratives and the visit log
        # stay open — that is what those classes mean — while the immediate
        # ones are already signed and frozen, which is what immediate means.
        # These seven rows are the whole freeze model, visible on one screen.
        ("preshift_signin", DEMO_OPEN_DAY_OFFSET, "submitted"),
        ("osha_log", DEMO_OPEN_DAY_OFFSET, "submitted"),
        ("scaffold_maintenance", DEMO_OPEN_DAY_OFFSET, "submitted"),
        ("concrete_operations", DEMO_OPEN_DAY_OFFSET, "submitted"),
        ("daily_jobsite", DEMO_OPEN_DAY_OFFSET, "draft"),
        ("ssc_daily_safety_log", DEMO_OPEN_DAY_OFFSET, "draft"),
        ("site_superintendent_log", DEMO_OPEN_DAY_OFFSET, "draft"),
        # Weekly, given once — ON THE MONDAY OF THE VIEWER'S OWN WEEK, which is
        # why this row carries a marker instead of an offset. A fixed offset
        # would drift out of the Mon–Fri week that `toolbox_period` measures
        # against, so on some weekdays the demo would open with the weekly tile
        # reading "not filed" — the 588 Thomas red morning, staged for a
        # prospect. WEEK_START resolves to that Monday whatever day it is read.
        ("toolbox_talk", WEEK_START, "submitted"),
        # As-needed: Devon Clarke's first day.
        ("subcontractor_orientation", -3, "submitted"),
    ]
)

# ── THE CONTENTS OF EACH SHEET ──────────────────────────────────────────────
#
# One `data` payload per type, copied onto every document of that type.
#
# THE KEYS ARE THE EDITORS' KEYS AND THE RENDERER'S KEYS, taken from the nine
# editors under frontend/app/logbooks/ and their model modules, and from
# lib/legal_render/schema.py, which is what actually prints the filed document.
# Getting them nearly right is worse than leaving them out: a section whose key
# is missing VANISHES from the sheet, and a row missing its `row_requires` field
# is DROPPED from the table — silently, on a document a prospect is reading.
#
# The per-type notes below record the traps, because the next person to edit
# this data will not have read those nine files.
DEMO_LOGBOOK_DATA = {
    # Renderer: schema.py §daily_jobsite. `checklist_items` must be present or
    # section 6 omits entirely; `other_checklist.result` stays None by design
    # (it is the note-only item). `time_in`/`time_out` are read by the renderer
    # and NEVER written by the editor, so they are absent here too — copying the
    # real document means copying its gaps. No photos: a photo row carries an R2
    # key, and there is no object store behind a demo.
    "daily_jobsite": {
        "project_address": "852 East 176th Street, Bronx, NY 10460",
        "weather": "Clear",
        "weather_temp": "68°F",
        "weather_wind": "8 mph NW",
        "weather_fetch_state": "ok",
        "general_description": (
            "Third-floor deck pour completed in the morning. Steel erection "
            "continued on the east bay. Sidewalk shed and scaffold inspected at "
            "the start of the shift; no defects noted."
        ),
        "activities": [
            {"activity_id": "demo-activity-01", "subcontractor_id": "demo-trade-01",
             "crew_id": "Crew A", "company": "Demo Concrete Corp",
             "num_workers": "2", "work_description": "Placed and finished 40 cy on the north bay.",
             "work_locations": "Level 3 deck", "photos": [], "trade": "concrete",
             "gate_sourced": True, "check_in_time": None, "worker_ids": [],
             "activity_ids": [], "location_ids": [], "company_gate": None},
            {"activity_id": "demo-activity-02", "subcontractor_id": "demo-trade-02",
             "crew_id": "Crew B", "company": "Demo Steel Erectors",
             "num_workers": "1", "work_description": "Set and plumbed columns at lines 4–6.",
             "work_locations": "East bay", "photos": [], "trade": "structural steel",
             "gate_sourced": True, "check_in_time": None, "worker_ids": [],
             "activity_ids": [], "location_ids": [], "company_gate": None},
            {"activity_id": "demo-activity-03", "subcontractor_id": "demo-trade-03",
             "crew_id": "Crew C", "company": "Demo Interiors LLC",
             "num_workers": "1", "work_description": "Layout for partition track.",
             "work_locations": "Level 2", "photos": [], "trade": "carpentry",
             "gate_sourced": True, "check_in_time": None, "worker_ids": [],
             "activity_ids": [], "location_ids": [], "company_gate": None},
        ],
        "equipment_on_site": {"elevator": False, "compressor": True, "pump": True,
                              "hoist": True, "boom_crane": False,
                              "other_equipment": False},
        "checklist_items": {
            "street_frontage": {"result": "pass", "note": ""},
            "fire_safety": {"result": "pass", "note": ""},
            "perimeter_fence": {"result": "pass", "note": ""},
            "fall_protections": {"result": "pass", "note": ""},
            "neighbors_property": {"result": "pass", "note": ""},
            "license_spot_check": {"result": "pass", "note": ""},
            "plans": {"result": "pass", "note": ""},
            "permits": {"result": "pass", "note": ""},
            "other_checklist": {"result": None,
                                "note": "Hoist landing gates checked before the second lift."},
        },
        "observations": [
            {"description": "Housekeeping at the hoist landing.",
             "responsible_party": "Demo Interiors LLC",
             "remedy": "Cleared before the second lift.",
             "corrected_immediately": True},
        ],
        "visitors_deliveries": "Ready-mix deliveries 07:40 and 09:55. No agency visits.",
    },
    # Renderer: schema.py §preshift_signin. `row_requires: ["name"]` — a roster
    # row with no name is dropped from the filed sheet without a word.
    # had_injury / inspected_ppe are the LOWERCASE STRINGS 'yes' / 'no', not
    # booleans: the `answer` formatter prints them verbatim and a True would
    # print as nothing.
    #
    # NO FABRICATED SIGNATURE STROKES. `worker_signature` is None and `signin_id`
    # carries the gate affirmation instead, which is the renderer's documented
    # fallback. A demo may invent a worker; it should not invent the mark he
    # made with his own hand.
    "preshift_signin": {
        "company": DEMO_COMPANY_NAME,
        "project_location": "852 East 176th Street, Bronx, NY 10460",
        "total_count": 5,
        "workers": [
            {"worker_id": "demo-worker-01", "name": "Luis Ferreira",
             "company": "Demo Concrete Corp", "osha_number": "DEMOOSHA01",
             "worker_signature": None, "had_injury": "no", "inspected_ppe": "yes",
             "signed": True, "auto_filled": True, "signin_id": "demo-signin-01"},
            {"worker_id": "demo-worker-05", "name": "Piotr Nowak",
             "company": "Demo Concrete Corp", "osha_number": "DEMOOSHA05",
             "worker_signature": None, "had_injury": "no", "inspected_ppe": "yes",
             "signed": True, "auto_filled": True, "signin_id": "demo-signin-02"},
            {"worker_id": "demo-worker-03", "name": "Kwame Boateng",
             "company": "Demo Steel Erectors", "osha_number": "DEMOOSHA03",
             "worker_signature": None, "had_injury": "no", "inspected_ppe": "yes",
             "signed": True, "auto_filled": True, "signin_id": "demo-signin-03"},
            {"worker_id": "demo-worker-02", "name": "Andre Whitfield",
             "company": "Demo Interiors LLC", "osha_number": "DEMOOSHA02",
             "worker_signature": None, "had_injury": "no", "inspected_ppe": "yes",
             "signed": True, "auto_filled": True, "signin_id": "demo-signin-04"},
            {"worker_id": "demo-worker-04", "name": "Ana Sotelo",
             "company": DEMO_COMPANY_NAME, "osha_number": "DEMOOSHA04",
             "worker_signature": None, "had_injury": "no", "inspected_ppe": "yes",
             "signed": True, "auto_filled": True, "signin_id": "demo-signin-05"},
        ],
    },
    # Renderer: schema.py §site_superintendent_log. Only the four `presence.*`
    # keys are read off `data` directly; section 3 is a REGISTER built
    # server-side from lib/logbook/superintendent_log.py's ITEMS vocabulary, so
    # the sub-dicts below must use that vocabulary's own field names or the
    # register reads them as NOT_REACHED. `corrected` is one of
    # 'corrected' | 'not_corrected' | 'not_yet' | None.
    "site_superintendent_log": {
        "presence": {"printed_name": "Marcus Hale", "arrived_at": "06:30",
                     "departed_at": "15:30", "departed_next_day": False,
                     "signature": None},
        "progress": {"summary": "Level 3 deck poured and finished; steel set at lines 4–6.",
                     "source": "own"},
        "cs_activities": {"summary": "Walked levels 1–3 and the perimeter; checked shoring "
                                     "before the pour and the shed after it."},
        "unsafe_conditions": {"entries": [
            {"location": "Level 3 east", "observed_at": "09:15",
             "condition": "Guardrail gap at the deck edge.", "corrected": "corrected"},
        ]},
        "orders_given": {"entries": [
            {"location": "Level 3 east", "observed_at": "09:15",
             "order": "Reinstall the rail before placement continues.",
             "given_to": "Demo Steel Erectors foreman",
             "condition": "Guardrail gap at the deck edge.", "corrected": "corrected"},
        ]},
        "dob_actions": {"none_to_report": True},
        "incidents": {"none_to_report": True},
        "competent_person": {"name": "Ana Sotelo"},
        "daily_inspection": {"location": "All floors, scaffold and perimeter"},
    },
    # Renderer: schema.py §toolbox_talk. `row_requires: ["name"]`. `signed` and
    # `gate_confirmed` are stored and deliberately not printed; `type_of_work` is
    # written by the editor and read by nothing, and is kept so the demo
    # document matches a real one rather than a tidied one. `checked_topics`
    # prints only its truthy keys — an empty map prints "none documented".
    "toolbox_talk": {
        "location": "Gate trailer — East 176th",
        "company_name": DEMO_COMPANY_NAME,
        "type_of_work": "Concrete and structural steel",
        "meeting_time": "07:05",
        "performed_by": DEMO_CP_NAME,
        "checked_topics": {"hard_hats": True, "safety_glasses": True,
                           "ladder_safety": True, "egress": True},
        "attendees": [
            {"worker_id": "demo-worker-01", "name": "Luis Ferreira",
             "title": "Foreman", "company": "Demo Concrete Corp", "time": "07:05",
             "gate_confirmed": True, "gate_confirmed_at": None, "signed": True,
             "signature": None, "added_from": "gate"},
            {"worker_id": "demo-worker-05", "name": "Piotr Nowak",
             "title": "Operator", "company": "Demo Concrete Corp", "time": "07:05",
             "gate_confirmed": True, "gate_confirmed_at": None, "signed": True,
             "signature": None, "added_from": "gate"},
            {"worker_id": "demo-worker-03", "name": "Kwame Boateng",
             "title": "Ironworker", "company": "Demo Steel Erectors", "time": "07:06",
             "gate_confirmed": True, "gate_confirmed_at": None, "signed": True,
             "signature": None, "added_from": "gate"},
            {"worker_id": "demo-worker-02", "name": "Andre Whitfield",
             "title": "Carpenter", "company": "Demo Interiors LLC", "time": "07:07",
             "gate_confirmed": True, "gate_confirmed_at": None, "signed": True,
             "signature": None, "added_from": "gate"},
            # EVERY MAN WHO TAPPED IN IS ON THIS LIST, and that is not tidiness.
            # `toolbox_period` reports WEEKEND_UNCOVERED for anyone who checked
            # in on the Saturday or Sunday of the week and is not named as an
            # attendee — so if the demo is opened at a weekend, a worker missing
            # from here turns the weekly tile red for a reason the prospect
            # cannot see.
            {"worker_id": "demo-worker-04", "name": "Ana Sotelo",
             "title": "Site Safety Coordinator", "company": DEMO_COMPANY_NAME,
             "time": "07:05", "gate_confirmed": True, "gate_confirmed_at": None,
             "signed": True, "signature": None, "added_from": "gate"},
        ],
    },
    # Renderer: schema.py §subcontractor_orientation. ONE SHEET PER WORKER — this
    # one is Devon Clarke's first day. The checklist keys are the canonical
    # fifteen from LABEL_SETS["orientation_items"]; a key outside that set prints
    # nothing at all. `worker_signature` is None for the same reason as the
    # pre-shift sheet, and section 5 discloses rather than invents.
    "subcontractor_orientation": {
        "worker_id": "demo-worker-06",
        "worker_name": "Devon Clarke",
        "worker_company": "Demo Interiors LLC",
        "worker_trade": "Carpentry",
        "osha_number": "DEMOOSHA06",
        "orientation_number": "DEMO-ORI-0001",
        # The SAME map the worker document's own orientation row carries — see
        # _ORIENTATION_CHECKLIST. The sheet and the roster are one event.
        "checklist": _ORIENTATION_CHECKLIST,
        "_completed_at_days_ago": 3,
        "worker_signature": None,
        "language_provided": "en",
    },
    # Renderer: schema.py §osha_log. `row_requires: ["worker_name"]` — a row with
    # a card number and no name is dropped. `certification_type` is the LABEL
    # STRING the register stores ("SST Supervisor"), not the stored class enum;
    # `oshaLogModel.certLabel` resolves the class to a word before the row is
    # filed, and a filed register is never rewritten.
    #
    # The card numbers are the SAME ones on the worker documents. A register
    # that disagrees with the roster is precisely the contradiction this
    # dataset's tests exist to prevent.
    "osha_log": {
        "entries": [
            {"worker_id": "demo-worker-01", "worker_name": "Luis Ferreira",
             "company": "Demo Concrete Corp", "certification_type": "SST Full",
             "card_number": "DEMOSST001", "_expiration_in_days": 330,
             "signed": True, "unverified": False},
            {"worker_id": "demo-worker-05", "worker_name": "Piotr Nowak",
             "company": "Demo Concrete Corp", "certification_type": "SST Full",
             "card_number": "DEMOSST005", "_expiration_in_days": 520,
             "signed": True, "unverified": False},
            {"worker_id": "demo-worker-03", "worker_name": "Kwame Boateng",
             "company": "Demo Steel Erectors", "certification_type": "SST Supervisor",
             "card_number": "DEMOSST003", "_expiration_in_days": 450,
             "signed": True, "unverified": False},
            {"worker_id": "demo-worker-02", "worker_name": "Andre Whitfield",
             "company": "Demo Interiors LLC", "certification_type": "SST Temporary",
             "card_number": "DEMOSST002", "_expiration_in_days": 21,
             "signed": True, "unverified": False},
            {"worker_id": "demo-worker-04", "worker_name": "Ana Sotelo",
             "company": DEMO_COMPANY_NAME, "certification_type": "SST Supervisor",
             "card_number": "DEMOSST004", "_expiration_in_days": 210,
             "signed": True, "unverified": False},
        ],
    },
    # Renderer: schema.py §scaffold_maintenance. `requires: ["data.answers"]` —
    # NO answers map, NO checklist section at all. The values are the strings
    # 'YES' | 'NO' | 'N/A' and never booleans: a boolean here prints every failed
    # check as a pass, which is a compliance document asserting the opposite of
    # what was found.
    "scaffold_maintenance": {
        "general_info": {
            "scaffold_erector": "Demo Scaffold Co",
            "renters_name": DEMO_COMPANY_NAME,
            "permit_number": "DEMO-SF-0001",
            "_installation_date_days_ago": 58,
            "_expiration_date_in_days": 96,
            "phone": DEMO_SITE_PHONE,
            "scaffold_height": "24 ft",
            "num_platforms": "2",
            "shed_type": "Heavy",
        },
        "answers": {
            "signs_on_parapets": "YES", "base_plates_mudsills": "YES",
            "scaffold_pins_bolts": "YES", "legs_poles_plumb": "YES",
            "tie_ins_spaced": "YES", "cross_braces": "YES",
            "pipe_clamps_tight": "YES", "window_jacks_tight": "N/A",
            "planks_secured": "YES", "decking_planks_condition": "YES",
            "deck_fully_planked": "YES", "gaps_open_spaces": "NO",
            "guardrails_toe_boards": "YES", "netting_extension": "YES",
            "netting_secured": "YES", "parapet_height": "YES",
            "lights_working": "YES", "deck_clean": "YES",
            "drawings_on_site": "YES",
        },
    },
    # Renderer: schema.py §ssc_daily_safety_log. Thirteen flat keys, all always
    # present. The site block and the five compliance flags use
    # `requires_present`, so a recorded 0 or a recorded False still prints —
    # which is why every one of them is written explicitly here rather than
    # omitted when the answer is "nothing to report".
    "ssc_daily_safety_log": {
        "project_address": "852 East 176th Street, Bronx, NY 10460",
        "ssp_number": "DEMO-SSP-0001",
        "weather": "Clear 68°F",
        "workers_on_site_count": "5",
        "incidents_reported": False,
        "safety_meetings_held": True,
        "fire_protection_in_place": True,
        "housekeeping_satisfactory": True,
        "ppe_compliance": True,
        "site_conditions": "Dry. Wind light. Deck and shed clear.",
        "safety_violations_observed": "None observed.",
        "corrective_actions_taken": "Guardrail gap at Level 3 east closed on the spot.",
        "incident_details": "",
    },
    # Renderer: schema.py §concrete_operations. Slump rows carry
    # `row_requires: ["time","value"]` plus `row_requires_present: ["pass"]`, and
    # `pass` is TRI-STATE — None means "not recorded" and is not a failure. The
    # `pass_fail` formatter prints "Fail", never "No".
    "concrete_operations": {
        "pour_location": "Level 3 deck — north bay",
        "concrete_supplier": "Demo Ready Mix Co",
        "mix_design": "4000 psi / 3/4 agg",
        "volume_ordered": "40",
        "weather_conditions": "Clear",
        "temperature": "68",
        "slump_tests": [
            {"time": "08:10", "value": "4.5", "pass": True},
            {"time": "10:20", "value": "4.0", "pass": True},
        ],
        "formwork_checklist": {"shores_plumb": True, "bracing_adequate": True,
                               "formwork_clean": True, "no_gaps": True},
    },
}


# ── THE DOB RECORD ──────────────────────────────────────────────────────────
#
# Sixteen records: 5 permits, 2 violations, 1 complaint, 8 inspections —
# exactly the counts `DEMO_PROJECT["dob_summary"]` prints on the tile, because
# the tile and this list are one fact shown on two screens and a prospect taps
# straight from one to the other.
#
# EVERY raw_dob_id IS UNIQUE, and that is load-bearing rather than incidental.
# The real summary pipeline DEDUPES by raw_dob_id — a status change INSERTS a
# row, so counting rows overcounts — and keeps the latest per id. With one id
# per record, "rows" and "deduped records" are the same number, which is what
# lets the counts above be compared to the list at all. A future record staging
# a status TRANSITION would need two rows under one id, and would then have to
# leave the counts alone.
#
# Shaped for `DOBLogResponse`. Every date is an offset, so a permit that must
# read as ACTIVE stays active however long this demo runs — the real summary
# counts a permit as active only while its expiry is in the future, and a demo
# whose permits quietly expire on the shelf reports its own site as lapsed.
DEMO_DOB_RECORDS = [
    # ── PERMITS (5) ────────────────────────────────────────────────────────
    # One expires inside thirty days, so the "expiring" tile has something to
    # show; the other four are comfortably live. None is REVOKED and none lacks
    # an expiry, so all five count toward the active denominator.
    {"id": "demo-dob-permit-01", "record_type": "permit",
     "raw_dob_id": "DEMO-PERMIT-0001", "signal_kind": "permit_issued",
     "permit_type": "NB", "permit_subtype": "OT", "permit_status": "ISSUED",
     "job_number": "DEMO000001", "job_type": "NB",
     "work_type": "General Construction", "filing_system": "DOB NOW",
     "permit_class": "Major", "description": "New Building — general construction",
     "_issuance_date_days_ago": 124, "_filing_date_days_ago": 160,
     "_expiration_date_in_days": 18, "_detected_at_days_ago": 124,
     "severity": "Medium"},
    {"id": "demo-dob-permit-02", "record_type": "permit",
     "raw_dob_id": "DEMO-PERMIT-0002", "signal_kind": "permit_issued",
     "permit_type": "EQ", "permit_subtype": "CH", "permit_status": "ISSUED",
     "job_number": "DEMO000002", "job_type": "EQ",
     "work_type": "Construction Hoist", "filing_system": "DOB NOW",
     "permit_class": "Major", "description": "Construction hoist — install and use",
     "_issuance_date_days_ago": 96, "_filing_date_days_ago": 130,
     "_expiration_date_in_days": 140, "_detected_at_days_ago": 96,
     "severity": "Low"},
    {"id": "demo-dob-permit-03", "record_type": "permit",
     "raw_dob_id": "DEMO-PERMIT-0003", "signal_kind": "permit_issued",
     "permit_type": "PL", "permit_subtype": "OT", "permit_status": "ISSUED",
     "job_number": "DEMO000003", "job_type": "A2", "work_type": "Plumbing",
     "filing_system": "DOB NOW", "permit_class": "Standard",
     "description": "Plumbing — rough and finish",
     "_issuance_date_days_ago": 74, "_filing_date_days_ago": 110,
     "_expiration_date_in_days": 210, "_detected_at_days_ago": 74,
     "severity": "Low"},
    {"id": "demo-dob-permit-04", "record_type": "permit",
     "raw_dob_id": "DEMO-PERMIT-0004", "signal_kind": "permit_issued",
     "permit_type": "SF", "permit_subtype": "OT", "permit_status": "ISSUED",
     "job_number": "DEMO000004", "job_type": "A2",
     "work_type": "Supported Scaffold", "filing_system": "DOB NOW",
     "permit_class": "Standard",
     "description": "Supported scaffold — north and east elevations",
     "_issuance_date_days_ago": 58, "_filing_date_days_ago": 90,
     "_expiration_date_in_days": 96, "_detected_at_days_ago": 58,
     "severity": "Low"},
    {"id": "demo-dob-permit-05", "record_type": "permit",
     "raw_dob_id": "DEMO-PERMIT-0005", "signal_kind": "permit_issued",
     "permit_type": "SH", "permit_subtype": "OT", "permit_status": "ISSUED",
     "job_number": "DEMO000005", "job_type": "A2", "work_type": "Sidewalk Shed",
     "filing_system": "DOB NOW", "permit_class": "Standard",
     "description": "Sidewalk shed — East 176th Street frontage",
     "_issuance_date_days_ago": 150, "_filing_date_days_ago": 180,
     "_expiration_date_in_days": 300, "_detected_at_days_ago": 150,
     "severity": "Low"},
    # ── VIOLATIONS (2) — one closed, one open ──────────────────────────────
    #
    # The closed one is `recent_activity`'s "Work without permit — RESOLVED",
    # which the seed already shows on the project card. The open one is what
    # gives the compliance screen a live row: a demo where nothing is
    # outstanding shows none of the work this product exists to do.
    #
    # `resolution_state` is written explicitly rather than inferred. The real
    # value is derived at ingestion by `_classify_resolution_state` from DOB's
    # own status words, and the summary pipeline counts a violation as OPEN
    # when it is not one of {certified, dismissed, paid, resolved}. The
    # `violation_category` strings below are the ones BIS actually writes —
    # note "RESOLVE" has no trailing D — so the stated state and the words it
    # would have been derived from agree.
    {"id": "demo-dob-violation-01", "record_type": "violation",
     "raw_dob_id": "DEMO-VIOL-0001", "signal_kind": "violation_resolved",
     "violation_type": "WORK WITHOUT PERMIT", "violation_number": "DEMOV00001",
     "violation_category": "V-DOB VIOLATION - RESOLVE",
     "resolution_state": "resolved", "current_status": "RESOLVE",
     "penalty_amount": "0", "respondent": DEMO_COMPANY_NAME,
     "description": "Work without permit — resolved on re-inspection",
     "_violation_date_days_ago": 166, "_disposition_date_days_ago": 150,
     "disposition_comments": "Corrected and certified.",
     "_detected_at_days_ago": 166, "severity": "Medium"},
    {"id": "demo-dob-violation-02", "record_type": "violation",
     "raw_dob_id": "DEMO-VIOL-0002", "signal_kind": "violation_dob",
     "violation_type": "FAILURE TO MAINTAIN", "violation_number": "DEMOV00002",
     "violation_category": "V-DOB VIOLATION - ACTIVE",
     "resolution_state": "open", "current_status": "ACTIVE",
     "penalty_amount": "1250", "respondent": DEMO_COMPANY_NAME,
     "description": "Sidewalk shed lighting not maintained",
     "_violation_date_days_ago": 22, "_compliance_deadline_in_days": 14,
     "_detected_at_days_ago": 22, "severity": "Critical"},
    # ── COMPLAINT (1) — closed ─────────────────────────────────────────────
    # Closed, with both a closed_date and a status matching /closed/i, which is
    # the pair the summary's open-complaint facet tests. One of them alone would
    # leave the two screens disagreeing about whether it is open.
    {"id": "demo-dob-complaint-01", "record_type": "complaint",
     "raw_dob_id": "DEMO-CMPL-0001", "signal_kind": "complaint_311",
     "complaint_number": "DEMOC00001", "complaint_type": "05",
     "complaint_status": "CLOSED", "category_label": "After-hours work",
     "disposition_code": "A1", "disposition_label": "Resolved — no violation",
     "complaint_source": "311", "inspector_unit": "Construction",
     "incident_address": "852 East 176th Street, Bronx, NY 10460",
     "description": "After-hours work reported; no work found on inspection",
     "_complaint_date_days_ago": 88, "_closed_date_days_ago": 81,
     "_detected_at_days_ago": 88, "severity": "Low"},
    # ── INSPECTIONS (8) ────────────────────────────────────────────────────
    # Seven passes and one failure followed by its re-inspection. An
    # all-green inspection history is the least believable thing a
    # construction record can show, and the pair also demonstrates the
    # follow-up the activity feed is for.
    {"id": "demo-dob-inspection-01", "record_type": "inspection",
     "raw_dob_id": "DEMO-INSP-0001", "signal_kind": "inspection_passed",
     "inspection_type": "Foundation", "inspection_result": "PASSED",
     "inspection_result_description": "Footing reinforcement approved",
     "linked_job_number": "DEMO000001", "_inspection_date_days_ago": 180,
     "_detected_at_days_ago": 180, "severity": "Low"},
    {"id": "demo-dob-inspection-02", "record_type": "inspection",
     "raw_dob_id": "DEMO-INSP-0002", "signal_kind": "inspection_passed",
     "inspection_type": "Sidewalk Shed", "inspection_result": "PASSED",
     "inspection_result_description": "Shed erected per approved drawings",
     "linked_job_number": "DEMO000005", "_inspection_date_days_ago": 146,
     "_detected_at_days_ago": 146, "severity": "Low"},
    {"id": "demo-dob-inspection-03", "record_type": "inspection",
     "raw_dob_id": "DEMO-INSP-0003", "signal_kind": "inspection_passed",
     "inspection_type": "Construction Hoist", "inspection_result": "PASSED",
     "inspection_result_description": "Hoist commissioned and load tested",
     "linked_job_number": "DEMO000002", "_inspection_date_days_ago": 94,
     "_detected_at_days_ago": 94, "severity": "Low"},
    {"id": "demo-dob-inspection-04", "record_type": "inspection",
     "raw_dob_id": "DEMO-INSP-0004", "signal_kind": "inspection_passed",
     "inspection_type": "Scaffold", "inspection_result": "PASSED",
     "inspection_result_description": "Supported scaffold inspected — compliant",
     "linked_job_number": "DEMO000004", "_inspection_date_days_ago": 57,
     "_detected_at_days_ago": 57, "severity": "Low"},
    {"id": "demo-dob-inspection-05", "record_type": "inspection",
     "raw_dob_id": "DEMO-INSP-0005", "signal_kind": "inspection_passed",
     "inspection_type": "Structural Stability", "inspection_result": "PASSED",
     "inspection_result_description": "Levels 1–3 framing reviewed",
     "linked_job_number": "DEMO000001", "_inspection_date_days_ago": 44,
     "_detected_at_days_ago": 44, "severity": "Low"},
    {"id": "demo-dob-inspection-06", "record_type": "inspection",
     "raw_dob_id": "DEMO-INSP-0006", "signal_kind": "inspection_failed",
     "inspection_type": "Plumbing Rough", "inspection_result": "FAILED",
     "inspection_result_description": "Re-inspection required — hanger spacing",
     "linked_job_number": "DEMO000003", "_inspection_date_days_ago": 31,
     "_detected_at_days_ago": 31, "severity": "Medium"},
    {"id": "demo-dob-inspection-07", "record_type": "inspection",
     "raw_dob_id": "DEMO-INSP-0007", "signal_kind": "inspection_passed",
     "inspection_type": "Plumbing Rough", "inspection_result": "PASSED",
     "inspection_result_description": "Re-inspection — corrected and approved",
     "linked_job_number": "DEMO000003", "_inspection_date_days_ago": 24,
     "_detected_at_days_ago": 24, "severity": "Low"},
    {"id": "demo-dob-inspection-08", "record_type": "inspection",
     "raw_dob_id": "DEMO-INSP-0008", "signal_kind": "inspection_passed",
     "inspection_type": "Site Safety", "inspection_result": "PASSED",
     "inspection_result_description": "Site safety plan and logs reviewed",
     "linked_job_number": "DEMO000001", "_inspection_date_days_ago": 9,
     "_detected_at_days_ago": 9, "severity": "Low"},
]


# ── PLANS AND FILES ─────────────────────────────────────────────────────────
#
# METADATA ONLY, AND NOTHING BACKS IT. These rows carry the shape
# GET /projects/{id}/dropbox-files returns for an R2-cached file — including the
# backend proxy URL such a row normally carries — but there is NO R2 OBJECT
# behind any of them, and this module will never accept one.
#
# THAT UNFINISHED EDGE BELONGS TO THE ROUTE, NOT TO THE DATA, and it is written
# here so the decision gets made rather than discovered. A demo user who taps a
# plan reaches GET /projects/demo/files/{id}/content, which has to answer
# something; the honest answers are a 404 or a "not available in the demo"
# placeholder, and choosing between them is the job of whoever wires the routes.
#
# `index_status` is `_public_index_status`'s shape — {state, reason,
# disciplines, covered_by, at} — on the one row that has one. The combined-set
# skip is included deliberately: "Combined set — skipped", with its reason, is a
# real state the Plans & Files screen renders, and a demo that only ever shows
# the happy path hides the disclosure the screen was built to make.
DEMO_FILES = [
    {"id": "demo-file-01", "name": "A-101 Floor Plans.pdf",
     "path": "/Demo Project/Drawings/A-101 Floor Plans.pdf",
     "size": 4_812_004, "_modified_days_ago": 61, "source": "dropbox_sync",
     "cache_version": 3, "index_status": None},
    {"id": "demo-file-02", "name": "S-201 Framing Plans.pdf",
     "path": "/Demo Project/Drawings/S-201 Framing Plans.pdf",
     "size": 6_204_118, "_modified_days_ago": 61, "source": "dropbox_sync",
     "cache_version": 3, "index_status": None},
    {"id": "demo-file-03", "name": "M-401 Mechanical.pdf",
     "path": "/Demo Project/Drawings/M-401 Mechanical.pdf",
     "size": 3_118_442, "_modified_days_ago": 47, "source": "dropbox_sync",
     "cache_version": 2, "index_status": None},
    {"id": "demo-file-04", "name": "Full Drawing Set (combined).pdf",
     "path": "/Demo Project/Drawings/Full Drawing Set (combined).pdf",
     "size": 41_903_770, "_modified_days_ago": 47, "source": "dropbox_sync",
     "cache_version": 2,
     "index_status": {
         "state": "skipped_combined_set",
         "reason": "every discipline in this file is already indexed on its own",
         "disciplines": ["A", "S", "M"],
         "covered_by": ["demo-file-01", "demo-file-02", "demo-file-03"],
         "_at_days_ago": 47,
     }},
    {"id": "demo-file-05", "name": "Site Safety Plan.pdf",
     "path": "/Demo Project/Site Safety/Site Safety Plan.pdf",
     "size": 2_004_551, "_modified_days_ago": 118, "source": "upload",
     "cache_version": 1, "index_status": None},
    {"id": "demo-file-06", "name": "Scaffold Design — Sealed.pdf",
     "path": "/Demo Project/Field Set/Scaffold Design — Sealed.pdf",
     "size": 1_442_907, "_modified_days_ago": 58, "source": "upload",
     "cache_version": 1, "index_status": None},
]
