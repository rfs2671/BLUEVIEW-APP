"""What a sender speaks, set on People (Auto / English / Spanish / Yiddish),
is Whisper's language hint for their voice notes. Also the eval harness's
scoring (lib/voice_metrics) and clip loading (scripts/voice_lang_eval)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import voice_ingest, voice_metrics, wa_voice  # noqa: E402
from tests.test_whatsapp_attention import CO_A, LID, T0, ADMIN, PM, _msg  # noqa: E402
from tests.test_whatsapp_sender_map import PROJ_A, _call, _db, _people  # noqa: E402
from tests.test_voice_group_silent import _Base, _ok  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _set(db, key, language, user=ADMIN):
    out, _ = _call(db, server.set_whatsapp_person_language, PROJ_A["_id"], key,
                   server.SenderLanguageBody(language=language),
                   project=PROJ_A, current_user=user)
    return out


class OnPeople(unittest.TestCase):

    def _world(self):
        db = _db()
        _msg(db, "buenos días", sender=LID, jid=f"{LID}@lid", sender_name="Carlos B", at=T0)
        return db

    def test_auto_until_set_then_shown_and_kept(self):
        db = self._world()
        row = _people(db)["senders"][0]
        self.assertEqual(row["language"], "auto")
        out = _set(db, row["key"], "es")
        self.assertEqual(out["language"], "es")
        self.assertEqual(_people(db)["senders"][0]["language"], "es")
        stored = db[wa_voice.SENDER_LANG_COLLECTION].rows
        self.assertEqual([(r["company_id"], r["sender_jid"], r["language"]) for r in stored],
                         [(CO_A, f"{LID}@lid", "es")])
        # No name was needed, and none was made up: still not assigned.
        self.assertIsNone(_people(db)["senders"][0]["assigned"])

    def test_auto_removes_it_and_a_pm_can_set_it(self):
        db = self._world()
        key = _people(db)["senders"][0]["key"]
        _set(db, key, "yi", user=PM)
        self.assertEqual(_people(db)["senders"][0]["language"], "yi")
        _set(db, key, "auto")
        self.assertEqual(db[wa_voice.SENDER_LANG_COLLECTION].rows, [])
        self.assertEqual(_people(db)["senders"][0]["language"], "auto")

    def test_anything_else_is_refused(self):
        db = self._world()
        key = _people(db)["senders"][0]["key"]
        with self.assertRaises(HTTPException) as cm:
            _set(db, key, "fr")
        self.assertEqual(cm.exception.status_code, 422)
        with self.assertRaises(HTTPException) as cm:
            _set(db, "not-a-key", "es")
        self.assertEqual(cm.exception.status_code, 404)

    def test_the_lookup_gives_whispers_hint(self):
        db = self._world()
        _set(db, _people(db)["senders"][0]["key"], "es")
        with patch.object(server, "db", db):
            self.assertEqual(_run(server._sender_whisper_language(CO_A, [f"{LID}@lid"])), "es")
            self.assertIsNone(_run(server._sender_whisper_language("other", [f"{LID}@lid"])))
            self.assertIsNone(_run(server._sender_whisper_language(CO_A, ["1@c.us"])))
            self.assertIsNone(_run(server._sender_whisper_language(None, [f"{LID}@lid"])))

    def test_choices(self):
        self.assertEqual(wa_voice.whisper_language("auto"), None)
        self.assertEqual(wa_voice.whisper_language("yi"), "yi")
        self.assertEqual(wa_voice.sender_language(" ES "), "es")
        with self.assertRaises(ValueError):
            wa_voice.sender_language("de")


class TheGroupNoteIsHinted(_Base):

    def test_the_senders_language_reaches_whisper(self):
        seen = []

        async def lang(company_id, jids):
            seen.append((str(company_id), jids))
            return "es"
        with patch.object(server, "_sender_whisper_language", lang):
            self.run_note([_ok()])
        self.assertEqual(self.kw[0].get("language"), "es")
        self.assertTrue(seen and seen[0][1][0].endswith("@c.us"))

    def test_no_language_set_means_none_passed(self):
        self.run_note([_ok()])
        self.assertIsNone(self.kw[0].get("language"))


class WhisperGetsTheHint(unittest.TestCase):

    class _Http:
        def __init__(self, refuse_language=False):
            self.files, self.refuse = [], refuse_language

        async def post(self, url, headers=None, files=None, timeout=None):
            import httpx
            self.files.append(dict(files))
            req = httpx.Request("POST", url)
            if self.refuse and "language" in files:
                return httpx.Response(400, request=req,
                                      text='{"error":{"message":"Language yi is not supported"}}')
            return httpx.Response(200, request=req, json={
                "text": "mañana", "language": "spanish", "duration": 2.5,
                "segments": [{"avg_logprob": -0.2, "no_speech_prob": 0.01}]})

    def test_the_language_is_a_form_field(self):
        http = self._Http()
        _run(voice_ingest.transcribe_whisper(b"OggS" + b"\0" * 40, openai_api_key="k",
                                             http_client=http, language="es"))
        self.assertEqual(http.files[0]["language"], (None, "es"))

    def test_a_refused_language_falls_back_to_detection(self):
        http = self._Http(refuse_language=True)
        with patch.object(voice_ingest, "WHISPER_BACKOFF_SEC", 0):
            r = _run(voice_ingest.transcribe_whisper(b"OggS" + b"\0" * 40, openai_api_key="k",
                                                     http_client=http, language="yi"))
        self.assertEqual(r.transcript, "mañana")
        self.assertEqual(len(http.files), 2)
        self.assertNotIn("language", http.files[1])

    def test_process_voice_note_passes_it_and_records_it(self):
        seen = []

        async def whisper(audio, *, openai_api_key, http_client=None, **kw):
            seen.append(kw)
            return voice_ingest.WhisperResult(transcript="buenos días", language="spanish",
                                              duration_sec=3.0, no_speech_prob=0.0,
                                              cost_usd=0.0, raw_segments=1)

        async def translate(text, **kw):
            return voice_ingest.TranslateResult(english="good morning", tokens_in=1,
                                                tokens_out=1, cost_usd=0.0,
                                                fell_back_to_original=False)
        r = _run(voice_ingest.process_voice_note(b"OggS" + b"\0" * 400, openai_api_key="k",
                                                 whisper_fn=whisper, translate_fn=translate,
                                                 language="es"))
        self.assertEqual(seen, [{"language": "es"}])
        self.assertEqual(r.telemetry["whisper_language_hint"], "es")


class TheScore(unittest.TestCase):

    def test_yiddish_points_and_ligatures_do_not_count(self):
        self.assertEqual(voice_metrics.wer("דער באַטאָן קומט מאָרגן", "דער באטאן קומט מארגן"), 0.0)
        self.assertEqual(voice_metrics.normalize("ײַ װ ױ"), "יי וו וי")
        self.assertEqual(voice_metrics.script_of("der Beton"), "latin")
        self.assertEqual(voice_metrics.script_of("דער באטאן"), "hebrew")

    def test_spanish_accents_count_punctuation_does_not(self):
        self.assertEqual(voice_metrics.wer("¿Está listo?", "está listo"), 0.0)
        self.assertEqual(voice_metrics.wer("está listo", "esta listo"), 0.5)

    def test_cer_is_gentler_than_wer(self):
        self.assertLess(voice_metrics.cer("el colado", "el colao"),
                        voice_metrics.wer("el colado", "el colao"))


class TheHarness(unittest.TestCase):

    def test_clips_from_folders_or_a_manifest(self):
        from scripts import voice_lang_eval as ev
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "es").mkdir()
            (root / "yi").mkdir()
            (root / "es" / "01.ogg").write_bytes(b"OggS")
            (root / "es" / "01.txt").write_text("Mañana llega la varilla\n", encoding="utf-8")
            (root / "yi" / "01.opus").write_bytes(b"OggS")
            (root / "yi" / "01.txt").write_text("דער באַטאָן", encoding="utf-8")
            (root / "yi" / "02.ogg").write_bytes(b"OggS")          # no text: skipped
            clips = ev.load_clips(root)
            self.assertEqual([(c.id, c.lang, c.text) for c in clips],
                             [("es/01.ogg", "es", "Mañana llega la varilla"),
                              ("yi/01.opus", "yi", "דער באַטאָן")])
            (root / "manifest.json").write_text(json.dumps(
                [{"file": "es/01.ogg", "lang": "ES", "text": "hola"}]), encoding="utf-8")
            self.assertEqual([(c.lang, c.text) for c in ev.load_clips(root)], [("es", "hola")])

    def test_the_matrix_and_the_score(self):
        from scripts import voice_lang_eval as ev
        # 2 models x prompt off/on x hint off/on, + whisper-1 translate.
        self.assertEqual(len(ev.configs("both")), 9)
        self.assertEqual({c["model"] for c in ev.configs("off")},
                         {"whisper-1", "gpt-4o-transcribe", ev.TRANSLATE})
        rows = [ev.Result(clip="a", lang="es", model="whisper-1", prompt=False, hint=False,
                          ref="uno dos tres cuatro", wer=0.5, cer=0.2),
                ev.Result(clip="b", lang="es", model="whisper-1", prompt=False, hint=False,
                          ref="uno dos", wer=0.0, cer=0.0, wrong_lang=True),
                ev.Result(clip="c", lang="es", model="whisper-1", prompt=False, hint=False,
                          ref="uno", error="RuntimeError: 500")]
        sc = ev.score(rows)
        self.assertAlmostEqual(sc["wer"], (0.5 * 4) / 6)        # weighted by words
        self.assertEqual((sc["wrong_lang"], sc["failed"], sc["n"]), (1, 1, 2))
        self.assertTrue(ev.wrong_language("yi", {"text": "der Beton", "language": None}))
        self.assertTrue(ev.wrong_language("es", {"text": "x", "language": "english"}))
        self.assertFalse(ev.wrong_language("es", {"text": "x", "language": "spanish"}))


class CompanyDelete(unittest.TestCase):

    def test_the_languages_go_with_the_company(self):
        src = Path(server.__file__).read_text()
        i = src.index('await db[wa_sender_map.COLLECTION].delete_many({"company_id": str(company_id)})')
        self.assertIn("wa_voice.SENDER_LANG_COLLECTION].delete_many", src[i:i + 300])


if __name__ == "__main__":
    unittest.main()


# ── Everyone who can send a voice note: users, workers, and People ──────────

from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    _db as _phase1_db, CO_A as P1_CO, PM_PHONE)
from tests._fake_mongo import FakeDb  # noqa: E402

ADMIN_A = {"id": "u_admin", "_id": "u_admin", "role": "admin", "company_id": P1_CO}
ADMIN_B = {"id": "u_b", "_id": "u_b", "role": "admin", "company_id": "co_b"}


def _lang_rows(db):
    return sorted((r["company_id"], r["sender_jid"], r["language"])
                  for r in db[wa_voice.SENDER_LANG_COLLECTION].rows)


class ForUsers(unittest.TestCase):

    def test_set_by_their_number_and_read_back(self):
        db = _phase1_db()
        with patch.object(server, "db", db):
            self.assertEqual(_run(server.get_admin_user_voice_language("u_pm", admin=ADMIN_A)),
                             {"language": "auto", "has_phone": True})
            out = _run(server.set_admin_user_voice_language(
                "u_pm", server.VoiceLanguageBody(language="es"), admin=ADMIN_A))
        self.assertEqual(out, {"language": "es", "has_phone": True})
        self.assertEqual(_lang_rows(db), [(P1_CO, f"{PM_PHONE}@c.us", "es")])

    def test_another_companys_admin_is_refused(self):
        db = _phase1_db()
        with patch.object(server, "db", db), self.assertRaises(HTTPException) as cm:
            _run(server.set_admin_user_voice_language(
                "u_pm", server.VoiceLanguageBody(language="es"), admin=ADMIN_B))
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(_lang_rows(db), [])

    def test_no_phone_no_language(self):
        db = _phase1_db()
        db.users.rows.append({"_id": "u_nophone", "company_id": P1_CO, "role": "cp", "name": "N"})
        with patch.object(server, "db", db):
            self.assertEqual(_run(server.get_admin_user_voice_language("u_nophone", admin=ADMIN_A)),
                             {"language": "auto", "has_phone": False})
            with self.assertRaises(HTTPException) as cm:
                _run(server.set_admin_user_voice_language(
                    "u_nophone", server.VoiceLanguageBody(language="yi"), admin=ADMIN_A))
        self.assertEqual(cm.exception.status_code, 422)

    def test_the_language_moves_with_their_number(self):
        db = _phase1_db()
        with patch.object(server, "db", db):
            _run(server._voice_lang_set(P1_CO, f"{PM_PHONE}@c.us", "yi", "u_admin", {}))
            _run(server._voice_lang_move(P1_CO, "+" + PM_PHONE, "(718) 555-0199"))
        self.assertEqual(_lang_rows(db), [(P1_CO, "17185550199@c.us", "yi")])


    def test_a_failed_write_keeps_the_old_setting(self):
        db = _phase1_db()
        coll = db[wa_voice.SENDER_LANG_COLLECTION]

        async def down(*a, **k):
            raise RuntimeError("transient")
        with patch.object(server, "db", db):
            _run(server._voice_lang_set(P1_CO, f"{PM_PHONE}@c.us", "yi", "u_admin", {}))
            with patch.object(coll, "update_one", down):
                _run(server._voice_lang_move(P1_CO, "+" + PM_PHONE, "(718) 555-0199"))
        self.assertEqual(_lang_rows(db), [(P1_CO, f"{PM_PHONE}@c.us", "yi")])


class ForWorkers(unittest.TestCase):

    def _db(self):
        return FakeDb(workers=[{"_id": "w1", "company_id": "co1", "name": "Carlos",
                                "phone": "718-555-0142"},
                               {"_id": "w2", "company_id": "co1", "name": "No Phone"}])

    def test_set_and_read(self):
        db = self._db()
        w = db.workers.rows[0]
        with patch.object(server, "db", db):
            out = _run(server.set_worker_voice_language(
                "w1", server.VoiceLanguageBody(language="es"), worker=w, current_user=ADMIN_A))
            self.assertEqual(out["language"], "es")
            self.assertEqual(_run(server.get_worker_voice_language("w1", worker=w))["language"], "es")
        self.assertEqual(_lang_rows(db), [("co1", "17185550142@c.us", "es")])

    def test_no_phone_is_refused(self):
        db = self._db()
        with patch.object(server, "db", db), self.assertRaises(HTTPException) as cm:
            _run(server.set_worker_voice_language(
                "w2", server.VoiceLanguageBody(language="es"), worker=db.workers.rows[1],
                current_user=ADMIN_A))
        self.assertEqual(cm.exception.status_code, 422)

    def test_a_new_number_takes_the_language_along(self):
        db = self._db()
        with patch.object(server, "db", db):
            _run(server._voice_lang_set("co1", "17185550142@c.us", "es", "a", {}))
            _run(server.update_worker("w1", {"phone": "718-555-0177"}, worker=dict(db.workers.rows[0])))
        self.assertEqual(_lang_rows(db), [("co1", "17185550177@c.us", "es")])


class TheNoteFindsThem(unittest.TestCase):

    def test_a_phone_sender_is_their_own_key(self):
        with patch.object(server, "db", FakeDb()):
            self.assertEqual(_run(server._sender_language_jids("co1", "17185550142@c.us")),
                             ["17185550142@c.us"])

    def test_a_privacy_id_finds_the_users_number_through_their_optin(self):
        db = _phase1_db()
        db[server.WA_OPTINS].rows.append({"status": "active", "chat_digits": "99887766554433",
                                          "user_id": "u_pm", "phone": "+" + PM_PHONE})
        with patch.object(server, "db", db):
            keys = _run(server._sender_language_jids(P1_CO, "99887766554433@lid"))
        self.assertEqual(keys, ["99887766554433@lid", f"{PM_PHONE}@c.us"])

    def test_a_privacy_id_finds_a_number_people_gave(self):
        db = FakeDb(whatsapp_sender_map=[{"company_id": "co1", "sender_jid": "4455@lid",
                                          "phone": "17185550142", "set_at": T0}])
        with patch.object(server, "db", db):
            keys = _run(server._sender_language_jids("co1", "4455@lid"))
        self.assertEqual(keys, ["4455@lid", "17185550142@c.us"])

    def test_the_note_jid_wins_over_the_phone(self):
        db = FakeDb()
        db[wa_voice.SENDER_LANG_COLLECTION].rows.extend([
            {"company_id": "co1", "sender_jid": "17185550142@c.us", "language": "en"},
            {"company_id": "co1", "sender_jid": "4455@lid", "language": "yi"}])
        with patch.object(server, "db", db):
            self.assertEqual(_run(server._sender_whisper_language(
                "co1", ["4455@lid", "17185550142@c.us"])), "yi")
            self.assertEqual(_run(server._sender_whisper_language(
                "co1", ["9999@lid", "17185550142@c.us"])), "en")


class AUserSetOnTheirScreenIsHeardInTheGroup(_Base):

    def _db(self):
        db = super()._db()
        db[wa_voice.SENDER_LANG_COLLECTION].rows.append(
            {"company_id": CO_A, "sender_jid": f"{PM_PHONE}@c.us", "language": "es"})
        return db

    def test_their_group_voice_note_gets_the_hint(self):
        self.run_note([_ok()])
        self.assertEqual(self.kw[0].get("language"), "es")
