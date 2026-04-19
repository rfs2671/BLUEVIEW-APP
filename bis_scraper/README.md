# Blueview BIS Scraper

Standalone worker that does three things on every tick, in order:

1. **Property Profile scrape** — loads the NYC DOB BIS Property Profile page for every project with `track_dob_status=True` and a valid `nyc_bin`, extracts the violations + complaints tables, diffs them against `db.dob_logs`, inserts new records, and fires email alerts through the shared 24-hour throttle. **On the same page** it also reads the active-permit rows to extract the GC license number and stores it on the company document (if none is set).

2. **License insurance fetch** — for every unique license number surfaced in Step 1, hits the BIS Licensing portal (throttled to once per 24 h per license number — not per project, since many projects share the same GC) and parses the insurance table.

3. **Insurance upsert** — writes the insurance records onto every company that has that license number, using the exact schema manual entry writes to (`gc_insurance_records` array with `{insurance_type, carrier_name, policy_number, effective_date, expiration_date, is_current, source}`). The existing Settings / Insurance UI reads this with no frontend changes. Manual entries (`source='manual_entry'`) are never overwritten — the scraper only fills in or refreshes entries it owns.

**This runs as a separate Railway service.** Don't deploy it to the backend service — it needs a Chromium runtime the FastAPI server doesn't include and can't share.

## Why a separate service

- BIS is protected by Akamai. A plain `httpx` GET gets a 403. A real browser with cookies doesn't. Playwright + Chromium is the simplest way to pass the gate.
- Chromium is a heavy runtime (~300 MB on disk, ~200 MB RAM even idle). Coupling it to the API server slows every deploy and costs memory on every request handler.
- Scraping long-tails. A 30-second BIS page load blocking the API event loop would be awful. Giving it its own process and a small APScheduler removes the coupling.

## Config

Environment variables (set in Railway → Service → Variables):

| Name | Required | Description |
|---|---|---|
| `MONGO_URL` | ✅ | Same connection string as the API backend |
| `DB_NAME` | ✅ | Same database name as the API backend |
| `RESEND_API_KEY` | ◦ | If missing, critical alerts log-only (no email). Same key as backend |
| `WEBSHARE_PROXY_URL` | ◦ | Proxy URL `http://user:pass@host:port`. Falls back to direct connection if unset |
| `BIS_SCAN_INTERVAL_MIN` | ◦ | Scan cadence in minutes. Default `60` |
| `BIS_SCAN_CONCURRENCY` | ◦ | Parallel BINs per scan. Default `2`. Keep low — BIS throttles |
| `BIS_DEBUG_HTML` | ◦ | `1` to log the first 400 chars of the page when no table is found. Turn on for initial bring-up, off in steady state |

## Deploy (Railway)

1. Create a new service in the same Railway project as the backend.
2. **Root directory:** `bis_scraper/`
3. **Builder:** Dockerfile (auto-detected from `bis_scraper/Dockerfile`).
4. Copy `MONGO_URL`, `DB_NAME`, `RESEND_API_KEY` from the backend service's variables.
5. Optionally set `WEBSHARE_PROXY_URL` and knob envs.
6. Deploy. No HTTP port is exposed — this is a worker, not a server.

Verify from the Railway log tab. On boot you should see:

```
[bis_scraper] INFO bis_scraper started, interval=60m, concurrency=2, proxy=off
[bis_scraper] INFO BIS scan starting: 3 projects proxy=off concurrency=2
[bis_scraper] INFO BIN 1047819 project=638 Lafayette: found 2 violation rows, 0 complaint rows
[bis_scraper] INFO BIS scan complete: processed=3 failed=0 v_new=2 v_crit=0 c_new=0 c_crit=0 elapsed=43.2s
```

## Coexistence with the backend

The backend has its own `dob_nightly_scan` (every 30 min) and `dob_311_fast_poll` (every 30 min) writing to `dob_logs`. The BIS scraper writes to the same collection and the same schema. Dedupe is layered:

- The Mongo `raw_dob_id` unique index catches exact duplicates at write time.
- The scraper's per-record `find_one` additionally looks at `violation_number` / `complaint_number` to catch rows the backend's httpx sync wrote under a different `raw_dob_id` format. This means running BIS after the backend sync can only ever ADD new information — it won't duplicate what's already there.
- Critical-alert emails share a 24-hour throttle across all sources, keyed in `system_config` under `dob_alert_sent:{project_id}:{raw_dob_id}`. Both this scraper and the backend read/write that same key shape.

## Local smoke test

```bash
cd bis_scraper/
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

export MONGO_URL='mongodb+srv://…'
export DB_NAME='blueview'
export BIS_SCAN_INTERVAL_MIN=60
export BIS_SCAN_CONCURRENCY=1
export BIS_DEBUG_HTML=1

python bis_scraper.py
```

First run kicks off in ~30 seconds. Tail the logs; on the first scan you'll see the full violations/complaints enumerated per BIN.

## Proxy notes

Webshare residential proxies work out of the box. Set `WEBSHARE_PROXY_URL` to the rotating endpoint they give you. If you get `ERR_PROXY_CONNECTION_FAILED` in logs, the proxy creds are wrong — fall back to direct by unsetting the var.

If BIS starts hard-blocking on your Railway IP (rare but possible at higher cadence), enabling the proxy is the knob to turn first.
