"""Photos make items; one text describes its batch (Tue Oct 13, 3:37 PM, 588).

Live, 47 items, shadow: "Last 8 pics all interior" became photo #13's words,
"Back of building" and "Cellar" the words of single photos, and 33 photos
went out blank. The walker sends a burst of photos, then ONE text about it.

The walk replayed here has the shape the walker described: bursts of
photos, each followed by one text ("Cellar", "Back of building", "Last 8 pics
all interior", "Compound and sheetrock not done", "Roof missing coping", "All
waterproof finished"), 15 photos with no text at all, then "done", "send to
me", "go ahead". (The exact message order and times of the live walk are in
the webhook log; scripts/repair_punch_walk.py --dump-events writes them out
in the TIMELINE shape below.)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import punch, punch_batch  # noqa: E402
from tests.test_punch_walkthrough_2031 import CO, CHAT, _Walk  # noqa: E402

#: (kind, photos in the burst | the text), in order.
TIMELINE = [
    ("photos", 6), ("text", "Cellar"),
    ("photos", 2), ("text", "Back of building"),
    ("photos", 10), ("text", "Last 8 pics all interior"),
    ("photos", 4), ("text", "Compound and sheetrock not done"),
    ("photos", 4), ("text", "Roof missing coping"),
    ("photos", 6), ("text", "All waterproof finished"),
    ("photos", 15),
]


def _seen(key: str) -> str:
    """What the (fake) vision model sees in a photo: one per photo."""
    return f"Visible issue {key.rsplit('/', 1)[-1].split('.')[0][-6:]}"


class _Batch(_Walk):

    def setUp(self):
        super().setUp()
        self.described = []

    def _patches(self):
        async def describe(key, project_id=None):
            self.described.append(key)
            return _seen(key)

        async def no_model(*a, **k):
            return None
        return super()._patches() + [
            patch.object(server, "_punch_describe_photo", describe),
            patch.object(server, "_punch_batch_model", no_model),
            patch.object(server, "_punch_brain_model", no_model)]

    def n_of(self, n):
        return next(it for it in self.sess()["items"] if it["n"] == n)


def _expect_walk(test, items):
    """The 588 walk as the rules read it (live, or repaired)."""
    by_n = {it["n"]: it for it in items}
    test.assertEqual(sorted(by_n), list(range(1, 48)))                     # 47 photos, nothing else
    test.assertTrue(all(it.get("photo_key") for it in items))
    for n in range(1, 7):
        test.assertEqual(by_n[n]["area"], "Cellar", n)
    for n in (7, 8):
        test.assertEqual(by_n[n]["area"], "Back of building", n)
    for n in (9, 10):                                                        # before the last 8
        test.assertEqual(by_n[n].get("area"), punch.UNKNOWN, n)
    for n in range(11, 19):
        test.assertEqual(by_n[n]["area"], "interior", n)
    for n in range(19, 23):
        test.assertEqual((by_n[n]["text"], by_n[n].get("text_auto")),
                         ("Compound and sheetrock not done", None), n)
    for n in range(23, 27):
        test.assertEqual((by_n[n]["area"], by_n[n]["text"]), ("roof", "Missing coping"), n)
    for n in range(27, 33):                                                  # a status, not an issue
        test.assertEqual(by_n[n]["notes"][-1]["text"], "All waterproof finished", n)
    auto = [n for n, it in by_n.items() if it.get("text_auto")]
    # A place alone is no description: those photos are described too.
    test.assertEqual(auto, [*range(1, 19), *range(27, 48)])                  # 39 described
    test.assertTrue(all((it.get("text") or "").strip() for it in items))     # never blank


class TheWalkAsSentNow(_Batch):
    """The same messages through the walk as it works now."""

    def _replay(self):
        out = {}
        self.turn("starting walkthrough at 588")
        for kind, what in TIMELINE:
            if kind == "photos":
                for _ in range(what):
                    self.assertEqual(self.turn("", photo=True), [])          # a 👍, no words
            else:
                out[what] = self.turn(what)
        return out

    def test_every_text_is_about_its_batch(self):
        said = self._replay()
        self.assertEqual(said["Cellar"], ["Got it — #1–#6 (6 photos): Cellar."])
        self.assertEqual(said["Back of building"], ["Got it — #7, #8 (2 photos): Back of building."])
        self.assertEqual(said["Last 8 pics all interior"], ["Got it — #11–#18 (8 photos): interior."])
        self.assertEqual(said["Compound and sheetrock not done"],
                         ["Got it — #19–#22 (4 photos): Compound and sheetrock not done."])
        self.assertEqual(said["Roof missing coping"], ["Got it — #23–#26 (4 photos): roof — Missing coping."])
        self.assertEqual(said["All waterproof finished"],
                         ["Got it — #27–#32 (6 photos): note: All waterproof finished."])
        self.assertEqual(len(self.sess()["items"]), 47)                       # no text made an item
        self.assertEqual(self.assistant, [])

    def test_done_describes_the_blank_ones_then_the_draft(self):
        self._replay()
        out = self.turn("done")
        self.assertEqual(out[0], "Writing a short description for the 39 photos with none — one moment.")
        draft = out[-1]
        self.assertIn("(draft)", draft)
        self.assertEqual(len(self.described), 39)
        _expect_walk(self, self.sess()["items"])
        self.assertIn(f"9. 📷 {_seen(self.n_of(9)['photo_key'])} (auto)", draft)
        self.assertIn("19. 📷 Compound and sheetrock not done\n", draft)
        self.assertNotIn("Last 8 pics", draft)
        self.assertNotIn("See photo", draft)

    def test_go_ahead_sends_and_no_bullet_is_blank(self):
        self._replay()
        self.turn("done")
        (recap,) = self.turn("send to me")
        self.assertTrue(recap.startswith("Ready to DM the whole list to Roy Fishman (GC team)"), recap)
        self.assertIn(": 47 items", recap)
        for go in ("go ahead",):
            (sent,) = self.turn(go)
        self.assertTrue(sent.startswith("Punch sends are in shadow mode"), sent)
        self.assertEqual(len(self.db[punch.COLLECTION].rows), 47)
        bullets = [l for l in sent.splitlines() if l.startswith("•")]
        self.assertEqual(len(bullets), 47)
        for b in bullets:
            self.assertRegex(b, r"^• P-\S+ \S", b)                           # words after every id
        lines = sent.splitlines()
        for i, l in enumerate(lines):
            if l.startswith("*"):                                            # a heading has items
                self.assertTrue(i + 1 < len(lines) and lines[i + 1].startswith(("•", "_")), l)


class TheRecapTakesPlainYes(_Batch):

    def test_go_words(self):
        for said in ("go ahead", "do it", "yes send", "send it", "ok go ahead", "Go ahead please",
                     "looks good send"):
            with self.subTest(said):
                self.setUp()
                self.turn("starting walkthrough at 588")
                self.turn("tile cracked 2nd floor", photo=True)
                self.turn("done")
                self.turn("send to me")
                (out,) = self.turn(said)
                self.assertTrue(out.startswith("Punch sends are in shadow mode"), out)
        for no in ("no wait", "send it to chris", "go back"):
            self.assertFalse(punch.is_go(no), no)


class OnlyPhotosMakeItems(_Batch):

    def test_a_text_never_makes_an_item_but_add_does(self):
        self.turn("starting walkthrough at 588")
        self.turn("", photo=True)
        self.turn("Back of building")
        self.turn("Cellar")                          # a second text: the same burst
        self.assertEqual(len(self.sess()["items"]), 1)
        (out,) = self.turn("add: missing access ladder 3rd floor")
        self.assertTrue(out.startswith("Added #2 'Missing access ladder'"), out)
        self.assertEqual(len(self.sess()["items"]), 2)

    def test_an_ok_is_nothing_about_the_photos(self):
        self.turn("starting walkthrough at 588")
        self.turn("", photo=True)
        for said in ("ok", "thanks", "👍"):
            self.assertEqual(self.turn(said), ["👍 Keep going — say done when you're finished."])
        self.assertEqual(self.item(1).get("text"), "")

    def test_a_question_when_the_model_is_down_changes_nothing(self):
        # Codex on #785: never words for the photos.
        self.turn("starting walkthrough at 588")
        self.turn("", photo=True)
        (out,) = self.turn("how many do I have so far?")
        self.assertTrue(out.startswith("I can't do that right now"), out)
        self.assertEqual(self.item(1).get("text"), "")

    def test_a_reply_to_one_photo_is_that_photo(self):
        self.turn("starting walkthrough at 588")
        self.turn("", photo=True)
        self.turn("", photo=True)
        self.turn("cracked tile", reply_to=2)       # the first photo's message
        self.assertEqual(self.item(1)["text"], "cracked tile")
        self.assertEqual(self.item(2).get("text"), "")

    def test_undo_takes_a_batch_back(self):
        self.turn("starting walkthrough at 588")
        for _ in range(3):
            self.turn("", photo=True)
        self.turn("2nd floor compound not done")
        (out,) = self.turn("undo")
        self.assertEqual(out, "Undone — #1–#3 back as they were.")
        self.assertEqual([self.item(n).get("text") for n in (1, 2, 3)], ["", "", ""])
        (out,) = self.turn("roof")                  # the same burst again
        self.assertEqual(out, "Got it — #1–#3 (3 photos): roof.")

    def test_an_auto_description_is_replaced_by_the_walkers_words(self):
        self.turn("starting walkthrough at 588")
        self.turn("", photo=True)
        self.turn("done")
        self.assertTrue(self.item(1)["text_auto"])
        self.turn("missing outlet cover", reply_to=2)
        self.assertEqual(self.item(1)["text"], "missing outlet cover")
        self.assertNotIn("text_auto", self.item(1))


class ReadingABatchText(unittest.TestCase):

    def test_the_live_texts(self):
        r = punch_batch.read_batch
        self.assertEqual((r("Last 8 pics all interior")["last_n"], r("Last 8 pics all interior")["area"]),
                         (8, "interior"))
        self.assertEqual(r("Back of building")["area"], "Back of building")
        self.assertEqual(r("Cellar")["area"], "Cellar")
        self.assertEqual(r("Compound and sheetrock not done")["description"],
                         "Compound and sheetrock not done")
        self.assertEqual((r("Roof missing coping")["area"], r("Roof missing coping")["description"]),
                         ("roof", "Missing coping"))
        self.assertEqual((r("All waterproof finished")["note"], r("All waterproof finished")["description"]),
                         ("All waterproof finished", None))
        self.assertEqual(punch_batch.last_n("the previous three photos"), 3)

    def test_the_model_is_checked(self):
        got = punch_batch.clean_batch_model({"kind": "annotation", "floor": "2", "area": "interior",
                                             "description": "Compound and sheetrock not done",
                                             "last_n": 99}, "2nd floor interior compound not done")
        self.assertEqual((got["floor"], got["area"], got["last_n"]), ("2", "interior", None))
        got = punch_batch.clean_batch_model({"kind": "annotation", "description": "All waterproof finished"},
                                            "All waterproof finished")
        self.assertEqual((got["note"], got["description"]), ("All waterproof finished", None))
        self.assertEqual(punch_batch.clean_batch_model({"kind": "command"}, "send it"), {"kind": "command"})
        self.assertIsNone(punch_batch.clean_batch_model("nope", "x"))

    def test_a_vision_answer_is_eight_words_at_most(self):
        self.assertEqual(punch_batch.clean_description('"Exposed rebar at slab edge."'),
                         "Exposed rebar at slab edge")
        self.assertEqual(len(punch_batch.clean_description("a b c d e f g h i j").split()), 8)
        self.assertIsNone(punch_batch.clean_description("none"))


# ── THIS WALK, PUT RIGHT ─────────────────────────────────────────────────────

T0 = datetime(2026, 10, 13, 19, 0, tzinfo=timezone.utc)                     # 3:00 PM New York


def _old_walk():
    """The walk as the old rule left it, and its messages in order. Each
    text was the last photo's words, except one the assistant made an item
    of its own; it was sent in shadow (P-ids, rows, attention items)."""
    items, events, rows, att = [], [], [], []
    n, k = 0, 0
    for kind, what in TIMELINE:
        if kind == "photos":
            for _ in range(what):
                n += 1
                k += 1
                mid = f"false_{CHAT}_PH{n:03d}"
                items.append({"n": n, "captured": n, "text": "", "photo_key": f"wa-photos/p588/w/{n:03d}.jpg",
                              "message_id": mid, "floor": punch.UNKNOWN, "area": punch.UNKNOWN,
                              "trade": punch.UNKNOWN, "trade_guess": False, "at": T0 + timedelta(seconds=20 * k)})
                events.append({"kind": "photo", "message_id": mid, "at": T0 + timedelta(seconds=20 * k)})
        else:
            k += 1
            mid = f"false_{CHAT}_TX{k:03d}"
            events.append({"kind": "text", "message_id": mid, "text": what, "quoted": "",
                           "at": T0 + timedelta(seconds=20 * k)})
            if what == "Roof missing coping":
                # The assistant's "add": an item with no photo.
                items.append({"n": 99, "captured": n + 0.5, "text": what, "photo_key": None,
                              "message_id": mid, "added": True, "floor": "roof", "area": "roof",
                              "trade": punch.UNKNOWN})
            else:
                last = items[-1]
                fresh = punch.new_item(last["n"], what, photo_key=last["photo_key"],
                                       message_id=last["message_id"])
                last.update({kk: fresh[kk] for kk in ("text", "floor", "area", "trade", "trade_guess")},
                            caption_ids=[mid])
    for kind, what in (("text", "done"), ("text", "send to me"), ("text", "ok")):
        k += 1
        events.append({"kind": kind, "message_id": f"false_{CHAT}_TX{k:03d}", "text": what,
                       "quoted": "", "at": T0 + timedelta(seconds=20 * k)})
    for i, it in enumerate(items, start=1):
        pid = f"P-588-{i + 5}"
        att.append({"_id": f"att{i}", "punch_id": pid})
        rows.append({"_id": f"p588:{pid}", "pid": pid, "n": it["n"], "walk_id": "w588",
                     "send_mode": "shadow", "attention_item_id": f"att{i}", "status": "open"})
    sess = {"_id": "w588", "user_id": "u_roy", "company_id": CO, "chat": CHAT, "project_id": "p588",
            "job_name": "588 Thomas St", "job_code": "588", "status": "sent", "items": items,
            "created_at": T0, "sent_at": T0 + timedelta(minutes=40), "send_mode": "shadow",
            "detail": "simple", "group_loc_v2": True}
    return sess, events, rows, att


class ThisWalkPutRight(_Batch):

    def _load(self):
        sess, events, rows, att = _old_walk()
        self.db[punch.SESSIONS].rows.append(sess)
        self.db[punch.COLLECTION].rows.extend(rows)
        self.db["attention_items"].rows.extend(att)
        return events, rows

    def _run(self, coro):
        return super()._run(coro)

    def test_a_dry_run_changes_nothing(self):
        events, rows = self._load()
        lines = []
        out = self._run(server.punch_walk_rebatch("w588", apply=False, events=events, say=lines.append))
        self.assertTrue(out["ok"])
        self.assertEqual((out["kept"], out["removed"], out["rows"]), (47, 1, 48))
        self.assertEqual(self.sess()["status"], "sent")
        self.assertEqual(len(self.db[punch.COLLECTION].rows), 48)
        # The dry run shows the real draft: vision's words on photos with
        # none, "(auto)" -- in memory only (Wed Oct 14).
        self.assertTrue(self.described)
        self.assertIn("(auto)", out["draft"])
        self.assertFalse(any(it.get("text_auto") for it in self.sess()["items"]))
        log = "\n".join(lines)
        self.assertIn("text 'Last 8 pics all interior'\n           -> #11–#18: Interior", log)

    def test_applied_the_draft_is_right_and_nothing_is_sent(self):
        events, rows = self._load()
        out = self._run(server.punch_walk_rebatch("w588", apply=True, events=events, dm=True))
        self.assertTrue(out["ok"], out)
        s = self.sess()
        self.assertEqual(s["status"], "draft")
        _expect_walk(self, s["items"])
        # The text-made item is gone; every photo keeps its P-id.
        self.assertNotIn(99, [it["n"] for it in s["items"]])
        pid_of = {r["n"]: r["pid"] for r in rows}
        self.assertEqual({it["n"]: it["pid"] for it in s["items"]}, {n: pid_of[n] for n in range(1, 48)})
        # The shadow rows and their attention items: gone.
        self.assertEqual(self.db[punch.COLLECTION].rows, [])
        self.assertEqual(self.db["attention_items"].rows, [])
        # The corrected draft, by DM -- before any send.
        (dm,) = self.said
        self.assertTrue(dm.startswith("I re-read your walkthrough at 588 Thomas St"), dm)
        self.assertIn("Nothing was sent.", dm)
        self.assertIn("(draft)", dm)
        self.assertNotIn("Last 8 pics", dm)

    def test_sent_again_keeps_the_ids(self):
        events, rows = self._load()
        self._run(server.punch_walk_rebatch("w588", apply=True, events=events))
        self.turn("send to me")
        (sent,) = self.turn("go ahead")
        self.assertTrue(sent.startswith("Punch sends are in shadow mode"), sent)
        self.assertEqual(sorted(r["pid"] for r in self.db[punch.COLLECTION].rows),
                         sorted(r["pid"] for r in rows if r["n"] != 99))

    def test_an_explicit_add_is_kept(self):
        # Codex on #785: "add: ..." is still an item under the new rule.
        events, rows = self._load()
        s = self.sess()
        mid = f"false_{CHAT}_ADD1"
        s["items"].append({"n": 48, "captured": 47.5, "text": "Missing access ladder", "photo_key": None,
                           "message_id": mid, "added": True, "floor": punch.UNKNOWN,
                           "area": punch.UNKNOWN, "trade": punch.UNKNOWN})
        events.insert(-3, {"kind": "text", "message_id": mid, "text": "add: missing access ladder",
                           "quoted": "", "at": T0 + timedelta(minutes=30)})
        out = self._run(server.punch_walk_rebatch("w588", apply=True, events=events))
        self.assertEqual((out["kept"], out["removed"]), (48, 1))
        self.assertIn("Missing access ladder", [it["text"] for it in self.sess()["items"]])

    def test_a_voice_note_is_replayed_as_its_words(self):
        # Codex on #785: the log has no transcript; the item the old rule put
        # it on does.
        events, rows = self._load()
        s = self.sess()
        last = next(it for it in s["items"] if it["n"] == 47)
        vid = f"false_{CHAT}_VO1"
        last.update(text="Paint scuffs in hallway", caption_ids=[vid],
                    voice={"transcript": "paint scuffs in hallway", "lang": "en"})
        events.insert(-3, {"kind": "voice", "message_id": vid, "text": "", "quoted": "",
                           "at": T0 + timedelta(minutes=31)})
        out = self._run(server.punch_walk_rebatch("w588", apply=True, events=events))
        self.assertTrue(out["ok"])
        by_n = {it["n"]: it for it in self.sess()["items"]}
        for n in range(33, 48):                      # the 15 photos it was about
            self.assertEqual((by_n[n]["text"], by_n[n]["area"], by_n[n].get("text_auto")),
                             ("Paint scuffs", "hallway", None), n)

    def test_a_live_walk_is_never_touched(self):
        events, rows = self._load()
        for r in self.db[punch.COLLECTION].rows:
            r["send_mode"] = "live"
        out = self._run(server.punch_walk_rebatch("w588", apply=True, events=events))
        self.assertFalse(out["ok"])
        self.assertIn("LIVE", out["why"])
        self.assertEqual(self.sess()["status"], "sent")
        self.assertEqual(len(self.db[punch.COLLECTION].rows), 48)


class TheLogIsRead(unittest.TestCase):

    def test_a_text_and_a_cut_off_photo(self):
        text = {"event": "message", "data": {"message": {
            "id": {"fromMe": False, "remote": CHAT, "id": "TX1", "_serialized": f"false_{CHAT}_TX1"},
            "from": CHAT, "to": "15550000000@c.us", "body": "Last 8 pics all interior", "type": "chat",
            "timestamp": 1760382000, "_data": {}, "hasMedia": False, "fromMe": False,
            "hasQuotedMsg": False}}}
        e = server._wa_log_event({"raw_body_preview": json.dumps(text), "received_at": T0})
        self.assertEqual((e["kind"], e["text"], e["chat"], e["from_me"]),
                         ("text", "Last 8 pics all interior", CHAT, False))
        cut = ('{"event":"message","data":{"message":{"id":{"fromMe":false,"remote":"' + CHAT
               + '","id":"PH1","_serialized":"false_' + CHAT + '_PH1"},"from":"' + CHAT
               + '","type":"image","body":"/9j/4AAQSkZJRg' + "A" * 4000)[:4000]
        e = server._wa_log_event({"raw_body_preview": cut, "received_at": T0})
        self.assertEqual((e["kind"], e["message_id"], e["chat"]), ("photo", f"false_{CHAT}_PH1", CHAT))

    def test_only_the_walkers_messages_in_the_walk(self):
        from tests._fake_mongo import FakeDb

        def row(chat, mid, at, me=False):
            body = {"event": "message", "data": {"message": {
                "id": {"fromMe": me, "remote": chat, "id": mid, "_serialized": f"{str(me).lower()}_{chat}_{mid}"},
                "from": chat, "to": "x@c.us", "body": "hello", "type": "chat", "timestamp": 1,
                "_data": {}, "hasMedia": False, "fromMe": me, "hasQuotedMsg": False}}}
            return {"_id": mid, "raw_body_preview": json.dumps(body), "received_at": at}
        db = FakeDb(whatsapp_webhook_log=[
            row(CHAT, "A", T0 + timedelta(minutes=1)), row("19998887777@c.us", "B", T0 + timedelta(minutes=2)),
            row(CHAT, "C", T0 + timedelta(minutes=3), me=True), row(CHAT, "D", T0 - timedelta(hours=2)),
            row(CHAT, "A", T0 + timedelta(minutes=1))])
        sess = {"chat": CHAT, "created_at": T0, "sent_at": T0 + timedelta(minutes=30)}
        got = asyncio.run(server._punch_walk_events(sess, db))
        self.assertEqual([e["message_id"] for e in got], [f"false_{CHAT}_A"])


if __name__ == "__main__":
    unittest.main()
