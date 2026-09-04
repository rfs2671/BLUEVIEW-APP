"""PAGE ONE OF A PLAN, SMALL ENOUGH FOR A LIST ROW.

THE GAP THIS CLOSES. The plan list draws a blank document icon, so the only way
to tell which sheet a row is is to open it — and an open costs the CP 20-30
seconds, twice when he picks wrong. The pixels have existed all along: the
indexer renders every page at 250 DPI (`_PLAN_RENDER_DPI`) and stores it in R2
at `plans/{project}/{file}/page_{N}.jpg` for the VLM. Nothing has ever served
one to a phone; the only HTTP surfaces exposing `page_jpeg_r2_key` were two
`/debug/` endpoints.

So this is plumbing, not rendering, and these tests hold the four properties
that make it plumbing rather than a second rasteriser:

  1. THE THUMBNAIL IS MADE FROM THE RENDERED PAGE, not from the PDF. The
     expensive step has already happened when `_make_page_thumb_jpeg` is
     called; re-rendering to get a small copy would pay poppler twice.

  2. PAGE ONE ONLY. A thumbnail for sheet 147 of a 200-sheet set is storage
     nobody reads.

  3. THE KEY IS WRITTEN ON EVERY BRANCH THAT WRITES THE PAGE ROW, including
     the two that record "no image". An absent key and an empty key are
     different facts, and the reader ladder distinguishes them.

  4. THE MANIFEST FLAG RIDES THE FILE ROW. A parallel `thumbnails` section
     would need a second copy of the site device's visibility filter, and this
     file already documents what that costs.
"""

import io
import os
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from tests.source_text import code_of  # noqa: E402

SRC = code_of("server.py")


