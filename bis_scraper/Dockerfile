# Playwright-official Python image: ships Chromium + all OS deps (libnss, etc.)
# preinstalled. If you roll your own base you'll fight chromium deps for hours.
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

WORKDIR /app

# Xvfb lets us run Chromium non-headless inside a virtual display.
# Headless Chromium (especially the chromium-headless-shell variant newer
# Playwright versions pull) has fingerprint signals Akamai Bot Manager
# flags. Non-headless Chromium behind Xvfb looks to the target site
# exactly like a real user's Chrome window, and beats most
# fingerprint-based bot defenses.
RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first so Docker layer cache survives source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers are already installed in the base image, but `playwright install`
# is a no-op if they're present — safe to run.
RUN python -m playwright install --with-deps chromium

COPY bis_scraper.py entrypoint.sh ./
RUN chmod +x /app/entrypoint.sh

# No HTTP port — this is a worker process.
ENV PYTHONUNBUFFERED=1

# entrypoint.sh starts Xvfb on :99, exports DISPLAY, then runs Python.
# We do this manually instead of via xvfb-run because xvfb-run's
# stdin/xauth handling hangs in some Docker setups.
CMD ["/app/entrypoint.sh"]
