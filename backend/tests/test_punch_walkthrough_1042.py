"""The DM walkthrough, Mon Oct 12 10:42-10:47 AM (588), and what it broke:

  2. "Chris gc" at "Who gets what?" -- every trade to one person -- said
     "Would post in 588 group, mentioning each one". Every trade to ONE
     person is the whole list to them by DM; the group only on "to the
     group" / "post in group".
  3. The shadow text read "@17187559520". The admin reads "@Chris Weiss (GC
     team)"; the number is only in the send text and the mention payload.
  4. "Done, send to chris" got only a 👍. At any stage after the photos:
     "done, send to X" / "send to X" / "send it to X" / "send all to X" /
     "everything to X" (+ "asap", "by Fri") -> the missing locations asked,
     then the whole list to X by DM, the recap, 'ok' sends. "send to the
     group": the same, to the group.
  5. A text during a walk never gets only a reaction.
"""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

import server  # noqa: F401
from tests import _punch_detailed  # noqa: E402
from lib import punch
from tests.test_punch_walkthrough_2031 import _Walk


setUpModule, tearDownModule = _punch_detailed.module_hooks()


class _Real(_Walk):
    """Mentions as they really come back: the number as the handle."""

    def _patches(self):
        ps = super()._patches()

        async def targets(people, company_id, now=None):
            out = []
            for p in people:
                d = "".join(ch for ch in str(p.get("jid") or "") if ch.isdigit())
                out.append({"name": p.get("name") or "", "phone": d or None,
                            "handle": "@" + (d or p.get("name") or ""), "resolved": bool(d),
                            "source": "jid" if d else "none"})
            return out
        return [p for p in ps if getattr(p, "attribute", "") != "_mention_targets"] + \
            [patch.object(server, "_mention_targets", targets)]

    def start(self):
        self.turn("starting walkthrough at 588")
        self.turn("tile cracked 4D", photo=True)               # 10:43
        self.turn("outlet cover missing 4D", photo=True)       # 10:44 (P-588-4)


NUMBER = re.compile(r"\d{10,}")


class OnePersonIsADm(_Real):

    def test_chris_gc_at_who_gets_what_is_a_dm(self):
        self.start()
        self.turn("done")
        (who,) = self.turn("send")
        self.assertTrue(who.startswith("Who gets what?"), who)
        (recap,) = self.turn("Chris gc")
        self.assertTrue(recap.startswith("Ready to DM the whole list to Chris Weiss (GC team)"), recap)
        self.assertNotIn("post in", recap)
        (sent,) = self.turn("ok")
        self.assertIn("Would DM Chris Weiss (GC team):", sent)
        self.assertNotIn("Would post", sent)
        rows = self.db[punch.COLLECTION].rows
        self.assertEqual({r["sent_via"] for r in rows}, {"dm"})

    def test_the_group_only_when_asked(self):
        self.start()
        self.turn("done")
        self.turn("send")
        self.turn("Chris gc")
        (recap,) = self.turn("to the group")
        self.assertTrue(recap.startswith("Ready to post the whole list in"), recap)
        (sent,) = self.turn("ok")
        self.assertIn("Would post in", sent)

    def test_two_people_stay_per_trade(self):
        self.start()
        self.turn("2 → electrical")                            # (draft edits come later)
        self.turn("done")
        self.turn("1 → tile")
        self.turn("send")
        (recap,) = self.turn("tile → Chris gc; electrical → Dov")
        self.assertTrue(recap.startswith("Ready to post in"), recap)


class NoNumberIsShown(_Real):

    def test_the_shadow_text_names_people(self):
        self.start()
        self.turn("done")
        self.turn("send")
        self.turn("Chris gc")
        self.turn("to the group")
        (sent,) = self.turn("ok")
        self.assertIn("@Chris Weiss (GC team)", sent)
        self.assertIsNone(NUMBER.search(sent), sent)           # 10:45 AM: "@17187559520"
        for line in self.said:
            self.assertIsNone(NUMBER.search(line), line)

    def test_a_token_left_unnamed_is_never_a_number(self):
        self.assertEqual(punch.no_numbers("@17187559520 tile cracked"),
                         "@(WhatsApp contact) tile cracked")


