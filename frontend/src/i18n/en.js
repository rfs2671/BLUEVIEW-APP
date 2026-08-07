// English catalogue. Keys are grouped by NAMESPACE — one namespace per screen
// or component, so two surfaces can both own a `title` without colliding.
//
// Every string here was moved verbatim out of the component that used to own
// it. Nothing was reworded; migrating a component onto this layer must not
// change a single rendered character.

export default {
  // ── app/logbooks/review.jsx — 47 keys, was the local TRANSLATIONS map ──────
  review: {
    title: 'Check-In Review',
    subtitle: 'Workers needing a decision',
    selectProject: 'Select a project',
    noProjects: 'No projects assigned to you yet.',
    empty: 'Nothing to review',
    emptyHint: 'No flagged check-ins on this project.',
    loadError: 'Could not load flagged check-ins',
    // OFFLINE vs EMPTY. "Nothing to review" is a compliance claim — it must
    // only ever appear when the SERVER said the list is empty.
    offlineLoad: 'Not loaded — this device cannot reach the server. This is NOT a confirmation that there is nothing to review.',
    errorLoad: 'The flagged check-ins could not be read. Pull to refresh or try again.',
    offlineProjects: 'Your project list could not be loaded, so this screen has nothing to select. Reconnect and pull to refresh.',
    errorProjects: 'Your project list could not be read. Pull to refresh or try again.',
    offlineWrite: 'Offline — nothing recorded',
    offlineWriteHint: 'The decision was NOT saved. Reconnect and try again.',
    expiredSst: 'Expired SST',
    expiredOn: 'expired',
    needsTrade: 'No trade assigned',
    needsTradeHint: 'This project had no trades set up when they checked in.',
    approve: 'Approve',
    sendHome: 'Send home',
    approved: 'Approved',
    sentHome: 'Sent home',
    by: 'by',
    reviewFailed: 'Could not record the decision',
    approvedToast: 'Worker approved to stay on site',
    sentHomeToast: 'Sent-home decision recorded',
    viewCard: 'Tap card to enlarge',
    noCard: 'No card image on file',
    checkedInAt: 'Checked in',
    refresh: 'Refresh',
    close: 'Close',
    assignTrade: 'Assign trade',
    chooseTrade: 'Choose a trade & company',
    assign: 'Assign',
    cancel: 'Cancel',
    assigned: 'Trade assigned',
    assignedToast: 'Trade assigned to this check-in',
    assignFailed: 'Could not assign the trade',
    noRoster: 'This project has no trades configured yet — an admin must add them first.',
    // Cert-review reason codes (backend stores the CODE; text lives here).
    unknownSst: 'Unverified SST',
    admit: 'Admit',
    admittedUnverified: 'Admitted — credential still unverified',
    unknownAdmitHint: 'Admitting records entry only — it does not verify the card. The credential stays flagged for review.',
    reason_CLASS_UNVERIFIED: 'Card class could not be read — verify the card',
    reason_EXPIRY_IMPLAUSIBLE: 'Expiry date is implausible — re-scan or verify',
    reason_EXPIRY_UNPARSEABLE: 'Expiry date could not be read — verify the card',
    reason_EXPIRY_CONFLICT: 'Two scans disagree on the expiry — verify the card',
    reason_DUPLICATE_SST: 'Duplicate SST records — resolve to one',
  },

  // ── src/components/SignaturePad.js — 5 keys, was the local SIG_STRINGS ─────
  // Only the affirmation UI is localized. The rest of the pad (title, "SIGNER
  // NAME", "Draw signature here", "Clear", "Confirm Signature", the two hints)
  // is still hardcoded English in the component and is NOT moved here — that
  // would be a copy change, not a wiring change.
  signature: {
    verified: 'VERIFIED',
    unaffirmed: 'UNAFFIRMED',
    affirm: 'Affirm for this document',
    clearResign: 'Clear & Re-sign',
    unaffirmedHint: 'Inherited signature — tap Affirm to attest for this document.',
  },
};
