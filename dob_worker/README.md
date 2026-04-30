# dob_worker — local Docker filing agent

The dob_worker process is the local-laptop counterpart to the
Railway-hosted backend. It pulls filing jobs from Railway Redis and
executes them via Playwright using each GC's stored DOB NOW
credentials. It also continues to run the legacy BIS scraping that
the previous bis_scraper container handled — that behavior is
preserved verbatim under `handlers/bis_scrape.py`.

## Operator pre-deploy checklist (MR.5)

Run these in order. Each line has a verification step you can use
to confirm it landed before moving on.

```
[ ] 1. Provision Railway Redis add-on
       Dashboard → Project → Add → Redis. Copy the
       REDIS_URL connection string.
       Verify: redis-cli -u "$REDIS_URL" ping  → "PONG"

[ ] 2. Set WORKER_SECRET on the Railway BACKEND service
       Generate: openssl rand -hex 32
       Dashboard → Backend service → Variables → add WORKER_SECRET
       Verify: /api/internal/agent-heartbeat returns 401 without
       the matching header, 200 with it.

[ ] 3. Create host directories for bind-mounts
         mkdir -p ~/.levelog/agent-keys ~/.levelog/agent-storage
         chmod 0700 ~/.levelog/agent-keys
       Verify: ls -la ~/.levelog/

[ ] 4. Generate the RSA-4096 keypair
         docker compose run --rm dob_worker python scripts/generate_keypair.py
       Verify: file at ~/.levelog/agent-keys/agent.key exists,
       chmod 0400; public key was printed to stdout.
       Save the public key — paste into MR.10's onboarding UI when
       it ships.

[ ] 5. Copy + fill .env.local
         cp dob_worker/.env.local.example dob_worker/.env.local
         # edit with REDIS_URL, WORKER_SECRET, WORKER_ID,
         # MONGO_URL (for bis_scrape passthrough), etc.

[ ] 6. Set host bind-mount path env vars
       Linux / macOS:
         export LEVELOG_AGENT_KEYS_DIR=$HOME/.levelog/agent-keys
         export LEVELOG_AGENT_STORAGE_DIR=$HOME/.levelog/agent-storage
       Windows (PowerShell):
         $env:LEVELOG_AGENT_KEYS_DIR = "$env:USERPROFILE\.levelog\agent-keys"
         $env:LEVELOG_AGENT_STORAGE_DIR = "$env:USERPROFILE\.levelog\agent-storage"
       Verify: docker compose config | grep -A1 volumes
       (paths should resolve to absolute, not literal ${...})

[ ] 7. Update the existing bis_scraper Railway service Root Directory
       The Railway service was deploying from bis_scraper/. After
       this commit, the source directory is dob_worker/.
       Dashboard → bis_scraper service → Settings → Root Directory
       → change from `bis_scraper/` to `dob_worker/`.
       (You can also rename the service itself to dob_worker for
       clarity — optional.)
       Verify: trigger a redeploy; Build logs reference dob_worker/.
       CRITICAL: do this BEFORE merging the rename PR or the
       Railway deploy will fail.

[ ] 8. Build and start the local container
         docker compose up -d --build dob_worker
       Verify: docker compose logs -f dob_worker shows:
         [dob_worker] booting worker_id=...
         bis_scraper started, interval=60m, ...

[ ] 9. (OPTIONAL v1) install + configure cloudflared
       v1 is outbound-only; skipping cloudflared just means the
       worker posts from the operator's residential IP directly.
       Skip on first deploy; revisit if Akamai starts challenging.

         cloudflared login
         cloudflared tunnel create agent-tunnel-1
         cp cloudflared/config.yml.example cloudflared/config.yml
         # paste tunnel UUID from credentials.json into config.yml
       Then uncomment the cloudflared service in docker-compose.yml.
```

## Architecture

