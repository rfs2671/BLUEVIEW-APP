/**
 * THE REFUSAL, WITH THE NAME IN IT.
 *
 * The server names the condition; the client owns the wording — the rule every
 * `code_*` entry in the `finalize` namespace follows. This is that same rule
 * with ONE addition: a refusal may carry a FACT the copy needs, and
 * NOT_THE_REGISTERED_SUPERINTENDENT carries the only fact that makes it
 * actionable — WHO may file.
 *
 *     {"code": "NOT_THE_REGISTERED_SUPERINTENDENT",
 *      "message": "...Michael Cespedes is registered on this project...",
 *      "registered_name": "Michael Cespedes"}
 *
 * The server's English `message` is still never rendered; `registered_name` is
 * a NAME, not prose, so interpolating it keeps the wording on this side of the
 * wire where the convention wants it.
 *
 * ── WHY TWO KEYS ────────────────────────────────────────────────────────────
 *
 * `code_X`        nameless. Safe anywhere a code is all there is.
 * `code_X_NAMED`  carries `{name}`, and is reached ONLY when a detail actually
 *                 supplies one.
 *
 * Because LogbookLockBar renders this same namespace from a code STORED by
 * recordFinalizeError — a code with no response and no detail beside it — a
 * single `{name}` sentence would paint a literal "{name}" onto that banner.
 * Splitting the sentence is what lets the lock bar stay exactly as it is.
 *
 * ── AND WHY IT IS A MODULE ──────────────────────────────────────────────────
 *
 * gateCopy is four lines copied into eleven editors and the lock bar. This does
 * not go and change all twelve — it is imported by the one screen that meets a
 * named refusal, and it behaves IDENTICALLY to the copies for every other code
 * (csRefusalCopy.test.cjs asserts that against all fifteen of them), so the
 * others may adopt it whenever they have a reason to rather than because this
 * PR moved their cheese.
 */

/** The slot the named sentence carries. */
export const NAME_SLOT = '{name}';

/** Suffix of the variant that names the registered superintendent. */
export const NAMED_SUFFIX = '_NAMED';

/**
 * The name the server sent with a refusal, or null.
 *
 * `registered_name` is `reg.get("full_name")` on a registration row, so it can
 * legitimately be absent or blank — an admin registered a licence and left the
 * name empty. Absent is a different sentence, not a broken one.
 */
export function registeredName(detail) {
  const raw = detail && typeof detail === 'object' ? detail.registered_name : null;
  const text = typeof raw === 'string' ? raw.trim() : '';
  return text || null;
}

/**
 * The sentence to show for a refusal code.
 *
 * `t` is a namespaced translator over `finalize` (useT('finalize')), which
 * returns the KEY on a miss — that is how an unmapped code is detected, and the
 * rule is unchanged: an unmapped code falls back to `genericError`.
 *
 * The ONLY departure: when the copy for a code exists in a `_NAMED` variant AND
 * the detail carries a name, that variant is used with the name substituted.
 * Everything else routes exactly as the shipped four-liner did.
 */
export function refusalCopy(code, detail, t) {
  const generic = t('genericError');
  if (!code) return generic;

  const name = registeredName(detail);
  if (name) {
    const namedKey = `code_${code}${NAMED_SUFFIX}`;
    const named = t(namedKey);
    if (named && named !== namedKey) {
      return String(named).split(NAME_SLOT).join(name);
    }
  }

  const key = `code_${code}`;
  const copy = t(key);
  if (!copy || copy === key) return generic;
  // A nameless sentence that still holds a slot would paint "{name}" at him.
  // It cannot happen with the catalogue as written — the test pins that — and
  // if it ever does, the generic message is the lesser failure.
  return String(copy).indexOf(NAME_SLOT) >= 0 ? generic : copy;
}

export default { NAME_SLOT, NAMED_SUFFIX, registeredName, refusalCopy };
