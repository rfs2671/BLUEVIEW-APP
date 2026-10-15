"""Render the sample progress report (the 588 fixture) to a PDF and PNGs.

    python scripts/render_report_sample.py [out_dir]

Writes progress_report_588.pdf and progress_report_588-<page>.png (needs
pdftoppm for the PNGs) into out_dir (default docs/samples). The photos are
drawn here -- the fixture's photos are not real photos -- each marked
"SAMPLE".
"""

from __future__ import annotations

import base64
import io
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
from tests import report_588 as F  # noqa: E402


def _drawn(caption: str, seed: int) -> str:
    """A drawn stand-in for a jobsite photo: a floor, studs, a slab edge."""
    from PIL import Image, ImageDraw
    w, h = 900, 600
    im = Image.new("RGB", (w, h), (196, 204, 212))
    d = ImageDraw.Draw(im)
    d.rectangle([0, int(h * 0.72), w, h], fill=(150, 146, 138))              # slab
    d.rectangle([0, 0, w, int(h * 0.08)], fill=(120, 124, 130))              # deck above
    step = 40 + (seed % 4) * 8
    for x in range(30 + seed % 30, w, step):                                 # studs
        d.rectangle([x, int(h * 0.08), x + 9, int(h * 0.72)], fill=(168, 172, 178))
    d.rectangle([0, int(h * 0.08), w, int(h * 0.08) + 10], fill=(150, 154, 160))   # top track
    d.rectangle([0, int(h * 0.72) - 10, w, int(h * 0.72)], fill=(150, 154, 160))  # bottom track
    d.rectangle([w - 190, 12, w - 12, 52], fill=(200, 16, 46))
    d.text((w - 176, 24), "SAMPLE", fill=(255, 255, 255))
    d.text((16, h - 30), caption[:80], fill=(40, 40, 40))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def main(out_dir: str) -> None:
    import weasyprint
    os.makedirs(out_dir, exist_ok=True)
    rep = F.report()
    images = {p["key"]: _drawn(p["caption"], i) for i, p in enumerate(rep["photos"])}
    html = P.render_html([rep], gc=F.GC, title=P.title_for([rep]), now=F.NOW, images=images)
    pdf = os.path.join(out_dir, "progress_report_588.pdf")
    weasyprint.HTML(string=html).write_pdf(pdf)
    with open(os.path.join(out_dir, "progress_report_588.whatsapp.txt"), "w", encoding="utf-8") as f:
        f.write(P.whatsapp_message(rep) + "\n")
    if shutil.which("pdftoppm"):
        subprocess.run(["pdftoppm", "-png", "-r", "60", pdf,
                        os.path.join(out_dir, "progress_report_588")], check=True)
    print(pdf)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(HERE)),
                                                            "docs", "samples"))
