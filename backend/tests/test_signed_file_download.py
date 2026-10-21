"""A DOWNLOAD LINK NAMES ONE FILE, ONE PRINCIPAL AND TWO MINUTES.

WHAT WAS BROKEN. Plans & Files' Download built `/content?token=<JWT>` from
window.localStorage. A phone has no window.localStorage, so the token was
empty and the browser opened on {"detail":"Not authenticated"} -- the four
non-webhook `token=` lines in the retained Railway logs are exactly those
401s. On the web it worked by putting the 30-day session token in a URL.

WHAT REPLACES IT. GET /api/files/{id}/signed-url (bearer header) returns a
link to /api/files/{id}/download carrying an HMAC over file id, principal and
an expiry 120s out. Asserted here, over real HTTP through server.app (every
middleware, the real JWT, only the database and R2 replaced):

  * the link works with NO header, and keeps working for a second byte range
    (not single-use -- a PDF viewer comes back for ranges);
  * changing any signed field (file, user, kind, expiry) or the signature
    refuses it, and so does the clock;
  * the signature is not the permission: a user deleted, moved to another
    company or set pending after the link was minted is refused;
  * a stranger cannot mint one, and a site device only for its allow-list;
  * the ?token= path still authenticates, and every use of it is logged
    with the path and subject and never the token.
"""

import asyncio
import io
import logging
import os
import re
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

import httpx  # noqa: E402
from bson import ObjectId  # noqa: E402

import server  # noqa: E402
from async_fake_mongo import AsyncFakeDB  # noqa: E402

BYTES = b"%PDF-1.7\n" + bytes(range(256)) * 40 + b"\n%%EOF\n"

CO_A, CO_B = ObjectId(), ObjectId()
PROJ_A = ObjectId()
FILE_A = ObjectId()        # in the device's allowed folder
FILE_HIDDEN = ObjectId()   # same project, folder NOT ticked for the device
FILE_UNSTORED = ObjectId()
ADMIN_A, ADMIN_B, CP_A = ObjectId(), ObjectId(), ObjectId()
DEVICE = ObjectId()


class FakeR2:
    """get_object with a single `Range`, the way R2/S3 answer it."""

    def __init__(self):
        self.calls = []

    def get_object(self, Bucket, Key, Range=None):
        self.calls.append((Key, Range))
        if Key != "co/proj/plan.pdf" and Key != "co/proj/hidden.pdf":
            raise KeyError(Key)
        if not Range:
            return {"Body": io.BytesIO(BYTES), "ContentLength": len(BYTES),
                    "ContentType": "application/pdf"}
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", Range)
        a, b = m.group(1), m.group(2)
        if a == "":
            start, end = len(BYTES) - int(b), len(BYTES) - 1
        else:
            start = int(a)
            end = min(int(b), len(BYTES) - 1) if b else len(BYTES) - 1
        if start >= len(BYTES):
            err = Exception("InvalidRange")
            err.response = {"Error": {"Code": "InvalidRange"}}
            raise err
        chunk = BYTES[start:end + 1]
        return {"Body": io.BytesIO(chunk), "ContentLength": len(chunk),
                "ContentRange": f"bytes {start}-{end}/{len(BYTES)}",
                "ContentType": "application/pdf"}


def _seed():
    db = AsyncFakeDB()
    db.companies.docs += [{"_id": CO_A, "name": "Acme"}, {"_id": CO_B, "name": "Other"}]
    db.projects.docs.append({
        "_id": PROJ_A, "company_id": str(CO_A), "name": "Tower",
        "status": "active", "is_deleted": False,
        "dropbox_folder_path": "/jobs/tower",
        "site_device_subfolders": ["plans"]})
    for oid, key, path in ((FILE_A, "co/proj/plan.pdf", "/jobs/tower/plans/plan.pdf"),
                           (FILE_HIDDEN, "co/proj/hidden.pdf", "/jobs/tower/office/hidden.pdf"),
                           (FILE_UNSTORED, "", "/jobs/tower/plans/unstored.pdf")):
        db.project_files.docs.append({
            "_id": oid, "project_id": str(PROJ_A), "company_id": str(CO_A),
            "name": path.rsplit("/", 1)[-1], "dropbox_path": path, "r2_key": key,
            "size": len(BYTES)})
    for oid, co, role in ((ADMIN_A, CO_A, "admin"), (ADMIN_B, CO_B, "admin"),
                          (CP_A, CO_A, "cp")):
        db.users.docs.append({
            "_id": oid, "email": f"{oid}@t.test", "name": role, "role": role,
            "company_id": str(co), "account_status": "approved",
            "is_deleted": False})
    db.site_devices.docs.append({
        "_id": DEVICE, "project_id": str(PROJ_A), "device_name": "Gate",
        "is_active": True})
    return db


