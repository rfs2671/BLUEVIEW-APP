"""A group's "Languages spoken" (en / es / yi), and Yiddish notes to review
grouped in Attention.

- bot_config.languages: a list of en/es/yi (empty: any), set on the group's
  settings. One language: Whisper's hint for a sender with none of their own.
  A note heard in a language the group does not speak (a Yiddish group's
  note "heard" as English) is flagged for review and gets Whisper's English
  of the audio.
- Attention: three or more open Yiddish voice notes to review in one group on
  one day are one row, "5 Yiddish voice notes to review", each note inside
  with ▶ Play and its English; fewer stay one row each.
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
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_voice_hallucination import BLESSING_EN, The257NoteInTheGroup  # noqa: E402
from tests.test_whatsapp_phase0_security import CO_A, _group_row  # noqa: E402
from tests.test_whatsapp_phase1_foundations import _run  # noqa: E402

ADMIN = {"id": "u", "company_id": CO_A, "role": "admin"}
CLEAN_EN = {"text": "Concrete truck is at the gate", "language": "english", "duration": 4.0,
            "segments": [{"start": 0, "end": 4, "avg_logprob": -0.21, "no_speech_prob": 0.02,
                          "compression_ratio": 1.1}]}


class TheSetting(unittest.TestCase):

    def test_the_pure_rules(self):
        self.assertEqual(wa_voice.group_languages(["yi", "en", "yi"]), ["en", "yi"])
        self.assertEqual(wa_voice.group_languages([]), [])
        for bad in (["fr"], "yi", None, [1]):
            self.assertIsNone(wa_voice.group_languages(bad), bad)
        self.assertEqual(wa_voice.group_hint(["es"]), "es")
        self.assertIsNone(wa_voice.group_hint(["en", "yi"]))
        self.assertIsNone(wa_voice.group_hint([]))
        self.assertTrue(wa_voice.heard_outside("en", ["yi"]))
        self.assertFalse(wa_voice.heard_outside("yi", ["yi"]))
        self.assertFalse(wa_voice.heard_outside("en", []))          # none set: any

    def test_saved_on_the_group(self):
        db = FakeDb(whatsapp_groups=[_group_row(CO_A, "proj_a", _id="g1")])
        with patch.object(server, "db", db):
            out = _run(server.whatsapp_update_group_config(
                "g1", {"languages": ["yi", "en"]}, ADMIN))
            self.assertEqual(out["bot_config"]["languages"], ["en", "yi"])
            with self.assertRaises(HTTPException) as e:
                _run(server.whatsapp_update_group_config("g1", {"languages": ["fr"]}, ADMIN))
            self.assertEqual(e.exception.status_code, 422)
        self.assertEqual(server._default_bot_config()["languages"], [])
        self.assertEqual(server._effective_bot_config({})["languages"], [])


class InAGroup(The257NoteInTheGroup):
    """The webhook, Whisper's parsing, the group's languages."""

    langs = None
    # The 2:57 PM tests run in their own file, not again here.
    test_kept_for_review_silently_never_as_words = None
    test_the_dm_reads_it_as_not_reliably_transcribed = None
    test_a_clean_english_note_is_untouched = None
    test_a_sender_set_to_yiddish_gets_the_translation_and_a_flag = None
    test_heard_as_german_or_hebrew = None

    #: How alike Whisper's English and its direct English are (embeddings).
    similarity = 0.95

    def _db(self):
        db = super()._db()
        if self.langs is not None:
            db.whatsapp_groups.rows[0]["bot_config"]["languages"] = self.langs
        return db

    def _deliver(self, *a, **kw):
        self.embedded = []

        async def embed(texts):
            self.embedded.append(list(texts))
            s = self.similarity
            return None if s is None else [[1.0, 0.0], [s, (1 - s * s) ** 0.5]]
        with patch.object(server, "_memory_embed_many", embed):
            return super()._deliver(*a, **kw)

    def _row(self):
        (row,) = [r for r in self.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        return row

    def test_a_yiddish_group_flags_a_note_heard_as_english(self):
        # The words agree with the audio's English, but the group speaks
        # only Yiddish: for a person.
        self.langs, self.translation = ["yi"], CLEAN_EN["text"]
        self._deliver(CLEAN_EN, forwarded=False)
        row = self._row()
        self.assertTrue(row["voice"]["review"])
        self.assertEqual(row["voice"]["review_reason"], "heard_en_not_spoken_here")
        self.assertEqual(row["voice"]["english_direct"], CLEAN_EN["text"])

    def _flagged(self):
        (rev,) = self.reviews()
        self.assertEqual(rev["voice_failure"], "unreliable")
        row = self._row()
        self.assertEqual(row["skipped"], "voice_unreliable")
        self.assertEqual(self.group_posts(), [])
        self.assertEqual(self.agent_calls, [])
        return rev, row

    def test_an_english_group_leaves_it_alone(self):
        self.langs = ["en", "es"]
        self._deliver(CLEAN_EN, forwarded=False)
        self.assertFalse(self._row()["voice"]["review"])
        self.assertEqual(self.translations, [])

    def test_one_language_is_the_hint(self):
        self.langs = ["es"]
        got = {}
        from lib import voice_ingest
        real_process = voice_ingest.process_voice_note

        async def process(audio, **kw):
            got.update(kw)
            return await real_process(audio, **kw)
        with patch.object(voice_ingest, "process_voice_note", process):
            self._deliver(CLEAN_EN, forwarded=False)
        self.assertEqual(got.get("language"), "es")

    def test_a_senders_own_language_wins(self):
        self.langs = ["es"]
        got = {}
        from lib import voice_ingest
        real_process = voice_ingest.process_voice_note

        async def process(audio, **kw):
            got.update(kw)
            return await real_process(audio, **kw)
        with patch.object(voice_ingest, "process_voice_note", process):
            self._deliver(CLEAN_EN, forwarded=False, sender_lang="en")
        self.assertEqual(got.get("language"), "en")


class AnEnglishAndYiddishGroup(InAGroup):
    """588 is EN+YI. Every note also goes straight to English; a note heard as
    English whose direct English says something else is not what was said."""

    langs = ["en", "yi"]
    test_a_yiddish_group_flags_a_note_heard_as_english = None
    test_an_english_group_leaves_it_alone = None
    test_one_language_is_the_hint = None
    test_a_senders_own_language_wins = None

    def test_the_257_clip_is_flagged(self):
        # Forwarded Williamsburg Yiddish, labeled English by Whisper.
        self._deliver()
        rev, row = self._flagged()
        self.assertEqual(self.translations, [b"OggS"])
        self.assertEqual(row["voice"]["english_direct"], BLESSING_EN)
        self.assertNotIn("People speaking", rev["evidence"]["quote"])

    def test_the_257_clip_with_fluent_english_words_is_flagged_too(self):
        # The same audio, had Whisper made up a plausible sentence instead of
        # describing it: nothing in its scores or words gives it away; the
        # direct English does.
        self.similarity = 0.31
        self._deliver(dict(CLEAN_EN, text="I'll be at the house on Tuesday"))
        rev, row = self._flagged()
        self.assertEqual(self.embedded, [["I'll be at the house on Tuesday", BLESSING_EN]])
        (why,) = row["voice"]["unreliable"]
        self.assertIn(wa_voice.DIVERGED, why)

    def test_an_english_note_that_agrees_is_untouched(self):
        self.translation = "The concrete truck is at the gate"
        self._deliver(CLEAN_EN, forwarded=False)
        self.assertEqual(self.reviews(), [])
        row = self._row()
        self.assertFalse(row["voice"]["review"])
        self.assertEqual(row["voice"]["english_direct"], "The concrete truck is at the gate")
        self.assertEqual(self.translations, [b"OggS"])        # every note, any language

    def test_no_translation_or_no_comparison_is_flagged(self):
        self.translation = ""
        self._deliver(CLEAN_EN, forwarded=False)
        self.assertEqual(self._flagged()[1]["voice"]["unreliable"],
                         ["no direct translation of the audio"])
        self.similarity, self.translation = None, CLEAN_EN["text"]
        self._deliver(CLEAN_EN, forwarded=False)
        self._flagged()

    def test_no_hint(self):
        got = {}
        from lib import voice_ingest
        real_process = voice_ingest.process_voice_note

        async def process(audio, **kw):
            got.update(kw)
            return await real_process(audio, **kw)
        self.translation = CLEAN_EN["text"]
        with patch.object(voice_ingest, "process_voice_note", process):
            self._deliver(CLEAN_EN, forwarded=False)
        self.assertIsNone(got.get("language"))


class AForwardedNote(InAGroup):
    """Someone else's voice: the forwarder's own language is not used."""

    test_a_yiddish_group_flags_a_note_heard_as_english = None
    test_an_english_group_leaves_it_alone = None
    test_one_language_is_the_hint = None
    test_a_senders_own_language_wins = None

    def test_the_group_decides_not_the_forwarder(self):
        self.langs = ["es"]
        got = {}
        from lib import voice_ingest
        real_process = voice_ingest.process_voice_note

        async def process(audio, **kw):
            got.update(kw)
            return await real_process(audio, **kw)
        with patch.object(voice_ingest, "process_voice_note", process):
            self._deliver(CLEAN_EN, forwarded=True, sender_lang="yi")
        self.assertEqual(got.get("language"), "es")
        # Not "sender_yiddish": the forwarder's Yiddish is not the note's.
        self.assertNotEqual(self._row()["voice"].get("review_reason"), "sender_yiddish")

    def test_typed_by_the_sender_their_language_still_counts(self):
        self.langs = ["es"]
        self._deliver(CLEAN_EN, forwarded=False, sender_lang="yi")
        self.assertEqual(self._row()["voice"]["review_reason"], "sender_yiddish")


class TheDivergenceRule(unittest.TestCase):

    def test_the_pure_rule(self):
        self.assertTrue(wa_voice.translates_every_note(["en", "yi"]))
        self.assertFalse(wa_voice.translates_every_note(["en", "es"]))
        self.assertFalse(wa_voice.translates_every_note([]))
        self.assertIsNone(wa_voice.diverged("a", "b", 0.75))
        self.assertIn(wa_voice.DIVERGED, wa_voice.diverged("a", "b", 0.74))
        self.assertEqual(wa_voice.diverged("a", "  ", 0.99), "no direct translation of the audio")
        self.assertTrue(wa_voice.diverged("a", "b", None))


class SettingA588(unittest.TestCase):
    """scripts/group_languages_set.py: 588 is set to EN+YI by a run, not code."""

    def _run_script(self, *argv):
        from scripts import group_languages_set as s
        db = FakeDb(projects=[{"_id": "proj_a", "name": "588 Bedford", "company_id": CO_A}],
                    whatsapp_groups=[_group_row(CO_A, "proj_a", _id="g1"),
                                     _group_row(CO_A, "proj_b", _id="g2")])
        with patch("builtins.print"):
            s.main(["--project", "proj_a", *argv], db=db)
        return db

    def test_dry_run_writes_nothing_and_i_know_writes_and_audits(self):
        db = self._run_script("--langs", "en,yi")
        self.assertEqual(db.whatsapp_groups.rows[0]["bot_config"]["languages"], [])
        self.assertEqual(db.audit_logs.rows, [])
        db = self._run_script("--langs", "yi,en", "--i-know", "--reason", "588 is EN+YI",
                              "--session", "s1")
        self.assertEqual(db.whatsapp_groups.rows[0]["bot_config"]["languages"], ["en", "yi"])
        self.assertEqual(db.whatsapp_groups.rows[1]["bot_config"]["languages"], [])   # not 588
        self.assertTrue(db.audit_logs.rows)
        self.assertIn("588 is EN+YI", str(db.audit_logs.rows))
        with self.assertRaises(SystemExit):
            self._run_script("--langs", "en,fr", "--i-know", "--reason", "x", "--session", "s1")
        with self.assertRaises(SystemExit):
            self._run_script("--langs", "en,yi", "--apply")        # the old flag: refused


def _yid_item(i, group="g1", minutes=0, verdict=None, lang="yi"):
    at = datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return {"_id": f"a{i}", "project_id": "proj_a", "company_id": CO_A, "group_id": group,
            "type": "voice_review", "status": "open", "needs_review": True,
            "summary": "Voice note not processed — not reliably transcribed",
            "review": {"verdict": verdict} if verdict else None, "created_at": at,
            "evidence": {"kind": "voice", "lang": lang, "message_row_id": f"r{i}",
                         "sent_at": at, "sender_last4": "1234", "forwarded": i == 1},
            "history": []}


class TheBatches(unittest.TestCase):

    def _list(self, items, rows=()):
        db = FakeDb(attention_items=list(items), whatsapp_messages=list(rows),
                    whatsapp_groups=[{"_id": "G1", "wa_group_id": "g1", "project_id": "proj_a",
                                      "company_id": CO_A, "group_name": "588 – Site"},
                                     {"_id": "G2", "wa_group_id": "g2", "project_id": "proj_a",
                                      "company_id": CO_A, "group_name": "588 – Office"}])

        async def admin(project_id, user):
            return CO_A
        with patch.object(server, "db", db), \
                patch.object(server, "_attention_admin_project", admin):
            return _run(server.get_project_attention("proj_a", "open", current_user=ADMIN))

    def test_three_or_more_in_a_group_on_a_day_are_one_row(self):
        rows = [{"_id": f"r{i}", "company_id": CO_A, "project_id": "proj_a",
                 "voice": {"lang": None, "english_direct": f"Blessing {i}",
                           "audio_key": f"k{i}"}} for i in range(5)]
        out = self._list([_yid_item(i, minutes=i) for i in range(5)], rows)
        self.assertEqual(out["items"], [])
        (b,) = out["voice_batches"]
        self.assertEqual((b["label"], b["group_name"], b["day"], b["count"]),
                         ("5 Yiddish voice notes to review", "588 – Site", "2026-10-11", 5))
        self.assertEqual([i["english"] for i in b["items"]],
                         [f"Blessing {i}" for i in range(5)])
        self.assertTrue(all(i["audio"] for i in b["items"]))

    def test_two_stay_one_row_each_and_groups_and_days_are_apart(self):
        items = ([_yid_item(i, minutes=i) for i in range(2)]                       # g1, 2
                 + [_yid_item(10 + i, group="g2", minutes=i) for i in range(3)]    # g2, 3
                 + [_yid_item(20 + i, minutes=24 * 60 + i) for i in range(3)])     # g1 next day
        out = self._list(items)
        self.assertEqual(sorted(i["id"] for i in out["items"]), ["a0", "a1"])
        self.assertEqual([(b["group_name"], b["day"], b["count"]) for b in out["voice_batches"]],
                         [("588 – Site", "2026-10-12", 3), ("588 – Office", "2026-10-11", 3)])

    def test_reviewed_or_not_yiddish_are_not_batched(self):
        items = ([_yid_item(i, minutes=i) for i in range(2)]
                 + [_yid_item(5, verdict="correct"), _yid_item(6, lang="es")])
        out = self._list(items)
        self.assertEqual(out["voice_batches"], [])
        self.assertEqual(len(out["items"]), 3)        # the reviewed one is not open
        # And in the pure rule: a verdict takes a note out of a batch.
        views = [{"voice": True, "needs_review": True, "lang": "yi", "status": "open",
                  "group_name": "g", "sent_at": "2026-10-11T18:00:00+00:00", "id": str(i),
                  "verdict": "correct" if i == 0 else None} for i in range(3)]
        batches, rest = wa_voice.yiddish_batches(views)
        self.assertEqual((batches, len(rest)), ([], 3))


if __name__ == "__main__":
    unittest.main()
