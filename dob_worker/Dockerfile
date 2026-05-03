# Playwright-official Python image: ships Chromium + all OS deps (libnss, etc.)
# preinstalled. If you roll your own base you'll fight chromium deps for hours.
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

WORKDIR /app

# Xvfb lets us run Chrome non-headless inside a virtual display.
# Headless Chromium (especially the chromium-headless-shell variant newer
# Playwright versions pull) has fingerprint signals Akamai Bot Manager
# flags. Non-headless real Chrome behind Xvfb looks to the target site
# exactly like a real user's Chrome window, and beats most
# fingerprint-based bot defenses.
#
# MR.13: in addition to Xvfb, we install google-chrome-stable so the
# dob_now_filing handler can use Playwright's `channel="chrome"` to
# launch the real Chrome binary instead of bundled
# playwright-chromium. Bundled Chromium has a JA3 TLS fingerprint
# Akamai's threat-intel feeds know about; real Chrome does not.
# See docs/architecture/akamai-bypass-decision.md.
RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb wget gnupg ca-certificates \
 && wget -q -O /tmp/google-chrome.gpg https://dl.google.com/linux/linux_signing_key.pub \
 && gpg --dearmor < /tmp/google-chrome.gpg > /usr/share/keyrings/google-chrome.gpg \
 && rm /tmp/google-chrome.gpg \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends google-chrome-stable \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first so Docker layer cache survives source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bundled Chromium is still installed from the playwright base image —
# bis_scrape.py uses it for the legacy BIS site (no Akamai). The
# dob_now_filing handler uses real Chrome via channel="chrome"
# (the apt google-chrome-stable above).
RUN python -m playwright install --with-deps chromium

# MR.5: copy the full restructured worker tree.
# - dob_worker.py: orchestrator (queue + heartbeat + bis_scrape sched)
# - handlers/: per-job-type modules (bis_scrape preserved verbatim,
#              dob_now_filing stub for MR.6+)
# - lib/: shared infrastructure (queue, crypto, browser_context,
#         heartbeat, circuit_breaker)
# - scripts/: operational utilities (generate_keypair.py)
COPY dob_worker.py entrypoint.sh ./
COPY handlers/ ./handlers/
COPY lib/ ./lib/
COPY scripts/ ./scripts/
RUN chmod +x /app/entrypoint.sh

# No HTTP port — this is a worker process.
ENV PYTHONUNBUFFERED=1

# entrypoint.sh starts Xvfb on :99, exports DISPLAY, then runs Python.
# We do this manually instead of via xvfb-run because xvfb-run's
# stdin/xauth handling hangs in some Docker setups.
CMD ["/app/entrypoint.sh"]
