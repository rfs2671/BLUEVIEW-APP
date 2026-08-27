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

  // ── src/components/LogbookLockBar.jsx — the finalize completeness gate ─────
  // The server rejects an incomplete finalize with a machine CODE only
  // (backend/server.py:14638-14645) because the convention here is that the
  // server names the condition and the CLIENT owns the wording. The `code_`
  // prefix mirrors review's `reason_` codes: the code is looked up
  // dynamically, so it must not be able to collide with a UI key in this
  // namespace. An unmapped code falls back to `genericError`, exactly as
  // BLOCK_LABELS does in backend/checkin.html:1508-1518. The server's English
  // `detail` is never rendered.
  finalize: {
    errorTitle: 'Could not finalize',
    genericError: 'This log could not be finalized. Please try again.',
    code_FINALIZE_EMPTY_LOG: 'This log is empty. Fill it in before finalizing — a finalized log can only be corrected by an amendment.',
    code_FINALIZE_MISSING_CP_SIGNATURE: 'This log is not signed. Sign it before finalizing — a finalized log can only be corrected by an amendment.',
    // Shown when a log frozen on THIS DEVICE was refused by the server on the
    // reconnect drain. Persistent, not a toast: the drain runs in the
    // background with no screen, so this is the next place the CP can see it.
    notLockedTitle: 'NOT LOCKED ON THE SERVER',
    notLockedHint: 'This log is frozen on this device only. It stays queued and will retry, but the server keeps refusing it until the problem above is fixed.',
    notLockedHintEditor: 'The server refused this log, so it is NOT locked. Your draft is still editable — fix the problem above and submit again.',
    // The submit-time gate on create/update (server.py create_logbook and
    // update_logbook). Same machine-code convention as the finalize codes
    // above: the server names the condition, the client owns the wording.
    code_SUBMIT_EMPTY_LOG: 'This log is empty. Fill it in before submitting.',
    code_SUBMIT_MISSING_CP_SIGNATURE: 'This log is not signed. Sign it before submitting.',
    // TWO REFUSALS, NOT ONE, and the difference is which tap fixes it.
    //
    // The server gate now asks whether the signature is AFFIRMED for this
    // document, not merely present. A CP looking at his own signature on the
    // screen and being told "this log is not signed" is being given the wrong
    // instruction: his credential IS there, the affirmation of THIS record is
    // what is missing, and the fix is Affirm rather than sign again. The pad
    // already draws this distinction — affirmationHintKey returns
    // submitNeedsAffirmation vs submitNeedsSignature for the same reason.
    //
    // SHIPPED BEFORE THE SERVER EMITS IT, deliberately. gateCopy() falls back
    // to genericError for a code it does not know, so a server switching
    // first would show "something went wrong" on every device that has not
    // fetched this bundle — and the device still writing the bad shape is
    // the one least likely to be current.
    code_SUBMIT_SIGNATURE_NOT_AFFIRMED: 'Your signature is on this log but not affirmed for it. Tap your signature to affirm, then submit. You do not need to sign again.',
    // A safety orientation may be CREATED without a trade — the gate check-in
    // writes one that way, and a worker at the turnstile is never blocked for
    // an admin's unfinished roster. It may not be SUBMITTED without one: the
    // record is entirely about what this man was oriented TO do on this site.
    // The server sends the worker's name alongside the code; the orientation
    // screen names him and offers the fix on his row, so this generic sentence
    // is the fallback for anywhere else the code surfaces (the reconnect drain
    // has no screen and no row to point at).
    code_SUBMIT_MISSING_TRADE: 'This worker has no trade assigned. Assign one before submitting the orientation.',
    // Raised for the two records that ARE a list of rows — the certification
    // register and the sign-in sheet — when every row is one the PDF renderer
    // would refuse to print. The document would come out blank. Not a
    // completeness rule: it says the record contains nothing at all, which is
    // the one thing that is true of it regardless of which form it is.
    code_SUBMIT_NO_CONTENT: 'Every row on this log is empty, so there is nothing to file. Fill in at least one before submitting.',
    // Raised by the reconnect DRAIN, not by a screen — a pre-shift draft
    // written before the injury/PPE gate shipped replays with both answers
    // null, and no client gate can reach that path. It names the fix rather
    // than the failure: the CP is reading this on a banner, away from the
    // form, and "something went wrong" gives him nothing to do.
    code_SUBMIT_INCOMPLETE_WORKER_ANSWERS: 'Answer injury and PPE for every worker, then resubmit.',
    // ── THE LOCAL SAVE FAILED AND THE PUSH DID NOT LAND ─────────────────────
    // Every other failure on this screen leaves the log somewhere: refused by
    // the server but still in the draft, or offline but queued for the drain.
    // This one leaves it nowhere. `writeDraft` returns false rather than
    // throwing, so a full or broken store used to pass silently, the key was
    // queued anyway, and the CP was told a signed log existed that the drain
    // would later find empty or stale.
    //
    // The copy says the three things he cannot see: nothing was filed, nothing
    // is queued, and what he typed is still on the screen in front of him — so
    // he does not navigate away and lose it while looking for the fix.
    localSaveFailedTitle: 'Not saved — nothing was filed',
    localSaveFailed: 'This device could not store the log, and it did not reach the server either. Nothing was filed and nothing is queued to retry. Your entries are still on this screen. Free up space on the device, then submit again.',
    // Shown under a Submit button disabled because no signature is on file. A
    // CP sets his signature by signing on the log itself — there is no separate
    // profile screen for it (nothing under app/settings or app/profile writes
    // cp_signature) — so the copy points at the pad directly above the button.
    submitNeedsSignature: 'Sign above to submit. Your signature is saved for next time.',
    // A DIFFERENT SENTENCE, because it is a different fix. The signature above
    // is his and it is on screen — what is missing is his affirmation that it
    // applies to THIS document, which is the one thing that cannot be inherited
    // from a previous log. Telling a man with a signature on screen that he has
    // no signature is how he learns to ignore the hint.
    submitNeedsAffirmation: 'Tap your signature above to affirm it for this log. An inherited signature cannot be reused.',
    submitSignatureLoading: 'Loading your saved signature...',
    // A queued draft the server REFUSED on the reconnect drain. Distinct from
    // notLocked* above: nothing was created, so nothing is frozen anywhere —
    // the work is still on this device and still editable.
    notPushedTitle: 'NOT SAVED TO THE SERVER',
    notPushedHint: 'The server refused this log, so it was NOT saved and is NOT locked. Your work is still on this device and still editable — fix the problem above and submit again.',
    // ── THE LOCAL STORE FAILED ────────────────────────────────────────────
    // A THIRD TRUTH, and the two above are both wrong for it.
    //
    // notLockedHint promises a queued retry. notPushedHint promises the work
    // is still on the device. When the local write itself failed, neither is
    // true: nothing is queued, because queuing a key whose draft does not
    // hold this content is how the drain files stale content; and nothing is
    // on the device, because that is the failure. The only copy is the one on
    // screen, and the whole point of saying so is to stop him navigating away
    // from it.
    //
    // A BANNER, NOT A TOAST. He signs and walks — to the next floor, to his
    // truck — and a message that removed itself four seconds later is the same
    // as no message. Same reasoning that made the drain's refusal durable.
    notSavedLocalTitle: 'NOT SAVED ON THIS DEVICE',
    notSavedLocalHint: 'Nothing is queued and nothing will retry. Your entries are still on this screen and nowhere else — do not close this log until you have saved it. Free up space on the device, then submit again.',
    code_LOCAL_SAVE_FAILED: 'This device could not store the log, and it did not reach the server either.',
    // ── THE OTHER REASON, AND IT IS NOT THE SAME PROBLEM ──────────────────
    // He is signing a legal record. A phone holding data the server does not
    // is exactly what he needs to know before he attests to it — so this
    // fires on the ordinary offline path too, where the local write SUCCEEDED
    // and only the push did not land.
    //
    // ONE BANNER, TWO WORDINGS. "Your last change is not saved on this device"
    // and "your work is on this device but not on the server" are different
    // problems with different fixes: the first means do not close the log, the
    // second means do not assume anyone else can see it yet. Telling him WHICH
    // one he has is the whole point of putting it on screen.
    notOnServerTitle: 'ON THIS DEVICE ONLY',
    notOnServerHint: 'This log is saved here and is queued to upload. Nobody else can see it and no inspector can be shown it until it syncs — reconnect when you can. Your work is safe on this device in the meantime.',
    code_NOT_ON_SERVER: 'Saved on this device, but it has not reached the server.',
    // ── THE SAME FAILURE, ONE STEP EARLIER ────────────────────────────────
    // Shown at the SUBMIT GATE, beside the reasons a submit is blocked, when a
    // background autosave has failed. Not a toast: a CP saving every few
    // seconds does not need a message each time, and one that fires constantly
    // is one he stops seeing — which is worse than silence.
    //
    // It does NOT disable Submit. A broken local store does not stop the log
    // reaching the server, and blocking the submit would turn a storage fault
    // into an inability to file at all. It warns; it does not gate.
    autosaveFailedWarning: 'This device is not saving your draft. Your entries are only on this screen — submit now, and do not close the log until it is filed.',
  },

  // ── app/logbooks/daily_jobsite.jsx — the activity photo cap ────────────────
  // The cap is 10 photos PER SUBCONTRACTOR, counted across every activity row
  // that names that sub — not per row. `{n}` is substituted from the single
  // MAX_PHOTOS_PER_SUBCONTRACTOR constant so the sentence can never claim a
  // number other than the one being enforced (it claimed 5 while enforcing 5
  // per row, which for a sub with three rows was 15).
  dailyJobsite: {
    photoCapTitle: 'Limit Reached',
    photoCapBody: 'Maximum {n} photos per subcontractor',
    photoCapRowHint: 'Photo limit reached for this subcontractor',
    // A capture is copied out of the OS cache into documentDirectory before it
    // is recorded, because the cache can be evicted. That copy used to fail
    // SILENTLY and hand back the cache path, so the draft recorded a photo the
    // app did not own and the CP was never told. It is now reported, and the
    // photo is not recorded at all — the wording says both halves: it was not
    // kept, and the fix is to take it again. It never blocks the log.
    photoNotSavedTitle: 'Photo Not Saved',
    photoNotSavedBody: 'This device could not store the photo, so it was not kept. Please take it again.',

    // ── U5 scaffolding for the U1 stepper ────────────────────────────────
    // Every user-facing string the Daily Jobsite Log needs, routed here BEFORE
    // the stepper is built so U1 consumes the layer instead of hardcoding and
    // being retrofitted. The screen on main still carries these as literals;
    // it is replaced wholesale by U1, so it was deliberately NOT churned.
    //
    // DELIBERATELY ABSENT: the DOB form number ("NYC DOB 3301-02"). It is an
    // identifier, not prose — identical in every language — and this catalogue
    // forbids an ES value equal to its EN one, correctly. U1 renders it from a
    // module constant, not from here.
    screenTitle: 'Daily Jobsite Log',

    sectionProject: 'Project Information',
    sectionActivities: 'Activity Details',
    sectionEquipment: 'Equipment on Site',
    sectionInspected: 'Daily inspections',
    sectionObservations: 'Safety Observations / Violations',
    sectionVisitors: 'Visitors / Deliveries / Inspections',
    sectionSignOff: 'Competent Person Sign-Off',

    fieldAddress: 'Address',
    fieldWeather: 'Weather',
    fieldGeneralDescription: "General Description of Today's Activities",
    colCompany: 'COMPANY',
    colWorkDescription: 'WORK DESCRIPTION',
    colWorkLocations: 'WORK LOCATIONS',

    phCompany: 'Company',
    phWorkPerformed: 'Work performed...',
    phWorkLocations: 'Floors, areas...',
    phGeneralDescription: 'Describe the main work performed today...',
    phObservation: 'Describe observation...',
    phResponsibleParty: 'Responsible party',
    phRemedy: 'Remedy / corrective action',
    phVisitors: 'Record any visitors or deliveries...',

    photoTake: 'Take Photo',
    photoGallery: 'Gallery',
    photoLabel: 'Photo',
    pendingAssignment: 'Pending assignment',
    autoPopulatedHint: 'Auto-populated from check-ins. Edit as needed.',

    permissionDeniedTitle: 'Permission Denied',
    permissionDeniedBody: 'Camera roll access is required to upload photos',
    cameraErrorTitle: 'Camera Error',
    cameraErrorBody: 'Could not open camera. Check permissions in device settings.',

    draftSavedTitle: 'Draft Saved',
    saveFailedTitle: 'Could not save log',
    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the log before submitting — this is a signed record.',
    submittedTitle: 'Submitted & Signed',
    submittedOfflineBody: 'Signed and locked on this device. It will sync when you are back online.',

    // ── U4: the activity chips ───────────────────────────────────────────
    // The ranker ORDERS chips; it never pre-selects and never blocks. When a
    // project has no structural system set the app says so rather than letting
    // the CP assume it knows — `structuralSystemUnknown` is that sentence.
    chipsSuggested: 'Suggested from yesterday',
    chipsAlwaysAvailable: 'Always available',
    chipsCatalog: 'All activities',
    // Shown when a crew's four come from its TRADE rather than from the
    // sequence. Most trades' activities carry no edges in the graph, so a
    // crew with a real prior can still get no sequenced chips — and
    // presenting a declaration-ordered list as though yesterday informed it
    // would claim a ranking that does not exist.
    // "Other" is not a pass/fail item — it names nothing, so the CP names
    // what he inspected and the note IS the record.
    phInspectionOther: 'What else did you inspect?',
    chipsFromTrade: 'This trade’s work — not ranked off yesterday.',
    chipsRemembered: 'Used on this project',
    chipOther: 'Other',
    chipOtherPrompt: 'What was the activity?',
    structuralSystemUnknown: 'Structural system not set for this project, so both concrete and CFS activities are shown.',
    chipsNoPriorDay: 'No earlier log to suggest from, so these are the project-start activities.',

    // ── U1: the stepper ──────────────────────────────────────────────────
    // Read by a Competent Person who is older, not technical, outdoors,
    // gloved and one-handed. No screen may need more than twelve words read
    // to know what to do, so these are short sentences, not instructions.
    stepOf: 'Step {n} of {m}',
    back: 'Back',
    next: 'Next',
    cancel: 'Cancel',
    save: 'Save',

    step1Title: 'What was on site',
    step2Title: 'What each crew did',
    step3Title: 'Safety observations',
    step4Title: 'Daily inspections walked',
    step5Title: 'Review and sign',

    // Step 4 — the nine items, walked. A tick could only say the CP LOOKED;
    // on a filed 3301-02 that reads as "this is fine", with no way to say
    // otherwise. Pass, fail, or not walked — and a fail says what failed.
    // The progress pips carry a third state and colour alone is a weak
    // signal outdoors, so the row says it out loud to a screen reader.
    stepsIncomplete: 'Steps {steps} are started but not finished.',
    stepsAllComplete: 'Every step you have been through is complete.',
    // Nothing ticked is NOT the same as nothing on site. Matches
    // logbookView.fNotRecorded and the server's NOT_RECORDED.
    notRecorded: '— Not recorded',
    inspectionsHint: 'Tap Pass or Fail for each. Leave an item blank if you did not walk it.',
    inspectionPass: 'Pass',
    inspectionFail: 'Fail',
    inspectionNoteRequired: 'What failed?',
    phInspectionNote: 'What you found, and where',
    inspectionNoteMissing: 'A failed inspection has to say what failed.',
    inspectionLegacyTicked: 'Ticked on an earlier version of this form, which recorded no result.',
    reviewInspectionsNone: 'None walked',
    reviewInspectionsNotWalked: 'Not inspected',
    reviewInspectionsPassed: 'Passed',

    // Step 1 — the gate roster.
    // "Locked" has to read as PROVENANCE, not as a refusal. The CP is not
    // being denied an edit; the app is telling him where the number came from
    // and that it already matches the check-in record.
    fromGate: 'From gate check-in',
    gateLocked: 'Recorded at the gate',
    // THE HEADCOUNT THE CP CAN CORRECT. Editable on a gate row and a
    // hand-added one; when it stands over a gate count, what the turnstile
    // said stays on screen beside it rather than disappearing as he types.
    headcountLabel: 'Workers on site',
    headcountPlaceholder: '—',
    headcountGateWas: 'Gate recorded {n}',
    crewsOnSite: 'Crews on site',
    noCrews: 'No crews came through the gate for this day.',
    addCrew: 'Add a crew the gate missed',
    addCrewTitle: 'Add a crew',
    // NO CORRECTION AFFORDANCE. Assigning a company or trade does not belong on
    // the daily log: a worker sets his own at check-in, and a CP who has to fix
    // one does it during safety orientation. The three `correctCompany*` keys
    // were removed with the flow. `correctedFrom` stays — company_gate is still
    // recorded as gate provenance and is still shown when it differs.
    correctedFrom: 'Gate recorded',
    unboundCrew: 'Not on the project roster',
    unboundCrewHint: 'Saved and flagged for an admin. It does not block this log.',
    noCrewWorker: 'No crew assigned',
    // A man who came through the gate with no company. He is PRESENT — the log
    // must show he was here — but an activity row represents a COMPANY's work,
    // so he gets no card on Step 2. The copy has to say both halves, and must
    // not read as an error: it is an admin gap, not something he did wrong, and
    // it never blocks the CP.
    unassignedTitle: 'On site, no company assigned',
    unassignedHint: 'He is counted as present. Work is logged per company, so there is nothing to fill in for him until a company is assigned.',
    // A CREW WITH NOBODY ON IT. Stated, never silent: the log has quietly
    // stopped asking this crew for an activity and a location, and a CP who
    // sees one card asking and another not asking, with no reason given,
    // learns to distrust the screen.
    //
    // THE COPY PROMISES NOTHING HE CANNOT DO. There is no headcount edit and
    // no crew delete on this screen, so it says what is true and what will be
    // filed — it does not tell him to "set a headcount" against a field that
    // does not exist.
    emptyCrewTitle: 'No workers recorded',
    emptyCrewHint: 'Nobody was recorded on site for this crew, so the log does not ask what they did. It stays on the record with a count of 0.',
    unassignedNoCard_one: '1 worker on site has no company assigned, so he has no work card here. He is recorded on the previous step.',
    unassignedNoCard_other: '{n} workers on site have no company assigned, so they have no work cards here. They are recorded on the previous step.',
    workers_one: '1 worker',
    workers_other: '{n} workers',
    checkedInAt: 'Checked in {time}',
    checkInTimeUnknown: 'Check-in time not recorded',

    // The roster-integrity warning. This is a compliance claim: a short list
    // shown as complete is a fabricated record, so the CP is told plainly.
    rosterPartialTitle: 'This roster may be incomplete',
    rosterPartialBody: 'The server could not confirm the full list of who was on site. Check the crews below and add anyone missing before you sign.',
    // A MERGE, NOT A FAILED READ. Its own heading, because the two say
    // different things about the server and only one of them is a fault.
    rosterCollapsedTitle: 'Two workers may have been counted once',
    rosterCollapsedBody: 'Two workers with the same name at one company can be counted once. Check the worker counts below.',

    // Step 2 — activity, location, then the camera.
    activityQuestion: 'What did this crew do?',
    // THE SECOND BAND'S OWN QUESTION. The first asks about THIS CREW's work;
    // this asks about the SITE. Deliberately not "More activities" or "Other" —
    // both would read as a continuation of the first list, which is exactly the
    // confusion that made a working four-slot cap look broken for four rounds.
    siteActivityQuestion: 'Anything else on site today?',
    locationQuestion: 'Where on site?',
    locationOther: 'Somewhere else',
    locationOtherPrompt: 'Where was the work?',
    // The camera is unreachable until crew, activity and location are set, so
    // that every photo carries all three before the shutter fires. The reason
    // is stated rather than the button just being absent.
    cameraLockedHint: 'Choose the activity and location first — every photo is labelled with them.',
    photoTaggedWith: 'Photos will be labelled:',
    photosCount_one: '1 photo',
    photosCount_other: '{n} photos',

    // Step 3 — an observation is not savable without a corrective action.
    addObservation: 'Add an observation',
    removeObservation: 'Remove this observation',
    noObservations: 'No safety observations today.',
    observationWho: 'Who is responsible?',
    observationWhoHint: 'Pick a crew that was on site.',
    observationRemedyRequired: 'What was done about it?',
    observationRemedyMissing: 'Add what was done about it before saving.',
    correctedImmediately: 'Fixed on the spot',

    // Weather is fetched, never typed. When the fetch fails the log must SAY
    // so — a blank weather field on a signed record cannot be told apart from
    // a question nobody asked, and with the manual chips gone the CP has no
    // way to fill it in himself.
    // The general description is DRAFTED from the trades of the chips the CP
    // tapped, and he edits it before signing. The copy has to make both halves
    // plain: the app wrote a first line, and it is his to change.
    descriptionDrafted: 'Drafted from the activities you chose. Edit it if it is not right — you are signing this.',
    descriptionEmpty: 'No activities were chosen, so this is blank. Write it yourself if there is anything to record.',

    weatherAutoNote: 'Recorded automatically from the weather service.',
    weatherUnavailableTitle: 'Weather could not be retrieved',
    weatherUnavailableBody: 'The weather service did not answer. This is recorded on the log — it is not left blank.',
    weatherUnavailableOffline: 'This device could not reach the weather service. This is recorded on the log — it is not left blank.',

    // Step 5 — the record read back before it is signed.
    reviewHeading: 'Check this is right',
    reviewNothingYet: 'Nothing recorded',
    submitAndSign: 'Sign and close the day',
    signingClosesDay: 'Signing locks this log. Corrections then need an amendment.',
    // SIGN ONCE, FREEZE AT END OF DAY. He signs and the log stays open
    // for the rest of the day; the 3am sweep closes it. Saying so is the
    // point: a CP told only "filed" would not add the afternoon's photos.
    signedStaysOpen: 'Signed. This log stays open for the rest of the day — add photos or injuries as they happen. It closes overnight.',
    // A crew on site whose work nobody described. stepComplete(2) has held this
    // rule all along and only marked with it; the filed §3301.2 log is where
    // the gap shows.
    crewWorkMissingTitle: 'A crew is missing its work',
    // POSITION AND TOTAL, so he can find the card instead of hunting.
    // The day's description, empty at the moment of signing. He is attesting
    // to that sentence, so the app drafts it when he arrives at review and will
    // not file it unread — and will not file a blank either.
    descriptionRequiredTitle: 'The day needs a description',
    descriptionRequiredHint: 'Add a short description of the day above before signing. It is the first thing the report says.',
    crewNofM: 'Crew {n} of {m}',
    crewMissing_activity: 'has no activity',
    crewMissing_location: 'has no location',
    crewMissingJoin: ' and ',
    savedAutomatically: 'Saved automatically',
  },

  // ── app/logbooks/fall_protection.jsx — the strap log, 2 steps ─────────────
  //
  // EN-ONLY, like every other logbook namespace. See EN_ONLY_NAMESPACES.
  //
  // `standardNotice` IS THE POINT OF THIS BLOCK. OSHA 1926.502(d)(21) mandates
  // the INSPECTION and not a written record of it; the documented inspection
  // comes from ANSI Z359, an industry consensus standard. The same sentence is
  // printed by both PDF renderers from FALL_PROTECTION_NOTICE in
  // backend/server.py — one wording, three surfaces, so the app cannot say two
  // different things about what this log is. If one changes the other changes
  // with it, and fallProtectionModel.test.cjs asserts they still agree.
  fallProtection: {
    screenTitle: 'Fall Protection',
    screenSub: 'Equipment Inspection Log',

    stepOf: 'Step {n} of {m}',
    step1Title: 'Equipment inspected',
    step2Title: 'Check this before you sign',

    registerHint: 'One row per piece of equipment. Workers come from the gate — add a row for anyone the gate did not see.',
    rowOf: 'Row {n} of {m}',
    removeRow: 'Remove this row',
    addRow: 'Add equipment',

    colWorker: 'Worker',
    colCompany: 'Company',
    colEquipment: 'Equipment',
    colEquipmentId: 'ID / serial',
    colMfgDate: 'Manufacture date',
    colResult: 'Inspection result',
    colImpact: 'Impact loaded since last use?',
    colDefect: 'Defect found',
    colAction: 'Action taken',
    colAnchor: 'Anchor point',
    colPhoto: 'Photo (optional)',
    colPhotoRequired: 'Photo (required)',

    phWorker: 'Worker name',
    phCompany: 'Company',
    phEquipmentId: "The manufacturer's marking",
    phDefect: 'What is wrong with it',
    phAction: 'What was done about it',
    phAnchor: 'Where it was anchored',

    yes: 'Yes',
    no: 'No',

    takePhoto: 'Take a photo',
    choosePhoto: 'Choose a photo',
    removePhoto: 'Remove this photo',
    photoPermTitle: 'Permission needed',
    photoPermBody: 'Allow camera and photo access to attach a photo to this row.',
    photoFailedTitle: 'Photo not added',
    photoFailedBody: 'Nothing was attached. Try again.',

    // The row has stopped claiming to know who this is.
    unlinkedNote: 'Not linked to a gate check-in. This row records the name as typed.',

    // 1926.502(d)(19) — mandatory removal. Said, never done for him.
    impactWarning: 'Impact-loaded equipment must be removed from service (OSHA 1926.502(d)(19)). Record it as Removed from service, or change the impact answer.',
    impactWarningTitle: 'Impact-loaded equipment still in service',
    impactWarningBody: 'These rows record impact loading without removing the equipment from service: {rows}. Fix them before you sign, or the record contradicts 1926.502(d)(19).',

    // Fail / Removed needs a defect, an action and a photo.
    missing_defect: 'defect',
    missing_action: 'action taken',
    missing_photo: 'photo',
    adverseIncompleteTitle: 'A failed inspection needs the detail',
    adverseIncompleteBody: 'Fail and Removed from service each need a defect, an action and a photo. Missing on {rows}.',

    // Rows that will be dropped at filing, named before they go.
    reasonUnnamed: 'no worker named',
    reasonNoResult: 'no inspection result',
    notFiledTitle: 'Some rows will not be filed',
    notFiledBody: 'These rows will not be filed: {rows}. Complete them, or delete the row.',

    nothingToFileTitle: 'Nothing to file',
    nothingToFileBody: 'No row records an inspection yet. Record a result before signing.',

    reviewRows: 'Inspections recorded',
    reviewNothingYet: 'Nothing recorded yet',
    rowsCount_one: '{n} inspection',
    rowsCount_other: '{n} inspections',

    standardNotice: 'OSHA 1926.502(d)(21) requires that this equipment be inspected before each use. It does not require a written record of each inspection. This log follows ANSI Z359, an industry consensus standard, and is not a DOB or OSHA filing.',

    next: 'Next',
    submitAndSign: 'Sign and file',
    savedAutomatically: 'Saved automatically as you go.',

    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the log before filing it.',
    submittedTitle: 'Filed',
    submittedBody: 'The fall protection log is filed and frozen.',
    submittedOfflineBody: 'Saved on this device. It will sync when you are back online.',
    saveFailedTitle: 'Could not save',
  },

  // ── app/logbooks/osha_log.jsx — the certification register, 2 steps ────────
  //
  // EN-ONLY, like every other logbook namespace: this is a legal record filed
  // with the DOB and a DOB inspector reads English. See EN_ONLY_NAMESPACES in
  // src/i18n/i18n.test.cjs, where adding a namespace is a deliberate decision.
  //
  // DELIBERATELY ABSENT: the certification NAMES (OSHA 10, SST, Flagman…).
  // They are identifiers on a physical card, identical in every language, and
  // this catalogue forbids an ES value equal to its EN one — correctly. They
  // live in oshaLogModel.CERT_TYPES.
  oshaLog: {
    screenTitle: 'OSHA Log Book',
    screenSub: 'Worker Certifications Register',

    stepOf: 'Step {n} of {m}',
    step1Title: 'Certifications',
    step2Title: 'Review and sign',

    // Step 1 — the register.
    registerHint: 'Built from the workers who checked in today. Correct anything the gate got wrong, and add anyone it missed.',
    noEntries: 'No workers checked in for this date. Add a row for anyone on site.',
    addEntry: 'Add a worker',
    removeEntry: 'Remove this row',
    entryOf: 'Worker {n} of {m}',

    colWorker: 'Worker',
    colCompany: 'Company',
    colCert: 'Certification',
    colCard: 'Card number',
    colExpiration: 'Expires',

    phWorker: 'Name',
    phCompany: 'Company',
    phCert: 'Tap to choose',
    phCard: 'Card number',
    phExpiration: 'Tap to choose a date',

    certPickTitle: 'Which certification?',
    signedOnFile: 'Signature on file',
    signedMark: 'Mark signature on file',

    // Two rows for one man are his two CARDS. Said out loud because a CP who
    // reads them as a duplicate types a different worker's name over one —
    // which is how a certification came to be filed against the wrong worker
    // record on a signed register.
    sameWorkerNote: 'Same worker as another row — one row per certification, not a duplicate. To record a different worker, use Add a worker.',
    // Shown once a gate-recorded name has been edited: the row has stopped
    // claiming to know who this is, which is the honest state.
    unlinkedNote: 'Not linked to a gate check-in. This row records the name as typed.',
    // The register cannot be filed with nothing in it.
    nothingToFileTitle: 'Nothing to file',
    nothingToFileBody: 'Every row is empty. Add a worker and a certification before signing.',

    // A row with a card number and no name asserts something about a man the
    // document does not identify. It is dropped at filing either way — this is
    // the sentence that stops it happening behind his back. Shown at SIGN, not
    // on Next: a half-typed row is ordinary work mid-shift.
    // Appended when dropping the rows above leaves the register with nothing.
    // The reason comes first and this second — a CP told only "nothing to
    // file" has been given the consequence and not the cause.
    nothingLeftBody: 'That leaves nothing to file, so the register cannot be signed yet.',
    unnamedRowsTitle: 'Some rows name no worker',
    unnamedRowsBody: 'A certification row has to say whose card it is, so these rows will not be filed: {rows}. Add the worker’s name, or delete the row.',

    // A worker the gate turned away for missing OSHA. He is on the register as
    // DENIED — never as a certification — because the one fact the gate
    // established is that he had none.
    deniedBadge: 'DENIED — MISSING OSHA (turned away at gate, not admitted)',

    // Step 2 — review and sign.
    reviewHeading: 'Check this before you sign',
    reviewEntries: 'Certifications recorded',
    reviewNothingYet: 'Nothing recorded yet',
    entriesCount_one: '{n} row',
    entriesCount_other: '{n} rows',

    next: 'Next',
    submitAndSign: 'Sign and file',
    savedAutomatically: 'Saved automatically as you go.',
    stepsIncomplete: 'Some steps are still incomplete — you can still sign.',
    stepsAllComplete: 'Every step is filled in.',

    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the register before filing it.',
    submittedTitle: 'Signed and locked',
    submittedBody: 'This register is now locked. Corrections require an amendment.',
    submittedOfflineBody: 'Signed and locked on this device. It will sync when you are back online.',
    saveFailedTitle: 'Could not save',

    dateClear: 'Clear',
    dateDone: 'Done',
    notRecorded: 'Not recorded',
  },

  // ── app/logbooks/toolbox_talk.jsx — the safety talk, 4 steps ──────────────
  //
  // EN-ONLY, like every other logbook namespace: NYC DOB §3301.12.3 and OSHA
  // 29 CFR 1926.21 records are filed in English. See EN_ONLY_NAMESPACES.
  //
  // DELIBERATELY ABSENT: the 24 topic labels and the 5 group names. They are
  // printed verbatim on the filed PDF by the backend renderer, so the label
  // must be the SAME string on the device and on the document. They live in
  // toolboxTalkModel.TOPICS.
  toolboxTalk: {

    // Both renderers already refuse to print a nameless attendee, so the row
    // could only ever reach the STORED record — and it carried two ticks
    // against a man nobody can identify.
    // A talk has to touch all five subjects. The gate asked for a TOTAL, so
    // five PPE ticks filed as a complete talk with nothing said about height,
    // hazards, equipment or the public.
    topicGroupMissingTitle: 'Some topics were not covered',
    topicGroupMissingBody: 'A talk has to cover every topic tab. Nothing is ticked under: {groups}. Open each tab and tick what you discussed.',
    unnamedAttendeeTitle: 'Some rows name no worker',
    unnamedAttendeeBody: 'An attendance record has to say who was there, so these rows will not be filed: {rows}. Add the name, or delete the row.',
    unnamedAttendeeMarked: 'marked present',
    // Device round 4. Step 1 is the one gated step (finding 8) and the weekly
    // gap is ruling C — the men who worked this week without a talk, whom the
    // daily roster never offered.
    requiredField: 'Required field',
    step1Required: '{n} still to fill in before you can continue.',
    weeklyGapCount_one: '1 other worked this week without a talk',
    weeklyGapCount_other: '{n} others worked this week without a talk',
    weeklyGapHint: 'A toolbox talk covers the week. These men were on site this week but are not on today’s check-in list. Add anyone who attended this talk.',
    weeklyGapAdd: 'Add {name} to the roster',
    weeklyGapAddAll: 'Add all {n}',
    addedFromWeek: 'Added from this week — your assertion, not a gate check-in',
    screenTitle: 'Tool Box Talk',
    screenSub: 'NYC DOB §3301.12.3 — Safety Meeting',

    stepOf: 'Step {n} of {m}',
    step1Title: 'The talk',
    step2Title: 'Topics covered',
    step3Title: 'Who attended',
    step4Title: 'Review and sign',

    // Step 1.
    fLocation: 'Location',
    fCompany: 'Company',
    fTypeOfWork: 'Type of work',
    fMeetingTime: 'Time of the talk',
    fPerformedBy: 'Performed by',
    phField: 'Not recorded',
    phTime: 'Tap to choose a time',

    // Step 2.
    topicsHint: 'Tick what you covered. Anything not ticked is not on the record.',
    topicsCount: '{n} covered',

    // Step 3.
    rosterHint: 'Built from the workers who checked in today. Add anyone the gate missed.',
    noAttendees: 'Nobody has checked in yet. Add anyone who attended.',
    addAttendee: 'Add someone',
    removeAttendee: 'Remove this row',
    attendeeOf: 'Attendee {n} of {m}',
    colName: 'Name',
    colTitle: 'Title',
    colCompany: 'Company',
    colTime: 'Checked in',
    phName: 'Name',
    phTitle: 'Trade or title',
    phCompany: 'Company',
    // A worker is NOT required to sign a toolbox talk — the CP's signature over
    // the roster is the legal attestation. These two are markers, not
    // signatures, and the copy must not imply otherwise.
    presentMark: 'Mark present',
    presentOn: 'Marked present',
    gateConfirmed: 'Confirmed at the gate',
    gateNote: 'A worker who did not tap at the gate is still on the roster.',

    // Step 4.
    reviewHeading: 'Check this before you sign',
    reviewTopics: 'Topics covered',
    reviewAttendees: 'On the roster',
    reviewNothingYet: 'Nothing recorded yet',
    attendeesCount_one: '{n} worker',
    attendeesCount_other: '{n} workers',
    signAttests: 'Your signature attests that this talk was delivered to the workers listed.',

    next: 'Next',
    submitAndSign: 'Sign and file',
    savedAutomatically: 'Saved automatically as you go.',
    stepsIncomplete: 'Some steps are still incomplete — you can still sign.',
    stepsAllComplete: 'Every step is filled in.',

    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the talk before filing it.',
    submittedTitle: 'Signed and locked',
    submittedBody: 'This talk is now locked. Corrections require an amendment.',
    submittedOfflineBody: 'Signed and locked on this device. It will sync when you are back online.',
    saveFailedTitle: 'Could not save',

    dateClear: 'Clear',
    dateDone: 'Done',
    notRecorded: 'Not recorded',
  },

  // ── app/logbooks/scaffold_maintenance.jsx — the shed inspection, 3 steps ───
  //
  // EN-ONLY for the same reason as oshaLog above.
  //
  // DELIBERATELY ABSENT: the 19 inspection questions and the four shed types.
  // They are the DOB form's own wording, printed verbatim on the filed PDF by
  // backend/server.py:13329-13349, and the label must be the SAME string on
  // the device and on the document. They live in scaffoldMaintenanceModel and
  // are asserted against the renderer's copy.
  scaffoldMaintenance: {
    screenTitle: 'Scaffold Maintenance Log',
    screenSub: 'NYC DOB — Daily Inspection',

    stepOf: 'Step {n} of {m}',
    step1Title: 'The scaffold',
    step2Title: 'The checks',
    step3Title: 'Review and sign',

    // Step 1 — the shed.
    shedHint: 'Carried over from the last inspection on this project. Change anything that is no longer true.',
    fErector: 'Name of scaffold erector',
    fRenter: 'Renters name',
    fPermit: 'Permit #',
    fInstalled: 'Installation date',
    fExpires: 'Expiration',
    fPhone: 'Phone #',
    fHeight: 'Scaffold height',
    fPlatforms: 'Number of platforms decked',
    fShedType: 'Shed type',
    phField: 'Not recorded',
    phDate: 'Tap to choose a date',

    // Step 2 — the 19 checks.
    checksHint: 'Answer every item. N/A is a real answer — an item left blank is not.',
    answeredOf: '{n} of {m} answered',
    questionOf: 'Item {n} of {m}',

    // Step 3 — review and sign.
    reviewHeading: 'Check this before you sign',
    reviewShed: 'The scaffold',
    reviewChecks: 'The checks',
    reviewUnanswered: '{n} still unanswered',
    reviewAllAnswered: 'All {m} answered',
    reviewNothingYet: 'Nothing recorded yet',

    next: 'Next',
    submitAndSign: 'Sign and file',
    savedAutomatically: 'Saved automatically as you go.',
    stepsIncomplete: 'Some steps are still incomplete — you can still sign.',
    stepsAllComplete: 'Every step is filled in.',

    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the inspection before filing it.',
    submittedTitle: 'Signed and locked',
    submittedBody: 'This inspection is now locked. Corrections require an amendment.',
    submittedOfflineBody: 'Signed and locked on this device. It will sync when you are back online.',
    saveFailedTitle: 'Could not save',

    dateClear: 'Clear',
    dateDone: 'Done',
    notRecorded: 'Not recorded',
  },

  // ── app/logbooks/concrete_operations.jsx — the pour, 4 steps ──────────────
  //
  // EN-ONLY for the same reason as oshaLog above.
  //
  // DELIBERATELY ABSENT: the four formwork item labels. They are printed
  // verbatim on the filed PDF by backend/server.py:13415-13420 and again on the
  // combined report at :19932-19937, so the label must be the SAME string on
  // the device and on the document. They live in concreteOperationsModel and
  // are asserted against the renderers' copies.
  concreteOperations: {
    screenTitle: 'Concrete Operations Log',
    screenSub: 'Pour Record and Formwork Inspection',

    stepOf: 'Step {n} of {m}',
    step1Title: 'The pour',
    step2Title: 'Slump tests',
    step3Title: 'Formwork inspection',
    step4Title: 'Review and sign',

    // Step 1 — the pour.
    pourHint: 'What was poured, where it came from, and the conditions it went in under.',
    fPourLocation: 'Pour location',
    fSupplier: 'Concrete supplier',
    fMixDesign: 'Mix design',
    // No unit is offered because the form captures none — the renderers print
    // volume and temperature exactly as typed.
    fVolumeOrdered: 'Volume ordered',
    fTemperature: 'Temperature',
    fWeather: 'Weather',
    phField: 'Not recorded',

    // Step 2 — the slump tests.
    slumpHint: 'One row per test. A result you did not take stays blank — a blank prints as nothing, never as a fail.',
    slumpOf: 'Test {n} of {m}',
    addSlump: 'Add a slump test',
    removeSlump: 'Remove this test',
    fTime: 'Time',
    phTime: 'Tap to choose a time',
    fSlumpValue: 'Slump (in)',
    phSlumpValue: 'Not recorded',
    fResult: 'Result',
    resultPass: 'PASS',
    resultFail: 'FAIL',

    // Step 3 — the formwork.
    formworkHint: 'Answer every item. A NO is a real answer — an item left blank prints as not recorded.',
    answeredOf: '{n} of {m} answered',

    // Step 4 — review and sign.
    reviewHeading: 'Check this before you sign',
    reviewPour: 'The pour',
    reviewSlumps: 'Slump tests recorded',
    reviewFormwork: 'Formwork inspection',
    reviewUnanswered: '{n} still unanswered',
    reviewAllAnswered: 'All {m} answered',
    reviewNothingYet: 'Nothing recorded yet',
    slumpCount_one: '{n} test',
    slumpCount_other: '{n} tests',

    next: 'Next',
    submitAndSign: 'Sign and file',
    savedAutomatically: 'Saved automatically as you go.',
    stepsIncomplete: 'Some steps are still incomplete — you can still sign.',
    stepsAllComplete: 'Every step is filled in.',

    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the pour record before filing it.',
    submittedTitle: 'Signed and locked',
    submittedBody: 'This pour record is now locked. Corrections require an amendment.',
    submittedOfflineBody: 'Signed and locked on this device. It will sync when you are back online.',
    saveFailedTitle: 'Could not save',

    dateClear: 'Clear',
    dateDone: 'Done',
    notRecorded: 'Not recorded',
  },

  // ── app/logbooks/crane_operations.jsx — the crane, 4 steps ────────────────
  //
  // EN-ONLY for the same reason as oshaLog above.
  //
  // DELIBERATELY ABSENT: the fifteen pre-operation check labels. They are
  // printed verbatim on the filed PDF by backend/server.py:13299-13315 and
  // again on the combined report at :19556-19574, so the label must be the SAME
  // string on the device and on the document. They live in craneOperationsModel
  // and are asserted against the renderers' copies.
  craneOperations: {
    screenTitle: 'Crane Operations Log',
    screenSub: 'Pre-Lift Checks and Lift Log',

    stepOf: 'Step {n} of {m}',
    step1Title: 'The crane',
    step2Title: 'Pre-operation checks',
    step3Title: 'Lift log',
    step4Title: 'Review and sign',

    // Step 1 — the crane and its operator.
    craneHint: 'The machine and the man on the sticks. The licence number is what an inspector checks first.',
    fCraneType: 'Crane type',
    fCraneId: 'Crane ID / serial number',
    fOperatorName: 'Operator name',
    fOperatorLicense: 'Operator licence number',
    phField: 'Not recorded',

    // Step 2 — the fifteen checks.
    preOpHint: 'Answer every item before the first pick. A NO is a real answer — an item left blank prints as not recorded.',
    answeredOf: '{n} of {m} answered',
    itemOf: 'Item {n} of {m}',

    // Step 3 — the lift log.
    liftHint: 'One row per pick. Weight and radius are recorded exactly as you enter them.',
    liftOf: 'Lift {n} of {m}',
    addLift: 'Add a lift',
    removeLift: 'Remove this lift',
    fTime: 'Time',
    phTime: 'Tap to choose a time',
    fDescription: 'Description',
    phDescription: 'What was picked',
    fLoadWeight: 'Load weight',
    fRadius: 'Radius',
    phNumber: 'Not recorded',

    // Step 4 — review and sign.
    reviewHeading: 'Check this before you sign',
    reviewCrane: 'The crane',
    reviewPreOp: 'Pre-operation checks',
    reviewLifts: 'Lifts recorded',
    reviewUnanswered: '{n} still unanswered',
    reviewAllAnswered: 'All {m} answered',
    reviewNothingYet: 'Nothing recorded yet',
    liftCount_one: '{n} lift',
    liftCount_other: '{n} lifts',

    next: 'Next',
    submitAndSign: 'Sign and file',
    savedAutomatically: 'Saved automatically as you go.',
    stepsIncomplete: 'Some steps are still incomplete — you can still sign.',
    stepsAllComplete: 'Every step is filled in.',

    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the crane log before filing it.',
    submittedTitle: 'Signed and locked',
    submittedBody: 'This crane log is now locked. Corrections require an amendment.',
    submittedOfflineBody: 'Signed and locked on this device. It will sync when you are back online.',
    saveFailedTitle: 'Could not save',

    dateClear: 'Clear',
    dateDone: 'Done',
    notRecorded: 'Not recorded',
  },

  // ── app/logbooks/excavation_monitoring.jsx — the cut, 4 steps ─────────────
  //
  // EN-ONLY for the same reason as oshaLog above.
  //
  // DELIBERATELY ABSENT: the soil types and protection systems. They are enum
  // VALUES stored in the payload and printed verbatim by both renderers, so the
  // string on the device has to be the string on the document. They live in
  // excavationMonitoringModel.
  excavationMonitoring: {

    // A reading with no address names no building. Dropped at filing either
    // way; this is the sentence that stops it happening behind him.
    unnamedPointTitle: 'A monitoring point needs an address',
    unnamedPointBody: 'These rows record readings but name no building, so they will not be filed: {rows}. Add the address, or delete the row.',
    screenTitle: 'Excavation Monitoring Log',
    screenSub: 'Adjacent-Structure and Vibration Readings',

    stepOf: 'Step {n} of {m}',
    step1Title: 'The excavation',
    step2Title: 'Adjacent structures',
    step3Title: 'Vibration and conditions',
    step4Title: 'Review and sign',

    // Step 1 — the cut.
    cutHint: 'How deep, what you are digging in, and what is holding the sides up.',
    // No unit is offered because the form captures none — both renderers print
    // the depth exactly as typed.
    fDepth: 'Excavation depth',
    fSoilType: 'Soil type',
    fProtection: 'Protection system',
    phField: 'Not recorded',

    // Step 2 — the monitoring points.
    pointsHint: 'One row per building you are watching. Movement is worked out from the two readings.',
    pointOf: 'Point {n} of {m}',
    addPoint: 'Add a building',
    removePoint: 'Remove this building',
    fAddress: 'Address',
    fBaseline: 'Baseline reading',
    fCurrent: 'Current reading',
    fMovement: 'Movement',
    movementDerived: 'Worked out from the two readings above.',
    phAddress: 'Building address',
    phReading: 'Not recorded',

    // Step 3 — vibration and conditions.
    vibrationHint: 'A current reading only means something next to a threshold. Record both or neither.',
    fThreshold: 'Threshold',
    fCurrentReading: 'Current reading',
    overThresholdTitle: 'Over threshold',
    overThresholdBody: 'The current reading is above the threshold. Review and take corrective action.',
    withinThreshold: 'Within threshold',
    conditionsLabel: 'Conditions',
    fGroundwater: 'Groundwater observed',
    fAtmospheric: 'Atmospheric testing performed',
    yes: 'Yes',
    no: 'No',

    // Step 4 — review and sign.
    reviewHeading: 'Check this before you sign',
    reviewCut: 'The excavation',
    reviewPoints: 'Monitoring points recorded',
    reviewVibration: 'Vibration',
    reviewConditions: 'Conditions',
    reviewNothingYet: 'Nothing recorded yet',
    pointCount_one: '{n} building',
    pointCount_other: '{n} buildings',

    next: 'Next',
    submitAndSign: 'Sign and file',
    savedAutomatically: 'Saved automatically as you go.',
    stepsIncomplete: 'Some steps are still incomplete — you can still sign.',
    stepsAllComplete: 'Every step is filled in.',

    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the readings before filing them.',
    submittedTitle: 'Signed and locked',
    submittedBody: 'These readings are now locked. Corrections require an amendment.',
    submittedOfflineBody: 'Signed and locked on this device. It will sync when you are back online.',
    saveFailedTitle: 'Could not save',

    dateClear: 'Clear',
    dateDone: 'Done',
    notRecorded: 'Not recorded',
  },

  // ── app/logbooks/hot_work.jsx — the burn permit, 4 steps ──────────────────
  //
  // EN-ONLY for the same reason as oshaLog above.
  //
  // DELIBERATELY ABSENT: the seven precaution labels and the five work types.
  // The precautions are printed verbatim on the filed permit by
  // backend/server.py:13260-13268 and again at :19509-19517, and work_type is
  // an enum VALUE stored in the payload — so both must be the SAME string on
  // the device and on the document. They live in hotWorkModel.
  hotWork: {
    screenTitle: 'Hot Work Permit',
    screenSub: 'Burn Permit and Fire Watch',

    stepOf: 'Step {n} of {m}',
    step1Title: 'The work',
    step2Title: 'Timing',
    step3Title: 'Precautions',
    step4Title: 'Review and sign',

    // A failed load with no local draft. Said out loud: a blank permit reads as
    // "none exists for today" and invites a second one for the same burn.
    offlineDetail: 'Could not check for an existing permit. You can still fill this in — it saves on this device and syncs when you reconnect.',

    // Step 1 — the work.
    workHint: 'What is being burned, where, and by whom.',
    fWorkType: 'Type of hot work',
    fLocation: 'Location',
    fWorkerName: 'Worker name',
    fWorkerCert: 'Worker certification number',
    phField: 'Not recorded',

    // Step 2 — the timing.
    timingHint: 'When the work runs, and who watches for fire after it stops.',
    fStartTime: 'Start time',
    fEndTime: 'End time',
    fFireWatchUntil: 'Fire watch until',
    fireWatchDerived: '(default: work end + 30 min)',
    needsEndTime: 'Choose an end time above',
    fFireWatchName: 'Fire watch person',
    phTime: 'Tap to choose a time',

    // Step 3 — the seven precautions.
    precautionsHint: 'Answer every item before the first spark. A NO is a real answer — an item left blank prints as not recorded.',
    answeredOf: '{n} of {m} answered',
    itemOf: 'Item {n} of {m}',

    // Step 4 — review and sign.
    reviewHeading: 'Check this before you sign',
    reviewWork: 'The work',
    reviewTiming: 'Timing',
    reviewPrecautions: 'Precautions',
    reviewUnanswered: '{n} still unanswered',
    reviewAllAnswered: 'All {m} answered',
    reviewNothingYet: 'Nothing recorded yet',

    next: 'Next',
    submitAndSign: 'Sign and file',
    savedAutomatically: 'Saved automatically as you go.',
    stepsIncomplete: 'Some steps are still incomplete — you can still sign.',
    stepsAllComplete: 'Every step is filled in.',

    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the permit before filing it.',
    submittedTitle: 'Signed and locked',
    submittedBody: 'This permit is now locked. Corrections require an amendment.',
    submittedOfflineBody: 'Signed and locked on this device. It will sync when you are back online.',
    saveFailedTitle: 'Could not save',

    dateClear: 'Clear',
    dateDone: 'Done',
    notRecorded: 'Not recorded',
  },

  // ── app/logbooks/ssc_daily_safety_log.jsx — the daily narrative, 4 steps ──
  //
  // EN-ONLY for the same reason as oshaLog above.
  //
  // DELIBERATELY ABSENT: the five compliance labels and the three narrative
  // prompts. They are printed verbatim on the filed PDF by
  // backend/server.py:13529-13535 and :13585-13589, and again on the combined
  // report, so the label must be the SAME string on the device and on the
  // document. They live in sscDailySafetyLogModel.
  sscDailySafetyLog: {

    // SIGN ONCE, FREEZE AT END OF DAY — the same sentence daily_jobsite
    // shows, for the same reason: an SSC told only "filed" would not add
    // the afternoon's incidents.
    signedStaysOpen: 'Signed. This log stays open for the rest of the day — add incidents or conditions as they happen. It closes overnight.',
    screenTitle: 'SSC/SSM Daily Safety Log',
    screenSub: 'Site Safety Coordinator — Daily Record',

    stepOf: 'Step {n} of {m}',
    step1Title: 'The site',
    step2Title: 'Compliance',
    step3Title: 'The narrative',
    step4Title: 'Review and sign',

    // Step 1 — the site.
    siteHint: 'Where this is, how many men were on it, and what the weather did.',
    fAddress: 'Project address',
    fSsp: 'Site Safety Plan #',
    fWeather: 'Weather',
    fWorkers: 'Workers on site',
    // The two above come off the project record, so correcting them here would
    // correct one day's log and not the job. Said out loud rather than left as
    // a field that mysteriously will not accept a tap.
    fromProjectNote: 'Carried from the project record. Change it on the project, not on one day’s log.',
    notOnFile: 'Not on file',
    phField: 'Not recorded',

    // Step 2 — the five compliance switches.
    complianceHint: 'Mark what you confirmed today.',
    // The same caveat both filed surfaces already print under this table: an
    // unticked item is a default, not a finding.
    complianceDefaultNote: 'An item you do not mark prints as “No”. It reads as an untouched default, not as a finding you made.',

    // Step 3 — the narrative.
    narrativeHint: 'This log IS these sentences. A prompt left blank prints as “Not recorded” on the filed document.',
    fIncidentDetails: 'Incident Details',
    incidentDetailsHint: 'You marked an incident on the previous step, so the document will ask for this.',
    phNarrative: 'Not recorded',

    // Step 4 — review and sign.
    reviewHeading: 'Check this before you sign',
    reviewSite: 'The site',
    reviewCompliance: 'Compliance',
    reviewNarrative: 'The narrative',
    yes: 'Yes',
    no: 'No',

    next: 'Next',
    submitAndSign: 'Sign and close the day',
    signingClosesDay: 'Signing locks this log. Corrections then need an amendment.',
    savedAutomatically: 'Saved automatically as you go.',
    stepsIncomplete: 'Some steps are still incomplete — you can still sign.',
    stepsAllComplete: 'Every step is filled in.',

    signatureRequiredTitle: 'Signature required',
    signatureRequiredBody: 'Sign the log before closing the day.',
    submittedTitle: 'Signed and locked',
    submittedBody: 'This log is now locked. Corrections require an amendment.',
    submittedOfflineBody: 'Signed and locked on this device. It will sync when you are back online.',
    saveFailedTitle: 'Could not save',

    notRecorded: 'Not recorded',
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

  // ── app/site/logbooks.jsx — the eight logbook types the inspector screen ───
  // could not render. Labels are the editors' own wording (each editor's
  // constant list is cited in the renderer that uses these keys), so the
  // record an inspector reads on the device matches the form the CP filled.
  // Booleans are rendered as glyphs, not words, so there is no Yes/No key.
  logbookView: {
    // Tab / document titles. The first three carry the labels the tab strip
    // already shipped, moved here verbatim so the whole list resolves the
    // same way — no rendered character changes in English.
    tabDailyJobsite: 'Daily Jobsite',
    tabToolboxTalk: 'Toolbox Talk',
    tabPreshift: 'Pre-Shift Sign-In',
    tabHotWork: 'Hot Work',
    tabCrane: 'Crane Operations',
    tabExcavation: 'Excavation Monitoring',
    tabConcrete: 'Concrete Operations',
    tabScaffold: 'Scaffold Maintenance',
    tabSsc: 'SSC Daily Safety Log',
    tabOsha: 'OSHA / SST Log',
    tabOrientation: 'Subcontractor Orientation',

    // Shared field + column labels
    fLocation: 'Location',
    fCompany: 'Company',
    fWorker: 'Worker',
    fWeather: 'Weather',
    fTemperature: 'Temperature',
    fTime: 'Time',
    fDescription: 'Description',
    fItem: 'Item',
    fConfirmed: 'Confirmed',
    fStatus: 'Status',
    // A field on the form that the CP never filled. Stated, not implied: the
    // same words the report/PDF surface prints (server.py
    // generate_combined_report), so one record reads the same on both. A blank
    // would be ambiguous — never asked, or asked and unanswered?
    fNotRecorded: '— Not recorded',

    // Hot work
    hwWorkType: 'Work Type',
    hwWorkerCert: 'Worker Cert #',
    hwStart: 'Start Time',
    hwEnd: 'End Time',
    hwFireWatch: 'Fire Watch',
    hwFireWatchUntil: 'Fire Watch Until',
    hwFireWatchDefault: '(default: work end + 30 min)',
    hwPrecautions: 'Pre-Work Precautions',
    hwPrecaution: 'Precaution',
    p_area_cleared: 'Area Cleared of Combustibles (35 ft)',
    p_fire_extinguisher_present: 'Fire Extinguisher Present',
    p_sprinklers_operational: 'Sprinklers Operational',
    p_combustibles_covered: 'Combustibles Covered / Protected',
    p_fire_watch_assigned: 'Fire Watch Assigned',
    p_ventilation_adequate: 'Ventilation Adequate',
    p_permit_posted: 'Permit Posted at Location',

    // Crane operations
    crType: 'Crane Type',
    crId: 'Crane ID',
    crOperator: 'Operator',
    crLicense: 'Operator License',
    crPreOp: 'Pre-Operation Checklist',
    crLiftLog: 'Lift Log',
    crLoadWeight: 'Load Weight',
    crRadius: 'Radius',
    c_wire_ropes: 'Wire Ropes Inspected',
    c_hooks_latches: 'Hooks & Latches Secure',
    c_brakes: 'Brakes Functional',
    c_outriggers: 'Outriggers Deployed',
    c_load_chart: 'Load Chart Available',
    c_boom_condition: 'Boom Condition OK',
    c_anti_two_block: 'Anti Two-Block Device',
    c_fire_extinguisher: 'Fire Extinguisher Present',
    c_signals_reviewed: 'Signals Reviewed',
    c_area_barricaded: 'Area Barricaded',
    c_wind_speed_checked: 'Wind Speed Checked',
    c_power_lines_clear: 'Power Lines Clear',
    c_load_weight_known: 'Load Weight Known',
    c_rigging_inspected: 'Rigging Inspected',
    c_swing_radius_clear: 'Swing Radius Clear',

    // Excavation monitoring
    exDepth: 'Excavation Depth',
    exSoil: 'Soil Type',
    exProtection: 'Protection System',
    exGroundwater: 'Groundwater Observed',
    exAtmospheric: 'Atmospheric Testing',
    exVibration: 'Vibration',
    exThreshold: 'Threshold',
    exCurrent: 'Current',
    exOver: 'Over threshold',
    exWithin: 'Within threshold',
    exPoints: 'Adjacent-Structure Monitoring Points',
    exBaseline: 'Baseline',
    exMovement: 'Movement',

    // Concrete operations
    coPour: 'Pour Location',
    coSupplier: 'Supplier',
    coMix: 'Mix Design',
    coVolume: 'Volume Ordered',
    coSlumpTests: 'Slump Tests',
    coSlump: 'Slump',
    coResult: 'Result',
    coPass: 'Pass',
    coFail: 'Fail',
    coFormwork: 'Formwork Inspection',
    fw_shores_plumb: 'Shores Plumb',
    fw_bracing_adequate: 'Bracing Adequate',
    fw_formwork_clean: 'Formwork Clean',
    fw_no_gaps: 'No Gaps',

    // Scaffold maintenance
    scErector: 'Scaffold Erector',
    scRenter: 'Renter',
    scPermit: 'Permit #',
    scPhone: 'Phone #',
    scInstall: 'Installation Date',
    scExpiration: 'Expiration',
    scHeight: 'Scaffold Height',
    scPlatforms: 'Platforms Decked',
    scShedType: 'Shed Type',
    scChecklist: 'Inspection Checklist',
    scQuestion: 'Question',
    scAnswer: 'Answer',
    q_signs_on_parapets: 'Are the signs on the parapets?',
    q_base_plates_mudsills: 'Are the base plates and mudsills secured?',
    q_scaffold_pins_bolts: 'Are the scaffold pins and bolts installed?',
    q_legs_poles_plumb: 'Are the legs and poles plumb, braced and not displaced?',
    q_tie_ins_spaced: 'Are tie-ins correctly spaced, properly secured and the correct amount?',
    q_cross_braces: 'Are cross braces fully attached, not bent, and not missing?',
    q_pipe_clamps_tight: 'Are pipe clamps tight?',
    q_window_jacks_tight: 'Are window jacks tight?',
    q_planks_secured: 'Are all the planks secured?',
    q_decking_planks_condition: 'Are decking and planks in good condition?',
    q_deck_fully_planked: 'Is deck fully planked?',
    q_gaps_open_spaces: 'Are there gaps or open spaces on decking?',
    q_guardrails_toe_boards: 'Are the guardrails and toe boards secured at all places where required?',
    q_netting_extension: 'Is the netting extension of full length and height?',
    q_netting_secured: 'Is the netting secured?',
    q_parapet_height: 'Is the parapet the proper height and secured?',
    q_lights_working: 'Are the lights working?',
    q_deck_clean: 'Is the deck clean and free of debris?',
    q_drawings_on_site: 'Drawings on site for inspection?',

    // SSC daily safety log
    sscAddress: 'Project Address',
    sscSsp: 'Site Safety Plan #',
    sscWorkers: 'Workers on Site',
    sscCompliance: 'Compliance',
    // A rendered "off" here may be an untouched default, not a deliberate
    // negative finding — the same caveat the PDF renderer prints.
    sscDefaultNote: 'Compliance items stay unset unless the reviewer marks them.',
    sscNarrative: 'Narrative',
    sscSiteConditions: 'Site Conditions',
    sscViolations: 'Safety Violations Observed',
    sscCorrective: 'Corrective Actions Taken',
    sscIncidentDetails: 'Incident Details',
    s_incidents_reported: 'Incidents Reported',
    s_safety_meetings_held: 'Safety Meetings Held',
    s_fire_protection_in_place: 'Fire Protection in Place',
    s_housekeeping_satisfactory: 'Housekeeping Satisfactory',
    s_ppe_compliance: 'PPE Compliance',

    // OSHA / SST certification log
    oshaCertType: 'Cert Type',
    oshaCard: 'Card #',
    oshaExpiration: 'Expiration',
    oshaSigned: 'Signed',

    // Subcontractor safety orientation
    orTrade: 'Trade',
    orOsha: 'OSHA / SST #',
    orNumber: 'Orientation #',
    orLanguage: 'Language Provided',
    orCompleted: 'Completed',
    orTopics: 'Safety Topics Reviewed',
    orTopic: 'Topic',
    orReviewed: 'Reviewed',
    orAck: 'Worker Acknowledgment',
    orUnsigned: 'UNSIGNED',
    orConductedBy: 'Conducted By (CP)',
    o_hard_hats: 'Hard hats required at all times on site',
    o_safety_boots: 'Safety boots required (steel toe, ANSI rated)',
    o_safety_glasses: 'Safety glasses / eye protection required',
    o_high_vis: 'High-visibility vest required near traffic',
    o_no_horseplay: 'No horseplay, running, or unsafe behavior',
    o_report_hazards: 'Report all hazards to CP immediately',
    o_fall_protection_required: 'Fall protection required at 6 ft and above',
    o_harness_inspection: 'Inspect harness before each use',
    o_ladder_safety: 'Three-point contact on ladders at all times',
    o_scaffold_rules: 'Only use scaffold as erected — no modifications',
    o_emergency_exits: 'Emergency exit locations reviewed',
    o_first_aid: 'First aid kit location reviewed',
    o_emergency_contact: 'Emergency contact numbers provided',
    o_incident_reporting: 'All incidents must be reported immediately',
    o_no_drugs_alcohol: 'Zero tolerance for drugs and alcohol on site',
    o_sign_in_out: 'Must sign in and out every day',
    o_authorized_areas: 'Only enter authorized work areas',
    o_housekeeping: 'Keep work area clean at all times',
  },

  // ── app/reports.jsx — the admin-only report preview panel ─────────────────
  // {n} is substituted by the caller (this layer has no interpolation).
  reportPreview: {
    failedPhotos: '{n} photo(s) failed processing — they may be missing from this report.',
  },
};
