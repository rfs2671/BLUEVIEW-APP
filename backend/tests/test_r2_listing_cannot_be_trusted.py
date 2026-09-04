"""AN HTTP 200 CARRYING A CORS DOCUMENT, PARSED AS AN EMPTY LISTING.

`R2_ENDPOINT_URL` ends in the bucket name --
`https://<account>.r2.cloudflarestorage.com/blueview` -- and boto3 appends
`Bucket=` on top of it. Object operations survive that: the doubled segment
becomes part of the key namespace, consistently, for every write and every read.
A LISTING does not. It becomes `GET /blueview/blueview?list-type=2`, a GET on an
object named `blueview`, and R2 answers **200 with the bucket's CORS
configuration**. botocore parses `<CORSConfiguration>` as a `ListBucketResult`,
finds no `Contents` and no `KeyCount`, and returns an empty page. No error, at
any layer, ever.

Measured against production 2026-09-04, one token, one client:

    head_object("plans/<proj>/<file>/page_1.jpg")   -> 3,353,739 bytes
    list_objects_v2(Prefix="plans/")                -> 200, CORS document
    list_buckets()                                  -> []

and with the bucket stripped from the endpoint, same credential:

    list_buckets()                                  -> ['blueview']
    head_object("plans/<proj>/<file>/page_1.jpg")   -> 404

IT IS NOT A PERMISSION, AND THE FIRST DIAGNOSIS SAID IT WAS. The token is Admin
Read & Write and can list. That reading survived one A/B against the production
client config and was only killed by dumping the raw HTTP body -- a reminder
that "I reproduced it" is not the same as "I know why". The 404 on the last line
is the load-bearing fact: the real keys carry the doubled segment, so
`R2_ENDPOINT_URL` is correct exactly as written and must not be "fixed".

WHAT IT COST. `_r2_delete_prefix` paged an empty result, deleted nothing,
returned a truthful 0 and never raised. `hard_delete_project` had NEVER removed
a plan page image, and it deleted the index rows -- the only record of those
keys -- before sweeping, so the bytes are unreachable.

THE STRONGEST FORM OF THE CLASS THIS REPO HAS BEEN CATALOGUING. The others were
checks that could not reach their subject. This one reached it, got a 200, and
the response it parsed was a different document about the same bucket. There is
no error to notice, no empty-set heuristic that fires, and the count it reports
is accurate.

AND THE TESTS THAT SHIPPED IT WERE MINE. Fifteen, asserting the call site sweeps
the right prefix with the right helper, plus a control run proving they fail
without the code. All passed. None asked whether the helper does anything,
because they tested the CALL and not the EFFECT.

NO STARTUP CHECK HERE. One was built and removed: it alerted on a permission
that is fine, which is wrong advice wired to fire forever. A check worth having
asserts the ENDPOINT SHAPE -- head_object a known key, list that key's own
prefix, alert when the object is present and the listing is empty -- and that is
recorded as an option rather than built.
"""

import ast
import os
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from tests.source_text import code_of  # noqa: E402

SRC = code_of("server.py")
#: The file AS WRITTEN. `code_of` strips comments and docstrings, so a
#: warning that lives in prose is invisible to SRC by design.
RAW = open(os.path.join(BACKEND, "server.py"), encoding="utf-8").read()


def _fn(name):
    i = SRC.index(f"async def {name}(")
    nxt = SRC.find("\nasync def ", i + 1)
    alt = SRC.find("\ndef ", i + 1)
    end = min(x for x in (nxt, alt, len(SRC)) if x > 0)
    return SRC[i:end]


class KeysAreDeletedByKey(unittest.TestCase):
    """Where the keys are known, nothing depends on listing."""

    def test_there_is_a_delete_by_key_helper(self):
        self.assertIn("async def _r2_delete_keys(", SRC)

    def test_it_uses_delete_objects_not_one_call_per_key(self):
        body = _fn("_r2_delete_keys")
        self.assertIn("delete_objects", body)
        self.assertIn("1000", body, "DeleteObjects caps at 1000 keys per call")

    def test_it_reports_per_key_refusals(self):
        """A batch delete can refuse individual keys in a 200 response -- the
        same shape as the defect this file exists for."""
        body = _fn("_r2_delete_keys")
        self.assertIn('resp.get("Errors")', body)
        self.assertIn("logger.error", body)