class SendToShortcuts(_Real):

    def test_done_send_to_chris_10_46(self):
        self.start()
        out = self.turn("Done, send to chris")
        self.assertEqual(self.reacts.count("👍"), 2)              # the two photos only
        (recap,) = out
        self.assertTrue(recap.startswith("Ready to DM the whole list to Chris Weiss (GC team)"), recap)
        self.assertIn("#1, #2", recap)
        (sent,) = self.turn("ok")
        self.assertIn("Would DM Chris Weiss (GC team):", sent)
        self.assertEqual(len(self.db[punch.COLLECTION].rows), 2)

    def test_a_full_name_before_the_due_stays_whole(self):
        # Codex review on #765: "John Smith tomorrow" read as John, due "Smith tomorrow".
        for text, want in (("send it to John Smith tomorrow", {"name": "John Smith", "due": "tomorrow"}),
                           ("send to Chris Weiss by Fri", {"name": "Chris Weiss", "due": "Fri"}),
                           ("everything to Chris next Fri", {"name": "Chris", "due": "next Fri"}),
                           ("send to Chris Weiss", {"name": "Chris Weiss", "due": None})):
            self.assertEqual(punch.send_shortcut(text), want, text)

    def test_every_form_with_a_due(self):
        for text, due in (("send to Chris", None), ("send it to Chris gc", None),
                          ("send all to chris asap", "ASAP"), ("everything to Chris by Fri", "Fri"),
                          ("done send it to chris, due tomorrow", "tomorrow")):
            with self.subTest(text):
                self.setUp()
                self.start()
                (recap,) = self.turn(text)
                self.assertTrue(recap.startswith("Ready to DM the whole list to Chris Weiss"), recap)
                if due:
                    self.assertEqual(set(self.sess()["due"].values()), {due})
                    self.assertIn(punch.capitalize(punch.due_label(due)), recap)

    def test_missing_locations_never_stop_a_send(self):
        # Tue Oct 13, 1:43 PM: nothing optional stops a send -- the recap.
        self.turn("starting walkthrough at 588")
        self.turn("tile cracked", photo=True)                  # no location
        (recap,) = self.turn("done, send to chris")
        self.assertTrue(recap.startswith("Ready to DM the whole list to Chris Weiss"), recap)

    def test_send_to_the_group(self):
        self.start()
        (recap,) = self.turn("Done. Send it to the group")
        self.assertTrue(recap.startswith("Ready to post the whole list in"), recap)

    def test_at_the_draft_and_at_who_gets_what(self):
        self.start()
        self.turn("done")                                       # the draft
        (recap,) = self.turn("send it to chris")
        self.assertTrue(recap.startswith("Ready to DM the whole list to Chris Weiss"), recap)
        self.setUp()
        self.start()
        self.turn("done")
        self.turn("send")                                       # Who gets what?
        (recap,) = self.turn("everything to chris asap")
        self.assertTrue(recap.startswith("Ready to DM the whole list to Chris Weiss"), recap)


class NeverOnlyAReaction(_Real):

    def test_every_text_during_the_walk_gets_words(self):
        self.turn("starting walkthrough at 588")
        self.turn("", photo=True)
        texts = ["tile cracked 4D", "also the grout", "Done, send to chris"]
        for t in texts:
            before = len(self.reacts)
            out = self.turn(t)
            self.assertTrue(out, f"{t!r}: no reply")
            self.assertEqual(len(self.reacts), before, f"{t!r}: a reaction")


class TheScreenSaysWhatHappened(_Real):
    """6. The punch screen's history said "Sent" for a shadow send."""

    def test_a_shadow_dm_and_a_shadow_post(self):
        self.start()
        self.turn("Done, send to chris")
        self.turn("ok")
        h = server._punch_view(self.db[punch.COLLECTION].rows[0])["history"][0]
        self.assertEqual((h["action"], h["mode"], h["dest"]),
                         ("sent", "shadow", "DM to Chris Weiss (GC team)"))
        self.setUp()
        self.start()
        self.turn("Done. Send it to the group")
        self.turn("ok")
        h = server._punch_view(self.db[punch.COLLECTION].rows[0])["history"][0]
        self.assertEqual((h["mode"], h["dest"]), ("shadow", "post in the job group"))

    def test_an_older_send_is_worked_out(self):
        row = {"pid": "P-588-1", "sent_via": "dm", "send_mode": "shadow",
               "assignee": {"kind": "user", "id": "u_chris", "name": "Chris Weiss"},
               "history": [{"action": "sent", "at": None}]}
        h = server._punch_view(row)["history"][0]
        self.assertEqual((h["mode"], h["dest"]), ("shadow", "DM to Chris Weiss (GC team)"))
