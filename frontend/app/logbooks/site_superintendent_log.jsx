/**
 * THE SITE SUPERINTENDENT LOG — BC 3301.13.13.
 *
 * THE ONE THING THAT MUST NOT BE COPIED FROM ANOTHER EDITOR.
 *
 *     eventType: 'superintendent_sign'
 *
 * `deriveActingCapacity` (src/utils/signatureAudit.js) keys on the EVENT TYPE
 * first and the signer's role only as a fallback. preshift_signin.jsx and
 * osha_log.jsx both send `cp_sign`, and this screen's obvious starting point
 * was one of them. If it inherits `cp_sign`, the ledger records the
 * construction superintendent log as signed by a COMPETENT PERSON — the exact
 * opposite of what `acting_capacity` exists to prove, on the one document
 * where the capacity is the point.
 *
 * IT FAILS SILENTLY. Nothing errors, the hash computes, the document renders.
 * Only the capacity is wrong, in a field nobody reads until somebody needs it.
 * siteSuperintendentSign.test.cjs asserts the string by name.
 *
 * THE FREEZE IS AT DEPARTURE, NOT END OF DAY. 3301.13.13 says "complete such
 * log prior to departing the job site", so this is timing class `visit`:
 * excluded from sweep_stale_end_of_day_logs, frozen when its author signs on
 * the way out. See the note in server.py beside VISIT_LOG_TYPES.
 *
 * FIVE STEPS, matching the daily jobsite stepper he already knows:
 *   1 Presence          item 1
 *   2 Work & inspection items 2, 3, 11
 *   3 Findings & orders items 4 + 5, entered ONCE — see csFindings.js
 *   4 DOB & incidents   items 6, 7
 *   5 Scope & sign      items 8, 9, 10, and the signature
 *
 * THE DECLARED ITEMS ARE THE SOURCE OF TRUTH. Everything about which items
 * exist, which are attestable, which are collected and which apply on a given
 * date comes from superintendentLogModel.js, which mirrors
 * lib/logbook/superintendent_log.py. This screen renders them; it does not
 * restate them.
 */
import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import { View, Text, TextInput, Pressable, ScrollView } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Plus, Trash2, Check, X } from 'lucide-react-native';

import LogbookStepper from '../../src/components/logbookStepper/LogbookStepper';
// THE TIME PICKER, AND IT IS THE ONE THIS REPO ALREADY OWNS. concrete,
// crane, hot_work and toolbox_talk render this same component; a fifth screen
// is not the moment to reach for a package. Every picker on npm carries a
// NATIVE MODULE, and a native module ends OTA delivery — the rule TimeField
// and DateField were both hand-built under, stated at the top of TimeField.jsx
// and again in src/i18n/index.js, which refused expo-localization on it.
//
// `parseClock` and `toClock` come from the same file for the same reason
// hotWorkModel takes them from there: the prefill below has to be written in
// the format the picker itself writes, and a second implementation of that
// format is how two of them start to disagree.
import TimeField, { parseClock, toClock } from '../../src/components/logbookStepper/TimeField';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { Card, StepHeaderBase } from '../../src/components/logbookStepper/primitives';
import SignaturePad from '../../src/components/SignaturePad';
import { outdoor, spacing } from '../../src/styles/theme';
import { useToast } from '../../src/components/Toast';
import { useT } from '../../src/i18n';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { useEsraConsent } from '../../src/hooks/useEsraConsent';
import { logbooksAPI, dobAPI } from '../../src/utils/api';
// THE SERVER IS ASKED EVEN WHEN A DRAFT EXISTS — the same one call the other
// eleven editors make, not a twelfth copy of the reasoning. See draftFreshness.
import { compareDraftToServer, submitRefused } from '../../src/utils/draftFreshness';
import { scratchKey, stash, take, drop } from '../../src/utils/logbookScratch';
// ── THE LOCAL-FIRST STORE, AND WHY IT IS THE SHARED ONE ────────────────────
//
// This screen's load handler used to say "let him work offline; the draft is
// local-first like every other editor" while importing nothing from here. It
// was not. Nothing was written anywhere: a five-step 3301.13.13 log lived in
// React state, the push threw with no signal, a toast said so, and the log was
// gone when he left the screen. It is the WORST log to lose that way — the
// statute requires it completed before he departs, and cellars and shafts are
// exactly where there is no signal.
//
// NOT A NEW MECHANISM. The nine siblings write through logbookDrafts and are
// drained by draftSync on the next NetInfo transition; `site_superintendent_log`
// is deliberately NOT in that drain's SKIP_LOG_TYPES, and the payload it
// rebuilds from a key — {project_id, log_type, date, data, cp_signature,
// cp_name, status} — is exactly what handleSubmit posts. So the draft goes in
// the same store, under the same key shape, and the existing drain sends it.
import {
  draftKey, readDraft, writeDraft, setDraftBackendId,
  markPending, clearPending, markFinalized,
} from '../../src/utils/logbookDrafts';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';
import {
  finalizeErrorCode, recordFinalizeError, clearFinalizeError,
} from '../../src/utils/draftSync';
import { isOfflineError } from '../../src/utils/offlineState';
// TWO MODULES, AND THEY ARE NOT INTERCHANGEABLE. `signatureAudit` is the
// LEDGER (recordSignatureEvent, device fingerprint, integrity); the predicate
// that says whether a signature was affirmed lives in `signatureAffirmed`.
// Importing the predicate from the ledger binds it to `undefined` rather than
// failing — every static gate stayed green and the screen crashed to the error
// boundary on mount. The mount smoke is what caught it.
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import { isAffirmedSignature } from '../../src/utils/signatureAffirmed';
import { useAuth } from '../../src/context/AuthContext';
import { resolveSignerName } from '../../src/utils/signerName';
import {
  csLogItems, csItemState, csUnanswered, csItemLabels,
} from '../../src/utils/superintendentLogModel';
import {
  emptyFinding, findingIsEmpty, findingGaps, deriveConditionAndOrderBlocks,
  CORRECTED, NOT_CORRECTED, NOT_YET, isCorrectionState,
} from '../../src/utils/csFindings';

const LOG_TYPE = 'site_superintendent_log';
const TOTAL_STEPS = 5;

/**
 * The write answered, and answered with nothing that names a record.
 *
 * A CONSTANT BECAUSE IT IS A PAIR. It is thrown at the one place that can
 * detect it and read at the one place that reports it, and a literal at each
 * end is how the two drift into a machine string reaching a jobsite.
 */
const NO_RECORD_RETURNED = 'LOG_NOT_FILED';

const todayISO = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' })
  .format(new Date());

/**
 * The site's wall clock right now, IN THE PICKER'S OWN FORMAT AND ON ITS GRID,
 * for a prefill he confirms or changes.
 *
 * IT USED TO BE `nowHHMM()`, RETURNING 24-HOUR "HH:MM", and both reasons it
 * cannot stay that way are about the filed record rather than the control:
 *
 *   TWO FORMATS IN ONE FIELD. `presence.arrived_at` now holds what TimeField
 *   writes — "hh:mm AM/PM". A 24-hour prefill he never retapped would file a
 *   SECOND format into the same key, and every reader of it (server.py's
 *   `_arrived`/`_departed`, app/site/logbooks.jsx's "On site" line) echoes the
 *   string raw and converts nothing. A key that holds two shapes is how a
 *   reader eventually starts converting.
 *
 *   AN OFF-GRID MINUTE IS INVISIBLE IN THE PICKER. TimeField selects the chip
 *   whose {h24, m} matches exactly, on a five-minute grid. Prefill 07:17 and
 *   the modal opens with nothing selected — the field says one thing and the
 *   list he is choosing from says he has chosen nothing.
 *
 * FLOORED, NEVER ROUNDED UP. A prefill is a suggestion about a moment that has
 * already happened, and rounding forward would suggest an arrival the clock
 * cannot support yet.
 */
const nowClock = () => {
  const hhmm = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date()).replace(/^24:/, '00:');
  const p = parseClock(hhmm);
  // Unparseable means no suggestion, never a guess. The field stays blank and
  // the gate below names it — which is the honest outcome and not a defect.
  return p ? toClock(p.h24, p.m - (p.m % 5)) : '';
};

