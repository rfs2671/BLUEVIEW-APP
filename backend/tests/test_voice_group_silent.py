"""A group voice note that cannot be read is never answered in the group.

Live, Sun Oct 11 10:05 AM, 588: a 3-second voice note got "Voice note
couldn't be processed, please retype as text." posted to the whole group.
That text is voice_ingest's Whisper-failed reply: the download "succeeded"
but handed Whisper WhatsApp's AES-encrypted .enc blob (WaAPI's download-media
answer carried the bytes without their mediaKey, which the webhook had), and
Whisper refused it.

Pinned here, with a real-shaped WaAPI voice ("ptt") payload:
- the encrypted blob is decrypted with the webhook's own mediaKey, and
  Whisper gets Ogg/Opus;
- nothing is ever posted in the group on a failure: a download or
  transcription failure is retried once, then the note is kept (audio
  attached when there is any) as "Voice note not processed" in Attention;
- under 2 seconds, or no words heard: the same silent path, no retry, and
  a note under 2 seconds is not transcribed at all;
- a DM may still be asked to retype.
"""

from __future__ import annotations

import base64
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")

import server  # noqa: E402
from lib import voice_ingest  # noqa: E402
from lib import wa_voice  # noqa: E402
from tests.test_whatsapp_phase1_foundations import (  # noqa: E402
    CO_A, GROUP, PM_PHONE, _Ctx, _db, _run,
)

OGG = b"OggS" + bytes(range(256)) * 3                 # Ogg/Opus, as decrypted
KEY = base64.b64encode(bytes(range(32))).decode()       # the note's mediaKey
SENT = datetime(2026, 10, 11, 14, 5, tzinfo=timezone.utc)   # 10:05 AM New York


def _encrypt(plain: bytes, key_b64: str) -> bytes:
    """WhatsApp media encryption (HKDF-SHA256 "WhatsApp Audio Keys",
    AES-256-CBC, PKCS7, a 10-byte MAC tail): the .enc blob."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    keys = HKDF(algorithm=hashes.SHA256(), length=112, salt=b"\x00" * 32,
                info=b"WhatsApp Audio Keys").derive(base64.b64decode(key_b64))
    pad = 16 - len(plain) % 16
    enc = Cipher(algorithms.AES(keys[16:48]), modes.CBC(keys[0:16])).encryptor()
    return enc.update(plain + bytes([pad]) * pad) + enc.finalize() + b"\x07" * 10


ENC = _encrypt(OGG, KEY)


def _payload(msg_id="3A5F0C1E9B2D", seconds="3"):
    """What WaAPI posts for a voice note in a group (event "message",
    type "ptt"): the encrypted media's path and its mediaKey ride along."""
    path = "/v/t62.7117-24/31415926_271828_n.enc?ccb=11-4&oh=01_Q5Aa&oe=6731A2B4&_nc_sid=5e03e0"
    return {"event": "message", "instanceId": "inst", "data": {"message": {
        "id": {"id": msg_id, "fromMe": False, "remote": GROUP,
               "participant": f"{PM_PHONE}@c.us",
               "_serialized": f"false_{GROUP}_{msg_id}_{PM_PHONE}@c.us"},
        "from": GROUP, "to": "15555550100@c.us", "author": f"{PM_PHONE}@c.us",
        "body": "", "type": "ptt", "hasMedia": True, "duration": seconds,
        "timestamp": int(SENT.timestamp()), "notifyName": "Roy",
        "_data": {
            "type": "ptt", "duration": seconds, "mimetype": "audio/ogg; codecs=opus",
            "mediaKey": KEY, "mediaKeyTimestamp": int(SENT.timestamp()),
            "filehash": "0nYp1y1z3v4ZK7m2pP7dW5w3r8D1jXyEo9b2Pq4F5mI=",
            "encFilehash": "uQ2f8sXr1mJ9pZk3c7Vb0nL4wY6hT5gR2eD8aF1oK0s=",
            "size": len(OGG), "directPath": path,
            "deprecatedMms3Url": f"https://mmg.whatsapp.net{path}",
            "isViewOnce": False, "notifyName": "Roy"},
    }}}


class _Resp:
    def __init__(self, status, j):
        self.status_code, self._j = status, j
        self.text = str(j)[:200]
        self.content = b"x"

    def json(self):
        return self._j


