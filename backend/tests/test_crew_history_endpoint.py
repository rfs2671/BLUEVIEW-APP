"""The activity-chips endpoint ranks a trade's chips off that trade's own days."""

import unittest

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


def _db_with(logs):
    db = _mk_db(prior=logs[0] if logs else None)
    db.logbooks.find = lambda q=None, *a, **k: _Cursor(logs)
    return db


PLUMB = {"trade": "Plumber", "activity_ids": ["mep_rough_in"]}
ELEC = {"trade": "Electrician", "activity_ids": ["elec_pull_wire"]}


class TheEndpointUsesTheCrewsOwnDays(unittest.TestCase):

    def test_a_trade_with_history_is_ranked_by_it_and_says_why(self):
        logs = [_log("2026-10-14", PLUMB, ELEC), _log("2026-10-13", PLUMB), _log("2026-10-12", PLUMB, ELEC)]
        body = _get(_db_with(logs), date="2026-10-15", trade="Plumber").json()
        self.assertTrue(body["personalized"])
        self.assertEqual(body["history_days"], 3)
        self.assertEqual(body["chips"][0]["id"], "mep_rough_in")
        self.assertIn("continuing", body["chips"][0]["reason"])

    def test_another_trades_days_are_not_this_trades(self):
        logs = [_log("2026-10-14", ELEC)]
        body = _get(_db_with(logs), date="2026-10-15", trade="Plumber").json()
        self.assertFalse(body["personalized"])
        self.assertEqual(body["history_days"], 0)
        self.assertTrue(all(c["reason"] is None for c in body["chips"]))

    def test_no_trade_is_the_project_ranking_as_before(self):
        body = _get(_db_with([_log("2026-10-14", PLUMB)]), date="2026-10-15").json()
        self.assertFalse(body["personalized"])

    def test_the_four_guarantees_hold_with_history(self):
        logs = [_log("2026-10-14", PLUMB), _log("2026-10-13", PLUMB)]
        body = _get(_db_with(logs), date="2026-10-15", trade="Plumber").json()
        self.assertEqual(body["chips"][-1]["id"], "other")
        self.assertEqual([c["id"] for c in body["chips"]].count("other"), 1)
        self.assertTrue(all(c["selected"] is False for c in body["chips"]))
        plain = _get(_mk_db(), date="2026-10-15", trade="Plumber").json()
        self.assertEqual(sorted(c["id"] for c in body["chips"]), sorted(c["id"] for c in plain["chips"]))

    def test_a_history_read_that_fails_leaves_the_ranking_alone(self):
        db = _mk_db(prior=_log("2026-10-14", PLUMB))

        def boom(*a, **k):
            raise RuntimeError("mongo down")
        db.logbooks.find = boom
        resp = _get(db, date="2026-10-15", trade="Plumber")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["personalized"])


if __name__ == "__main__":
    unittest.main()
