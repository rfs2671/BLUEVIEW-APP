# ── THE OCR STACK IS PINNED, AND A PIN THAT BREAKS IS A SIGNAL ─────────────
#
# lib/plan_ocr.py reads the schedules a CAD export drew as curves: pdftoppm
# renders each grid twice, RapidOCR reads both, and a cell the two reads
# disagree on is stored as "(readings disagree)". WHICH cells disagree, and
# what the others say, depends on the renderer and the OCR runtime. Every
# version below was unpinned, so each rebuild could change what a re-index
# stores with no code change at all.
#
# Pinned to the stack that OCR'd 588 Boyland (deployment 6eea5ba4, built from
# f8fd7cfa, 2026-09-20). Reproduced offline in a container at these versions:
# 27 of 30 grids come out exactly as production stored them, contested
# readings included; the other 3 differ by one contested cell's text.
#
#   base image     python:3.12-slim, the index digest below (amd64
#                  sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b)
#   poppler-utils  25.03.0-5+deb13u4 (pdftoppm 25.03.0 is MEASURED from that
#                  deployment's startup log; the Debian revision is inferred)
#   onnxruntime, opencv-python, pypdfium2   pinned in backend/constraints.txt
#                  (they are dependencies of dependencies, so they are
#                  constrained, not required; see that file)
#
# ONLY THESE ARE PINNED. `apt-get update` still brings every other package's
# security updates; nothing else is frozen.
#
# WHEN A PIN BREAKS -- Debian replaces poppler-utils 25.03.0-5+deb13u4 on
# deb.debian.org when it ships the next security update, and the build then
# fails on this line -- DO NOT JUST BUMP THE VERSION. Re-run the ocr-repro
# harness at the new version first (container build + 30-grid comparison;
# see the PR that added this block), and bump only if the 27 faithful grids
# still reproduce. A renderer that reads a cell differently is a change to
# stored data, and it should arrive as one.
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
    poppler-utils=25.03.0-5+deb13u4 \
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
