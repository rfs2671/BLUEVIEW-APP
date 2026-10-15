"""The progress report, on the 588 fixture (tests/report_588.py).

  * Every number is the records' (counted here again, independently).
  * The schedule is the days each sub was on site, labelled with the work in
    its daily logs; the work by sub is the logs' words.
  * Photos: only ones vision passed; each sub's earliest and latest.
  * The summary from the model goes out only when every number and name in
    it is in the facts; else the records' own summary.
  * The WhatsApp message is the short one; the PDF is attached, the link
    only as a fallback.
  * Never "man-days", never a percentage, never a phone number.
  * The whole report as text is snapshotted (fixtures/report_588.snap.txt;
    REPORT_SNAPSHOT_UPDATE=1 rewrites it).
"""

from __future__ import annotations

import os
import re
import unittest
from collections import defaultdict
from datetime import date, timedelta

os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

from lib import progress_report as P  # noqa: E402
from tests import report_588 as F  # noqa: E402

SNAP = os.path.join(os.path.dirname(__file__), "fixtures", "report_588.snap.txt")
NO_GOOD = re.compile(r"man[- ]?days?|\d\s?%|percent|vs\.? (?:the )?(?:period|prior)", re.IGNORECASE)


def rep():
    return F.report()


class TheNumbersAreTheRecords(unittest.TestCase):

    def test_site_counted_again(self):
        per = defaultdict(lambda: defaultdict(set))
        for c in F.checkins():
            per[c["check_in_time"].astimezone(F.NY).date()][c["worker_company"]].add(c["worker_id"])
        totals = {d: sum(len(v) for v in by.values()) for d, by in per.items()}
        site = rep()["site"]
        self.assertEqual(site["worked"], len(totals))
        self.assertEqual(site["possible"], len(F.WORKDAYS))
        self.assertEqual(site["avg"], round(sum(totals.values()) / len(totals)))
        self.assertEqual((site["max"], site["max_day"]), (37, date(2026, 10, 15)))
        self.assertEqual([r["total"] for r in site["table"]], [totals[d] for d in sorted(totals)])

    def test_each_sub(self):
        subs = {s["name"]: s for s in rep()["subs"]}
        self.assertEqual(list(subs), ["Arkon Builders", "Quality Plumbing", "Power Direct", "J&G Scaffolding"])
        for name, days in F.CREWS.items():
            s = subs[name]
            self.assertEqual(s["days"], sorted(days))
            self.assertEqual(s["max"], max(days.values()))
            self.assertEqual(s["avg"], round(sum(days.values()) / len(days), 1))

    def test_a_weekend_does_not_break_a_bar_a_gap_does(self):
        runs = {s["name"]: [(r["start"], r["end"]) for r in s["runs"]] for s in rep()["subs"]}
        self.assertEqual(runs["Arkon Builders"], [(date(2026, 10, 2), date(2026, 10, 15))])
        self.assertEqual(runs["J&G Scaffolding"], [(date(2026, 10, 2), date(2026, 10, 6)),
                                                   (date(2026, 10, 15), date(2026, 10, 15))])

    def test_the_work_is_the_logs_words(self):
        subs = {s["name"]: s for s in rep()["subs"]}
        self.assertEqual(subs["Arkon Builders"]["label"], "Framing fl 1–4")
        self.assertEqual(subs["Arkon Builders"]["work"],
                         ["Framing — fl 1–2 (Oct 2–9)", "Framing — fl 3–4 (Oct 12–15)"])
        self.assertEqual(subs["J&G Scaffolding"]["work"],
                         ["Scaffolding — Front facade (Oct 2–6)", "Scaffolding — Rear facade (Oct 15)"])
        self.assertIn("Oct 9: Power Direct short 2 workers today; rough-in on the 2nd floor behind.",
                      subs["Power Direct"]["issues"])

    def test_open_items(self):
        r = rep()
        self.assertEqual([(c["who"], c["due"]) for c in r["late"]],
                         [("J&G Scaffolding", date(2026, 10, 8)), ("Power Direct", date(2026, 10, 9)),
                          ("Quality Plumbing", date(2026, 10, 12)), ("Arkon Builders", date(2026, 10, 13))])
        self.assertEqual(r["punch"]["open"], len(F.punch_items()))            # the real 588 walk
        self.assertEqual([e["date"] for e in r["coming_up"]],
                         [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 23)])
        self.assertEqual([(x["kind"], x["number"]) for x in r["records"]], [("DOT permit", "X01-2026278-A11")])

    def test_the_chat_is_people_only(self):
        talk = rep()["chat"]
        self.assertEqual({c["who"] for c in talk}, {"Site super", "PM"})
        self.assertFalse(any("bot line" in c["text"] or c["text"] == "ok" for c in talk))


