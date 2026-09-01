import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'expo-router';
import { esraConsentAPI } from '../utils/api';
import { consentState, canSign, UNKNOWN } from '../utils/esraConsentState';

/**
 * The consent gate, for a screen that is about to apply a signature.
 *
 * ── ONE QUESTION, ASKED AT ONE MOMENT ───────────────────────────────────────
 *
 * `ensure()` returns TRUE only when a signature may be applied. Every other
 * outcome routes to /consent and returns FALSE, so the caller's submit path is
 * one line and cannot accidentally proceed.
 *
 * IT DOES NOT FETCH ON MOUNT. The question is asked when he tries to SIGN, not
 * when the screen opens:
 *
 *   A CONSENTED USER — everyone after the first time — should not pay a round
 *   trip for a question already answered, on a screen he opens daily.
 *
 *   AND AN OUTAGE MUST NOT PRESENT ITSELF AS A CONSENT PROBLEM AT OPEN. If the
 *   server is unreachable he still has a form to fill; telling him about
 *   consent before he has typed anything turns a wait into a wall.
 *
 * ── THE STATE LOGIC IS NOT IN HERE ──────────────────────────────────────────
 *
 * esraConsentState.js is pure and is what the tests execute. This owns the I/O
 * and the navigation only. The rule about what counts as consent is the part
 * that has to be provable, and a rule tangled in useEffect can only be
 * asserted by reading it.
 *
 * ── AND IT PUSHES RATHER THAN REPLACES ──────────────────────────────────────
 *
 * `push` keeps the editor mounted underneath, so his half-filled log survives
 * and `router.back()` returns him to it. `replace` would discard it. That is
 * the single most important line in this file.
 */
export function useEsraConsent() {
  const router = useRouter();
  const [state, setState] = useState(UNKNOWN);
  const [busy, setBusy] = useState(false);

  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  /** Ask the server. Never throws; a failure IS the UNKNOWN state. */
  const read = useCallback(async () => {
    try {
      const next = consentState(await esraConsentAPI.get());
      if (alive.current) setState(next);
      return next;
    } catch (_e) {
      if (alive.current) setState(UNKNOWN);
      return UNKNOWN;
    }
  }, []);

  /**
   * May a signature be applied right now?
   *
   * True, silently, when consent is on file. Otherwise routes to the agreement
   * and returns false — including on UNKNOWN, deliberately: a signature
   * applied while we cannot tell whether consent exists is the defect this
   * whole path removes, and the screen names the outage rather than blocking
   * mutely.
   */
  const ensure = useCallback(async () => {
    setBusy(true);
    const next = await read();
    if (!alive.current) return false;
    setBusy(false);
    if (canSign(next)) return true;
    router.push('/consent');
    return false;
  }, [read, router]);

  return { state, busy, ensure };
}

export default useEsraConsent;
