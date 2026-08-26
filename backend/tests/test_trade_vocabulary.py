"""Trade is a controlled vocabulary, and nothing stored is rewritten.

THE DEFECT. The list existed TWICE -- DEFAULT_TRADES in server.py and
TRADE_SUGGESTIONS in app/project/[id]/trades.jsx, twenty identical strings --
and NEITHER validated anything. TradeAssignment.trade was a bare `str`, the
admin's control was a plain TextInput, and the suggestion dropdown only filled
it in. So "Framers" reached production, which is in neither list, while the
header comment on that screen claimed "No free-text" directly above the
free-text field.

THE RULE THIS FILE PROTECTS, and it is the one that costs the most to get
wrong:

    ** A PUBLISHED LABEL IS IMMUTABLE. **

A filed subcontractor_orientation holds `data.worker_trade` as a plain English
string forever, and nothing joins on it. Re-spelling "Concrete / Cement" to
"Concrete" would orphan every record carrying the old text -- silently. So
superseded labels are DEPRECATED (valid on existing rows, hidden from the
picker) and never edited.

Migration writes ONE field: trade_source. No trade string changes, ever.

    python backend/tests/test_trade_vocabulary.py
"""

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

import server  # noqa: E402

SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"


class TheVocabulary(unittest.TestCase):

    def test_it_exists_and_is_a_list_of_strings(self):
        self.assertIsInstance(server.TRADE_VOCABULARY, list)
        for t in server.TRADE_VOCABULARY:
            self.assertIsInstance(t, str)
            self.assertEqual(t, t.strip(), f"{t!r} has surrounding whitespace")
            self.assertTrue(t, "an empty label is not a trade")

    def test_the_operator_ruled_entries_are_all_present(self):
        """The list verbatim. A label added or dropped by anyone other than the
        operator shows up here as a diff, not as a silent change to what an
        admin can pick."""
        self.assertEqual(server.TRADE_VOCABULARY, [
            "Concrete", "Formwork", "Excavation", "Masonry", "Steel / Ironwork",
            "Framing", "Drywall", "Roofing", "Waterproofing", "Plumber",
            "Water Main", "Electrical", "HVAC / Mechanical", "Sprinkler",
            "Fire Protection", "Elevator", "Glazing", "Painting", "Flooring",
            "Demolition", "Abatement", "Scaffolding", "Surveying", "Safety",
            "Cleaning",
        ])

    def test_no_duplicates_under_the_match_rule(self):
        """Two labels differing only in case would make _trade_source
        ambiguous and offer the admin the same trade twice."""
        keys = [server._roster_key(t) for t in server.TRADE_VOCABULARY]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_separations_the_operator_ruled_are_kept(self):
        """Formwork is a distinct crew from Concrete (always the foundation
        company); Plumber and Water Main are never the same crew in NYC.
        Merging either later is a ruling, not a tidy-up."""
        for a, b in [("Concrete", "Formwork"), ("Plumber", "Water Main")]:
            self.assertIn(a, server.TRADE_VOCABULARY)
            self.assertIn(b, server.TRADE_VOCABULARY)

    def test_the_ruled_out_entries_are_absent(self):
        for t in ("General Contractor", "Landscaping"):
            self.assertNotIn(t, server.TRADE_VOCABULARY)


