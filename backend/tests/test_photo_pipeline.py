"""Photographs are judged ONCE, soon after their daily log is filed, and the
verdict is stored; a report reads what is already known instead of judging a
fortnight of photographs while someone waits (real 588: 209 photos in 11 days)."""

import asyncio
import copy
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

import server
from lib import progress_report as P

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def _match(doc, flt):
    for k, want in (flt or {}).items():
        have = doc.get(k)
        if isinstance(want, dict):
            for op, arg in want.items():
                if op == "$in" and have not in arg:
                    return False
                if op == "$ne" and have == arg:
                    return False
                if op == "$gte" and not (have is not None and have >= arg):
                    return False
                if op not in ("$in", "$ne", "$gte", "$nin"):
                    raise AssertionError(f"fake does not know {op}")
        elif have != want:
            return False
    return True


class _Cur:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, n=None):
        return copy.deepcopy(self.docs)


class _Coll:
    def __init__(self):
        self.docs = []

    def find(self, flt=None, projection=None, **kw):
        return _Cur([d for d in self.docs if _match(d, flt)])

    async def update_one(self, flt, update, upsert=False, **kw):
        for d in self.docs:
            if _match(d, flt):
                d.update(update.get("$set") or {})
                for k, v in (update.get("$inc") or {}).items():
                    d[k] = d.get(k, 0) + v
                return
        if upsert:
            doc = dict(flt)
            doc.update(update.get("$set") or {})
            for k, v in (update.get("$inc") or {}).items():
                doc[k] = doc.get(k, 0) + v
            self.docs.append(doc)


class _Db:
    def __init__(self):
        self.c = {}

    def __getattr__(self, name):
        return self[name]

    def __getitem__(self, name):
        return self.c.setdefault(name, _Coll())


def photo(i):
    return {"original_r2_key": f"r2/{i}.jpg"}


def log(lid, day, photos, status="submitted", project="p1", company="c1", **kw):
    return {"_id": lid, "log_type": "daily_jobsite", "date": day, "status": status, "project_id": project,
            "company_id": company, "is_deleted": False,
            "data": {"activities": [{"company": "Arkon Builders", "photos": photos}]}, **kw}


GOOD = {"ok": True, "kind": "progress", "score": 8, "work": "framing", "caption": "Studs"}


