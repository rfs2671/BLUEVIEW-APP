/**
 * buildVerdict.js
 * Place at: frontend/src/utils/buildVerdict.js
 *
 * WHAT THE BUILD CARD IS ALLOWED TO SAY ABOUT TWO COMMITS.
 *
 * THE DEFECT THIS REPLACES. settings.jsx computed
 *
 *     buildMatches = jsCommit.slice(0,7) === backendCommit.slice(0,7)
 *
 * and printed "MISMATCH — the app and the backend are on different commits"
 * for every inequality, in warning colour. String equality has no notion of
 * ancestry, so ONE OUTPUT covered three different states:
 *
 *     the app is behind        an OTA that failed to publish, or a phone that
 *                              has not fetched one — a real fault
 *     the backend is behind    a deploy that has not landed — a real fault
 *     NEITHER is behind        a BACKEND-ONLY change. Nothing under frontend/
 *                              changed, so the OTA workflow correctly did not
 *                              run, the phone keeps the bundle it has, and the
 *                              system is exactly right
 *
 * The third case is not hypothetical. On 2026-09-04 two backend-only merges
 * landed and the acceptance test written for the CP said "wait for the OTA and
 * confirm the version line reads the new SHA" — a line that was never going to
 * change. He would have concluded a landed fix had not shipped, which is the
 * same wrong conclusion the stale-bundle case produces, from the opposite
 * cause. A check that returns a well-formed answer without reaching its
 * subject, on the one surface an operator is told to trust before a device
 * test.
 *
 * WHAT SEPARATES THEM, AND WHAT DOES NOT. Ancestry would, and it is not
 * available to a phone. Two timestamps are, and they answer the actionable
 * half — WHICH SIDE MOVED. `Updates.createdAt` is when this bundle was
 * published; `deployed_at` from /api/version is when the running backend
 * started. Both are "when did this artifact come into existence", which makes
 * them comparable.
 *
 * WHAT THIS DELIBERATELY DOES NOT CLAIM. A backend restart resets `deployed_at`
 * with no new commit, so "backend is ahead" is also true for a genuinely stale
 * app. The BACKEND_AHEAD wording therefore states the comparison as fact and
 * offers the benign cause without asserting it. A card that over-claimed would
 * be the same defect it exists to fix, one step further along.
 */

export const IN_SYNC = 'in_sync';
export const BACKEND_AHEAD = 'backend_ahead';
export const APP_AHEAD = 'app_ahead';
export const DIFFERENT = 'different';       // differ, and nothing can say which
export const UNKNOWN = 'unknown';           // not enough to compare at all

function ms(value) {
  if (!value) return null;
  const t = new Date(value).getTime();
  return Number.isFinite(t) ? t : null;
}

/**
 * @param {string|null} jsCommit        commit baked into the bundle
 * @param {string|null} backendCommit   commit reported by /api/version
 * @param {string|null} bundleCreatedAt Updates.createdAt
 * @param {string|null} backendDeployedAt /api/version deployed_at
 * @returns {{state: string, text: string, ok: boolean}}
 */
export function buildVerdict(
  jsCommit, backendCommit, bundleCreatedAt, backendDeployedAt,
) {
  // NOT COMPARABLE IS ITS OWN ANSWER, and it comes first. An unreachable
  // backend or an uninjected bundle commit are different kinds of thing from
  // two commits that disagree, and saying "MISMATCH" about them was always
  // wrong.
  if (!backendCommit) {
    return { state: UNKNOWN, ok: false,
      text: 'Backend unreachable — nothing to compare.' };
  }
  if (!jsCommit) {
    return { state: UNKNOWN, ok: false,
      text: 'Bundle commit not injected at build time; compare the times above.' };
  }

  if (String(jsCommit).slice(0, 7) === String(backendCommit).slice(0, 7)) {
    return { state: IN_SYNC, ok: true,
      text: 'In sync — app and backend are on the same commit.' };
  }

  const bundle = ms(bundleCreatedAt);
  const backend = ms(backendDeployedAt);

  // EQUAL TIMESTAMPS ARE NOT "BACKEND AHEAD". Strictly newer, or this says
  // nothing — the whole point is to stop asserting a direction the evidence
  // does not carry.
  if (bundle !== null && backend !== null) {
    if (backend > bundle) {
      return { state: BACKEND_AHEAD, ok: true,
        text: 'Backend is ahead of your app bundle. A backend-only change does '
            + 'this and needs no app update.' };
    }
    if (bundle > backend) {
      return { state: APP_AHEAD, ok: false,
        text: 'The backend deploy has not landed yet — your app is ahead of '
            + 'the server.' };
    }
  }

  // Different commits, and no usable pair of times. Say exactly that, without
  // the alarm the old wording carried.
  return { state: DIFFERENT, ok: false,
    text: 'App and backend are on different commits.' };
}

export default { buildVerdict, IN_SYNC, BACKEND_AHEAD, APP_AHEAD, DIFFERENT, UNKNOWN };
