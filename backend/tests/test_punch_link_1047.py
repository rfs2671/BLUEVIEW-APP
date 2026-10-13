"""Live 588, Mon Oct 12 10:47 AM: the assignee's page (items 9-12).

 9. Progress persists: every "Mark done" is saved at once; opening the link
    any later day shows those items first, "✓ Ready to check — waiting for
    review" (not hidden), the open ones below, the closed ones folded.
10. The photo uploads as soon as it is picked (progress bar, retry), so a
    closed tab never loses it; "Mark done" just confirms.
11. An admin's reopen puts the item back to Open on their page with the
    admin's note ("Still chipped at the corner").
12. One stable link per assignee per job: items given to them later show up
    on the same link; it works while any of theirs is not closed, and until
    30 days after the last activity.
"""

from __future__ import annotations

import html as html_
import io
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from starlette.datastructures import Headers, UploadFile

import server
from tests import _punch_detailed  # noqa: E402
from lib import punch, punch_link
from tests.test_punch_link import URL, _Req, _open_card, _body, _call, _jpeg, _sent
from tests.test_punch_server import dry


def _up(data, name="p.jpg"):
    return UploadFile(file=io.BytesIO(data), filename=name,
                      headers=Headers({"content-type": "image/jpeg"}))


setUpModule, tearDownModule = _punch_detailed.module_hooks()


