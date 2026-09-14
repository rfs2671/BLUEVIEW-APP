"""A paid operation running since launch with no artifact recording it happened.

Two endpoints call a paid vision model — `POST /checkin/upload-osha` on every
card photo at every gate, and `POST /enrollment/parse_card`. Nothing anywhere
recorded that a call was made. No counter, no log collection, no per-call row.
"How much did we spend on OCR last month" and "which project drives it" could
not be answered from our own data.

Every other instance of a check that could not reach its subject in
docs/audits/followups.md is a TEST. This one is a MEASUREMENT, and it was
missing entirely rather than wrong.

THE CEILING IS NOT IN THIS CHANGE. A ceiling reads a number; there is no number
until this has run. Nothing here refuses, alerts, or thresholds.

Run:  python -m pytest backend/tests/test_vision_meter.py -q
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import os
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib import vision_meter as vm  # noqa: E402


class _FakeColl:
    def __init__(self):
        self.calls = []

    async def update_one(self, flt, update, upsert=False):
        self.calls.append({"filter": flt, "update": update, "upsert": upsert})


class _FakeDB:
    def __init__(self):
        self.coll = _FakeColl()

    def __getitem__(self, name):
        self.name = name
        return self.coll


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── THE ATOMIC POINT, WHICH IS THE WHOLE DESIGN ───────────────────────────

def test_it_increments_and_never_reads_first():
    """We run at least two containers. `find` then `update` races: both read 4,
    both write 5, and two calls count as one — undercounting by the container
    count under exactly the load worth measuring. That is the in-process rate
    limiter's N-times problem with extra steps, and it LOOKS more careful.

    `$inc` is applied server-side under the document's own lock. There is no
    read, so there is nothing to race."""
    db = _FakeDB()
    _run(vm.record_vision_call(db, endpoint=vm.VISION_UPLOAD_OSHA,
                               project_id="p1"))
    (one,) = db.coll.calls
    assert one["update"]["$inc"] == {"calls": 1}
    assert one["upsert"] is True
    src = inspect.getsource(vm.record_vision_call)
    for forbidden in ("find_one", "find(", "$set: {\"calls\"", '"calls": '):
        if forbidden == '"calls": ':
            continue
        assert forbidden not in src, (
            f"{forbidden!r} in the counter — a read-then-write races across "
            "containers and undercounts"
        )


def test_set_and_setoninsert_touch_disjoint_paths():
    """Mongo rejects an update naming one path in both."""
    db = _FakeDB()
    _run(vm.record_vision_call(db, endpoint=vm.VISION_PARSE_CARD, project_id="p"))
    upd = db.coll.calls[0]["update"]
    assert not (set(upd["$set"]) & set(upd["$setOnInsert"]))
    assert "calls" not in upd["$set"] and "calls" not in upd["$setOnInsert"]


# ── THE KEY ───────────────────────────────────────────────────────────────

def test_one_row_per_day_project_endpoint():
    a = vm.meter_key("2026-09-04", "p1", vm.VISION_UPLOAD_OSHA)
    for other in (vm.meter_key("2026-09-05", "p1", vm.VISION_UPLOAD_OSHA),
                  vm.meter_key("2026-09-04", "p2", vm.VISION_UPLOAD_OSHA),
                  vm.meter_key("2026-09-04", "p1", vm.VISION_PARSE_CARD)):
        assert a != other, other
    assert vm.meter_key("2026-09-04", None, "x").endswith(":unknown:x")


def test_the_day_is_eastern_not_utc():
    """A UTC boundary splits a New York shift across two rows from 20:00 EDT.
    Thirteen instances of that bug have shipped on this project."""
    late = datetime(2026, 9, 5, 1, 30, tzinfo=timezone.utc)   # 21:30 EDT Sep 4
    assert vm.eastern_day(late) == "2026-09-04"
    early = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)  # 08:00 EDT Sep 4
    assert vm.eastern_day(early) == "2026-09-04"


# ── IT NEVER BECOMES THE CALLER'S PROBLEM ─────────────────────────────────

def test_a_failed_write_never_raises():
    class Boom:
        def __getitem__(self, _):
            raise RuntimeError("mongo is down")
    _run(vm.record_vision_call(Boom(), endpoint=vm.VISION_UPLOAD_OSHA))


def test_an_unregistered_endpoint_is_still_counted():
    """Counted under its own name and logged — never dropped. A misnamed
    endpoint that vanished from the count is how spend goes unattributed
    again."""
    db = _FakeDB()
    _run(vm.record_vision_call(db, endpoint="something_new", project_id="p"))
    assert len(db.coll.calls) == 1
    assert ":something_new" in db.coll.calls[0]["filter"]["_id"]


# ── AND NO LIMIT IS ATTACHED ──────────────────────────────────────────────

def test_nothing_here_refuses_or_alerts():
    src = inspect.getsource(vm)
    body = src[src.index("def record_vision_call"):]
    for term in ("HTTPException", "status_code", "compliance_alerts", "raise "):
        assert term not in body, (
            f"{term!r} in the meter. The ceiling is a separate change and is "
            "gated on a week of this counter's own data."
        )


# ── BOTH CALL SITES, BEFORE THE MODEL ─────────────────────────────────────

def _call_lines(fn, name):
    src = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(src)
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            rendered = ast.unparse(node.func)
            if rendered in ("record_vision_call", name):
                out.setdefault(rendered, node.lineno)
    return out


def test_upload_osha_counts_before_it_spends():
    import server
    lines = _call_lines(server.upload_osha_card, "client_http.post")
    assert "record_vision_call" in lines, "upload_osha_card is not metered"
    src = textwrap.dedent(inspect.getsource(server.upload_osha_card))
    post_at = min(n.lineno for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Call)
                  and ast.unparse(n.func).endswith("client_http.post"))
    assert lines["record_vision_call"] < post_at, (
        "the model is called before the count; a call that errors after "
        "billing would go unrecorded"
    )


def test_parse_card_counts_before_it_spends_and_after_it_validates():
    import card_audit
    src = textwrap.dedent(inspect.getsource(card_audit.enrollment_parse_card))
    tree = ast.parse(src)
    def first(pred):
        got = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call) and pred(ast.unparse(n.func))]
        return min(got) if got else None
    meter = first(lambda r: r == "record_vision_call")
    vlm = first(lambda r: r == "_qwen_vlm")
    lookup = first(lambda r: r.endswith("projects.find_one"))
    assert meter and vlm and lookup
    assert lookup < meter < vlm, (
        f"order is lookup={lookup} meter={meter} vlm={vlm}; an unresolvable "
        "request must cost nothing and must not be counted as spend"
    )


# ── The WhatsApp side, which nothing counted until now ────────────────────


def test_every_qwen_call_site_is_metered():
    """THE SET USED TO NAME TWO AND THE SYSTEM HAD FOUR.

    Both extra sites were on the WhatsApp path — the one input to this
    system that nobody at Levelog controls — and neither recorded anything.
    This test is written against the POST, not against a list of function
    names, so a fifth call site added later fails here rather than going
    quiet: anything that posts to QWEN_API_BASE must have a
    record_vision_call ahead of it in the same function."""
    import re
    src = Path(__file__).resolve().parents[1] / "server.py"
    text = src.read_text(encoding="utf-8")
    tree = ast.parse(text)

    posts_to_qwen = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.get_source_segment(text, node) or ""
        if "QWEN_API_BASE" not in body or "chat/completions" not in body:
            continue
        posts_to_qwen.append((node.name, body))

    assert posts_to_qwen, "no Qwen call sites found — has the base URL moved?"

    unmetered = []
    for name, body in posts_to_qwen:
        meter = body.find("record_vision_call")
        post = body.find("chat/completions")
        if meter == -1 or meter > post:
            # The card-audit adapter is metered by its caller in
            # card_audit.py, with the project_id this level does not have.
            # Counting it here too would double every card parse.
            if name == "_card_audit_vlm_adapter":
                continue
            unmetered.append(name)

    assert not unmetered, (
        f"paid vision calls with no count before them: {unmetered}"
    )


def test_plan_indexing_counts_per_page_not_per_upload():
    """A forty-sheet set is forty calls from one user action. The count sits
    inside _index_single_page, which is the loop body, so the row says forty
    — not one."""
    import server
    lines = _call_lines(server._index_single_page, "client_http.post")
    assert "record_vision_call" in lines, "plan indexing is not metered"
    assert lines["record_vision_call"] < lines["client_http.post"]


def test_whatsapp_vqa_counts_per_sheet_not_per_question():
    """_handle_plan_query walks its candidate sheets until one answers, so a
    question about something the set does not show costs the whole list. The
    count is inside the per-sheet function for that reason."""
    import server
    lines = _call_lines(server._qwen_visual_qa, "client_http.post")
    assert "record_vision_call" in lines, "WhatsApp VQA is not metered"
    assert lines["record_vision_call"] < lines["client_http.post"]


def test_vqa_does_not_count_a_call_it_never_makes():
    """The guard clause returns before the meter. An unconfigured key or an
    empty buffer is not spend, and counting it would put a number in the row
    that no invoice will ever match."""
    src = textwrap.dedent(inspect.getsource(__import__("server")._qwen_visual_qa))
    tree = ast.parse(src)
    guard = min(n.lineno for n in ast.walk(tree) if isinstance(n, ast.Return))
    meter = min(n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and ast.unparse(n.func) == "record_vision_call")
    assert guard < meter, "the meter fires before the no-key guard returns"

