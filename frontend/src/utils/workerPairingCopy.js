/**
 * WHAT A WORKER'S TRADE AND COMPANY SAY WHEN THERE IS NO PROJECT.
 *
 * THE DEFECT. Three surfaces rendered "No trade specified" / "No company" off
 * the WORKERS document — and nothing writes those fields. The rule is stated
 * where the collection is defined:
 *
 *   "a worker's trade and company belong to the {worker, project} PAIR, never
 *    to the worker alone. Nothing writes trade or company to the global
 *    `workers` document."
 *
 * and WorkerResponse's own docstring says why the endpoint cannot fill them:
 * "a worker with pairings on two projects has two companies, and this endpoint
 * has no project context to choose between them."
 *
 * So the fields are absent BY DESIGN, and "No company" reported that as missing
 * data. An admin reading it went to fix it — and the edit form on that same
 * screen wrote a worker-level copy, the exact bleed the design forbids, until
 * that path was closed.
 *
 * ABSENCE IS NOT A DEFICIENCY HERE. It is the design showing through, and the
 * copy has to say so. _get_worker_project_trade refuses to fall back to the
 * worker document for the same reason: "a value from another project is worse
 * than no value, because it is silently wrong instead of visibly absent."
 *
 * ONE MODULE because three surfaces render this and they drifted once already.
 */

/**
 * The trade/company line for a worker, given whatever context the caller has.
 *
 * @param trade       resolved pairing trade, or falsy
 * @param company     resolved pairing company, or falsy
 * @param projectName the project the pairing belongs to, or falsy
 *
 * Returns a string. Never "No company", and never an empty string — a blank
 * line reads as a rendering fault rather than as an answer.
 */
export function pairingLine({ trade, company, projectName } = {}) {
  const t = String(trade || '').trim();
  const c = String(company || '').trim();
  const p = String(projectName || '').trim();

  // BOTH KNOWN — the ordinary case once a project is in hand. The project is
  // named because the pairing is only true there; an unqualified
  // "Framers · Arkon Builders" is the same over-claim the worker-level copy
  // made, just sourced correctly.
  if (t && c) return p ? `${t} · ${c} — on ${p}` : `${t} · ${c}`;

  // ONE OF THE TWO. A pairing with a trade and no company is a real stored
  // shape (_get_worker_project_trade returns company as "" when unset), so it
  // is rendered rather than collapsed into the absent case.
  if (t) return p ? `${t} — on ${p}` : t;
  if (c) return p ? `${c} — on ${p}` : c;

  // NEITHER. State the rule, and name the project when one is known so the
  // sentence is about something the reader can act on rather than a general
  // fact about the system.
  return p
    ? `Trade and company are set per project — none recorded for ${p}.`
    : 'Trade and company are set per project.';
}

/**
 * True when a real pairing was resolved, for callers that style the two states
 * differently. Kept here so "is there a pairing" is asked in one place.
 */
export function hasPairing({ trade, company } = {}) {
  return !!(String(trade || '').trim() || String(company || '').trim());
}

export default pairingLine;
