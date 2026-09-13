"""A SECTION THAT DRAWS NOTHING IS THE FAILURE THIS MIGRATION KEEPS MAKING.

── WHAT HAPPENED, TWICE ─────────────────────────────────────────────────

The superintendent log's statutory register drew NOTHING on all six filed
records. `register` took its subject AS the rows, and under `scope: context`
the subject is the whole render context -- so iterating it yielded key STRINGS,
every one was skipped as "not a dict", and an entire BC 3301.13.13 register
came off the sheet.

THE WORD DIFF REPORTED IT AS SEVENTEEN MISSING WORDS. That is a number a reader
skims past. It was found by reading the list, not by the number.

The daily jobsite log did the same thing one conversion earlier: an inspection
register with no stored map drew a numbered grey bar with nothing under it,
because emptiness was decided by "were any records filed" and one was.

── WHY A DECLARATION MAKES THIS EASY TO DO AND HARD TO SEE ──────────────

A section that renders empty is not an error. `validate` passes -- the
declaration is well-formed. The engine runs -- a primitive returning "" is a
legitimate thing for it to do. The page still has the section's numbered
heading, so it looks like a form with a blank field rather than a renderer that
failed. Every layer reports success.

── AND IT MATTERS MOST WHERE THERE IS NOTHING TO COMPARE AGAINST ────────

Six of the thirteen types have ZERO filed records. Their fixtures are the only
evidence those conversions will ever have, and a fixture that fills every
declared path is exactly what surfaces this shape: if a section has a value for
every field it declares and still draws nothing, the binding is wrong.

So this builds that fixture FROM THE DECLARATION ITSELF -- every path a section
names gets a value -- and asserts each section puts something on the page.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402
from lib import legal_render  # noqa: E402

_PROJECT = {"_id": "p1", "name": "Site", "address": "1 Test Street",
            "company_name": "Metro Build", "bbl": "3035400025",
            "nyc_bin": "3255362"}
_STROKES = [[{"x": 1, "y": 2}, {"x": 30, "y": 20}]]


def _put(doc: dict, path: str, value):
    """Set a dotted path, creating the maps on the way down."""
    parts = [p for p in str(path).split(".") if p and p != "."]
    if not parts:
        return
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
        if not isinstance(cur, dict):
            return
    cur[parts[-1]] = value


def _value_for(formatter: str):
    """Something a formatter will render as CONTENT, never as an absence."""
    return {
        "date_long": "2026-09-09",
        "datetime_stamp": "2026-09-09T07:00:00",
        "time_of_day": "07:30",
        "bbl_borough": "3035400025",
        "bbl_block": "3035400025",
        "bbl_lot": "3035400025",
        "yes_no": True,
        "answer": "yes",
        "pass_fail": True,
        "tick_or_blank": True,
        "toggle_list": {"compressor": True},
        "weather_line": {"weather": "Clear", "weather_temp": "70F"},
        "affirmation_note": 3,
        "signature_ink": {"paths": _STROKES},
    }.get(formatter, "Recorded value")


def _fixture(log_type: str) -> dict:
    """A record with a value for EVERY path the declaration names."""
    decl = legal_render.SCHEMAS[log_type]
    doc = {"_id": "lb1", "project_id": "p1", "date": "2026-09-09",
           "log_type": log_type, "status": "submitted",
           "cp_name": "daniel kaplan",
           "cp_signature": {"paths": _STROKES, "signerName": "daniel kaplan"},
           "data": {}}
    for sec in decl["sections"]:
        for path, _label, fmt in ((sec.get("fields") or [])
                                  + (sec.get("columns") or [])):
            if path and path != ".":
                _put(doc, path, _value_for(fmt))
        for key in ("path", "name_path", "signature_path"):
            p = sec.get(key)
            if isinstance(p, (list, tuple)):
                p = p[0]
            if not p or p in ("register_rows", "cs_attribution_sentence",
                              "preshift_affirmation_count"):
                continue
            prim = sec.get("primitive")
            if key == "path" and prim in ("table",):
                row = {}
                for cpath, _l, cfmt in (sec.get("columns") or []):
                    if cpath and cpath != ".":
                        _put(row, cpath, _value_for(cfmt))
                for need in (sec.get("row_requires") or []):
                    _put(row, need, "Recorded value")
                _put(doc, p, [row])
            elif key == "path" and prim in ("checklist", "inspection_log",
                                            "question_answers"):
                labels = legal_render.schema.LABEL_SETS.get(
                    sec.get("labels"), [])
                if prim == "inspection_log":
                    _put(doc, p, {k: {"result": "pass"} for k, _t in labels})
                elif prim == "question_answers":
                    _put(doc, p, {k: "YES" for k, _t in labels})
                else:
                    _put(doc, p, {k: True for k, _t in labels})
            elif key == "path" and prim == "narrative":
                _put(doc, p, "A recorded sentence.")
            elif key == "signature_path" or (key == "path"
                                             and prim == "signature"):
                # A MARK GOES WHERE A MARK GOES. `name_path` on a signature
                # section names the SIGNER, not the signature -- the first
                # version of this builder matched on the primitive alone and
                # wrote a stroke object over the printed name, so the sheet
                # rendered a signer called "[object]" and the fixture guard
                # read it as a record that filled nothing.
                _put(doc, p, {"paths": _STROKES})
            else:
                _put(doc, p, "Recorded value")
    return doc


class _Cur:
    def __init__(s, r): s._r = r
    def sort(s, *a, **k): return s
    def limit(s, *a, **k): return s
    async def to_list(s, *a, **k): return list(s._r)


class _Coll:
    def find(s, *a, **k): return _Cur([])
    async def find_one(s, *a, **k): return dict(_PROJECT)
    async def count_documents(s, *a, **k): return 0
    def aggregate(s, *a, **k): return _Cur([])


class _DB:
    def __getattr__(s, n): return _Coll()


def _render(doc):
    stack = [patch.object(server, "db", _DB()),
             patch.object(server, "to_query_id", lambda v: v),
             patch.object(server, "eastern_datetime", lambda *a, **k: "FROZEN")]
    for p in stack:
        p.start()
    try:
        return asyncio.run(server.generate_single_logbook_html(doc))
    finally:
        for p in reversed(stack):
            p.stop()


def _text(html: str) -> str:
    s = re.sub(r"<img\b[^>]*>", " [IMAGE] ", html, flags=re.I)
    s = re.sub(r"<svg\b.*?</svg>", " [INK] ", s, flags=re.S | re.I)
    s = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    import html as _h
    return re.sub(r"\s+", " ", _h.unescape(s)).strip()


class EveryDeclaredSectionPutsSomethingOnThePage(unittest.TestCase):

    def test_there_are_converted_types_to_check(self):
        """THE VACUITY GUARD. Every assertion below iterates CONVERTED_TYPES,
        and an empty set makes all of them pass."""
        self.assertGreaterEqual(len(legal_render.CONVERTED_TYPES), 1)

    def test_every_section_of_every_converted_type_draws_content(self):
        """THE ASSERTION. A fixture with a value for every declared path must
        put something under every declared heading.

        A SECTION DRAWING NOTHING IS NOT AN ERROR ANYWHERE ELSE. `validate`
        passes, the engine runs, and the page keeps the numbered heading -- so
        it reads as a form with a blank field rather than a binding that is
        wrong. This is the only place that says otherwise.
        """
        for log_type in sorted(legal_render.CONVERTED_TYPES):
            decl = legal_render.SCHEMAS[log_type]
            html = _render(_fixture(log_type))
            text = _text(html)
            titles = [f"{s['n']}. {s['title']}" for s in decl["sections"]]
            for i, title in enumerate(titles):
                with self.subTest(log_type=log_type, section=title):
                    if title not in text:
                        # OMITTED, WHICH IS A LEGITIMATE OUTCOME. A section
                        # whose subject is resolved by the caller -- an
                        # affirmation count, a register the context carries --
                        # cannot be filled from the record, so this fixture
                        # cannot make it appear. An absent heading is a
                        # section that declined to draw; the failure this
                        # guard exists for is a heading WITH NOTHING UNDER IT.
                        continue
                    start = text.index(title) + len(title)
                    end = (text.index(titles[i + 1])
                           if i + 1 < len(titles)
                           and titles[i + 1] in text[start:] else len(text))
                    body = text[start:end].strip()
                    self.assertGreater(
                        len(body), 0,
                        f"{log_type} section {title!r} drew NOTHING for a "
                        f"record that has a value for every path it declares. "
                        f"The binding is wrong, and nothing else in this suite "
                        f"will say so -- validate passes, the engine runs, and "
                        f"the heading is still on the page.")

    def test_the_fixture_actually_fills_something(self):
        """THE GUARD ON THE FIXTURE. A builder that produced an empty record
        would make the assertion above pass on sheets full of 'not recorded',
        which is the shape it exists to catch."""
        for log_type in sorted(legal_render.CONVERTED_TYPES):
            with self.subTest(log_type=log_type):
                doc = _fixture(log_type)
                self.assertTrue(doc.get("data"),
                                "the fixture builder filled no data at all")
                # AT LEAST ONE DECLARED VALUE REACHES THE PAGE. Not
                # every type has a plain `text` field -- the superintendent's
                # sheet is a register whose rows the CALLER resolves -- so the
                # check is that the fixture filled the record, and that
                # something it filled is visible wherever the type has such a
                # field at all.
                _flat = [f for s in legal_render.SCHEMAS[log_type]["sections"]
                         for f in (s.get("fields") or [])
                         if f[2] in ("text", "sentence", "name", "raw_name")]
                if _flat:
                    self.assertIn("Recorded value", _text(_render(doc)),
                                  "no declared field reached the page")


if __name__ == "__main__":
    unittest.main(verbosity=2)
