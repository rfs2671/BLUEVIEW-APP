"""Real WhatsApp @mentions (lib/wa_mention.py, server._mention_target,
send_whatsapp_message mentions=, _group_post).

Pinned:
  * the `mentions` array always matches the "@<number>" tokens in the text;
    a mismatch is never sent as mentions;
  * a mention send counts only when WaAPI answers data.status "success";
  * the app's copy of a post reads "@Name", never the number;
  * a person's number: Levelog user phone -> People phone -> the id itself
    when it is a phone -> WaAPI lid lookup (mocked), cached per company for
    a week; unresolved keeps "@Name", logs "[mention] unresolved" and the
    screens say "mention won't notify (no number)";
  * chase stays shadow (nothing sent) and records the post as it would go
    out, replying to the chased message by WaAPI's serialized id;
  * People mapping takes an optional phone.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException  # noqa: E402

import server  # noqa: E402
from lib import punch  # noqa: E402
from lib import wa_mention as m  # noqa: E402
from tests._fake_mongo import FakeDb  # noqa: E402
from tests.test_whatsapp_chase import _Base, _et, _item  # noqa: E402
from tests.test_whatsapp_attention import CO_A, CO_B, MIKE  # noqa: E402
from tests.test_whatsapp_sender_map import (  # noqa: E402
    PROJ_A, _assign, _db as _sm_db, _people,
)

LID = "84894491394148@lid"
GROUP = "120363000000000001@g.us"
NOW = datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc)


def _run(c):
    return asyncio.run(c)


class TheRules(unittest.TestCase):

    def test_phone_numbers(self):
        self.assertEqual(m.phone("(718) 555-0100"), "17185550100")
        self.assertEqual(m.phone("+1 718 555 0100"), "17185550100")
        self.assertEqual(m.phone("17185550100@c.us"), "17185550100")
        self.assertEqual(m.phone("972 52 123 4567"), "972521234567")
        self.assertIsNone(m.phone(LID))
        self.assertIsNone(m.phone("12345"))
        self.assertIsNone(m.phone(""))

    def test_handle_is_the_number_when_known_else_the_name(self):
        self.assertEqual(m.handle("Carlos", "17185550100"), "@17185550100")
        self.assertEqual(m.handle("Carlos  Baez", None), "@Carlos Baez")
        t = m.target("Carlos", "7185550100", "people")
        self.assertEqual((t["phone"], t["handle"], t["resolved"], t["source"]),
                         ("17185550100", "@17185550100", True, "people"))
        u = m.target("Carlos", None)
        self.assertEqual((u["handle"], u["resolved"], u["source"]), ("@Carlos", False, "none"))

    def test_mentions_match_the_text_tokens(self):
        a, b, c = (m.target("Ana", "17185550001"), m.target("Bo", "17185550002"),
                   m.target("Cy", None))
        text = f"{b['handle']} and {a['handle']} and {c['handle']}: see above"
        mentions = m.mentions_for(text, [a, b, c])
        self.assertEqual(mentions, ["17185550002@c.us", "17185550001@c.us"])
        self.assertIsNone(m.check(text, mentions))
        self.assertTrue(all(m.MENTION_JID.match(j) for j in mentions))
        # Not in the text: not mentioned.
        self.assertEqual(m.mentions_for("@Ana hi", [a]), [])

    def test_a_mismatch_is_caught_either_way(self):
        self.assertIn("not in the text", m.check("@Ana hi", ["17185550001@c.us"]))
        # Someone's own "@<number>" quoted in the post is plain text: fine.
        self.assertIsNone(m.check("@17185550001 hi", []))
        self.assertIn("bad jid", m.check("@17185550001 hi", ["17185550001@lid"]))
        # An email or a P-id is not a mention token.
        self.assertEqual(m.tokens("mail a@17185550001.com, P-588-12, @171855"), [])

    def test_the_app_copy_reads_names(self):
        a = m.target("Ana Ortiz", "17185550001")
        self.assertEqual(m.display("@17185550001 punch list — due Fri:", [a]),
                         "@Ana Ortiz punch list — due Fri:")

    def test_sent_ok_needs_success(self):
        self.assertTrue(m.sent_ok({"data": {"status": "success"}}))
        self.assertFalse(m.sent_ok({"data": {"status": "error"}}))
        self.assertFalse(m.sent_ok({}))
        self.assertFalse(m.sent_ok(None))

    def test_the_get_lid_answer(self):
        self.assertEqual(m.LID_ACTION, "get-lid")
        self.assertEqual(m.lookup_body([LID, "1@lid"]), {"contactIds": [LID, "1@lid"]})
        ok = {"data": {"status": "success", "data": {"count": 2, "contacts": [
            {"lid": LID, "pn": "17185550100@c.us"}, {"lid": "1@lid"}]}}}
        self.assertEqual(m.phones_from_lookup(ok, [LID, "1@lid", "2@lid"]),
                         {LID: "17185550100", "1@lid": None, "2@lid": None})
        # Not a success: nothing learned (None), not "no number".
        self.assertIsNone(m.phones_from_lookup({"data": {"status": "error"}}, [LID]))
        self.assertIsNone(m.phones_from_lookup(None, [LID]))
        # No guessing: a number anywhere else in the answer is not read.
        odd = {"data": {"status": "success", "phone": "17185550100",
                        "data": {"contacts": [{"lid": LID, "phone": "17185550100@c.us"}]}}}
        self.assertEqual(m.phones_from_lookup(odd, [LID]), {LID: None})

    def test_chunks_of_50(self):
        self.assertEqual([len(c) for c in m.chunks([str(i) for i in range(120)])], [50, 50, 20])


class _Waapi:
    """Stands in for _waapi_post_raw: records each call; answers send-message
    with `send` and the lid lookup with `lookup`."""

    def __init__(self, send=None, lookup=None, code=200, status="success"):
        self.calls, self.send, self.code, self.status = [], send, code, status
        self.lookup = lookup or {}          # {lid: phone}: what WaAPI knows

    async def __call__(self, url, payload, headers):
        self.calls.append((url.rsplit("/", 1)[-1], dict(payload)))
        if url.endswith("send-message"):
            return 200, self.send if self.send is not None else {"data": {"status": "success"}}, None
        ids = payload.get("contactIds") or []
        contacts = [{"lid": l, **({"pn": f"{self.lookup[l]}@c.us"} if self.lookup.get(l) else {})}
                    for l in ids]
        return self.code, {"data": {"status": self.status,
                                    "data": {"contacts": contacts, "count": len(contacts)}}}, None


def _ctx(db, waapi):
    return [patch.object(server, "db", db), patch.object(server, "_waapi_post_raw", waapi),
            patch.object(server, "WAAPI_INSTANCE_ID", "inst"),
            patch.object(server, "WAAPI_TOKEN", "tok")]


def _with(ps, coro):
    for p in ps:
        p.start()
    try:
        return _run(coro)
    finally:
        for p in ps:
            p.stop()


class TheSend(unittest.TestCase):

    def setUp(self):
        self.db = FakeDb(whatsapp_messages=[], whatsapp_groups=[])

    def test_a_group_post_carries_mentions_and_logs_names(self):
        w = _Waapi()
        a = m.target("Ana Ortiz", "17185550001")
        text = f"{a['handle']} punch list — due Fri:"
        with patch.object(server, "_resolve_group_binding", lambda g: _async({"status": "x"})):
            out = _with(_ctx(self.db, w), server._group_post(GROUP, text, [a], reply_to="false_x_y"))
        self.assertTrue(out)
        (action, payload), = w.calls
        self.assertEqual(action, "send-message")
        self.assertEqual(payload["message"], "@17185550001 punch list — due Fri:")
        self.assertEqual(payload["mentions"], ["17185550001@c.us"])
        self.assertEqual(payload["replyToMessageId"], "false_x_y")
        self.assertEqual(self.db.whatsapp_messages.rows[-1]["body"],
                         "@Ana Ortiz punch list — due Fri:")

    def test_not_success_is_not_sent(self):
        w = _Waapi(send={"data": {"status": "error", "message": "bad mention"}})
        a = m.target("Ana", "17185550001")
        with patch.object(server, "_resolve_group_binding", lambda g: _async({})):
            out = _with(_ctx(self.db, w), server._group_post(GROUP, f"{a['handle']} hi", [a]))
        self.assertIsNone(out)

    def test_unresolved_goes_plain_without_mentions(self):
        w = _Waapi()
        u = m.target("Cy", None)
        with patch.object(server, "_resolve_group_binding", lambda g: _async({})):
            _with(_ctx(self.db, w), server._group_post(GROUP, f"{u['handle']} hi", [u]))
        (_a, payload), = w.calls
        self.assertEqual(payload["message"], "@Cy hi")
        self.assertNotIn("mentions", payload)

    def test_a_mismatched_mention_list_is_dropped(self):
        w = _Waapi()
        with patch.object(server, "_resolve_group_binding", lambda g: _async({})), \
                self.assertLogs(server.logger, "ERROR") as logs:
            _with(_ctx(self.db, w), server.send_whatsapp_message(
                GROUP, "@Ana hi", mentions=["17185550001@c.us"]))
        (_a, payload), = w.calls
        self.assertNotIn("mentions", payload)
        self.assertTrue(any("[mention] not sent as mentions" in l for l in logs.output))

    def test_a_quoted_at_number_does_not_cost_the_real_mention(self):
        w = _Waapi()
        a = m.target("Ana", "17185550001")
        text = f"{a['handle']} end of day — did this get done?\n“call @17185550200 about the crane”"
        db = FakeDb(whatsapp_messages=[], whatsapp_groups=[])
        with patch.object(server, "_resolve_group_binding", lambda g: _async({})):
            _with(_ctx(db, w), server._group_post(GROUP, text, [a]))
        (_a, payload), = w.calls
        self.assertEqual(payload["mentions"], ["17185550001@c.us"])


async def _async(v):
    return v


class WhoseNumber(unittest.TestCase):

    def setUp(self):
        self.db = FakeDb(
            users=[{"_id": "u1", "company_id": CO_A, "name": "Roy", "phone": "(718) 555-0100"},
                   {"_id": "u2", "company_id": CO_A, "name": "No Phone"}],
            whatsapp_sender_map=[
                {"_id": "m1", "company_id": CO_A, "sender_jid": "999@lid", "person_name": "Pat",
                 "phone": "17185550111"},
                {"_id": "m2", "company_id": CO_A, "sender_jid": LID, "person_name": "Chris"},
                {"_id": "m3", "company_id": CO_B, "sender_jid": LID, "person_name": "Other",
                 "phone": "17185550999"}])

    def target(self, person, waapi=None, company=CO_A, now=NOW):
        return _with(_ctx(self.db, waapi or _Waapi()),
                     server._mention_target(person, company, now))

    def test_a_levelog_user_phone_first(self):
        t = self.target({"kind": "user", "id": "u1", "name": "Roy", "jid": LID})
        self.assertEqual((t["phone"], t["source"]), ("17185550100", "user"))

    def test_then_the_people_mapping_phone(self):
        t = self.target({"kind": "sender_map", "id": "m1", "name": "Pat", "jid": "999@lid"})
        self.assertEqual((t["phone"], t["source"]), ("17185550111", "people"))

    def test_then_the_id_itself_when_it_is_a_phone(self):
        t = self.target({"kind": "worker", "id": "w1", "name": "Joe", "jid": "17185550222@c.us"})
        self.assertEqual((t["phone"], t["source"]), ("17185550222", "jid"))

    def test_then_the_lid_lookup_cached_per_company_for_a_week(self):
        w = _Waapi(lookup={LID: "17185550333"})
        person = {"kind": "sender_map", "id": "m2", "name": "Chris", "jid": LID}
        t = self.target(person, w)
        self.assertEqual((t["phone"], t["source"]), ("17185550333", "lid_lookup"))
        self.assertEqual(w.calls[0], ("get-lid", {"contactIds": [LID]}))
        # Cached: no second call within the week (and not another company's).
        self.target(person, w, now=NOW + timedelta(days=6))
        self.assertEqual(len(w.calls), 1)
        cache = self.db[m.LOOKUP_COLLECTION].rows
        self.assertEqual([r["_id"] for r in cache], [f"{CO_A}|{LID}"])
        # A week on: asked again.
        self.target(person, w, now=NOW + timedelta(days=8))
        self.assertEqual(len(w.calls), 2)

    def test_another_companys_mapping_is_never_used(self):
        w = _Waapi()
        t = self.target({"kind": "sender_map", "id": "m2", "name": "Chris", "jid": LID}, w)
        self.assertFalse(t["resolved"])           # not CO_B's 17185550999

    def test_unresolved_keeps_the_name_and_logs(self):
        w = _Waapi()                               # success, but no pn for it
        with self.assertLogs(server.logger, "INFO") as logs:
            t = self.target({"kind": "user", "id": "u2", "name": "No Phone", "jid": "555@lid"}, w)
        self.assertEqual((t["handle"], t["resolved"]), ("@No Phone", False))
        self.assertTrue(any("[mention] unresolved" in l for l in logs.output))
        # "No number" is remembered for the week too.
        self.target({"kind": "user", "id": "u2", "name": "No Phone", "jid": "555@lid"}, w)
        self.assertEqual(len(w.calls), 1)
        self.assertIsNone(self.db[m.LOOKUP_COLLECTION].rows[0]["phone"])

    def test_a_failed_lookup_is_not_cached(self):
        for w in (_Waapi(code=500), _Waapi(status="error", lookup={LID: "17185550333"})):
            t = self.target({"kind": "sender_map", "id": "m2", "name": "Chris", "jid": LID}, w)
            self.assertFalse(t["resolved"])
            self.assertEqual(self.db[m.LOOKUP_COLLECTION].rows, [])

    def test_many_lids_are_asked_together_50_per_call(self):
        lids = [f"{9000 + i}@lid" for i in range(120)]
        w = _Waapi(lookup={lids[0]: "17185550001", lids[119]: "17185550119"})
        people = [{"kind": "worker", "id": str(i), "name": f"P{i}", "jid": l}
                  for i, l in enumerate(lids)]
        people.append({"kind": "user", "id": "u1", "name": "Roy"})   # has a phone: never asked
        got = _with(_ctx(self.db, w), server._mention_targets(people, CO_A, NOW))
        self.assertEqual([len(c[1]["contactIds"]) for c in w.calls], [50, 50, 20])
        self.assertEqual((got[0]["phone"], got[119]["phone"], got[50]["resolved"]),
                         ("17185550001", "17185550119", False))
        self.assertEqual(got[-1]["source"], "user")
        self.assertEqual(len(self.db[m.LOOKUP_COLLECTION].rows), 120)
        # Again within the week: all from the cache, no call.
        _with(_ctx(self.db, w), server._mention_targets(people, CO_A, NOW + timedelta(days=1)))
        self.assertEqual(len(w.calls), 3)


class TheChase(_Base):
    """Still shadow: _Base fails the test if anything is sent."""

    def test_a_resolved_owner_mentions_and_replies_to_the_message(self):
        it = _item(self.db)
        self.db.whatsapp_messages.rows.append({
            "_id": "wm", "group_id": it["group_id"], "message_id": it["evidence"]["message_id"],
            "message_id_serialized": f"false_{it['group_id']}_{it['evidence']['message_id']}_x@lid"})
        self.chase(_et(8, 35))
        (r,) = self.rows()
        self.assertEqual(r["send_text"].splitlines()[0], f"@{MIKE} morning — this is due today:")
        self.assertEqual(r["mentions"], [f"{MIKE}@c.us"])
        self.assertIsNone(m.check(r["send_text"], r["mentions"]))
        self.assertTrue(r["text"].startswith("@Mike Rivera "))
        self.assertEqual(r["reply_to"], f"false_{it['group_id']}_{it['evidence']['message_id']}_x@lid")
        self.assertIsNone(server._chase_view(r)["mention_note"])
        self.assertNotIn(MIKE, str(server._chase_view(r)))

    def test_an_owner_with_no_number_is_flagged(self):
        _item(self.db, owner={"jid": "301000000000004@lid", "id": "m_none"})
        self.chase(_et(8, 35))
        (r,) = self.rows()
        self.assertEqual(r["mentions"], [])
        self.assertTrue(r["send_text"].startswith("@Mike Rivera "))
        self.assertEqual(r["mention"], {"resolved": False, "source": "none"})
        self.assertEqual(server._chase_view(r)["mention_note"], "mention won't notify (no number)")


class PunchShadow(unittest.TestCase):

    def test_shadow_text_flags_who_wont_be_notified(self):
        rows = [{"pid": "P-588-1", "text": "outlet cover", "floor": "6", "area": "?"}]
        out = punch.shadow_text([
            {"name": "Ana Ortiz", "items": rows, "due_words": "Fri", "mention_resolved": True},
            {"name": "Luis Ortega", "items": rows, "due_words": "Fri", "mention_resolved": False}])
        self.assertIn("@Ana Ortiz punch list — due Fri:", out)
        self.assertNotIn("(@Ana Ortiz: mention won't notify", out)
        self.assertIn("(@Luis Ortega: mention won't notify (no number))", out)


class PeoplePhone(unittest.TestCase):

    def _key(self, db):
        from tests.test_whatsapp_sender_map import _msg, LID as SLID
        _msg(db, "morning all", sender=SLID, jid=f"{SLID}@lid", sender_name="Chris")
        return _people(db)["senders"][0]["key"]

    def test_an_optional_phone_is_kept_and_shown_by_role(self):
        db = _sm_db()
        key = self._key(db)
        from tests.test_whatsapp_sender_map import _call
        out, _ = _call(db, server.set_whatsapp_person, PROJ_A["_id"], key,
                       server.SenderMapBody(person_name="Chris", sub_company="Bright Electric",
                                            phone="(718) 555-0144"),
                       project=PROJ_A, current_user=_admin())
        # An admin sees the full number; a PM the last 4.
        self.assertEqual(out["assigned"]["phone"], "+1 718-555-0144")
        self.assertEqual(out["phone"], "+1 718-555-0144")
        row = db.whatsapp_sender_map.rows[0]
        self.assertEqual(row["phone"], "17185550144")
        from tests.test_whatsapp_attention import PM
        pm_rows = _people(db, user=PM)["senders"]
        self.assertEqual((pm_rows[0]["assigned"]["phone"], pm_rows[0]["phone"]), ("…0144", "…0144"))
        # Kept for good on the sender's earlier messages, with how and when.
        msgs = [m for m in db.whatsapp_messages.rows if m.get("sender_jid", "").endswith("@lid")]
        self.assertTrue(msgs and all(m["sender_phone"] == "17185550144"
                                     and m["sender_phone_source"] == "people"
                                     and m["sender_phone_at"] for m in msgs))
        # Saved again without a phone (the form never re-sends it): kept.
        out, _ = _assign(db, key, "Chris B", "Bright Electric")
        self.assertEqual(out["assigned"]["phone"], "+1 718-555-0144")
        # An explicit "" clears it.
        out, _ = _call(db, server.set_whatsapp_person, PROJ_A["_id"], key,
                       server.SenderMapBody(person_name="Chris B", sub_company="Bright Electric",
                                            phone=""),
                       project=PROJ_A, current_user=_admin())
        self.assertIsNone(out["assigned"]["phone"])

    def test_no_phone_is_fine_and_a_bad_one_is_refused(self):
        db = _sm_db()
        from tests.test_whatsapp_sender_map import _call
        key = self._key(db)
        out, _ = _assign(db, key, "Chris", "Bright Electric")
        self.assertIsNone(out["assigned"]["phone"])
        with self.assertRaises(HTTPException) as e:
            _call(db, server.set_whatsapp_person, PROJ_A["_id"], key,
                  server.SenderMapBody(person_name="Chris", sub_company="Bright Electric",
                                       phone="12"),
                  project=PROJ_A, current_user=_admin())
        self.assertEqual(e.exception.status_code, 422)


class TheDryRuns(unittest.TestCase):

    def test_punch_live_every_post_mentions_exactly_its_tokens(self):
        import json as _json
        from scripts import punch_dry_run as pdry
        sc = _json.loads((Path(pdry.__file__).parent / "dry_run_punch"
                          / "walk_588_2026_10.json").read_text(encoding="utf-8"))
        sc["punch_sends"] = "live"
        i = next(k for k, l in enumerate(sc["dm"]) if l.get("text") == "electrical Mon, everything else Fri")
        sc["dm"] = [{k: v for k, v in l.items() if k != "expect"} for l in sc["dm"][:i + 1]]
        sc["group"], sc["dm_after"] = [], []
        sc["expect"] = {"mention_resolved": ["Mike Rivera", "Jose Zarate", "Ana Ortiz"],
                        "mention_unresolved": []}
        res = asyncio.run(pdry.run(sc))
        self.assertEqual([w for ok, w in res["checks"] if not ok], [])
        posts = {p["text"].split(" ")[0]: p["mentions"] for p in res["mention_posts"]}
        self.assertEqual(len(res["mention_posts"]), 4)
        for p in res["mention_posts"]:
            self.assertIsNone(m.check(p["text"], p["mentions"]))
        self.assertEqual(posts["@17185550203"], ["17185550203@c.us"])      # Ana, by lookup
        self.assertEqual(posts["@Luis"], [])                                # no number: plain
        shown = [t for _n, _c, t in res["group_posts"] if _n == "send_whatsapp_message"]
        self.assertTrue(any(t.startswith("@Ana Ortiz punch list") for t in shown))
        self.assertFalse(any("17185550203" in t for t in shown))

    def test_chase_dry_run_rows_mention_exactly_their_tokens(self):
        from scripts import attention_dry_run as adry
        sc = adry.load(str(Path(adry.__file__).parent / "dry_run" / "busy_group_2026_10.json"))
        out = asyncio.run(adry.run(sc, scripted=True))
        rows = [r for r in out["db"]["chase_shadow"].rows if r.get("kind") == "group"]
        self.assertTrue(rows)
        self.assertEqual(out["sent"], [])                                 # still shadow
        for r in rows:
            self.assertIsNone(m.check(r["send_text"], r["mentions"]), r["_id"])
            self.assertIn(r["mention"]["resolved"], (True, False))


# ══════════════════════════════════════════════════════════════════════════
# A PHONE NUMBER IS EVIDENCE: kept for good, shown by role, never logged
# ══════════════════════════════════════════════════════════════════════════

class EvidenceDisplay(unittest.TestCase):

    def test_admins_full_others_last4(self):
        self.assertEqual(m.pretty("17187559520"), "+1 718-755-9520")
        self.assertEqual(m.shown("17187559520", True), "+1 718-755-9520")
        self.assertEqual(m.shown("17187559520", False), "…9520")
        self.assertEqual(m.shown(None, True), "")
        self.assertEqual(m.evidence_line("Mark Rivera", "17187559520", "Oct 10, 11:11:11 AM", True),
                         "Mark Rivera · +1 718-755-9520 · Oct 10, 11:11:11 AM")
        self.assertEqual(m.evidence_line("Mark Rivera", "17187559520", "Oct 10, 11:11:11 AM", False),
                         "Mark Rivera · …9520 · Oct 10, 11:11:11 AM")

    def test_no_phone_in_server_logs_for_chats(self):
        self.assertEqual(server._log_chat("17185550100@c.us"), "dm…0100")
        self.assertEqual(server._log_chat("120363000000000001@g.us"), "120363000000000001@g.us")


class EvidenceKept(unittest.TestCase):

    def setUp(self):
        self.db = FakeDb(whatsapp_messages=[], whatsapp_groups=[], whatsapp_sender_map=[])

    def store(self, jid, now=NOW):
        parsed = {"sender": jid, "push_name": "", "has_audio": False, "message_id": f"m{len(self.db.whatsapp_messages.rows)}",
                  "message_id_serialized": "", "timestamp": None, "mentioned_jids": [],
                  "quoted_message_id": "", "quoted_author": "", "quoted_body": "", "from_me": False}
        with patch.object(server, "db", self.db):
            return _run(server._store_group_message(parsed, GROUP, "proj_a", CO_A, "hello", now))

    def test_a_phone_sender_is_stamped_at_once(self):
        row = self.store("17185550100@c.us")
        self.assertEqual((row["sender_phone"], row["sender_phone_source"], row["sender_phone_at"]),
                         ("17185550100", "jid", NOW))

    def test_an_unknown_lid_waits_then_every_message_is_stamped_when_resolved(self):
        early = self.store(LID)
        self.assertIsNone(early["sender_phone"])
        w = _Waapi(lookup={LID: "17187559520"})
        later = NOW + timedelta(hours=2)
        with self.assertLogs(server.logger, "INFO") as logs:
            _with(_ctx(self.db, w), server._mention_targets(
                [{"kind": "sender_map", "id": "x", "name": "Mark", "jid": LID}], CO_A, later))
        stamped = self.db.whatsapp_messages.rows[0]
        self.assertEqual((stamped["sender_phone"], stamped["sender_phone_source"], stamped["sender_phone_at"]),
                         ("17187559520", "lid_lookup", later))
        rec = self.db[m.LOOKUP_COLLECTION].rows[0]
        self.assertEqual((rec["phone"], rec["resolved_at"]), ("17187559520", later))
        # Logged: the lid and "resolved" -- never the number.
        joined = "\n".join(logs.output)
        self.assertIn(f"[mention] get-lid {LID}: resolved", joined)
        self.assertNotRegex(joined, r"(?<!\d)1?718-?755-?9520(?!\d)")
        # A new message from them is stamped at once, from the record.
        nxt = self.store(LID, NOW + timedelta(hours=3))
        self.assertEqual((nxt["sender_phone"], nxt["sender_phone_source"]), ("17187559520", "lid_lookup"))

    def test_a_number_a_message_carries_is_never_overwritten(self):
        self.store(LID)
        self.db.whatsapp_messages.rows[0].update(m.stamp("17180000000", "people", NOW))
        with patch.object(server, "db", self.db):
            _run(server._stamp_sender_phone(CO_A, LID, "17187559520", "lid_lookup", NOW))
        self.assertEqual(self.db.whatsapp_messages.rows[0]["sender_phone"], "17180000000")


class EvidenceSourceSheet(unittest.TestCase):

    def _db(self):
        from bson import ObjectId
        oid = ObjectId()
        db = FakeDb(whatsapp_messages=[{
            "_id": oid, "project_id": "proj_a", "company_id": CO_A, "group_id": GROUP,
            "body": "rebar Thursday", "sender_jid": LID, "sender_name": "7187559520",
            "timestamp": datetime(2026, 10, 10, 15, 11, 11, tzinfo=timezone.utc),
            **m.stamp("17187559520", "lid_lookup", NOW)}],
            whatsapp_sender_map=[{"_id": "s1", "company_id": CO_A, "sender_jid": LID,
                                  "person_name": "Mark Rivera"}])
        return db, str(oid)

    def _get(self, user):
        db, rid = self._db()

        async def scope(pid, u):
            return CO_A
        with patch.object(server, "db", db), patch.object(server, "_memory_project", scope):
            return _run(server.get_whatsapp_source_message("proj_a", rid, current_user=user))

    def test_admin_sees_the_full_number_and_the_evidence_line(self):
        from tests.test_whatsapp_attention import ADMIN
        out = self._get(ADMIN)
        self.assertEqual(out["who"], "Mark Rivera")
        self.assertEqual(out["phone"], "+1 718-755-9520")
        self.assertEqual(out["evidence"], "Mark Rivera · +1 718-755-9520 · Oct 10, 11:11:11 AM")
        self.assertEqual(out["phone_resolved_at"], NOW.isoformat())

    def test_a_pm_sees_the_last_4(self):
        from tests.test_whatsapp_attention import PM
        out = self._get(PM)
        self.assertEqual(out["phone"], "…9520")
        self.assertEqual(out["evidence"], "Mark Rivera · …9520 · Oct 10, 11:11:11 AM")
        self.assertNotIn("7559520", str(out))

    def test_a_display_name_that_is_a_number_is_never_shown(self):
        from tests.test_whatsapp_attention import PM
        db, rid = self._db()
        db.whatsapp_sender_map.rows.clear()

        async def scope(pid, u):
            return CO_A
        with patch.object(server, "db", db), patch.object(server, "_memory_project", scope):
            out = _run(server.get_whatsapp_source_message("proj_a", rid, current_user=PM))
        self.assertEqual(out["who"], "")
        self.assertNotIn("7187559520", str(out))


class EvidenceInAnswers(unittest.TestCase):

    def test_three_renderings_and_the_model_never_sees_a_number(self):
        from lib import project_memory as pm
        src = {"sid": "S1", "source": pm.SOURCE_WHATSAPP, "who": "Mark Rivera", "group": "MEP",
               "when": "Oct 10, 11:11 AM", "phone": "17187559520", "text": "rebar Thursday"}
        claims = [{"sid": "S1", "text": "Rebar Thursday.", "quote": "rebar Thursday"}]
        self.assertNotIn("9520", pm.source_block([src]))
        none = pm.format_answer(claims, {"S1": src})
        last4 = pm.format_answer(claims, {"S1": src}, phones={"S1": m.shown("17187559520", False)})
        full = pm.format_answer(claims, {"S1": src}, phones={"S1": m.shown("17187559520", True)})
        self.assertIn("Mark Rivera · MEP", none)
        self.assertNotIn("9520", none)
        self.assertIn("Mark Rivera · …9520 · MEP", last4)
        self.assertIn("Mark Rivera · +1 718-755-9520 · MEP", full)

    def test_the_dm_gets_the_rendering_for_the_readers_role(self):
        texts = {"none": "N", "last4": "L", "full": "F"}

        async def agent(**k):
            server._MEMORY_DM_ANSWERS[server._memory_dm_key(k["group_id"], k["reply_to"])] = dict(texts)
            k["tool_trace"].append({"tool": "search_project_history", "result": "x"})
            return "agent words"
        for role, want in (("admin", "F"), ("pm", "L"), ("cp", "L")):
            ident = {"user": {"_id": "u", "role": role}, "role": role, "company_id": CO_A}
            with patch.object(server, "_run_group_agent", agent):
                got = _run(server._dm_answer_job(ident, {"_id": "proj_a"}, "17185550100@c.us",
                                                 "what about rebar?", "mid1"))
            self.assertEqual(got, want, role)


class EvidenceLifecycle(unittest.TestCase):

    def _db(self):
        return FakeDb(
            whatsapp_messages=[{"_id": "w1", "company_id": CO_A, "sender_jid": "1@lid"}],
            whatsapp_lid_phone=[{"_id": f"{CO_A}|1@lid", "company_id": CO_A, "lid": "1@lid",
                                 "phone": "17185550001"},
                                {"_id": f"{CO_A}|2@lid", "company_id": CO_A, "lid": "2@lid",
                                 "phone": "17185550002"}],
            whatsapp_sender_map=[{"_id": "s2", "company_id": CO_A, "sender_jid": "2@lid",
                                  "person_name": "Gone", "resolved_phone": "17185550002",
                                  "resolved_phone_at": NOW}])

    def test_a_number_goes_when_the_senders_last_message_goes(self):
        db = self._db()
        with patch.object(server, "db", db):
            dry = _run(server._sender_phone_gc(False))
            self.assertEqual(dry, {"orphaned": 2, "removed": 0})
            self.assertEqual(len(db.whatsapp_lid_phone.rows), 2)        # counted only
            done = _run(server._sender_phone_gc(True))
        self.assertEqual(done["removed"], 2)
        # 1@lid still has a message (e.g. under legal hold): kept.
        self.assertEqual([r["lid"] for r in db.whatsapp_lid_phone.rows], ["1@lid"])
        # The mapping stays (a person's name); only the looked-up number goes.
        sm = db.whatsapp_sender_map.rows[0]
        self.assertEqual((sm["person_name"], sm["resolved_phone"]), ("Gone", None))

    def test_retention_runs_it_and_delete_paths_remove_it(self):
        import inspect
        src = inspect.getsource(server._retention_tick)
        self.assertIn("_sender_phone_gc(purge", src)
        self.assertIn("_sender_phone_gc(True", inspect.getsource(server.hard_delete_project))
        comp = inspect.getsource(server.hard_delete_company)
        self.assertIn("wa_sender_map.COLLECTION].delete_many", comp)
        self.assertIn("wa_mention.LOOKUP_COLLECTION].delete_many", comp)


def _admin():
    from tests.test_whatsapp_attention import ADMIN
    return ADMIN


if __name__ == "__main__":
    unittest.main()
