"""pip succeeded, the tests passed, the deploy went green, the reader was dead.

`rapidocr-onnxruntime` installed cleanly on Railway. It imports `cv2`, `cv2`
needs `libGL.so.1`, and the container carried none. The FIRST fix for this went
into `nixpacks.toml`, because that is what the README said built the image. It
deployed green and changed nothing — Railway builds from the `Dockerfile`, and
nothing has ever read `nixpacks.toml`:

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

  1. The DOCKERFILE declares the system libraries its Python dependencies link
     against, because that is the file the build reads. A wheel that installs
     is not a wheel that imports, and a config nothing reads is not a fix.
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
    """THE DOCKERFILE, because that is what Railway actually builds.

    The first fix for the missing libGL went into `nixpacks.toml` — a file
    that sat in this repo for months, was read by nothing, and that the README
    described as the production build path. It deployed green and changed
    nothing: `libGL.so.1` was still missing and the reader was still dead. A
    test asserting that file's contents would have passed the whole time.
    """

    def apt_packages(self):
        """Every package name the Dockerfile apt-get installs.

        Continuations are joined first, so a package added on its own `\\` line
        — which is how every one of them is written here — is seen. A PINNED
        package (`poppler-utils=25.03.0-5+deb13u4`) is seen by its name: this
        used to skip any token with `=`, so pinning a package made it vanish
        from the set and read as uninstalled."""
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        joined = re.sub(r"\\\s*\n", " ", text)
        got = set()
        for line in joined.splitlines():
            if "apt-get install" not in line:
                continue
            tail = line.split("apt-get install", 1)[1]
            tail = re.split(r"&&|\|\||;", tail)[0]
            for tok in tail.split():
                if tok and not tok.startswith("-"):
                    got.add(tok.split("=", 1)[0])
        return got

    def apt_pins(self):
        """package -> pinned version, for every `name=version` installed."""
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        return dict(re.findall(r"^\s*([a-z0-9][a-z0-9.+-]*)=(\S+)\s*\\?\s*$",
                               text, re.M))

    def test_the_renderer_is_pinned_to_the_one_that_read_the_corpus(self):
        # pdftoppm 25.03.0 measured from deployment 6eea5ba4's startup log;
        # the Debian revision inferred. A pin break means: re-run the
        # ocr-repro harness before bumping (see the Dockerfile).
        self.assertEqual(self.apt_pins().get("poppler-utils"), "25.03.0-5+deb13u4")

    def test_the_base_image_is_pinned_by_digest(self):
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$")

    def test_the_ocr_runtime_is_pinned(self):
        # Dependencies of dependencies, so CONSTRAINED rather than required:
        # a line in constraints.txt pins a package only if requirements.txt
        # already pulls it in. requirements.txt stays free of opencv (see
        # test_photo_enhance.NoThirdPartyImageDependency).
        cons = (REPO / "backend" / "constraints.txt").read_text(encoding="utf-8")
        for pin in ("onnxruntime==1.30.0", "opencv-python==4.14.0.94",
                    "pypdfium2==5.13.0"):
            self.assertIn(pin, cons)
        req = (REPO / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("rapidocr-onnxruntime==1.4.4", req)

    def test_the_constraints_are_actually_applied(self):
        # A constraints file nothing passes to pip is decoration: the image
        # must COPY it before the install and hand it to pip with -c.
        text = (REPO / "Dockerfile").read_text(encoding="utf-8")
        copy = text.index("COPY backend/constraints.txt")
        install = text.index("pip install --no-cache-dir -r requirements.txt -c backend/constraints.txt")
        self.assertLess(copy, install)

    def test_opencv_s_system_libraries_are_installed(self):
        # The wheel links libGL.so.1 and libglib-2.0.so.0 and bundles neither.
        # Verified on the container 2026-09-17: with libgl1 extracted onto
        # LD_LIBRARY_PATH, `import cv2` succeeded, RapidOCR constructed, and it
        # read PTAC-1 / 21 / PTH093K / 14,000 off a rendered row.
        pkgs = self.apt_packages()
        self.assertIn("libgl1", pkgs)
        self.assertIn("libglib2.0-0", pkgs)

    def test_poppler_is_still_there(self):
        # pdftoppm and pdfinfo. _check_poppler refuses to start the index
        # worker without both, and the schedule crops are rendered by them.
        self.assertIn("poppler-utils", self.apt_packages())

    def test_the_ocr_dependency_is_still_the_one_that_needs_them(self):
        req = (REPO / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("rapidocr-onnxruntime", req)

    def test_no_second_build_file_sits_beside_the_dockerfile(self):
        # A build config nothing reads is worse than none: it is where a fix
        # goes to have no effect. Railway prefers the Dockerfile whenever the
        # repo has one, so any of these is decoration that reads as authority.
        for dead in ("nixpacks.toml", "railpack.json", "project.toml"):
            with self.subTest(file=dead):
                self.assertFalse(
                    (REPO / dead).exists(),
                    f"{dead} is not read by the build; a system library added "
                    f"to it changes nothing while looking like a fix")

    def test_the_readme_does_not_send_the_next_person_to_the_wrong_file(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("Railway builds from the `Dockerfile`", readme)
        self.assertNotIn("There is no Dockerfile path in production", readme)


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