class TheKeysAreReadBeforeTheRowsAreDestroyed(unittest.TestCase):
    """The index rows are the ONLY record of the page-image keys. Deleting them
    first and sweeping afterwards leaves bytes nothing can name."""

    def test_file_delete_reads_the_keys_first(self):
        body = _fn("delete_project_file")
        self.assertLess(
            body.index("page_jpeg_r2_key"),
            body.index("db.document_page_index.delete_many"),
            "the keys must be collected BEFORE the rows that carry them go",
        )

    def test_file_delete_removes_them_by_key(self):
        body = _fn("delete_project_file")
        self.assertIn("_r2_delete_keys(_r2_client, R2_BUCKET_NAME, page_keys)", body)

    def test_hard_delete_reads_the_keys_first(self):
        body = _fn("hard_delete_project")
        self.assertLess(
            body.index("page_jpeg_r2_key"),
            body.index("db.document_page_index.delete_many"),
        )

    def test_hard_delete_removes_them_by_key(self):
        body = _fn("hard_delete_project")
        self.assertIn("_r2_delete_keys(_r2_client, R2_BUCKET_NAME, page_keys)", body)

    def test_both_collect_every_derivative_field(self):
        """A derivative whose key field is not read here is one the sweep is
        the only path to -- and the sweep is the thing that does not work."""
        for name in ("delete_project_file", "hard_delete_project"):
            body = _fn(name)
            for field in ("page_jpeg_r2_key", "page_thumb_r2_key",
                          "page_base_r2_key"):
                self.assertIn(field, body, f"{name} does not collect {field}")

    def test_the_prefix_sweep_is_kept_as_a_supplement(self):
        """Not removed: it is the only thing that can reach a derivative no row
        names, once the credential can list."""
        self.assertIn("_r2_delete_prefix(", _fn("delete_project_file"))
        self.assertIn("_r2_delete_prefix(", _fn("hard_delete_project"))


class TheHelperCarriesTheWarning(unittest.TestCase):
    """READ FROM `RAW`, NOT `SRC`. `code_of` strips comments AND docstrings, so
    a docstring assertion against it can only ever fail -- which is what the
    first draft of this test did. A warning that lives in prose has to be read
    from the file as written."""

    def test_the_docstring_says_an_empty_result_is_ambiguous(self):
        i = RAW.index("async def _r2_delete_prefix(")
        head = RAW[i:i + 3000]
        self.assertIn("_r2_delete_keys", head,
                      "the warning must name the alternative")
        self.assertIn("HTTP 200", head,
                      "the warning must say what the failure LOOKS like")


class NothingElseInProductionDependsOnListing(unittest.TestCase):
    """The census. Enumerated because "one helper" was an assumption until it
    was checked, and the whole finding is that a listing caller cannot tell
    it has failed."""

    def test_list_objects_v2_is_called_from_exactly_one_function(self):
        """BY AST, NOT BY SUBSTRING COUNT.

        An earlier draft counted occurrences of the string and found one more
        than there were calls, because the name also appeared inside an f-string
        in a diagnostic message. A substring standing in for a structural fact,
        written into a test whose whole subject is a call that lies about what
        it did. Counting text cannot tell a call from a mention; the AST can."""
        self.assertEqual(
            sorted(self._callers()), ["_r2_delete_prefix"],
            "A new listing caller against THIS deployment returns 0 whatever "
            "the bucket holds, and cannot tell that it has. Use head_object, "
            "or delete by explicit key.",
        )

    def test_the_count_is_asserted_too(self):
        """Membership alone passes on an empty scan."""
        self.assertEqual(len(self._callers()), 1)

    @staticmethod
    def _callers():
        tree = ast.parse(RAW)
        out = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(fn):
                # `client.list_objects_v2` passed to to_thread, or called
                # directly -- either way it appears as an Attribute load.
                if isinstance(n, ast.Attribute) and n.attr == "list_objects_v2":
                    out.append(fn.name)
        return sorted(set(out))

    def test_no_paginator_survives_outside_the_sweep(self):
        tree = ast.parse(open(os.path.join(BACKEND, "server.py"),
                              encoding="utf-8").read())
        sites = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(fn):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "get_paginator"):
                    sites.append(fn.name)
        self.assertEqual(sites, [], f"paginator callers: {sites}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
