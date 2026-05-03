# Akamai Bypass — Architecture Decision (MR.12)

**Status**: Accepted
**Date**: 2026-05-03
**Decider**: Operator (Roy Fisman) + claude-code engineering session
**Affects**: `dob_worker/handlers/dob_now_filing.py` and the entire
DOB NOW automation path. **Does NOT affect** `dob_worker/handlers/bis_scrape.py`,
which targets the legacy BIS site (no Akamai protection).

## Context

DOB NOW (`a810-dobnow.nyc.gov`) is fronted by **Akamai Bot Manager v4**.
Every cold connection from a headless worker to the DOB NOW landing
page returns HTTP 403 with an Akamai challenge page before our code
can even reach the NYC.ID login form. Without a bypass, the entire
filing pipeline is blocked.

## Approaches attempted (in chronological order)

Each approach below was implemented, smoke-tested against the live
DOB NOW site, and proven insufficient. Documented here so future
work doesn't re-attempt the same dead ends.

### Attempt 1: Warm-session cookie seeding (MR.11.1)

**Hypothesis**: Akamai grants trust based on cookies earned during a
real human login. Capture those cookies once, reuse on every worker
run.

**Implementation**: `dob_worker/scripts/seed_storage_state.py` runs
non-headless Chromium so the operator can hand-log-in to NYC.ID;
`context.storage_state(path=...)` dumps the cookie jar; the worker's
`with_browser_context` loads it on next run via `storage_state=`.

**Result**: ❌ HTTP 403 on first `page.goto()` despite 26-cookie
seeded jar being loaded into the BrowserContext. Akamai's first-
contact check happens BEFORE cookies are sent (likely TLS
fingerprint or initial JS challenge), so cookies alone don't help.

### Attempt 2: Path resolution + DOB NOW navigation correction (MR.11.2)

**Hypothesis (separate from bypass)**: Beyond Akamai, our handler
also had two bugs: (a) the seed script wrote to `C:\storage\…`
instead of the host bind-mount source `~/.levelog/agent-storage/…`,
and (b) the navigation code assumed a single-row "click → Renew"
flow when the empirical DOM is two-tier (job search → filing row →
View Work Permits → work permit row → Renew Permit).

**Implementation**: Path resolution prefers `LEVELOG_AGENT_STORAGE_DIR`
and ignores in-container `STORAGE_STATE_DIR`. Navigation rewritten
to match operator's 2026-04-30 DOM survey.

**Result**: ✅ Both fixes correct (and necessary — kept). Did not
solve Akamai 403, since 403 fires before navigation runs.

### Attempt 3: Preserve-on-failure + shared launch fingerprint (MR.11.3)

**Hypothesis**: Two compounding problems: (a) failed runs were
overwriting the seeded session with post-Akamai-block cookies,
progressively degrading the seed; (b) the seed script and the
worker handler launched Chromium with different flags, default
user-agents, and viewports, so Akamai saw two different browser
identities and rejected the worker as "not the browser that earned
these cookies."

**Implementation**: `with_browser_context` skips the post-fn save
when handler returned `failed`/`cancelled`. New `lib/browser_launch.py`
provides a single source of truth for launch + context kwargs (UA,
viewport, locale, timezone, headers, `--headless=new`); both seed
script and handler import from it.

**Result**: ❌ HTTP 403 still fires. Cookies + matching fingerprint
are necessary but not sufficient. Akamai Bot Manager v4 also
inspects:
- TLS ClientHello (JA3/JA4 fingerprint) — Playwright's bundled
  Chromium has a JA3 distinct from real Chrome installations.
- Network behavior (RTT, packet timing) — datacenter/cloud egress
  paths look different from residential ISP paths.
- IP reputation — even residential proxy IPs from commercial
  pools are widely-known to bot-detection services.
- Behavioral analysis — mouse movement patterns, dwell time,
  fingerprint-canvas/WebGL/audioContext probes injected via JS.

### Attempt 4 (proposed, not implemented): Webshare residential proxy

**Hypothesis**: Egress from a residential ISP IP defeats Akamai's
IP-reputation layer.

