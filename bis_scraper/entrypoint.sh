#!/bin/sh
# Start Xvfb in the background on display :99. `-ac` disables access
# control so Chromium can attach without xauth gymnastics. `+extension
# RANDR` is required by modern Chromium or it crashes on startup.
Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR -nolisten tcp &
XVFB_PID=$!

# Wait briefly for Xvfb to be ready. 2s is plenty on any modern host.
sleep 2

export DISPLAY=:99

# Run the scraper. When it exits, tear down Xvfb so the container dies
# cleanly and Docker's restart policy can bring us back up.
python -u bis_scraper.py
EXIT_CODE=$?

kill "$XVFB_PID" 2>/dev/null
exit $EXIT_CODE
