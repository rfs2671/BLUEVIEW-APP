"""THE AFFIRM CONTROL ON THE GATE KIOSK — B10, second half.

checkin.html is a single public HTML file with an inline script, so the control is
asserted by EXECUTING that script against a stub DOM rather than by grepping it.
Seven source assertions on this project have been satisfied by prose about the
thing rather than the thing — twice this round — so the behaviours that matter
here (the language freeze, the never-blocks rule, the no-image rule) are run.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_HTML = (Path(__file__).resolve().parents[1] / "checkin.html").read_text(encoding="utf-8")
_SCRIPT = re.search(r"<script>([\s\S]*)</script>", _HTML).group(1)


def _run(js: str, *, lang: str = "en", worker=None):
    """Execute the page's own affirm functions under Node with a stub DOM.

    Only the four functions under test are lifted, by name, so the harness
    cannot accidentally exercise something else — and if one is renamed this
    fails rather than silently testing nothing.
    """
    import json
    import subprocess

    wanted = ["function toggleAffirm(", "function signatureAffirmed(",
              "function renderAffirmBlock("]
    src = ""
    for needle in wanted:
        assert needle in _SCRIPT, f"{needle} is gone from checkin.html"
        start = _SCRIPT.index(needle)
        depth, i = 0, _SCRIPT.index("{", start)
        for i in range(i, len(_SCRIPT)):
            if _SCRIPT[i] == "{":
                depth += 1
            elif _SCRIPT[i] == "}":
                depth -= 1
                if depth == 0:
                    break
        src += _SCRIPT[start:i + 1] + "\n"

    harness = f"""
    const _boxes = {{}};
    const _texts = {{}};
    let _hidden = {{}};
    function _mk(id) {{
      return {{
        classList: {{
          _s: new Set(),
          add(c) {{ this._s.add(c); if (c === 'hidden') _hidden[id] = true; }},
          remove(c) {{ this._s.delete(c); if (c === 'hidden') _hidden[id] = false; }},
          toggle(c) {{ this._s.has(c) ? this._s.delete(c) : this._s.add(c); }},
          contains(c) {{ return this._s.has(c); }},
        }},
        set textContent(v) {{ _texts[id] = v; }},
        get textContent() {{ return _texts[id]; }},
      }};
    }}
    for (const id of ['affirmBlock', 'affirmBox', 'affirmOnFile']) _boxes[id] = _mk(id);
    const document = {{ getElementById: (id) => _boxes[id] || null }};
    let currentLang = {json.dumps(lang)};
    const TR = {{
      affirmOnFile: 'Your signature is on file. Signed {{date}}.',
      affirmOnFileNoDate: 'Your signature is on file.',
    }};
    function t(k) {{ return TR[k] || k; }}
    {src}
    const worker = {json.dumps(worker)};
    let out = {{}};
    {js}
    console.log(JSON.stringify(out));
    """
    proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[:400]
    return json.loads(proc.stdout.strip().splitlines()[-1])


_SIGNED = {"has_signature": True, "signature_signed_at": "2025-07-29T08:00:00Z"}
_NO_SIG = {"has_signature": False, "signature_signed_at": None}


class TestTheControlAppearsOnlyWhenThereIsSomethingToAffirm(unittest.TestCase):
    def test_a_worker_with_a_signature_is_offered_it(self):
        out = _run("renderAffirmBlock(worker); out.hidden = _hidden.affirmBlock;",
                   worker=_SIGNED)
        self.assertIs(out["hidden"], False)

    def test_a_worker_with_nothing_on_file_is_offered_nothing(self):
        """The sheet will say NO SIGNATURE ON FILE — a different fact from not
        affirming, and not something he can fix at a turnstile."""
        out = _run("renderAffirmBlock(worker); out.hidden = _hidden.affirmBlock;",
                   worker=_NO_SIG)
        self.assertIs(out["hidden"], True)

    def test_reopening_clears_a_previous_affirmation(self):
        """A second worker on the same kiosk must not inherit the first one's
        tap."""
        out = _run(
            "renderAffirmBlock(worker); toggleAffirm();"
            "renderAffirmBlock(worker); out.affirmed = signatureAffirmed();",
            worker=_SIGNED)
        self.assertIs(out["affirmed"], False)

    def test_reopening_also_clears_the_recorded_language(self):
        """Defence in depth: the server only stores the language when affirmed,
        so a stale value never reaches the record — but the line clearing it
        exists, and a mutation removing it survived until this asserted it."""
        out = _run(
            "renderAffirmBlock(worker); toggleAffirm();"
            "renderAffirmBlock(worker); out.lang = affirmedLang;",
            lang="es", worker=_SIGNED)
        self.assertIsNone(out["lang"])


class TestHeIsToldWhenHeSignedAndNeverBlocked(unittest.TestCase):
    def test_the_signing_date_is_shown(self):
        out = _run("renderAffirmBlock(worker); out.text = _texts.affirmOnFile;",
                   worker=_SIGNED)
        self.assertIn("2025", out["text"])
        self.assertNotIn("{date}", out["text"])

    def test_a_missing_date_still_offers_the_control(self):
        """The signature is on file either way, and that is what he affirms."""
        out = _run("renderAffirmBlock(worker); out.hidden = _hidden.affirmBlock;"
                   "out.text = _texts.affirmOnFile;",
                   worker={"has_signature": True, "signature_signed_at": None})
        self.assertIs(out["hidden"], False)
        self.assertNotIn("Invalid", out["text"])

    def test_an_unparseable_date_does_not_print_Invalid_Date(self):
        out = _run("renderAffirmBlock(worker); out.text = _texts.affirmOnFile;",
                   worker={"has_signature": True, "signature_signed_at": "not a date"})
        self.assertNotIn("Invalid", out["text"])

    def test_nothing_about_the_affirmation_can_refuse_a_check_in(self):
        """The standing rule: the gate does not stop a man working. An
        unaffirmed signature is a gap on a sheet, not a locked turnstile."""
        quick = _SCRIPT[_SCRIPT.index("async function quickCheckIn"):]
        quick = quick[:quick.index("\nasync function", 10)] if "\nasync function" in quick[10:] else quick[:4000]
        for line in quick.splitlines():
            s = line.strip()
            if ("signatureAffirmed" in s or "affirmedLang" in s) and s.startswith(("if ", "return", "throw")):
                self.fail(f"the affirmation is gating the check-in: {s}")


class TestTheLanguageIsFrozenAtTheMomentOfAffirmation(unittest.TestCase):
    def test_it_records_the_language_that_was_on_screen(self):
        out = _run("renderAffirmBlock(worker); toggleAffirm(); out.lang = affirmedLang;",
                   lang="es", worker=_SIGNED)
        self.assertEqual(out["lang"], "es")

    def test_flipping_the_toggle_AFTER_affirming_does_not_rewrite_it(self):
        """A record that changes after the fact is worse than one that records
        nothing. He affirmed Spanish copy; that is what he read."""
        out = _run(
            "renderAffirmBlock(worker); toggleAffirm();"
            "currentLang = 'en';"
            "out.lang = affirmedLang; out.affirmed = signatureAffirmed();",
            lang="es", worker=_SIGNED)
        self.assertEqual(out["lang"], "es")
        self.assertIs(out["affirmed"], True)

    def test_un_affirming_clears_the_language(self):
        """Never left pointing at a language he saw for a tap he then undid."""
        out = _run("renderAffirmBlock(worker); toggleAffirm(); toggleAffirm();"
                   "out.lang = affirmedLang; out.affirmed = signatureAffirmed();",
                   lang="es", worker=_SIGNED)
        self.assertIsNone(out["lang"])
        self.assertIs(out["affirmed"], False)

    def test_it_reads_as_NOT_affirmed_when_the_DOM_is_missing(self):
        """Total on the submit path: any DOM surprise must never throw."""
        out = _run("out.affirmed = signatureAffirmed();", worker=_SIGNED)
        self.assertIs(out["affirmed"], False)


class TestTheImageNeverReachesThisPage(unittest.TestCase):
    """lookup-worker is public and keyed on a phone number. Once signature
    images are reachable that way they have been reachable."""

    def test_the_page_never_reads_a_signature_image_field(self):
        block = _HTML[_HTML.index('id="affirmBlock"'):]
        block = block[:block.index("</div>", block.index("affirmOnFile"))]
        self.assertNotIn("<img", block)
        self.assertNotIn("signature_image", _SCRIPT)
        self.assertIsNone(re.search(r"worker\.signature\b", _SCRIPT),
                          "the kiosk must never read the signature itself")

    def test_it_reads_only_the_fact_and_the_date(self):
        self.assertIn("worker.has_signature", _SCRIPT)
        self.assertIn("worker.signature_signed_at", _SCRIPT)


class TestTheCopyIsApprovedAndBilingual(unittest.TestCase):
    def test_both_locales_carry_the_affirmation_copy(self):
        for key in ("affirmLabel", "affirmOnFile", "affirmOnFileNoDate"):
            with self.subTest(key=key):
                self.assertEqual(_SCRIPT.count(f"{key}:"), 2,
                                 "worker-facing legal copy must exist in EN and ES")

    def test_the_english_is_the_approved_wording(self):
        self.assertIn(
            "By tapping Affirm, I confirm this is my signature and authorize its "
            "use on today's Pre-Shift Sign-In Log for this jobsite.", _HTML)

    def test_it_names_the_preshift_log_and_nothing_else(self):
        """SCOPE: the pre-shift sign-in log only. #135 ruled a worker does not
        sign a toolbox talk and this does not reverse it."""
        for label in re.findall(r"affirmLabel: ['\"](.+?)['\"],", _SCRIPT):
            with self.subTest(label=label[:40]):
                self.assertNotIn("toolbox", label.lower())
                self.assertNotIn("charla", label.lower())

    def test_the_spanish_is_not_the_english(self):
        labels = re.findall(r"affirmLabel: ['\"](.+?)['\"],", _SCRIPT)
        self.assertEqual(len(labels), 2)
        self.assertNotEqual(labels[0], labels[1])
        self.assertIn("Afirmar", labels[1])


class TestItIsSubmittedWithTheCheckIn(unittest.TestCase):
    def test_both_fields_are_sent(self):
        self.assertIn("signature_affirmed: signatureAffirmed(),", _SCRIPT)
        self.assertIn("signature_affirmed_lang: affirmedLang,", _SCRIPT)


if __name__ == "__main__":
    unittest.main()
