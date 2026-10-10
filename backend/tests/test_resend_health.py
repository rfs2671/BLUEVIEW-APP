"""The startup Resend check: a sending-only key is fine (INFO), not a
warning. Resend answers GET /domains with 401 restricted_api_key for it."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")

import server  # noqa: E402


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _client(resp):
    class C:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return resp
    return C


def _check(resp):
    import lib.server_http as sh
    with patch.object(server, "RESEND_API_KEY", "re_test"), \
            patch.object(sh, "ServerHttpClient", _client(resp)), \
            patch.object(server.logger, "info") as info, \
            patch.object(server.logger, "warning") as warning, \
            patch.object(server.logger, "error") as error:
        asyncio.run(server._verify_resend_domain_at_startup())
    return info, warning, error


class SendingOnlyKey(unittest.TestCase):

    def test_restricted_api_key_is_info_not_a_warning(self):
        info, warning, error = _check(_Resp(401, {
            "statusCode": 401, "name": "restricted_api_key",
            "message": "This API key is restricted to only send emails"}))
        warning.assert_not_called()
        error.assert_not_called()
        self.assertIn("sending-only API key", info.call_args[0][0])

    def test_the_message_alone_is_enough(self):
        info, warning, _ = _check(_Resp(401, {"message": "This API key is restricted to only send emails"}))
        warning.assert_not_called()
        info.assert_called_once()

    def test_any_other_401_still_warns(self):
        for body in ({"name": "invalid_api_key", "message": "API key is invalid"},
                     ValueError("not json"), ["x"]):
            info, warning, _ = _check(_Resp(401, body))
            warning.assert_called_once()
            info.assert_not_called()

    def test_a_500_still_warns(self):
        _info, warning, _ = _check(_Resp(500, {"name": "internal_server_error"}))
        warning.assert_called_once()

    def test_a_full_access_key_still_checks_the_domain(self):
        info, warning, error = _check(_Resp(200, {"data": [{"name": "levelog.com",
                                                             "status": "verified"}]}))
        warning.assert_not_called()
        error.assert_not_called()
        info.assert_called_once()
        _info, _w, error = _check(_Resp(200, {"data": [{"name": "levelog.com",
                                                        "status": "failed"}]}))
        error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
