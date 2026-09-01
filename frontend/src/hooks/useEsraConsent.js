import { useCallback, useEffect, useRef, useState } from 'react';
import { esraConsentAPI } from '../utils/api';
import {
  consentState, canSign, versionToAgree, UNKNOWN,
} from '../utils/esraConsentState';

/**
 * The consent gate, as a hook, so a screen wires it in four lines.
 *
 * THE STATE LOGIC IS NOT IN HERE. esraConsentState.js is pure and is what the
 * tests execute; this owns only the I/O and the React state around it. That
 * split is deliberate: the rule about what counts as consent is the part that
 * has to be provable, and a rule tangled in useEffect can only be asserted by
 * reading it.
 *
 * IT DOES NOT FETCH ON MOUNT. The question is asked when he tries to SIGN, not
 * when the screen opens. Two reasons:
 *
 *   A CONSENTED USER — which is every user, after the first time — should
 *   never pay a round trip for a question already answered, on a screen he
 *   opens daily.
 *
 *   AND AN OUTAGE MUST NOT PRESENT ITSELF AS A CONSENT PROBLEM AT OPEN. If the
 *   server is unreachable he has a form to fill regardless; telling him about
 *   consent before he has typed anything turns a wait into a wall.
 *
 * `ensure()` returns TRUE only when a signature may be applied. Every other
 * outcome opens the modal and returns FALSE, so the caller's submit path reads
 * as one line and cannot accidentally proceed.
 */
export function useEsraConsent() {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState(UNKNOWN);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // Guards a setState after unmount — this runs off a submit, and he may leave
  // the screen while the request is in flight.
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  /** Ask the server. Never throws; a failure IS the UNKNOWN state. */
  const read = useCallback(async () => {
    try {
      const payload = await esraConsentAPI.get();
      const next = consentState(payload);
      if (alive.current) {
        setState(next);
        // Only ever the server's wording, and only when it sent some. Keeping
        // a previous text on a failed read would show him words this response
        // did not carry.
        setText(typeof payload?.current_text === 'string' ? payload.current_text : '');
      }
      return { state: next, payload };
    } catch (_e) {
      if (alive.current) { setState(UNKNOWN); setText(''); }
      return { state: UNKNOWN, payload: null };
    }
  }, []);

  /**
   * May a signature be applied right now?
   *
   * Returns true and does nothing visible when consent is on file. Otherwise
   * opens the modal in whatever state the read produced and returns false.
   */
  const ensure = useCallback(async () => {
    setBusy(true);
    setError('');
    const { state: next } = await read();
    if (!alive.current) return false;
    setBusy(false);
    if (canSign(next)) return true;
    setOpen(true);
    return false;
  }, [read]);

  /**
   * Record the agreement, then RE-READ rather than assuming.
   *
   * THE POST'S OWN ANSWER IS NOT TAKEN AS THE NEW STATE. It reports what this
   * request did (`recorded` / `already`), which is not the same question as
   * "may he sign now" — and the server checks the version rather than trusting
   * it, so a stale client is refused here. Reading back means the gate opens
   * on the server's answer to the actual question, the way it would on any
   * later attempt.
   */
  const agree = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      const { payload } = await read();
      const version = versionToAgree(payload);
      if (!version) {
        if (alive.current) {
          setBusy(false);
          setError('');
        }
        return false;
      }
      await esraConsentAPI.agree(version);
      const { state: after } = await read();
      if (!alive.current) return false;
      setBusy(false);
      if (canSign(after)) { setOpen(false); return true; }
      return false;
    } catch (e) {
      if (alive.current) {
        setBusy(false);
        // The server names the condition; the code is surfaced rather than its
        // English prose, matching LogbookLockBar's gateCopy convention.
        setError(e?.response?.data?.detail?.code || '');
      }
      return false;
    }
  }, [read]);

  const retry = useCallback(async () => {
    setBusy(true);
    setError('');
    await read();
    if (alive.current) setBusy(false);
  }, [read]);

  return {
    open, state, text, busy, error,
    ensure, agree, retry,
    close: () => setOpen(false),
  };
}

export default useEsraConsent;
