"""ONE RECORD WITH ITS AMENDMENT HISTORY, NOT TWO OF IT.

THE OPERATOR'S RULING, AND THE ONE THING IT FORBIDS. An inspector should see
one record with its history. Amending a filed document IN PLACE was considered
and rejected: `verify_signature_integrity` re-hashes the STORED snapshot
against itself and never reads the live document, so an in-place edit would
leave every signature verifying green on content nobody signed. So the original
stays immutable and this is a READ-PATH change — which is why
`test_no_stored_byte_of_a_filed_record_changes` below is not a formality.

── THE THREE THINGS THAT WERE WRONG ─────────────────────────────────────────

G1  `GET /logbooks/project/{id}/submitted` returned every submitted row with
    no `is_amendment` filter, and the screen that reads it draws a card per
    row and imports no collapse helper. 26 (project, date, log_type) groups in
    production hold two or more submitted rows where at least one is an
    amendment: the original and its correction, two identical-looking filed
    records, nothing saying which is current.

G2  the client's `collapseChains` keyed on `data.worker_id`, which resolves
    for `subcontractor_orientation` and no other type. Asserted in
    frontend/src/utils/amendmentChainKeysOnTheChain.test.cjs, not here.

G3  `amendment_state` returns the "none" state unless `is_amendment is True`,
    so a superseded PARENT'S sheet printed as though it were the record.

── WHAT THIS FILE REFUSES TO DO ─────────────────────────────────────────────

It does not restate `_filed_log`'s supersession rule. The whole design of the
collapse is that it GROUPS the documents and then calls `_filed_log` to pick
the head, so that the list and the combined report cannot disagree about one
amendment. A test here that re-encoded "newest filed wins" would be the second
copy of the rule arriving through the test suite.

Run:  python -m pytest tests/test_one_record_with_its_history.py -q
"""

from __future__ import annotations

import copy
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


# ── the documents, in the shapes amend_logbook actually writes ──────────────
#
# `date`, `log_type`, `project_id` and `company_id` are COPIED from the parent
# onto the child (server.py, amend_logbook), which is the fact the per-date
# collapse and the (project, date, log_type) sibling read both rest on.

DAY = "2026-09-02"


def _t(hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 9, 2, hh, mm, tzinfo=timezone.utc)


def _doc(_id, *, parent=None, hour=8, log_type="daily_jobsite",
         status="submitted", is_locked=True, by="Casey CP",
         reason="corrected the crew count", date=DAY, data=None):
    d = {
        "_id": _id,
        "project_id": "proj1",
        "company_id": "co_test",
        "log_type": log_type,
        "date": date,
        "status": status,
        "is_locked": is_locked,
        "is_deleted": False,
        "cp_name": by,
        "created_by_name": by,
        "created_at": _t(hour),
        "updated_at": _t(hour),
        "data": copy.deepcopy(data) if data is not None else {"weather": "Sunny"},
    }
    if parent is not None:
        d["is_amendment"] = True
        d["parent_logbook_id"] = parent
        d["amendment_reason"] = reason
    return d


def _ids(rows):
    return [str(r.get("id") or r.get("_id") or "") for r in rows]


# ══ 1. THE PRIMITIVE ═══════════════════════════════════════════════════════

