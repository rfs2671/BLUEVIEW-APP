"""THE REQUIRED-LOG SET, RESOLVED FROM THE PROJECT.

The approved model, and the one place it now lives (LOGBOOK_TYPE_REGISTRY):

  DAILY, ALWAYS      daily_jobsite · preshift_signin · osha_log
  WEEKLY             toolbox_talk
  PER WORKER, ONCE   subcontractor_orientation
  TOGGLED, off       scaffold_maintenance · crane_operations ·
                     excavation_monitoring · hot_work
  MAJOR ONLY         concrete_operations · ssc_daily_safety_log

WHAT THIS FILE IS FOR, and it is not "the list has the right strings in it".

  1. THE TWO MAJOR-BUILDING LOGS MUST NOT APPEAR ON A NON-MAJOR PROJECT.
     Asserted directly, on every surface that resolves a set — not inferred
     from a filter existing somewhere in the source.

  2. BLANK FAILS CLOSED. classify_project used to answer "regular" for a
     project nobody had measured, so NEVER ASSESSED and MEASURED AND FOUND
     NON-MAJOR were one value in one field. The consequence is asymmetric:
     that default REMOVES two required logs, and a missing obligation on a
     compliance record is invisible in the way an extra one is not.

  3. ONE MODEL. The registry declared `conditional` keys that nothing read
     while get_required_logbooks hand-built the list from different rules. They
     disagreed on every conditional type, and crane_operations appeared in NO
     required set on ANY project — it was unreachable by construction.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("QWEN_API_KEY", "")

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

import server as S  # noqa: E402
from tests.source_text import code_of  # noqa: E402

_CODE = code_of("server.py")

DAILY_THREE = {"daily_jobsite", "preshift_signin", "osha_log"}
MAJOR_ONLY = {"concrete_operations", "ssc_daily_safety_log"}
TOGGLED = {
    "scaffold_maintenance": "scaffold_erected",
    "crane_operations": "crane_on_site",
    "excavation_monitoring": "excavation_active",
    "hot_work": "hot_work_permitted",
    # Work at height is a site condition the CP can see, so it toggles like the
    # scaffold. A foundation crew at grade has no fall exposure, and a daily
    # fall-protection log on that day is a record of nothing.
    "fall_protection": "fall_protection_active",
    # THE CS LOG TOGGLES TOO, and by an ADMIN rather than the CP -- assigning a
    # construction superintendent is an administrative act, not a site
    # condition the CP observes.
    #
    # It is toggled rather than always-required because registering the type
    # made it required on EVERY project the moment it existed, and the investor
    # report began counting a twelfth required log with no editor to file it.
    # Every project would have carried a permanent "not filed" deficiency for a
    # document nobody could produce -- the 285 false flags again. A project with
    # no superintendent is not in breach for having no superintendent log.
    "site_superintendent_log": "superintendent_log_active",
}
NON_MAJOR_CLASSES = ("regular",)
MAJOR_CLASSES = ("major_a", "major_b")


class TheModelIsTheRegistry(unittest.TestCase):
    """One declaration. A rule that lives in two places has already drifted."""

    def test_every_registry_key_is_a_real_log_type(self):
        keys = [e["key"] for e in S.LOGBOOK_TYPE_REGISTRY]
        self.assertEqual(sorted(keys), sorted(set(S.LOGBOOK_TIMING_CLASS)))

    def test_the_conditional_fields_are_the_approved_set(self):
        conds = {e["key"]: e.get("conditional") for e in S.LOGBOOK_TYPE_REGISTRY
                 if e.get("conditional")}
        self.assertEqual(conds, TOGGLED)

    def test_the_dead_conditional_keys_are_gone(self):
        """`has_crane_permit`, `has_excavation` and `building_stories_gte_5`
        were declared and read by nothing, while get_required_logbooks used a
        different rule for each — including `adjacent_to_occupied`, a field
        NOTHING in this codebase has ever written."""
        for dead in ("has_crane_permit", "has_excavation",
                     "building_stories_gte_5", "adjacent_to_occupied"):
            with self.subTest(field=dead):
                self.assertNotIn(dead, _CODE)

    def test_who_may_flip_each_toggle_is_declared(self):
        """The CP toggles what he can SEE on site. Hot work rests on an FDNY
        permit and a certificate of fitness — paper the admin holds and this
        app has never seen — so declaring the work permitted is not the CP's
        act, even though filling the log is."""
        owners = {e["key"]: e.get("activated_by") for e in S.LOGBOOK_TYPE_REGISTRY
                  if e.get("conditional")}
        self.assertEqual(owners, {
            "scaffold_maintenance": "cp",
            "crane_operations": "cp",
            "excavation_monitoring": "cp",
            "fall_protection": "cp",
            "hot_work": "admin",
            # ADMIN, like hot work and for the same kind of reason: assigning a
            # construction superintendent to a project is an administrative
            # act, not a site condition the CP can observe and toggle.
            "site_superintendent_log": "admin",
        })

    def test_only_conditional_types_declare_an_owner(self):
        """A log that is always required has nobody to activate it, and an
        `activated_by` on one would read as a toggle that does not exist."""
        for e in S.LOGBOOK_TYPE_REGISTRY:
            with self.subTest(key=e["key"]):
                if not e.get("conditional"):
                    self.assertIsNone(e.get("activated_by"))


class TheTwoMajorLogsNeverReachANonMajorProject(unittest.TestCase):
    """ASSERTED, not filtered-and-hoped. These are the two logs the operator
    reported as wrong for both live sites."""

    def test_neither_appears_for_a_non_major_class(self):
        for pclass in NON_MAJOR_CLASSES:
            for project in ({}, {"building_stories": 3},
                            {"scaffold_erected": True, "crane_on_site": True,
                             "excavation_active": True, "hot_work_permitted": True}):
                with self.subTest(pclass=pclass, project=project):
                    got = set(S.get_required_logbooks(pclass, project))
                    self.assertEqual(got & MAJOR_ONLY, set())

    def test_no_toggle_can_summon_them(self):
        """They are a building CLASSIFICATION, not a site condition. Setting
        every conditional field true — including ones they never carried —
        must not put either on a regular project."""
        every_flag = {v: True for v in TOGGLED.values()}
        every_flag.update({"building_stories": 40, "has_full_demolition": True,
                           "concrete_operations": True, "ssc_daily_safety_log": True})
        got = set(S.get_required_logbooks("regular", every_flag))
        self.assertEqual(got & MAJOR_ONLY, set())

    def test_both_appear_for_a_major_class(self):
        """The other half of the claim: they are removed because the class says
        so, not because they are broken."""
        for pclass in MAJOR_CLASSES:
            with self.subTest(pclass=pclass):
                self.assertTrue(MAJOR_ONLY <= set(S.get_required_logbooks(pclass, {})))

    def test_concrete_no_longer_waits_on_a_storey_count(self):
        """It was gated on >= 5 storeys, so a major building with no storey
        count recorded did not require the Concrete Safety Manager log."""
        self.assertIn("concrete_operations", S.get_required_logbooks("major_a", {}))


class BlankFailsClosed(unittest.TestCase):

    def test_classify_project_returns_None_when_nothing_was_measured(self):
        self.assertIsNone(S.classify_project(None, None, False, None, None))
        self.assertIsNone(S.classify_project(0, 0, False, 0, 0))

    def test_a_single_measurement_IS_an_assessment(self):
        for kwargs in ({"stories": 3}, {"footprint_sqft": 900},
                       {"building_height": 30}, {"demo_stories": 2}):
            with self.subTest(**kwargs):
                args = {"stories": None, "footprint_sqft": None, "full_demo": False,
                        "demo_stories": None, "building_height": None, **kwargs}
                self.assertEqual(S.classify_project(**args), "regular")

    def test_declaring_a_full_demolition_is_an_assessment_on_its_own(self):
        self.assertEqual(
            S.classify_project(None, None, True, None, None), "regular")

    def test_the_thresholds_are_unchanged(self):
        self.assertEqual(S.classify_project(20, None, False, None, None), "major_b")
        self.assertEqual(S.classify_project(11, None, False, None, None), "major_a")
        self.assertEqual(S.classify_project(3, None, False, None, None), "regular")

    def test_an_unassessed_project_gets_BOTH_major_logs(self):
        for pclass in (None, "", "unknown", "REGULAR"):
            with self.subTest(pclass=pclass):
                got = set(S.get_required_logbooks(pclass, {}))
                self.assertTrue(MAJOR_ONLY <= got,
                                "blank must fail CLOSED, never to non-major")

    def test_unassessed_is_NOT_the_same_answer_as_non_major(self):
        """The whole point. If these two agreed, the field would still be
        carrying one value for two different facts."""
        self.assertNotEqual(set(S.get_required_logbooks(None, {})),
                            set(S.get_required_logbooks("regular", {})))

    def test_classification_assessed_names_the_case(self):
        self.assertTrue(S.classification_assessed({"project_class": "regular"}))
        self.assertTrue(S.classification_assessed({"project_class": "major_b"}))
        for bad in ({}, {"project_class": None}, {"project_class": ""},
                    {"project_class": "nonsense"}, None):
            with self.subTest(project=bad):
                self.assertFalse(S.classification_assessed(bad))


class TheTogglesDecideTheConditionalFour(unittest.TestCase):

    def test_all_four_are_off_by_default(self):
        got = set(S.get_required_logbooks("regular", {}))
        self.assertEqual(got & set(TOGGLED), set())
        self.assertEqual(got, DAILY_THREE | {"toolbox_talk", "subcontractor_orientation"})

    def test_each_toggle_adds_exactly_its_own_log(self):
        for key, field in TOGGLED.items():
            with self.subTest(log=key):
                got = set(S.get_required_logbooks("regular", {field: True}))
                self.assertEqual(got & set(TOGGLED), {key})

    def test_a_toggle_applies_on_a_major_project_too(self):
        got = set(S.get_required_logbooks("major_a", {"crane_on_site": True}))
        self.assertIn("crane_operations", got)

    def test_a_toggle_applies_even_when_the_class_is_unknown(self):
        """A scaffold is up regardless of how many storeys anybody typed. The
        class gate and the condition gate are different kinds of fact."""
        self.assertIn("scaffold_maintenance",
                      S.get_required_logbooks(None, {"scaffold_erected": True}))

    def test_an_explicit_False_is_off(self):
        self.assertNotIn("crane_operations",
                         S.get_required_logbooks("regular", {"crane_on_site": False}))

    def test_crane_is_reachable_at_all(self):
        """It appeared in NO required set on ANY project: get_required_logbooks
        never appended it under any condition, so five ported forms were built
        and one of them could not be reached by any configuration."""
        self.assertIn("crane_operations",
                      S.get_required_logbooks("regular", {"crane_on_site": True}))

    def test_hot_work_is_no_longer_major_only(self):
        """Welding happens on regular sites. It was major-only, which is why it
        never appeared for the operator."""
        self.assertIn("hot_work",
                      S.get_required_logbooks("regular", {"hot_work_permitted": True}))


class TheDailySubsetComesFromTheRegistry(unittest.TestCase):
    """Four places were deciding "which types are due daily" and only one read
    the registry. A weekly log in a required set must never become a nightly
    missing-logbook alert."""

    def test_weekly_and_as_needed_are_not_daily(self):
        req = S.get_required_logbooks("regular", {})
        self.assertEqual(set(S.daily_required_logbooks(req)), DAILY_THREE)

    def test_toolbox_and_orientation_are_excluded_by_FREQUENCY(self):
        self.assertEqual(S.logbook_frequency("toolbox_talk"), "weekly")
        self.assertEqual(S.logbook_frequency("subcontractor_orientation"), "as_needed")
        self.assertEqual(S.logbook_frequency("hot_work"), "as_needed")

    def test_a_toggled_daily_log_IS_daily(self):
        req = S.get_required_logbooks("regular", {"scaffold_erected": True})
        self.assertIn("scaffold_maintenance", S.daily_required_logbooks(req))

    def test_hot_work_is_never_a_daily_deficiency(self):
        """It is as-needed: a site can hold a permit for a month and weld on
        three days of it."""
        req = S.get_required_logbooks("regular", {"hot_work_permitted": True})
        self.assertIn("hot_work", req)
        self.assertNotIn("hot_work", S.daily_required_logbooks(req))

    def test_an_unregistered_type_is_treated_as_daily(self):
        """Surfaced rather than silently exempted from every deadline."""
        self.assertEqual(S.logbook_frequency("something_new"), "daily")
        self.assertEqual(S.daily_required_logbooks(["something_new"]), ["something_new"])

    def test_the_nightly_check_uses_it(self):
        self.assertIn("daily_required = daily_required_logbooks(required)", _CODE)
        self.assertNotIn(
            'r not in ("subcontractor_orientation", "toolbox_talk")', _CODE)


class TheEndpointReportsBothTheSetAndTheDoubt(unittest.TestCase):
    """`/api/projects/{id}/required-logbooks` is what the CP screen asks, so it
    is the surface the fail-closed decision actually reaches a person through.
    The set alone is not enough: two extra logs with no reason given read as
    the app being wrong about his site."""

    def _get(self, project):
        # AUTHORIZATION IS NOT WHAT THIS FILE TESTS, and the fixture used to
        # depend on it being broken. It passed `current_user={}` -- a caller
        # with NO company_id -- which reached the payload only because the
        # tenancy check was `if company_id and ...` and short-circuited on a
        # falsy company. The route now fails closed, so the fixture supplies a
        # caller who legitimately has access and these assertions stay about
        # the classification payload.
        scoped = None
        if project is not None:
            scoped = dict(project)
            scoped.setdefault("company_id", "c1")

        class _Projects:
            async def find_one(self, *a, **k):
                return dict(scoped) if scoped is not None else None

        class _DB:
            projects = _Projects()

        with patch.object(S, "db", _DB()),              patch.object(S, "to_query_id", lambda x: x):
            return asyncio.run(S.get_project_required_logbooks(
                "p1", current_user={"company_id": "c1"}))

    def test_an_assessed_non_major_project_says_so_and_drops_both(self):
        out = self._get({"_id": "p1", "project_class": "regular"})
        self.assertIs(out["classification_assessed"], True)
        self.assertEqual(set(out["required_logbooks"]) & MAJOR_ONLY, set())

    def test_an_unassessed_project_says_so_and_keeps_both(self):
        out = self._get({"_id": "p1"})
        self.assertIs(out["classification_assessed"], False)
        self.assertTrue(MAJOR_ONLY <= set(out["required_logbooks"]))

    def test_the_flag_tracks_the_class_rather_than_being_hardcoded(self):
        for pclass, expected in (("regular", True), ("major_a", True),
                                 ("major_b", True), (None, False),
                                 ("", False), ("nonsense", False)):
            with self.subTest(project_class=pclass):
                out = self._get({"_id": "p1", "project_class": pclass})
                self.assertIs(out["classification_assessed"], expected)

    def test_a_missing_class_is_reported_as_missing_not_as_regular(self):
        """The read used to substitute "regular" for an absent class — the same
        silent default classify_project stopped making, one layer out."""
        self.assertIsNone(self._get({"_id": "p1"})["project_class"])

    def test_the_payload_carries_the_toggles_and_their_state(self):
        """One request, so the control and the list beside it cannot disagree."""
        out = self._get({"_id": "p1", "project_class": "regular",
                         "excavation_active": True})
        by_type = {a["log_type"]: a for a in out["activations"]}
        self.assertEqual(set(by_type), set(TOGGLED))
        self.assertIs(by_type["excavation_monitoring"]["active"], True)
        self.assertIs(by_type["crane_operations"]["active"], False)
        self.assertEqual(by_type["hot_work"]["activated_by"], "admin")

    def test_a_toggle_shows_up_in_the_payload(self):
        out = self._get({"_id": "p1", "project_class": "regular",
                         "crane_on_site": True})
        self.assertIn("crane_operations", out["required_logbooks"])


class TheStoredSetIsRefreshedWhenAToggleMoves(unittest.TestCase):
    """`required_logbooks` on the project is a CACHE, and it had two writers:
    project create, and project update when a CLASSIFICATION field changed. A
    toggle is neither — so the scaffold went up, the CP filed scaffold logs,
    and the daily report's compliance line never counted one because the cache
    still held the set computed at project creation."""

    def _refresh(self, project):
        saved = {}

        class _Projects:
            async def find_one(self, *a, **k):
                return dict(project)

            async def update_one(self, q, update):
                saved.update(update["$set"])

        class _DB:
            projects = _Projects()

        with patch.object(S, "db", _DB()),              patch.object(S, "to_query_id", lambda x: x):
            returned = asyncio.run(S._refresh_required_logbooks("p1"))
        return returned, saved

    def test_flipping_a_toggle_rewrites_the_stored_set(self):
        returned, saved = self._refresh({
            "_id": "p1", "project_class": "regular", "scaffold_erected": True,
            "required_logbooks": ["daily_jobsite"],
        })
        self.assertIn("scaffold_maintenance", saved["required_logbooks"])
        self.assertEqual(returned, saved["required_logbooks"])

    def test_turning_it_off_removes_it_again(self):
        _, saved = self._refresh({
            "_id": "p1", "project_class": "regular", "scaffold_erected": False,
            "required_logbooks": ["daily_jobsite", "scaffold_maintenance"],
        })
        self.assertNotIn("scaffold_maintenance", saved["required_logbooks"])

    def test_it_writes_only_the_cached_field(self):
        """The point is that recomputing a CACHE must not rewrite project DATA
        — a refresh that also touched project_class or a toggle could undo the
        very change that triggered it.

        `updated_at` is not project data; it is the document's change marker,
        and this helper now stamps it itself rather than inheriting one from
        whichever caller happened to bump it first. That ordering luck was the
        bug: this write changes WHICH COMPLIANCE LOGS A PROJECT MUST FILE, and
        a caller that did not pre-stamp would have moved it behind a timestamp
        nobody updated. See test_writers_stamp_updated_at.py."""
        _, saved = self._refresh({"_id": "p1", "project_class": "regular"})
        self.assertEqual(set(saved), {"required_logbooks", "updated_at"})

    def test_the_scaffold_write_path_calls_it(self):
        fn = _CODE[_CODE.index("async def update_scaffold_info"):]
        fn = fn[:fn.index("Scaffold info saved")]
        self.assertIn("await _refresh_required_logbooks(project_id)", fn)


class TheActivationsAreReadOffTheRegistry(unittest.TestCase):
    """The screen renders one row per conditional type from this, so a fifth
    one added to the registry appears with no client change."""

    def test_one_entry_per_conditional_type_and_no_others(self):
        acts = S.logbook_activations({})
        self.assertEqual({a["log_type"] for a in acts}, set(TOGGLED))

    def test_each_names_its_field_and_its_owner(self):
        by_type = {a["log_type"]: a for a in S.logbook_activations({})}
        for log_type, field in TOGGLED.items():
            with self.subTest(log=log_type):
                self.assertEqual(by_type[log_type]["field"], field)
        self.assertEqual(by_type["hot_work"]["activated_by"], "admin")
        for cp_owned in ("scaffold_maintenance", "crane_operations",
                         "excavation_monitoring", "fall_protection"):
            self.assertEqual(by_type[cp_owned]["activated_by"], "cp")

    def test_active_tracks_the_project_field(self):
        acts = {a["log_type"]: a["active"]
                for a in S.logbook_activations({"crane_on_site": True})}
        self.assertIs(acts["crane_operations"], True)
        self.assertIs(acts["scaffold_maintenance"], False)

    def test_a_label_comes_along_so_the_client_invents_no_wording(self):
        by_type = {a["log_type"]: a for a in S.logbook_activations({})}
        self.assertEqual(by_type["hot_work"]["label"], "Hot Work Permit Log")


class OnlyTheRightPersonMayFlipIt(unittest.TestCase):
    """ENFORCED SERVER-SIDE. Hiding the control on the client is a courtesy;
    the request still exists, and a CP declaring hot work permitted would be
    asserting an FDNY permit and a certificate of fitness that this app has
    never seen."""

    def _call(self, log_type, active, role="cp", project=None, omit_state=False):
        state = {"doc": dict(project if project is not None
                             else {"_id": "p1", "project_class": "regular"}),
                 "audit": []}

        class _Projects:
            async def find_one(self, *a, **k):
                return dict(state["doc"])

            async def update_one(self, q, update):
                state["doc"].update(update["$set"])

        class _Audit:
            async def insert_one(self, doc):
                state["audit"].append(doc)

        class _DB:
            projects = _Projects()
            audit_logs = _Audit()

        body = {"log_type": log_type}
        if not omit_state:
            body["active"] = active
        with patch.object(S, "db", _DB()), \
             patch.object(S, "to_query_id", lambda x: x):
            out = asyncio.run(S.set_logbook_activation(
                "p1", body, current_user={"id": "u1", "role": role}))
        return out, state

    def test_a_cp_may_switch_on_what_he_can_see(self):
        for log_type in ("scaffold_maintenance", "crane_operations",
                         "excavation_monitoring", "fall_protection"):
            with self.subTest(log=log_type):
                out, state = self._call(log_type, True)
                self.assertIs(out["active"], True)
                self.assertIs(state["doc"][TOGGLED[log_type]], True)
                self.assertIn(log_type, out["required_logbooks"])

    def test_a_cp_may_NOT_switch_on_hot_work(self):
        with self.assertRaises(S.HTTPException) as cm:
            self._call("hot_work", True, role="cp")
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(cm.exception.detail["code"], "ACTIVATION_REQUIRES_ADMIN")

    def test_an_admin_may(self):
        for role in ("admin", "owner"):
            with self.subTest(role=role):
                out, state = self._call("hot_work", True, role=role)
                self.assertIs(state["doc"]["hot_work_permitted"], True)
                self.assertIn("hot_work", out["required_logbooks"])

    def test_the_refusal_writes_nothing_at_all(self):
        """A 403 that had already flipped the field would be a guard in name."""
        captured = {}

        class _Projects:
            async def find_one(self, *a, **k):
                return {"_id": "p1", "project_class": "regular"}

            async def update_one(self, q, update):
                captured["wrote"] = update

        class _DB:
            projects = _Projects()

        with patch.object(S, "db", _DB()), \
             patch.object(S, "to_query_id", lambda x: x):
            with self.assertRaises(S.HTTPException):
                asyncio.run(S.set_logbook_activation(
                    "p1", {"log_type": "hot_work", "active": True},
                    current_user={"id": "u1", "role": "cp"}))
        self.assertEqual(captured, {})

    def test_switching_off_removes_it_from_the_required_set(self):
        out, state = self._call(
            "scaffold_maintenance", False,
            project={"_id": "p1", "project_class": "regular", "scaffold_erected": True})
        self.assertIs(state["doc"]["scaffold_erected"], False)
        self.assertNotIn("scaffold_maintenance", out["required_logbooks"])

    def test_a_type_with_no_toggle_is_refused(self):
        for log_type in ("daily_jobsite", "concrete_operations", "nonsense", ""):
            with self.subTest(log=log_type):
                with self.assertRaises(S.HTTPException) as cm:
                    self._call(log_type, True, role="owner")
                self.assertEqual(cm.exception.status_code, 400)
                self.assertEqual(cm.exception.detail["code"], "LOGBOOK_NOT_ACTIVATABLE")

    def test_a_missing_state_is_refused_rather_than_read_as_OFF(self):
        """Coercing an absent key to False would turn a malformed request into
        a silent switch-off of a required compliance log."""
        with self.assertRaises(S.HTTPException) as cm:
            self._call("crane_operations", None, omit_state=True)
        self.assertEqual(cm.exception.detail["code"], "ACTIVATION_STATE_REQUIRED")

    def test_a_non_boolean_state_is_refused(self):
        for bad in ("true", 1, 0, [], {}, None):
            with self.subTest(active=bad):
                with self.assertRaises(S.HTTPException) as cm:
                    self._call("crane_operations", bad)
                self.assertEqual(cm.exception.detail["code"], "ACTIVATION_STATE_REQUIRED")

    def test_the_flip_is_audited(self):
        _, state = self._call("crane_operations", True)
        self.assertEqual(len(state["audit"]), 1)
        entry = state["audit"][0]
        self.assertEqual(entry["action"], "logbook_activation")
        self.assertEqual(entry["details"],
                         {"log_type": "crane_operations", "field": "crane_on_site",
                          "active": True})

    def test_the_stored_required_set_is_rewritten_in_the_same_call(self):
        _, state = self._call("crane_operations", True)
        self.assertIn("crane_operations", state["doc"]["required_logbooks"])


class TheCitationsNameTheRightSection(unittest.TestCase):

    def _ref(self, key):
        return next(e for e in S.LOGBOOK_TYPE_REGISTRY
                    if e["key"] == key)["dob_reference"]

    def test_concrete_carries_the_CONCRETE_SAFETY_MANAGERS_sections(self):
        """It carried §3310.4 — the SITE SAFETY COORDINATOR's section, which is
        the SSC log's citation, sitting on the CSM's log. Nothing renders
        dob_reference today, and that is exactly why it was worth fixing: a
        wrong citation in a registry is the kind of thing that gets rendered
        later and believed."""
        self.assertEqual(self._ref("concrete_operations"), "§3310.10 / §3315")

    def test_and_it_is_no_longer_the_SSCs(self):
        self.assertNotEqual(self._ref("concrete_operations"),
                            self._ref("ssc_daily_safety_log"))


if __name__ == "__main__":
    unittest.main()
