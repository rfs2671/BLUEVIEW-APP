"""Voice notes and English / Spanish / Yiddish understanding.

- lib/multilang.py: day words in all three languages read by the SAME
  resolvers and never-guess rules; state-change, ack and sarcasm words.
- lib/wa_voice.py: the review rule, language codes, the row's voice block.
- The group webhook: a voice note is stored as said (with language,
  confidence, duration, the R2 audio key), the assistant answers from the
  English, the daily cap holds.
- Unsure voice (Yiddish, or low confidence): flagged, never changes state.
- The dry runs: Spanish scenarios pass scripted; Yiddish placeholders refuse
  to run.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")

import server  # noqa: E402
from lib import multilang as ml  # noqa: E402
from lib import upcoming as u  # noqa: E402
from lib import voice_ingest  # noqa: E402
from lib import wa_attention as wa  # noqa: E402
from lib import wa_attention_state as st  # noqa: E402
from lib import wa_voice  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    CO_A, GROUP, PM_PHONE, _Ctx, _db, _run,
)

FRI = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)     # Fri 10am New York
TUE = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)     # Tue 10am
THU = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)     # Thu 10am
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class SpanishAndYiddishDays(unittest.TestCase):
    """Normalized to English, then the same resolver: the same rules."""

    def test_next_weekday_follows_the_english_rule(self):
        # Said Friday: the coming Tuesday. Said Tuesday: ambiguous, skipped.
        self.assertEqual(u.resolve_when("el próximo martes a las 10am", FRI),
                         {"date": date(2026, 10, 13), "time": "10:00"})
        self.assertEqual(u.resolve_when("el próximo martes", TUE), {"skip": "ambiguous"})
        self.assertEqual(u.resolve_when("el martes que viene", FRI)["date"], date(2026, 10, 13))
        self.assertEqual(u.resolve_when("nekhstn dinstik", FRI)["date"], date(2026, 10, 13))
        self.assertEqual(u.resolve_when("nekhstn dinstik", TUE), {"skip": "ambiguous"})

    def test_this_and_bare_weekday(self):
        self.assertEqual(u.resolve_when("este viernes", THU)["date"], date(2026, 10, 9))
        self.assertEqual(u.resolve_when("el viernes", FRI), {"skip": "ambiguous"})   # same day
        self.assertEqual(u.resolve_when("el lunes", TUE)["date"], date(2026, 10, 12))
        self.assertEqual(u.resolve_when("פרייטיק", TUE)["date"], date(2026, 10, 9))

    def test_relative_days(self):
        cases = {"hoy": 0, "mañana": 1, "pasado mañana": 2, "en 3 semanas": 21,
                 "en tres semanas": 21, "en 10 días": 10, "haynt": 0, "morgn": 1,
                 "ibermorgn": 2, "in 3 vokhn": 21, "היינט": 0, "מארגן": 1,
                 "איבערמארגן": 2}
        for words, ahead in cases.items():
            self.assertEqual(u.resolve_when(words, TUE)["date"],
                             date(2026, 10, 6) + timedelta(days=ahead), words)

    def test_times_and_the_morning(self):
        self.assertEqual(u.resolve_when("mañana a las 7am", TUE),
                         {"date": date(2026, 10, 7), "time": "07:00"})
        self.assertEqual(u.resolve_when("el lunes 10 de la mañana", TUE),
                         {"date": date(2026, 10, 12), "time": "10:00"})
        # "por la mañana" is the morning, not tomorrow.
        self.assertEqual(u.resolve_when("por la mañana", TUE), {"skip": "no_date"})
        self.assertEqual(ml.normalize_when("gut morgn"), "")
        self.assertEqual(u.resolve_when("4 de diciembre", TUE)["date"], date(2026, 12, 4))

    def test_vague_is_never_guessed(self):
        for words in ("pronto", "la semana que viene", "la próxima semana", "algún día",
                      "en unos días"):
            self.assertIn(u.resolve_when(words, TUE).get("skip"), ("vague", "no_date"), words)

    def test_the_attention_due_reader(self):
        self.assertEqual(wa.parse_due("para mañana", TUE), date(2026, 10, 7))
        self.assertEqual(wa.parse_due("el viernes", TUE), date(2026, 10, 9))
        self.assertEqual(wa.parse_due("pasado mañana", TUE), date(2026, 10, 8))
        self.assertEqual(wa.parse_due("day after tomorrow", TUE), date(2026, 10, 8))  # was tomorrow
        self.assertEqual(wa.parse_due("en 3 semanas", TUE), date(2026, 10, 27))
        self.assertEqual(wa.parse_due("morgn", TUE), date(2026, 10, 7))
        self.assertIsNone(wa.parse_due("la semana que viene", TUE))


class WhichLanguage(unittest.TestCase):

    def test_detect(self):
        self.assertEqual(ml.detect("the pour is tomorrow at 7"), "en")
        self.assertEqual(ml.detect("el colado es mañana"), "es")
        self.assertEqual(ml.detect("di inspection iz morgn"), "yi")
        self.assertEqual(ml.detect("הבדיקה איז מארגן"), "yi")
        self.assertEqual(ml.detect("the inspector viene el lunes ok guys see you there"), "mixed")

    def test_the_english_filters_do_not_drop_other_languages(self):
        self.assertEqual(wa.filter_reason({"body": "Buenos días, ¿quién trae la escalera?",
                                           "sender": "1"}), "question_mark")
        self.assertEqual(wa.filter_reason({"body": "el electricista viene el lunes",
                                           "sender": "1"}), "non_english")
        self.assertTrue(u.worth_a_call("la grúa llega pasado mañana"))

    def test_prompts_take_three_languages_and_keep_quotes(self):
        for prompt in (wa.SYSTEM_PROMPT, u.SYSTEM_PROMPT):
            self.assertIn("Spanish or Yiddish", prompt)
            self.assertIn("Never translate a quote", prompt)
            self.assertIn("ALWAYS in English", prompt)
        from lib import project_memory
        self.assertIn("Answer in English", project_memory.ANSWER_PROMPT)
        self.assertIn("never translate a quote", project_memory.ANSWER_PROMPT)


class StateChangeWords(unittest.TestCase):

    def test_done_cancel_move_in_spanish_and_yiddish(self):
        self.assertEqual(st.classify("Ya lo mandé")["kind"], "done")
        self.assertEqual(st.classify("Listo, ya está instalado")["kind"], "done")
        self.assertEqual(st.classify("fartik")["kind"], "done")
        self.assertEqual(st.classify("shoyn geshikt")["kind"], "done")
        self.assertEqual(st.classify("el colado se canceló")["kind"], "cancel")
        self.assertEqual(st.classify("olvídalo, ya no hace falta")["kind"], "cancel")
        moved = st.classify("En realidad, el viernes")
        self.assertEqual((moved["kind"], moved["due_text"]), ("reschedule", "el viernes"))

    def test_not_a_change(self):
        self.assertIsNone(st.classify("Mañana lo mando"))           # a promise
        self.assertIsNone(st.classify("¿ya está?"))                  # a question
        self.assertIsNone(st.classify("La inspección no se canceló"))
        self.assertIsNone(st.classify("the pour is not cancelled"))
        self.assertIsNone(st.due_phrase("lo mando por la mañana"))   # the morning

    def test_short_yes_and_sarcasm(self):
        for yes in ("sí", "Sí", "dale", "ya", "vale", "yo", "gut", "zicher", "ok"):
            self.assertIsNotNone(st.ack(yes), yes)
        self.assertEqual(st.ack("Sí, mañana"), {"due_text": "mañana"})
        for no in ("ya ya", "jaja ok", "jajaja sí", "sí 🙄"):
            self.assertIsNone(st.ack(no), no)

    def test_spanish_code_cancel(self):
        ev = [{"id": "p", "kind": "pour", "agency": None},
              {"id": "i", "kind": "inspection", "agency": "DOB"}]
        self.assertEqual(u.code_cancel("El colado se canceló por la lluvia", ev)["event_id"], "p")
        self.assertIsNone(u.code_cancel("La inspección no se canceló", ev))


class TheVoiceRules(unittest.TestCase):

    def test_language_codes(self):
        self.assertEqual(wa_voice.lang_code("spanish", "hola"), "es")
        self.assertEqual(wa_voice.lang_code("english", "hi"), "en")
        self.assertEqual(wa_voice.lang_code("hebrew", "שלום"), "yi")    # crews speak Yiddish
        self.assertEqual(wa_voice.lang_code("german", "די באַן"), "yi")  # Hebrew script

    def test_who_needs_review(self):
        self.assertTrue(wa_voice.needs_review("yi", 0.99))        # Yiddish voice: always
        self.assertTrue(wa_voice.needs_review("es", 0.2))
        self.assertTrue(wa_voice.needs_review("en", None))
        self.assertFalse(wa_voice.needs_review("es", 0.9))
        self.assertEqual(wa_voice.review_reason("yi", 0.99), "yiddish_voice")
        self.assertEqual(wa_voice.review_reason("en", 0.1), "low_confidence_voice")

    def test_the_row_and_the_key(self):
        v = wa_voice.row_fields("el colado es mañana", "the pour is tomorrow", "es", 0.9,
                                12.34, "wa-audio/p/g/m.ogg")["voice"]
        self.assertEqual((v["transcript"], v["english"], v["duration_sec"], v["review"]),
                         ("el colado es mañana", "the pour is tomorrow", 12.3, False))
        self.assertEqual(wa_voice.audio_key("p1", "1203@g.us", "3EB0/X"),
                         "wa-audio/p1/1203_g.us/3EB0_X.ogg")

    def test_whisper_confidence(self):
        self.assertIsNone(voice_ingest.aggregate_confidence([]))
        c = voice_ingest.aggregate_confidence(
            [{"start": 0, "end": 9, "avg_logprob": -0.1}, {"start": 9, "end": 10, "avg_logprob": -2.0}])
        self.assertTrue(0.7 < c < 0.85, c)


def _voice_payload(msg_id="V1"):
    return {"event": "message", "data": {"message": {
        "id": {"id": msg_id, "fromMe": False, "_serialized": f"false_{GROUP}_{msg_id}"},
        "from": GROUP, "author": f"{PM_PHONE}@c.us", "body": "", "type": "ptt",
        "timestamp": int(datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc).timestamp())}}}


class TheGroupWebhook(unittest.TestCase):

    def _db(self):
        cfg = server._default_bot_config()
        cfg["features"]["material_detection"] = False
        return _db(whatsapp_groups=[{
            "_id": "g1", "wa_group_id": GROUP, "company_id": CO_A,
            "project_id": "proj_a", "active": True,
            "linked_at": datetime.now(timezone.utc) - timedelta(days=1),
            "bot_config": cfg}])

    def _run_voice(self, db, result, msg_id="V1"):
        heard, uploads = [], []

        async def agent(**kw):
            heard.append(kw)
            return None

        async def audio(parsed):
            return b"\x00" * 4000

        async def ingest(audio_bytes, **kw):
            return result

        def upload(data, key, ctype="application/octet-stream"):
            uploads.append((key, ctype, len(data)))
            return f"https://r2/{key}"

        with _Ctx(db) as c, patch.object(server, "_run_group_agent", agent), \
                patch.object(server, "download_audio", audio), \
                patch.object(voice_ingest, "process_voice_note", ingest), \
                patch.object(server, "_upload_to_r2", upload):
            _run(server._process_whatsapp_message(_voice_payload(msg_id)))
        rows = [r for r in c.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        return rows, heard, uploads

    def _result(self, lang="spanish", conf=0.9):
        return voice_ingest.VoiceIngestResult(
            ok=True, english_transcript="The pour is tomorrow at 7",
            original_transcript="El colado es mañana a las 7", language_detected=lang,
            no_speech_prob=0.01, confidence=conf, duration_sec=6.2,
            telemetry={"whisper_cost_usd": 0.001, "translate_cost_usd": 0.0001})

    def test_a_voice_note_is_stored_as_said(self):
        db = self._db()
        rows, heard, uploads = self._run_voice(db, self._result())
        (row,) = rows
        self.assertEqual(row["body"], "El colado es mañana a las 7")      # as said
        v = row["voice"]
        self.assertEqual((v["lang"], v["confidence"], v["duration_sec"], v["english"], v["review"]),
                         ("es", 0.9, 6.2, "The pour is tomorrow at 7", False))
        self.assertEqual(v["audio_key"], "wa-audio/proj_a/120363000000000777_g.us/V1.ogg")
        self.assertEqual(uploads, [(v["audio_key"], "audio/ogg", 4000)])
        self.assertTrue(row["transcribed"])
        day = db[wa_voice.DAILY].rows[0]
        self.assertEqual((day["count"], day.get("lang_es"), day.get("review")), (1, 1, 0))

    def test_yiddish_voice_is_flagged(self):
        db = self._db()
        rows, _, _ = self._run_voice(db, self._result(lang="yiddish", conf=0.95))
        self.assertTrue(rows[0]["voice"]["review"])
        self.assertEqual(rows[0]["voice"]["review_reason"], "yiddish_voice")

    def test_the_daily_cap(self):
        db = self._db()
        with patch.object(wa_voice, "VOICE_DAILY_CAP", 1):
            self._run_voice(db, self._result(), msg_id="V1")
            rows, _, uploads = self._run_voice(db, self._result(), msg_id="V2")
        capped = [r for r in rows if r.get("message_id") == "V2"][0]
        self.assertEqual(capped["skipped"], "voice_cap")
        self.assertNotIn("voice", capped)
        self.assertEqual(uploads, [])                      # nothing downloaded or kept


class DmAnswersCiteVoice(unittest.TestCase):

    def test_a_voice_source_is_cited_with_the_mic(self):
        from lib import project_memory as pm
        src = {"source": pm.SOURCE_WHATSAPP, "who": "Carlos Méndez", "group": "120 Atlantic",
               "when": "Sep 24, 8:30 AM", "voice": True}
        self.assertEqual(pm.cite(src), "Carlos Méndez · 120 Atlantic · 🎤 Sep 24, 8:30 AM")
        self.assertEqual(pm.cite({**src, "voice": False}),
                         "Carlos Méndez · 120 Atlantic · Sep 24, 8:30 AM")

    def test_placeholders_are_not_indexed(self):
        from lib import project_memory as pm
        self.assertFalse(pm.indexable_message({"project_id": "p", "sender": "1",
                                               "body": "(voicenote — download failed)",
                                               "skipped": "voice_download_failed"}))
        self.assertTrue(pm.indexable_message({"project_id": "p", "sender": "1",
                                              "body": "el colado es mañana",
                                              "voice": {"lang": "es"}}))


class TheSourceMessage(unittest.TestCase):

    def test_text_voice_and_the_audio_link(self):
        db = _db(whatsapp_messages=[{
            "_id": "r1", "project_id": "proj_a", "company_id": CO_A, "group_id": GROUP,
            "sender": PM_PHONE, "sender_name": "Carlos", "body": "El colado es mañana",
            "created_at": datetime(2026, 10, 14, 11, 0, tzinfo=timezone.utc),
            "voice": {"lang": "es", "confidence": 0.9, "duration_sec": 6.2,
                      "english": "The pour is tomorrow", "audio_key": "wa-audio/proj_a/g/m.ogg",
                      "review": False}}])
        from tests.test_whatsapp_attention import ADMIN
        with patch.object(server, "db", db), \
                patch.object(server, "_presign_r2_get", lambda k, e=3600: f"https://signed/{k}"), \
                patch.object(server, "_bot_project_scope", _async(True)), \
                patch.object(server, "_assert_project_access", _async(None)):
            out = _run(server.get_whatsapp_source_message("proj_a", "r1", current_user=ADMIN))
        self.assertEqual(out["text"], "El colado es mañana")
        self.assertEqual(out["voice"]["audio_url"], "https://signed/wa-audio/proj_a/g/m.ogg")
        self.assertEqual(out["voice"]["english"], "The pour is tomorrow")
        self.assertNotIn(PM_PHONE, json.dumps(out))


def _async(v):
    async def f(*a, **k):
        return v
    return f


class CodexRound1(unittest.TestCase):

    def test_a_denied_done_or_sent_changes_nothing(self):
        for t in ("No está listo", "No lo mandé", "nisht geshikt", "Not done yet", "nope not sent"):
            self.assertIsNone(st.classify(t), t)
        for t in ("ya está listo", "ya lo mandé", "done", "no problem, done"):
            self.assertEqual(st.classify(t)["kind"], "done", t)

    def test_a_voice_note_is_never_merged_into_a_burst(self):
        t0 = datetime(2026, 10, 8, 14, 0)
        rows = [{"sender": "1", "body": "The delivery", "created_at": t0, "message_id": "a"},
                {"sender": "1", "body": "is cancelled", "created_at": t0 + timedelta(seconds=20),
                 "message_id": "b", "voice": {"review": True, "review_reason": "low_confidence"}}]
        out = st.bursts(rows)
        self.assertEqual([len(b) for b in out], [1, 1])
        self.assertTrue(wa_voice.unsure(st.merge(out[1])))

    def test_spanish_month_dates_pass_the_upcoming_filter(self):
        self.assertTrue(u.worth_a_call("FDNY 4 de diciembre"))
        self.assertTrue(u.worth_a_call("inspection 4 de diciembre"))
        self.assertFalse(u.worth_a_call("inspection"))


class TheDryRuns(unittest.TestCase):

    def test_spanish_attention_scripted(self):
        from scripts import attention_dry_run as dry
        sc = dry.load(str(SCRIPTS / "dry_run" / "spanish_2026_10.json"))
        r = dry.report(sc, asyncio.run(dry.run(sc, scripted=True)))
        self.assertEqual(r["score"]["hard"], r["score"]["lines"])
        self.assertEqual((r["chase"]["missing"], r["chase"]["unexpected"]), ([], []))

    def test_spanish_upcoming_scripted(self):
        sys.path.insert(0, str(SCRIPTS))
        import upcoming_dry_run as dry
        sc = dry.load(str(SCRIPTS / "upcoming_eval" / "job_es_2026_10.json"))
        r = dry.score(sc, asyncio.run(dry.run(sc, scripted=True)))
        self.assertEqual([(x["case"], x["notes"]) for x in r["rows"] if x["verdict"] == "FAIL"], [])
        self.assertEqual(r["score"], {"HARD": 5, "PASS": 1, "FAIL": 0})

    def test_yiddish_placeholders_refuse_to_run(self):
        from scripts import attention_dry_run as adry
        sys.path.insert(0, str(SCRIPTS))
        import upcoming_dry_run as udry
        with self.assertRaises(adry.ScenarioError):
            adry.load(str(SCRIPTS / "dry_run" / "yiddish_2026_10.json"))
        with self.assertRaises(udry.ScenarioError):
            udry.load(str(SCRIPTS / "upcoming_eval" / "yiddish_2026_10.json"))


if __name__ == "__main__":
    unittest.main()