class Pipeline(unittest.TestCase):

    def setUp(self):
        self.db = _Db()
        self.calls = []

        async def verdict(raw, project_id, endpoint):
            self.calls.append(raw)
            return None if raw == b"bad" else dict(GOOD)

        async def no_filter(base=None):
            return dict(base or {})
        self.bytes = {}
        patches = [mock.patch.object(server, "db", self.db), mock.patch.object(server, "QWEN_API_KEY", "k"),
                   mock.patch.object(server, "_photo_verdict", verdict),
                   mock.patch.object(server, "unattended_project_filter", no_filter),
                   mock.patch.object(server, "_report_photo_bytes",
                                     lambda c: self.bytes.get(c["key"], b"img"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tick(self, **kw):
        return asyncio.run(server._photo_pipeline_tick(NOW, **kw))

    def stored(self):
        return {d["_id"]: d for d in self.db[server.REPORT_PHOTO_VERDICTS].docs if "ok" in d}

    def test_every_photo_of_a_filed_log_is_judged_and_stored_with_where_it_came_from(self):
        self.db.logbooks.docs.append(log("L1", "2026-10-20", [photo(1), photo(2), photo(3)]))
        got = self.tick()
        self.assertEqual((got["logs"], got["photos"], got["judged"]), (1, 3, 3))
        doc = self.stored()["report-v3:r2/1.jpg"]
        self.assertEqual((doc["project_id"], doc["company_id"], doc["log_id"], doc["date"]), ("p1", "c1", "L1", "2026-10-20"))
        self.assertEqual((doc["ok"], doc["work"], doc["score"]), (True, "framing", 8))

    def test_a_photo_is_judged_once_never_twice(self):
        self.db.logbooks.docs.append(log("L1", "2026-10-20", [photo(1), photo(2)]))
        self.tick()
        again = self.tick()
        self.assertEqual((again["judged"], again["already"]), (0, 2))
        self.assertEqual(len(self.calls), 2)

    def test_the_report_keys_a_photo_exactly_as_the_pipeline_does(self):
        lg = log("L1", "2026-10-20", [photo(1), {"base64": "AAAA"}])
        keys = [x["key"] for x in P.log_photos(lg)]
        self.assertEqual(keys, ["r2/1.jpg", "L1:0:1".join(["inline:", ""])])

    def test_drafts_withdrawn_amendments_and_old_logs_are_left_alone(self):
        self.db.logbooks.docs += [
            log("draft", "2026-10-20", [photo(1)], status="draft"),
            log("old", "2026-09-01", [photo(2)]),
            log("gone", "2026-10-20", [photo(3)], status=server.WITHDRAWN_STATUS),
            log("locked", "2026-10-20", [photo(4)], status="draft", is_locked=True)]
        got = self.tick()
        self.assertEqual(got["photos"], 1)
        self.assertEqual(set(self.stored()), {"report-v3:r2/4.jpg"})

    def test_a_photo_the_model_cannot_read_is_retried_then_given_up_on(self):
        self.db.logbooks.docs.append(log("L1", "2026-10-20", [photo(1)]))
        self.bytes["r2/1.jpg"] = b"bad"
        results = [self.tick() for _ in range(5)]
        self.assertEqual([r["failed"] for r in results], [1, 1, 1, 0, 0])
        self.assertEqual(results[-1]["given_up"], 1)
        self.assertEqual(self.stored(), {})                       # a failure is never stored as a verdict

    def test_the_budget_is_spent_on_the_newest_photos_first(self):
        self.db.logbooks.docs += [log("old", "2026-10-15", [photo(1), photo(2)]),
                                  log("new", "2026-10-20", [photo(3), photo(4)])]
        got = self.tick(budget=2)
        self.assertEqual(got["judged"], 2)
        self.assertEqual(set(self.stored()), {"report-v3:r2/3.jpg", "report-v3:r2/4.jpg"})
        self.assertEqual(self.tick(budget=2)["judged"], 2)        # the backlog drains on the next tick

    def test_no_vision_key_means_nothing_runs(self):
        self.db.logbooks.docs.append(log("L1", "2026-10-20", [photo(1)]))
        with mock.patch.object(server, "QWEN_API_KEY", ""):
            self.assertEqual(self.tick()["judged"], 0)
        self.assertEqual(self.calls, [])


class TheReportReadsWhatIsStored(unittest.TestCase):

    def test_stored_verdicts_are_used_and_vision_is_not_called_for_them(self):
        db = _Db()
        cands = []
        for i in range(6):
            cands.append({"key": f"r2/{i}.jpg", "date": date(2026, 10, 1) + timedelta(days=i), "sub": "Arkon Builders",
                          "trade": "Framers", "where": f"floor {i}", "words": "x", "work": "x",
                          "source": "daily log", "log_id": "L", "photo": {}})
            db[server.REPORT_PHOTO_VERDICTS].docs.append({"_id": f"report-v3:r2/{i}.jpg", **GOOD, "score": 6 + i % 3})
        rep = {"photo_candidates": cands}

        async def boom(c, project_id):
            raise AssertionError("vision was called for a photo that already has a verdict")
        with mock.patch.object(server, "db", db), mock.patch.object(server, "_report_judge_photo", boom):
            chosen = asyncio.run(server._report_photos(rep, "p1"))
        self.assertEqual(len(chosen), 5)                          # a full row, from stored verdicts alone
        self.assertEqual(rep["photos_unjudged"], 0)

    def test_only_photos_without_a_verdict_are_judged_now(self):
        db = _Db()
        cands = [{"key": f"r2/{i}.jpg", "date": date(2026, 10, 1) + timedelta(days=i), "sub": "Arkon Builders",
                  "trade": "Framers", "where": f"floor {i}", "words": "x", "work": "x", "source": "daily log",
                  "log_id": "L", "photo": {}} for i in range(4)]
        db[server.REPORT_PHOTO_VERDICTS].docs.append({"_id": "report-v3:r2/0.jpg", **GOOD})
        asked = []

        async def judge(c, project_id):
            asked.append(c["key"])
            return dict(GOOD)
        with mock.patch.object(server, "db", db), mock.patch.object(server, "_report_judge_photo", judge):
            asyncio.run(server._report_photos({"photo_candidates": cands}, "p1"))
        self.assertEqual(sorted(asked), ["r2/1.jpg", "r2/2.jpg", "r2/3.jpg"])