class _WaapiDownload:
    """WaAPI's client/action/download-media, answering with the media's
    bytes base64 -- still encrypted, and without the mediaKey."""
    calls = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None, **k):
        _WaapiDownload.calls.append((url, json))
        return _Resp(200, {"data": {"status": "success", "data": {"media": {
            "mimetype": "audio/ogg; codecs=opus", "filename": None,
            "data": base64.b64encode(ENC).decode()}}}})

    async def get(self, url, **k):
        return _Resp(404, {})


def _ok(text="I'll send the stair shop drawings Monday", seconds=3.0):
    return voice_ingest.VoiceIngestResult(
        ok=True, english_transcript=text, original_transcript=text,
        language_detected="english", no_speech_prob=0.02, confidence=0.93,
        duration_sec=seconds, telemetry={"whisper_cost_usd": 0.0003})


class _Base(unittest.TestCase):

    def _db(self):
        cfg = server._default_bot_config()
        cfg["features"]["material_detection"] = False
        return _db(whatsapp_groups=[{
            "_id": "g1", "wa_group_id": GROUP, "company_id": CO_A,
            "project_id": "proj_a", "active": True,
            "linked_at": datetime.now(timezone.utc) - timedelta(days=1),
            "bot_config": cfg}])

    def run_note(self, results, payload=None, download=None):
        """Deliver the note; `results`: what transcription returns on each
        call (an Exception is raised). Returns (ctx, bytes Whisper got,
        uploads)."""
        heard, uploads = [], []
        results = list(results)
        _WaapiDownload.calls = []

        async def transcribe(audio_bytes, **kw):
            heard.append(audio_bytes)
            r = results.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        async def agent(**kw):
            return None

        def upload(data, key, ctype="application/octet-stream"):
            uploads.append((key, data[:4]))
            return f"https://r2/{key}"

        ps = [patch.object(server, "ServerHttpClient", _WaapiDownload),
              patch.object(voice_ingest, "process_voice_note", transcribe),
              patch.object(server, "_run_group_agent", agent),
              patch.object(server, "_upload_to_r2", upload),
              patch.object(wa_voice, "RETRY_SECONDS", 0)]
        if download is not None:
            ps.append(patch.object(server, "download_audio", download))
        self.db = self._db()
        with _Ctx(self.db) as c:
            for p in ps:
                p.start()
            try:
                _run(self._deliver(payload or _payload()))
            finally:
                for p in ps:
                    p.stop()
        self.c = c
        return heard, uploads

    async def _deliver(self, payload):
        import asyncio
        await server._process_whatsapp_message(payload)
        # Let a scheduled retry (RETRY_SECONDS patched to 0) run.
        for _ in range(20):
            await asyncio.sleep(0)
            if not getattr(server, "_VOICE_RETRY_PENDING", None):
                break
        for _ in range(20):
            await asyncio.sleep(0)

    def group_posts(self):
        return [p for p in self.c.wire.calls if p.get("chatId") == GROUP]

    def reviews(self):
        return [i for i in self.db.attention_items.rows if i["type"] == "voice_review"]