def _tok(uid, role="admin", co=CO_A):
    return server.create_token(str(uid), f"{uid}@t.test", role, company_id=str(co))


def _device_tok():
    return server.create_token(str(DEVICE), "gate", "site_device", site_mode=True,
                               project_id=str(PROJ_A), company_id=str(CO_A))


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _swap(path, key, value):
    return re.sub(rf"([?&]{key}=)[^&]*", lambda m: m.group(1) + value, path)


async def _run(fn):
    db = _seed()
    r2 = FakeR2()
    with patch.object(server, "db", db), \
            patch.object(server, "_r2_client", r2), \
            patch.object(server, "R2_BUCKET_NAME", "bucket"):
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await fn(c, db, r2)


def run(fn):
    return asyncio.run(_run(fn))


async def _link(c, file_id=FILE_A, tok=None):
    r = await c.get(f"/api/files/{file_id}/signed-url", headers=_h(tok or _tok(ADMIN_A)))
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()


class TheLinkWorksWithoutAHeader(unittest.TestCase):

    def test_minting_needs_a_session(self):
        async def go(c, db, r2):
            return (await c.get(f"/api/files/{FILE_A}/signed-url")).status_code
        self.assertEqual(run(go), 401)

    def test_the_link_serves_the_bytes_with_no_authorization(self):
        async def go(c, db, r2):
            body = await _link(c)
            r = await c.get(body["path"])
            return body, r
        body, r = run(go)
        self.assertEqual(r.status_code, 200, r.text[:300])
        self.assertEqual(r.content, BYTES)
        self.assertEqual(body["expires_in"], 120)
        self.assertNotIn("token=", body["path"])
        self.assertTrue(body["url"].endswith(body["path"]))
        self.assertIn("inline", r.headers["content-disposition"])
        self.assertEqual(r.headers["accept-ranges"], "bytes")
        self.assertIn("no-store", r.headers["cache-control"])

    def test_it_is_not_single_use_and_answers_byte_ranges(self):
        async def go(c, db, r2):
            path = (await _link(c))["path"]
            first = await c.get(path, headers={"Range": "bytes=0-99"})
            second = await c.get(path, headers={"Range": "bytes=100-199"})
            tail = await c.get(path, headers={"Range": "bytes=-7"})
            whole = await c.get(path)
            return first, second, tail, whole
        first, second, tail, whole = run(go)
        self.assertEqual((first.status_code, first.content), (206, BYTES[0:100]))
        self.assertEqual(first.headers["content-range"], f"bytes 0-99/{len(BYTES)}")
        self.assertEqual((second.status_code, second.content), (206, BYTES[100:200]))
        self.assertEqual((tail.status_code, tail.content), (206, BYTES[-7:]))
        self.assertEqual((whole.status_code, whole.content), (200, BYTES))

    def test_a_range_past_the_end_is_416(self):
        async def go(c, db, r2):
            path = (await _link(c))["path"]
            return await c.get(path, headers={"Range": f"bytes={len(BYTES) + 10}-"})
        self.assertEqual(run(go).status_code, 416)

    def test_dl_1_asks_for_an_attachment(self):
        async def go(c, db, r2):
            path = (await _link(c))["path"]
            return await c.get(path + "&dl=1")
        r = run(go)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-disposition"].startswith("attachment;"))


class EverySignedFieldIsBound(unittest.TestCase):

    def _refused(self, mutate):
        async def go(c, db, r2):
            body = await _link(c)
            r = await c.get(mutate(body["path"]))
            return r, len(r2.calls)
        r, r2_calls = run(go)
        self.assertEqual(r.status_code, 403, r.text[:200])
        self.assertIn("not valid", r.text)
        self.assertIn("no es válido", r.text)
        self.assertEqual(r2_calls, 0, "storage must not be touched for a bad link")

    def test_another_file(self):
        self._refused(lambda p: p.replace(str(FILE_A), str(FILE_HIDDEN)))

    def test_another_user(self):
        self._refused(lambda p: _swap(p, "u", str(CP_A)))

    def test_another_kind(self):
        self._refused(lambda p: _swap(p, "k", "d"))

    def test_a_later_expiry(self):
        self._refused(lambda p: _swap(p, "e", str(int(time.time()) + 10 ** 6)))

    def test_a_forged_signature(self):
        self._refused(lambda p: _swap(p, "s", "0" * 64))

    def test_a_missing_signature(self):
        self._refused(lambda p: p.split("&s=")[0])

    def test_an_expired_link_says_so_in_both_languages(self):
        async def go(c, db, r2):
            principal = {"id": str(ADMIN_A), "role": "admin"}
            path, _ = server._sign_file_download_path(
                str(FILE_A), principal, now=time.time() - 121)
            return await c.get(path)
        r = run(go)
        self.assertEqual(r.status_code, 403)
        self.assertIn("expired", r.text)
        self.assertIn("caducado", r.text)

    def test_the_lifetime_is_120_seconds(self):
        self.assertEqual(server.FILE_DOWNLOAD_LINK_TTL_SECONDS, 120)
        now = 1_800_000_000
        path, exp = server._sign_file_download_path(
            str(FILE_A), {"id": str(ADMIN_A)}, now=now)
        self.assertEqual(exp, now + 120)
        q = dict(kv.split("=") for kv in path.split("?")[1].split("&"))
        self.assertIsNone(server._check_file_download_signature(
            str(FILE_A), q["k"], q["u"], q["e"], q["s"], now=now + 120))
        self.assertEqual(server._check_file_download_signature(
            str(FILE_A), q["k"], q["u"], q["e"], q["s"], now=now + 121), "expired")


