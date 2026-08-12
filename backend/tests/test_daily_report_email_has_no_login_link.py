"""The daily report email sends no one to a login wall.

WHO GETS IT. project.report_email_list — an arbitrary list of addresses an
admin types (server.py update_report_settings). It is NEVER derived from user
accounts, and nothing in the send path looks a recipient up in `users`. An
investor or a bank on that list has no login, so a "View in LeveLog" button was
a dead end for exactly the audience the report is for.

The system cannot tell an investor from an admin who added themselves, and a
per-recipient account lookup is not worth adding to keep a button — so the CTA
goes for everyone on this template.

WHAT THEY ACTUALLY NEED IS ATTACHED. The PDF rides on the same email, and the
body still says so.

THE OTHER FIVE TRIGGERS KEEP THEIRS. Permit renewals go to people who act on
them inside the app, and their link is the point of the mail.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from lib.email_templates import (  # noqa: E402
    TRIGGER_RENDERERS, render_for_trigger,
)

DAILY = {
    "project_name": "857 Prescott Pl", "project_address": "857 Prescott Pl",
    "report_date": "2026-08-11", "logbook_count": 4, "worker_count": 5,
    "expiring_permits": 0, "attached": True,
    "action_link": "https://app.levelog.com/reports",
}
RENEWAL = {
    "permit_type": "Sidewalk Shed", "project_name": "857 Prescott Pl",
    "expiry_date": "2026-09-01", "days_left": 30,
    "action_link": "https://app.levelog.com/permits/1",
}


class TheDailyReportHasNoCallToAction(unittest.TestCase):
    def setUp(self):
        self.subject, self.html, self.text = render_for_trigger(
            "project_daily_report", DAILY)

    def test_no_view_in_levelog_button(self):
        self.assertNotIn("View in LeveLog", self.html)

    def test_no_view_in_levelog_in_the_plain_text_part(self):
        """Both parts, because a mail client may render either."""
        self.assertNotIn("View in LeveLog", self.text)

    def test_no_app_link_survives_anywhere_in_the_html(self):
        """Not merely the label — the URL itself must be gone, or a client
        that linkifies bare text would put the wall back."""
        self.assertNotIn("app.levelog.com", self.html)
        self.assertNotIn("app.levelog.com", self.text)

    def test_the_action_link_context_key_is_simply_IGNORED(self):
        """The caller still passes it (server.py builds the context for every
        trigger the same way). Passing it must not resurrect the button."""
        self.assertNotIn(DAILY["action_link"], self.html)

    def test_what_they_need_is_still_promised(self):
        self.assertIn("attached as a PDF", self.text)

    def test_the_report_still_says_what_it_is(self):
        for expected in ("857 Prescott Pl", "2026-08-11"):
            self.assertIn(expected, self.html, expected)


class TheOtherTriggersKeepTheirs(unittest.TestCase):
    """The control. Without it every assertion above would also pass on a
    template layer that had lost its buttons entirely."""

    def test_a_permit_renewal_still_links_into_the_app(self):
        _s, html, _t = render_for_trigger("renewal_t_minus_30", RENEWAL)
        self.assertIn("Review Permit", html)
        self.assertIn(RENEWAL["action_link"], html)

    def test_every_OTHER_trigger_still_renders_a_button(self):
        for trigger in TRIGGER_RENDERERS:
            if trigger == "project_daily_report":
                continue
            with self.subTest(trigger=trigger):
                _s, html, _t = render_for_trigger(trigger, RENEWAL)
                self.assertIn("border-radius:6px;text-decoration:none", html,
                              f"{trigger} lost its action button")


class TheCardMakesTheButtonOPTIONAL(unittest.TestCase):
    SRC = (_BACKEND / "lib" / "email_templates.py").read_text(encoding="utf-8")

    def test_both_args_default_to_empty(self):
        self.assertIn('action_label: str = ""', self.SRC)
        self.assertIn('action_url: str = ""', self.SRC)

    def test_the_block_renders_only_when_BOTH_are_given(self):
        """A label with no url would render a button linking nowhere."""
        self.assertIn("if (action_label and action_url) else", self.SRC)


if __name__ == "__main__":
    unittest.main()
