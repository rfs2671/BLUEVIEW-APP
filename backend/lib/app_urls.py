"""Where the app lives, defined ONCE.

THE BUG THIS CLOSES. This value was defined twice, in two files, and the two
had drifted:

    server.py:39030          APP_BASE_URL default = "https://app.levelog.com"
    lib/notifications.py:77  APP_BASE_URL default = "https://www.levelog.com"

Both read the same environment variable, so production was consistent and
nothing failed. The drift was invisible precisely because the variable IS set
on the Railway service — the defaults are dead code there, and dead code does
not get corrected. On any environment where the variable is unset, permit
renewal deep links would have pointed at the app while notification emails
pointed at the marketing site, from the same request.

WHY THERE IS NO DEFAULT ANY MORE.

This value's only job is to build links that go into EMAILS TO CUSTOMERS. Think
about the two failure modes:

  A DEFAULT THAT IS WRONG fails silently and permanently. No test covers it, no
  deploy turns red, the link renders fine, and it lands in somebody's inbox
  pointing at a page that is not ours to fix. An email cannot be recalled and a
  customer who follows a dead link does not file a bug — he concludes the
  product is broken.

  A MISSING VARIABLE fails loudly, at import, on the first deploy that lacks
  it, in front of the person deploying.

The second is strictly cheaper, and the drift above is the evidence: a default
is a value nobody has to think about, which is exactly why the two stopped
agreeing. So this raises instead.

Every environment that runs this must set APP_BASE_URL. The test suite sets it
in backend/tests/conftest.py; the CI import smoke job sets it alongside
MONGO_URL and the rest.
"""

from __future__ import annotations

import os

_RAW = os.environ.get("APP_BASE_URL")

if not _RAW or not _RAW.strip():
    raise RuntimeError(
        "APP_BASE_URL is not set.\n"
        "\n"
        "It is the base of every link this backend puts in an email — permit\n"
        "renewal reminders, notification action links, annotation short links.\n"
        "There is deliberately no default: a wrong default sends a dead link to\n"
        "a customer and nothing goes red, while a missing variable stops the\n"
        "process here, now, in front of you.\n"
        "\n"
        "Production and preview: set it on the service (https://app.levelog.com).\n"
        "Local and CI: export APP_BASE_URL before starting or running tests."
    )

#: Base URL of the customer-facing app, no trailing slash.
APP_BASE_URL = _RAW.strip().rstrip("/")
