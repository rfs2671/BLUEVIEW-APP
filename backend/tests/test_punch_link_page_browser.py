"""The assignee's page in a real browser, on a 360 px Android screen (Oct 12
redesign: "a 70-year-old with no tech skills understands it in 5 seconds").

The page is lib/punch_link.page() as the server sends it; the network is the
test's (the photo upload, "I fixed it", the thumbnails), so the page's own
script is what is tested: the camera button sends the photo made at most
2000 px, the card turns green, a send that fails keeps the photo and says
so in big words, tries again by itself when the signal is back, and after a
reload; "Skip photo"; the photo full screen. Nothing on the page is wider
than the screen, and every button is at least 56 px tall.

Needs Python Playwright and its Chromium (in the dev container); skipped
where they are missing (CI has the library, not the browser).
SAVE_SCREENS=<dir> keeps the screenshots (the PR's).

A Playwright that started but could not launch a browser is stopped before
skipping: left running, its event loop broke asyncio.run() for every test
after this file (CI on #766: 1,654 failures).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import unittest

from PIL import Image

from lib import punch_link

try:
    from playwright.sync_api import sync_playwright
except Exception:                                   # pragma: no cover
    sync_playwright = None

ORIGIN = "https://levelog.test"
TOK = "abcdefghijklmnop.ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
PAGE = f"{ORIGIN}/api/public/punch/{TOK}"
UA = ("Mozilla/5.0 (Linux; Android 13; SM-A136U) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Mobile Safari/537.36")


def _jpeg(w, h, c=(150, 110, 70)):
    b = io.BytesIO()
    Image.new("RGB", (w, h), c).save(b, "JPEG", quality=85)
    return b.getvalue()


def items(reopened=False):
    """Mike's items on 588, Mon Oct 12 (as the 588 walk left them)."""
    rows = [
        {"pid": "P-588-1", "seq": 1, "status": "open", "text": "Exit sign out", "floor": "3",
         "area": "corridor", "photos": 1, "due": {"due_text": "Mon", "due_at": "2026-10-12"}},
        {"pid": "P-588-2", "seq": 2, "status": "open", "text": "Outlet covers missing",
         "floor": "4", "area": "Apt 4B", "photos": 2, "due": {"due_text": "Fri", "due_at": "2026-10-16"}},
        {"pid": "P-588-3", "seq": 3, "status": "open", "text": "Falta un enchufe en la cocina",
         "floor": "4", "area": "Apt 4C", "room": "kitchen", "photos": 1,
         "due": {"due_text": "Fri", "due_at": "2026-10-09"}},
        {"pid": "P-588-4", "seq": 4, "status": "ready_to_check", "text": "Bathroom no light",
         "floor": "6", "area": "Apt 6B", "photos": 1},
        {"pid": "P-588-12", "seq": 12, "status": "open", "text": "Lobby door scuffed",
         "floor": "lobby", "photos": 0},
    ]
    if reopened:
        rows[3].update(status="open", reopened=True, reopen_note="Still no light in the bathroom")
    return rows


def html(lang="en", reopened=False, done_items=True, company="Blueview Construction Inc"):
    rows = [r for r in items(reopened) if done_items or r["status"] != "ready_to_check"]
    return punch_link.page(name="Mike Rivera", job="588 Thomas S Boyland St",
                           items=rows, tok=TOK, lang=lang, today="2026-10-12",
                           wa_url="https://wa.me/17185550100", company=company)


