"""The retired model, and the status code the report trace used to withhold.

gemini-2.5-flash-lite was retired under this key. Every call returned
404 NOT_FOUND — "no longer available to new users. Please update your code to
use models/gemini-3.5-flash-lite" — and the report printed `failed: ClientError`
for all three crews, identically, for a day. A class name that is equally true
of a retired model, a revoked key, a malformed request and an exhausted quota.

TWO THINGS ARE PINNED HERE, and the second matters more than the first.

  1. The default model, in BOTH live call sites, which must not drift apart.
     GEMINI_MODEL is unset in production (checked 2026-08-28), so the default
     IS the live value — there is no override to hide behind.

  2. What the trace may and may not say. `.code` is an int off the HTTP
     response and `.status` is a fixed enum token; neither can carry an
     identifier. `str(e)` interpolates the SERVER'S OWN BODY, which can carry a
     request id, a URL or a fragment of the payload — and this string is
     RENDERED into an admin page. The refusal to print the message stays; the
     status is what should have been there all along.

The leak assertions use a real error carrying a real message, so they fail if
someone later "improves" the trace by adding `{e}`.
"""

import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from google.genai import errors  # noqa: E402

from lib.ai import phase_inference, sub_summary  # noqa: E402


# The real thing: Google's body, verbatim in shape, including the model names
# and the sentence that must never reach the page.
RETIRED_MODEL_BODY = {
    "error": {
        "code": 404,
        "status": "NOT_FOUND",
        "message": (
            "This model models/gemini-2.5-flash-lite is no longer available to "
            "new users. Please update your code to use "
            "models/gemini-3.5-flash-lite"
        ),
    },
}


def retired_model_error():
    return errors.ClientError(404, RETIRED_MODEL_BODY)