class DeprecationNotRespelling(unittest.TestCase):
    """The immutability rule, enforced."""

    def test_the_deprecated_labels_are_the_ruled_four(self):
        self.assertEqual(dict(server.DEPRECATED_TRADES), {
            "Concrete / Cement": "Concrete",
            "Framers": "Framing",
            "Electrician": "Electrical",
            "Carpentry": "Framing",
        })

    def test_a_deprecated_label_is_never_also_active(self):
        """If it were in both, "hidden from the picker" and "offered in the
        picker" would be true at once."""
        active = {server._roster_key(t) for t in server.TRADE_VOCABULARY}
        for old in server.DEPRECATED_TRADES:
            self.assertNotIn(server._roster_key(old), active)

    def test_every_supersedes_target_is_a_real_active_label(self):
        """A deprecation pointing at nothing is a dangling note."""
        for old, new in server.DEPRECATED_TRADES.items():
            self.assertIn(new, server.TRADE_VOCABULARY, f"{old} -> {new}")

    def test_a_deprecated_label_still_counts_as_vocabulary(self):
        """IT WAS PUBLISHED. A row carrying it is history, not an admin's
        off-list improvisation, and flagging it custom would tell an admin to
        fix something that is already correct."""
        for old in server.DEPRECATED_TRADES:
            self.assertEqual(server._trade_source(old), "vocabulary", old)

    def test_the_immutability_rule_is_stated_in_the_source(self):
        """The reason has to travel with the list. Someone tidying
        "Concrete / Cement" into "Concrete" is doing the obvious thing."""
        i = SRC.index("TRADE_VOCABULARY: List[str] = [")
        header = SRC[max(0, i - 2500):i]
        self.assertIn("IMMUTABLE", header)
        self.assertIn("orphan", header)


class TheSourcePredicate(unittest.TestCase):

    def test_a_vocabulary_label_is_vocabulary(self):
        self.assertEqual(server._trade_source("Framing"), "vocabulary")

    def test_an_unknown_string_is_custom(self):
        self.assertEqual(server._trade_source("Bricklayer"), "custom")

    def test_it_normalises_case_and_whitespace(self):
        """_roster_key is the project's ONE match rule -- strip + casefold --
        already mirrored by rosterKey() in checkin.html. A case-only edit must
        not turn a vocabulary row into a custom one."""
        for variant in ("framing", "FRAMING", "  Framing  ", "\tframing\n"):
            self.assertEqual(server._trade_source(variant), "vocabulary", repr(variant))

    def test_empty_and_none_are_custom_not_a_crash(self):
        for v in (None, "", "   "):
            self.assertEqual(server._trade_source(v), "custom", repr(v))

    def test_the_old_default_trades_list_is_gone(self):
        """ONE SOURCE OF TRUTH. DEFAULT_TRADES was the server half of the
        duplicate."""
        self.assertFalse(hasattr(server, "DEFAULT_TRADES"))
        # A DECLARATION, not the word. The comments explaining why the
        # duplicate was removed name it, and asserting on a bare substring
        # matched that prose -- the same trap this project has hit repeatedly:
        # a source assertion matching an explanation ABOUT the thing instead of
        # the thing.
        self.assertIsNone(re.search(r"^DEFAULT_TRADES\s*[:=]", SRC, re.M))


