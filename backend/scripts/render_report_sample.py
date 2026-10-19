"""Render the sample progress report (the 588 fixture) to PDFs and PNGs.

    python scripts/render_report_sample.py [out_dir]

Writes, into out_dir (default docs/samples):
  progress_report_588.pdf            with a confirmed schedule (the fixture's own)
  progress_report_588_no_schedule.pdf  what a job with no schedule gets
  *-<page>.png                        pages of the first (needs pdftoppm)
  progress_report_588.whatsapp.txt    the DM text

The data is the tests' fixture (tests/report_588.py), NOT production records.
There are no real jobsite photographs in the repository, so none are drawn or
generated: the Visual progress page is simply absent, as it is in production
when no screened daily-log photo exists.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET", "sample-only")
os.environ.setdefault("APP_BASE_URL", "https://app.levelog.com")

from lib import progress_report as P  # noqa: E402
from lib import progress_report_render as RR  # noqa: E402
from tests import report_588 as F  # noqa: E402


def _pdf(rep, path):
    import weasyprint
    rep["photos"] = []                       # no real photographs exist for the fixture
    html = RR.render_html([rep], gc=F.GC, title=RR.title_for([rep]), now=F.NOW, images={}, report_id="sample588-0")
    doc = weasyprint.HTML(string=html).write_pdf(path)
    return doc


def main(out):
    os.makedirs(out, exist_ok=True)
    main_pdf = os.path.join(out, "progress_report_588.pdf")
    _pdf(F.report(schedule=True), main_pdf)
    _pdf(F.report(), os.path.join(out, "progress_report_588_no_schedule.pdf"))
    with open(os.path.join(out, "progress_report_588.whatsapp.txt"), "w", encoding="utf-8") as f:
        f.write(P.whatsapp_message(F.report(schedule=True)) + "\n")
    if shutil.which("pdftoppm"):
        for old in os.listdir(out):
            if old.startswith("progress_report_588-") and old.endswith(".png"):
                os.remove(os.path.join(out, old))
        subprocess.run(["pdftoppm", "-r", "70", "-png", main_pdf, os.path.join(out, "progress_report_588")], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "..", "docs", "samples"))
