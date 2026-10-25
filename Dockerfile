# ── THE OCR STACK: WHAT IS PINNED, AND WHY poppler-utils NO LONGER IS ──────
#
# lib/plan_ocr.py reads the schedules a CAD export drew as curves: pdftoppm
# renders each grid twice, RapidOCR reads both, and a cell the two reads
# disagree on is stored as "(readings disagree)". WHICH cells disagree, and
# what the others say, depends on the renderer and the OCR runtime.
#
# Measured against the stack that OCR'd 588 Boyland (deployment 6eea5ba4, built
# from f8fd7cfa, 2026-09-20): 27 of 30 grids reproduce exactly at these versions.
#
#   base image     python:3.12-slim, the index digest below (amd64
#                  sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b)
#   onnxruntime, opencv-python, pypdfium2   pinned in backend/constraints.txt
#                  (they are dependencies of dependencies, so they are
#                  constrained, not required; see that file)
#
# poppler-utils IS NOT VERSION-PINNED (operator ruling, 2026-10-21). It was
# pinned to 25.03.0-5+deb13u4, and an exact apt version is a build that fails
# on the day Debian replaces it on the mirror -- every deploy, not just an OCR
# re-index, for a package whose next revision is normally a security fix. The
# trade is stated: a new Debian revision can change what a RE-INDEX stores for
# a contested cell. It stays visible: the boot log prints the measured
# renderer ("POPPLER CHECK: OK -- ... pdftoppm version ..."), so a change in
# pdftoppm is one line to compare against 25.03.0, and the ocr-repro harness
# (container build + 30-grid comparison; see the PR that pinned it) is the way
# to judge one before re-indexing.
#
# `apt-get update` brings every package's security updates; only the base
# image digest and the constraints above are frozen.
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
# ── SYSTEM LIBRARIES THE PYTHON WHEELS LINK AGAINST ────────────────────────
#
# libgl1 is here for opencv, which rapidocr-onnxruntime imports to do anything
# at all — lib/plan_ocr.py reads the schedules a CAD export flattened to
# curves. The wheel links libGL.so.1 and bundles it no more than it bundles
# glib. Without it `import cv2` raises ImportError on a container where pip
# reported success, every test passed and the deploy went green, and the
# indexer then writes zero schedule records for the sheets that reader exists
# to read — silently, because an absent engine is a state plan_ocr treats as
# normal.
#
# THIS FILE IS THE ONLY PLACE A SYSTEM LIBRARY GOES. Railway builds from this
# Dockerfile because the repo has one. A nixpacks.toml sat beside it for
# months, was read by nothing, and the README said it was the build path —
# so the first fix for the missing libGL went into that file and changed
# nothing at all.
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libgobject-2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    libharfbuzz0b \
    libffi-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
COPY backend/constraints.txt ./backend/constraints.txt
RUN pip install --no-cache-dir -r requirements.txt -c backend/constraints.txt
# Install Playwright system deps manually (Debian Trixie renames some Ubuntu font packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-unifont \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*
# Now install just the Chromium browser binary (deps already satisfied above)
RUN playwright install chromium
COPY backend/ ./backend/
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8001"]
