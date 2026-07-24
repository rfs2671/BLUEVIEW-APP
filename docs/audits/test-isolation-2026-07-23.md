# Backend Test Isolation Audit — 2026-07-23

Diagnostic only. Findings and locations. No fixes. Run against clean `main`
(HEAD `7d7ee7d`), `backend/` pytest suite.

All paths relative to `backend/`.

---

## Summary

The suite is **order-dependent**. Of 21 full-suite failures, **18 are a single
shared-state leak** (the process-global rate-limiter counter saturating
mid-run) and **3 are genuine, order-independent failures** unrelated to
isolation.

The 18 leak-failures all fail with HTTP **429 `rate_limit_exceeded`**, not with
their own assertions. They pass in isolation. Which specific tests land on the
saturated side of a 60-second window shifts when the suite's shape changes —
which is exactly why the same suite reported **11 failures on
`feat/two-tier-project-delete`** (a test file there called
`reset_counter()` per test) and **21 on clean main**.

| Bucket | Count | Cause | Order-dependent? |
|---|---|---|---|
| Rate-limiter 429 saturation | 18 | shared `_COUNTER` singleton | **Yes** |
| Stale source-text anchor | 2 | `TestServerPyV23PrewarmWiring` | No (genuine) |
| Real data assertion | 1 | `test_history_filters_by_statistical_v1` | No (genuine) |

---

## 1. Full suite, default order — 3 runs

`python -m pytest tests/ -q --tb=no`, run 3×:

| Run | Result |
|---|---|
| 1 | 21 failed, 1990 passed |
| 2 | 21 failed, 1990 passed |
| 3 | 21 failed, 1990 passed |

**Identical failing set across all 3 runs** (verified by `diff` of the sorted
`FAILED` lists). Default collection order is deterministic, so the saturation
points fall at the same tests every run.

The 21 failing tests:

```
test_scheduling_endpoints.py ......................... 4   (429)
test_start_renewal_clicked.py ........................ 4   (429)
test_v2_0_logbook.py ................................. 9   (429)
test_v2_2_score.py ................................... 2   (1× 429 + 1 genuine)
test_v2_2_schema_scaffolding.py::TestServerPyV23PrewarmWiring . 2   (genuine)
```

## 2. Shuffled order — NOT PERFORMED (plugin absent)

`pytest-randomly` is **not installed** (`import pytest_randomly` → `ModuleNotFoundError`;
`--randomly-seed` is silently ignored). No `conftest.py` exists to provide an
alternative shuffle hook. The requested "3 seeds × shuffle" run could not be
executed with the tools present.

Order-dependence was instead established directly and conclusively (§3 + the
21-vs-11 branch delta), which is stronger evidence than a shuffle: the failing
tests **pass in isolation and fail in the suite**, and the failure set demonstrably
changes with suite shape. Installing a new plugin was out of scope for a
read-only diagnostic.

## 3. Isolation runs (leakage confirmation)

| File | Isolation result | In-suite | Verdict |
|---|---|---|---|
| `test_v2_0_logbook.py` | **54 passed** | 9 fail | order-dependent (429) |
| `test_scheduling_endpoints.py` | **4 passed** | 4 fail | order-dependent (429) |
| `test_start_renewal_clicked.py` | **7 passed** | 4 fail | order-dependent (429) |
| `test_v2_2_score.py` | **1 failed, 33 passed** | 2 fail | 1 genuine + 1 order-dependent |
| `test_v2_2_schema_scaffolding.py::TestServerPyV23PrewarmWiring` | **2 failed, 3 passed** | 2 fail | genuine (order-independent) |

Every order-dependent failure carries the same signature. Example
([test_v2_0_logbook.py:706](../../backend/tests/test_v2_0_logbook.py) via
`test_audit_404`):

```
E  AssertionError: 429 != 404 : {"error":"rate_limit_exceeded",
   "retry_after_seconds":17,"limit":"100 requests per 1 minute"}
```

