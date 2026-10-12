"""Live 588, Mon Oct 12 (PR 4 of 4): the assignee's private link.

Every punch DM / post ends with a private no-login link per assignee
(signed; one per assignee per job). The phone page shows only their open
items on that job, full photos, location, due, and "Mark done" with a photo
-> ready to check. It works while any of their items is not closed, until
30 days after the last activity (live 588, Oct 12 10:47 #12: one stable link,
tests/test_punch_link_1047.py). Shadow mode makes the link and shows it in the shadow text; nothing
is sent. Company-scoped; follows the retention and project-delete paths.
"""

from __future__ import annotations

import asyncio
import html as html_
import io
import os
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from PIL import Image  # noqa: E402
from starlette.datastructures import Headers, UploadFile  # noqa: E402

import server  # noqa: E402
from lib import punch, punch_link, wa_retention  # noqa: E402
from tests.test_punch_server import _run, _sc, _upto, dry  # noqa: E402

URL = re.compile(r"https://\S+/api/public/punch/([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")


def _jpeg():
    b = io.BytesIO()
    Image.new("RGB", (1200, 900), (90, 90, 90)).save(b, "JPEG")
    return b.getvalue()


def _sent():
    """The 588 walk, sent (shadow): db, and the walker's DM transcript."""
    sc = _upto(_sc(), "ok")
    db, proj = dry.world(sc)
    with patch.object(dry, "world", lambda _sc: (db, proj)):
        res = _run(sc)
    return db, "\n".join(str(t) for t in res["transcript"])


def _call(db, fn, *a, **k):
    with patch.object(server, "db", db), \
            patch.object(server, "_presign_r2_get", lambda key, ttl: f"https://r2.invalid/{key}"):
        return asyncio.run(fn(*a, **k))


def _open_card(pid):
    """An open item's card on the page (its one big "I fixed it")."""
    return f'data-state="open" data-pid="{pid}"'


class _Req:
    """What the endpoints read of a request: its headers and cookies."""

    def __init__(self, accept="", cookies=None):
        self.headers = {"accept": accept}
        self.cookies = dict(cookies or {})


def _body(resp):
    return resp.body.decode()


class TheToken(unittest.TestCase):

    def test_signed_and_checked(self):
        tok = punch_link.token("abcdefghijklmnop", "s3cret")
        self.assertEqual(punch_link.verify(tok, "s3cret"), "abcdefghijklmnop")
        self.assertIsNone(punch_link.verify(tok, "other-secret"))
        link_id, sig = tok.split(".")
        self.assertIsNone(punch_link.verify(f"{link_id}.{sig[:-1]}A", "s3cret"))
        self.assertIsNone(punch_link.verify("abcdefghijklmnop", "s3cret"))   # an id alone
        for bad in ("", None, "a.b", "../x.y", f"{link_id}.{sig}.x"):
            self.assertIsNone(punch_link.verify(bad, "s3cret"), bad)


class EveryMessageCarriesIt(unittest.TestCase):

    def test_shadow_shows_a_link_per_assignee_and_sends_nothing(self):
        db, said = _sent()
        links = db[punch_link.COLLECTION].rows
        assignees = {punch_link.person_key(r["assignee"]) for r in db[punch.COLLECTION].rows
                     if r.get("assignee")}
        self.assertEqual({l["assignee_key"] for l in links}, assignees)
        self.assertIn("Punch sends are in shadow mode: nothing was sent.", said)
        toks = set(URL.findall(said))
        self.assertEqual(len(toks), len(assignees))
        self.assertIn("private link, no login", said)
        for t in toks:
            self.assertIsNotNone(punch_link.verify(t, server._punch_link_secret()))
        for l in links:
            self.assertEqual(l["company_id"], dry.COMPANY)
            self.assertEqual(l["expires_at"] - l["created_at"], timedelta(days=30))

    def test_one_link_per_assignee_per_job_reused(self):
        db, _said = _sent()
        a = next(r["assignee"] for r in db[punch.COLLECTION].rows if r.get("assignee"))
        now = datetime.now(timezone.utc)
        u1 = _call(db, server._punch_link_for, dry.COMPANY, "p588", a, now)
        u2 = _call(db, server._punch_link_for, dry.COMPANY, "p588", a, now)
        self.assertEqual(u1, u2)
        self.assertEqual(len([l for l in db[punch_link.COLLECTION].rows
                              if l["assignee_key"] == punch_link.person_key(a)]), 1)