// ── THE FIELD COMPONENTS LIVE HERE, AND THAT IS THE WHOLE POINT ─────────────
//
// THE BUG THIS PLACEMENT FIXES. `Field`, `CorrectionChoice` and `EntryList`
// were declared INSIDE `SiteSuperintendentLog` and used as JSX element types
// (`<Field ... />`). A function expression in a render body is a NEW function
// object on every render, and React compares element types by REFERENCE — a
// new type is a DIFFERENT component, so the old subtree is UNMOUNTED and a
// fresh one mounted. The `TextInput` inside was destroyed and rebuilt, and a
// destroyed input is not a focused input.
//
// Per keystroke: onChangeText -> setState -> re-render -> new `Field` identity
// -> remount -> KEYBOARD DISMISSED. The site superintendent filled eleven
// items of statutory prose one character at a time, tapping the field again
// between each. The log was unfillable in practice.
//
// HOISTED RATHER THAN CALLED. Converting the call sites to plain function
// calls — `Field({...})`, the way `stepPresence()` is called below — would
// also inline the elements and also fix it. Module scope was chosen because it
// makes the identity stable BY CONSTRUCTION: `Field` is created once, when the
// module loads, and nothing a later editor does inside the screen body can
// make it unstable again. The call-site convention would have to be noticed.
//
// EVERYTHING THEY USED TO CLOSE OVER IS NOW A PROP. `s` (the pinned stepper
// styles), `locked` (read-only once the log is filed) and `t` (the translator)
// were read from the enclosing scope. At module scope those names do not
// exist, so each arrives explicitly — a dropped capture would be a silent
// stale-closure bug worse than the one being fixed, and
// siteSuperintendentStableFields.test.cjs asserts every call site passes them.
//
// THE REAL PROPERTY IS PROVED BY EXECUTION, not by that source guard:
// `node scripts/focus-survives-keystroke.cjs --dist dist` types three
// characters into the first field of this screen in a real browser and asserts
// the same DOM node still holds focus and holds all three.

/**
 * One labelled text field. `locked` is what makes a filed log read-only, so it
 * is required at every call site rather than defaulted — a default of `false`
 * would render an editable input over a signed statutory record.
 */
const Field = ({ s, locked, label, value, onChangeText, placeholder, multiline }) => (
  <View style={{ marginBottom: spacing.md }}>
    <Text style={s.reviewLabel}>{label}</Text>
    <TextInput
      style={multiline ? s.input : s.input}
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={outdoor.textDim}
      multiline={!!multiline}
      editable={!locked}
    />
  </View>
);

/**
 * WAS IT CORRECTED — THREE POSITIVE ANSWERS, AND NO WAY BACK TO BLANK.
 *
 * This was a two-chip yes/no that returned to `null` when you tapped the
 * selected chip again. Two things were wrong with it, and the second is the
 * one that matters on a licensed record:
 *
 *   TWO ANSWERS ARE NOT ENOUGH. "Not corrected" and "not corrected YET" are
 *   different statements about the same site — one says he found something
 *   and left it standing, the other says the work is under way. With only
 *   yes/no he has to assert whichever is less wrong.
 *
 *   AN UNTOGGLE PRODUCES A BLANK THAT LOOKS LIKE A NO. `null` renders as
 *   three unselected chips, which is indistinguishable from "not corrected"
 *   to anyone reading the filed document. That is the recurring defect here:
 *   absence read as a claim.
 *
 * So the three states are declared in csFindings.js, every chip SETS one,
 * none clears, and findingGaps refuses a row that has none of them.
 */
const CorrectionChoice = ({ s, locked, t, label, note, value, onChange }) => (
  <View style={{ marginBottom: spacing.md }}>
    <Text style={s.reviewLabel}>{label}</Text>
    <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
      {[
        [t('correctedYes'), CORRECTED],
        [t('correctedNo'), NOT_CORRECTED],
        [t('correctedNotYet'), NOT_YET],
      ].map(([lbl, v]) => (
        <Pressable
          key={v}
          disabled={locked}
          // SETS, NEVER CLEARS. Tapping the chosen chip again is a no-op
          // rather than a way back to unanswered.
          onPress={() => onChange(v)}
          style={[s.chip, value === v && s.chipSelected]}
        >
          {value === v ? <Check size={13} strokeWidth={2} /> : null}
          <Text style={[s.chipText, value === v && s.chipTextSelected]}>{lbl}</Text>
        </Pressable>
      ))}
    </View>
    {note ? <Text style={s.noteText}>{note}</Text> : null}
  </View>
);

/** A tickable list of typed entries — the DOB actions and the incidents. */
const EntryList = ({
  s, locked, t, heading, note, entries, setEntries, none, setNone, noneLabel,
}) => (
  <Card s={s}>
    <StepHeaderBase s={s} title={heading} />
    {note ? <Text style={s.noteText}>{note}</Text> : null}
    {entries.map((e, i) => (
      <View key={e.id} style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Pressable disabled={locked}
          onPress={() => { setNone(false); setEntries((p) => p.map((x, j) => (j === i ? { ...x, included: !x.included } : x))); }}
          style={[s.chip, e.included && s.chipSelected]}>
          {e.included ? <Check size={13} strokeWidth={2} /> : <X size={13} strokeWidth={2} />}
        </Pressable>
        <TextInput
          style={[s.input, { flex: 1 }]}
          value={e.text}
          editable={!locked}
          onChangeText={(v) => setEntries((p) => p.map((x, j) => (j === i ? { ...x, text: v } : x)))}
          placeholder={t('entryPlaceholder')}
          placeholderTextColor={outdoor.textDim}
        />
      </View>
    ))}
    <Pressable disabled={locked}
      onPress={() => { setNone(false); setEntries((p) => [...p, { id: `m_${Date.now()}`, text: '', source: 'manual', included: true }]); }}>
      <Text style={s.secondaryBtnText}>{t('dobAddManual')}</Text>
    </Pressable>
    {entries.filter((e) => e.included && e.text.trim()).length === 0 ? (
      <Pressable disabled={locked} onPress={() => setNone((v) => !v)}
        style={[s.chip, none && s.chipSelected, { marginTop: spacing.sm }]}>
        {none ? <Check size={13} strokeWidth={2} /> : null}
        <Text style={[s.chipText, none && s.chipTextSelected]}>{noneLabel}</Text>
      </Pressable>
    ) : null}
  </Card>
);

