import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'expo-router';
import { esraConsentAPI } from '../utils/api';
import { useAuth } from '../context/AuthContext';
import { rememberConsent, readConsent } from '../utils/consentCache';
import { consentState, canSign, READY, UNKNOWN } from '../utils/esraConsentState';

/**
 * A SIXTH REASON, AND IT IS NOT A SERVER STATE.
 *
 * The server said nothing — it could not be reached — and the device remembered
 * a yes from a previous read. Kept apart from READY because it answers a
 * different question: READY is "the server confirms he has agreed", CACHED is
 * "he agreed once and we are honouring it with no signal". A screen that wants
 * to say so can; nothing is required to.
 */
export const CACHED = 'cached';

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
  const { user } = useAuth();
  const userId = user?.id || user?._id || null;
  const [state, setState] = useState(UNKNOWN);
  const [busy, setBusy] = useState(false);

  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  /**
   * Ask the server. Never throws; a failure IS the UNKNOWN state.
   *
   * A confirmed yes is REMEMBERED on the way past. That write is what lets the
   * same person sign later with no signal, and it happens here rather than at
   * the call site so no caller can forget it.
   */
  const read = useCallback(async () => {
    try {
      const payload = await esraConsentAPI.get();
      const next = consentState(payload);
      if (next === READY) {
        await rememberConsent(userId, payload?.agreed_version || payload?.current_version);
      }
      if (alive.current) setState(next);
      return next;
    } catch (_e) {
      if (alive.current) setState(UNKNOWN);
      return UNKNOWN;
    }
  }, [userId]);

  /**
   * May a signature be applied right now, AND WHY NOT?
   *
   * `{ ok, reason }`. ok true, silently, when consent is on file. Otherwise it
   * routes to the agreement and returns false — including on UNKNOWN,
   * deliberately: a signature applied while we cannot tell whether consent
   * exists is the defect this whole path removes, and the screen names the
   * outage rather than blocking mutely.
   *
   * THE REASON IS CARRIED BECAUSE FOUR REFUSALS ARE NOT ONE. `ensure()`
   * collapses NOT_AGREED, STALE, DECLINED and UNKNOWN into a single false, so a
   * caller cannot tell a man who declined from a man whose server is down, and
   * cannot say anything true to either. `reason` is one of the states from
   * esraConsentState.js, or CACHED when an offline yes was honoured. Reading
   * `state` instead does not work: it is React state and is not settled by the
   * time this promise resolves.
   */
  const ensureWithReason = useCallback(async () => {
    setBusy(true);
    const next = await read();
    if (canSign(next)) {
      if (alive.current) setBusy(false);
      return { ok: true, reason: READY };
    }

    // ── THE SERVER COULD NOT BE ASKED ──────────────────────────────────────
    //
    // ONLY on UNKNOWN. A server answer of not-agreed, superseded or declined is
    // AUTHORITATIVE and the cache is never consulted against it — the cache
    // holds only a yes, so consulting it there could only ever overturn a real
    // no with a stale one.
    //
    // A REMEMBERED YES IS HONOURED WHATEVER VERSION IT NAMES. A version
    // mismatch seen offline is not evidence he withdrew; it is evidence the
    // wording changed while he had no signal, which is a fact about the
    // publisher and not about him. He agreed, in terms naming no document and
    // no date, and nothing he did has changed. Refusing a signature at the
    // bottom of a shaft because a revision landed that morning is the wrong
    // failure direction, and nothing is lost by allowing it: the server
    // re-checks the version on the next signature made with a connection, and
    // catches a genuinely stale consent there — online, where he can actually
    // read the new wording.
    //
    // DO NOT TIGHTEN THIS TO A VERSION COMPARISON. See consentCache.js.
    if (next === UNKNOWN) {
      const remembered = await readConsent(userId);
      if (remembered) {
        if (alive.current) setBusy(false);
        return { ok: true, reason: CACHED };
      }
    }

    if (!alive.current) return { ok: false, reason: next };
    setBusy(false);
    router.push('/consent');
    return { ok: false, reason: next };
  }, [read, router, userId]);

  /**
   * The one-line form every signing screen uses: `if (!(await ensure())) return;`
   *
   * A BOOLEAN, AND IT MUST STAY ONE. Thirteen call sites negate this value
   * directly, so anything truthy returned on a refusal — an object, a reason
   * string — would read as permission and apply the signature it was written to
   * stop. A screen that wants to say WHICH refusal it was calls
   * ensureWithReason and reads `.ok` itself.
   */
  const ensure = useCallback(
    async () => (await ensureWithReason()).ok,
    [ensureWithReason],
  );

  return { state, busy, ensure, ensureWithReason };
}

export default useEsraConsent;