class TheSignatureIsNotThePermission(unittest.TestCase):

    def _after(self, change):
        async def go(c, db, r2):
            path = (await _link(c))["path"]
            change(db)
            return await c.get(path)
        return run(go)

    def _user(self, db):
        return next(u for u in db.users.docs if u["_id"] == ADMIN_A)

    def test_a_user_deleted_after_minting_is_refused(self):
        r = self._after(lambda db: self._user(db).update(is_deleted=True))
        self.assertEqual(r.status_code, 403)
        self.assertIn("do not have access", r.text)
        self.assertIn("No tiene acceso", r.text)

    def test_a_user_moved_to_another_company_is_refused(self):
        r = self._after(lambda db: self._user(db).update(company_id=str(CO_B)))
        self.assertEqual(r.status_code, 403)

    def test_a_user_set_pending_is_refused(self):
        r = self._after(lambda db: self._user(db).update(account_status="pending"))
        self.assertEqual(r.status_code, 403)

    def test_a_file_removed_after_minting_is_missing(self):
        r = self._after(lambda db: db.project_files.docs.clear())
        self.assertEqual(r.status_code, 404)
        self.assertIn("Este archivo no está disponible", r.text)

    def test_control_unchanged_principal_still_downloads(self):
        self.assertEqual(self._after(lambda db: None).status_code, 200)


class WhoMayMintOne(unittest.TestCase):

    def _status(self, file_id, tok):
        async def go(c, db, r2):
            r = await c.get(f"/api/files/{file_id}/signed-url", headers=_h(tok))
            return r.status_code
        return run(go)

    def test_another_companys_admin_cannot(self):
        self.assertEqual(self._status(FILE_A, _tok(ADMIN_B, co=CO_B)), 403)

    def test_a_file_not_in_storage_is_404(self):
        # The DETAIL, not just the status: a route that does not exist is a
        # 404 too, and that is exactly what this read before the route did.
        async def go(c, db, r2):
            r = await c.get(f"/api/files/{FILE_UNSTORED}/signed-url", headers=_h(_tok(ADMIN_A)))
            return r.status_code, r.json().get("detail")
        self.assertEqual(run(go), (404, "File not stored in R2"))

    def test_an_unknown_file_is_404_and_a_bad_id_400(self):
        self.assertEqual(self._status(ObjectId(), _tok(ADMIN_A)), 404)
        self.assertEqual(self._status("not-an-id", _tok(ADMIN_A)), 400)

    def test_a_device_gets_its_allowed_folder_only(self):
        self.assertEqual(self._status(FILE_A, _device_tok()), 200)
        self.assertEqual(self._status(FILE_HIDDEN, _device_tok()), 403)

    def test_a_device_link_works_and_dies_with_the_device(self):
        async def go(c, db, r2):
            path = (await _link(c, tok=_device_tok()))["path"]
            ok = await c.get(path)
            db.site_devices.docs[0]["is_active"] = False
            off = await c.get(path)
            return ok, off, path
        ok, off, path = run(go)
        self.assertIn("k=d", path)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(off.status_code, 403)


