"""pip succeeded, the tests passed, the deploy went green, the reader was dead.

`rapidocr-onnxruntime` installed cleanly on Railway. It imports `cv2`, `cv2`
needs `libGL.so.1`, and the container carried none:

    $ railway ssh "python -c 'from lib import plan_ocr; print(plan_ocr.available())'"
    available: False
    why: ImportError: libGL.so.1: cannot open shared object file

`plan_ocr` is deliberately written to treat an absent engine as a NORMAL
state — a container without it indexes exactly as it did before. That is the
right design and it is precisely why nothing failed loudly. A re-index would
have run to completion, reported every page done, and written ZERO schedule
records for the sheets the reader exists to read. The only way to find out was
an SSH session, and the next thing scheduled was the single re-index before
the eval.

THE TWO THINGS THIS FILE HOLDS

  1. The runtime declares the system libraries its Python dependencies link
     against. A wheel that installs is not a wheel that imports.
  2. /health NAMES a reader that cannot load, without moving `status` and
     without loading 15 MB of model weights to find out.
"""

import inspect
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "smoke_test")
os.environ.setdefault("JWT_SECRET", "smoke_test_secret")

from lib import plan_ocr  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


class TheRuntimeCarriesWhatTheWheelsLinkAgainst(unittest.TestCase):

    def nixpkgs(self):
        text = (REPO / "nixpacks.toml").read_text(encoding="utf-8")
        line = [l for l in text.splitlines() if l.strip().startswith("nixPkgs")]
        self.assertTrue(line, "nixpacks.toml declares no nixPkgs")
        return set(re.findall(r'"([^"]+)"', line[0]))

    def test_opencv_s_system_libraries_are_declared(self):
        # The wheel links libGL.so.1 and libglib-2.0.so.0 and bundles neither.
        pkgs = self.nixpkgs()
        self.assertIn("libGL", pkgs)
        self.assertIn("glib", pkgs)

    def test_poppler_is_still_there(self):
        # pdftoppm and pdfinfo. _check_poppler refuses to start the index
        # worker without both, and the schedule crops are rendered by them.
        self.assertIn("poppler_utils", self.nixpkgs())

    def test_the_ocr_dependency_is_still_the_one_that_needs_them(self):
        req = (REPO / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("rapidocr-onnxruntime", req)


class ProbingCostsNothing(unittest.TestCase):

    def test_the_probe_does_not_build_the_engine(self):
        # /health is what the platform polls. A probe that loads 15 MB of ONNX
        # weights on its first call is a restart loop, which is the one thing
        # that endpoint is written never to cause.
        src = inspect.getsource(plan_ocr.probe)
        self.assertNotIn("RapidOCR(", src)
        self.assertNotIn("_load(", src)

    def test_the_probe_reports_the_import_that_actually_fails(self):
        src = inspect.getsource(plan_ocr.probe)
        self.assertIn("import rapidocr_onnxruntime", src)

    def test_it_answers_a_pair_and_says_why_when_it_cannot(self):
        saved = plan_ocr._probe
        try:
            plan_ocr._probe = (False, "ImportError: libGL.so.1: cannot open ...")
            ok, why = plan_ocr.probe()
            self.assertFalse(ok)
            self.assertIn("libGL", why)
        finally:
            plan_ocr._probe = saved

    def test_a_working_environment_reports_no_detail(self):
        saved = plan_ocr._probe
        try:
            plan_ocr._probe = None
            ok, why = plan_ocr.probe()
            if ok:
                self.assertEqual(why, "")
        finally:
            plan_ocr._probe = saved


class HealthNamesItWithoutRestartingOverIt(unittest.TestCase):

    def setUp(self):
        import server
        self.src = inspect.getsource(server.health_check)

    def test_health_reports_the_reader(self):
        self.assertIn('"plan_ocr"', self.src)
        self.assertIn("plan_ocr.probe()", self.src)

    def test_it_says_what_an_unavailable_reader_costs(self):
        self.assertIn('"effect"', self.src)
        self.assertIn("no schedule records", self.src)

    def test_it_does_not_move_status(self):
        # Same rule as failed_unique_builds: a missing system library is not
        # fixed by cycling the process, and `status` is what the platform
        # restarts on.
        i = self.src.index("_ocr_ok")
        self.assertNotIn("_status =", self.src[i:])

    def test_health_still_answers_when_the_reader_is_missing(self):
        import asyncio

        import server
        saved = plan_ocr._probe
        try:
            plan_ocr._probe = (False, "ImportError: libGL.so.1")
            got = asyncio.run(server.health_check())
            self.assertEqual(got["status"], "healthy")
            self.assertFalse(got["plan_ocr"]["importable"])
            self.assertIn("libGL", got["plan_ocr"]["detail"])
            self.assertTrue(got["plan_ocr"]["effect"])
        finally:
            plan_ocr._probe = saved

    def test_a_working_reader_carries_no_excuse(self):
        import asyncio

        import server
        saved = plan_ocr._probe
        try:
            plan_ocr._probe = (True, "")
            got = asyncio.run(server.health_check())
            self.assertTrue(got["plan_ocr"]["importable"])
            self.assertEqual(got["plan_ocr"]["detail"], "")
            self.assertEqual(got["plan_ocr"]["effect"], "")
        finally:
            plan_ocr._probe = saved


if __name__ == "__main__":
    unittest.main()
