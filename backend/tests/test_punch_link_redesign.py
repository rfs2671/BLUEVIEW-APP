"""The assignee's page, Oct 12 redesign: the server's side (the page's script
is tested in a browser, tests/test_punch_link_page_browser.py).

- "Hi Mike 👋 · 4 things to fix", the job's address, "0 of 4 done"; items
  grouped by floor; one big "✓ I fixed it" that opens the camera; the id
  small at the bottom; "Due today" / "Overdue" only.
- Their language: Spanish when People says so; the switch at the top wins
  and is remembered on their phone.
- "I fixed it" from the page's script answers JSON (sent twice: still fine).
- The list's thumbnails are small JPEGs, made once and kept beside the photo.
- "Questions? Reply on WhatsApp" opens the assistant's chat.
"""

from __future__ import annotations

import html as html_
import io
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from PIL import Image
from starlette.datastructures import Headers, UploadFile

import server
from lib import punch, punch_link, wa_voice
from tests.test_punch_link import URL, _Req, _body, _call, _jpeg, _open_card, _sent
from tests.test_punch_server import dry


class Redesign(unittest.TestCase):

    def setUp(self):
        self.db, _ = _sent()
        self.rows = self.db[punch.COLLECTION].rows
        self.mike = next(r["assignee"] for r in self.rows if r["assignee"]["name"] == "Mike Rivera")
        self.url = _call(self.db, server._punch_link_for, dry.COMPANY, "p588", self.mike,
                         datetime.now(timezone.utc))
        self.tok = URL.search(self.url).group(1)
        self.mine = [r for r in self.rows if r["assignee"]["name"] == "Mike Rivera"]

    def page(self, req=None, **kw):
        return _call(self.db, server.public_punch_link, self.tok, req or _Req(), **kw)

    def done(self, pid, req=None, data=None):
        up = (UploadFile(file=io.BytesIO(data), filename="fix.jpg",
                         headers=Headers({"content-type": "image/jpeg"})) if data is not None else None)
        with patch.object(server, "_upload_to_r2", lambda b, k, t: k):
            return _call(self.db, server.public_punch_link_done, self.tok, pid,
                         req or _Req(), up)

    # ── The top and the list ────────────────────────────────────────────

    def test_hello_count_address_progress(self):
        h = _body(self.page())
        self.assertIn("<h1>Hi Mike 👋</h1>", h)
        self.assertIn('<p class="left">4 things to fix</p>', h)
        self.assertIn('<p class="addr">588 Thomas St</p>', h)
        self.assertIn('<p class="count">0 of 4 done</p>', h)
        self.done(self.mine[0]["pid"])
        h = _body(self.page())
        self.assertIn('<p class="left">3 things to fix</p>', h)
        self.assertIn('<p class="count">1 of 4 done</p>', h)

    def test_grouped_by_floor_where_on_the_card_id_small_at_the_bottom(self):
        h = _body(self.page())
        heads = [h.index(f"<h2>{g}</h2>") for g in ("Floor 3", "Floor 4", "Floor 6")]
        self.assertEqual(heads, sorted(heads))
        p3 = next(r for r in self.mine if r["pid"] == "P-588-3")         # Apt 4C, kitchen
        card = h[h.index(_open_card(p3["pid"])):]
        card = card[:card.index("</section>")]
        self.assertIn('<p class="where">Apt 4C · Kitchen</p>', card)
        self.assertIn(f'<p class="pid">{p3["pid"]}</p>', card)
        self.assertLess(card.index('class="fix"'), card.index('class="pid"'))   # id last
        self.assertNotIn(f"<h2>{p3['pid']}", h)                          # never up front

    def test_one_big_button_that_opens_the_camera(self):
        h = _body(self.page())
        self.assertEqual(h.count("✓ I fixed it"), 4)
        self.assertEqual(h.count('accept="image/*" capture="environment"'), 4)
        # The file control only inside the button's label: never seen as a
        # "Choose File".
        for chunk in h.split('<input type="file"')[1:]:
            self.assertTrue(chunk.split(">")[0].endswith('capture="environment"'))
        self.assertEqual(h.count('<input type="file"'), h.count('<label class="fix">'))
        self.assertIn("Take a photo of the fix", h)
        self.assertIn("Skip photo", h)

    def test_due_only_when_it_presses(self):
        today = server.eastern_date(datetime.now(timezone.utc))
        a, b, c = self.mine[0], self.mine[1], self.mine[2]
        a["due"] = {"due_text": "today", "due_at": today}
        b["due"] = {"due_text": "Mon", "due_at": "2026-01-05"}
        c["due"] = {"due_text": "Fri", "due_at": "2099-01-02"}
        h = _body(self.page())

        def card(r):
            x = h[h.index(_open_card(r["pid"])):]
            return x[:x.index("</section>")]
        self.assertIn('<p class="due">Due today</p>', card(a))
        self.assertIn('<p class="due">Overdue</p>', card(b))
        self.assertNotIn('class="due"', card(c))

    def test_reopened_on_top_done_and_closed_folded_at_the_bottom(self):
        now = datetime.now(timezone.utc)
        r0, r1, r2 = self.mine[0], self.mine[1], self.mine[3]
        self.done(r1["pid"])
        _call(self.db, server._punch_set_status, r2, "closed", now, by="u_pm", quote="ok")
        self.done(r0["pid"])
        _call(self.db, server._punch_set_status, r0, "open", now, by="u_pm", quote="P1 not done",
              note="Still chipped at the corner")
        h = _body(self.page())
        top = h.index(_open_card(r0["pid"]))
        self.assertLess(top, h.index("<h2>"))
        self.assertIn("Not fixed yet: Still chipped at the corner", h)
        waiting = h.index("Done — waiting for the GC to check (1)")
        closed = h.index("Checked and closed (1)")
        self.assertLess(h.rindex("</section>", 0, waiting), waiting)
        self.assertLess(waiting, h.index(f'data-pid="{r1["pid"]}"', waiting))
        self.assertLess(waiting, closed)
        self.assertIn('<details class="waiting">', h)                    # folded: no "open"

    # ── Language ────────────────────────────────────────────────────────

    def test_spanish_when_people_says_so_the_switch_wins_and_is_remembered(self):
        self.db[wa_voice.SENDER_LANG_COLLECTION].rows.append(
            {"company_id": dry.COMPANY, "sender_jid": self.mike["jid"], "language": "es"})
        h = _body(self.page())
        self.assertIn('<html lang="es">', h)
        self.assertIn("<h1>Hola Mike 👋</h1>", h)
        self.assertIn("4 cosas por arreglar", h)
        self.assertIn("✓ Ya lo arreglé", h)
        self.assertIn("<h2>Piso 3</h2>", h)
        resp = self.page(lang="en")                                      # the switch
        self.assertIn("Hi Mike 👋", _body(resp))
        cookie = resp.headers["set-cookie"]
        self.assertIn("punch_lang=en", cookie)
        self.assertIn(f"Path=/api/public/punch/{self.tok}", cookie)
        h = _body(self.page(_Req(cookies={"punch_lang": "en"})))         # remembered
        self.assertIn("Hi Mike 👋", h)
        self.assertIn('href="?lang=es"', h)
        self.assertNotIn("set-cookie", self.page(lang="fr").headers)    # not a page language

    # ── "I fixed it" from the page's script ─────────────────────────────

    def test_json_for_the_script_and_twice_is_fine(self):
        js = _Req(accept="application/json")
        r = self.mine[0]
        resp = self.done(r["pid"], js)
        self.assertEqual((resp.status_code, resp.body), (200, b'{"ok":true,"status":"ready_to_check"}'))
        self.assertEqual(r["status"], "ready_to_check")
        self.assertEqual(self.done(r["pid"], js).status_code, 200)        # sent again: still done
        r["status"] = "closed"
        self.assertEqual(self.done(r["pid"], js).status_code, 409)
        self.assertEqual(self.done("P-588-9", js).status_code, 404)      # not theirs
        self.assertEqual(self.done(self.mine[1]["pid"], js, data=b"%PDF").status_code, 422)
        self.assertEqual(self.mine[1]["status"], "open")

    def test_a_plain_form_still_works(self):
        r = self.mine[0]
        resp = self.done(r["pid"], data=_jpeg())
        self.assertEqual(resp.status_code, 303)
        self.assertIn("Thank you! The GC will check it.",
                      _body(self.page(done=r["pid"])))
        resp = self.done(self.mine[1]["pid"], data=b"%PDF")
        self.assertEqual(resp.status_code, 422)
        self.assertIn(html_.escape(punch_link.t("en", "bad_photo")), _body(resp))

    def test_the_scripts_empty_form_through_the_real_app(self):
        # The script posts "I fixed it" as an empty multipart form.
        from fastapi.testclient import TestClient
        r = self.mine[0]
        with patch.object(server, "db", self.db):
            client = TestClient(server.app)
            resp = client.post(f"/api/public/punch/{self.tok}/done/{r['pid']}",
                               files={}, data={}, headers={"Accept": "application/json"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(r["status"], "ready_to_check")

    # ── Thumbnails ──────────────────────────────────────────────────────

    def test_thumbnails_are_small_and_made_once(self):
        r = next(x for x in self.mine if x.get("photo_key"))
        r2 = {r["photo_key"]: _jpeg()}                                   # 1200x900
        stored, reads = [], []

        def get(key):
            reads.append(key)
            return r2.get(key)

        def put(b, k, t):
            stored.append(k)
            r2[k] = b
            return k
        with patch.object(server, "_r2_bytes", get), patch.object(server, "_upload_to_r2", put):
            resp = _call(self.db, server.public_punch_link_photo, self.tok, r["pid"], 1, thumb=1)
            self.assertEqual(resp.media_type, "image/jpeg")
            self.assertEqual(max(Image.open(io.BytesIO(resp.body)).size), server.PUNCH_LINK_THUMB_PX)
            self.assertEqual(stored, [server._punch_thumb_key(r["photo_key"])])
            reads.clear()
            _call(self.db, server.public_punch_link_photo, self.tok, r["pid"], 1, thumb=1)
            self.assertEqual(reads, [server._punch_thumb_key(r["photo_key"])])   # kept
            r2[r["photo_key"]] = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 40      # an iPhone HEIC
            r2.pop(server._punch_thumb_key(r["photo_key"]))
            resp = _call(self.db, server.public_punch_link_photo, self.tok, r["pid"], 1, thumb=1)
            self.assertEqual(resp.status_code, 302)                      # the full one, then

    def test_a_project_purge_deletes_the_thumbnails_too(self):
        # Codex review on #766: the thumbnails are kept nowhere but R2, and
        # the purge deletes by key (the prefix sweep removes nothing here).
        import inspect
        rows = [{"photo_key": "wa-photos/p/w/1.jpg", "extra_photos": ["wa-photos/p/w/2.jpg"],
                 "completion": {"photo_key": "wa-photos/p/msg/9.jpg"},
                 "link_photo_pending": {"key": "wa-photos/p/link/P-1-5.jpg"}},
                {"photo_key": None}]
        walks = [{"items": [{"photo_key": "wa-photos/p/w/1.jpg"}, {"photo_key": "wa-photos/p/w/3.jpg"}]}]
        self.assertEqual(server._punch_r2_keys(rows, walks), [
            "wa-photos/p/w/1.jpg", "wa-photos/p/w/2.jpg",
            "wa-photos/p/w/1-thumb.jpg", "wa-photos/p/w/2-thumb.jpg",
            "wa-photos/p/msg/9.jpg", "wa-photos/p/link/P-1-5.jpg", "wa-photos/p/w/3.jpg"])
        self.assertIn("_punch_r2_keys(", inspect.getsource(server.hard_delete_project))

    def test_a_levelog_page_with_the_gcs_name(self):
        self.db.companies.rows.append({"_id": dry.COMPANY, "name": "Blueview",
                                       "gc_business_name": "Blueview Construction Inc"})
        h = _body(self.page())
        self.assertIn('>Blueview Construction Inc</p>', h)                   # shown in uppercase
        self.assertIn('style="font-size:14px;letter-spacing:2px"', h)
        self.assertIn('<img class="logo" src="data:image/png;base64,', h)
        self.assertIn('<p class="powered">Powered by Levelog</p>', h)
        self.assertIn("<title>588 Thomas St · Levelog</title>", h)
        self.db.companies.rows[0].pop("gc_business_name")
        self.assertIn('>Blueview</p>', _body(self.page()))
        self.assertEqual(punch_link.gc_sizing("B" * 60), (10, 1))         # long: smaller

    def test_green_is_only_for_done_in_the_styles(self):
        # Every style rule that paints green is a done state.
        import re
        css = punch_link._CSS
        for rule in re.findall(r"([^{}]+)\{([^}]*)\}", css):
            sel, body = rule[0].strip(), rule[1]
            if punch_link.GREEN in body or "#E8F5E9" in body or "#C8E6C9" in body:
                for part in sel.split(","):
                    self.assertTrue(re.search(r"data-ui=done|\.mini|summary|banner\.good",
                                              part), part)
        self.assertIn(f"background:{punch_link.BLUE}", css[css.index(".fix{"):])

    # ── Questions ───────────────────────────────────────────────────────

    def test_questions_open_the_assistants_chat(self):
        with patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": "+1 (718) 555-0100"}):
            h = _body(self.page())
        self.assertIn('<a class="wa" href="https://wa.me/17185550100">Questions? Reply on WhatsApp</a>', h)
        with patch.dict(os.environ, {"WAAPI_DISPLAY_NUMBER": ""}):
            self.assertNotIn('class="wa"', _body(self.page()))


if __name__ == "__main__":
    unittest.main()
