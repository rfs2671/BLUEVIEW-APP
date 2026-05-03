# Akamai Bypass — Architecture Decision

**Status**: Accepted (MR.13 — supersedes MR.12)
**Date**: 2026-05-03 (MR.12, superseded) → 2026-05-03 (MR.13, current)
**Decider**: Operator (Roy Fisman) + claude-code engineering session
**Affects**: `dob_worker/handlers/dob_now_filing.py` and the entire
DOB NOW automation path. **Does NOT affect** `dob_worker/handlers/bis_scrape.py`,
which targets the legacy BIS site (no Akamai protection).

## TL;DR (current state)

- **MR.13 (active)**: dob_worker container runs **real Chrome**
  (`channel="chrome"`, headed via Xvfb) on the operator's laptop,
  using the operator's residential IP. Storage_state seeding
  (MR.11.x) re-engaged. Optional Webshare proxy as fallback.
  Volume capped at ~2 filings/day across ≤20 GCs.
- **MR.12 (superseded)**: Bright Data Browser API via CDP. Closed
  off because Bright Data classifies `*.gov` domains as restricted
  and blocks them at the proxy layer (industry-wide pattern —
  Oxylabs, ScrapingBee, Smartproxy all impose KYC + use-case
  review for gov targets). The 5-line probe script that surfaced
  this is recorded under "Attempt 6" below.
- **v2 trigger**: when the GC count or filing rate exceeds
  ~5/day per IP, Akamai's "many users from one residential IP"
  heuristic begins firing. At that point a different
  infrastructure choice is required — see "v2 ceiling" at the
  bottom of this doc.

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

### Attempt 6: Bright Data Browser API (MR.12 — implemented, then closed off)

**Hypothesis**: Bright Data's managed remote Chromium handles all
five Akamai detection layers (TLS, IP, browser fingerprint,
behavioral, CAPTCHA) with constantly-rotated TLS hellos and
residential IP pools. Independent benchmarks reported ~98% success
on Akamai-protected targets.

**Implementation**: MR.12 shipped `chromium.connect_over_cdp(...)`
to `wss://brd.superproxy.io:9222` with the operator's zone CDP
URL. Pre-flight gate validates `BRIGHT_DATA_CDP_URL`. Storage_state
load/save was removed since Bright Data manages session identity.
Per-filing cost estimated at $0.04–$0.13 with $20/mo minimum.

**Result**: ❌ **Bright Data's policy blocks government domains.**
Discovered via 5-line probe script the same evening MR.12 shipped:

```python
# probe_brightdata.py
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(BRIGHT_DATA_CDP_URL)
        page = await browser.new_page()
        resp = await page.goto("https://a810-dobnow.nyc.gov/Publish/Index.html")
        print(resp.status, await page.content()[:500])
asyncio.run(main())
```