**Investigation**: Operator empirically tested Webshare rotating
+ residential — both 403'd. The TLS/JA3 layer is not addressed by
proxies; Webshare and similar commercial proxy pools are themselves
fingerprinted by Akamai's threat intel feeds. Even when the IP
looks residential, the JA3 from Playwright's Chromium gives the
session away.

**Result**: ❌ Surface-level cost win ($5–10/mo), zero detection-
layer wins. Operator can cancel the Webshare subscription —
nothing else in the active code path uses it. (`bis_scrape.py`
references `WEBSHARE_PROXY_URL` defensively but the operator's
`.env.local` has it unset; the BIS scrape runs unproxied today.)

### Attempt 5 (proposed, not implemented): Cloudflare Tunnel egress

**Investigation**: The MR.5 cloudflared scaffold is inbound-only;
it doesn't route worker egress. To use Cloudflare for egress IP
shaping requires Zero Trust dedicated egress IPs — an enterprise
add-on with no public pricing, and the IP block is published, so
Akamai already classifies it as datacenter traffic. Same JA3
problem regardless of egress IP choice.

**Result**: ❌ Doesn't address the detection layers that actually
matter. Cloudflare Tunnel scaffold left in place for future
inbound-webhook use cases (CAPTCHA prompt routing, etc.) — not
useful for this problem.

## Decision: Bright Data Browser API (MR.12)

**Bright Data Browser API** (formerly "Scraping Browser") is a
remote managed-Chromium service accessed via Chrome DevTools
Protocol (CDP). The worker connects to `wss://brd.superproxy.io:9222`
via Playwright's `chromium.connect_over_cdp(...)`. Bright Data
handles the entire stack of evasion concerns:

| Detection layer | Bright Data's handling |
|---|---|
| TLS / JA3 fingerprint | Their browsers present TLS hellos matching real Chrome stable; constantly rotated as Chrome updates |
| IP reputation | Residential / mobile / ISP pools, geo-targetable, rotated per session |
| Browser fingerprint (canvas, WebGL, fonts, audio) | Spoofed to match the IP's apparent device profile |
| CAPTCHA | Built-in solver, default ON |
| Behavioral signals | Their browser presents normal mouse-event distributions |
| Cookies | Managed transparently by Bright Data's session machinery |

Independent benchmarks report ~98.44% success rate on Akamai-
protected targets — consistent with operator's empirical result on
DOB NOW.

### What we keep

- ✅ All handler business logic in `handlers/dob_now_filing.py`:
  decrypt credentials, login, navigate (job search → View Work
  Permits → work permit row → Renew Permit), fill PW2, submit,
  capture confirmation number. None of it changes.
- ✅ Audit log + cancellation checkpoints — same backend contract.
- ✅ MR.11.2 navigation flow correction — empirical DOM survey
  still applies; Akamai bypass doesn't change DOB NOW's UX.
- ✅ `bis_scrape.py` and its local Chromium launch — unchanged.
  Legacy BIS site has no Akamai; Bright Data would be wasted spend.
- ✅ `lib/browser_launch.py` — kept, but `get_launch_args()` /
  `get_context_args()` are now used only by `seed_storage_state.py`
  (which itself is vestigial in the active path; see "Vestigial").
- ✅ `lib/browser_context.py:with_browser_context()` — kept, not
  called from the active dob_now_filing path; available for any
  future local-Chromium handler that wants per-GC storage_state.

### What we remove from the active path

- ❌ `pw.chromium.launch(headless=True, args=...)` in the
  dob_now_filing handler. Replaced with
  `pw.chromium.connect_over_cdp(BRIGHT_DATA_CDP_URL)`.
- ❌ Storage_state load/save for dob_now_filing. Bright Data's
  session is ephemeral by design; persisting cookies between runs
  would defeat their per-session identity rotation. The
  `~/.levelog/agent-storage/<gc>/current.json` file is no longer
  consulted by the active path.
- ❌ `with_browser_context(...)` wrapper in the dob_now_filing
  handler — replaced with a flat `browser.new_context()` since
  per-GC isolation isn't a meaningful concept when Bright Data
  rotates identity per session anyway.
- ❌ Webshare proxy concept for dob_now_filing. Operator can
  cancel the Webshare subscription if no other component uses it.

