"""The deploy gate's own logic.

A gate nobody tested is a gate nobody can rely on, and this one exists because
the last three signals all read green through a total outage of the
authenticated API. The single most important assertion in this file is
test_login_200_and_me_500_FAILS: that is 2026-08-31 exactly, and any check that
passes it is worthless.
"""

import os
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))

from postdeploy_login_check import evaluate, expectation_error  # noqa: E402

OK = dict(version_status=200, sha="a6536de1234567890", login_status=200,
          me_status=200, me_status_no_header=200)


class AHealthyDeployPasses(unittest.TestCase):
    def test_no_failures(self):
        self.assertEqual(evaluate(**OK), [])

    def test_matching_expected_sha_passes(self):
        self.assertEqual(evaluate(**OK, expect_sha="a6536de"), [])

    def test_full_sha_against_short_passes_either_direction(self):
        self.assertEqual(
            evaluate(**dict(OK, sha="a6536de"), expect_sha="a6536de1234567890"),
            [])


class TheOutageThisWasBuiltFor(unittest.TestCase):
    def test_login_200_and_me_500_FAILS(self):
        """2026-08-31. THE ASSERTION THAT MATTERS.

        POST /auth/login returned 200 all day. A gate that stops there passes
        while every authenticated request in the product is failing.
        """
        failures = evaluate(**dict(OK, me_status=500))
        self.assertEqual(len(failures), 1)
        self.assertIn("/api/auth/me", failures[0])

    def test_the_message_explains_the_symptom_not_just_the_code(self):
        """Whoever reads this at 7am needs to connect a 500 on /auth/me to the
        words the operator will use, which are "I cannot log in"."""
        msg = evaluate(**dict(OK, me_status=500))[0]
        self.assertIn("Login Failed", msg)
        self.assertIn("login succeeds", msg)

    def test_a_healthy_version_endpoint_does_NOT_rescue_it(self):
        """/api/version was 200 throughout the outage."""
        self.assertTrue(evaluate(**dict(OK, version_status=200, me_status=500)))


class EachHalfIsChecked(unittest.TestCase):
    def test_login_failure_is_caught(self):
        self.assertTrue(any("auth/login" in f
                            for f in evaluate(**dict(OK, login_status=500))))

    def test_login_401_is_caught(self):
        """Wrong credentials in the secret store must fail the gate, not pass
        it quietly."""
        self.assertTrue(evaluate(**dict(OK, login_status=401)))

    def test_the_NO_HEADER_path_is_checked_too(self):
        """The defect lived in the gap between the two. A repair to one path
        must not be allowed to break the other."""
        self.assertTrue(any("WITHOUT" in f
                            for f in evaluate(**dict(OK, me_status_no_header=500))))

    def test_both_halves_can_fail_together(self):
        self.assertEqual(len(evaluate(**dict(OK, me_status=500,
                                             me_status_no_header=500))), 2)


class TheDeployMustActuallyHaveLanded(unittest.TestCase):
    def test_a_mismatched_sha_FAILS(self):
        """The rollback state: the service is healthy, serving old code. Every
        other assertion passes and the deploy still did not happen."""
        failures = evaluate(**OK, expect_sha="deadbeef")
        self.assertEqual(len(failures), 1)
        self.assertIn("did not land", failures[0])

    def test_no_expected_sha_means_no_sha_assertion(self):
        self.assertEqual(evaluate(**OK), [])

    def test_a_missing_sha_is_reported(self):
        self.assertTrue(any("no commit sha" in f
                            for f in evaluate(**dict(OK, sha=""))))

    def test_version_endpoint_down_is_reported(self):
        self.assertTrue(any("/api/version" in f
                            for f in evaluate(**dict(OK, version_status=502))))


class UnreachableIsNotHealthy(unittest.TestCase):
    def test_status_zero_everywhere_fails(self):
        """DNS/TLS/timeout are reported as 0 by the shell. A gate that treats
        "no answer" as anything but a failure is worse than no gate."""
        failures = evaluate(version_status=0, sha="", login_status=0,
                            me_status=0, me_status_no_header=0)
        self.assertGreaterEqual(len(failures), 3)


class AnEmptyExpectedShaFailsLoudly(unittest.TestCase):
    def test_required_and_empty_is_an_error(self):
        self.assertIsNotNone(expectation_error(None, True))
        self.assertIsNotNone(expectation_error("", True))

    def test_required_with_a_sha_passes(self):
        self.assertIsNone(expectation_error("abc1234", True))

    def test_not_required_keeps_the_manual_behaviour(self):
        self.assertIsNone(expectation_error(None, False))


class TheWaitStepNeverMatchesAnEmptyAnswer(unittest.TestCase):
    """The 2026-11-04 miss: a 502 gives LIVE='', and case "$WANT" in "$LIVE"*)
    matches every WANT when LIVE is empty, so the wait step passed with no
    deployed SHA and the sign-in ran against a half-deployed API."""

    @classmethod
    def setUpClass(cls):
        wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "postdeploy-login-check.yml"
        cls.text = wf.read_text(encoding="utf-8")

    def test_the_comparison_is_only_reached_for_a_non_empty_live_sha(self):
        self.assertIn('if [ -n "$LIVE" ]; then', self.text)
        self.assertLess(self.text.index('if [ -n "$LIVE" ]; then'),
                        self.text.index('"$LIVE"*) echo "deployed='))

    def test_an_empty_expected_sha_stops_the_wait_step(self):
        self.assertIn('if [ -z "$WANT" ]; then', self.text)

    def test_the_sign_in_step_requires_an_expected_sha(self):
        self.assertIn('REQUIRE_EXPECT_SHA: "1"', self.text)

    def test_the_wait_is_ten_minutes(self):
        self.assertIn("seq 1 40", self.text)
        self.assertIn("sleep 15", self.text)


class ItLeaksNothing(unittest.TestCase):
    def test_no_secret_is_ever_formatted_into_a_message(self):
        """evaluate() is handed statuses and a sha -- never the password, the
        token, or a response body. Enforced by its signature."""
        import inspect
        params = set(inspect.signature(evaluate).parameters)
        for forbidden in ("password", "token", "body", "email", "secret"):
            self.assertNotIn(forbidden, params)


if __name__ == "__main__":
    unittest.main()
