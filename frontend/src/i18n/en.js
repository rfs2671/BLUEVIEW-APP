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
    // A safety orientation may be CREATED without a trade — the gate check-in
    // writes one that way, and a worker at the turnstile is never blocked for
    // an admin's unfinished roster. It may not be SUBMITTED without one: the
    // record is entirely about what this man was oriented TO do on this site.
    // The server sends the worker's name alongside the code; the orientation
    // screen names him and offers the fix on his row, so this generic sentence
    // is the fallback for anywhere else the code surfaces (the reconnect drain
    // has no screen and no row to point at).
    code_SUBMIT_MISSING_TRADE: 'This worker has no trade assigned. Assign one before submitting the orientation.',
    // Shown under a Submit button disabled because no signature is on file. A
    // CP sets his signature by signing on the log itself — there is no separate
    // profile screen for it (nothing under app/settings or app/profile writes
    // cp_signature) — so the copy points at the pad directly above the button.
    submitNeedsSignature: 'Sign above to submit. Your signature is saved for next time.',
    submitSignatureLoading: 'Loading your saved signature...',
    // A queued draft the server REFUSED on the reconnect drain. Distinct from
    // notLocked* above: nothing was created, so nothing is frozen anywhere —
    // the work is still on this device and still editable.
    notPushedTitle: 'NOT SAVED TO THE SERVER',
    notPushedHint: 'The server refused this log, so it was NOT saved and is NOT locked. Your work is still on this device and still editable — fix the problem above and submit again.',
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
    rosterCollapsedBody: 'Two workers with the same name at one company can be counted once. Check the worker counts below.',

    // Step 2 — activity, location, then the camera.
    activityQuestion: 'What did this crew do?',
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
    savedAutomatically: 'Saved automatically',
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
