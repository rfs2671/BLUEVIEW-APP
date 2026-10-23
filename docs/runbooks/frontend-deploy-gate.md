# Frontend deploy gate: the backend goes first

**Why.** On 2026-10-21 Railway paused deploys platform-wide after #826. Vercel
(app.levelog.com) and the EAS OTA (every store install) kept shipping on every
merge, so the web build and the phones ran screens whose endpoints the backend
did not have yet — the project schedule screen showed "Could not load the
schedule". The frontend must never go live ahead of the backend it calls.

**The rule.** A frontend publish waits until `https://api.levelog.com/api/version`
serves a commit that *includes* the one being published (git ancestry, not an
exact match — Railway may skip straight to a later merge). After 20 minutes the
job fails and nothing is published; re-run it once `/api/version` catches up.

| Piece | Where | State after merge |
|---|---|---|
| OTA gate | `.github/workflows/ota-update.yml`, step *Wait for the backend to serve this commit* | **Active** for `production` publishes. Newest push cancels an older waiting run. |
| Web gate | `.github/workflows/web-deploy.yml` | **Inert** until the steps below are done (warns and exits 0 without the secret). |
| Lag alarm | `.github/workflows/backend-deploy-lag.yml`, every 15 min | **Active**: red when the oldest undeployed merge on main is > 30 min old. |
| Logic | `.github/scripts/backend_deploy.py` (`wait`, `lag`) | Tested in `backend/tests/test_backend_deploy_gate.py`. |

## Switching the web build over (operator, in Vercel and GitHub)

Do these in order. Until step 3 is done Vercel keeps auto-deploying and the web
gate stays inert, so steps 1–2 are safe to do any time.

1. **Create the deploy hook.** Vercel → the app.levelog.com project →
   **Settings → Git → Deploy Hooks**. Name it `after-backend`, branch `main`,
   create, copy the URL. Treat the URL as a secret: anyone holding it can deploy.
2. **Add the secret.** GitHub → repository **Settings → Secrets and variables →
   Actions → New repository secret**: name `VERCEL_DEPLOY_HOOK_URL`, value the
   URL from step 1.
3. **Turn off git auto-deploy for `main` only.** In `frontend/vercel.json`
   (the project's root directory is `frontend/`), add:

   ```json
   "git": { "deploymentEnabled": { "main": false } }
   ```

   This stops deployments *upon commits* to `main` and keeps preview
   deployments for PR branches. It is a reviewed change in git rather than a
   dashboard toggle nobody can see. Vercel's docs say deploy hooks stop only
   under the legacy `github.enabled: false`, which this is not; they do not
   say in so many words that hooks run when `deploymentEnabled` is false for
   the branch, so **verify once**: after merging, run *web deploy (after the
   backend)* from the Actions tab (workflow_dispatch) and confirm a deployment
   marked "Deploy Hook" appears in Vercel and `app.levelog.com/version.json`
   reports main's tip.
4. **Retune the post-deploy web check in the same change as step 3.**
   `postdeploy-web-check.yml` runs on every push to main and waits 10 minutes
   (`POLL_SECONDS=600`) for `version.json` to equal that exact SHA. With the
   gate, the web build arrives later (backend deploy + Vercel build), and a
   backend-only merge no longer rebuilds the web at all — so as written it
   would go red on those merges. Trigger it from `web-deploy.yml` after the
   hook fires (or on `frontend/**` pushes with `POLL_SECONDS` ≥ 2100).

## When the gate fails

The job log says which commit the backend serves. Check Railway (status page
and the project's deployments). Once `/api/version` shows a commit that
includes the merge, re-run the failed job — OTA: *EAS Update*; web: *web deploy
(after the backend)*. Do not bypass the gate by dispatching to `production`
from a laptop: that is the failure this exists to prevent.
