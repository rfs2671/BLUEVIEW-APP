"""The activity-chips endpoint ranks a trade's chips from where THAT trade left off,
and from a confirmed schedule -- and changes nothing else."""

import unittest

import server
from tests.test_activity_chips_endpoint import _get, _mk_db


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        return self

    async def to_list(self, n):
        return list(self.rows)


def _log(day, *rows):
    return {"date": day, "log_type": "daily_jobsite", "data": {"activities": list(rows)}}


def _db_with(logs, schedule=None):
    db = _mk_db(prior=logs[0] if logs else None)
    db.logbooks.find = lambda q=None, *a, **k: _Cursor(logs)
    db[server.PROJECT_SCHEDULES].set_find_one(lambda q: schedule)
    return db


PLUMB_UNDER = {"trade": "Plumber", "activity_ids": ["under_slab_mep"]}
ELEC = {"trade": "Electrician", "activity_ids": ["elec_pull_wire"]}


class TheEndpointRanksFromWhereATradeLeftOff(unittest.TestCase):

    def test_plumbers_back_after_a_week_get_rough_in_not_the_projects_latest_day(self):
        # last week: under-slab MEP. Since then only electricians have been logged.
        logs = [_log("2026-10-14", ELEC), _log("2026-10-13", ELEC), _log("2026-10-07", PLUMB_UNDER)]
        body = _get(_db_with(logs), date="2026-10-15", trade="Plumber").json()
        self.assertTrue(body["personalized"])
        ids = [c["id"] for c in body["chips"][:5]]
        self.assertIn("mep_rough_in", ids)
        top = next(c for c in body["chips"] if c["id"] == "mep_rough_in")
        self.assertIn("next stage after under-slab MEP", top["reason"])

    def test_another_trades_days_are_not_this_trades(self):
        body = _get(_db_with([_log("2026-10-14", ELEC)]), date="2026-10-15", trade="Plumber").json()
        self.assertFalse(body["personalized"])
        self.assertEqual(body["history_days"], 0)
        self.assertTrue(all(c["reason"] is None for c in body["chips"]))

    def test_no_trade_is_the_project_ranking_as_before(self):
        self.assertFalse(_get(_db_with([_log("2026-10-14", PLUMB_UNDER)]), date="2026-10-15").json()["personalized"])

    def test_a_confirmed_schedule_lifts_what_it_planned_for_the_day(self):
        plan = {"doc": {"activities": [{"name": "Riser install floors 1-4", "current_start": "2026-10-14",
                                        "current_finish": "2026-10-20"}]}}
        body = _get(_db_with([], schedule=plan), date="2026-10-15", trade="Plumber").json()
        self.assertTrue(body["personalized"])
        self.assertEqual(body["chips"][0]["id"], "plmb_riser_install")
        self.assertTrue(body["chips"][0]["reason"].startswith("scheduled: Riser install floors 1-4"))

    def test_the_four_guarantees_hold(self):
        logs = [_log("2026-10-07", PLUMB_UNDER)]
        body = _get(_db_with(logs), date="2026-10-15", trade="Plumber").json()
        plain = _get(_mk_db(), date="2026-10-15", trade="Plumber").json()
        self.assertEqual(body["chips"][-1]["id"], "other")
        self.assertEqual([c["id"] for c in body["chips"]].count("other"), 1)
        self.assertTrue(all(c["selected"] is False for c in body["chips"]))
        self.assertEqual(sorted(c["id"] for c in body["chips"]), sorted(c["id"] for c in plain["chips"]))

    def test_a_failed_read_leaves_the_ranking_alone(self):
        db = _mk_db(prior=_log("2026-10-14", PLUMB_UNDER))

        def boom(*a, **k):
            raise RuntimeError("mongo down")
        db.logbooks.find = boom
        resp = _get(db, date="2026-10-15", trade="Plumber")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["personalized"])


if __name__ == "__main__":
    unittest.main()