class CodexOn803(unittest.TestCase):

    def test_two_subs_that_differ_by_trade_stay_two(self):
        d = F.WORKDAYS[0]
        ck = [{"worker_id": f"{c}{i}", "worker_company": co, "check_in_time": F._at(d)}
              for c, co in (("p", "ABC Plumbing"), ("e", "ABC Electrical")) for i in range(3)]
        r = P.compute(job=F.JOB, address="", gc="G", start=F.START, end=F.END, now=F.NOW, checkins=ck)
        self.assertEqual(sorted(s["name"] for s in r["subs"]), ["ABC Electrical", "ABC Plumbing"])
        self.assertEqual([s["max"] for s in r["subs"]], [3, 3])

    def test_a_short_name_is_the_one_sub_it_can_be(self):
        d = F.WORKDAYS[0]
        ck = [{"worker_id": f"j{i}", "worker_company": "J&G", "check_in_time": F._at(d)} for i in range(2)]
        logs = [{"_id": "l1", "date": d.isoformat(), "data": {"activities": [
            {"company": "J&G Scaffolding", "num_workers": 2, "work_description": "Scaffolding",
             "work_locations": "Front facade"}]}}]
        r = P.compute(job=F.JOB, address="", gc="G", start=F.START, end=F.END, now=F.NOW,
                      checkins=ck, logbooks=logs)
        self.assertEqual(len(r["subs"]), 1)
        self.assertEqual(r["subs"][0]["label"], "Scaffolding")

    def test_a_commitment_made_after_the_period_is_not_late_in_it(self):
        later = F.commitments()[0]
        later["created_at"] = F._at(date(2026, 10, 20))
        r = P.compute(job=F.JOB, address="", gc="G", start=F.START, end=F.END, now=F.NOW,
                      commitments=[later])
        self.assertEqual(r["late"], [])

    def test_a_photo_with_only_its_inline_copy_is_a_candidate(self):
        d = F.WORKDAYS[0]
        logs = [{"_id": "l1", "date": d.isoformat(), "data": {"activities": [
            {"company": "Arkon Builders", "num_workers": 2, "work_description": "Framing",
             "photos": [{"base64": "data:image/jpeg;base64,AAAA"}, {"thumb_base64": "AAAA"}, {}]}]}}]
        r = P.compute(job=F.JOB, address="", gc="G", start=F.START, end=F.END, now=F.NOW, logbooks=logs)
        self.assertEqual([c["key"] for c in r["photo_candidates"]], ["inline:l1:0:0", "inline:l1:0:1"])
        self.assertEqual(r["photo_candidates"][0]["photo"], {"base64": "data:image/jpeg;base64,AAAA"})