class Live1047(unittest.TestCase):

    def setUp(self):
        self.db, _ = _sent()
        self.rows = self.db[punch.COLLECTION].rows
        self.mike = next(r["assignee"] for r in self.rows if r["assignee"]["name"] == "Mike Rivera")
        self.url = _call(self.db, server._punch_link_for, dry.COMPANY, "p588", self.mike,
                         datetime.now(timezone.utc))
        self.tok = URL.search(self.url).group(1)
        self.mine = [r for r in self.rows if r["assignee"]["name"] == "Mike Rivera"]
        self.theirs = [r for r in self.rows if r["assignee"]["name"] != "Mike Rivera"]
        self.assertEqual(len(self.mine), 4)          # P-588-1..4

    def link(self):
        return next(l for l in self.db[punch_link.COLLECTION].rows
                    if l["assignee_key"] == punch_link.person_key(self.mike))

    def page(self, tok=None):
        return _call(self.db, server.public_punch_link, tok or self.tok, _Req())

    def upload(self, pid, data, store=lambda b, k, t: k):
        stored = []
        with patch.object(server, "_upload_to_r2",
                          lambda b, k, t: (stored.append((k, b)), store(b, k, t))[1]):
            resp = _call(self.db, server.public_punch_link_upload, self.tok, pid, _up(data))
        return resp, stored

    def done(self, pid, data=None):
        with patch.object(server, "_upload_to_r2", lambda b, k, t: k):
            return _call(self.db, server.public_punch_link_done, self.tok, pid, _Req(),
                         _up(data) if data is not None else None)

    # ── 9. Progress persists ────────────────────────────────────────────

    def test_9_done_items_stay_on_the_page_first_open_below_closed_folded(self):
        first, second = self.mine[0], self.mine[1]
        self.assertEqual(self.done(first["pid"]).status_code, 303)      # saved at once
        self.assertEqual(first["status"], "ready_to_check")
        self.mine[2]["status"] = "closed"                               # a GC closed one
        # Another day, the link opened again.
        html = _body(self.page())
        # Not hidden: under "Done — waiting for the GC to check (1)", below
        # the open ones (the Oct 12 redesign moved them to the bottom).
        waiting = html.index(punch_link.t("en", "waiting", n=1))
        self.assertGreater(html.index(f'data-pid="{first["pid"]}"'), waiting)
        self.assertNotIn(_open_card(first["pid"]), html)
        self.assertIn(_open_card(second["pid"]), html)
        self.assertLess(html.index(_open_card(second["pid"])), waiting)
        closed = html.index(punch_link.t("en", "closed", n=1))
        self.assertGreater(closed, waiting)
        self.assertGreater(html.index(f'data-pid="{self.mine[2]["pid"]}"'), closed)

    # ── 10. Upload on pick ──────────────────────────────────────────────

    def test_10_the_picked_photo_is_kept_before_mark_done_and_a_closed_tab_loses_nothing(self):
        r = self.mine[0]
        html = _body(self.page())
        self.assertIn(f'data-up="{self.tok}/upload/{r["pid"]}"', html)  # the page's own upload
        self.assertIn('class="prog"', html)
        self.assertIn(html_.escape(punch_link.t("en", "failed")), html)
        img = _jpeg()
        resp, stored = self.upload(r["pid"], img)                       # picked
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(stored[0][1], img)
        self.assertEqual(r["status"], "open")                           # not marked yet
        key = r["link_photo_pending"]["key"]
        # The tab is closed; later the link is opened again.
        html = _body(self.page())
        self.assertIn(f'data-pid="{r["pid"]}" data-pending="1"', html)      # the page finishes it
        self.assertEqual(self.done(r["pid"]).status_code, 303)          # just confirms
        self.assertEqual(r["status"], "ready_to_check")
        self.assertEqual(r["completion"]["photo_key"], key)
        self.assertNotIn("link_photo_pending", r)

    def test_10_a_photo_left_unconfirmed_is_not_kept_past_a_status_change(self):
        r = self.mine[0]
        self.upload(r["pid"], _jpeg())
        _call(self.db, server._punch_set_status, r, "ready_to_check", datetime.now(timezone.utc),
              by="17185550123@c.us", quote="done P1")                  # done in WhatsApp
        self.assertNotIn("link_photo_pending", r)

    def test_10_a_failed_upload_keeps_nothing_and_the_retry_does(self):
        r = self.mine[0]
        resp, _ = self.upload(r["pid"], _jpeg(), store=lambda b, k, t: None)
        self.assertEqual(resp.status_code, 503)
        self.assertNotIn("link_photo_pending", r)
        resp, _ = self.upload(r["pid"], _jpeg())                        # Retry
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(r["link_photo_pending"]["key"])

    def test_10_not_a_photo_or_not_theirs(self):
        r = self.mine[0]
        resp, stored = self.upload(r["pid"], b"%PDF-1.4 nope")
        self.assertEqual((resp.status_code, stored), (422, []))
        resp, stored = self.upload(self.theirs[0]["pid"], _jpeg())
        self.assertEqual((resp.status_code, stored), (404, []))
        self.assertNotIn("link_photo_pending", self.theirs[0])

    # ── 11. Admin reopen with a note ────────────────────────────────────

    def test_11_whatsapp_reopen_shows_open_with_the_admins_note(self):
        r = self.mine[0]
        self.done(r["pid"])
        ident = {"user": {"role": "pm"}, "role": "pm", "user_id": "u_pm",
                 "projects": [{"_id": "p588"}]}
        said = _call(self.db, server._punch_verdict, ident,
                     f"{r['pid']} not done — still chipped at the corner",
                     datetime.now(timezone.utc))
        self.assertIn("reopened", said)
        self.assertEqual(r["status"], "open")
        html = _body(self.page())
        self.assertIn("Not fixed yet: Still chipped at the corner", html)
        self.assertIn(_open_card(r['pid']), html)

    def test_11_app_reopen_with_a_note(self):
        r = self.mine[0]
        self.done(r["pid"])

        async def scope(project_id, user):
            return dry.COMPANY
        pm = {"id": "u_pm", "_id": "u_pm", "role": "pm", "company_id": dry.COMPANY}
        with patch.object(server, "_memory_project", scope):
            out = _call(self.db, server.patch_project_punch, "p588", r["pid"],
                        {"status": "open", "note": "Still chipped at the corner"}, current_user=pm)
            self.assertEqual(out["reopen_note"], "Still chipped at the corner")
            self.assertIn("Not fixed yet: Still chipped at the corner", _body(self.page()))
            with self.assertRaises(server.HTTPException) as e:          # a note goes with a reopen
                _call(self.db, server.patch_project_punch, "p588", r["pid"],
                      {"status": "closed", "note": "x"}, current_user=pm)
            self.assertEqual(e.exception.status_code, 422)

    # ── 12. One stable link ─────────────────────────────────────────────

    def test_12_an_item_given_later_shows_up_on_the_same_link(self):
        other = self.theirs[0]
        self.assertNotIn(f'data-pid="{other["pid"]}"', _body(self.page()))
        _call(self.db, server._punch_reassign, other, self.mike, datetime.now(timezone.utc), "u_pm")
        self.assertIn(_open_card(other['pid']), _body(self.page()))
        again = _call(self.db, server._punch_link_for, dry.COMPANY, "p588", self.mike,
                      datetime.now(timezone.utc))
        self.assertEqual(again, self.url)                               # the next send: same link
        self.assertEqual(len([l for l in self.db[punch_link.COLLECTION].rows
                              if l["assignee_key"] == punch_link.person_key(self.mike)]), 1)

    def test_12_valid_while_any_is_not_closed(self):
        now = datetime.now(timezone.utc)
        for r in self.mine:
            _call(self.db, server._punch_set_status, r, "closed", now, by="u_pm", quote="ok")
        self.assertEqual(self.page().status_code, 404)
        self.assertIsNone(self.link()["revoked_at"])
        _call(self.db, server._punch_set_status, self.mine[0], "open", now, by="u_pm",
              quote="P1 not done", note="Still chipped at the corner")
        self.assertEqual(self.page().status_code, 200)                  # the same link

    def test_12_thirty_days_after_the_last_activity(self):
        now = datetime.now(timezone.utc)
        link = self.link()
        link["expires_at"] = now + timedelta(days=2)                    # quiet for 28 days
        self.assertEqual(self.page().status_code, 200)                  # opened: activity
        self.assertGreater(self.link()["expires_at"], now + timedelta(days=29))
        link["expires_at"] = now + timedelta(days=2)
        _call(self.db, server._punch_set_status, self.mine[0], "ready_to_check", now,
              by="link:x", quote="q")                                   # a status change
        self.assertGreater(self.link()["expires_at"], now + timedelta(days=29))
        link["expires_at"] = now - timedelta(seconds=1)                 # 30 days, nothing
        self.assertEqual(self.page().status_code, 404)

    def test_12_a_link_the_old_rule_revoked_comes_back(self):
        # #764 revoked a link for good once all its items closed.
        link = self.link()
        link.update(revoked_at=datetime.now(timezone.utc), revoked_reason="all_closed")
        self.assertEqual(self.page().status_code, 200)
        url = _call(self.db, server._punch_link_for, dry.COMPANY, "p588", self.mike,
                    datetime.now(timezone.utc))
        self.assertEqual(url, self.url)
        self.assertIsNone(self.link()["revoked_at"])
        link.update(revoked_at=datetime.now(timezone.utc), revoked_reason="manual")
        self.assertEqual(self.page().status_code, 404)                  # revoked by hand: gone

    def test_the_reopen_note_words(self):
        self.assertEqual(punch.reopen_note("P-588-4 not done — still chipped at the corner"),
                         "Still chipped at the corner")
        self.assertEqual(punch.reopen_note("P2 redo: grout"), "Grout")
        self.assertIsNone(punch.reopen_note("P2 not done"))
        self.assertIsNone(punch.reopen_note("P2 ok"))


if __name__ == "__main__":
    unittest.main()