class TheThumbnailIsMadeFromThePageNotThePdf(unittest.TestCase):
    """Functional — this one actually runs the encoder."""

    @staticmethod
    def _page_jpeg(w, h):
        from PIL import Image
        img = Image.new("RGB", (w, h), "white")
        # A little structure so the encoder has something to do; a flat image
        # compresses to almost nothing and would make the size assertion
        # meaningless.
        for x in range(0, w, 40):
            for y in range(0, h, 40):
                img.putpixel((x, y), (0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    def _make(self, data):
        import server
        return server._make_page_thumb_jpeg(data)

    def test_an_arch_e_sheet_comes_back_within_the_long_edge(self):
        """9000x12000 at 250 DPI is what an ARCH-E sheet actually renders to."""
        from PIL import Image
        src = self._page_jpeg(1200, 900)      # same aspect, tractable in a test
        out = self._make(src)
        self.assertIsNotNone(out)
        img = Image.open(io.BytesIO(out))
        self.assertEqual(max(img.size), 400)
        self.assertLess(len(out), len(src))

    def test_aspect_ratio_survives(self):
        from PIL import Image
        out = self._make(self._page_jpeg(1200, 900))
        img = Image.open(io.BytesIO(out))
        self.assertAlmostEqual(img.size[0] / img.size[1], 1200 / 900, places=1)

    def test_an_already_small_page_is_not_upscaled(self):
        from PIL import Image
        out = self._make(self._page_jpeg(120, 90))
        img = Image.open(io.BytesIO(out))
        self.assertEqual(img.size, (120, 90))

    def test_garbage_returns_None_rather_than_raising(self):
        """A missing thumbnail is the blank icon the list already draws. It
        must never be able to fail an import."""
        self.assertIsNone(self._make(b"not a jpeg"))
        self.assertIsNone(self._make(b""))
        self.assertIsNone(self._make(None))


class PageOneOnly(unittest.TestCase):
    def test_the_thumb_upload_is_guarded_on_page_one(self):
        self.assertIn("if page_number == 1:", SRC)
        i = SRC.index("if page_number == 1:")
        self.assertIn("_upload_page_thumb_to_r2", SRC[i:i + 400])

    def test_the_full_page_upload_is_NOT_guarded(self):
        """Every page keeps its full JPEG — the VLM query path reads them."""
        i = SRC.index("page_jpeg_r2_key = await _upload_page_jpeg_to_r2")
        window = SRC[max(0, i - 300):i]
        self.assertNotIn("if page_number == 1:", window)


class TheKeyIsWrittenOnEveryBranch(unittest.TestCase):
    def test_three_write_sites_for_three_write_sites(self):
        """The two 'no image' branches and the real one. An absent key would
        make a page indexed today indistinguishable from one indexed before
        this existed.

        COUNTS WRITES, not mentions. Both keys also appear in readers,
        projections and two debug endpoints. A write is a line in the index
        document literal: the key, then either `""` or the variable holding
        what was uploaded. Anything else is a read and says nothing about
        whether the row is written consistently.
        """
        def writes(key):
            n = 0
            for ln in SRC.splitlines():
                t = ln.strip()
                if not t.startswith(f'"{key}":'):
                    continue
                value = t.split(":", 1)[1].strip().rstrip(",").strip()
                if value == '""' or value == key:
                    n += 1
            return n

        self.assertEqual(writes("page_thumb_r2_key"), 3)
        self.assertEqual(writes("page_thumb_r2_key"), writes("page_jpeg_r2_key"))

    def test_the_empty_branches_record_empty_not_absent(self):
        self.assertEqual(SRC.count('"page_thumb_r2_key":  "",'), 2)


class TheReaderIsALadder(unittest.TestCase):
    def test_the_thumb_reader_falls_back_to_the_full_page(self):
        """Every v2-indexed plan already has a full page JPEG, so the existing
        set gets thumbnails with no backfill."""
        i = SRC.index("async def _fetch_page_thumb")
        body = SRC[i:i + 1400]
        self.assertIn("page_thumb_r2_key", body)
        self.assertIn("_fetch_page_jpeg", body)
        self.assertIn("_make_page_thumb_jpeg", body)

    def test_the_reader_does_not_write_back_to_r2(self):
        i = SRC.index("async def _fetch_page_thumb")
        body = SRC[i:SRC.index("async def _fetch_page_jpeg")]
        self.assertNotIn("_upload_to_r2", body)
        self.assertNotIn("_upload_page_thumb_to_r2", body)


class TheEndpointIsScopedToTheProject(unittest.TestCase):
    def test_it_declares_require_project_access(self):
        i = SRC.index('"/projects/{project_id}/files/{file_id}/thumbnail"')
        head = SRC[i:i + 200]
        self.assertIn("require_project_access", head)

    def test_the_record_lookup_is_keyed_on_the_project_too(self):
        """A file id from another project must 404, not resolve."""
        i = SRC.index("async def get_project_file_thumbnail")
        body = SRC[i:i + 2000]
        self.assertIn('"project_id": project_id', body)
        self.assertIn('"is_deleted": {"$ne": True}', body)

    def test_a_missing_thumbnail_is_a_404_not_a_placeholder_image(self):
        i = SRC.index("async def get_project_file_thumbnail")
        body = SRC[i:i + 2000]
        self.assertIn("status_code=404", body)

    def test_the_cache_header_is_private(self):
        """A picture of a plan sheet is as confidential as the plan."""
        i = SRC.index("async def get_project_file_thumbnail")
        body = SRC[i:i + 2000]
        self.assertIn("private, max-age=", body)
        self.assertNotIn("public, max-age=", body)


class TheManifestFlagRidesTheFileRow(unittest.TestCase):
    def test_there_is_no_second_thumbnails_section(self):
        self.assertNotIn('"thumbnails": {', SRC)

    def test_the_flag_is_applied_after_the_visibility_filter(self):
        """`file_rows` has already passed `_visible_to_site`. Decorating it
        cannot drift from the filter; a parallel query could."""
        vis = SRC.index("_visible_to_site")
        flag = SRC.index('_r["t"] = 1')
        self.assertLess(vis, flag)

    def test_the_flag_is_a_flag_not_a_url(self):
        """A url in a cached manifest is an authenticated endpoint written into
        a document that outlives the token."""
        i = SRC.index("_thumb_ids = set()")
        body = SRC[i:i + 900]
        self.assertNotIn("http", body)
        self.assertIn('"page_thumb_r2_key": 1', body)

    def test_a_failure_degrades_rather_than_failing_the_manifest(self):
        """A manifest that raises is a device that syncs nothing."""
        i = SRC.index("_thumb_ids = set()")
        body = SRC[i:i + 1200]
        self.assertIn("except Exception", body)


class TheBaseLayerIsTheSamePipelineAtADifferentSize(unittest.TestCase):
    """RULED: 2048px long edge, q80. At fit-to-width on a ~1000 css tablet the
    sheet occupies ~2000 device px, so 2048 is sharp rather than soft — and if
    pdf.js takes twenty seconds this is not a flash, it is what the CP looks at
    for twenty seconds."""

    def test_the_ruled_size(self):
        import server
        self.assertEqual(server._PLAN_BASE_MAX_EDGE, 2048)
        self.assertEqual(server._PLAN_BASE_QUALITY, 80)

    def test_one_downscaler_serves_both_derivatives(self):
        """Two resize implementations is two to keep in step. The thumbnail and
        the base layer are one function with two sets of constants."""
        self.assertIn("def _downscale_page_jpeg(", SRC)
        for wrapper in ("_make_page_thumb_jpeg", "_make_page_base_jpeg"):
            i = SRC.index(f"def {wrapper}(")
            self.assertIn("_downscale_page_jpeg", SRC[i:i + 300])

    def test_the_base_layer_is_written_for_every_page(self):
        """The thumbnail identifies a FILE, so page one is the whole job. The
        base layer sits under whatever sheet he is on, so a set is only covered
        when every sheet has one.

        INDENTATION IS THE ASSERTION, not proximity. The thumbnail's
        `if page_number == 1:` sits directly above this line, so a
        preceding-window scan finds it and proves nothing. What distinguishes
        the two is nesting: the guarded upload is indented inside the `if`, the
        unguarded one is at the function's own level.
        """
        def indent_of(needle):
            line = next(ln for ln in SRC.splitlines() if needle in ln)
            return len(line) - len(line.lstrip())

        base = indent_of("page_base_r2_key = await _upload_page_base_to_r2")
        thumb = indent_of("page_thumb_r2_key = await _upload_page_thumb_to_r2")
        guard = indent_of("if page_number == 1:")
        self.assertEqual(base, guard, "the base upload is NOT inside the guard")
        self.assertGreater(thumb, guard, "the thumb upload IS inside the guard")

    def test_it_produces_a_2048px_image(self):
        import server
        from PIL import Image
        src = TheThumbnailIsMadeFromThePageNotThePdf._page_jpeg(4000, 3000)
        out = server._make_page_base_jpeg(src)
        self.assertIsNotNone(out)
        self.assertEqual(max(Image.open(io.BytesIO(out)).size), 2048)

    def test_the_reader_is_the_same_ladder(self):
        i = SRC.index("async def _fetch_page_base")
        body = SRC[i:SRC.index("async def _fetch_page_thumb")]
        self.assertIn("page_base_r2_key", body)
        self.assertIn("_fetch_page_jpeg", body)
        self.assertIn("_make_page_base_jpeg", body)
        self.assertNotIn("_upload_to_r2", body)

    def test_the_endpoint_is_scoped_and_404s(self):
        i = SRC.index('"/projects/{project_id}/files/{file_id}/pages/{page_number}/base"')
        head = SRC[i:i + 200]
        self.assertIn("require_project_access", head)
        j = SRC.index("async def get_project_file_page_base")
        body = SRC[j:j + 2400]
        self.assertIn('"project_id": project_id', body)
        self.assertIn("status_code=404", body)
        self.assertIn("private, max-age=", body)

    def test_a_page_number_below_one_is_refused(self):
        j = SRC.index("async def get_project_file_page_base")
        self.assertIn("if page_number < 1:", SRC[j:j + 600])


if __name__ == "__main__":
    unittest.main(verbosity=2)