Result: connection refused at the Bright Data proxy layer with an
error explicitly classifying `*.gov` and `a810-dobnow.nyc.gov` as
"restricted target — KYC + use-case review required for government
domains." This is **industry-wide**: Oxylabs, ScrapingBee,
Smartproxy, NetNut all impose the same restriction (verified via
each provider's terms / FAQ). Pure managed-stealth-API path is
closed off for DOB NOW unless we go through enterprise-tier KYC,
which adds weeks of setup and unpredictable approval outcomes for
a "permit-renewal automation" use case.

The MR.12 code is removed cleanly in MR.13 (no dead-code dual-path).
The architecture decision survives in this doc as the durable
record of what was tried.

## Decision: Real Chrome on operator's laptop (MR.13 — current)

After Bright Data was ruled out, the operator's empirical findings
combined with industry research collapsed the option space to **one
viable v1 path**: run real (not headless, not bundled-Chromium)
Chrome on the operator's own laptop using the operator's own
residential IP, capped at low filing volume.

### How this addresses each Akamai detection layer

| Detection layer | MR.13 handling |
|---|---|
| TLS / JA3 fingerprint | Real installed Chrome's TLS hello matches real Chrome — because it IS real Chrome. Playwright's `channel="chrome"` opt-in tells Playwright to launch the OS's installed Chrome instead of the bundled `playwright-chromium` build that has the JA3 fingerprint Akamai's threat-intel feeds know about. |
| Headless markers | `headless=False` + Xvfb (already in the worker container's entrypoint). Real Chrome rendering into a virtual display behaves identically to a human's Chrome on a desktop. No `navigator.webdriver=true`, no missing plugins, no anomalous canvas/WebGL, etc. |
| IP reputation | Operator's residential ISP IP. Akamai sees a normal home/office IP that's not on commercial-proxy or datacenter feeds. |
| Behavioral signals | Volume cap (~2 filings/day across ≤20 GCs = ≤2 filings/day per IP). Akamai's "many users from one IP" detector fires at much higher rates; we stay below the threshold by design. |
| Cookies | Storage_state seeding (MR.11.1) restored. Operator hand-logs-in once per GC; the seeded cookies + matching fingerprint reduce the cold-contact handshake load. |
| CAPTCHA | If DOB NOW serves one, the existing operator-input modal (MR.7) routes it through the FilingStatusCard. Volume cap means this is rare. |

### Why v1 only

The "low volume from one residential IP" guarantee is what makes
this work. At v2 scale (more GCs, more filings/day), Akamai's
behavioral analysis will start flagging the IP as suspicious
("unusual cross-account activity from a single residence"). The
ceiling depends on Akamai's exact threshold — operator should
monitor for any first-403 occurrence and treat it as the v2 trigger.

### What we keep (intact from prior MRs)

- ✅ All handler business logic (decrypt, login, navigation flow,
  PW2 fill, submit, confirmation capture, audit log, cancellation
  checkpoints).
- ✅ MR.11.2 navigation flow correction (job search → View Work
  Permits → work permit row → Renew Permit).
- ✅ MR.11.3 storage_state preserve-on-failure (skip save when
  result.status is "failed" / "cancelled" so the seeded session
  survives transient run failures).
- ✅ `lib/browser_launch.py` shared fingerprint config (UA,
  viewport, locale, timezone). Identical between seed script and
  worker handler.
- ✅ `lib/browser_context.with_browser_context` per-GC storage_state
  load/save — re-engaged.
- ✅ `bis_scrape.py` legacy BIS path — unchanged.

### What MR.13 changes vs. MR.12

| Concern | MR.12 (Bright Data) | MR.13 (real Chrome local) |
|---|---|---|
| Browser source | `chromium.connect_over_cdp(BRIGHT_DATA_CDP_URL)` | `chromium.launch(channel="chrome", headless=False, args=...)` |
| Chrome binary | Bright Data's managed remote | Operator's installed Chrome (apt `google-chrome-stable` inside the container) |
| Headless? | Their internal | `headless=False` + Xvfb virtual display |
| Storage_state | Disabled (Bright Data managed) | **Re-enabled** via `with_browser_context` (MR.11.x machinery) |
| Egress IP | Bright Data residential pools | Operator's residential ISP |
| Optional fallback proxy | n/a | `WEBSHARE_PROXY_URL` env-gated |
| Per-filing cost | $0.04–$0.13 | $0 (already-paid ISP) |
| Monthly minimum | $20 | $0 |
| Volume ceiling | Effectively unbounded | ~5 filings/day per residential IP before behavioral flags |

### What MR.13 removes (Bright Data cleanup)

- ❌ `BRIGHT_DATA_CDP_URL` env var (removed from `.env.local.example`).
- ❌ `get_cdp_endpoint_url()` + `BrightDataConfigError` from
  `lib/browser_launch.py`.
- ❌ Bright Data branch in handler's launch site.
- ❌ MR.12-specific failure mode `bright_data_cdp_url_missing`.

The MR.12 architecture decision (this doc) records WHY Bright Data
didn't work, but no MR.12 *code* survives in MR.13. Operator
cancels the Bright Data subscription (free trial — no charge if
within trial window).

## v2 ceiling — when MR.13 stops working

This is the most important section for future readers. MR.13 is
viable strictly because the load is small and concentrated on one
trusted residential IP. The ceiling is:

1. **Volume per IP**: ≤5 filings/day is a safe estimate. At higher
   rates, Akamai's "many users from one IP" heuristic starts
   firing — even if every individual filing is well-formed.
2. **GC count per IP**: ≤20 GCs is operator's stated v1 scope.
   Multiple GC accounts + multiple permits each routed through
   ONE IP looks like cross-account fraud at sufficient volume.
3. **Operator availability**: storage_state cookies expire (~30–60
   min idle for NYC.ID). At v1 volume the operator re-seeds when
   prompted. At v2 volume, automated re-seeding becomes a real
   ops burden.

When any of those tips over:

| v2 option | Sketch | Cost shape | Risk |
|---|---|---|---|
| **Operator-fleet model** | Multiple operator laptops, one per N GCs, each with its own ISP. Round-robin filings across the fleet. | Linear in operator count; ~free per laptop. | High coordination cost; needs a control plane. |
| **Dedicated residential VM with real Chrome** | Cloud VM at a residential-IP-friendly provider (Wasabi, some VPS providers offer this). One IP per ~10 GCs. | $30–$100/mo per VM. | Akamai may classify the VM provider's IP block as datacenter despite the "residential" label. |
| **Enterprise Bright Data + KYC** | Re-engage Bright Data's enterprise tier with KYC for gov-domain access. | $500+/mo + multi-week onboarding. | Approval not guaranteed for "permit automation" framing. |
| **Direct DOB integration** | Lobby NYC DOB for an API or sanctioned automation channel. | $0 if granted; high political/process cost. | Years not weeks; outside engineering scope. |

The **operator-fleet model** is the most likely v2 path for
LeveLog specifically — adding a second operator at GC-count ~15
spreads load naturally and matches the org's growth shape.

### Original MR.12 decision text (preserved for reference)

The text below was the MR.12 decision narrative. Kept intact for
historical clarity even though the implementation is gone.

---

## Decision: Bright Data Browser API (MR.12 — superseded)

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
