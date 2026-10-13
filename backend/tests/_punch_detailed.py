"""Walks in these suites are DETAILED (trades and locations asked and
shown): they were written for it. Simple -- the company default since Tue
Oct 13 (1:43 PM, 588) -- is tests/test_punch_walk_brain.py.

    from tests import _punch_detailed
    setUpModule, tearDownModule = _punch_detailed.module_hooks()
"""

from __future__ import annotations

from unittest.mock import patch

import server


async def _detailed(company_id):
    return "detailed"


def module_hooks():
    p = patch.object(server, "_punch_company_detail", _detailed)
    return p.start, p.stop