DEV_CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def start_browser(exe=None):
    """(playwright, browser), or SkipTest with Playwright stopped again."""
    exe = exe or (DEV_CHROMIUM if os.path.exists(DEV_CHROMIUM) else None)
    pw = sync_playwright().start()
    try:
        return pw, pw.chromium.launch(**({"executable_path": exe} if exe else {}))
    except Exception as e:
        pw.stop()
        raise unittest.SkipTest(f"no Chromium: {type(e).__name__}")


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class NoBrowserLeavesNothingRunning(unittest.TestCase):

    def test_a_failed_launch_stops_playwright(self):
        with self.assertRaises(unittest.SkipTest):
            start_browser("/nonexistent/chrome")
        self.assertEqual(asyncio.run(asyncio.sleep(0, "ok")), "ok")


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class OnA360PxAndroid(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.pw, cls.browser = start_browser()
        cls.shots = os.environ.get("SAVE_SCREENS")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.ctx = self.browser.new_context(
            viewport={"width": 360, "height": 780}, device_scale_factor=2, is_mobile=True,
            has_touch=True, user_agent=UA)
        self.page = self.ctx.new_page()
        self.uploads, self.dones = [], []
        self.fail_uploads = 0
        self.lang, self.reopened, self.done_items = "en", False, True
        self.company = "Blueview Construction Inc"
        self.ctx.route(f"{ORIGIN}/**", self.serve)

    def tearDown(self):
        self.ctx.close()

    # The server, as far as the page can tell.
    def serve(self, route):
        req = route.request
        url = req.url.split("?")[0]
        if url == PAGE:
            return route.fulfill(status=200, content_type="text/html; charset=utf-8",
                                 body=html(self.lang, self.reopened, self.done_items, self.company))
        if "/photo/" in url:
            return route.fulfill(status=200, content_type="image/jpeg",
                                 body=_jpeg(240, 180) if "thumb=1" in req.url else _jpeg(1600, 1200))
        if "/upload/" in url:
            if self.fail_uploads:
                self.fail_uploads -= 1
                return route.abort("internetdisconnected")
            self.uploads.append((url.rsplit("/", 1)[1], req.post_data_buffer))
            return route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        if "/done/" in url:
            self.dones.append((url.rsplit("/", 1)[1], req.headers.get("accept")))
            return route.fulfill(status=200, content_type="application/json",
                                 body='{"ok":true,"status":"ready_to_check"}')
        return route.fulfill(status=404, body="")

    def open(self):
        self.page.goto(PAGE)
        self.page.wait_for_load_state("networkidle")

    def shot(self, name, full=True, at=None):
        if at:
            self.page.evaluate(f"document.querySelector('.card[data-pid=\"{at}\"]')"
                               ".scrollIntoView({block: 'center'})")
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
            self.page.screenshot(path=os.path.join(self.shots, name), full_page=full)

    def card(self, pid):
        return self.page.locator(f'.card[data-pid="{pid}"]')

    def pick(self, pid, data):
        self.card(pid).locator("input[type=file]").set_input_files(
            {"name": "IMG_2041.jpg", "mimeType": "image/jpeg", "buffer": data})

    def sent_photo(self, body):
        start = body.index(b"\xff\xd8")
        return Image.open(io.BytesIO(body[start:body.rindex(b"\xff\xd9") + 2]))

    # ── What it looks like ──────────────────────────────────────────────

    def test_the_first_look_fits_the_screen_and_says_what_to_do(self):
        self.open()
        p = self.page
        self.assertEqual(p.locator("h1").inner_text(), "Hi Mike 👋")
        self.assertEqual(p.locator(".top .left").inner_text(), "4 things to fix")
        self.assertEqual(p.locator(".addr").inner_text(), "588 Thomas S Boyland St")
        self.assertEqual(p.locator(".count").inner_text(), "1 of 5 done")
        self.assertEqual(p.locator("main h2").all_inner_texts(), ["Lobby", "Floor 3", "Floor 4"])
        self.assertEqual(p.locator(".card[data-state=open] .fix").first.inner_text().split("\n")[0],
                         "✓ I fixed it")
        self.assertEqual(self.card("P-588-1").locator(".due").inner_text(), "Due today")
        self.assertEqual(self.card("P-588-3").locator(".due").inner_text(), "Overdue")
        self.assertEqual(self.card("P-588-2").locator(".due").count(), 0)      # Fri: not yet
        self.assertEqual(self.card("P-588-3").locator(".where").inner_text(), "Apt 4C · Kitchen")
        # No "Choose File" anywhere: the file control is never seen.
        for box in p.locator("input[type=file]").evaluate_all(
                "els => els.map(e => e.getBoundingClientRect().width)"):
            self.assertLessEqual(box, 1)
        # Nothing wider than the screen; every button 56 px or more; 18 px text.
        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), 360)
        heights = p.evaluate("""() => [...document.querySelectorAll(
            '.fix, .skip, .wa, summary, .langs a')].filter(e => e.offsetParent)
            .map(e => [e.className || e.tagName, e.getBoundingClientRect().height])""")
        for name, h in heights:
            self.assertGreaterEqual(h, 56, name)
        sizes = p.evaluate("""() => [...document.querySelectorAll('.what, .where, .due, .count, .addr')]
            .map(e => parseFloat(getComputedStyle(e).fontSize))""")
        self.assertGreaterEqual(min(sizes), 18)
        # Done ones folded at the bottom.
        self.assertFalse(p.locator("details.waiting").evaluate("d => d.open"))
        self.assertIn("Done — waiting for the GC to check (1)", p.locator("details.waiting summary").inner_text())
        self.assertEqual(p.locator(".wa").get_attribute("href"), "https://wa.me/17185550100")
        self.shot("1-first-look-360.png")
        self.shot("1-first-look-360-screen.png", full=False)

    def test_a_levelog_page_blue_to_press_green_only_when_done(self):
        self.open()
        p = self.page
        logo = p.locator(".brand img.logo")
        self.assertEqual(logo.get_attribute("alt"), "Levelog")
        self.assertTrue(logo.get_attribute("src").startswith("data:image/png;base64,"))
        self.assertLessEqual(logo.bounding_box()["height"], 32)
        self.assertLess(logo.bounding_box()["x"], 30)                   # top left
        gc = p.locator(".top .gc")
        self.assertEqual(gc.inner_text(), "BLUEVIEW CONSTRUCTION INC")   # the app's thin uppercase
        self.assertLess(logo.bounding_box()["y"], gc.bounding_box()["y"])  # under the logo
        self.assertEqual(gc.evaluate("e => e.getClientRects().length"), 1)
        self.assertLessEqual(gc.bounding_box()["height"], 32)           # one line, never broken
        self.assertEqual(gc.evaluate("e => getComputedStyle(e).fontWeight"), "300")
        blue, green = "rgb(21, 101, 192)", "rgb(46, 125, 50)"
        style = lambda sel, prop: p.locator(sel).first.evaluate(
            f"e => getComputedStyle(e).{prop}")
        self.assertEqual(style(".fix", "backgroundColor"), blue)        # I fixed it: blue
        self.assertEqual(style(".bar i", "backgroundColor"), blue)
        self.assertEqual(style(".langs a.on", "backgroundColor"), blue)
        self.assertEqual(style(".wa", "color"), blue)
        self.assertEqual(style("body", "backgroundColor"), "rgb(255, 255, 255)")
        self.assertEqual(style("details.waiting summary", "color"), green)   # done: green
        # Nothing green that is not done.
        greens = p.evaluate("""() => [...document.querySelectorAll('body *')].filter(e => {
            const s = getComputedStyle(e);
            return e.offsetParent && [s.color, s.backgroundColor, s.borderTopColor]
                .includes('rgb(46, 125, 50)');
        }).filter(e => !e.closest('details.waiting, [data-ui=done]')).map(e => e.outerHTML.slice(0, 80))""")
        self.assertEqual(greens, [])
        self.assertEqual(p.locator(".powered").inner_text(), "Powered by Levelog")
        self.assertEqual(style(".powered", "fontSize"), "13px")

    def test_a_long_gc_name_stays_on_one_line(self):
        # Codex review on #767: as the app's header, one line, smaller for a
        # long name, "…" only when even that does not fit.
        for name in ("Blueview Construction and General Contracting Services of New York LLC",
                     "SUPERLONGCONSTRUCTIONCOMPANYNAMEWITHOUTANYSPACESATALLINC"):
            self.company = name
            self.open()
            gc = self.page.locator(".top .gc")
            self.assertEqual(gc.evaluate("e => e.getClientRects().length"), 1, name)
            self.assertLessEqual(gc.bounding_box()["height"], 32, name)
            self.assertLessEqual(gc.bounding_box()["x"] + gc.bounding_box()["width"], 360 - 15, name)
            self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"), 360, name)
            self.assertGreaterEqual(float(gc.evaluate("e => getComputedStyle(e).fontSize")[:-2]), 10)
        self.shot("8-long-gc-name-360-screen.png", full=False)

    def test_in_spanish(self):
        self.lang = "es"
        self.open()
        p = self.page
        self.assertEqual(p.locator("h1").inner_text(), "Hola Mike 👋")
        self.assertEqual(p.locator(".top .left").inner_text(), "4 cosas por arreglar")
        self.assertEqual(p.locator(".card[data-state=open] .fix").first.inner_text().split("\n")[0],
                         "✓ Ya lo arreglé")
        self.assertEqual(p.locator(".wa").inner_text(), "¿Preguntas? Responda por WhatsApp")
        self.assertLessEqual(p.evaluate("document.documentElement.scrollWidth"), 360)
        self.shot("5-spanish-360-screen.png", full=False)

    def test_a_reopened_item_comes_back_at_the_top_in_red(self):
        self.reopened = True
        self.open()
        first = self.page.locator(".card[data-state=open]").first
        self.assertEqual(first.get_attribute("data-pid"), "P-588-4")
        self.assertEqual(first.locator(".note").inner_text(),
                         "Not fixed yet: Still no light in the bathroom")
        self.assertLess(self.page.evaluate(
            "document.querySelector('.card[data-pid=\"P-588-4\"]').getBoundingClientRect().top"),
            self.page.evaluate("document.querySelector('main h2').getBoundingClientRect().top"))
        self.shot("4-reopened-360-screen.png", full=False)

    # ── "I fixed it" ────────────────────────────────────────────────────

    def test_i_fixed_it_takes_the_photo_sends_it_small_and_turns_green(self):
        self.open()
        inp = self.card("P-588-1").locator("input[type=file]")
        self.assertEqual(inp.get_attribute("capture"), "environment")
        self.assertEqual(inp.get_attribute("accept"), "image/*")
        self.pick("P-588-1", _jpeg(4000, 3000))                 # a phone's 12 MP photo
        self.page.wait_for_selector('.card[data-pid="P-588-1"][data-ui=done]')
        (pid, body), = self.uploads
        self.assertEqual(pid, "P-588-1")
        self.assertEqual(max(self.sent_photo(body).size), 2000)  # made smaller on the phone
        self.assertEqual(self.dones, [("P-588-1", "application/json")])
        c = self.card("P-588-1")
        self.assertEqual(c.locator(".status").inner_text().strip(),
                         "Done ✓ — thanks! The GC will check it.")
        self.assertFalse(c.locator(".fix").is_visible())
        self.assertEqual(self.page.locator(".count").inner_text(), "2 of 5 done")
        self.assertEqual(self.page.locator(".top .left").inner_text(), "3 things to fix")
        self.shot("2-fixed-green-360-screen.png", full=False, at="P-588-1")
        # Then down into "Done — waiting for the GC to check (2)", folded; its
        # floor ("Floor 3", nothing else on it) goes; open ones stay on top.
        self.page.wait_for_selector('details.waiting .card[data-pid="P-588-1"]', state="attached")
        box = self.page.locator("details.waiting")
        self.assertFalse(box.evaluate("d => d.open"))
        self.assertEqual(" ".join(box.locator("summary").inner_text().split()),
                         "✅ Done — waiting for the GC to check (2)")
        self.assertEqual(self.page.locator("main h2").all_inner_texts(), ["Lobby", "Floor 4"])
        first_open = self.page.locator(".card[data-state=open]:not([data-ui=done])").first
        self.assertLess(first_open.bounding_box()["y"], box.bounding_box()["y"])
        box.scroll_into_view_if_needed()
        self.shot("7-done-folded-at-the-bottom-360-screen.png", full=False)

    def test_the_first_done_makes_the_folded_list(self):
        self.done_items = False
        self.open()
        self.assertTrue(self.page.locator("details.waiting").is_hidden())
        self.card("P-588-12").locator(".skip").click()
        self.page.wait_for_selector('details.waiting .card[data-pid="P-588-12"]', state="attached")
        self.assertTrue(self.page.locator("details.waiting").is_visible())
        self.assertIn("(1)", self.page.locator("details.waiting summary").inner_text())
        self.assertNotIn("Lobby", self.page.locator("main h2").all_inner_texts())

    def test_skip_photo(self):
        self.open()
        self.card("P-588-12").locator(".skip").click()
        self.page.wait_for_selector('.card[data-pid="P-588-12"][data-ui=done]')
        self.assertEqual(self.uploads, [])
        self.assertEqual(self.dones, [("P-588-12", "application/json")])

    # ── No signal ───────────────────────────────────────────────────────

    def test_no_signal_keeps_the_photo_says_so_and_sends_it_when_back(self):
        self.open()
        self.fail_uploads = 1
        self.pick("P-588-2", _jpeg(1200, 900))
        self.page.wait_for_selector('.card[data-pid="P-588-2"][data-ui=failed]')
        retry = self.card("P-588-2").locator(".retry")
        self.assertTrue(retry.is_visible())
        self.assertEqual(retry.inner_text(), "Couldn't send — tap to try again")
        self.assertGreaterEqual(retry.bounding_box()["height"], 56)
        self.shot("3-could-not-send-360-screen.png", full=False, at="P-588-2")
        self.page.evaluate("window.dispatchEvent(new Event('online'))")   # the signal is back
        self.page.wait_for_selector('.card[data-pid="P-588-2"][data-ui=done]')
        self.assertEqual(len(self.uploads), 1)

    def test_tap_to_try_again(self):
        self.open()
        self.fail_uploads = 1
        self.pick("P-588-2", _jpeg(1200, 900))
        self.page.wait_for_selector('.card[data-pid="P-588-2"][data-ui=failed]')
        self.card("P-588-2").locator(".retry").click()
        self.page.wait_for_selector('.card[data-pid="P-588-2"][data-ui=done]')

    def test_the_photo_survives_closing_the_page(self):
        self.open()
        self.fail_uploads = 1
        self.pick("P-588-3", _jpeg(1200, 900))
        self.page.wait_for_selector('.card[data-pid="P-588-3"][data-ui=failed]')
        self.page.reload()                                      # closed, opened again
        self.page.wait_for_selector('.card[data-pid="P-588-3"][data-ui=done]')
        (pid, body), = self.uploads
        self.assertEqual((pid, self.sent_photo(body).size), ("P-588-3", (1200, 900)))

    def test_a_photo_kept_for_another_jobs_link_is_not_sent_here(self):
        # Codex review on #766: two jobs can share an item's number. A photo
        # left on the phone by job 2's link must not be sent as P-588-3 here.
        self.open()
        self.page.evaluate("""() => new Promise(ok => {
            const r = indexedDB.open('levelog-punch', 1);
            r.onupgradeneeded = () => r.result.createObjectStore('photos');
            r.onsuccess = () => {
                const tx = r.result.transaction('photos', 'readwrite');
                tx.objectStore('photos').put(new Blob(['x'], {type: 'image/jpeg'}),
                                             'otherjoblink00.SIG/done/P-588-3');
                tx.objectStore('photos').put(new Blob(['x'], {type: 'image/jpeg'}),
                                             'P-588-3');      // the key before the fix
                tx.oncomplete = ok;
            };
        })""")
        self.page.reload()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(300)
        self.assertEqual((self.uploads, self.dones), ([], []))
        self.assertIsNone(self.card("P-588-3").get_attribute("data-ui"))

    # ── The photo ───────────────────────────────────────────────────────

    def test_the_photo_full_screen_and_back(self):
        self.open()
        self.card("P-588-2").locator(".thumb").click()
        v = self.page.locator("#viewer")
        self.assertTrue(v.is_visible())
        self.assertIn("/photo/P-588-2/1", v.locator("img").get_attribute("src"))
        v.locator(".next").click()                              # its second photo
        self.assertIn("/photo/P-588-2/2", v.locator("img").get_attribute("src"))
        self.shot("6-photo-full-screen-360.png", full=False)
        v.locator(".close").click()
        self.assertFalse(v.is_visible())


if __name__ == "__main__":
    unittest.main()
