"""THE WARRANT SENT A 54 MEGAPIXEL IMAGE AND COULD NOT READ IT.

`check_refusal_against_the_sheet` fetched the full page JPEG - 9000x6000, 54
MP - on the reasoning, written in the comment it replaced, that the full page
is more legible than a thumbnail. It is not.

MEASURED ON GN-001.00, one question, three renderings, three reps each,
byte-identical replies every time:

    the 54 MP page                     9000x6000   in=16304   NO
    the stored base layer              2048x1365   in= 2832   YES
    a naive LANCZOS of the 54 MP page  2048x1365   in= 2832   NO

THE SECOND AND THIRD ARE THE SAME SIZE AND COST THE SAME. So size is not the
variable; the resampling is. `_downscale_page_jpeg` calls `img.draft()`
first, which makes the JPEG decoder emit at 1/2, 1/4 or 1/8 scale - 9000 ->
2250 inside the decoder, averaging whole DCT blocks and suppressing the
ringing the 9000px encode introduced - and only the last step is a resize.

WHY GN-001.00 AND NOT SOME OTHER SHEET: it is the one page with a known
answer on both ends. The pre-build probe rendered it from the PDF at
2000-3000px and answered YES; the wired warrant answered NO. A third
rendering that says YES implicates the image rather than the model, and a
control with a known value on each side is the only kind that can.

WHAT THESE TESTS CAN AND CANNOT DO. They cannot call the model - that is a
paid, non-deterministic dependency. What they pin is the thing that WOULD
silently regress: which fetcher the warrant calls. The image is invisible in
every output the benchmark produces, so a change back to `_fetch_page_jpeg`
would show up as a worse overturn rate months later and be blamed on ranking.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

import server  # noqa: E402


class TheWarrantAsksForTheBaseLayer(unittest.TestCase):

    def setUp(self):
        # #638 split the warrant in two: `check_refusal_against_the_sheet`
        # loops over CANDIDATE_SHEETS candidates and `_check_one_sheet` does
        # the fetching. The fetch is what this file is about, so it inspects
        # the function that fetches - naming the wrong one is how a test
        # earlier in this arc read `_handle_group_lifecycle` while claiming
        # to read `_process_whatsapp_message`.
        self.src = inspect.getsource(server._check_one_sheet)

    def test_the_loop_still_goes_through_the_fetching_function(self):
        """If the two are ever merged back, the source above stops being the
        one that matters and every assertion here quietly tests nothing."""
        self.assertIn("_check_one_sheet(",
                      inspect.getsource(server.check_refusal_against_the_sheet))

    def test_it_fetches_the_base_and_not_the_full_page(self):
        self.assertIn("_fetch_page_base(page_rec)", self.src)
        self.assertNotIn("_fetch_page_jpeg(page_rec)", self.src)

    def test_the_page_record_still_carries_the_base_key(self):
        """`_fetch_page_base` reads `page_base_r2_key` off the record it is
        handed. Projecting it away would send every call down the regenerate
        path - correct output, 54 MP decoded on every refusal."""
        self.assertIn("page_base_r2_key", self.src)

    def test_the_measurement_is_recorded_where_the_choice_is(self):
        """The three verdicts are the whole reason for this line. Without
        them the next reader sees a smaller image being sent to a model and
        'fixes' it back."""
        for token in ("9000", "2048", "draft"):
            self.assertIn(token, self.src,
                          f"the reasoning lost {token!r}")


class TheFallbackCannotLeaveTheWarrantBlind(unittest.TestCase):
    """A page with no stored base must still be checkable."""

    def test_it_regenerates_when_the_key_is_missing(self):
        made = {}

        async def no_key_fetch(rec):
            made["full"] = True
            return b"FULLBYTES"

        def make_base(b):
            made["base"] = b
            return b"BASEBYTES"

        saved = (server._fetch_page_jpeg, server._make_page_base_jpeg,
                 server._r2_client)
        try:
            server._fetch_page_jpeg = no_key_fetch
            server._make_page_base_jpeg = make_base
            server._r2_client = None
            got = asyncio.run(server._fetch_page_base({"file_id": "f1"}))
        finally:
            (server._fetch_page_jpeg, server._make_page_base_jpeg,
             server._r2_client) = saved
        self.assertEqual(got, b"BASEBYTES")
        self.assertEqual(made.get("base"), b"FULLBYTES")

    def test_no_image_at_all_returns_none_not_an_exception(self):
        """Every failure path in the warrant returns None and lets the
        refusal stand. A raise here would turn a missing derivative into a
        dropped reply."""
        async def nothing(rec):
            return None

        saved = (server._fetch_page_jpeg, server._r2_client)
        try:
            server._fetch_page_jpeg = nothing
            server._r2_client = None
            self.assertIsNone(
                asyncio.run(server._fetch_page_base({"file_id": "f1"})))
        finally:
            server._fetch_page_jpeg, server._r2_client = saved


class TheOtherCallersKeepTheFullPage(unittest.TestCase):
    """AUDIT, PINNED. Four of the five callers of `_fetch_page_jpeg` must NOT
    move to the base layer, and the reasons differ:

      _fetch_page_base    PRODUCES the base from the full - it is the source
      _fetch_page_thumb   produces the 400px thumbnail, same reason
      _send_plan_image    delivers to a person who may zoom; not a model
      debug_test_plan...  the same delivery path, behind a debug route

    Only one caller was ever a vision call. If a second appears, it should
    fail here and be argued for rather than inherited."""

    def test_the_derivative_makers_still_read_the_full_page(self):
        for fn in (server._fetch_page_base, server._fetch_page_thumb):
            self.assertIn("_fetch_page_jpeg(page_rec)",
                          inspect.getsource(fn),
                          f"{fn.__name__} must build from the full page")

    def test_the_human_delivery_path_is_unchanged(self):
        self.assertIn("_fetch_page_jpeg(page_rec)",
                      inspect.getsource(server._send_plan_image))

    def test_only_one_vision_call_reads_a_stored_page_image(self):
        """The indexer renders from the PDF with `_render_pdf_page`, so it is
        not on this path at all and a change there is a re-index decision."""
        src = Path(server.__file__).read_text(encoding="utf-8")
        self.assertEqual(
            src.count("_fetch_page_jpeg(page_rec)"), 3,
            "a caller of the full page was added or removed; re-do the audit "
            "in test docstring above before changing this number")


if __name__ == "__main__":
    unittest.main()
