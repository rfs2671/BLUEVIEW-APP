# LeveLog — DOB Compliance Monitoring for NYC GCs

LeveLog is a **DOB compliance monitoring + notification product**
for NYC General Contractors. It polls public NYC Open Data datasets
on a per-project basis, classifies records into plain-English
signals, surfaces them in an activity feed, and emails critical
alerts. When a permit needs renewal, LeveLog tells the operator
exactly what values to type into DOB NOW; the operator files
manually.

**LeveLog never files anything.** The four-phase loop is signals →
diffing → activity feed → renewal start. See
[`docs/architecture/v1-monitoring-architecture.md`](./docs/architecture/v1-monitoring-architecture.md)
for the canonical product description.

---

## Tech stack

- **Backend**: FastAPI + MongoDB + Motor (async). Hosted on Railway.
- **Frontend**: React Native Web on Cloudflare Pages.
- **Email**: Resend.
- **Storage**: Cloudflare R2 (COI uploads, photo attachments).
- **Auth**: JWT.

There is **no worker container, no Playwright runtime, no Docker
Compose, no Redis, and no DOB NOW credential storage**. All of
those existed in the MR.5–MR.13 renewal-automation effort and were
removed across MR.14 commits 4a → 5. See
[`docs/architecture/akamai-bypass-decision.md`](./docs/architecture/akamai-bypass-decision.md)
for the historical context.

---

## Local development

### Prerequisites

- **Python 3.11+** (3.12 in production)
- **Node.js 18+**
- **MongoDB** (local container or cluster connection string)
- **npm** or **yarn**

### Git hooks (one-time, after clone)

```bash
bash scripts/install-hooks.sh
```

Sets `git config core.hooksPath .githooks`. Runs the dependency-
resolution check (`pip install --dry-run -r requirements.txt`) on
every commit that touches the requirements file — catches the
class of bug that took production down between Phase C2 and C2.1.
See [`docs/operations/runbook.md`](./docs/operations/runbook.md) §13
for the full rationale.

### Backend

```bash
cd backend

# 1. Install Python dependencies
pip install -r ../requirements.txt

# 2. Set required env vars (or put them in a .env file the runtime reads)
export MONGO_URL="mongodb://localhost:27017"
export DB_NAME="levelog_dev"
export JWT_SECRET="dev-only-not-for-production"
export RESEND_API_KEY="re_xxx"            # use a Resend test key
export NOTIFICATIONS_ENABLED=0            # keep notifications off in dev
export R2_ACCOUNT_ID="..."
export R2_ACCESS_KEY_ID="..."
export R2_SECRET_ACCESS_KEY="..."
export R2_BUCKET="..."
export NYC_SOCRATA_APP_TOKEN="..."        # optional in dev; pollers work without it
export QWEN_API_KEY=""                    # only needed if you exercise Qwen-backed features

# 3. Run the server
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

The full env-var reference (including the v2 candidates and the
deprecated vars MR.14 cleanup removed) lives in
`docs/architecture/v1-monitoring-architecture.md`.

### Frontend

```bash
cd frontend
npm install

# Point the frontend at the local backend
echo 'EXPO_PUBLIC_BACKEND_URL=http://localhost:8001' > .env

# Run for web
npm run dev    # alias for `expo start --web`
```

### Tests

Backend:

```bash
cd backend
python -m pytest tests/ -q
```

Single-file invariant pin (the architectural shape of the v1
product — fails immediately if a future commit accidentally
re-introduces a removed surface):

```bash
python -m pytest tests/test_v1_monitoring_invariants.py -v
```

Frontend (no unit tests today — the project relies on backend
tests + manual smoke). Components are validated through `npm run
dev` + the Expo Router page surface.

---

## Production deploy

**Railway only.** The backend runs from the repo root via
`Procfile`:

```
web: cd backend && python -m uvicorn server:app --host 0.0.0.0 --port $PORT
```

Railway uses nixpacks (`nixpacks.toml`) which adds `poppler-utils`
for the COI OCR path. There is no Dockerfile path in production.

The frontend deploys to Cloudflare Pages from `frontend/`.

### Required production env vars

| Variable | Purpose |
|---|---|
| `MONGO_URL` | Production Mongo cluster |
| `DB_NAME` | Database name within the cluster |
| `JWT_SECRET` | JWT signing key |
| `RESEND_API_KEY` | Outbound email |
| `NOTIFICATIONS_ENABLED` | `1` in production. Pair with `NOTIFICATIONS_KILL_SWITCH=1` for emergency halt. |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | Cloudflare R2 storage |
| `NYC_SOCRATA_APP_TOKEN` | Higher Socrata quota (recommended) |
| `QWEN_API_KEY` | Qwen LLM (only required if Qwen-backed features run) |

### Deprecated env vars (no longer read by any code path)

```
ELIGIBILITY_BYPASS_DAYS_REMAINING
BRIGHT_DATA_CDP_URL
WEBSHARE_PROXY_URL
WORKER_SECRET
REDIS_URL
MR14_SEED_WINDOW_START
MR14_SEED_WINDOW_DURATION_MIN
```

Delete these from Railway after the MR.14 commit 5 deploy.

---

## Project structure

```
.
├── backend/
│   ├── server.py                  FastAPI application (single-file architecture)
│   ├── permit_renewal.py          Renewal endpoints + 30-day-window sweep
│   ├── lib/
│   │   ├── dob_signal_classifier.py     record_type + status → signal_kind
│   │   ├── dob_signal_templates.py      signal_kind → plain-English {title, body, severity}
│   │   ├── dob_signal_notifications.py  Severity → channel routing
│   │   ├── notifications.py             send_notification + kill switch + idempotency
│   │   ├── pw2_field_mapper.py          MR.4 PW2 mapper (used by Start Renewal panel)
│   │   ├── filing_readiness.py          Pre-flight readiness check
│   │   ├── eligibility_v2.py            30-day renewal-window logic
│   │   └── ...
│   ├── scripts/                   One-shot migration scripts
│   └── tests/                     pytest suite (490+ tests)
├── frontend/
│   ├── app/                       Expo Router pages
│   └── src/
│       ├── components/
│       │   └── permit-renewal/    StartRenewalPanel + FilingStatusCard + ManualRenewalPanel
│       └── ...
└── docs/
    ├── architecture/
    │   ├── v1-monitoring-architecture.md   Canonical product description
    │   └── akamai-bypass-decision.md       SUPERSEDED — historical bypass attempts
    └── coi-retention-guarantee.md          R2 bucket-lock guarantee for COI uploads
```

---

## Operator runbooks

The architecture doc carries the post-deploy operator action
checklists for each MR.14 sub-commit (4a, 4b, 4c, 5). Specifically:

- Cleanup migrations: `migrate_clear_filing_rep_credentials`,
  `migrate_clean_stranded_renewals`, `migrate_clean_duplicate_projects`.
- Drop the orphaned `agent_public_keys` Mongo collection.
- Verify the four-phase loop (signals, diffing, feed, renewal start)
  end-to-end on production projects.

---

## License

MIT