class TheLiveFailure(_Base):

    def test_the_encrypted_blob_is_decrypted_with_the_webhooks_key(self):
        self.assertFalse(wa_voice.playable(ENC))              # what Whisper was handed
        heard, uploads = self.run_note([_ok()])
        self.assertEqual(len(heard), 1)
        self.assertTrue(heard[0].startswith(b"OggS"), heard[0][:8])
        self.assertEqual(heard[0], OGG)
        # It asked WaAPI by the serialized id.
        (url, body), = _WaapiDownload.calls
        self.assertTrue(url.endswith("/client/action/download-media"))
        self.assertTrue(body["messageId"].startswith(f"false_{GROUP}_"))
        (row,) = [r for r in self.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        self.assertEqual(row["body"], "I'll send the stair shop drawings Monday")
        self.assertEqual(row["voice"]["audio_key"], uploads[0][0])
        self.assertEqual(uploads[0][1], b"OggS")
        self.assertEqual(self.group_posts(), [])
        self.assertEqual(self.reviews(), [])

    def test_the_parsed_payload(self):
        parsed = server.parse_inbound_message(_payload(), vendor="waapi")
        self.assertTrue(parsed["has_audio"])
        self.assertEqual(wa_voice.media_key(parsed["raw"]), KEY)
        self.assertEqual(wa_voice.seconds(parsed["raw"]), 3.0)
        self.assertEqual(server._playable_audio(ENC, parsed), (OGG, None))
        self.assertEqual(server._playable_audio(b"\x00" * 400, parsed), (None, "not_audio"))
        self.assertEqual(server._playable_audio(None, parsed), (None, "download_failed"))


class NeverInTheGroup(_Base):

    def test_transcription_failing_twice_is_kept_for_review_silently(self):
        boom = RuntimeError("400 Bad Request: Invalid file format")
        heard, uploads = self.run_note([boom, boom])
        self.assertEqual(len(heard), 2)                       # tried once more
        self.assertEqual(self.group_posts(), [])              # never a word in the group
        (rev,) = self.reviews()
        self.assertEqual(rev["summary"], "Voice note not processed — transcription failed")
        self.assertEqual((rev["status"], rev["needs_review"], rev["excluded_from_metrics"]),
                         ("open", True, True))
        self.assertTrue(rev["evidence"]["quote"].startswith("🎤"))
        row = next(r for r in self.db.whatsapp_messages.rows
                   if str(r["_id"]) == rev["evidence"]["message_row_id"])
        self.assertEqual(row["skipped"], "voice_whisper_failed")
        self.assertEqual(row["voice"]["audio_key"], uploads[0][0])   # audio attached
        self.assertEqual(uploads[0][1], b"OggS")

    def test_a_failure_then_success_on_the_retry(self):
        heard, _ = self.run_note([RuntimeError("timeout"), _ok()])
        self.assertEqual(len(heard), 2)
        self.assertEqual(self.group_posts(), [])
        self.assertEqual(self.reviews(), [])
        (row,) = [r for r in self.db.whatsapp_messages.rows if r.get("sender") != "bot"]
        self.assertEqual(row["body"], "I'll send the stair shop drawings Monday")

    def test_a_download_that_never_works(self):
        async def nothing(parsed):
            return None
        heard, uploads = self.run_note([], download=nothing)
        self.assertEqual(heard, [])
        self.assertEqual(self.group_posts(), [])
        (rev,) = self.reviews()
        self.assertIn("could not be downloaded", rev["summary"])
        self.assertEqual(uploads, [])                         # nothing to attach

    def test_under_two_seconds_is_not_transcribed(self):
        heard, uploads = self.run_note([], payload=_payload(seconds="1"))
        self.assertEqual(heard, [])                           # not billed
        self.assertEqual(self.group_posts(), [])
        (rev,) = self.reviews()
        self.assertEqual(rev["summary"], "Voice note not processed — shorter than 2 seconds")
        self.assertEqual(uploads[0][1], b"OggS")              # the audio is still kept

    def test_no_words_heard_is_silent_and_not_retried(self):
        silent = voice_ingest.VoiceIngestResult(
            ok=False, original_transcript="", user_reply=voice_ingest.USER_REPLY_NO_SPEECH,
            error_kind="low_confidence", duration_sec=3.0, telemetry={})
        heard, _ = self.run_note([silent])
        self.assertEqual(len(heard), 1)                       # no retry
        self.assertEqual(self.group_posts(), [])
        (rev,) = self.reviews()
        self.assertIn("no words were heard", rev["summary"])

    def test_an_empty_transcript_is_silent(self):
        heard, _ = self.run_note([_ok(text="   ")])
        self.assertEqual(self.group_posts(), [])
        self.assertIn("no words were heard", self.reviews()[0]["summary"])

    def test_a_redelivered_webhook_is_processed_once(self):
        heard, _ = self.run_note([_ok()])
        with _Ctx(self.db):
            with patch.object(voice_ingest, "process_voice_note", None):
                _run(server._process_whatsapp_message(_payload()))   # same id again
        self.assertEqual(len(heard), 1)


if __name__ == "__main__":
    unittest.main()


class WhisperIsToldWhatTheFileIs(unittest.TestCase):
    """The upload is named for its container (Whisper reads the format from
    the name), and OpenAI's refusal reason is kept in the error."""

    class _Http:
        def __init__(self, status=200, body=None):
            self.sent, self.status, self.body = [], status, body

        async def post(self, url, headers=None, files=None, timeout=None):
            import httpx
            self.sent.append(files["file"][:1] + files["file"][2:])
            req = httpx.Request("POST", url)
            if self.status != 200:
                return httpx.Response(self.status, request=req, text=self.body)
            return httpx.Response(200, request=req, json={
                "text": "pour friday", "language": "english", "duration": 3.1,
                "segments": [{"avg_logprob": -0.2, "no_speech_prob": 0.01}]})

    def _send(self, audio, http):
        import asyncio
        with patch.object(voice_ingest, "WHISPER_BACKOFF_SEC", 0):
            return asyncio.run(voice_ingest.transcribe_whisper(
                audio, openai_api_key="k", http_client=http))

    def test_each_container_gets_its_name(self):
        cases = {b"OggS" + b"\0" * 40: ("voice.ogg", "audio/ogg"),
                 b"ID3\x04" + b"\0" * 40: ("voice.mp3", "audio/mpeg"),
                 b"\0\0\0\x20ftypM4A " + b"\0" * 40: ("voice.m4a", "audio/mp4")}
        for audio, want in cases.items():
            http = self._Http()
            self.assertEqual(self._send(audio, http).transcript, "pour friday")
            self.assertEqual(http.sent[0], want)

    def test_openais_reason_is_kept(self):
        http = self._Http(400, '{"error":{"message":"Invalid file format."}}')
        with self.assertRaises(Exception) as cm:
            self._send(b"\xfd\xff\xc9\x18" + b"\0" * 60, http)
        msg = str(cm.exception)
        self.assertIn("Invalid file format", msg)
        self.assertIn("first8=fdffc918", msg)


class CodexFindings(_Base):
    """#746 review: the retry and the daily cap, the ledger written last,
    every MP3 frame header, and the kept audio named for what it is."""

    def test_a_retry_past_the_daily_cap_is_still_reviewed(self):
        claims = []

        async def claim(company_id, now):
            claims.append(1)
            return len(claims) == 1          # the first try took the last one
        with patch.object(server, "_voice_claim", claim):
            self.run_note([RuntimeError("whisper 500"), RuntimeError("whisper 500")])
        self.assertEqual(len(claims), 1)     # the retry is not counted again
        self.assertEqual(len(self.reviews()), 1)
        self.assertEqual(self.group_posts(), [])
        self.assertFalse([r for r in self.db.whatsapp_messages.rows
                          if r.get("skipped") == "voice_cap"])

    def test_a_review_that_failed_part_way_is_finished_on_redelivery(self):
        db = self._db()
        parsed = {"message_id": "M1", "timestamp": 1760000000, "sender": "1555@c.us",
                  "push_name": "Dave"}
        real = db.attention_items.insert_one
        calls = []

        async def flaky(doc):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient")
            return await real(doc)
        with _Ctx(db):
            with patch.object(db.attention_items, "insert_one", flaky):
                for _ in range(2):
                    _run(server._voice_not_processed(
                        parsed, GROUP, "proj_a", CO_A, "1555", datetime.now(timezone.utc),
                        "whisper_failed", None))
        self.assertEqual(len([i for i in db.attention_items.rows
                              if i["type"] == "voice_review"]), 1)
        self.assertEqual(len(db.whatsapp_voice_events.rows), 1)
        self.assertEqual(len([r for r in db.whatsapp_messages.rows
                              if r.get("message_id") == "M1"]), 1)   # the row is reused

    def test_every_mpeg_layer_iii_header_is_audio(self):
        pad = b"\0" * 40
        for head in (b"\xff\xfb", b"\xff\xfa", b"\xff\xf3", b"\xff\xf2", b"\xff\xe3", b"\xff\xe2"):
            self.assertEqual(wa_voice.playable(head + pad), "mp3", head.hex())
        self.assertIsNone(wa_voice.playable(b"\xff\xf1" + pad))     # AAC/ADTS, layer 00
        self.assertIsNone(wa_voice.playable(ENC))

    def test_the_kept_audio_is_named_for_what_it_is(self):
        mp3 = b"ID3\x04" + bytes(range(256)) * 2

        async def download(parsed):
            return mp3
        heard, uploads = self.run_note([_ok()], download=download)
        self.assertEqual(heard, [mp3])
        self.assertEqual(len(uploads), 1)
        self.assertTrue(uploads[0][0].endswith(".mp3"), uploads[0][0])
        self.assertEqual(wa_voice.audio_type(mp3), ("mp3", "audio/mpeg"))
        self.assertEqual(wa_voice.audio_type(OGG), ("ogg", "audio/ogg"))
