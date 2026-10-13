"""DM actions for the personal assistant (lib/dm_actions.py, server.py "DM
ACTIONS"): an admin or PM gets things done in their own words.

Rule one, checked on every reply here: short, plain, friendly; two short
sentences at most; no ids, no field names, never a whole phone number.

- Reading: 30+ messy real-world phrasings (EN/ES, typos, voice-style) give
  the right action and fields, or one clear question.
- The model's answer is checked field by field; garbage never acts.
- Add a job (GeoSearch -> plain words -> yes -> created, DOB and DOT
  watched), a sub, a person (last 4 only), a punch contact, a setting.
- Sending punch lists for real: the address typed back, admin only.
- undo / never mind within 10 minutes; every change audited.
- Never a guess between people or jobs; the wrong role is told simply; what
  it cannot do is said with what it can.
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402
from lib import dm_actions, wa_sender_map  # noqa: E402
from scripts import punch_dry_run as dry  # noqa: E402

SC = json.load(open(os.path.join(os.path.dirname(dry.__file__), "dry_run_punch",
                                 "walk_588_2026_10.json")))
CHAT = "17185550100@c.us"


# ── READING ──────────────────────────────────────────────────────────────────

PHRASINGS = [
    # (what they wrote, action, fields that must be read)
    ("add 9 menahan", "add_job", {"address": "9 menahan"}),
    ("we got a new job on 9 menahan st", "add_job", {"address": "9 menahan st"}),
    ("start tracking 588 thomas boyland", "add_job", {"address": "588 thomas boyland"}),
    ("nuevo trabajo en 9 menahan", "add_job", {"address": "9 menahan"}),
    ("Add 9 Menahan St Brooklyn please", "add_job", {"borough": "Brooklyn"}),
    ("we just got a new job 1420 fulton st bk", "add_job", {"address": "1420 fulton st bk"}),
    ("track 852 e 176 st bronx", "add_job", {"borough": "Bronx"}),
    ("hey can you add 77 water st 10005", "add_job", {"zip": "10005"}),
    ("agrega 9 menahan", "add_job", {"address": "9 menahan"}),
    ("so we picked up a new job 45 Bay Ridge Ave", "add_job", {"address": "45 bay ridge ave"}),
    ("put power direct on 588 they're the electrician", "add_sub",
     {"company": "Power Direct", "job": "588", "trade": "Electrical"}),
    ("put Arkon on 588 as the plumber", "add_sub", {"company": "Arkon", "trade": "Plumbing"}),
    ("add power direct to 588 thomas boyland", "add_sub", {"company": "Power Direct"}),
    ("pon a arkon en 588 son los plomeros", "add_sub", {"company": "Arkon", "trade": "Plumbing"}),
    ("power direct is the electrician on 588", "add_sub", {"trade": "Electrical"}),
    ("chris is our super his number is 718 555 1234", "add_person",
     {"name": "Chris", "company": "GC team", "role": "super", "phone": "7185551234"}),
    ("Chris Weiss 718-555-1234 from Arkon", "add_person",
     {"name": "Chris Weiss", "company": "Arkon", "phone": "7185551234"}),
    ("dov from power direct his cell is (917) 555 0199", "add_person",
     {"name": "Dov", "company": "Power Direct", "phone": "9175550199"}),
    ("juan es nuestro capataz su numero es 347 555 7788", "add_person",
     {"name": "Juan", "company": "GC team", "role": "foreman"}),
    ("save mike 1 917 555 0101", "add_person", {"name": "Mike", "phone": "9175550101"}),
    ("dov handles punch for power direct", "set_punch_contact",
     {"name": "Dov", "company": "Power Direct"}),
    ("punch contact for arkon is chris", "set_punch_contact", {"name": "Chris", "company": "Arkon"}),
    ("give arkon's punch list to chris", "set_punch_contact", {"company": "Arkon"}),
    ("dov maneja el punch de power direct", "set_punch_contact", {"name": "Dov"}),
    ("stop bugging people on weekends at 588", "set_setting",
     {"setting": "rest", "days": "ask", "off": True, "job": "588"}),
    ("no weekend reminders at 588", "set_setting", {"setting": "rest", "days": "ask", "off": True}),
    ("turn off weekends 588", "set_setting", {"days": "ask", "off": True}),
    ("ok to chase on weekends at 9 menahan", "set_setting",
     {"days": "both", "off": False, "job": "9 menahan"}),
    ("no molestar los fines de semana en 588", "set_setting", {"days": "ask", "off": True, "job": "588"}),
    ("no chasing on shabbos only at 588", "set_setting", {"days": "shabbos", "off": True, "job": "588"}),
    ("no chasing sundays at 588", "set_setting", {"days": "sunday", "off": True, "job": "588"}),
    ("no chasing the whole weekend at 588", "set_setting", {"days": "both", "off": True, "job": "588"}),
    ("start sending punch lists for real at 588", "set_setting",
     {"setting": "punch_sends", "value": "live", "job": "588"}),
    ("punch at 588 for real", "set_setting", {"value": "live", "job": "588"}),
    ("put punch back to practice at 588", "set_setting", {"value": "shadow"}),
    ("undo that", "undo", {}),
    ("never mind", "undo", {}),
    ("wait no", "undo", {}),
    ("olvídalo", "undo", {}),
    ("delete 588", "unsupported", {}),
    ("remove chris from the job", "unsupported", {}),
]


class Reading(unittest.TestCase):

    def test_messy_phrasings(self):
        self.assertGreaterEqual(len(PHRASINGS), 30)
        for said, action, fields in PHRASINGS:
            with self.subTest(said):
                got = dm_actions.rules(said)
                self.assertEqual(got["action"], action, got)
                for k, v in fields.items():
                    self.assertEqual(str(got.get(k)).lower() if isinstance(v, str) else got.get(k),
                                     v.lower() if isinstance(v, str) else v, (k, got))
                self.assertTrue(dm_actions.looks_like_request(said))

    def test_questions_are_not_requests(self):
        for said in ("who's on site at 588", "how many workers today", "any dob violations",
                     "what's open on floor 4", "thanks!", "good morning", "cuantos trabajadores hay"):
            with self.subTest(said):
                self.assertEqual(dm_actions.rules(said)["action"], "none")

    def test_the_models_answer_is_checked_field_by_field(self):
        c = dm_actions.clean
        self.assertEqual(c({"action": "drop_table"}), {"action": "none"})
        self.assertEqual(c("add_job"), {"action": "none"})
        got = c({"action": "add_person", "name": "chris weiss", "phone": "call me",
                 "company": "our", "evil": "$where"})
        self.assertEqual(got, {"action": "add_person", "name": "Chris Weiss", "company": "GC team",
                               "bad_phone": True})
        got = c({"action": "add_job", "address": "9 menahan st", "borough": "Narnia", "zip": "12"})
        self.assertEqual(got, {"action": "add_job", "address": "9 menahan st"})
        got = c({"action": "set_setting", "setting": "delete_everything", "value": True, "job": "588"})
        self.assertNotIn("setting", got)
        got = c({"action": "set_setting", "setting": "punch_sends", "value": "maybe"})
        self.assertNotIn("value", got)
        got = c({"action": "add_sub", "company": "x" * 500, "trade": "electricians"})
        self.assertEqual((len(got["company"]), got["trade"]), (80, "Electrical"))

    def test_yes_and_no_in_their_words(self):
        for yes in ("yes", "Yeah", "yep!", "ok", "sí", "si", "dale", "👍", "👍🏽", "✅", "go ahead", "yo"):
            self.assertIs(dm_actions.yes_no(yes), True, yes)
        for no in ("no", "nope", "nah", "no gracias", "👎", "mejor no", "cancel"):
            self.assertIs(dm_actions.yes_no(no), False, no)
        for neither in ("maybe", "what?", "9 menahan"):
            self.assertIsNone(dm_actions.yes_no(neither), neither)

    def test_their_language(self):
        self.assertEqual(dm_actions.reply_lang("nuevo trabajo en 9 menahan"), "es")
        self.assertEqual(dm_actions.reply_lang("add 9 menahan"), "en")
        self.assertEqual(dm_actions.reply_lang("לייג צו 9 מנחם"), "en")      # Yiddish: English

    def test_every_reply_is_plain(self):
        sample = {"place": "9 Menahan St, Brooklyn", "job": "588 Thomas St",
                  "company": "Power Direct", "trade": "Electrical", "name": "Chris Weiss",
                  "first": "Chris", "options": "Chris Weiss (GC) or Chris Lopez (Arkon)",
                  "last4": "1234", "what": "9 Menahan St is removed",
                  "state": "no chasing over Shabbos, Yom Tov or Sundays"}
        for lang, table in dm_actions.TEXT.items():
            for key in table:
                with self.subTest(lang=lang, key=key):
                    self.assertEqual(dm_actions.plain(dm_actions.say(lang, key, **sample)), [])
        self.assertTrue(dm_actions.plain("GeoSearch match BIN 3071234 BBL 3-03156-0042. "
                                         "Confirm create_project?"))

    def test_addresses_in_plain_words(self):
        self.assertEqual(dm_actions.pretty_address("9 MENAHAN STREET, Brooklyn, NY, USA"),
                         "9 Menahan St, Brooklyn")
        self.assertEqual(dm_actions.pretty_address("852 EAST 176 STREET, Bronx, NY, USA", False),
                         "852 E 176 St")


# ── THE CONVERSATION ─────────────────────────────────────────────────────────

GEO = {
    "9 menahan": [{"label": "9 MENAHAN STREET, Brooklyn, NY, USA", "place": "9 Menahan St, Brooklyn",
                   "borough": "Brooklyn", "zip": "11221"}],
    "45 main": [{"label": "45 MAIN STREET, Brooklyn, NY, USA", "place": "45 Main St, Brooklyn",
                 "borough": "Brooklyn", "zip": "11201"},
                {"label": "45 MAIN STREET, Queens, NY, USA", "place": "45 Main St, Queens",
                 "borough": "Queens", "zip": "11354"},
                {"label": "45 MAIN STREET, Staten Island, NY, USA",
                 "place": "45 Main St, Staten Island", "borough": "Staten Island", "zip": "10307"}],
    "588 thomas": [{"label": "588 THOMAS STREET, Brooklyn, NY, USA", "place": "588 Thomas St, Brooklyn",
                    "borough": "Brooklyn", "zip": "11207"}],
    "12 nowhere": [],
    "12 nowhere brooklyn": [{"label": "12 NOWHERE PLACE, Brooklyn, NY, USA",
                             "place": "12 Nowhere Pl, Brooklyn", "borough": "Brooklyn", "zip": "11211"}],
}


class Chat(unittest.TestCase):

    def setUp(self):
        import copy
        self.db, self.proj = dry.world(copy.deepcopy(SC))      # the fixture's rows are never shared
        self.other = {"_id": "p77", "name": "77 Water", "address": "77 Water St, New York, NY",
                      "company_id": dry.COMPANY, "trade_assignments": [
                          {"id": "u1", "company": "Arkon Drywall", "trade": "Drywall"}]}
        self.db.projects.rows.append(self.other)
        self.db[wa_sender_map.COLLECTION].rows.extend([
            {"_id": "m_cw", "company_id": dry.COMPANY, "person_name": "Chris Weiss",
             "sub_company": "GC team", "sender_jid": "17185550301@c.us"},
            {"_id": "m_cl", "company_id": dry.COMPANY, "person_name": "Chris Lopez",
             "sub_company": "Arkon Drywall", "sender_jid": "17185550302@c.us"}])
        self.ident = {**dry._ident(self.proj, SC), "projects": [self.p588()]}
        self.sent, self.dob, self.dot, self.model, self.applied = [], [], [], None, []
        self.now = datetime.now(timezone.utc)

    def talk(self, *lines, ident=None):
        """Their messages, one by one, as the DM assistant gets them; the
        replies."""
        out = []

        async def send(chat, text, *a, **k):
            self.assertEqual(chat, CHAT)
            out.append(text)
            self.sent.append(text)
            return {"ok": True}

        async def geo(text, size=5):
            key = " ".join(dm_actions._fold(text).replace(" st", "").replace(" street", "").split())
            for k in sorted(GEO, key=len, reverse=True):
                if key.startswith(k):
                    return GEO[k]
            return []

        async def model(text, jobs):
            return self.model(text) if self.model else None

        async def dob(project):
            self.dob.append(str(project["_id"]))
            return []

        async def dot(**kw):
            self.dot.append(kw.get("project_ids"))
            return {}

        async def bin_(address):
            return {"nyc_bin": "3071234", "bbl": "3031560042", "track_dob_status": True,
                    "normalized_address": address}

        async def nothing(*a, **k):
            return None

        async def quiet(company_id, jid, row):
            self.applied.append((jid, (row or {}).get("person_name")))
            return 0

        who = ident or self.ident

        async def run():
            for line in lines:
                with patch.object(server, "db", self.db), \
                        patch.object(server, "send_whatsapp_message", send), \
                        patch.object(server, "_dm_geosearch", geo), \
                        patch.object(server, "_dm_action_model", model), \
                        patch.object(server, "run_dob_sync_for_project", dob), \
                        patch.object(server, "_dot_sync_tick", dot), \
                        patch.object(server, "fetch_nyc_bin_from_address", bin_), \
                        patch.object(server, "_react_to_message", nothing), \
                        patch.object(server, "_dm_answer_job", nothing), \
                        patch.object(server, "_dm_scope", lambda body: _done("project")), \
                        patch.object(server, "_sender_map_apply", quiet), \
                        patch.object(server, "_stamp_sender_phone", nothing), \
                        patch.object(server._stat_engine, "prewarm_peer_stats", nothing):
                    handled = await server._dm_action_turn(who, CHAT, line, new=False) or \
                        await server._dm_action_turn(who, CHAT, line, new=True)
                    if not handled:
                        out.append(None)
                await asyncio.sleep(0)
        asyncio.run(run())
        for text in out:
            if text:
                self.assertEqual(dm_actions.plain(text), [], text)       # rule one, every time
        return out

    def audits(self, action="whatsapp_dm_action"):
        return [a for a in self.db.audit_logs.rows if a.get("action") == action]

    def p588(self):
        return next(p for p in self.db.projects.rows if p["_id"] == "p588")

    def settings(self, project_id="p588"):
        row = next(r for r in self.db.notification_preferences.rows if r["project_id"] == project_id)
        return row["whatsapp_project"]

    # ── 1. Add a job ─────────────────────────────────────────────────────

    def test_add_a_job_in_their_words_then_undo(self):
        found, done = self.talk("add 9 menahan", "yeah")
        self.assertEqual(found, "Found it: 9 Menahan St, Brooklyn. Add it as a new job?")
        self.assertEqual(done, "Done — 9 Menahan St is set up. I'll start watching DOB and DOT for it.")
        made = next(p for p in self.db.projects.rows if p.get("name") == "9 Menahan St")
        self.assertEqual(made["company_id"], dry.COMPANY)
        self.assertEqual(made["address"], "9 MENAHAN STREET, Brooklyn, NY, USA")
        self.assertEqual(self.dob, [str(made["_id"])])                  # watched now
        self.assertEqual(self.dot, [[str(made["_id"])]])
        (a,) = self.audits()
        self.assertEqual((a["user_id"], a["details"]["via"], a["details"]["said"]),
                         (dry.WALKER_ID, "whatsapp_dm", "add 9 menahan"))
        self.assertEqual(self.talk("undo that"), ["Undone — 9 Menahan St is removed."])
        self.assertTrue(made["marked_for_deletion"])
        self.assertEqual(len(self.audits("whatsapp_dm_undo")), 1)
        self.assertEqual(self.talk("undo"), ["There's nothing to undo."])

    def test_a_voice_note_with_nothing_in_it_keeps_the_question_open(self):
        """Tue Oct 13: a 1-second voice note answering "what's the address?"
        got "I couldn't find that address. Which borough?". Nothing heard
        (empty, flagged, or Whisper's words for silence): "I couldn't hear
        that voice note — can you type it?", and the question stays open."""
        from lib import voice_ingest, wa_voice
        self.assertEqual(self.talk("starting a new job i wanna set up"),
                         ["Sure — what's the address?"])
        before = dict(next(r for r in self.db[server._DM_STATE].rows
                           if r.get("kind") == server.DM_ACTION_STATE))
        notes = [
            voice_ingest.VoiceIngestResult(ok=True, english_transcript="Thank you.",
                                           original_transcript="Thank you.", duration_sec=1.0),
            voice_ingest.VoiceIngestResult(ok=True, english_transcript=" … ", duration_sec=1.0),
            voice_ingest.VoiceIngestResult(ok=False, user_reply="resend", error_kind="no_speech",
                                           duration_sec=1.0),
            voice_ingest.VoiceIngestResult(ok=True, english_transcript="nine menahan",
                                           duration_sec=3.0, unreliable=["avg_logprob -1.4 < -1.0"]),
        ]
        for i, v in enumerate(notes):
            out = []

            async def send(chat, text, *a, **k):
                out.append(text)
                return {"ok": True}

            async def go():
                with patch.object(server, "db", self.db), \
                        patch.object(server, "send_whatsapp_message", send):
                    return await server._dm_voice_unheard(CHAT, v, f"m{i}")
            with self.subTest(i):
                self.assertTrue(asyncio.run(go()))
                self.assertEqual(out, [wa_voice.DM_CANT_HEAR])
        after = next(r for r in self.db[server._DM_STATE].rows
                     if r.get("kind") == server.DM_ACTION_STATE)
        self.assertEqual(after, before)                     # untouched: still open
        # The typed answer is still the answer to it.
        self.assertEqual(self.talk("9 menahan"),
                         ["Found it: 9 Menahan St, Brooklyn. Add it as a new job?"])

    def test_a_voice_note_that_says_something_goes_on_as_before(self):
        from lib import voice_ingest

        async def go(v):
            with patch.object(server, "db", self.db):
                return await server._dm_voice_unheard(CHAT, v, "m1")
        said = voice_ingest.VoiceIngestResult(ok=True, english_transcript="9 Menahan Street",
                                              duration_sec=2.5)
        self.assertFalse(asyncio.run(go(said)))
        # A failed note with no question open keeps its own reply.
        failed = voice_ingest.VoiceIngestResult(ok=False, user_reply="resend", duration_sec=1.0)
        self.assertFalse(asyncio.run(go(failed)))

    def test_several_matches_a_short_numbered_list(self):
        which, found = self.talk("we got a new job on 45 main st", "2")
        self.assertEqual(which, "I found a few. Which one?\n1) 45 Main St, Brooklyn\n"
                                "2) 45 Main St, Queens\n3) 45 Main St, Staten Island")
        self.assertEqual(found, "Found it: 45 Main St, Queens. Add it as a new job?")

    def test_no_match_asks_the_borough(self):
        ask, found = self.talk("start tracking 12 nowhere", "brooklyn")
        self.assertEqual(ask, "I couldn't find that address. Which borough is it in?")
        self.assertEqual(found, "Found it: 12 Nowhere Pl, Brooklyn. Add it as a new job?")

    def test_a_job_they_already_have(self):
        self.assertEqual(self.talk("start tracking 588 thomas boyland"),
                         ["588 Thomas St is already one of your jobs."])

    def test_in_spanish(self):
        found, done = self.talk("nuevo trabajo en 9 menahan", "sí")
        self.assertEqual(found, "Lo encontré: 9 Menahan St, Brooklyn. ¿Lo agrego como trabajo nuevo?")
        self.assertTrue(done.startswith("Listo — 9 Menahan St está creado."))

    def test_never_mind_before_yes_changes_nothing(self):
        n = len(self.db.projects.rows)
        self.assertEqual(self.talk("add 9 menahan", "wait no")[1], "OK, I won't do it.")
        self.assertEqual(len(self.db.projects.rows), n)
        self.assertEqual(self.audits(), [])

    def test_a_pm_cannot_add_a_job(self):
        pm = {**self.ident, "role": "pm"}
        self.assertEqual(self.talk("add 9 menahan", ident=pm),
                         ["Only a company admin can do that. I can add people, subs and punch contacts for you."])

    # ── 2. A sub on a job ────────────────────────────────────────────────

    def test_put_a_sub_on_a_job(self):
        ask, done = self.talk("put power direct on 588 they're the electrician", "👍")
        self.assertEqual(ask, "Add Power Direct (Electrical) to 588 Thomas St?")
        self.assertEqual(done, "Done — Power Direct is on 588 Thomas St for Electrical.")
        rows = self.p588()["trade_assignments"]
        self.assertTrue(any(r["company"] == "Power Direct" and r["trade"] == "Electrical" and r.get("id")
                            for r in rows))
        self.assertEqual(len(self.audits()), 1)
        self.assertEqual(self.talk("never mind"), ["Undone — Power Direct is off 588 Thomas St."])
        self.assertEqual(next(r for r in self.p588()["trade_assignments"]
                              if r["company"] == "Power Direct").get("status"), "inactive")

    def test_which_job_never_a_guess(self):
        self.ident["projects"] = [self.proj, self.other]
        which, ask = self.talk("no chasing the whole weekend", "2")
        self.assertEqual(which, "Which job?\n1) 588 Thomas St\n2) 77 Water St")
        self.assertEqual(ask, "Done — at 77 Water St, no chasing over Shabbos, Yom Tov or Sundays.")
        self.assertEqual(self.talk("put power direct on thomas they're plumbers"),
                         ["Add Power Direct (Plumbing) to 588 Thomas St?"])

    def test_a_job_named_that_they_dont_have(self):
        self.ident["projects"] = [self.proj, self.other]
        (ask,) = self.talk("put power direct on 120 broadway as the electrician")
        self.assertEqual(ask, "I don't see that job. Which one did you mean?\n1) 588 Thomas St\n"
                              "2) 77 Water St")

    # ── 3. A person ──────────────────────────────────────────────────────

    def test_add_a_person_never_their_whole_number(self):
        ask, done = self.talk("chris is our super his number is 718 555 1234", "👍")
        self.assertEqual(ask, "Save Chris (GC), number ending 1234?")
        self.assertEqual(done, "Done — Chris is saved.")
        row = next(r for r in self.db[wa_sender_map.COLLECTION].rows
                   if r["sender_jid"] == "17185551234@c.us")
        self.assertEqual((row["person_name"], row["sub_company"], row["role"]),
                         ("Chris", "GC team", "super"))
        (a,) = self.audits()
        self.assertEqual(a["details"]["after"]["phone_last4"], "1234")
        self.assertNotIn("7185551234", json.dumps(a["details"]))
        self.talk("undo")
        self.assertFalse(any(r["sender_jid"] == "17185551234@c.us"
                             for r in self.db[wa_sender_map.COLLECTION].rows))

    def test_one_question_at_a_time(self):
        self.assertEqual(self.talk("add dov"), [None])   # not an address, nothing else: no change
        out = self.talk("dov's number is 917 555 0199", "bright", "yes")
        self.assertEqual(out, ["Who does Dov work for?", "Save Dov (Bright Electric), number ending 0199?",
                               "Done — Dov is saved."])

    def test_a_company_not_on_their_jobs(self):
        out = self.talk("dov from power direct his cell is (917) 555 0199")
        self.assertEqual(out, ["I don't see Power Direct on your jobs. Who does Dov work for?"])

    def test_a_pm_can_save_people(self):
        pm = {**self.ident, "role": "pm"}
        self.assertEqual(self.talk("Juan 347 555 7788 our foreman", "ok", ident=pm)[1],
                         "Done — Juan is saved.")

    # ── 4. A sub's punch contact ─────────────────────────────────────────

    def test_punch_contact_new_person(self):
        # Luis Ortega is saved -- with Arkon Drywall: not the one meant.
        out = self.talk("luis handles punch for quality plumbing")
        self.assertEqual(out, ["I don't have Luis from Quality Plumbing saved yet. What's their number?"])
        out = self.talk("917 555 0199", "yes")
        self.assertEqual(out, ["Send Quality Plumbing's punch lists at 588 Thomas St to Luis?",
                               "Done — Luis gets Quality Plumbing's punch lists at 588 Thomas St."])
        m = next(r for r in self.db[wa_sender_map.COLLECTION].rows
                 if r["sender_jid"] == "19175550199@c.us")
        self.assertEqual(m["sub_company"], "Quality Plumbing")
        self.assertEqual(self.settings()["punch_contacts"]["t2"], str(m["_id"]))

    def test_which_chris_never_a_guess(self):
        self.proj["trade_assignments"].append({"id": "t7", "company": "GC team", "trade": "General"})
        self.db[wa_sender_map.COLLECTION].rows[-1]["sub_company"] = "GC team"
        (ask,) = self.talk("chris handles punch for gc team")
        self.assertEqual(ask, "Which Chris — Chris Weiss (GC) or Chris Lopez (GC)?")
        out = self.talk("2", "yes")
        self.assertEqual(out[0], "Send GC team's punch lists at 588 Thomas St to Chris Lopez?")
        self.assertEqual(self.settings()["punch_contacts"]["t7"], "m_cl")

    def test_the_right_chris_by_their_company(self):
        # Chris Weiss (GC team) and Chris Lopez (Arkon Drywall): Arkon's is Lopez.
        (ask,) = self.talk("punch contact for arkon is chris")
        self.assertEqual(ask, "Send Arkon Drywall's punch lists at 588 Thomas St to Chris Lopez?")

    # ── Codex review on #768 ─────────────────────────────────────────────

    def test_an_account_not_approved_changes_nothing(self):
        pending = {**self.ident, "user": {**self.ident["user"], "account_status": "pending"}}
        n = len(self.db.projects.rows)
        self.assertEqual(self.talk("add 9 menahan", ident=pending),
                         ["Your account isn't approved yet, so I can't make changes. Ask your admin."])
        self.assertEqual(self.talk("chris is our super his number is 718 555 1234", ident=pending),
                         ["Your account isn't approved yet, so I can't make changes. Ask your admin."])
        # Approved when asked, not any more at "yes": still nothing.
        self.talk("add 9 menahan")
        self.assertEqual(self.talk("yes", ident=pending),
                         ["Your account isn't approved yet, so I can't make changes. Ask your admin."])
        self.assertEqual((len(self.db.projects.rows), self.audits()), (n, []))

    def test_the_audit_never_keeps_a_whole_number(self):
        self.talk("chris is our super, his number is (718) 555-1234", "yes")
        (a,) = self.audits()
        self.assertEqual(a["details"]["said"], "chris is our super, his number is …1234")
        flat = json.dumps(a, default=str)
        for leak in ("555-1234", "555 1234", "5551234", "(718)"):
            self.assertNotIn(leak, flat)

    def test_a_roster_row_from_before_ids(self):
        row = next(r for r in self.p588()["trade_assignments"] if r["company"] == "Quality Plumbing")
        row.pop("id")
        self.talk("luis handles punch for quality plumbing", "917 555 0199", "yes")
        row = next(r for r in self.p588()["trade_assignments"] if r["company"] == "Quality Plumbing")
        self.assertTrue(row.get("id"))                                   # minted
        self.assertIn(row["id"], self.settings()["punch_contacts"])

    def test_undo_a_person_puts_their_items_back(self):
        self.talk("chris is our super his number is 718 555 1234", "yes")
        self.assertEqual(self.applied, [("17185551234@c.us", "Chris")])
        self.talk("undo")
        self.assertEqual(self.applied[-1], ("17185551234@c.us", None))   # re-pointed back

    def test_two_rows_of_one_sub_never_a_guess(self):
        self.p588()["trade_assignments"].append(
            {"id": "t8", "company": "Quality Plumbing", "trade": "Sprinkler"})
        which, ask = self.talk("jose handles punch for quality plumbing", "2")
        self.assertEqual(which, "Which one?\n1) Quality Plumbing (Plumbing)\n2) Quality Plumbing (Sprinkler)")
        self.assertEqual(ask, "Send Quality Plumbing's punch lists at 588 Thomas St to Jose Zarate?")
        self.talk("yes")
        self.assertEqual(self.settings()["punch_contacts"]["t8"], "m_j")

    # ── 5. Settings ──────────────────────────────────────────────────────

    def test_weekends_off_then_undo(self):
        self.settings()["chase_weekends"] = True            # an old "chase on weekends" on
        ask, done = self.talk("stop bugging people on weekends at 588", "sunday too")
        self.assertEqual(ask, "Just Shabbos (Fri evening to Sat night), or Sunday too?")
        self.assertEqual(done, "Done — at 588 Thomas St, no chasing over Shabbos, Yom Tov or Sundays.")
        self.assertIs(self.settings()["chase_shabbos_off"], True)
        self.assertIs(self.settings()["chase_sundays_off"], True)
        (a,) = self.audits()
        self.assertEqual((a["details"]["before"], a["details"]["after"]),
                         ({"chase_shabbos_off": False, "chase_sundays_off": False},
                          {"chase_shabbos_off": True, "chase_sundays_off": True}))
        self.assertEqual(self.talk("undo"), ["Undone — 588 Thomas St is back the way it was."])
        self.assertIs(self.settings()["chase_shabbos_off"], False)
        self.assertIs(self.settings()["chase_sundays_off"], False)

    def test_already_so(self):
        self.assertEqual(self.talk("no weekend reminders at 588", "just shabbos"),
                         ["Just Shabbos (Fri evening to Sat night), or Sunday too?",
                          "Already set — at 588 Thomas St, no chasing over Shabbos and Yom Tov; "
                          "Sundays are on."])

    def test_punch_for_real_needs_the_address_typed(self):
        ask, done = self.talk("start sending punch lists for real at 588", "588 thomas st")
        self.assertEqual(ask, "This makes punch lists really go out to the subs at 588 Thomas St. "
                              "To confirm, type the job's address.")
        self.assertEqual(done, "Done — punch lists at 588 Thomas St now really go out.")
        self.assertEqual(self.settings()["punch_sends"], "live")

    def test_a_yes_is_not_the_address(self):
        out = self.talk("punch at 588 for real", "yes")
        self.assertEqual(out[1], "That didn't match the address, so nothing changed.")
        self.assertEqual(self.settings()["punch_sends"], "shadow")
        self.assertEqual(self.audits(), [])

    def test_only_an_admin_turns_it_live(self):
        pm = {**self.ident, "role": "pm"}
        self.assertEqual(self.talk("start sending punch lists for real at 588", ident=pm),
                         ["Only a company admin can do that. I can add people, subs and punch contacts for you."])

    # ── What it cannot do ────────────────────────────────────────────────

    def test_cannot_do_says_what_it_can(self):
        (said,) = self.talk("delete 588")
        self.assertEqual(said, "I can't do that here yet — please use the app. "
                               "I can add jobs, subs and people, and change job settings.")

    def test_undo_is_10_minutes(self):
        self.talk("put power direct on 588 they're the electrician", "yes")
        last = next(r for r in self.db[server._DM_STATE].rows if r["kind"] == server.DM_ACTION_LAST)
        last["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.assertEqual(self.talk("undo"), ["There's nothing to undo."])

    def test_through_the_dm_assistant_a_thumbs_up_answers(self):
        # The whole DM path: a 👍 is the "yes" to "Add it?", not a thank-you.
        out, reacted = [], []

        async def send(chat, text, *a, **k):
            out.append(text)

        async def react(chat, mid, emoji):
            reacted.append(emoji)

        async def nothing(*a, **k):
            return []

        async def geo(text, size=5):
            return GEO["9 menahan"]

        async def bin_(address):
            return {"nyc_bin": None, "bbl": None, "track_dob_status": False,
                    "normalized_address": address}

        async def model(text, jobs):
            return None

        async def run():
            with patch.object(server, "db", self.db), \
                    patch.object(server, "send_whatsapp_message", send), \
                    patch.object(server, "_react_to_message", react), \
                    patch.object(server, "_dm_history", nothing), \
                    patch.object(server, "_dm_store_inbound", nothing), \
                    patch.object(server, "_dm_geosearch", geo), \
                    patch.object(server, "_dm_action_model", model), \
                    patch.object(server, "fetch_nyc_bin_from_address", bin_), \
                    patch.object(server, "run_dob_sync_for_project", nothing), \
                    patch.object(server, "_dot_sync_tick", nothing), \
                    patch.object(server._stat_engine, "prewarm_peer_stats", nothing):
                await server._dm_assistant_reply(self.ident, CHAT, "add 9 menahan", "m1")
                await server._dm_assistant_reply(self.ident, CHAT, "👍", "m2")
                await asyncio.sleep(0)
        asyncio.run(run())
        self.assertEqual(out, ["Found it: 9 Menahan St, Brooklyn. Add it as a new job?",
                               "Done — 9 Menahan St is set up. I'll start watching DOB and DOT for it."])
        self.assertEqual(reacted, [])

    def test_questions_still_go_to_the_assistant(self):
        self.assertEqual(self.talk("who's on site at 588", "how many workers today"), [None, None])

    # ── The model ────────────────────────────────────────────────────────

    def test_the_model_reads_what_the_patterns_cannot(self):
        self.model = lambda text: {"action": "add_job", "address": "9 menahan",
                                   "borough": "brooklyn"}
        self.assertEqual(self.talk("yo we picked up that bldg on menahan 9 bk")[0],
                         "Found it: 9 Menahan St, Brooklyn. Add it as a new job?")

    def test_a_bad_model_answer_never_acts(self):
        self.model = lambda text: {"action": "delete_company", "company": "all"}
        n = len(self.db.projects.rows)
        # The model's garbage is dropped; the patterns' own reading asks
        # first (Mon 7:17 PM fix: a model miss never falls to "Which job?").
        self.assertEqual(self.talk("add 9 menahan"),
                         ["Found it: 9 Menahan St, Brooklyn. Add it as a new job?"])
        self.talk("no")
        self.assertEqual((len(self.db.projects.rows), self.audits()), (n, []))
        self.model = lambda text: {"action": "add_person", "name": "Dov", "phone": "917 555 019",
                                   "company": "Bright Electric"}
        self.assertEqual(self.talk("dovs cell is 917 555 019 hes with bright"),
                         ["That doesn't look like a phone number. Can you send it again?"])

    def test_the_request_the_model_gets(self):
        sent = {}

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": '{"action": "add_job", "address": "9 menahan"}'}}]}

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, headers=None, json=None):
                sent.update(json)
                return _Resp()
        with patch.object(server, "ServerHttpClient", _Client), patch.object(server, "OPENAI_API_KEY", "k"):
            got = asyncio.run(server._dm_action_model("add 9 menahan", ["588 Thomas St"]))
        self.assertEqual(got, {"action": "add_job", "address": "9 menahan"})
        self.assertEqual(sent["response_format"], {"type": "json_object"})
        self.assertEqual(sent["temperature"], 0)
        self.assertIn("588 Thomas St", sent["messages"][0]["content"])
        with patch.object(server, "OPENAI_API_KEY", ""):
            self.assertIsNone(asyncio.run(server._dm_action_model("x", [])))


async def _done(v):
    return v


if __name__ == "__main__":
    unittest.main()
