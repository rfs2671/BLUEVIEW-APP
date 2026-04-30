#!/bin/sh
# Start Xvfb in the background on display :99. `-ac` disables access
# control so Chromium can attach without xauth gymnastics. `+extension
# RANDR` is required by modern Chromium or it crashes on startup.
Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR -nolisten tcp &
XVFB_PID=$!

# Wait briefly for Xvfb to be ready. 2s is plenty on any modern host.
sleep 2

export DISPLAY=:99

# MR.5: dob_worker.py is the new orchestrator. It boots three
# concurrent asyncio tasks:
#   1. Heartbeat loop (60s POST to /api/internal/agent-heartbeat)
#   2. Queue dispatch loop (Redis BRPOP → handlers/<type>.handle())
#   3. The legacy bis_scrape periodic scheduler (preserved verbatim)
#
# When the orchestrator exits, tear down Xvfb so the container dies
# cleanly and Docker's restart policy can bring us back up.
python -u dob_worker.py
EXIT_CODE=$?

kill "$XVFB_PID" 2>/dev/null
exit $EXIT_CODE
