import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * A CONSENT THAT WAS GIVEN, REMEMBERED ON THE DEVICE.
 *
 * ── WHY THE GATE NEEDS THIS ─────────────────────────────────────────────────
 *
 * The consent gate refuses a signature whenever it cannot confirm consent,
 * including when the server is unreachable. That is safe on the superintendent
 * log, which is online-only: a signature there already required a reachable
 * server, so the gate added no new failure mode.
 *
 * IT IS NOT SAFE ON THE OTHER TWELVE. Every one of them is local-first — they
 * autosave to a local draft and push when a connection returns, because a CP
 * fills these in cellars, in shafts, and below grade. Extending a fail-closed
 * network check to them would stop a man signing his daily log in exactly the
 * place offline support exists for.
 *
 * ── ONLY A YES IS EVER CACHED ───────────────────────────────────────────────
 *
 * There is no code path in this module that writes a negative. Not "declined",
 * not "unknown", not "not yet". The absence of an entry means ASK, and the only
 * thing an entry can say is that this person agreed.
 *
 * That asymmetry is what makes the cache safe to trust offline. A cached yes
 * can only become wrong if the person withdrew consent — which the wording says
 * is done by telling a company administrator, out of band, and which this
 * application does not record, transmit or observe in any form. So the cached
 * value cannot go stale relative to anything the app knows: there is no state
 * on the server that would contradict it.
 *
 * A cached NO, by contrast, would go stale the moment he agreed on another
 * device, and would lock him out with no way to clear it. It is not cached.
 *
 * ── AND AN OLDER VERSION STILL COUNTS, OFFLINE ──────────────────────────────
 *
 * `readConsented` returns the entry whatever version it names, and the caller
 * honours it. THIS IS DELIBERATE AND SHOULD NOT BE TIGHTENED.
 *
 * A version mismatch seen while offline is not evidence that he withdrew. It is
 * evidence that the wording changed while he had no signal — a fact about the
 * publisher, not about him. Refusing to let a man sign at the bottom of a shaft
 * because a wording revision landed that morning is the wrong failure
 * direction: he agreed, in terms that name no document and no date, and nothing
 * he did has changed.
 *
 * NOTHING IS LOST BY ALLOWING IT. The server re-checks the version on the next
 * signature made with a connection, and a genuinely stale consent is caught
 * there and re-asked — online, where he can read the new wording, which is the
 * only place re-asking is any use.
 *
 * The version is stored anyway, so a reader can tell WHICH wording was honoured
 * and when. Storing it is not the same as gating on it.
 *
 * ── KEYED PER PERSON, AND NOT CLEARED ON LOGOUT ─────────────────────────────
 *
 * The key carries the user id, so signing in as somebody else cannot inherit
 * another person's agreement. It survives logout on purpose: a CP who signs out
 * and back in on his own phone, with no signal, must still be able to sign. The
 * stored value is the fact that user X agreed and the wording version — nothing
 * a person would mind being on their own device.
 */

const PREFIX = 'esra_consent_ok:';

const keyFor = (userId) => (userId ? `${PREFIX}${String(userId)}` : null);

/**
 * Remember that this person agreed. THE ONLY WRITER IN THIS MODULE.
 *
 * Never throws: a device that cannot write this must still let him sign the log
 * he is standing in front of. Losing the cache costs one round trip next time,
 * and a storage failure is not a reason to refuse a signature.
 */
export async function rememberConsent(userId, version) {
  const k = keyFor(userId);
  if (!k) return false;
  try {
    await AsyncStorage.setItem(k, JSON.stringify({
      version: version || null,
      at: new Date().toISOString(),
    }));
    return true;
  } catch (_e) {
    return false;
  }
}

/**
 * What this device remembers, or null.
 *
 * null means NOTHING IS REMEMBERED. It does not mean he has not consented, and
 * a caller must not report it as a refusal — it means ask the server, and if
 * the server cannot be asked, ask him.
 */
export async function readConsent(userId) {
  const k = keyFor(userId);
  if (!k) return null;
  try {
    const raw = await AsyncStorage.getItem(k);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    // A malformed entry is treated as nothing remembered rather than as a yes.
    // The cache is permission to sign; it has to be readable to be believed.
    return (parsed && typeof parsed === 'object') ? parsed : null;
  } catch (_e) {
    return null;
  }
}

/**
 * Forget — for a person who declines, or for tests.
 *
 * NOT called by the gate on a server "no". A server no is authoritative on its
 * own and needs no cache entry to contradict; clearing here would only matter
 * if a negative were ever cached, and none is.
 */
export async function forgetConsent(userId) {
  const k = keyFor(userId);
  if (!k) return;
  try { await AsyncStorage.removeItem(k); } catch (_e) { /* nothing to undo */ }
}

export default { rememberConsent, readConsent, forgetConsent };