class Photos(unittest.TestCase):

    def test_only_passed_photos_earliest_and_latest(self):
        photos = rep()["photos"]
        verdicts = F.verdicts()
        self.assertTrue(all(verdicts[p["key"]]["ok"] for p in photos))
        self.assertLessEqual(len(photos), P.MAX_PHOTOS)
        pairs = {(p["sub"], p.get("pair")): p["date"] for p in photos if p.get("pair")}
        self.assertEqual(pairs[("Arkon Builders", "before")], date(2026, 10, 2))
        self.assertEqual(pairs[("Arkon Builders", "after")], date(2026, 10, 15))
        self.assertEqual(pairs[("Quality Plumbing", "after")], date(2026, 10, 14))

    def test_daily_log_photos_only(self):
        r = rep()
        # The real 588 walk's 47 punch photos are in the rows: none is a candidate.
        self.assertTrue(any(i.get("photo_key") for i in F.punch_items()))
        self.assertEqual({c["source"] for c in r["photo_candidates"]}, {"daily log"})
        self.assertTrue(all(p["key"].startswith("logbooks/") for p in r["photos"]))

    def test_the_caption_is_the_subs_work_line(self):
        by = {(p["sub"], p["date"]): p["caption"] for p in rep()["photos"]}
        self.assertEqual(by[("Arkon Builders", date(2026, 10, 2))], "Framing — fl 1–2")
        self.assertEqual(by[("J&G Scaffolding", date(2026, 10, 15))], "Scaffolding — Rear facade")
        # Never the model's words.
        self.assertNotIn("Metal stud framing started on the 1st floor", by.values())

    def test_fewer_than_ten_usable_shows_what_there_is(self):
        usable = sum(1 for v in F.PHOTOS.values() if v["ok"])
        self.assertEqual(len(rep()["photos"]), usable)          # 9: never padded

    def test_fifteen_at_most_every_sub_shown(self):
        d0 = date(2026, 10, 1)
        cands = [{"key": f"a{i}", "date": d0 + timedelta(days=i % 14), "sub": "Arkon", "where": f"fl {i}",
                  "words": "Framing", "source": "daily log"} for i in range(30)]
        cands += [{"key": f"b{i}", "date": d0 + timedelta(days=i), "sub": "Power Direct", "where": f"fl {i}",
                   "words": "Rough-in", "source": "daily log"} for i in range(5)]
        verdicts = {c["key"]: {"ok": True, "kind": "progress", "score": 9 if c["sub"] == "Arkon" else 5}
                    for c in cands}
        picked = P.pick_photos(cands, verdicts)
        self.assertEqual(len(picked), 15)
        self.assertGreaterEqual(sum(1 for p in picked if p["sub"] == "Power Direct"), 5)
        self.assertEqual({p.get("pair") for p in picked if p["sub"] == "Arkon"} - {None}, {"before", "after"})

    def test_the_latest_is_the_best_of_its_day(self):
        # Codex on #806: two photos at one place on the last day -- the better one.
        d1, d2 = date(2026, 10, 1), date(2026, 10, 9)
        cands = [{"key": k, "date": d, "sub": "Arkon", "where": "fl 2", "words": "Framing",
                  "source": "daily log"} for k, d in (("a", d1), ("weak", d2), ("strong", d2))]
        v = {"a": 5, "weak": 2, "strong": 9}
        picked = P.pick_photos(cands, {k: {"ok": True, "kind": "progress", "score": n} for k, n in v.items()})
        self.assertEqual([(p["key"], p.get("pair")) for p in picked], [("a", "before"), ("strong", "after")])

    def test_every_sub_before_any_pair(self):
        # Codex on #806: nine subs with photos on two days each -- all nine shown.
        d1, d2 = date(2026, 10, 1), date(2026, 10, 9)
        cands = [{"key": f"{s}{i}", "date": d, "sub": f"Sub {s}", "where": "", "words": "Work",
                  "source": "daily log"} for s in "ABCDEFGHI" for i, d in enumerate((d1, d2))]
        picked = P.pick_photos(cands, {c["key"]: {"ok": True, "kind": "progress", "score": 5} for c in cands})
        self.assertEqual(len(picked), 15)
        self.assertEqual({p["sub"] for p in picked}, {f"Sub {s}" for s in "ABCDEFGHI"})

    def test_never_people_blurry_or_a_document(self):
        keys = {p["key"] for p in rep()["photos"]}
        for (sub, d), v in F.PHOTOS.items():
            if not v["ok"]:
                self.assertNotIn(F.photo_key(sub, d), keys, (sub, d))

    def test_the_verdict_is_read_strictly(self):
        self.assertEqual(P.parse_verdict('```json\n{"ok": true, "kind": "progress", "score": 12, '
                                         '"caption": "Framing, call 718-555-0100"}\n```'),
                         {"ok": True, "kind": "progress", "score": 10.0, "caption": "Framing, call [number]"})
        self.assertFalse(P.parse_verdict('{"ok": true, "kind": "people", "score": 9}')["ok"])
        self.assertIsNone(P.parse_verdict("a nice photo"))

    def test_a_cap_on_what_vision_sees(self):
        cands = [{"key": f"k{i}", "date": date(2026, 10, 2 + i % 10), "sub": f"S{i % 3}",
                  "where": "", "words": "", "source": "daily log"} for i in range(200)]
        self.assertEqual(len(P.to_judge(cands, 40)), 40)


class TheSummary(unittest.TestCase):

    def test_the_records_summary(self):
        s = rep()["summary"]
        n = len(re.findall(r"(?<=[.!?])\s", s)) + 1
        self.assertTrue(5 <= n <= 8, (n, s))
        self.assertIsNone(NO_GOOD.search(s))

    def test_a_model_summary_from_the_facts_passes(self):
        good = ("Framing by Arkon Builders moved from floors 1–2 to floors 3–4 this period, while "
                "Quality Plumbing installed risers on floors 1–3. Power Direct started electrical "
                "rough-in on floors 1–2 on Oct 8. The site was worked 10 of 10 working days with an "
                "average of 25 workers on site, and the busiest day was Thu Oct 15 with 37. The "
                "daily log notes the concrete delivery for stair 2 was pushed to next week. Four "
                "commitments are past due and 47 punch items are open. Next up is the plumbing "
                "inspection of the risers on Tue Oct 20.")
        self.assertTrue(P.check_summary(good, rep()))

    def test_an_invented_number_or_name_fails(self):
        base = ("Framing by Arkon Builders continued on floors 1–4. The site was worked 10 of 10 "
                "working days. Quality Plumbing installed risers on floors 1–3. Power Direct started "
                "rough-in. Next up is the plumbing inspection on Tue Oct 20.")
        self.assertTrue(P.check_summary(base, rep()))
        for bad in (base.replace("10 of 10", "11 of 12"),                     # a number not in the facts
                    base.replace("Power Direct", "Con Edison"),                # a name not in the facts
                    base + " That is 231 man-days.",
                    base.replace("Framing by", "Framing, up 151% vs the period before, by"),
                    "Framing continued."):                                     # too short
            self.assertFalse(P.check_summary(bad, rep()), bad)