### What's vestigial (kept but not used by active path)

- `dob_worker/scripts/seed_storage_state.py` — kept in case a
  future use-case wants warm-session seeding (e.g. a different
  non-Akamai site). Marked legacy in its docstring.
- `~/.levelog/agent-storage/626198/current.json` — the operator's
  stranded warm session from MR.11.x. Safe to ignore; no code
  reads it after MR.12.
- `lib/browser_context.py:with_browser_context()` — same. Will
  be reused if/when bis_scrape migrates off its inline launch.
- MR.5 cloudflared scaffold — kept for future inbound-webhook
  routing (CAPTCHA prompt handoff to operator UI).

## Pricing model

Bright Data Browser API on **pay-as-you-go** tier:

- **$8.40 per GB** of session bandwidth (the metered axis)
- **$20/month minimum** spend
- **Premium domains** OFF (DOB NOW is not on the premium list)
- **CAPTCHA solver** ON (default, no surcharge on standard plans)

### Per-filing cost estimate

A typical DOB NOW renewal filing involves:
- Landing page → NYC.ID redirect → login → dashboard → search →
  filing list → View Work Permits → work permit list → Renew →
  PW2 form → submit → confirmation page.
- ~10 page loads, mostly HTML + small JS bundles. DOB NOW is not
  asset-heavy.

Empirical estimate: **5–15 MB per filing** depending on cached
asset reuse within the session.

At $8.40/GB:
- Low end (5 MB): ~$0.04 per filing
- High end (15 MB): ~$0.13 per filing
- Operator's stated ~$0.07–0.13 range tracks.

Filing volume × $0.10 per filing × 22 working days = the monthly
spend formula. The **$20/month minimum** is the binding constraint
until volume reaches ~200 filings/month (~10/day).

### Probe to validate after credentials are set

Operator can run this 30-second probe via the Bright Data dashboard
(no worker code execution required):

```
1. Bright Data dashboard → Browser API zone "levelog_scraping_browser"
   → "Try it" or "Playground"
2. Run a single navigation to https://a810-dobnow.nyc.gov/Publish/Index.html
3. Note the bytes-transferred metric for that single page load
   (shown in the playground after the run completes)
4. Multiply by ~10 (page loads per filing) for a per-filing estimate
```

Lower-fidelity alternative: after the first real smoke-test filing
lands successfully, look at the zone's Usage tab → it shows
GB-consumed by day. Divide by filing count.

## Future revisits

| Trigger | Action |
|---|---|
| Filing volume > 500/month and per-filing cost stays at $0.10 | Re-evaluate vs Cloudflare Zero Trust enterprise (predictable monthly cost) |
| Bright Data success rate drops below ~90% on smoke tests | Akamai may have updated their fingerprinting; check Bright Data's release notes for matching update; if not, evaluate competitors (Oxylabs Web Unblocker, ScrapingBee) |
| DOB NOW migrates off Akamai (unlikely) | Drop Bright Data, switch back to local Chromium |
| Operator wants to reduce dependency on a paid third-party for the critical filing path | Long-term: invest in a custom undetected-chromedriver fork, accept ongoing maintenance cost |

## Failure modes added

`handlers/dob_now_filing.py` adds one new pre-flight failure mode:

- `bright_data_cdp_url_missing` — `BRIGHT_DATA_CDP_URL` env var is
  unset or empty. Operator action: complete the Bright Data
  zone setup per `dob_worker/README.md` step 11, paste the CDP URL
  into `.env.local`, and force-recreate the worker container.

Existing failure modes (akamai_challenge, login_failed,
permit_not_found, etc.) are preserved — Bright Data shouldn't
trigger them in normal operation, but the handler still surfaces
them if they occur.

## References

- Operator's empirical findings on Akamai 403 with Webshare —
  this conversation, transcript 2026-05-01 → 2026-05-03.
- Bright Data Browser API docs:
  https://docs.brightdata.com/scraping-automation/scraping-browser/overview
- Playwright `connect_over_cdp` API:
  https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp
- Architecture spec: `~/.claude/plans/permit-renewal-v3.md` §2.5
  (browser context dispatch — pre-MR.12 design now superseded for
  the dob_now_filing path).
