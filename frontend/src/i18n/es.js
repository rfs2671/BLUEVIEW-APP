// Spanish catalogue. Key-identical to ./en.js for every namespace it declares —
// the test asserts that, so a key added to one and forgotten in the other fails
// CI instead of silently falling back to English.
//
// It does NOT declare every namespace en.js does. A logbook is a legal record
// filed with the DOB and is written in English; Spanish belongs where a WORKER
// must understand what he is signing (the gate, and any worker signature or
// acknowledgment line inside a logbook). Namespaces that are entirely CP-facing
// are English-only and are listed in EN_ONLY_NAMESPACES in i18n.test.cjs, which
// asserts they are absent here rather than merely tolerating the gap.
//
// Every string here was moved verbatim out of the component that used to own
// it.

export default {
  // ── DELIBERATELY ABSENT, NOT MISSING ──────────────────────────────────────
  //   dailyJobsite, logbookView, review, finalize, reportPreview
  //
  // A logbook is a legal record filed with the DOB, so it is written in
  // English — a DOB inspector reads English. Spanish belongs where a WORKER has
  // to understand what he is signing: the gate, and any line a worker signs or
  // acknowledges inside a logbook.
  //
  // All five are CP-, inspector- or admin-facing: the daily jobsite editor, the
  // filed-log viewer, the flagged-worker review screen, the lock/refusal
  // prompts, and the admin report preview. No worker signs anything on any of
  // them — every SignaturePad under app/logbooks/ captures the COMPETENT
  // PERSON's signature, and a worker's signature is captured at the gate and
  // rendered here read-only.
  //
  // Safe by construction: translate() falls back to DEFAULT_LOCALE when the
  // active locale has no entry (src/i18n/index.js), so a Spanish-locale user
  // sees English rather than a blank or a raw key. i18n.test.cjs lists these in
  // EN_ONLY_NAMESPACES and asserts they are ABSENT here — a partial declaration
  // or a well-meant re-translation FAILS.

  // ── src/components/SignaturePad.js — 5 keys, was the local SIG_STRINGS ─────
  //
  // KEPT, AND NOT AN OVERSIGHT — do not strip this in a future audit.
  //
  // Strictly this is CP-facing today: SignaturePad renders only on CP screens,
  // so by the rule above it would go. It stays because it is the exact
  // component a WORKER would use if worker signing moves in-app, which is on
  // the roadmap. Deleting its Spanish would delete the mechanism the
  // worker-signature exception depends on, and it would have to be rebuilt.
  //
  // It is therefore held to the NORMAL strict parity rules — key-identical with
  // en, no blanks, no untranslated copies — not to the EN-only allowlist.
  signature: {
    verified: 'VERIFICADO',
    unaffirmed: 'SIN AFIRMAR',
    affirm: 'Afirmar para este documento',
    clearResign: 'Borrar y Firmar de nuevo',
    unaffirmedHint: 'Firma heredada — toque Afirmar para dar fe de este documento.',
  },


};