class ThePage(unittest.TestCase):

    def setUp(self):
        self.db, _ = _sent()
        self.rows = self.db[punch.COLLECTION].rows
        self.mike = next(r["assignee"] for r in self.rows if r["assignee"]["name"] == "Mike Rivera")
        self.url = _call(self.db, server._punch_link_for, dry.COMPANY, "p588", self.mike,
                         datetime.now(timezone.utc))
        self.tok = URL.search(self.url).group(1)
        self.mine = [r for r in self.rows if r["assignee"]["name"] == "Mike Rivera"]
        self.theirs = [r for r in self.rows if r["assignee"]["name"] != "Mike Rivera"]

    def page(self, tok=None):
        return _call(self.db, server.public_punch_link, tok or self.tok, _Req())

    def test_only_their_open_items_with_location_due_and_photos(self):
        resp = self.page()
        self.assertEqual(resp.status_code, 200)
        html = _body(resp)
        for r in self.mine:
            self.assertIn(r["pid"], html)
            self.assertIn(_open_card(r['pid']), html)
        for r in self.theirs:
            self.assertNotIn(r["pid"] + "<", html)
            self.assertNotIn(_open_card(r['pid']), html)
        self.assertIn("Hi Mike 👋", html)                         # first name only
        self.assertNotRegex(html, r"1718555\d{4}")              # no phone number
        self.assertIn("noindex", html)
        self.assertEqual(resp.headers["cache-control"], "no-store")
        with_photo = next(r for r in self.mine if r.get("photo_key"))
        self.assertIn(f'{self.tok}/photo/{with_photo["pid"]}/1', html)

    def test_their_photo_in_full_never_anyone_elses(self):
        r = next(r for r in self.mine if r.get("photo_key"))
        resp = _call(self.db, server.public_punch_link_photo, self.tok, r["pid"], 1)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["location"], f"https://r2.invalid/{r['photo_key']}")
        other = next(x for x in self.theirs if x.get("photo_key"))
        for pid, n in ((other["pid"], 1), (r["pid"], 9)):
            with self.assertRaises(server.HTTPException) as e:
                _call(self.db, server.public_punch_link_photo, self.tok, pid, n)
            self.assertEqual(e.exception.status_code, 404)

    def _done(self, pid, data=None, name="p.jpg"):
        up = None
        if data is not None:
            up = UploadFile(file=io.BytesIO(data), filename=name,
                            headers=Headers({"content-type": "image/jpeg"}))
        stored = []
        with patch.object(server, "_upload_to_r2", lambda b, k, t: stored.append((k, b)) or k):
            resp = _call(self.db, server.public_punch_link_done, self.tok, pid, _Req(), up)
        return resp, stored

    def test_mark_done_with_a_photo_is_ready_to_check(self):
        r = self.mine[0]
        img = _jpeg()
        resp, stored = self._done(r["pid"], img)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], f"/api/public/punch/{self.tok}?done={r['pid']}")
        self.assertEqual(r["status"], "ready_to_check")
        self.assertEqual(stored[0][1], img)                     # the original, kept
        self.assertTrue(stored[0][0].startswith("wa-photos/p588/link/"))
        self.assertEqual(r["completion"]["photo_key"], stored[0][0])
        self.assertEqual(r["completion"]["by"], f"link:{punch_link.person_key(self.mike)}")
        att = next(a for a in self.db.attention_items.rows if a.get("punch_id") == r["pid"])
        self.assertEqual(att["status"], "possibly_done")         # not chased; a GC closes it
        html = _body(_call(self.db, server.public_punch_link, self.tok, _Req(), done=r["pid"]))
        self.assertIn(punch_link.t("en", "thanks_banner"), html)
        self.assertIn(f'data-state="ready_to_check" data-pid="{r["pid"]}"', html)

    def test_mark_done_without_a_photo(self):
        r = self.mine[0]
        resp, stored = self._done(r["pid"])
        self.assertEqual((resp.status_code, stored, r["status"]), (303, [], "ready_to_check"))
        self.assertIsNone(r["completion"]["photo_key"])

    def test_not_a_photo_changes_nothing(self):
        r = self.mine[0]
        resp, stored = self._done(r["pid"], b"%PDF-1.4 not a photo", "x.pdf")
        self.assertEqual((resp.status_code, stored, r["status"]), (422, [], "open"))
        self.assertIn(punch_link.t("en", "bad_photo"), _body(resp))

    def test_someone_elses_item_cannot_be_marked(self):
        other = self.theirs[0]
        resp, _ = self._done(other["pid"])
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(other["status"], "open")

    def test_a_bad_or_tampered_link_opens_nothing(self):
        link_id, sig = self.tok.split(".")
        for bad in (f"{link_id}.{'A' * len(sig)}", link_id, "x" * 20 + "." + sig):
            resp = self.page(bad)
            self.assertEqual(resp.status_code, 404)
            self.assertIn(punch_link.GONE_TEXT, _body(resp))

    def test_after_30_days_it_stops(self):
        link = next(l for l in self.db[punch_link.COLLECTION].rows
                    if l["assignee_key"] == punch_link.person_key(self.mike))
        link["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertEqual(self.page().status_code, 404)

    def test_when_all_their_items_are_closed_it_stops_until_one_is_not(self):
        # #764 revoked it for good; live 588 #12: the same link comes back.
        for r in self.mine:
            r["status"] = "closed"
        self.assertEqual(self.page().status_code, 404)
        self.assertIsNone(self._link()["revoked_at"])
        self.mine[0]["status"] = "open"                         # reopened later: the same link
        self.assertEqual(self.page().status_code, 200)
        url = _call(self.db, server._punch_link_for, dry.COMPANY, "p588", self.mike,
                    datetime.now(timezone.utc))
        self.assertEqual(url, self.url)

    def test_a_reassigned_item_leaves_the_old_link(self):
        r = self.mine[0]
        r["assignee"] = dict(self.theirs[0]["assignee"])
        html = _body(self.page())
        self.assertNotIn(_open_card(r['pid']), html)

    def test_company_scoped(self):
        link = next(l for l in self.db[punch_link.COLLECTION].rows
                    if l["assignee_key"] == punch_link.person_key(self.mike))
        link["company_id"] = "another_company"                  # the project is not theirs
        self.assertEqual(self.page().status_code, 404)

    def test_a_deleted_project_closes_it(self):
        self.db.projects.rows[0]["is_deleted"] = True
        self.assertEqual(self.page().status_code, 404)


    # ── Codex review on #764 ─────────────────────────────────────────────

    def _link(self):
        return next(l for l in self.db[punch_link.COLLECTION].rows
                    if l["assignee_key"] == punch_link.person_key(self.mike))

    def test_closing_their_last_item_revokes_nothing(self):
        now = datetime.now(timezone.utc)
        for r in self.mine[:-1]:
            r["status"] = "closed"
        _call(self.db, server._punch_set_status, self.mine[-1], "closed", now, by="u_pm", quote="ok")
        self.assertIsNone(self._link()["revoked_at"])
        self.assertEqual(self.page().status_code, 404)                    # nothing left open
        self.mine[-1]["status"] = "open"                                  # reopened: back
        self.assertEqual(self.page().status_code, 200)

    def test_closing_one_of_several_keeps_it(self):
        _call(self.db, server._punch_set_status, self.mine[0], "closed",
              datetime.now(timezone.utc), by="u_pm", quote="ok")
        self.assertIsNone(self._link()["revoked_at"])

    def test_a_photo_that_cannot_be_stored_marks_nothing(self):
        r = self.mine[0]
        up = UploadFile(file=io.BytesIO(_jpeg()), filename="p.jpg",
                        headers=Headers({"content-type": "image/jpeg"}))
        with patch.object(server, "_upload_to_r2", lambda b, k, t: None):
            resp = _call(self.db, server.public_punch_link_done, self.tok, r["pid"], _Req(), up)
        self.assertEqual((resp.status_code, r["status"]), (503, "open"))
        self.assertIn(html_.escape(punch_link.t("en", "failed")), _body(resp))

    def test_closed_meanwhile_is_never_overwritten(self):
        r = self.mine[0]
        r["status"] = "closed"                    # an admin, after the page was read
        ok = _call(self.db, server._punch_set_status, dict(r, status="open"), "ready_to_check",
                   datetime.now(timezone.utc), by="link:x", quote="q",
                   only_if={"status": "open", "assignee.kind": r["assignee"]["kind"],
                            "assignee.id": r["assignee"]["id"]})
        self.assertFalse(ok)
        self.assertEqual(r["status"], "closed")
        att = next(a for a in self.db.attention_items.rows if a.get("punch_id") == r["pid"])
        self.assertNotEqual(att["status"], "possibly_done")
        import inspect
        self.assertIn('only_if={"status": "open"', inspect.getsource(server.public_punch_link_done))

    def test_a_big_job_never_hides_their_items(self):
        base = dict(self.theirs[0])
        for i in range(700):                      # others' open items, first by seq
            self.db[punch.COLLECTION].rows.insert(0, dict(base, _id=f"x{i}", pid=f"P-X-{i}", seq=-i))
        html = _body(self.page())
        for r in self.mine:
            self.assertIn(_open_card(r['pid']), html)


class RetentionAndDelete(unittest.TestCase):

    def test_follows_the_project_delete_and_retention_paths(self):
        self.assertIn(punch_link.COLLECTION, server._PROJECT_OWNED_COLLECTIONS)
        self.assertIn(punch_link.COLLECTION, wa_retention.COLLECTIONS)
