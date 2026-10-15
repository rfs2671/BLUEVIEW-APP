"""Project → WhatsApp → Voice log (admins).

Every voice note of a job, newest first: its groups' notes and DM voice notes
answered about it. Per note: when, who (a name, never a number), where,
language, confidence, what was said and its English, status (transcribed /
flagged / not processed and why), forwarded, audio kept, and what it
PRODUCED: an Attention item, an Upcoming event, or nothing. Filters: sender,
language, status.

DM voice notes carry their company and, once answered about a job, the job
(the event used to be stored with company_id None and nothing else).
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")

import server  # noqa: E402
from lib import wa_voice  # noqa: E402
from tests.test_voice_notes_in_dm import AT, CO_A, PID, ROWS, _note, _world  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _Ctx, _run  # noqa: E402

ADMIN = {"_id": "u_admin", "id": "u_admin", "company_id": CO_A, "role": "admin",
         "account_status": "approved"}
PM = {"_id": "u_pm", "id": "u_pm", "company_id": CO_A, "role": "pm",
      "account_status": "approved", "assigned_projects": [PID]}


def _full_world():
    failed = dict(_note(4, "(voice note — not processed)", 30), skipped="voice_too_short")
    failed["voice"] = {"transcript": "", "failed": "too_short", "review": True,
                       "audio_key": "wa-audio/p/g/M4.ogg"}
    with_audio = dict(ROWS[1])
    with_audio["voice"] = dict(ROWS[1]["voice"], audio_key="wa-audio/p/g/M2.ogg")
    db = _world(ROWS[0], with_audio, ROWS[2], failed)
    db.attention_items.rows.append({
        "_id": "a1", "project_id": PID, "company_id": CO_A, "type": "question",
        "status": "open", "summary": "Any inspection coming up for electricity?",
        "evidence": {"message_row_id": "v2"}})
    db.upcoming_events.rows.append({
        "_id": "e1", "project_id": PID, "company_id": CO_A, "title": "Concrete delivery",
        "date": "2026-10-12", "status": "open", "source_ref": "v1"})
    db.whatsapp_voice_events.rows.extend([
        {"_id": "d1", "where": "dm", "company_id": CO_A, "project_id": PID,
         "user_id": "u_roy", "sender": "15550009999",
         "original_transcript": "What was said on the last voicenote on 588 group",
         "english_transcript": "What was said on the last voicenote on 588 group",
         "language_detected": "english", "lang": "en", "confidence": 0.95,
         "duration_sec": 3.2, "error_kind": None, "received_at": AT + timedelta(minutes=1)},
        # Another job's DM note, another company's: not listed.
        {"_id": "d2", "where": "dm", "company_id": CO_A, "project_id": "proj_b",
         "original_transcript": "x", "received_at": AT},
        {"_id": "d3", "where": "dm", "company_id": "co_b", "project_id": PID,
         "original_transcript": "y", "received_at": AT}])
    db.users.rows.append({"_id": "u_roy", "company_id": CO_A, "name": "Roy"})
    return db


class TheLog(unittest.TestCase):

    def _get(self, user=ADMIN, db=None, **filters):
        async def scope(company_id, project_id):
            return {"_id": PID, "company_id": CO_A}
        db = db or _full_world()
        with _Ctx(db), patch.object(server, "_bot_project_scope", scope):
            return _run(server.get_project_voice_log(
                PID, filters.get("sender", ""), filters.get("lang", ""),
                filters.get("status", ""), filters.get("before", ""),
                filters.get("limit", server.VOICE_LOG_PAGE), filters.get("media", ""),
                current_user=user))

    def test_group_photos_are_in_the_log(self):
        db = _full_world()
        db.whatsapp_messages.rows.append({
            "_id": "ph1", "project_id": PID, "company_id": CO_A, "group_id": ROWS[0]["group_id"],
            "sender": "15550001111", "sender_name": "Yoel", "has_audio": False,
            "timestamp": AT + timedelta(minutes=5), "created_at": AT + timedelta(minutes=5),
            "photo": {"key": "wa-group-photos/c/p/ph1.jpg", "quality": "original",
                      "caption": "3rd floor framing", "sender_company": "Arkon Builders",
                      "vision": {"ok": True, "kind": "progress", "score": 8,
                                 "caption": "Metal stud framing"}}})
        with patch.object(server, "_presign_r2_get", lambda k, s: f"https://r2/{k}"):
            both = self._get(db=db)
            photos = self._get(db=db, media="photo")
            voice = self._get(db=db, media="voice")
        self.assertEqual(both["notes"][0]["id"], "ph1")                  # newest first
        self.assertEqual([n["id"] for n in photos["notes"]], ["ph1"])
        ph = photos["notes"][0]
        self.assertEqual((ph["kind"], ph["company"], ph["caption"], ph["seen"], ph["photo_url"]),
                         ("photo", "Arkon Builders", "3rd floor framing", "Metal stud framing",
                          "https://r2/wa-group-photos/c/p/ph1.jpg"))
        self.assertNotIn("ph1", [n["id"] for n in voice["notes"]])
        with self.assertRaises(HTTPException):
            self._get(db=db, media="video")

    def test_every_note_newest_first_with_dm(self):
        out = self._get()
        self.assertEqual([n["id"] for n in out["notes"]], ["d1", "v3", "v2", "v4", "v1"])
        self.assertEqual((out["scanned"], out["next_before"]), (5, None))   # read to the end
        dm = out["notes"][0]
        self.assertEqual((dm["where"], dm["place"], dm["who"], dm["status"], dm["audio"]),
                         ("dm", "DM", "Roy", "transcribed", False))
        self.assertEqual(dm["produced"], [])

    def test_a_note_says_what_it_produced(self):
        by = {n["id"]: n for n in self._get()["notes"]}
        self.assertEqual(by["v2"]["produced"], [
            {"kind": "item", "id": "a1", "type": "question",
             "label": "Any inspection coming up for electricity?", "status": "open"}])
        self.assertEqual(by["v1"]["produced"], [
            {"kind": "event", "id": "e1", "label": "Concrete delivery", "date": "2026-10-12",
             "status": "open"}])
        self.assertEqual(by["v3"]["produced"], [])

    def test_status_language_forwarded_audio(self):
        by = {n["id"]: n for n in self._get()["notes"]}
        self.assertEqual((by["v3"]["status"], by["v3"]["lang"], by["v3"]["forwarded"]),
                         ("flagged", "yi", True))
        self.assertEqual(by["v3"]["english"], "We pour the foundation tomorrow")
        self.assertEqual((by["v4"]["status"], by["v4"]["reason"]),
                         ("not_processed", "shorter than 2 seconds"))
        self.assertTrue(by["v4"]["audio"] and by["v2"]["audio"])
        self.assertFalse(by["v1"]["audio"])
        self.assertEqual((by["v2"]["status"], by["v2"]["english"]), ("transcribed", ""))
        self.assertEqual(by["v2"]["place"], "588 – Site")
        for n in by.values():
            self.assertNotIn("15550007788", str(n))

    def test_filters(self):
        self.assertEqual([n["id"] for n in self._get(sender="meilich")["notes"]],
                         ["v2", "v4", "v1"])
        self.assertEqual([n["id"] for n in self._get(lang="yi")["notes"]], ["v3"])
        self.assertEqual([n["id"] for n in self._get(status="not_processed")["notes"]], ["v4"])
        out = self._get(status="flagged")
        self.assertEqual(([n["id"] for n in out["notes"]], out["scanned"]), (["v3"], 5))
        self.assertEqual(out["facets"]["langs"], ["en", "yi"])
        with self.assertRaises(HTTPException) as e:
            self._get(status="bogus")
        self.assertEqual(e.exception.status_code, 422)

    def test_admins_only(self):
        with self.assertRaises(HTTPException) as e:
            self._get(user=PM)
        self.assertEqual(e.exception.status_code, 403)


class CodexReviewOn751(TheLog):
    """Filters run while reading, past the first page; next_before continues."""

    def _busy_world(self):
        db = _full_world()
        # 250 newer notes from Dave, all after Meilich's: one filtered read
        # must reach past them.
        for i in range(250):
            db.whatsapp_messages.rows.append(dict(
                _note(1000 + i, f"Dave {i}", -(i + 2), sender="15550004444", name="Dave"),
                timestamp=AT + timedelta(minutes=i + 2), created_at=AT + timedelta(minutes=i + 2)))
        return db

    def test_a_filter_finds_an_old_note_past_the_newest_pages(self):
        out = self._get(db=self._busy_world(), sender="meilich")
        self.assertEqual([n["id"] for n in out["notes"]], ["v2", "v4", "v1"])
        self.assertIsNone(out["next_before"])

    def test_pages_continue_without_gaps_or_repeats(self):
        db = self._busy_world()
        seen, before = [], ""
        for _ in range(10):
            out = self._get(db=db, limit=80, before=before)
            seen += [f"{n['where']}-{n['id']}" for n in out["notes"]]
            before = out["next_before"]
            if not before:
                break
        self.assertEqual(len(seen), 255)
        self.assertEqual(len(set(seen)), 255)

    def test_a_note_stored_while_the_bot_was_off_is_listed(self):
        db = _full_world()
        off = dict(_note(8, "", 2), voice=None)
        off.pop("transcribed", None)
        off["body"] = ""
        db.whatsapp_messages.rows.append(off)
        by = {n["id"]: n for n in self._get(db=db)["notes"]}
        self.assertEqual((by["v8"]["status"], by["v8"]["reason"]),
                         ("not_processed", wa_voice.BOT_OFF_REASON))

    def test_a_bad_cursor(self):
        with self.assertRaises(HTTPException) as e:
            self._get(before="yesterday")
        self.assertEqual(e.exception.status_code, 422)


class ADmVoiceNoteIsStamped(unittest.TestCase):

    def test_the_job_it_was_answered_about(self):
        db = _world()
        db.whatsapp_voice_events.rows.append(
            {"_id": "d1", "where": "dm", "company_id": CO_A,
             "message_id_serialized": "false_15550009999@c.us_ABC"})

        async def answer():
            return "Last voice note: …"

        async def log(*a, **k):
            return None

        async def send(*a, **k):
            return {"ok": True}
        with _Ctx(db), patch.object(server, "_dm_log_answer", log), \
                patch.object(server, "send_whatsapp_message", send):
            _run(server._dm_send_answer("15550009999@c.us", "false_15550009999@c.us_ABC",
                                        answer(), heard="what was the last voice note",
                                        log=({}, PID, "q", "job_agent")))
        self.assertEqual(db.whatsapp_voice_events.rows[0]["project_id"], PID)

    def test_a_headcount_answer_stamps_its_job_too(self):
        db = _world()
        db.whatsapp_voice_events.rows.append(
            {"_id": "d1", "where": "dm", "company_id": CO_A, "message_id_serialized": "HC1"})

        async def answer():
            return "6 workers on site at 588."

        async def noop(*a, **k):
            return None
        with _Ctx(db), patch.object(server, "send_whatsapp_message", noop):
            _run(server._dm_send_answer("c", "HC1", answer(), heard="how many workers at 588",
                                        project_id=PID))
        self.assertEqual(db.whatsapp_voice_events.rows[0]["project_id"], PID)
        import inspect
        src = inspect.getsource(server._dm_assistant_reply)
        self.assertEqual(src.count("_dm_answer_headcount("), src.count("project_id=str("))

    def test_a_typed_question_stamps_nothing(self):
        db = _world()
        db.whatsapp_voice_events.rows.append(
            {"_id": "d1", "where": "dm", "company_id": CO_A,
             "message_id_serialized": "MID"})

        async def answer():
            return "ok"

        async def noop(*a, **k):
            return None
        with _Ctx(db), patch.object(server, "_dm_log_answer", noop), \
                patch.object(server, "send_whatsapp_message", noop):
            _run(server._dm_send_answer("c", "MID", answer(), heard=None,
                                        log=({}, PID, "q", "job_agent")))
        self.assertNotIn("project_id", db.whatsapp_voice_events.rows[0])

    def test_the_dm_event_carries_its_company(self):
        import inspect
        src = inspect.getsource(server._process_whatsapp_message)
        self.assertEqual(src.count('"where":              "dm"') + src.count('"where":      "dm"'), 2)
        self.assertNotIn('"company_id":         None,  # filled below', src)


class ThePureRows(unittest.TestCase):

    def test_status(self):
        self.assertEqual(wa_voice.log_status({"review": True, "review_reason": "yiddish"}),
                         {"status": "flagged", "reason": "yiddish"})
        self.assertEqual(wa_voice.log_status({}, "voice_cap")["status"], "not_processed")
        self.assertEqual(wa_voice.log_status(None, None, "prompt_echo"),
                         {"status": "not_processed",
                          "reason": wa_voice.not_processed("prompt_echo")})
        self.assertEqual(wa_voice.log_status({"lang": "en"})["status"], "transcribed")

    def test_a_dm_failure(self):
        r = wa_voice.log_row_dm({"_id": "d", "error_kind": "low_confidence"}, who="Roy", at=None)
        self.assertEqual((r["status"], r["reason"]), ("not_processed", "no words were heard"))


if __name__ == "__main__":
    unittest.main()