and ([test_v2_2_score.py] history-filter test's 429 sibling):

```
E  assert 429 == 200 ... {"error":"rate_limit_exceeded", ...}
```

---

## 4 & 5. Shared mutable state — sources

### LEAK #1 — process-global rate-limiter counter (PRIMARY; 18 failures)

- **State:** `_COUNTER = _FixedWindowCounter()` — module-level singleton
  ([lib/rate_limits.py:417](../../backend/lib/rate_limits.py)). Its `_counts`
  dict ([lib/rate_limits.py:296-ish, inside `_FixedWindowCounter.__init__`](../../backend/lib/rate_limits.py))
  holds `(key, window) -> (count, window_start)` and uses `time.monotonic()`.
  Limit is `DEFAULT_LIMIT = "100/1 minute"`
  ([lib/rate_limits.py:164](../../backend/lib/rate_limits.py)); the counter is
  consulted per request at
  [lib/rate_limits.py:457](../../backend/lib/rate_limits.py) (`_COUNTER.hit(...)`).
- **How it leaks:** the counter is a single process-wide object with no
  per-test reset. Every `TestClient` request originates from the same client
  identifier (one test IP), so **all HTTP tests across all files share one
  counter bucket**. Roughly 2000 tests run inside overlapping 60-second
  windows; once a window accumulates >100 requests, every subsequent request in
  that window returns 429 regardless of the endpoint's own behavior.
- **Who resets it — and who doesn't:** `reset_counter()` exists
  ([lib/rate_limits.py:420](../../backend/lib/rate_limits.py)) but is called
  **only inside `test_c2_rate_limits.py`** — in the `setUp`/`tearDown` of
  `TestFixedWindowCounter` ([tests/test_c2_rate_limits.py:280](../../backend/tests/test_c2_rate_limits.py))
  and `TestMiddlewareIntegration` ([:536-540](../../backend/tests/test_c2_rate_limits.py)),
  for that file's own tests. **No `conftest.py` exists**, so there is no autouse
  fixture resetting the counter between the other ~90 test files. Its absence is
  the root enabler.
- **Dependent tests (order-dependent, all 429):**
  - `test_scheduling_endpoints.py` — 4 (e.g. `test_get_before_generate_is_404`, which posts to `/api/projects/proj1/schedule/generate`)
  - `test_start_renewal_clicked.py` — 4 (`TestErrorPaths`, `TestHappyPath`, `TestReadinessGate`)
  - `test_v2_0_logbook.py` — 9 (`TestEndpointsFlagDisabled` ×6 + `TestEndpointsFlagEnabled` ×3)
  - `test_v2_2_score.py` — 1 of its 2 failures (`TestGetRiskScoreFiltersModelVersion::test_filters_by_statistical_v1_model_version`)
- **Dependency type:** on **cumulative order**, not a specific predecessor. The
  failures are driven by total request volume from *all* prior HTTP-making tests
  landing in the same window, not by any one test. This is why these are the
  **late-alphabetical** files (`scheduling` / `start_renewal` / `v2_0` / `v2_2`
  sort last) — enough requests have accrued by the time they run. Reordering,
  adding, or removing any HTTP-heavy file shifts the window boundaries and
  changes which tests 429 — the mechanism behind the **21 (main) vs 11
  (`feat/two-tier-project-delete`)** discrepancy: that branch's
  `test_two_tier_project_delete.py` called `reset_counter()` per test, clearing
  the counter mid-suite and letting subsequently-run files stay under the cap.

### LEAK #2 — feature-flags module cache (LATENT; not a current failure cause)

- **State:** `_CACHE: Dict[str, Tuple[Optional[Dict], float]]` — module-level,
  60-second TTL ([lib/feature_flags.py:64](../../backend/lib/feature_flags.py),
  TTL at [:59](../../backend/lib/feature_flags.py)), guarded by `_CACHE_LOCK`
  ([:65](../../backend/lib/feature_flags.py)). Read via `_cache_get`
  ([:77](../../backend/lib/feature_flags.py)), written via `_cache_set`
  ([:90](../../backend/lib/feature_flags.py)).
- **How it leaks:** a test that resolves a flag populates `_CACHE`; for the next
  60s any test reading the same flag gets the cached value, even after patching
  `server.db` to a fixture with a different flag doc.
- **Evidence the authors know:** `test_v2_0_logbook.py`'s `TestEndpointsFlagDisabled`
  defensively calls `feature_flags.cache_invalidate(None)` in **both** `setUp`
  and `tearDown` ([tests/test_v2_0_logbook.py, `class TestEndpointsFlagDisabled`](../../backend/tests/test_v2_0_logbook.py))
  specifically to null this cache. Tests that toggle a flag *without* that guard
  are exposed.
- **Dependent tests:** any flag-gated endpoint test lacking a `cache_invalidate`
  in setUp/tearDown. **Not** implicated in the current 21 failures (those are
  429s that never reach flag resolution) — recorded as a live leak surface.
- **Dependency type:** on a **specific predecessor** (whichever test last cached
  that flag), bounded by the 60s TTL.

### LEAK #3 — `server.db` module attribute, one unrestored assignment

- **State:** the module global `server.db`. Tests swap it for a fake and are
  expected to restore it.
- **Restored (safe):** most call sites pair the assignment with a restore —
  `test_account_activation.py:68/72,89/94,108/120`, `test_activity_feed_endpoint.py:168/171`,
  `test_dob_logs_seed_suppression.py:144/147`, `test_project_list_defaults.py:143/146`,
  `test_project_model_endpoints.py:98/103`, `test_scheduling_endpoints.py:115/120`.
  The majority of the codebase instead uses `with patch.object(server, "db", ...)`
  (context-managed, auto-restored — not a leak).
- **Unrestored (leak):** [tests/test_project_model_autotrigger.py:108](../../backend/tests/test_project_model_autotrigger.py)
  does `server.db = db` with **no matching restore in the file** (no
  `server.db = orig`, no `addCleanup`, no `finally`). After that test module,
  `server.db` points at its fake until the next test that patches it overrides
  the value.
- **Dependent tests:** any test running after `test_project_model_autotrigger.py`
  that reads `server.db` without first patching it. Low blast radius (most tests
  patch first). **Not** implicated in the current 21 failures.
- **Dependency type:** on a **specific predecessor**.

### NOT leak sources (checked and cleared)

- **Environment variables — no cross-file leak.**
  - `test_c2_rate_limits.py:477` sets `os.environ["RATE_LIMITS_DISABLED"] = "true"`
    but its class `TestEvaluate` restores it in `tearDown`
    ([tests/test_c2_rate_limits.py:403-405](../../backend/tests/test_c2_rate_limits.py),
    `os.environ.pop("RATE_LIMITS_DISABLED", None)`). **Empirically verified:** after
    running the whole file, `RATE_LIMITS_DISABLED` is `None`. (Had it leaked
    `"true"`, later tests would be *un*limited — the opposite of the observed 429s.)
  - `test_eligibility_shadow.py:304/308/315` set `ELIGIBILITY_REWRITE_MODE`;
    `test_bbl_backfill.py:199` sets `SOCRATA_APP_TOKEN`. No restore verified, but
    **no observed cross-file impact** — the tests reading those vars pass, and
    neither var appears in the 21 failures. Recorded as unverified-restore, not a
    demonstrated leak.
- **`app.dependency_overrides` — all cleared.** Every test file that assigns
  `dependency_overrides[...]` (including `test_activity_feed_endpoint`,
  `test_coi_endpoints`, `test_dob_logs_seed_suppression`, `test_project_list_defaults`
  which override `server.get_admin_user` directly) also calls
  `dependency_overrides.clear()` / `.pop()`. Grep found **zero** files that set
  without clearing.
- **No `scope="session"` / `scope="module"` fixtures** anywhere in `tests/`.
- **No `conftest.py`** at repo root, `backend/`, or `backend/tests/`. (This
  absence is itself the reason LEAK #1 has no global reset.)
- **Real-DB writes:** not observed as a leak vector — the failing tests all
  patch `server.db` with in-memory fakes; the 429s short-circuit before any DB
  access. (A broader "does any test hit a real Mongo" sweep was not exhaustively
  performed; MONGO_URL defaults to `localhost:27017`, and tests that need Mongo
  patch it out.)

---

## The 3 genuine (order-independent) failures — NOT isolation issues

Recorded so they are not mistaken for leakage; they fail identically in isolation.

1. `test_v2_2_schema_scaffolding.py::TestServerPyV23PrewarmWiring::test_create_project_endpoint_spawns_prewarm`
2. `test_v2_2_schema_scaffolding.py::TestServerPyV23PrewarmWiring::test_create_project_endpoint_wraps_spawn_in_try_except`
   - Both: a **source-text anchor** assertion that greps `server.py` for
     `@api_router.post("/projects", response_model=ProjectResponse)` and fails —
     `AssertionError: endpoint anchor not found`. The decorator's current form no
     longer matches the pinned literal. A stale cross-reference test, independent
     of run order.
3. `test_v2_2_score.py::TestGetRiskScoreHistoryFiltersModelVersion::test_history_filters_by_statistical_v1`
   - Real data assertion: `AssertionError: 0 != 2 : history returned 0 rows,
     expected 2 V2.2 rows (V2.1 rows must be filtered out)`. Fails in isolation
     (only 34 requests, no rate-limit involvement).

---

## Effect on the "11 vs 21" discrepancy (the reported symptom)

The 9 `test_v2_0_logbook` failures — plus the scheduling/renewal/score 429s —
are all LEAK #1. On `feat/two-tier-project-delete`, `test_two_tier_project_delete.py`
called `rate_limits.reset_counter()` in its per-test client helper, clearing the
shared counter partway through the run. Files collected after it then started
each window under the cap, so fewer of them 429'd, dropping the observed count to
11. Nothing about the logbook code changed — only where the counter happened to
be saturated. On clean main, with no such reset, the full 18-failure saturation
pattern appears, for 21 total.

---

## Follow-ups (appended 2026-07-23)

Surfaced while fixing `test_history_filters_by_statistical_v1` (a rolling-window
fixture that drifted out of its window). Recorded, not fixed.

- **Three inline-`now()` rolling-window endpoints have NO test coverage** — the
  same bug class as the history-filter test, but with no test to catch the
  drift at all:
  - `get_my_recent_signals` — cutoff at [server.py:5705](../../backend/server.py) (`since = now() - timedelta(days=d)`)
  - `preview_my_notification_preferences` — cutoff at [server.py:6009](../../backend/server.py)
  - `mark_all_dob_logs_read` — cutoff at [server.py:17835](../../backend/server.py) (`now() - timedelta(days=30)`)

  Each computes a window from the real clock and has no test exercising that
  window. Untested rolling-window code is exactly the class that produced the
  history-filter failure — there is simply no fixture to detonate.

- **`permit_renewal.py` inline-`now()` expiry comparisons have no now-relative
  test** — `is_current = exp_dt > datetime.now()` ([permit_renewal.py:565](../../backend/permit_renewal.py)
  and [:896](../../backend/permit_renewal.py)) and
  `days_left = (exp_date - datetime.now(...)).days` ([permit_renewal.py:1138](../../backend/permit_renewal.py)).
  No test hardcodes an expiry date and asserts a now-relative outcome against
  these (the renewal-reminder tests pass `days_until` as an int, and
  `test_permit_renewal_datetime` only exercises tz-coercion). Correct behavior,
  but unguarded.

- **`GET /projects/{id}/risk-score/history` is registered and live but not
  wired to a UI.** The only frontend `/history` caller is reports
  ([frontend/src/utils/api.js:911](../../frontend/src/utils/api.js)); the risk-score
  drawer calls `/risk-score`, `/risk-score/calculate`, and
  `/risk-score/calibration`, never `/history`
  ([frontend/src/components/RiskScoreDrawer.jsx](../../frontend/src/components/RiskScoreDrawer.jsx)).
  This is the **second** shipped-but-unwired backend surface found this week,
  after `score_band` (zero production callers; the frontend
  `RiskScoreCircle.bandFor` reimplements the same thresholds independently).
