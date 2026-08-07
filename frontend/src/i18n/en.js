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