export default function SiteSuperintendentLog() {
  // THE PALETTE IS PINNED, NOT THEMED, and this screen does not get a choice.
  // LogbookStepper renders `<AnimatedBackground pinned>` unconditionally, so
  // the canvas under every editor is the LIGHT `outdoor` gradient whatever
  // theme the CP has set — a compliance log gets filled outdoors, often in
  // direct sun. Reaching for useTheme() here would paint dark-mode ink (which
  // is LIGHT) onto that light canvas and the screen would be blank in dark
  // mode. `buildStepperStyles()` takes no arguments for the same reason.
  const s = buildStepperStyles();
  const router = useRouter();
  const toast = useToast();
  const t = useT('siteSuperintendent');
  const tFinalize = useT('finalize');
  const { user } = useAuth();
  const { projectId, date } = useLocalSearchParams();
  const logDate = String(date || todayISO());

  const { cpName, cpSignature, setCpSignature, setCpName, profileLoaded } = useCpProfile();
  const consent = useEsraConsent();

  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(true);
  const [locked, setLocked] = useState(false);
  const [signing, setSigning] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  // The last autosave did not land. Sticky, exactly as the siblings keep it:
  // it clears only when a later write succeeds, never on the next keystroke,
  // because a warning that decays is one he can miss by typing.
  const [autosaveFailed, setAutosaveFailed] = useState(false);
  // THE SERVER DISAGREES WITH THIS DRAFT — null when it does not, or when no
  // comparison was possible (offline). Set on the local-first branch below,
  // which until now returned without ever asking the server. The eleven
  // sibling editors carry this identically; this screen grew its local-first
  // branch in #363, AFTER they were fixed, so it arrived with the same defect
  // already solved next door.
  const [draftConflict, setDraftConflict] = useState(null);

  // THE DRAFT KEY — (project, log type, date), the same identity the server
  // dedups on and the same one draftSync's parseDraftKey reads back out. Built
  // from LOG_TYPE rather than a literal so the two can never drift.
  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date: logDate }),
    [projectId, logDate],
  );

  // The in-memory stash key, declared HERE rather than beside snapshot/restore
  // below because the load effect's applyHeld lists it as a dependency and a
  // dependency array is evaluated during render. See the note down there.
  const scratchId = scratchKey(LOG_TYPE, projectId, logDate);

  /** The server names the condition, the client owns the wording. */
  const gateCopy = useCallback((code) => {
    if (!code) return tFinalize('genericError');
    const key = `code_${code}`;
    const copy = tFinalize(key);
    return copy && copy !== key ? copy : tFinalize('genericError');
  }, [tFinalize]);

  // ── item state ──────────────────────────────────────────────────────────
  // ARRIVAL IS PREFILLED AND IS HIS TO CHANGE. He may open the app in his
  // truck, so the first-open time is a SUGGESTION, never an observation the
  // app asserts on a licensed signature. The screen says so in words
  // (presenceNote) as well as by leaving the field editable.
  const [arrivedAt, setArrivedAt] = useState('');
  const [departedAt, setDepartedAt] = useState('');
  // ── HE LEFT AFTER MIDNIGHT, AND HE SAYS SO ──────────────────────────────
  //
  // STORED, NEVER DERIVED. The obvious alternative is to notice that
  // `departed_at` sorts before `arrived_at` and conclude the shift crossed
  // midnight, and that is wrong twice over: a superintendent who typed 07:00
  // for a 19:00 departure would have the app silently reclassify his log as a
  // night shift, and a night shift that ran 20:00 to 20:30 the next evening
  // does not sort backwards at all and would be silently kept on one day.
  //
  // AND IT IS WHY THE TIMES STAY WALL-CLOCK STRINGS. The other way to express
  // this is to store an instant — and then all seven readers of these two
  // fields, none of which converts anything today, have to convert back to
  // Eastern to print them. The first one that forgets reprints the
  // 20:00-check-in and LL196 month-boundary bugs onto a licensed signature.
  // One boolean he sets costs nothing and asks nobody to convert.
  const [departedNextDay, setDepartedNextDay] = useState(false);
  const [printedName, setPrintedName] = useState('');
  const [progress, setProgress] = useState('');
  const [activities, setActivities] = useState('');
  const [locations, setLocations] = useState('');
  const [inspectedOn, setInspectedOn] = useState(logDate);
  const [inspectionLocation, setInspectionLocation] = useState('');
  const [inspectionResult, setInspectionResult] = useState('');
  const [findings, setFindings] = useState([]);
  const [noneBoth, setNoneBoth] = useState(false);
  const [dobEntries, setDobEntries] = useState([]);
  const [dobNone, setDobNone] = useState(false);
  const [incidentEntries, setIncidentEntries] = useState([]);
  const [incidentsNone, setIncidentsNone] = useState(false);
  const [competentPersonName, setCompetentPersonName] = useState('');

  const prefilledArrival = useRef(false);

  useEffect(() => {
    if (prefilledArrival.current) return;
    prefilledArrival.current = true;
    setArrivedAt((v) => v || nowClock());
  }, []);

  // PREFILLED FROM THE SESSION, NOT THE CACHED PROFILE.
  //
  // This was `if (cpName && !printedName) setPrintedName(cpName)`. `cpName`
  // comes from useCpProfile, a cache written AFTER a successful signature — so
  // it is blank for anyone who has never signed, and on a screen that has
  // never been signable that is everyone. It would have prefilled for one CP
  // and left the next man with an empty field on the one control that gates
  // filing.
  //
  // resolveSignerName reads the authenticated session ahead of the profile:
  // typed > stored draft > session > profile. See src/utils/signerName.js for
  // why the profile is LAST — on a shared device it is the previous user's
  // name, and putting that under a licensed signature is the fabrication class
  // the departure stamp already cost us.
  //
  // STILL ONLY A DEFAULT. It never overwrites what he has typed, and the field
  // stays editable at every step.
  useEffect(() => {
    setPrintedName((current) => current || resolveSignerName({
      typed: current, user, profileName: cpName,
    }));
  }, [cpName, user]);

  // ── load ────────────────────────────────────────────────────────────────
  //
  // THE DEVICE IS ASKED FIRST. That ordering IS local-first: a superintendent
  // opening his log in a cellar gets the log, not a spinner and an empty form.
  // The server is consulted only when this device holds nothing for the day.
  //
  // ANYTHING HE HAD TYPED GOES ON TOP OF EITHER ANSWER. The scratch stash is
  // NEWER than both, and RICHER than the draft: the draft stores the DOCUMENT
  // shape, which is lossy on purpose (deriveConditionAndOrderBlocks drops a
  // finding row with a location typed and no condition yet; unticked DOB
  // suggestions never reach it; the step he was on is not in it). So the draft
  // is not a replacement for the stash and does not become one.
  //
  // NEVER ONTO A FROZEN DOCUMENT, from either source. A log that came back
  // locked is read-only, and restoring edits onto it would put text on screen
  // that corresponds to nothing writable. `take` still clears the stash, so it
  // cannot resurface onto a later visit either.
  const applyHeld = useCallback((isLocked) => {
    const held = take(scratchId);
    if (held && !isLocked) restore(held);
  }, [scratchId]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    // Re-derived every load, so an amendment can unlock the screen.
    setLocked(false);
    // AND SO IS THE CONFLICT, for the same reason the lock above it is: a
    // verdict reached on the previous load is not evidence about this one. This
    // also re-arms the acknowledgement, which rides ON the verdict — a CP who
    // agreed to overwrite one server change must be asked again about the next.
    setDraftConflict(null);
    if (!projectId) { setLoading(false); return; }
    try {
      const draft = await readDraft(_key);
      const hasLocalContent = !!(draft && draft.data
        && Object.keys(draft.data).length > 0);

      // ── A FROZEN LOCAL RECORD IS ASKED ABOUT FIRST, EMPTY OR NOT ─────────
      //
      // Parent and amendment collide on ONE key — amend_logbook copies
      // project, type and date onto the child — so a screen that trusted a
      // finalized local draft would show the filed parent forever and the
      // correction the superintendent was handed would be unreachable.
      // adoptAmendment discards the local record only when the SERVER confirms
      // an unlocked child exists, and offline it does nothing at all.
      //
      // ASKED BEFORE THE CONTENT CHECK, and that ordering is the whole point.
      // The branch below writes an EMPTY finalized draft whenever this screen
      // opens a log the server has already locked — that is how the offline
      // lock gets recorded for a log filed from another session. It holds no
      // data, so a content-gated amendment check skips straight past it, and
      // then every autosave on the amendment is silently refused by
      // writeDraft's finalize lock while the screen looks perfectly fine and
      // the "this device is not saving your draft" warning is the only clue.
      // Same trap as the one above, in its quietest form.
      const amended = !!(draft && draft.finalized) && await adoptAmendment({
        key: _key, projectId, logType: LOG_TYPE, date: logDate,
      });

      if (!amended && hasLocalContent) {
        // ── ALWAYS ASK THE SERVER, EVEN THOUGH A DRAFT IS IN HAND ──────────
        //
        // Until this line the branch below returned with the server NEVER
        // fetched. Device content and the filed record were pixel-identical on
        // screen, and the sign path then PUT the whole draft into
        // update_logbook, which applies `data` as a wholesale $set — so a
        // server-side correction was reverted by a superintendent who did
        // nothing but open his log.
        //
        // OFFLINE IS UNCHANGED, and that is a requirement rather than a side
        // effect: compareDraftToServer never throws, and it reads a failed
        // fetch as "no comparison possible" rather than "the server wins", so a
        // superintendent with no signal opens exactly the screen he did before.
        // Only a CONFLICT is stored — a clean comparison and an unreachable
        // server are both null, and null blocks nothing.
        //
        // THE DRAFT IS STILL WHAT IS HYDRATED BELOW. Nothing here applies the
        // server document or discards the draft; the CP chooses, in the banner.
        const _cmp = await compareDraftToServer({
          draft, projectId, logType: LOG_TYPE, date: logDate,
        });
        setDraftConflict(_cmp.conflict ? _cmp : null);
        if (draft.finalized) { setLocked(true); markFinalized(_key); }
        setExistingLogId(draft.backend_id || null);
        hydrate(draft.data);
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        applyHeld(draft.finalized === true);
        setLoading(false);
        return;
      }
      // Nothing usable on the device, or the amendment was adopted: ask the
      // server, whose load already prefers the unlocked child.

      const arr = await logbooksAPI.getByProject(projectId, LOG_TYPE, logDate);
      const list = Array.isArray(arr) ? arr : (arr?.items || []);
      // Prefer the EDITABLE document — an amendment child over its locked
      // parent — the same rule every other editor's load applies.
      const existing = list.find((l) => l.is_locked !== true) || list[0] || null;
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        setLocked(existing.is_locked === true);
        // AND THE LOCK IS RECORDED ON THE DEVICE. Without this the offline
        // finalize lock never engages for a log frozen on the server by
        // someone else's session, and a reopen with no signal would offer an
        // editable form over a filed statutory record.
        if (existing.is_locked === true) markFinalized(_key);
        hydrate(existing.data || {});
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
      applyHeld(existing?.is_locked === true);
    } catch (_e) {
      // A failed read is not an empty log. Leave the form as it is and let him
      // work offline — which now means something, because the draft above is
      // real. His entry is still restored if he had any held.
      applyHeld(false);
    } finally {
      setLoading(false);
    }
  }, [_key, projectId, logDate, applyHeld]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── DOB autofill ────────────────────────────────────────────────────────
  // HE SHOULD NOT TYPE A VIOLATION NUMBER THE SYSTEM ALREADY HOLDS. These are
  // SUGGESTIONS: nothing reaches the record until he ticks it, because the log
  // is his statement about what was issued on this project, not a copy of a
  // feed. Anything the system has not seen he adds by hand.
  useEffect(() => {
    let alive = true;
    (async () => {
      if (!projectId) return;
      try {
        const rows = await dobAPI.getLogs(projectId, { record_type: 'violation', limit: 20 });
        const items = Array.isArray(rows) ? rows : (rows?.items || []);
        if (!alive || items.length === 0) return;
        setDobEntries((prev) => (prev.length ? prev : items.map((r) => ({
          id: `dob_${r.id || r._id || Math.random().toString(36).slice(2)}`,
          text: [r.number || r.violation_number, r.description || r.summary]
            .filter(Boolean).join(' — '),
          source: 'dob',
          included: false,     // HIS to confirm. Never pre-ticked.
        }))));
      } catch (_e) { /* the feed is a convenience; its absence is not an error */ }
    })();
    return () => { alive = false; };
  }, [projectId]);

  function hydrate(d) {
    const g = (k) => (d && d[k]) || {};
    // AS STORED, NOT AS THE PICKER WOULD HAVE WRITTEN IT. Nothing here runs a
    // stored value through a display helper: migration is forward-only, and a
    // record that comes back out of storage in a shape it did not go in with
    // is a record whose appearance changed after it was signed. TimeField's
    // own rule is the same one — a value it did not produce is echoed as
    // stored — and the autosave below writes back exactly this state, so
    // opening an old draft cannot rewrite it either.
    setArrivedAt(g('presence').arrived_at || '');
    setDepartedAt(g('presence').departed_at || '');
    // === true, so a log filed before this flag existed reads FALSE rather
    // than undefined. It is not an inference about that log: the flag says
    // "he told us he left after midnight", and a log that was never asked
    // did not tell us that.
    setDepartedNextDay(g('presence').departed_next_day === true);
    setPrintedName(g('presence').printed_name || '');
    setProgress(g('progress').summary || '');
    setActivities(g('cs_activities').summary || '');
    setLocations(g('cs_activities').locations || '');
    setInspectedOn(g('daily_inspection').inspected_on || logDate);
    setInspectionLocation(g('daily_inspection').location || '');
    setInspectionResult(g('daily_inspection').result || '');
    setCompetentPersonName(g('competent_person').name || '');
    setNoneBoth(g('unsafe_conditions').none_to_report === true
      && g('orders_given').none_to_report === true);
    setDobNone(g('dob_actions').none_to_report === true);
    setIncidentsNone(g('incidents').none_to_report === true);
    const conds = g('unsafe_conditions').entries || [];
    const orders = g('orders_given').entries || [];
    if (conds.length || orders.length) {
      setFindings(conds.map((c, i) => ({
        ...emptyFinding(),
        location: c.location || '', observed_at: c.observed_at || '',
        condition: c.condition || '',
        order_given: (orders[i] && orders[i].order) || '',
        order_to: (orders[i] && orders[i].given_to) || '',
        // A STORED BOOLEAN IS A PRE-TRI-STATE ROW. Map it rather than
        // dropping it: `false` meant "not corrected", which is still one of
        // the three answers, and discarding it would blank a statement he
        // already made on a filed document.
        corrected: (isCorrectionState(c.corrected) ? c.corrected
          : (c.corrected === true ? CORRECTED
            : (c.corrected === false ? NOT_CORRECTED : null))),
      })));
    }
    setDobEntries((g('dob_actions').entries || []).map((e, i) => ({
      id: `saved_${i}`, text: typeof e === 'string' ? e : (e.text || ''),
      source: 'saved', included: true,
    })));
    setIncidentEntries((g('incidents').entries || []).map((e, i) => ({
      id: `inc_${i}`, text: typeof e === 'string' ? e : (e.text || ''),
      source: 'saved', included: true,
    })));
  }

  // ── WHAT HE HAS TYPED, HELD ACROSS THE TRIP TO /consent ─────────────────
  //
  // THE RAW FIELDS, NOT buildData's DOCUMENT SHAPE. The document shape is
  // lossy by design — deriveConditionAndOrderBlocks drops a finding row that
  // has a location typed but no condition yet, and unticked DOB suggestions
  // never reach it at all. Those are still his work, and a screen that hands
  // back less than he left is not preserving anything.
  //
  // See logbookScratch.js for why this exists at all: the consent screen is a
  // route, and the claim that the navigator keeps this screen mounted beneath
  // it could not be verified. Correct under either answer.
  //
  // `scratchId` ITSELF IS DECLARED WITH `_key`, ABOVE. It has to be: the load
  // effect's applyHeld names it in a dependency array, and a dependency array
  // is evaluated during render — a `const` declared here would be in its
  // temporal dead zone and the screen would crash to the error boundary on
  // mount, which is exactly the class the mount smoke exists to catch.

  const snapshot = () => ({
    arrivedAt, departedAt, departedNextDay, printedName, progress, activities, locations,
    inspectedOn, inspectionLocation, inspectionResult,
    findings, noneBoth, dobEntries, dobNone, incidentEntries, incidentsNone,
    competentPersonName, step,
  });

  const restore = (v) => {
    if (!v || typeof v !== 'object') return;
    setArrivedAt(v.arrivedAt ?? '');
    setDepartedAt(v.departedAt ?? '');
    setDepartedNextDay(v.departedNextDay === true);
    setPrintedName(v.printedName ?? '');
    setProgress(v.progress ?? '');
    setActivities(v.activities ?? '');
    setLocations(v.locations ?? '');
    setInspectedOn(v.inspectedOn ?? logDate);
    setInspectionLocation(v.inspectionLocation ?? '');
    setInspectionResult(v.inspectionResult ?? '');
    setFindings(Array.isArray(v.findings) ? v.findings : []);
    setNoneBoth(v.noneBoth === true);
    setDobEntries(Array.isArray(v.dobEntries) ? v.dobEntries : []);
    setDobNone(v.dobNone === true);
    setIncidentEntries(Array.isArray(v.incidentEntries) ? v.incidentEntries : []);
    setIncidentsNone(v.incidentsNone === true);
    setCompetentPersonName(v.competentPersonName ?? '');
    // BACK ON THE STEP HE LEFT. Returning him to step 1 after a five-step form
    // is its own small loss.
    if (Number.isInteger(v.step) && v.step >= 1 && v.step <= TOTAL_STEPS) setStep(v.step);
  };

  // ── the document this screen would file ─────────────────────────────────
  // NO `departure` PARAMETER ANY MORE. It existed for one caller — the submit
  // handler, which passed the moment he tapped Sign so that a blank departure
  // could be back-filled from the clock. That stamp is gone (see handleSubmit),
  // and a parameter whose only purpose was to inject a value the CP never chose
  // is not something to keep for symmetry.
  const buildData = useCallback(() => {
    const both = deriveConditionAndOrderBlocks(findings, noneBoth);
    const dobChosen = dobEntries.filter((e) => e.included && e.text.trim());
    const incChosen = incidentEntries.filter((e) => e.included && e.text.trim());
    return {
      presence: {
        printed_name: printedName.trim(),
        // A WALL-CLOCK STRING, NOT AN INSTANT. See the note on
        // `departedNextDay` above for why, and `nowClock` for the format.
        arrived_at: arrivedAt.trim(),
        departed_at: departedAt.trim(),
        // ALWAYS WRITTEN, both ways. An absent key is the shape every other
        // defect in this log has had — absence read as a claim — and here the
        // claim would be "the shift did not cross midnight", which nobody
        // made. Written explicitly, it is the CP's answer and no reader ever
        // has to derive it from the two times.
        departed_next_day: departedNextDay === true,
      },
      progress: progress.trim() ? { summary: progress.trim() } : {},
      cs_activities: (activities.trim() || locations.trim())
        ? { summary: activities.trim(), locations: locations.trim() } : {},
      ...both,
      dob_actions: dobChosen.length
        ? { entries: dobChosen.map((e) => ({ text: e.text.trim(), source: e.source })) }
        : (dobNone ? { none_to_report: true } : {}),
      incidents: incChosen.length
        ? { entries: incChosen.map((e) => ({ text: e.text.trim() })) }
        : (incidentsNone ? { none_to_report: true } : {}),
      competent_person: competentPersonName.trim()
        ? { name: competentPersonName.trim() } : {},
      daily_inspection: (inspectionLocation.trim() || inspectionResult.trim())
        ? {
          inspected_on: inspectedOn.trim(),
          location: inspectionLocation.trim(),
          result: inspectionResult.trim(),
        } : {},
    };
  }, [findings, noneBoth, dobEntries, dobNone, incidentEntries, incidentsNone,
    printedName, arrivedAt, departedAt, departedNextDay,
    progress, activities, locations,
    inspectedOn, inspectionLocation, inspectionResult, competentPersonName]);

  // ── AUTOSAVE ────────────────────────────────────────────────────────────
  //
  // NO `status`, AND THAT IS THE POINT. writeDraft preserves any field left
  // undefined, so an autosave that never names `status` cannot promote a
  // half-typed log to `submitted` — and it must not be able to, because the
  // reconnect drain replays whatever it finds in the draft. Naming it here
  // would be a way for a log nobody signed to file itself behind him.
  //
  // NOT A TOAST WHEN IT FAILS. A superintendent saving every few seconds does
  // not need a message each time, and one that fires constantly is one he
  // stops reading. It drives the SUBMIT WARNING instead — he is told once, at
  // the last moment it can still matter.
  useEffect(() => {
    if (loading || locked) return undefined;
    const h = setTimeout(() => {
      writeDraft(_key, {
        data: buildData(),
        cp_signature: cpSignature,
        cp_name: printedName.trim() || cpName,
      })
        .then((_ok) => setAutosaveFailed(!_ok))
        .catch(() => setAutosaveFailed(true));
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, buildData, cpSignature, cpName, printedName]);

  /** Write what is on screen right now — used when he changes step. */
  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const _ok = await writeDraft(_key, {
        data: buildData(),
        cp_signature: cpSignature,
        cp_name: printedName.trim() || cpName,
      });
      setAutosaveFailed(!_ok);
    } catch (_e) { setAutosaveFailed(true); }
  }, [locked, _key, buildData, cpSignature, cpName, printedName]);

  // THE SUBMIT GATE MIRRORS THE SERVER, WHICH REMAINS THE AUTHORITY.
  // create_logbook raises SUBMIT_UNATTESTED_ITEMS; this only decides whether
  // the button is reachable and names the items so he is not guessing.
  const unanswered = csUnanswered(buildData(), logDate);

  // ── ARRIVAL AND DEPARTURE ARE REQUIRED, AND csUnanswered CANNOT SAY SO ────
  //
  // THE STRUCTURAL REASON, because it is not an oversight anybody can fix in
  // the model. Item 1 is declared `attestable: false` in
  // superintendentLogModel.js, and `csUnanswered` filters on `i.attestable`
  // before it looks at any content. So the gate above is INCAPABLE of naming
  // presence: "unanswered" there means "no content AND no nothing-to-report
  // tick", and item 1 has no tick to make. A superintendent does not attest
  // that he has nothing to report about his own presence; he states two times.
  //
  // AND FLIPPING THE FLAG WOULD BE WORSE. `attestable: true` on item 1 makes
  // `none_to_report` a legal answer to it — the CS asserting he was not on the
  // site, on the log that exists to record that he was — and it changes
  // `csItemState` for every log already filed, which is a rewrite of records
  // nobody may rewrite. The parity test against
  // backend/lib/logbook/superintendent_log.py would then demand the same
  // change on the server, spreading it to both PDF renderers.
  //
  // SO THIS IS A SECOND GATE, BESIDE THE FIRST, and it names FIELDS rather
  // than an item — which is also what makes it useful to him: "presence" is
  // not a thing he can go and fill in, ARRIVED and DEPARTED are.
  //
  // IT ALSO CATCHES WHAT `hasContent` CANNOT. csItemState calls item 1 PRESENT
  // as soon as ANY of its four declared fields carries something, so a printed
  // name alone makes the item look answered on every reader while both times
  // are blank — absence read as a claim, the defect family this log keeps
  // producing.
  const arrivalMissing = !arrivedAt.trim();
  const departureMissing = !departedAt.trim();
  const presenceMissing = [
    arrivalMissing ? t('arrivedAt') : null,
    departureMissing ? t('departedAt') : null,
  ].filter(Boolean);

  const handleSubmit = async () => {
    if (signing || locked) return;
    // NO SILENT OVERWRITE — WHICH IS NOT THE SAME AS NO OVERWRITE.
    //
    // This path PUTs `data` as a wholesale $set, so pushing over a changed
    // server document really does revert it. THE SUPERINTENDENT'S DRAFT WINS
    // anyway: it is the most recent authorship and he is the one who made it.
    // What `submitRefused` withholds is the SILENT case — it stays true until
    // he has been shown the server change and taken the override in the banner,
    // and then it opens.
    //
    // AND IT NEVER OPENS FOR A FILED OR FINALIZED SERVER DOCUMENT. That is a
    // signed compliance record, not a competing draft; the server refuses the
    // write (423 / 409) and Amend is the route that corrects one.
    //
    // THE SAME PREDICATE THE SUBMIT BUTTON ASKS, so a live button and a
    // refusing save path cannot disagree — and the SAME predicate the other
    // eleven editors ask, so a CP does not learn this twelve ways.
    if (submitRefused(draftConflict)) return;
    // ── THE DEPARTURE STAMP IS GONE, AND THAT IS THE POINT OF THIS GATE ────
    //
    // This read `const departure = departedAt.trim() || nowHHMM();` and wrote
    // the moment he tapped Sign straight into `departed_at`. Three things were
    // wrong with it:
    //
    //   IT IS THE APP ASSERTING AN OBSERVATION on a licensed signature — the
    //   exact thing the note beside `arrivedAt` forbids for arrival. Arrival's
    //   prefill lands in a VISIBLE field he can correct for as long as he is
    //   filling the log; this one landed in the payload at the instant of
    //   filing, where he never saw it and could never correct it.
    //
    //   IT WAS NOT WHEN HE LEFT. 3301.13.13 wants the time he departed the
    //   job site; the clock at signature is the time he signed, and on a log
    //   he is required to complete BEFORE departing those are different by
    //   construction.
    //
    //   AND IT MADE THE REQUIREMENT UNREACHABLE. Departure could not be blank
    //   at submit, so no gate could ever tell him it was missing.
    //
    // He picks it, from the same clock list as everything else on this screen.
    if (presenceMissing.length > 0) return;
    if (!isAffirmedSignature(cpSignature)) return;
    if (unanswered.length > 0) return;

    // ── THE AGREEMENT TO SIGN ELECTRONICALLY ───────────────────────────────
    //
    // BB 2024-007 § V.5. The backend has recorded this since #308 and nothing
    // ever asked for it, so every signature applied before this line existed
    // was applied without recorded consent — and no later migration can fix
    // that, because a consent recorded in October does not describe a
    // signature applied in September.
    //
    // ASKED HERE, AT THE SIGNATURE, AND NOT AT SCREEN OPEN. Consent is about
    // the act of signing, so the act is what it gates. He fills the whole log
    // either way; nothing he typed is at risk, and a man who has already
    // consented — which is everyone after the first time — never sees it.
    //
    // ANYTHING OTHER THAN A RECORDED CURRENT CONSENT STOPS HERE and opens the
    // sheet in place. `ensure()` returns false for not-agreed, for superseded
    // wording, AND for "could not ask" — the last one deliberately, because a
    // signature applied while we cannot tell whether consent exists is the
    // defect this whole path removes. The sheet names which case it is.
    //
    // HIS ENTRY IS HELD FIRST, because `ensure()` may navigate. See
    // logbookScratch.js: the consent screen is a route, and whether this
    // screen stays mounted beneath it is a property of the navigator that
    // could not be verified. Stashing makes the answer irrelevant — if it
    // stays mounted the stash is written and never read.
    stash(scratchId, snapshot());
    if (!(await consent.ensure())) return;
    // He is still here, so nothing was navigated away from and the stash is
    // dead weight. Drop it rather than leaving it to be restored onto a
    // later, different visit.
    drop(scratchId);

    setSigning(true);
    const data = buildData();
    // ONE RESOLUTION, shared with the pad above — see the `signerName` const
    // near the render. Kept as a local so the submit cannot drift from what
    // the signer was shown when he signed.
    const signerName = resolveSignerName({
      typed: printedName, user, profileName: cpName,
    });

    // ── THE LOCAL SAVE, BEFORE THE PUSH, AND ITS ANSWER IS NOT DISCARDABLE ──
    //
    // This is the offline record. Everything below that promises a later sync
    // — the pending key, the "saved on this device" banner, the on-device
    // freeze — rests on this write having happened, so its BOOLEAN is carried
    // down to every one of those branches. writeDraft returns false for a
    // refused write and catches its own storage errors; the try covers a throw
    // anyway, because a caller that handles one failure mode and not the other
    // has fixed half of this.
    //
    // When it fails, what he has just signed exists only in React state, and
    // queueing the key would be worse than not queueing it: the drain would
    // read the last autosave — unsigned content, filed under this key — or
    // find nothing and clear the key as `no-draft`.
    let localSaved = false;
    try {
      localSaved = await writeDraft(_key, {
        data, cp_signature: cpSignature, cp_name: signerName, status: 'submitted',
      });
    } catch (_e) {
      localSaved = false;
    }
    setAutosaveFailed(!localSaved);

    /**
     * FREEZE ON THIS DEVICE — and never on a signature that did not earn it.
     *
     * markFinalized makes the draft IMMUTABLE: writeDraft refuses every later
     * content edit. The drain, in turn, refuses to push a `submitted` draft
     * whose signature is not AFFIRMED (`{}` is truthy, and production held
     * exactly that shape). Freeze one of those and the log can never be
     * corrected and can never be sent, while the screen shows it as filed —
     * a trap with no exit but a reinstall. The guard at the top of this
     * handler already refuses an unaffirmed submit; this says so again at the
     * point where the damage would be permanent.
     */
    const freezeLocally = async () => {
      if (!isAffirmedSignature(cpSignature)) return;
      await markFinalized(_key);
    };

    /** Offline, but the device holds it: announce that, freeze here, queue it. */
    const reportHeldOnDevice = async (handle) => {
      await freezeLocally();
      await markPending(_key);
      // ON THIS DEVICE ONLY — durable, not a toast. He is attesting to a legal
      // record and a toast is gone in four seconds, so LogbookLockBar renders
      // this on his next visit and draftSync takes it down when the push
      // lands. Recorded against the log id when one exists and against the
      // DRAFT KEY when it does not — an offline create has no server id, which
      // is exactly the case that most needs the banner.
      await recordFinalizeError(handle, 'NOT_ON_SERVER', _key, 'unsynced');
      setLocked(true);
      toast.success(t('savedLocallyTitle'), t('savedLocally'));
      router.push('/logbooks');
    };

    /** The local write failed too, so nothing anywhere holds this log. */
    const reportNothingSaved = async (handle) => {
      await recordFinalizeError(handle, 'LOCAL_SAVE_FAILED', _key, 'local');
      toast.error(tFinalize('localSaveFailedTitle'), tFinalize('localSaveFailed'));
    };

    try {
      const payload = {
        project_id: projectId,
        log_type: LOG_TYPE,
        date: logDate,
        data,
        cp_signature: cpSignature,
        cp_name: signerName,
        status: 'submitted',
      };
      const saved = existingLogId
        ? await logbooksAPI.update(existingLogId, payload)
        : await logbooksAPI.create(payload);
      const savedId = saved?.id || saved?._id || existingLogId;

      // ── NO ID, NO RECORD ───────────────────────────────────────────────
      //
      // ABSENCE OF AN EXCEPTION IS NOT PROOF OF A WRITE. `create` resolving
      // proves only that a response arrived; the id is the one thing in it
      // that proves a document exists — and it is also the only way to name
      // the document that has to be sealed.
      //
      // THIS IS WHERE THE LOG WAS LOST. The two calls that NEED an id were
      // guarded (`if (savedId)`) and the three lines that REPORT one were
      // not, so a response with no id skipped the ledger event, skipped the
      // finalize, and still said "Log filed and locked" — copy that asserts
      // the seal by name — then navigated away from the screen holding the
      // only copy of what he had typed. Nothing threw, so nothing was
      // reported.
      //
      // AND THE SERVER HAS THAT PATH. create_logbook re-reads the row it just
      // inserted and returns serialize_id(that read); a read that does not see
      // its own write makes it None, which FastAPI renders as 200 `null`. The
      // server half is fixed too (backend/tests/test_superintendent_log_files
      // .py), and this guard must hold regardless of it: a client that
      // believes a body it did not check is one bad deploy from doing this
      // again.
      //
      // THROWN, NOT RETURNED, so it lands in the one place this handler
      // reports a failure to file. That is also what makes it compose with
      // fix/superintendent-local-first: its catch sorts a push failure into
      // refused / offline / unsynced and holds the entry on the device, and a
      // throw here is routed by that sort like any other failed push.
      if (!savedId) throw new Error(NO_RECORD_RETURNED);

      setExistingLogId(savedId);
      // BIND THE SERVER ID ONTO THE DRAFT. Without it a later drain would take
      // this key for a create and the server would refuse it as already filed.
      //
      // UNCONDITIONAL, like the two below it. The guard above is what makes
      // that safe, and setDraftBackendId(_key, undefined) is precisely the
      // write that would have made this binding a lie.
      await setDraftBackendId(_key, savedId);

      // ── THE SIGNATURE EVENT ────────────────────────────────────────────
      // `superintendent_sign`, NEVER `cp_sign`. See the note at the top of
      // this file: deriveActingCapacity reads the event type first, and the
      // wrong one records this log as signed by a Competent Person.
      //
      // ── AWAITED HERE, AND ONLY HERE ──────────────────────────────────────
      //
      // THIS IS THE ONE EDITOR THAT SEALS IN THE SAME BREATH IT SIGNS. The
      // finalize a few lines below makes the record immutable, and the server
      // now asks the ledger at that moment whether an event exists for this
      // document. Fired and forgotten, this POST races that seal: the server
      // would report a gap for a row that is merely in flight, and a detector
      // that cries wolf is a detector nobody reads. Awaiting orders the two,
      // so a gap reported at finalize is a real one.
      //
      // NON-BLOCKING IS UNCHANGED. recordSignatureEvent catches its own error
      // and resolves with null; it has never rejected, which is why the
      // `.catch` that used to sit here had never once run. Awaiting a promise
      // that cannot reject cannot refuse the log — it only costs the round
      // trip, which this handler is already paying for twice.
      //
      // AND THE null IS READ. It is the function's whole failure report; the
      // caller that is about to seal the record is the last one that may throw
      // it away.
      //
      // NO LONGER `if (savedId)`. The guard above already refused the case
      // this was written for, and a condition that can no longer be false
      // reads as though the caller is still unsure — which is the shape the
      // whole defect had.
      const _evtId = await recordSignatureEvent({
        documentType: 'logbook',
        documentId: savedId,
        eventType: 'superintendent_sign',
        signerName: printedName.trim() || cpName,
        signerRole: user?.role || 'cp',
        signatureData: cpSignature,
        contentSnapshot: {
          log_type: LOG_TYPE, date: logDate, project_id: projectId,
          data: payload.data, status: 'submitted',
        },
        user,
      });
      if (!_evtId) {
        console.error(
          '[signature-ledger] the superintendent log is about to be sealed '
          + 'with no audit row.',
          { documentId: savedId, projectId, date: logDate, logType: LOG_TYPE },
        );
      }

      // ── THE FREEZE, AND WHY IT IS AN EXPLICIT CALL ─────────────────────
      // 3301.13.13: "complete such log prior to departing the job site."
      //
      // THIS CALL IS THE MECHANISM, NOT A WORKAROUND. The server's own
      // published contract (logbook_timing_meta) says, for class `visit`:
      //
      //     freeze_on_sign      false
      //     freeze_on_finalize  TRUE
      //     is_batchable        false
      //
      // with the note "A VISIT LOG FREEZES WHEN ITS AUTHOR SIGNS ON
      // DEPARTURE. That is a finalize, not a sign-and-freeze." So create and
      // update correctly leave it unlocked — `is_immediate_preshift` is meant
      // to be false here — and the author's finalize is what closes it.
      //
      // IT IS ALSO WHY NOTHING ELSE WILL. sweep_stale_end_of_day_logs
      // deliberately excludes VISIT_LOG_TYPES, because an overnight sweep
      // would freeze a visit its author had not finished. There is no second
      // actor: if this screen does not finalize, the document stays editable
      // indefinitely while showing as signed.
      //
      // ON A MAJOR BUILDING the DEADLINE is end of day rather than departure
      // (superintendent_log_deadline). That governs how late he may sign, not
      // what signing does — signing early is never a violation — so the
      // freeze is the same act on every project.
      //
      // AND IT IS THE ONE CALL THAT CAN FAIL AFTER THE CONTENT LANDED, which
      // is why it has its own catch. The document is on the server and
      // UNLOCKED; the two ways that can happen are not the same thing and must
      // not read the same to him.
      //
      // UNCONDITIONAL, for the reason the guard above gives. `if (savedId)`
      // wrapped this whole block until the guard made it dead: the seal was
      // quietly opting out beside a success message that says "filed and
      // LOCKED" — and there is no second actor to notice, because
      // sweep_stale_end_of_day_logs excludes VISIT_LOG_TYPES, so a log this
      // screen does not finalize is never finalized by anything. The catch
      // stays; it is about a finalize that FAILED, which is a different
      // question from a finalize that was never attempted.
      try {
        await logbooksAPI.finalize(savedId);
      } catch (freezeErr) {
        const status = freezeErr?.response?.status;
        if (typeof status === 'number' && status >= 400 && status < 500) {
          // A JUDGEMENT. The server looked at the log and refused to freeze
          // it, and it will keep refusing until the log changes. Never
          // frozen locally: the device must not claim a lock the record
          // does not have.
          const code = finalizeErrorCode(freezeErr);
          await recordFinalizeError(savedId, code, _key, 'editor');
          toast.error(tFinalize('errorTitle'), gateCopy(code));
          return;
        }
        // NOT A JUDGEMENT — it never arrived. The content is filed, the
        // freeze is owed, and draftSync's applyRemoteFreeze re-applies it on
        // reconnect precisely because the draft says finalized.
        if (localSaved) { await reportHeldOnDevice(savedId); return; }
        await reportNothingSaved(savedId);
        return;
      }

      // The server holds it and it is locked. Record the same freeze here, so
      // a reopen with no signal shows the filed log as filed.
      await freezeLocally();
      await clearPending(_key);
      // BOTH HANDLES. A banner raised while offline was recorded against the
      // DRAFT KEY, because there was no server id yet; clearing only by id
      // would leave it up permanently, and a banner that cannot come down is
      // how a superintendent learns to read past all of them.
      //
      // THE SECOND IS NO LONGER CONDITIONAL EITHER. It was written
      // `if (savedId)` for the same reason the wrapper above was, and the
      // guard has retired that reason: leaving the test in would say the
      // handler is still unsure whether it has an id, which is the exact
      // shape of the defect this branch exists to remove.
      await clearFinalizeError(_key);
      await clearFinalizeError(savedId);

      setLocked(true);
      toast.success(t('filed'));
      router.push('/logbooks');
    } catch (pushErr) {
      // ── WHAT WAS DONE, AND WHAT HE IS TOLD, ARE TWO QUESTIONS ──────────
      //
      // The SORT below decides what HAPPENS — queue the key, freeze on the
      // device, raise a durable banner, or stay put and let him fix it.
      // `reasonFor` decides what he READS. They are computed separately
      // because they do not partition the same way: SUBMIT_UNATTESTED_ITEMS
      // and a FINALIZE_* refusal are both 4xx and take the same branch, but
      // only one of them can name the items he left blank. Folding the
      // wording into the sort is what would force one to be dropped for the
      // other, and both halves of this merge are load-bearing.
      //
      // SUBMIT_UNATTESTED_ITEMS carries `items` precisely so the client can
      // point at the items he has not answered. This printed the bare machine
      // code and threw the useful half away, leaving a man on a jobsite to
      // read "SUBMIT_UNATTESTED_ITEMS" and guess which of the four it meant.
      //
      // SAME WORDING AS THE HINT on the disabled button, through the same
      // labels: one condition must not be described two ways depending on
      // whether the client or the server noticed it.
      const detail = pushErr?.response?.data?.detail;
      const items = Array.isArray(detail?.items) ? detail.items : [];

      /** The most specific sentence this failure can be given. */
      const reasonFor = (code) => {
        if (items.length) {
          return t('unansweredHint').replace('{items}', csItemLabels(items).join(', '));
        }
        // NOT A CODE. This one is not the server refusing him anything he can
        // correct — it is the app declining to claim a filing it cannot
        // prove, and what he needs to know is that nothing was confirmed and
        // his entry is still here.
        if (pushErr?.message === NO_RECORD_RETURNED) return t('noRecordReturned');
        // gateCopy, NOT the raw code: the server names the condition, this
        // screen owns the wording. It is the reason `couldNotFile` stopped
        // printing `detail.code` at him in the first place.
        return gateCopy(code);
      };

      // REFUSAL IS NOT OFFLINE, and neither is a 5xx. Three outcomes, and the
      // superintendent is told a different thing in each.
      const handle = existingLogId || _key;
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;

      if (refused) {
        // The server judged the log. The draft is untouched and still
        // editable, so fixing it and submitting again is the remedy — the key
        // is deliberately NOT queued for a replay of a write it just refused.
        // This is the branch SUBMIT_UNATTESTED_ITEMS arrives on, and the one
        // where naming the items is the whole difference between a refusal he
        // can act on and a machine string.
        const code = finalizeErrorCode(pushErr);
        await recordFinalizeError(handle, code, _key, 'editor');
        toast.error(t('couldNotFile'), reasonFor(code));
        return;
      }

      if (!localSaved) {
        // Nothing to defer to. Offline is the one failing path that still
        // reports success, and it does so on the strength of a local draft the
        // drain will send later. With no such draft there is no record
        // anywhere, so nothing is queued and nothing is announced.
        await reportNothingSaved(handle);
        return;
      }

      if (!isOfflineError(pushErr)) {
        // A 5xx reached a server that then failed — OR the write answered 200
        // with nothing that names a record (NO_RECORD_RETURNED, thrown above).
        // THE SAME THING IS TRUE OF BOTH: a server was reached, the document's
        // fate is unknown, and the work is on this device. So both are queued
        // and neither may claim the log was filed. It is deliberately NOT
        // reportHeldOnDevice — that freezes the draft, announces a success and
        // navigates away, and none of the three is honest about a filing this
        // handler could not confirm. He stays on the screen and can retry,
        // which is what `noRecordReturned` tells him to do.
        await markPending(_key);
        await recordFinalizeError(handle, 'NOT_ON_SERVER', _key, 'unsynced');
        toast.error(t('couldNotFile'), reasonFor(null));
        return;
      }

      await reportHeldOnDevice(handle);
    } finally {
      setSigning(false);
    }
  };

  // Moving between steps is never BLOCKED — it just writes what he has first.
  const onStepChange = useCallback(async (next) => {
    await flushDraft();
    setStep(Math.max(1, Math.min(TOTAL_STEPS, next)));
  }, [flushDraft]);

  // ── steps ───────────────────────────────────────────────────────────────
  // WHAT THE PAD SHOWS AND WHAT handleSubmit SENDS ARE THE SAME VALUE.
  // Two independent expressions here is how a document gets signed under one
  // name and filed under another.
  const signerName = resolveSignerName({
    typed: printedName, user, profileName: cpName,
  });

  const stepPresence = () => (
    <Card s={s}>
      <StepHeaderBase s={s} title={t('presenceHeading')} />
      <Text style={s.noteText}>{t('presenceNote')}</Text>
      <Field s={s} locked={locked} label={t('printedName')} value={printedName} onChangeText={setPrintedName} />
      {/* TAPPED, NOT TYPED. These were `<Field placeholder="HH:MM">` — a free
          text box in which "7", "0730", "7:30pm" and "seven" were all
          acceptable, on the two fields BC 3301.13.13 exists to record. No
          `locked` prop is passed for the same reason the other four editors
          pass none: LogbookStepper renders FiledLogView instead of the steps
          on a filed log, and wraps them in `pointerEvents="none"` besides, so
          a picker on a frozen record is unreachable by construction rather
          than by a prop somebody has to remember. */}
      <TimeField
        s={s}
        label={t('arrivedAt')}
        placeholder={t('phTime')}
        value={arrivedAt}
        clearLabel={t('dateClear')}
        doneLabel={t('dateDone')}
        onChange={setArrivedAt}
        required={arrivalMissing}
        requiredLabel={t('requiredField')}
      />
      <TimeField
        s={s}
        label={t('departedAt')}
        placeholder={t('phTime')}
        value={departedAt}
        clearLabel={t('dateClear')}
        doneLabel={t('dateDone')}
        onChange={setDepartedAt}
        required={departureMissing}
        requiredLabel={t('requiredField')}
      />
      {/* MARKED FROM THE START, BUT `nextDisabled` IS DELIBERATELY NOT SET.
          toolbox_talk blocks Next on its required step-1 fields; this screen
          must not, because in the morning he does not yet know when he will
          leave. The mark says the field is required, the submit gate is what
          enforces it, and he can fill the other four steps in between. */}
      <Pressable
        disabled={locked}
        accessibilityRole="button"
        accessibilityState={{ checked: departedNextDay }}
        onPress={() => setDepartedNextDay((v) => !v)}
        style={[s.chip, departedNextDay && s.chipSelected]}
      >
        {departedNextDay ? <Check size={13} strokeWidth={2} /> : null}
        <Text style={[s.chipText, departedNextDay && s.chipTextSelected]}>
          {t('departedNextDay')}
        </Text>
      </Pressable>
      <Text style={s.noteText}>{t('departedNextDayNote')}</Text>
    </Card>
  );

  const stepWork = () => (
    <>
      <Card s={s}>
        <Field s={s} locked={locked} label={t('progressLabel')} value={progress} onChangeText={setProgress}
          placeholder={t('progressPlaceholder')} multiline />
        <Field s={s} locked={locked} label={t('activitiesLabel')} value={activities} onChangeText={setActivities}
          placeholder={t('activitiesPlaceholder')} multiline />
        <Field s={s} locked={locked} label={t('locationsLabel')} value={locations} onChangeText={setLocations}
          placeholder={t('locationsPlaceholder')} />
      </Card>
      <Card s={s}>
        <StepHeaderBase s={s} title={t('inspectionHeading')} />
        {/* 1 RCNY 3301-04(f) NEEDS THREE THINGS, so it asks for three rather
            than one blank box: when, where, what was found. A freeform result
            is accepted for now — the 3310-01 tables are the eventual answer
            and are their own piece of work — but the DATE and the LOCATION
            are not optional prose. */}
        <Text style={s.noteText}>{t('inspectionNote')}</Text>
        <Field s={s} locked={locked} label={t('inspectedOn')} value={inspectedOn} onChangeText={setInspectedOn} />
        <Field s={s} locked={locked} label={t('inspectionLocation')} value={inspectionLocation}
          onChangeText={setInspectionLocation} />
        <Field s={s} locked={locked} label={t('inspectionResult')} value={inspectionResult}
          onChangeText={setInspectionResult}
          placeholder={t('inspectionResultPlaceholder')} multiline />
      </Card>
    </>
  );

  const stepFindings = () => (
    <Card s={s}>
      <StepHeaderBase s={s} title={t('findingsHeading')} />
      <Text style={s.noteText}>{t('findingsNote')}</Text>

      {findings.map((f, i) => (
        <View key={f.id} style={s.cardFill}>
          <Field s={s} locked={locked} label={t('findingLocation')} value={f.location}
            onChangeText={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, location: v } : x)))} />
          {/* NOT `required`. findingGaps asks for WHERE, WHAT YOU SAW and
              WHETHER IT WAS CORRECTED and deliberately not this — a finding
              with no time is still a record a reader can act on. The control
              changes; the gate does not. */}
          <TimeField
            s={s}
            label={t('findingObservedAt')}
            placeholder={t('phTime')}
            value={f.observed_at}
            clearLabel={t('dateClear')}
            doneLabel={t('dateDone')}
            onChange={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, observed_at: v } : x)))}
          />
          <Field s={s} locked={locked} label={t('findingCondition')} multiline value={f.condition}
            onChangeText={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, condition: v } : x)))} />
          <Field s={s} locked={locked} label={t('findingOrder')} multiline value={f.order_given}
            onChangeText={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, order_given: v } : x)))} />
          <Field s={s} locked={locked} label={t('findingOrderTo')} value={f.order_to}
            onChangeText={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, order_to: v } : x)))} />
          <CorrectionChoice s={s} locked={locked} t={t} label={t('findingCorrected')} value={f.corrected}
            onChange={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, corrected: v } : x)))} />
          {findingGaps(f).length > 0 && !findingIsEmpty(f) ? (
            <Text style={s.errorText}>{findingGaps(f).join(', ')}</Text>
          ) : null}
          <Pressable disabled={locked} onPress={() => setFindings((p) => p.filter((_, j) => j !== i))}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Trash2 size={14} strokeWidth={1.5} color={outdoor.textDim} />
              <Text style={s.noteText}>{t('findingRemove')}</Text>
            </View>
          </Pressable>
        </View>
      ))}

      <Pressable disabled={locked}
        onPress={() => { setNoneBoth(false); setFindings((p) => [...p, emptyFinding()]); }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 12 }}>
          <Plus size={16} strokeWidth={1.75} color={outdoor.text} />
          <Text style={s.secondaryBtnText}>{t('findingAdd')}</Text>
        </View>
      </Pressable>

      {/* ONE TAP, TWO STATUTORY ITEMS — and the label says so. He is attesting
          to item 4 AND item 5 at once, which is only defensible because the
          control names both. Suppressed once there are findings: a list with
          entries and a "nothing to report" tick is a contradiction. */}
      {findings.filter((f) => !findingIsEmpty(f)).length === 0 ? (
        <>
          <Pressable disabled={locked} onPress={() => setNoneBoth((v) => !v)}
            style={[s.chip, noneBoth && s.chipSelected]}>
            {noneBoth ? <Check size={13} strokeWidth={2} /> : null}
            <Text style={[s.chipText, noneBoth && s.chipTextSelected]}>{t('noneBoth')}</Text>
          </Pressable>
          <Text style={s.noteText}>{t('noneBothNote')}</Text>
        </>
      ) : null}
    </Card>
  );

  const stepDob = () => (
    <>
      <EntryList s={s} locked={locked} t={t}
        heading={t('dobHeading')} note={t('dobNote')}
        entries={dobEntries} setEntries={setDobEntries}
        none={dobNone} setNone={setDobNone} noneLabel={t('dobNoneToReport')} />
      <EntryList s={s} locked={locked} t={t}
        heading={t('incidentsHeading')} note={t('incidentsNote')}
        entries={incidentEntries} setEntries={setIncidentEntries}
        none={incidentsNone} setNone={setIncidentsNone}
        noneLabel={t('incidentsNoneToReport')} />
    </>
  );

  const stepSign = () => {
    const data = buildData();
    // ITEMS THIS RELEASE DOES NOT COLLECT, NAMED. An item of the eleven that
    // is simply missing reads as an omission; one that says it is not
    // collected reads as scope. csItemState returns NOT_COLLECTED for exactly
    // these, off the declared items — this screen does not decide it.
    const scopeItems = csLogItems(logDate)
      .filter((it) => csItemState(it.key, data, logDate) === 'not_collected');
    return (
      <>
        <Card s={s}>
          <StepHeaderBase s={s} title={t('competentPersonHeading')} />
          <Field s={s} locked={locked} label={t('competentPersonName')} value={competentPersonName}
            onChangeText={setCompetentPersonName} />
          <Text style={s.noteText}>{t('competentPersonNote')}</Text>
        </Card>

        {scopeItems.length > 0 ? (
          <Card s={s}>
            <StepHeaderBase s={s} title={t('scopeHeading')} />
            <Text style={s.noteText}>{t('scopeNote')}</Text>
            {scopeItems.map((it) => (
              <Text key={it.key} style={s.noteText}>{`${it.number}. ${it.label}`}</Text>
            ))}
          </Card>
        ) : null}

        <Card s={s}>
          <StepHeaderBase s={s} title={t('signHeading')} />
          <Text style={s.noteText}>{t('signNote')}</Text>
          {/* THREE PROP NAMES, NONE OF WHICH THIS COMPONENT DECLARES.
              This read `value` / `onChange` / `name`. SignaturePad takes
              `existingSignature` / `onSignatureCapture` / `signerName` /
              `onNameChange`. React passes unknown props through and the
              destructure yields undefined, so nothing errored and nothing
              worked:

                value={signerName || ''}                 -> always ''
                onChangeText={(t) => onNameChange && onNameChange(t)}  -> no-op

              A controlled input whose value is a constant and whose handler is
              undefined: every keystroke discarded, field re-renders empty.
              That is the "will not accept typing" report, and it is ONE defect
              with the blank, not two.

              AND onSignatureCapture WAS UNDEFINED TOO, so the signature could
              never be captured either. The pad was fully inert and Sign and
              Freeze was unreachable.

              BLAST RADIUS, MEASURED: db.logbooks holds ZERO documents of
              log_type "site_superintendent_log". This statutory log has never
              been filed by anyone since launch, and three misspelled prop
              names are the reason. */}
          <SignaturePad
            pinned
            title={t('signHeading')}
            signerName={signerName}
            onNameChange={setPrintedName}
            existingSignature={cpSignature}
            onSignatureCapture={setCpSignature}
          />
        </Card>
      </>
    );
  };

  const STEPS = [
    { key: 1, label: t('stepPresence'), render: stepPresence },
    { key: 2, label: t('stepWork'), render: stepWork },
    { key: 3, label: t('stepFindings'), render: stepFindings },
    { key: 4, label: t('stepDob'), render: stepDob },
    { key: 5, label: t('stepSign'), render: stepSign },
  ];

  // THE SAME LABELS THE REFUSAL RENDERS. csItemLabels is what handleSubmit's
  // catch uses on the server's `items` list, so the hint on the disabled
  // button and the message from a 400 cannot come to name one item two ways.
  const unansweredLabels = csItemLabels(unanswered).join(', ');

  return (
    <LogbookStepper
      s={s}
      loading={loading}
      title={t('screenTitle')}
      subtitle={t('screenSub')}
      step={step}
      steps={STEPS}
      onStepChange={onStepChange}
      onExit={() => router.push('/logbooks')}
      locked={locked}
      logType={LOG_TYPE}
      logId={existingLogId}
      /* THE LOCK BAR NEEDS BOTH HANDLES. A log filed with no signal has no
         server id, so its "on this device only" record is keyed by the DRAFT
         KEY; without this prop the bar could never look it up and the banner
         would be unreachable on the one case that most needs it. It is also
         what lets an adopted amendment discard the frozen local draft. */
      draftKey={_key}
      onFinalized={() => setLocked(true)}
      onAmended={fetchData}
      /* A WARNING IS NOT A GATE. The device having stopped storing the draft
         must not stop him filing a log the statute requires before he leaves —
         it tells him once, at the last moment it can still matter. */
      submitWarning={autosaveFailed ? tFinalize('autosaveFailedWarning') : ''}
      autosaveNote={t('savedAutomatically')}
      a11yProgressLabel={`Step ${step} of ${TOTAL_STEPS}`}
      nextLabel="Next"
      submitLabel="Sign & complete"
      submitting={signing}
      /* THE STATUTE SAYS "PRIOR TO DEPARTING", so an unsigned or unanswered
         submit must be UNREACHABLE rather than warned about. The server's
         SUBMIT_UNATTESTED_ITEMS is the authority; this stops him arriving at
         a refusal he cannot read. */
      submitDisabled={!isAffirmedSignature(cpSignature)
        || presenceMissing.length > 0
        || unanswered.length > 0}
      draftConflict={draftConflict}
      // HE TOOK THE OVERRIDE. Stored ON the verdict rather than beside it, so
      // the load that clears the verdict clears the acknowledgement with it and
      // a NEW server change is never covered by an answer he gave to an old one.
      onConflictAcknowledge={() => setDraftConflict(
        (c) => (c ? { ...c, acknowledged: true } : c),
      )}
      /* THE PRESENCE GAP IS NAMED FIRST, AND THE ORDER IS THE WHOLE COPY
         DECISION. The signature and the unanswered items are both on THIS
         step — he can see and fix either without leaving. ARRIVED and
         DEPARTED are back on step 1, so a hint that mentions them last costs
         him a second trip through the stepper. It names the fields by the
         labels printed above them and the step they are on, because "presence
         is incomplete" is not something he can go and do anything about. */
      submitHint={
        presenceMissing.length > 0
          ? t('presenceHint').replace('{fields}', presenceMissing.join(' and '))
          : (!isAffirmedSignature(cpSignature)
            ? t('signatureHint')
            : (unanswered.length > 0
              ? t('unansweredHint').replace('{items}', unansweredLabels)
              : ''))
      }
      onSubmit={handleSubmit}
    />
  );
}