class WhatsApp(unittest.TestCase):

    def test_the_message(self):
        self.assertEqual(P.whatsapp_message(rep()), "\n".join([
            "588 Thomas S Boyland · Oct 2–15",
            "- Work this period: framing fl 1–4 (Arkon), riser install fl 1–3 (Quality Plumbing), "
            "electrical rough-in fl 1–2 (Power Direct), scaffolding (J&G)",
            "- Site: worked 10 of 10 days · avg 25 workers/day · busiest Thu Oct 15 (37)",
            "- Open: 4 late commitments · 47 punch items",
            "Full report (PDF) attached."]))

    def test_the_link_only_as_a_fallback(self):
        r = rep()
        self.assertNotIn("http", P.whatsapp_message(r))
        self.assertTrue(P.whatsapp_message(r, attached=False, link="https://x/r.pdf")
                        .endswith("Full report (PDF): https://x/r.pdf"))

    def test_a_new_violation_is_open_a_permit_is_not(self):
        r = rep()
        r["records"] = r["records"] + [{"kind": "DOB violation", "number": "35123456", "status": "ACTIVE",
                                        "date": date(2026, 10, 9), "open": True}]
        self.assertIn("· 1 new DOB/DOT violation", P.whatsapp_message(r))


class ThePdf(unittest.TestCase):

    def html(self, r=None):
        r = r or rep()
        return P.render_html([r], gc=F.GC, title=P.title_for([r]), now=F.NOW,
                             images={p["key"]: "data:image/jpeg;base64,AA==" for p in r["photos"]})

    def test_sections_and_branding(self):
        h = self.html()
        for want in ("LEVELOG", "Blueview Construction", "Construction progress report",
                     "Prepared October 15, 2026", "counter(page)", "counter(pages)",
                     ">Summary<", ">Actual work (from daily logs)<", ">Work by sub<",
                     ">Progress photos<", ">Site activity<", ">DOB / DOT<", ">Open items<",
                     ">Coming up (next 2 weeks)<", ">Today<", "<svg", "workers on site",
                     "days on site"):
            self.assertIn(want, h, want)
        self.assertIsNone(NO_GOOD.search(re.sub(r"<style>.*?</style>|<[^>]+>|width=\"[^\"]*\"", " ", h,
                                                flags=re.DOTALL)))

    def test_empty_sections_say_none(self):
        r = P.compute(job="9 Menahan St", address="", gc="G", start=F.START, end=F.END, now=F.NOW)
        r["summary"] = P.summary_fallback(r)
        h = self.html(r)
        self.assertIn("None — no new DOB or DOT records this period.", h)
        self.assertIn("No progress photos in the daily logs", h)
        self.assertIn("No crews on site in this period.", h)

    def test_no_phone(self):
        r = rep()
        r["observations"].append({"date": date(2026, 10, 9), "text": "Call Dave 718-555-0100"})
        self.assertIsNone(re.search(r"555-0100", P.text_outline(r) + self.html(r)))

    def test_it_renders(self):
        import weasyprint
        doc = weasyprint.HTML(string=self.html()).render()
        self.assertGreaterEqual(len(doc.pages), 5)
        self.assertTrue(doc.write_pdf().startswith(b"%PDF"))


class Snapshot(unittest.TestCase):

    def test_the_report_as_text(self):
        r = rep()
        text = (P.whatsapp_message(r) + "\n\n" + "=" * 72 + "\n\n" + P.text_outline(r) + "\n")
        self.assertIsNone(NO_GOOD.search(text))
        if os.environ.get("REPORT_SNAPSHOT_UPDATE") or not os.path.exists(SNAP):
            with open(SNAP, "w", encoding="utf-8") as f:
                f.write(text)
        with open(SNAP, encoding="utf-8") as f:
            self.assertEqual(text, f.read())


if __name__ == "__main__":
    unittest.main()
