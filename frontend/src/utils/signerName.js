/**
 * signerName.js
 * Place at: frontend/src/utils/signerName.js
 *
 * WHOSE NAME GOES ON A STATUTORY SIGNATURE, AND WHERE IT COMES FROM.
 *
 * The superintendent log sourced its printed name from `useCpProfile` — a
 * cache written by `autoSave` AFTER a successful signature. So it is blank for
 * anyone who has never signed, which on a screen that has never been signable
 * is EVERYONE. Fixing the prop names alone would have prefilled it for the one
 * CP with a cached profile and left the next man with an empty field.
 *
 * THE AUTHENTICATED SESSION IS THE SOURCE. It is the same value the server
 * records as `signer_name` on a signature event, it exists on every signing
 * path, and it is never blank for a logged-in person.
 *
 * PRECEDENCE, most specific first:
 *
 *   1. what he has TYPED this session      — never overwritten, at any point
 *   2. what a rehydrated DRAFT stored      — his own earlier answer on this doc
 *   3. the authenticated SESSION           — full_name, then name
 *   4. the cached CP PROFILE               — last, and only as a fallback
 *
 * FROM HIS SESSION, NEVER THE DEVICE'S LAST USER. A superintendent signing on
 * somebody else's phone must see HIS name, and the cached profile on a shared
 * device is the previous user's. Sourcing (4) ahead of (3) would put another
 * man's name under a licensed signature — the same fabrication class as
 * stamping a departure time he did not give. It is kept only because a
 * pre-session draft may legitimately have nothing else, and it is behind the
 * session for that reason.
 *
 * EDITABLE THROUGHOUT. This computes a DEFAULT, never a lock. The field stays
 * a text input at every step so a signer can correct it — a name he cannot
 * change is as wrong as a name he did not give.
 */

/** The authenticated principal's display name, or '' when there is none. */
export function sessionSignerName(user) {
  if (!user || typeof user !== 'object') return '';
  const candidates = [user.full_name, user.name, user.display_name];
  for (const c of candidates) {
    if (typeof c === 'string' && c.trim()) return c.trim();
  }
  return '';
}

/**
 * The name to show, given everything known.
 *
 * @param {object} o
 * @param {string} o.typed      current field state (1)
 * @param {string} o.stored     value from a rehydrated draft (2)
 * @param {object} o.user       authenticated principal (3)
 * @param {string} o.profileName cached CP profile name (4)
 * @returns {string}
 */
export function resolveSignerName({ typed, stored, user, profileName } = {}) {
  const t = typeof typed === 'string' ? typed.trim() : '';
  if (t) return t;
  const s = typeof stored === 'string' ? stored.trim() : '';
  if (s) return s;
  const session = sessionSignerName(user);
  if (session) return session;
  const p = typeof profileName === 'string' ? profileName.trim() : '';
  return p;
}

export default { resolveSignerName, sessionSignerName };
