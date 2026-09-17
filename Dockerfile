FROM python:3.12-slim
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
RUN pip install --no-cache-dir -r requirements.txt
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