```
                    Railway (cloud)                 Operator's laptop
                    ────────────────                ──────────────────
                                                        Docker
   ┌────────────┐                                   ┌─────────────────┐
   │ Backend    │  ─enqueue→  ┌────────┐  ─poll→    │ dob_worker      │
   │ (FastAPI)  │              │ Redis  │             │  • orchestrator │
   │            │              │ queue  │             │  • handlers/    │
   │            │  ←/internal─ │        │             │  • lib/         │
   │            │  ←─ job-result, heartbeat ────       │                 │
   │            │  (X-Worker-Secret)                   └─────────────────┘
   │            │                                          ↕ bind-mount
   │            │                                       ~/.levelog/
   │            │                                         agent-keys/
   └────────────┘                                         agent-storage/
```

### Handler dispatch

`dob_worker.py` boots three concurrent asyncio tasks:

1. **Heartbeat** (`lib/heartbeat.py`) — POSTs state every 60s to
   `/api/internal/agent-heartbeat`. Backend's heartbeat-watchdog
   flags workers as degraded after 30 min absence.
2. **Queue dispatch** (`lib/queue_client.py`) — Redis BRPOP loop;
   routes by `job.type` to the appropriate `handlers/` module.
3. **bis_scrape periodic scheduler** — the original
   `bis_scraper.py` loop, preserved verbatim. Runs alongside the
   queue dispatch.

### Crypto

Hybrid encryption: cloud-side encrypt path (MR.10) wraps a per-
payload AES-256-GCM key with the operator's RSA-4096 public key.
Worker decrypts via `lib/crypto.py` using the bind-mounted private
key at `/keys/agent.key` (read-only inside the container).

Threat model:
- **Cloud DB compromise alone**: ciphertext useless without the
  private key.
- **Worker laptop compromise alone**: private key useful only with
  cloud DB access.
- **Both together**: breach. v2 hardens via OS-keychain integration.

## Existing bis_scrape behavior preserved

The existing periodic BIS scraping (every 60 min by default) runs
unchanged. The only structural change: the file moved from
`bis_scraper/bis_scraper.py` to `dob_worker/handlers/bis_scrape.py`,
with a 30-line `handle()` wrapper at the bottom for queue dispatch.
The scrape's data tags (`source: "bis_scraper"` in `dob_logs`,
`gc_license_source: "bis_scraper"` on companies) are PRESERVED
verbatim — never renamed retroactively. Existing
`/api/debug/bis-scraper-state` endpoint continues to filter on
those tags and return the same data.

## Testing

```
cd dob_worker/
python -m unittest discover -s tests
```

Six test files cover:
- `test_crypto.py` — encrypt/decrypt round-trip + tampering rejection
- `test_circuit_breaker.py` — trip threshold + recovery + per-job-type isolation
- `test_heartbeat.py` — snapshot shape + retry on 5xx
- `test_queue_client.py` — BRPOP loop + claim flow (200 / 409 / unknown)
- `test_browser_context.py` — per-GC storage_state isolation + rotation
- `test_dispatcher.py` — job_type → handler routing, breaker-open drop, mode-gate refuse

Backend smoke for the internal endpoints lives in
`backend/tests/test_internal_endpoints.py`.

## What's NOT in MR.5

- Live filing — `handlers/dob_now_filing.py` is a stub returning
  `not_implemented`. Real implementation lands in MR.6 alongside
  the credentials data model and audit log.
- Cloud-side encrypt path — ships with MR.10's onboarding UI.
- Operator UI for triggering filings — MR.7.
- Email notifications for filing reps — MR.9.
- Status polling for DOB approval — MR.8.

## Legacy reference (preserved from the original bis_scraper README)

The historical Railway deployment instructions, env-var dictionary,
and proxy notes for the BIS scraping code path are unchanged from
the previous bis_scraper/README.md. Run those steps under
`dob_worker/` instead of `bis_scraper/` (Root Directory). All
existing env vars are still honored: MONGO_URL, DB_NAME,
RESEND_API_KEY, WEBSHARE_PROXY_URL, BIS_SCAN_INTERVAL_MIN,
BIS_SCAN_CONCURRENCY, BIS_DEBUG_HTML.

## Reference

Architecture spec: `~/.claude/plans/permit-renewal-v3.md` §2 +
§14 (locked 2026-04-29).
