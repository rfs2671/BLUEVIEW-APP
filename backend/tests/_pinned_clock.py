"""Pin server.py's clock for a test: `now()` / `utcnow()` return a fixed moment.

WHY. Seven tests asked the bot to post with the REAL clock -- the GC confirm
flow (_handle_gc_confirm_reply reads datetime.now) and the live punch dry run.
Inside the Shabbos / Yom Tov quiet window the bot holds every message, so
those tests failed every Friday evening through Saturday night, on main, for
reasons unrelated to any change (seen 2026-10-23 17:02 New York). CI runs on
whatever the clock says, so a PR pushed then went red.

server.py does `from datetime import datetime`, so replacing `server.datetime`
with a subclass whose `now()` is fixed pins every clock read in server.py;
lib/shabbos is handed that `now`. Nothing else about datetime changes.

    from tests._pinned_clock import pin_server_clock, WEEKDAY
    def setUp(self):
        pin_server_clock(self)          # WEEKDAY unless `at=` says otherwise
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

#: Wednesday 2026-10-07 11:00 New York: a working day, inside the default send
#: window, clear of Shabbos and of the fall holidays (Simchat Torah was Oct 4).
WEEKDAY = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)


class _IsADatetime(type):
    """isinstance(x, <pinned class>) answers for ANY datetime: server.py's own
    `isinstance(v, datetime)` checks must keep seeing the fixtures' real
    datetimes (without this, a sort by created_at broke)."""

    def __instancecheck__(cls, obj):
        return isinstance(obj, datetime)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, datetime)


def fixed_datetime(at: datetime):
    """A datetime subclass whose now() / utcnow() return `at`."""
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)

    class _Pinned(datetime, metaclass=_IsADatetime):
        @classmethod
        def now(cls, tz=None):
            return at.astimezone(tz) if tz else at.astimezone(timezone.utc).replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return at.astimezone(timezone.utc).replace(tzinfo=None)
    return _Pinned


def pin_server_clock(test, at: datetime = WEEKDAY):
    """Pin server.datetime for the rest of `test` (undone by addCleanup)."""
    import server
    p = patch.object(server, "datetime", fixed_datetime(at))
    p.start()
    test.addCleanup(p.stop)
    return at