class NothingStoredIsRewritten(unittest.TestCase):
    """The strongest form of the rule, and it costs nothing to honour."""

    def test_a_custom_trade_keeps_its_exact_bytes(self):
        rows = server._merge_trade_assignments(
            [], [{"trade": "Framers Local 157", "company": "Arkon"}])
        self.assertEqual(rows[0]["trade"], "Framers Local 157")
        self.assertEqual(rows[0]["trade_source"], "custom")

    def test_a_deprecated_trade_keeps_its_exact_bytes(self):
        """NOT rewritten to its successor. This is the whole immutability
        rule in one assertion: 'Framers' does not become 'Framing'."""
        rows = server._merge_trade_assignments(
            [], [{"trade": "Framers", "company": "Arkon"}])
        self.assertEqual(rows[0]["trade"], "Framers")
        self.assertEqual(rows[0]["trade_source"], "vocabulary")

    def test_a_case_variant_keeps_its_exact_bytes(self):
        """Matched on the normalised key, stored raw."""
        rows = server._merge_trade_assignments(
            [], [{"trade": "framing", "company": "Arkon"}])
        self.assertEqual(rows[0]["trade"], "framing")
        self.assertEqual(rows[0]["trade_source"], "vocabulary")

    def test_the_flag_is_stamped_on_every_active_row(self):
        rows = server._merge_trade_assignments([], [
            {"trade": "Concrete", "company": "A"},
            {"trade": "Bricklayer", "company": "B"},
        ])
        self.assertEqual([r["trade_source"] for r in rows], ["vocabulary", "custom"])

    def test_soft_deleted_rows_are_stamped_too(self):
        """A row carried forward inactive is still a roster row, and a later
        reactivation must not find it unlabelled."""
        existing = [{"trade": "Concrete", "company": "A", "id": "r1"}]
        rows = server._merge_trade_assignments(existing, [])
        self.assertEqual(rows[0]["status"], "inactive")
        self.assertEqual(rows[0]["trade_source"], "vocabulary")

    def test_trade_source_is_derived_not_accepted_from_the_client(self):
        """It is a statement about the vocabulary, not a field an admin owns.
        A client claiming 'vocabulary' for an invented trade must not be
        believed."""
        rows = server._merge_trade_assignments(
            [], [{"trade": "Bricklayer", "company": "B", "trade_source": "vocabulary"}])
        self.assertEqual(rows[0]["trade_source"], "custom")

    def test_the_company_is_never_touched(self):
        rows = server._merge_trade_assignments(
            [], [{"trade": "Concrete", "company": "  Vanguard Ltd  "}])
        self.assertEqual(rows[0]["company"], "Vanguard Ltd")


class TheEndpoint(unittest.TestCase):

    def _call(self):
        import asyncio
        return asyncio.run(server.get_trade_vocabulary(current_user={"id": "u1"}))

    def test_it_is_mounted(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertIn("/api/trades/vocabulary", paths)

    def test_it_returns_the_active_list(self):
        self.assertEqual(self._call()["trades"], server.TRADE_VOCABULARY)

    def test_it_returns_deprecated_SEPARATELY(self):
        """Merged into one list, the picker would offer a label that must never
        be chosen again. Separate, the client can hide them and still render a
        row that holds one as a normal value."""
        out = self._call()
        self.assertEqual(out["deprecated"], dict(server.DEPRECATED_TRADES))
        for old in server.DEPRECATED_TRADES:
            self.assertNotIn(old, out["trades"])

    def test_it_returns_copies_not_the_module_lists(self):
        """A caller mutating the response must not edit the vocabulary."""
        out = self._call()
        out["trades"].append("Injected")
        self.assertNotIn("Injected", server.TRADE_VOCABULARY)

    def test_the_gate_does_not_call_it(self):
        """OUT OF SCOPE, RULED, and pinned. A worker's pick is validated
        against the project roster by _roster_key; a vocabulary check there
        would be a new way to refuse a man at a turnstile."""
        checkin_html = (Path(__file__).resolve().parent.parent / "checkin.html").read_text(
            encoding="utf-8")
        self.assertNotIn("trades/vocabulary", checkin_html)


class TheDeadEndpointIsGone(unittest.TestCase):

    def test_the_route_is_unmounted(self):
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertNotIn("/api/checkin/{project_id}/companies", paths)

    def test_the_handler_is_gone_too(self):
        """A decorator removed while the function survives leaves a reachable
        name and a confusing grep."""
        self.assertFalse(hasattr(server, "get_project_companies"))

    def test_checkin_html_no_longer_carries_its_vestige(self):
        checkin_html = (Path(__file__).resolve().parent.parent / "checkin.html").read_text(
            encoding="utf-8")
        self.assertIsNone(re.search(r"^let companies = \[\];", checkin_html, re.M))

    def test_the_endpoint_the_gate_ACTUALLY_reads_is_untouched(self):
        """The deletion must not have taken the live one with it."""
        paths = {getattr(r, "path", "") for r in server.app.routes}
        self.assertIn("/api/checkin/{project_id}/{tag_id}/info", paths)


class OneSourceOfTruth(unittest.TestCase):
    """The duplicate is what let the two lists validate nothing between them."""

    def test_the_client_carries_no_copy_of_the_list(self):
        """Asserted by looking for the LABELS, not for the old identifier. A
        renamed constant holding the same twenty strings is the same defect."""
        screen = (FRONTEND / "app" / "project" / "[id]" / "trades.jsx").read_text(
            encoding="utf-8")
        body = re.sub(r"/\*[\s\S]*?\*/", "", screen)
        body = re.sub(r"(?<!:)//.*$", "", body, flags=re.M)
        hits = [t for t in server.TRADE_VOCABULARY if f"'{t}'" in body or f'"{t}"' in body]
        self.assertEqual(hits, [], f"the screen hardcodes vocabulary labels: {hits}")

    def test_the_old_suggestion_constant_is_gone(self):
        screen = (FRONTEND / "app" / "project" / "[id]" / "trades.jsx").read_text(
            encoding="utf-8")
        self.assertNotIn("const TRADE_SUGGESTIONS", screen)

    def test_no_other_frontend_file_hardcodes_the_list(self):
        """A copy that moved to a neighbouring file is still a copy."""
        marker = "Steel / Ironwork"
        offenders = []
        for path in list(FRONTEND.glob("app/**/*.jsx")) + list(FRONTEND.glob("src/**/*.js")):
            if ".test." in path.name:
                continue
            if marker in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(FRONTEND)))
        self.assertEqual(offenders, [])

    def test_the_client_fetches_it(self):
        api = (FRONTEND / "src" / "utils" / "api.js").read_text(encoding="utf-8")
        self.assertIn("/api/trades/vocabulary", api)