class TheModelIsTheOneGoogleStillServes(unittest.TestCase):
    def test_both_live_call_sites_default_to_the_new_model(self):
        self.assertEqual(sub_summary.GEMINI_MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(phase_inference.GEMINI_MODEL, "gemini-3.5-flash-lite")

    def test_the_two_call_sites_agree(self):
        """One drifting from the other is the same outage on half the surface."""
        self.assertEqual(sub_summary.GEMINI_MODEL, phase_inference.GEMINI_MODEL)

    def test_the_retired_model_is_named_nowhere_in_the_backend(self):
        hits = []
        for path in BACKEND.rglob("*.py"):
            if "__pycache__" in str(path) or path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for n, line in enumerate(text.splitlines(), 1):
                if "gemini-2.5-flash-lite" in line and not line.lstrip().startswith("#"):
                    hits.append(f"{path.relative_to(BACKEND)}:{n}")
        self.assertEqual(hits, [], f"retired model still referenced in code: {hits}")

    def test_the_env_var_still_overrides(self):
        """The default is the fix because the variable is unset. It must not
        become a hardcode — an override has to keep working."""
        src = (BACKEND / "lib" / "ai" / "sub_summary.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("GEMINI_MODEL"', src)
        src2 = (BACKEND / "lib" / "ai" / "phase_inference.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("GEMINI_MODEL"', src2)

    def test_server_no_longer_declares_a_third_copy(self):
        """It was read by nothing in that file, and when the model was retired
        it was the one place where changing the string would have done
        nothing."""
        src = (BACKEND / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("GEMINI_MODEL = os.environ.get", src)


class TheTraceNamesTheStatus(unittest.TestCase):
    def test_the_exact_string_the_report_now_prints(self):
        self.assertEqual(sub_summary._error_trace(retired_model_error()),
                         "ClientError 404 NOT_FOUND")

    def test_end_to_end_through_the_generator(self):
        """The outcome the admin block renders, from a raising client."""
        def _boom(*a, **k):
            raise retired_model_error()

        with patch.object(sub_summary, "GEMINI_API_KEY", "test-key"), \
                patch.object(sub_summary.genai, "Client", _boom):
            sentence, outcome = sub_summary.generate_sentence_traced({
                "company": "Arkon Builders", "trade": "Framers",
                "worker_count": 5, "activities": ["wall framing"],
                "locations": ["floor 3"], "photo_count": 2,
            })
        self.assertIsNone(sentence)
        self.assertEqual(outcome, "failed: ClientError 404 NOT_FOUND")

    def test_404_is_distinguishable_from_the_other_4xx_it_used_to_look_like(self):
        cases = {
            403: "PERMISSION_DENIED",
            429: "RESOURCE_EXHAUSTED",
            400: "INVALID_ARGUMENT",
        }
        traces = set()
        for code, status in cases.items():
            e = errors.ClientError(code, {"error": {"code": code, "status": status,
                                                    "message": "x"}})
            traces.add(sub_summary._error_trace(e))
        self.assertEqual(len(traces), 3, f"still indistinguishable: {traces}")


class TheTraceStillWithholdsTheBody(unittest.TestCase):
    """The refusal that was right, kept. This string is rendered."""

    def test_the_message_does_not_reach_the_trace(self):
        trace = sub_summary._error_trace(retired_model_error())
        for leaked in ("gemini-2.5-flash-lite", "gemini-3.5-flash-lite",
                       "no longer available", "Please update"):
            self.assertNotIn(leaked, trace)

    def test_a_request_id_or_url_in_the_body_does_not_reach_the_trace(self):
        e = errors.ClientError(400, {"error": {
            "code": 400, "status": "INVALID_ARGUMENT",
            "message": ("request id 7f3c-9a11 failed at "
                        "https://generativelanguage.googleapis.com/v1beta/models "
                        "payload: {'company': 'Arkon Builders'}"),
        }})
        trace = sub_summary._error_trace(e)
        for leaked in ("7f3c-9a11", "https://", "googleapis", "Arkon"):
            self.assertNotIn(leaked, trace)
        self.assertEqual(trace, "ClientError 400 INVALID_ARGUMENT")

    def test_str_of_the_error_really_does_carry_the_body(self):
        """The premise of the refusal, asserted rather than assumed — if the
        SDK ever stops interpolating the body, this test says so and the
        reasoning above can be revisited."""
        self.assertIn("no longer available", str(retired_model_error()))

    def test_a_status_that_is_not_an_enum_token_is_dropped(self):
        """`.status` is derived from the response body, so a server returning
        prose there must not be able to put prose on the page."""
        e = errors.ClientError(500, {"error": {
            "code": 500,
            "status": "the upstream service at 10.0.0.4 rejected request abc123",
            "message": "m",
        }})
        self.assertEqual(sub_summary._error_trace(e), "ClientError 500")

    def test_a_plain_exception_still_traces_as_its_class(self):
        self.assertEqual(sub_summary._error_trace(ValueError("boom")), "ValueError")
        self.assertEqual(sub_summary._error_trace(TimeoutError()), "TimeoutError")

    def test_the_trace_is_always_render_safe(self):
        """Whatever it produces is a short token run — no angle brackets, no
        quotes, nothing that depends on the escaping at the render site."""
        for e in (retired_model_error(), ValueError("<script>"), TimeoutError()):
            with self.subTest(e=type(e).__name__):
                self.assertTrue(re.fullmatch(r"[A-Za-z_]+( \d{3})?( [A-Z_]+)?",
                                             sub_summary._error_trace(e)),
                                sub_summary._error_trace(e))


class TheOtherOutcomesAreUnchanged(unittest.TestCase):
    """The four-outcome contract the trace exists to serve."""

    def test_no_key_still_skips_rather_than_failing(self):
        with patch.object(sub_summary, "GEMINI_API_KEY", ""):
            sentence, outcome = sub_summary.generate_sentence_traced({"company": "X"})
        self.assertIsNone(sentence)
        self.assertEqual(outcome, "skipped: no key")

    def test_the_outcome_vocabulary_is_documented_in_the_docstring(self):
        doc = sub_summary.generate_sentence_traced.__doc__ or ""
        for token in ("generated", "skipped: no key", "failed:", "refused:"):
            self.assertIn(token, doc)


if __name__ == "__main__":
    unittest.main()
