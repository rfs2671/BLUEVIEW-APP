"""Which people have more than one account -- READ ONLY (memberships, ruling 4).

    railway run --service Blueview2 --environment production python backend/scripts/duplicate_accounts_census.py

Ruling 1 (2026-11-05) is one account per person. Before anything is merged the
operator rules on each case, and this lists the cases:

  * EMAIL: accounts whose emails are equal once case and surrounding spaces are
    ignored. The unique index on users.email is case-sensitive, so "Bob@x" and
    "bob@x" are two accounts today.
  * PHONE: accounts whose phones are equal once reduced to their last 10
    digits. There is no unique index on users.phone at all.

Each group says whether its accounts are in ONE company (an accidental second
account) or SEVERAL (the same person working for two companies -- the case
memberships exist for), and shows each account's company, role, status and
whether it is soft-deleted, so a ruling can be made from the printout alone.
Also printed: accounts per company and accounts with no company, by role.

READ ONLY, enforced here: every pymongo write method raises (installed before
the client exists), and the check runs before anything is read. Nothing is
written to the database or to disk; passwords are never read.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from probe_helpers import FieldNotInSample, counted, require_fields  # noqa: E402  (no app imports)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_WRITES = ("insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
           "delete_many", "bulk_write", "find_one_and_update", "find_one_and_replace",
           "find_one_and_delete", "create_index", "create_indexes", "drop", "rename", "drop_index")

#: What is read from each user. Never the password.
USER_FIELDS = ("email", "phone", "name", "company_id", "role", "account_status", "is_deleted",
               "created_at")


class ReadOnlyViolation(RuntimeError):
    pass


def lock_writes() -> int:
    """Every pymongo write method raises. Returns how many were replaced."""
    from pymongo.collection import Collection

    def refuse(name):
        def _r(self, *a, **k):
            raise ReadOnlyViolation(f"read-only census: {name} on {self.full_name} refused")
        _r.__readonly_refuser__ = True
        return _r
    n = 0
    for w in _WRITES:
        if hasattr(Collection, w):
            setattr(Collection, w, refuse(w))
            n += 1
    return n


def email_key(value) -> str:
    return str(value or "").strip().lower()


def phone_key(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else ""


def groups(users, key_fn, field):
    """{key: [user, ...]} for every key held by more than one account."""
    by = defaultdict(list)
    for u in users:
        k = key_fn(u.get(field))
        if k:
            by[k].append(u)
    return {k: v for k, v in by.items() if len(v) > 1}


def main() -> int:
    url = os.environ.get("CENSUS_MONGO_URL") or os.environ.get("MONGO_URL")
    name = os.environ.get("CENSUS_DB") or os.environ.get("DB_NAME")
    if not url or not name:
        sys.exit("No database: MONGO_URL/DB_NAME (railway run sets them) or CENSUS_MONGO_URL/"
                 "CENSUS_DB. Nothing was read.")
    n = lock_writes()
    from pymongo import MongoClient
    from pymongo.collection import Collection
    unlocked = [w for w in _WRITES if hasattr(Collection, w)
                and not getattr(getattr(Collection, w), "__readonly_refuser__", False)]
    if unlocked:
        sys.exit(f"GUARD FAILED: {unlocked} not refused. Nothing was read.")
    print(f"read-only guard: {n} write methods refused")
    db = MongoClient(url, serverSelectionTimeoutMS=15000, tz_aware=True).get_database(name)
    print(f"database: {name} on {urllib.parse.urlparse(url).hostname}  (credentials not printed)")

    users = list(db.users.find({}, {f: 1 for f in USER_FIELDS}))
    require_fields(users, "email", "company_id", "role")
    companies = {str(c["_id"]): c for c in db.companies.find({}, {"name": 1, "is_test": 1})}

    def company(cid):
        c = companies.get(str(cid or ""))
        if not cid:
            return "(no company)"
        if not c:
            return f"(missing company {cid})"
        return f"{c.get('name')!r}{' [test]' if c.get('is_test') else ''}"

    try:
        deleted = f"{counted(users, 'is_deleted', lambda v: bool(v))} soft-deleted"
    except FieldNotInSample:
        deleted = "none of the first 50 carries is_deleted"
    print(f"\nACCOUNTS: {len(users)} total, {deleted}")
    per_company = Counter(str(u.get("company_id") or "") for u in users if u.get("company_id"))
    for cid, k in per_company.most_common():
        print(f"  {k:>4}  {company(cid)}  ({cid})")
    no_company = Counter(str(u.get("role") or "?") for u in users if not u.get("company_id"))
    print(f"  no company: {sum(no_company.values())} -- by role: {dict(no_company)}")

    def show(title, found):
        cross = {k: v for k, v in found.items()
                 if len({str(u.get('company_id') or '') for u in v}) > 1}
        print(f"\n{title}: {len(found)} group(s) -- {len(cross)} across companies, "
              f"{len(found) - len(cross)} within one company")
        for k, accounts in sorted(found.items(), key=lambda kv: (kv[0] not in cross, kv[0])):
            where = "ACROSS COMPANIES" if k in cross else "one company"
            print(f"  [{where}] {k}")
            for u in accounts:
                print(f"     user {u['_id']}  email={u.get('email')!r}  phone={u.get('phone')!r}  "
                      f"name={u.get('name')!r}  company={company(u.get('company_id'))}  "
                      f"role={u.get('role')}  status={u.get('account_status')}  "
                      f"deleted={bool(u.get('is_deleted'))}  created={u.get('created_at')}")

    show("SAME EMAIL (ignoring case and spaces)", groups(users, email_key, "email"))
    show("SAME PHONE (last 10 digits)", groups(users, phone_key, "phone"))
    print("\nNothing was written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