class ChainCollapse(unittest.TestCase):
    """The grouping, which is the half `_filed_log` could not do."""

    def test_a_simple_amended_log_is_one_record(self):
        rows = [_doc("orig", hour=8), _doc("amd", parent="orig", hour=10)]
        out = server.collapse_amendment_chains(rows)
        self.assertEqual(len(out), 1, "the original and its amendment are one record")
        self.assertEqual(str(out[0]["head"]["_id"]), "amd")
        self.assertEqual(out[0]["length"], 2)
        self.assertEqual(out[0]["superseded"], ["orig"])

    def test_a_four_deep_chain_walks_to_the_true_head(self):
        """Production's deepest chain, and the shape 11 live children sit in:
        a parent that is itself an amendment."""
        rows = [
            _doc("l1", hour=8),
            _doc("l2", parent="l1", hour=9),
            _doc("l3", parent="l2", hour=10),
            _doc("l4", parent="l3", hour=11),
        ]
        out = server.collapse_amendment_chains(rows)
        self.assertEqual(len(out), 1, "four documents, one record")
        self.assertEqual(str(out[0]["head"]["_id"]), "l4")
        self.assertEqual(out[0]["length"], 4)
        self.assertEqual(out[0]["path"], ["l4", "l3", "l2", "l1"])
        self.assertEqual(out[0]["competing"], [])

    def test_a_chain_collapses_whatever_order_it_arrives_in(self):
        """Mongo's order is not the chain's. A grandchild that arrives before
        its parent must still find the root."""
        rows = [
            _doc("l3", parent="l2", hour=10),
            _doc("l1", hour=8),
            _doc("l4", parent="l3", hour=11),
            _doc("l2", parent="l1", hour=9),
        ]
        out = server.collapse_amendment_chains(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out[0]["head"]["_id"]), "l4")

    def test_a_fork_surfaces_as_a_fork(self):
        """TWO FILED CHILDREN OF ONE PARENT. `_filed_log` has to pick one --
        it must print something -- and the pick is deterministic. It is also
        SILENT, and six parents in production are in this state. The losing
        correction is named rather than dropped."""
        rows = [
            _doc("orig", hour=8),
            _doc("fork_a", parent="orig", hour=10),
            _doc("fork_b", parent="orig", hour=11),
        ]
        out = server.collapse_amendment_chains(rows)
        self.assertEqual(len(out), 1, "still one record, not three")
        self.assertEqual(str(out[0]["head"]["_id"]), "fork_b")
        self.assertEqual([str(c["_id"]) for c in out[0]["competing"]], ["fork_a"],
                         "the correction the tie-break did not pick is named")

    def test_two_originals_are_not_reported_as_competing(self):
        """A COMPETING RECORD IS A CORRECTION SOMEBODY FILED. Two separate
        originals amend nothing, so neither competes with the other -- and
        without the parent-link clause both would be reported as forks."""
        rows = [_doc("a", hour=8), _doc("b", hour=9)]
        out = server.collapse_amendment_chains(rows)
        self.assertEqual(len(out), 2, "two unlinked records stay two records")
        for entry in out:
            self.assertEqual(entry["competing"], [])

    def test_an_amendment_whose_parent_is_absent_is_still_shown(self):
        """FAIL OPEN. A child whose parent is not in the set -- never
        submitted, another page, another date -- becomes its own root and is
        rendered. Dropping a filed compliance record to make a list tidy is
        the opposite failure and the worse one."""
        rows = [_doc("child", parent="a_parent_not_here", hour=10)]
        out = server.collapse_amendment_chains(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out[0]["head"]["_id"]), "child")

    def test_two_types_never_merge(self):
        rows = [_doc("dj", log_type="daily_jobsite"),
                _doc("tt", log_type="toolbox_talk")]
        self.assertEqual(len(server.collapse_amendment_chains(rows)), 2)

    def test_a_cycle_terminates(self):
        """A self-parent or a pair naming each other is a write nobody has
        ruled out. An infinite loop here is an unanswered request on the
        tablet's only logbook read."""
        a = _doc("a", hour=8)
        a["parent_logbook_id"] = "b"
        b = _doc("b", parent="a", hour=9)
        out = server.collapse_amendment_chains([a, b])
        self.assertTrue(out, "a cycle returns rather than hanging")
        self.assertEqual(sum(e["length"] for e in out), 2,
                         "and no document is lost to it")

    def test_a_withdrawn_link_is_not_counted(self):
        """`chainHead` on the client and `_filed_log` here both already say a
        withdrawn correction corrected nothing. The length must agree."""
        rows = [_doc("orig", hour=8),
                _doc("wd", parent="orig", hour=10, status="withdrawn",
                     is_locked=False)]
        out = server.collapse_amendment_chains(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out[0]["head"]["_id"]), "orig")
        self.assertEqual(out[0]["length"], 1)

    def test_nothing_filed_still_yields_a_row(self):
        """`_filed_log` returns None here and on the REPORT that is right -- a
        card claiming FILED over an unsigned draft, carrying a public share
        link to it, is worse than a blank. On a LIST it would delete the row."""
        rows = [_doc("d", status="draft", is_locked=False)]
        out = server.collapse_amendment_chains(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(str(out[0]["head"]["_id"]), "d")

    def test_the_head_is_filed_logs_choice_and_not_a_second_rule(self):
        """THE POINT OF THE WHOLE DESIGN, asserted on the code rather than
        re-derived: the collapse calls `_filed_log`. A second supersession rule
        is how the list and the combined report come to disagree."""
        from tests.source_text import strip_python
        import inspect
        code = strip_python(inspect.getsource(server.collapsed_chain))
        self.assertIn("_filed_log(rows, log_type)", code,
                      "the head comes from _filed_log, not from a local sort")
        self.assertIn("logbook_is_filed(l)", code,
                      "and 'is this filed' goes through the one predicate")
        # ANCHORED, NOT BARE. `assertNotIn("is_locked", ...)` bans a SUBSTRING,
        # so it is satisfied or broken by anything containing the word --
        # test_absence_literals_are_specific.py caught exactly that here. These
        # two are the shapes a re-spelling of the filed test would actually
        # take, and neither matches a mention of the field in passing.
        self.assertNotIn('l.get("is_locked")', code,
                         "the filed test is not re-spelled here")
        self.assertNotIn('== "submitted"', code,
                         "nor is its other half")


# ══ 2. THE ENDPOINT ════════════════════════════════════════════════════════
#
# A Mongo faithful enough for a collapse to mean something. Deliberately a
# separate, smaller fake than test_submitted_logbooks_projection's: that one
# exists to measure a PROJECTION and models `_strip`; this one models the
# queries the endpoint makes and RECORDS every write method, because "no
# stored byte changes" is the constraint the ruling rests on.

class _Cursor:
    def __init__(self, items):
        self._items = items

    def sort(self, spec, direction=None):
        keys = ([(spec, direction if direction is not None else 1)]
                if isinstance(spec, str) else list(spec))
        for field, d in reversed(keys):
            self._items.sort(key=lambda x, f=field: (x.get(f) is None, x.get(f) or ""),
                             reverse=(d == -1))
        return self

    async def to_list(self, n=None):
        return self._items if n is None else self._items[:n]


def _matches(doc, query):
    for key, cond in (query or {}).items():
        val = doc.get(key, None)
        if isinstance(cond, dict):
            if "$ne" in cond and val == cond["$ne"]:
                return False
            if "$in" in cond and val not in cond["$in"]:
                return False
        elif val != cond:
            return False
    return True


def _project(doc, projection):
    if not projection:
        return copy.deepcopy(doc)
    keep = {k for k, v in projection.items() if v}
    if keep:
        return {k: copy.deepcopy(v) for k, v in doc.items()
                if k in keep or k == "_id"}
    out = copy.deepcopy(doc)
    for path in projection:
        node, parts = out, path.split(".")
        for p in parts[:-1]:
            node = node.get(p) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(parts[-1], None)
    return out


class _Logbooks:
    def __init__(self, docs):
        self.docs = docs
        self.writes = []

    def find(self, query=None, projection=None, *a, **k):
        hits = [d for d in self.docs if _matches(d, query or {})]
        return _Cursor([_project(d, projection) for d in hits])

    async def find_one(self, query=None, *a, **k):
        for d in self.docs:
            if _matches(d, query or {}):
                return copy.deepcopy(d)
        return None

    async def distinct(self, field, query=None, *a, **k):
        vals, seen = [], set()
        for d in self.docs:
            if not _matches(d, query or {}):
                continue
            v = d.get(field, None)
            if v in seen:
                continue
            seen.add(v)
            vals.append(v)
        return vals

    # EVERY WRITE METHOD, RECORDED AND REFUSED. A read path that writes is the
    # one thing this change is forbidden to be.
    def _forbid(self, name):
        async def _w(*a, **k):
            self.writes.append((name, a, k))
            raise AssertionError(f"the read path called {name}")
        return _w

    def __getattr__(self, name):
        if name in ("update_one", "update_many", "insert_one", "insert_many",
                    "delete_one", "delete_many", "replace_one",
                    "find_one_and_update", "bulk_write"):
            return self._forbid(name)
        raise AttributeError(name)


class _FakeCollection:
    def __init__(self, one=None):
        self.one = one

    async def find_one(self, *a, **k):
        return self.one

    def find(self, *a, **k):
        return _Cursor([])

    async def count_documents(self, *a, **k):
        return 0


PROJECT = {"_id": "proj1", "name": "Test Tower", "address": "1 Test Plaza",
           "company_name": "Test Builders", "company_id": "co_test",
           "is_deleted": False}


class _FakeDb:
    def __init__(self, logbooks):
        self._c = {"logbooks": logbooks, "projects": _FakeCollection(one=PROJECT)}

    def _get(self, n):
        if n not in self._c:
            self._c[n] = _FakeCollection()
        return self._c[n]

    def __getattr__(self, n):
        if n.startswith("_"):
            raise AttributeError(n)
        return self._get(n)

    def __getitem__(self, n):
        return self._get(n)


SITE_USER = {"_id": "site_1", "id": "site_1", "role": "cp",
             "company_id": "co_test", "account_status": "approved",
             "full_name": "Site Tablet", "assigned_projects": ["proj1"]}


def _submitted(docs):
    logbooks = _Logbooks(docs)
    db = _FakeDb(logbooks)

    async def _fake_user():
        return SITE_USER

    async def _fake_project():
        return PROJECT

    ov = server.app.dependency_overrides
    ov[server.get_current_user] = _fake_user
    ov[server.require_project_access] = _fake_project
    try:
        with patch.object(server, "db", db):
            r = TestClient(server.app).get(
                "/api/logbooks/project/proj1/submitted")
    finally:
        ov.clear()
    return r, logbooks


class TheInspectorsList(unittest.TestCase):
    """What the one screen an inspector reads on site is handed."""

    def test_an_amended_log_arrives_as_one_row(self):
        r, _ = _submitted([_doc("orig", hour=8),
                           _doc("amd", parent="orig", hour=10)])
        self.assertEqual(r.status_code, 200)
        rows = r.json()["dates"][DAY]
        self.assertEqual(_ids(rows), ["amd"],
                         "one record, and it is the amendment")
        self.assertEqual(r.json()["log_count"], 1,
                         "the count describes the body")

    def test_the_row_says_it_is_an_amended_record(self):
        r, _ = _submitted([_doc("orig", hour=8),
                           _doc("amd", parent="orig", hour=10,
                                by="Michael Cespedes",
                                reason="corrected the crew count")])
        row = r.json()["dates"][DAY][0]
        self.assertEqual(row["_chain_length"], 2)
        self.assertEqual(row["_superseded_ids"], ["orig"])
        self.assertIn("This record was amended by Michael Cespedes",
                      row["amendment_sentence"])
        self.assertIn("corrected the crew count", row["amendment_sentence"])

    def test_a_four_deep_chain_is_one_row_saying_four(self):
        r, _ = _submitted([
            _doc("l1", hour=8), _doc("l2", parent="l1", hour=9),
            _doc("l3", parent="l2", hour=10), _doc("l4", parent="l3", hour=11),
        ])
        rows = r.json()["dates"][DAY]
        self.assertEqual(_ids(rows), ["l4"])
        self.assertEqual(rows[0]["_chain_length"], 4)
        self.assertEqual(sorted(rows[0]["_superseded_ids"]), ["l1", "l2", "l3"])

    def test_a_fork_reaches_the_screen_as_a_fork(self):
        r, _ = _submitted([_doc("orig", hour=8),
                           _doc("fork_a", parent="orig", hour=10),
                           _doc("fork_b", parent="orig", hour=11)])
        rows = r.json()["dates"][DAY]
        self.assertEqual(_ids(rows), ["fork_b"])
        self.assertEqual([c["id"] for c in rows[0]["_competing_records"]],
                         ["fork_a"],
                         "the other filed correction is named, not dropped")

    def test_an_unamended_row_carries_none_of_the_new_fields(self):
        """SILENT ON THE COMMON CASE. Nothing extra on the 96% of rows that
        are one document, so nothing extra to read wrong."""
        r, _ = _submitted([_doc("plain", hour=8)])
        row = r.json()["dates"][DAY][0]
        for field in ("_chain_length", "_superseded_ids", "amendment_sentence",
                      "_competing_records"):
            self.assertNotIn(field, row)

    def test_every_type_collapses_and_not_just_orientation(self):
        """G2's measurement, from the server's side. The client's worker key
        resolved for orientation only; `parent_logbook_id` is written for
        every type."""
        docs = []
        types = ["daily_jobsite", "toolbox_talk", "preshift_signin",
                 "osha_log", "scaffold_maintenance", "site_superintendent_log",
                 "subcontractor_orientation"]
        for i, t in enumerate(types):
            docs.append(_doc(f"{t}_o", log_type=t, hour=8))
            docs.append(_doc(f"{t}_a", log_type=t, parent=f"{t}_o", hour=9))
        r, _ = _submitted(docs)
        rows = r.json()["dates"][DAY]
        self.assertEqual(len(rows), len(types),
                         "one row per type, not two")
        self.assertEqual(sorted(_ids(rows)),
                         sorted(f"{t}_a" for t in types))

    def test_two_dates_do_not_bleed_into_one_another(self):
        other = "2026-09-01"
        r, _ = _submitted([
            _doc("d1_o", hour=8, date=other),
            _doc("d1_a", parent="d1_o", hour=9, date=other),
            _doc("d2_o", hour=8),
            _doc("d2_a", parent="d2_o", hour=9),
        ])
        dates = r.json()["dates"]
        self.assertEqual(_ids(dates[other]), ["d1_a"])
        self.assertEqual(_ids(dates[DAY]), ["d2_a"])

    def test_the_payload_shape_an_installed_client_reads_is_unchanged(self):
        """AN OLD TABLET CANNOT TAKE AN OTA FOR WEEKS. It gets fewer rows of
        exactly the shape it already reads, and ignores the additions."""
        r, _ = _submitted([_doc("orig", hour=8),
                           _doc("amd", parent="orig", hour=10)])
        body = r.json()
        self.assertEqual(sorted(body.keys()),
                         ["complete", "date_count", "dates", "log_count",
                          "next_before"])
        row = body["dates"][DAY][0]
        for field in ("id", "log_type", "status", "date", "data",
                      "cache_version"):
            self.assertIn(field, row)


class NothingIsWritten(unittest.TestCase):
    """THE CONSTRAINT THE RULING RESTS ON, measured two ways."""

    def test_no_stored_byte_of_a_filed_record_changes(self):
        docs = [_doc("orig", hour=8), _doc("amd", parent="orig", hour=10),
                _doc("fork", parent="orig", hour=11)]
        before = copy.deepcopy(docs)
        r, logbooks = _submitted(docs)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(docs, before,
                         "the documents handed in are byte-identical after")
        self.assertEqual(logbooks.writes, [])

    def test_the_collapse_never_mutates_the_documents_it_reads(self):
        rows = [_doc("orig", hour=8), _doc("amd", parent="orig", hour=10)]
        before = copy.deepcopy(rows)
        out = server.collapse_amendment_chains(rows)
        self.assertEqual(rows, before)
        self.assertEqual(len(out), 1)


# ══ 3. THE SUPERSEDED SHEET ════════════════════════════════════════════════

class TheSupersededSheet(unittest.TestCase):
    """G3. The half the list cannot do: the parent's PDF is still downloadable,
    still in somebody's folder, and said nothing."""

    def test_the_current_record_says_nothing(self):
        rows = [_doc("orig", hour=8), _doc("amd", parent="orig", hour=10)]
        self.assertEqual(server.superseded_sentence(rows[1], rows), "")

    def test_an_unamended_record_says_nothing(self):
        rows = [_doc("solo", hour=8)]
        self.assertEqual(server.superseded_sentence(rows[0], rows), "")

    def test_the_amended_parent_says_so(self):
        rows = [_doc("orig", hour=8), _doc("amd", parent="orig", hour=10)]
        line = server.superseded_sentence(rows[0], rows)
        self.assertEqual(
            line,
            "This record was amended on 2026-09-02. The current record is the "
            "amendment of that date.")

    def test_a_draft_says_nothing_here(self):
        """`filing_state` above it already says the record is not filed. Two
        pieces of apparatus asserting one thing is how they come to disagree."""
        rows = [_doc("d", status="draft", is_locked=False, hour=8),
                _doc("amd", parent="d", hour=10)]
        self.assertEqual(server.superseded_sentence(rows[0], rows), "")

    def test_a_middle_link_points_at_the_head_and_not_at_its_child(self):
        """ON A 4-DEEP CHAIN THE DIRECT CHILD IS ITSELF SUPERSEDED. Naming it
        would hand the reader a second stale document."""
        rows = [_doc("l1", hour=8), _doc("l2", parent="l1", hour=9),
                _doc("l3", parent="l2", hour=10),
                _doc("l4", parent="l3", hour=11, by="Angel Lopez")]
        line = server.superseded_sentence(rows[0], rows)
        self.assertIn("corrected 3 times in all", line)
        self.assertIn("The current record is the amendment filed on "
                      "2026-09-02 by Angel Lopez", line)

    def test_a_forked_parent_refuses_to_name_one_correction(self):
        rows = [_doc("orig", hour=8), _doc("a", parent="orig", hour=10),
                _doc("b", parent="orig", hour=11)]
        line = server.superseded_sentence(rows[0], rows)
        self.assertIn("2 separate corrections", line)
        self.assertIn("They compete", line)

    def test_the_losing_half_of_a_fork_does_not_read_as_current(self):
        rows = [_doc("orig", hour=8), _doc("a", parent="orig", hour=10),
                _doc("b", parent="orig", hour=11)]
        line = server.superseded_sentence(rows[1], rows)
        self.assertIn("A second correction to the same record was filed", line)

    def test_the_notice_escapes_what_comes_off_the_document(self):
        rows = [_doc("orig", hour=8),
                _doc("amd", parent="orig", hour=10,
                     by='Casey <script>alert(1)</script>')]
        html = server.superseded_notice(rows[0], rows)
        self.assertNotIn("<script>", html)

    def test_the_notice_adds_nothing_about_the_records_own_data(self):
        """G3 ADDS A NOTICE. It must not alter, hide or restate the record."""
        rows = [_doc("orig", hour=8, data={"weather": "Sunny",
                                           "general_description": "Shoring"}),
                _doc("amd", parent="orig", hour=10)]
        html = server.superseded_notice(rows[0], rows)
        self.assertTrue(html)
        self.assertNotIn("Shoring", html)
        self.assertNotIn("Sunny", html)

    def test_the_sheet_draws_it_above_the_amendment_banner(self):
        """ORDER OF WHAT THEY DENY: not filed, then not current, then "this was
        itself a correction". A middle link carries the last two at once."""
        from tests.source_text import strip_python
        engine = strip_python(
            (_BACKEND / "lib" / "legal_render" / "engine.py")
            .read_text(encoding="utf-8"))
        i_state = engine.index('ctx["filing_state"]')
        i_sup = engine.index('ctx.get("superseded_html")')
        i_amd = engine.index('ctx.get("amendment_html")')
        self.assertLess(i_state, i_sup)
        self.assertLess(i_sup, i_amd)

    def test_the_renderer_composes_it_and_hands_it_over(self):
        from tests.source_text import strip_python
        import inspect
        code = strip_python(inspect.getsource(server.generate_single_logbook_html))
        self.assertIn("await superseded_notice_for(logbook)", code)
        self.assertIn('"superseded_html": _superseded_html', code)

    def test_the_lookup_is_the_served_query_and_not_the_partial_index(self):
        """MEASURED, NOT ASSUMED. The only index on `parent_logbook_id` is
        `logbooks_one_open_amendment_per_parent`, and its partialFilter is
        `status: draft, is_locked: False, cp_signature: None` -- the OPPOSITE
        of the filed children this notice asks for, so Mongo cannot use it and
        the query would scan the collection that holds the photographs."""
        from tests.source_text import strip_python
        import inspect
        code = strip_python(inspect.getsource(server.superseded_notice_for))
        self.assertIn('"project_id"', code)
        self.assertIn('"date"', code)
        self.assertIn('"log_type"', code)
        self.assertNotIn('"parent_logbook_id":', code,
                         "it must not query the field the partial index covers")
        self.assertEqual(
            server.OPEN_AMENDMENT_PARTIAL_FILTER.get("status"), "draft",
            "if this ever stops being draft-only, the reasoning above changes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