class TheQueryTokenIsStillAcceptedAndCounted(unittest.TestCase):

    def _logs(self, fn):
        records = []

        class _H(logging.Handler):
            def emit(self, rec):
                records.append(rec.getMessage())

        h = _H(level=logging.INFO)
        prev = server.logger.level
        server.logger.addHandler(h)
        server.logger.setLevel(logging.INFO)
        try:
            out = run(fn)
        finally:
            server.logger.removeHandler(h)
            server.logger.setLevel(prev)
        return out, [m for m in records if m.startswith("[query-token]")]

    def test_a_query_token_still_authenticates_and_is_logged_without_its_value(self):
        tok = _tok(ADMIN_A)

        async def go(c, db, r2):
            return await c.get(
                f"/api/projects/{PROJ_A}/files/{FILE_A}/content?token={tok}",
                headers={"X-Client-Version": "1.3.0"})
        r, lines = self._logs(go)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(f"path=/api/projects/{PROJ_A}/files/{FILE_A}/content", lines[0])
        self.assertIn(f"user={ADMIN_A}", lines[0])
        self.assertIn("outcome=ok", lines[0])
        self.assertIn("client=1.3.0", lines[0])
        self.assertNotIn(tok, lines[0])
        self.assertNotIn(tok.split(".")[1], lines[0])

    def test_the_empty_token_the_phone_sent_is_logged_too(self):
        async def go(c, db, r2):
            return await c.get(f"/api/projects/{PROJ_A}/files/{FILE_A}/content?token=")
        r, lines = self._logs(go)
        self.assertEqual(r.status_code, 401)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("outcome=empty", lines[0])

    def test_a_header_request_logs_nothing(self):
        async def go(c, db, r2):
            return await c.get(f"/api/projects/{PROJ_A}/files/{FILE_A}/content",
                               headers=_h(_tok(ADMIN_A)))
        r, lines = self._logs(go)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(lines, [])

    def test_the_signed_download_is_not_a_query_token_use(self):
        async def go(c, db, r2):
            path = (await _link(c))["path"]
            return await c.get(path)
        r, lines = self._logs(go)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(lines, [])


class RefusedLinksAreRateLimitedPerAddress(unittest.TestCase):
    """Forged or stale links: 20 a minute per address, then 429 before any
    MAC is computed. Good links are not counted -- a PDF viewer's ranges."""

    def setUp(self):
        server.signed_download_refusal_limiter.reset()

    tearDown = setUp

    def test_the_21st_refusal_from_one_address_is_429_and_storage_is_untouched(self):
        cap = server.SIGNED_DOWNLOAD_REFUSALS_PER_MINUTE

        async def go(c, db, r2):
            good = (await _link(c))["path"]
            bad = _swap(good, "s", "0" * 64)
            ip = {"X-Forwarded-For": "203.0.113.7"}
            refused = [(await c.get(bad, headers=ip)).status_code for _ in range(cap)]
            throttled = await c.get(bad, headers=ip)
            # A GOOD link from the same address is throttled too: the cap is
            # on the address, read before the signature.
            good_after = await c.get(good, headers=ip)
            other_ip = await c.get(good, headers={"X-Forwarded-For": "198.51.100.9"})
            return refused, throttled, good_after, other_ip, len(r2.calls)
        refused, throttled, good_after, other_ip, r2_calls = run(go)
        self.assertEqual(refused, [403] * cap)
        self.assertEqual(throttled.status_code, 429)
        self.assertEqual(throttled.headers.get("retry-after"), "60")
        self.assertIn("Too many download attempts", throttled.text)
        self.assertIn("Demasiados intentos", throttled.text)
        self.assertEqual(good_after.status_code, 429)
        self.assertEqual(other_ip.status_code, 200, "another address is unaffected")
        self.assertEqual(r2_calls, 1, "only the other address's good link reached storage")

    def test_good_links_are_not_counted(self):
        cap = server.SIGNED_DOWNLOAD_REFUSALS_PER_MINUTE

        async def go(c, db, r2):
            good = (await _link(c))["path"]
            ip = {"X-Forwarded-For": "203.0.113.8", "Range": "bytes=0-9"}
            return [(await c.get(good, headers=ip)).status_code for _ in range(cap + 5)]
        self.assertEqual(run(go), [206] * (cap + 5))

    def test_the_route_has_its_own_per_ip_bucket_in_the_middleware(self):
        from lib import rate_limits
        self.assertEqual(
            rate_limits._match_rule("GET", f"/api/files/{FILE_A}/download"),
            ("/api/files/{id}/download", "600/1 minute", "ip"))


class TheRouteIsMountedOutsideTheAuthenticatedRouter(unittest.TestCase):

    def test_download_is_on_app_and_signed_url_on_the_api_router(self):
        dl = [r for r in server.app.routes
              if getattr(r, "path", None) == "/api/files/{file_id}/download"]
        self.assertEqual(len(dl), 1)
        self.assertNotIn("/files/{file_id}/download",
                         [getattr(r, "path", None) for r in server.api_router.routes])
        self.assertIn("/api/files/{file_id}/signed-url",
                      [getattr(r, "path", None) for r in server.api_router.routes])


if __name__ == "__main__":
    unittest.main()