class TheBackfillIsTheOperatorsCall(unittest.TestCase):
    """The convention this repo already set, in test_roster_ids_on_create:
    "The backfill is the operator's call, and this pins that the code does not
    quietly make it for him.\""""

    def test_no_automatic_backfill_on_startup(self):
        for name in ("create_indexes", "startup_event", "lifespan"):
            if name not in SRC:
                continue
            i = SRC.index(f"def {name}")
            body = SRC[i:i + 6000]
            # ANCHORED, per test_absence_literals_are_specific: a bare
            # "trade_source" bans a word, not a construct. What must not exist
            # is a WRITE of the field -- as a dict key in a $set, or as an
            # attribute assignment.
            self.assertIsNone(
                re.search(r"""["']trade_source["']\s*:|\.trade_source\s*=""", body),
                f"{name} quietly backfills trade_source")

    def test_the_script_exists_and_defaults_to_a_dry_run(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "backfill_trade_source.py"
        self.assertTrue(script.exists())
        body = script.read_text(encoding="utf-8")
        self.assertIn('"--apply"', body)
        self.assertIn("DRY RUN", body)

    def test_the_script_never_writes_a_trade(self):
        """It sets trade_source and nothing else. A migration that edited a
        stored trade would orphan filed records."""
        script = Path(__file__).resolve().parent.parent / "scripts" / "backfill_trade_source.py"
        body = script.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r'row\["trade"\]\s*=', body))
        self.assertIsNone(re.search(r'row\["company"\]\s*=', body))
        self.assertIn('row["trade_source"] = source', body)

    def test_the_scripts_match_rule_agrees_with_the_servers(self):
        """It duplicates _roster_key deliberately -- importing server would boot
        the app -- so the two are checked against each other here."""
        script = Path(__file__).resolve().parent.parent / "scripts" / "backfill_trade_source.py"
        body = script.read_text(encoding="utf-8")
        self.assertIn('return str(value or "").strip().casefold()', body)
        i = SRC.index("def _roster_key")
        self.assertIn('return str(value or "").strip().casefold()', SRC[i:i + 900])


if __name__ == "__main__":
    unittest.main(verbosity=2)
