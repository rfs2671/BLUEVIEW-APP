# Akamai Bypass — Architecture Decision (SUPERSEDED)

> ## ⚠️ SUPERSEDED by [v1-monitoring-architecture.md](./v1-monitoring-architecture.md) (MR.14, 2026-05-03)
>
> **v1 ships as a monitoring-only product.** Renewal automation is
> deferred to v2. The `dob_worker/` directory, Bright Data + Webshare
> integrations, agent_public_keys collection, filing_reps[].credentials
> field, and cloudflared scaffold are all REMOVED from the codebase
> across MR.14 commits 4a → 5.
>
> If a future v2 revisits filing automation, the catalogue below is
> the prior art. **Read it first** so v2 doesn't relitigate the dead
> ends. If conditions change (DOB ships an official API; a new
> managed-stealth provider works against gov domains; etc.), write
> a NEW ADR — don't edit this one.

---

**Status**: SUPERSEDED
**Original decision dates**: 2026-04 → 2026-05-03 (MR.5 → MR.13)
**Final disposition**: 2026-05-03 (MR.14 pivot)
**Decider**: Operator (Roy Fisman) + claude-code engineering session

---

## Context (for future v2 readers)

NYC DOB NOW (`a810-dobnow.nyc.gov`) is the public-facing portal for
filing PW2 permit renewals. It's protected by **Akamai Bot Manager** —
TLS fingerprinting, JA3, navigator integrity checks, and behavioural
heuristics that distinguish managed browsers (Playwright,
puppeteer-extra-stealth, etc.) from real consumer Chrome.

LeveLog v1 (MR.5–MR.13) tried to drive PW2 through this portal under
the operator's NYC.ID session, with the operator-typed credentials
encrypted client-side and decrypted on a local worker. Every approach
in the catalogue below ran into the Akamai gate at some layer.

After MR.13's last viable path (Bright Data Browser API) was blocked
by Bright Data's gov-domain policy, the product direction shifted:
ship monitoring as the v1 value prop, treat filing automation as a
v2 question.

---

## Bypass approaches tried (in chronological order)

| # | Approach | Outcome |
|---|---|---|
| 1 | **Warm cookies + storage state**. Operator logs into DOB NOW manually; we capture cookies + localStorage and replay them in Playwright. | Worked initially; Akamai began rotating bot-detection signals on session reuse. Cookies aged out within hours. |
| 2 | **Browser fingerprint matching**. Adjust JA3, ClientHello, navigator properties to match the operator's real Chrome. | Closed the gap on TLS but Akamai's behavioural heuristics (mouse jitter, focus events, page-render timing) still flagged headless. |
| 3 | **Preserve-on-failure + circuit breaker**. Save storage state on partial failures; let operator manually intervene; circuit-break after N failures. | Made debugging easier but didn't solve the root cause; circuit breaker tripped within minutes of every test run. |
| 4 | **Residential proxy (Webshare)**. Route Playwright traffic through residential IPs to look like consumer connections. | Reduced IP-based blocking but Akamai's fingerprint heuristics still fired regardless of network path. |
| 5 | **cloudflared tunnel**. Route filing traffic through Cloudflare's WARP exit so DOB sees Cloudflare IPs. | Cloudflare IPs are well-known to Akamai; flagged worse, not better. |
| 6 | **Bright Data Browser API**. Managed-stealth browser hosted by Bright Data, designed to evade exactly these checks. | **Initially worked.** Then Bright Data's gov-domain policy classified `a810-dobnow.nyc.gov` as restricted and blocked it without enterprise KYC. Path closed. |
| 7 | **Real Chrome (`channel="chrome"`) on operator's laptop, inside Xvfb**. The MR.13 approach. Run actual consumer Chrome on the operator's machine, paced ~2 filings/day, optional Webshare proxy fallback. | Worked in dev but volume ceiling was ~5 filings/day per IP before Akamai rate-limited. Wouldn't scale beyond a single GC, much less the 20-GC v1 target. |

---

## Why we pivoted (don't re-try without new conditions)

Three constraints converge:

1. **Akamai is the right tool for what NYC DOB is doing.** It's
   designed to block exactly the workflows we were attempting. Every
   bypass in the catalogue above was either a temporary gap (closed
   within days) or a volume ceiling (5 filings/day per IP).
2. **Managed-stealth providers are the closest thing to a working
   solution** but they classify `.gov` domains as restricted by
   policy. Enterprise KYC unlocks them in theory but requires a
   business relationship that doesn't fit a pre-revenue product.
3. **The product hypothesis didn't depend on filing.** GCs don't
   need LeveLog to file PW2 — they need LeveLog to TELL them when
   PW2 needs filing. The activity feed + Start Renewal UX delivers
   that without going through Akamai at all.

The pivot is documented in `v1-monitoring-architecture.md`. v1 ships
without any of the seven bypass approaches.

---

## Conditions that would justify revisiting v2 filing automation

A future v2 should **not** retry these approaches without at least
one of:

- **DOB ships an official API.** Path of least resistance; everything
  else becomes irrelevant.
- **A managed-stealth provider relaxes its gov-domain policy.** Bright
  Data, Browserless, or a new entrant accepts `.gov` traffic.
- **Operator-fleet model becomes economically sensible.** Multiple
  operator laptops, each running a small filing volume, with a
  control-plane to dispatch filings to the laptop with available
  capacity. Adds infrastructure but sidesteps the per-IP volume
  ceiling. Only worth it at scale (50+ active GCs).
- **A reverse-engineered Akamai bypass becomes maintainable.** The
  prior art has a half-life measured in weeks; if the open-source
  community produces something with longer-term stability, revisit.

---

## Removed code references (for archaeology)

If you're trying to reconstruct what the old filing path looked like:

- `dob_worker/` directory — git history pre-MR.14-4a. Carries the
  Playwright handler (`handlers/dob_now_filing.py`), browser launch
  (`lib/browser_launch.py`), warm-cookie persistence
  (`lib/browser_context.py`), AES-GCM/RSA-OAEP credential decrypt
  (`lib/crypto.py`), heartbeat + queue client.
- `backend/server.py` MR.6 endpoints (POST `/internal/permit-renewal-claim`,
  `/job-result`, `/agent-heartbeat`, `/filing-jobs/{id}`,
  `/filing-job-event`) — git history pre-MR.14-4a.
- `frontend/src/lib/agent_crypto.js` — git history pre-MR.14-4b.
  SubtleCrypto-based hybrid encryption helper.

The `dob_signal_classifier`, `dob_signal_templates`, `dob_logs`
collection, and Open Data poller code in v1 are NEW (MR.14) and
unrelated to the bypass attempts above. Don't conflate them.
