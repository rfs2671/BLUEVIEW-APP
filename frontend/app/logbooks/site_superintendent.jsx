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
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { View, Text, TextInput, Pressable, ScrollView } from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Plus, Trash2, Check, X } from 'lucide-react-native';

import LogbookStepper from '../../src/components/logbookStepper/LogbookStepper';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { Card, StepHeaderBase } from '../../src/components/logbookStepper/primitives';
import SignaturePad from '../../src/components/SignaturePad';
import { outdoor, spacing } from '../../src/styles/theme';
import { useToast } from '../../src/components/Toast';
import { useT } from '../../src/i18n';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { logbooksAPI, dobAPI } from '../../src/utils/api';
// TWO MODULES, AND THEY ARE NOT INTERCHANGEABLE. `signatureAudit` is the
// LEDGER (recordSignatureEvent, device fingerprint, integrity); the predicate
// that says whether a signature was affirmed lives in `signatureAffirmed`.
// Importing the predicate from the ledger binds it to `undefined` rather than
// failing — every static gate stayed green and the screen crashed to the error
// boundary on mount. The mount smoke is what caught it.
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import { isAffirmedSignature } from '../../src/utils/signatureAffirmed';
import { useAuth } from '../../src/context/AuthContext';
import {
  csLogItems, csItemState, csUnanswered, CS_LOG_ITEMS,
} from '../../src/utils/superintendentLogModel';
import {
  emptyFinding, findingIsEmpty, findingGaps,
  deriveConditionAndOrderBlocks,
} from '../../src/utils/csFindings';

const LOG_TYPE = 'site_superintendent_log';
const TOTAL_STEPS = 5;

const todayISO = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' })
  .format(new Date());

/** HH:MM in the site's timezone, for a prefill he confirms or changes. */
const nowHHMM = () => new Intl.DateTimeFormat('en-GB', {
  timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(new Date());

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
  const { user } = useAuth();
  const { projectId, date } = useLocalSearchParams();
  const logDate = String(date || todayISO());

  const { cpName, cpSignature, setCpSignature, setCpName, profileLoaded } = useCpProfile();

  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(true);
  const [locked, setLocked] = useState(false);
  const [signing, setSigning] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);

  // ── item state ──────────────────────────────────────────────────────────
  // ARRIVAL IS PREFILLED AND IS HIS TO CHANGE. He may open the app in his
  // truck, so the first-open time is a SUGGESTION, never an observation the
  // app asserts on a licensed signature. The screen says so in words
  // (presenceNote) as well as by leaving the field editable.
  const [arrivedAt, setArrivedAt] = useState('');
  const [departedAt, setDepartedAt] = useState('');
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
    setArrivedAt((v) => v || nowHHMM());
  }, []);

  useEffect(() => { if (cpName && !printedName) setPrintedName(cpName); }, [cpName]);

  // ── load ────────────────────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    (async () => {
      if (!projectId) { setLoading(false); return; }
      try {
        const arr = await logbooksAPI.getByProject(projectId, LOG_TYPE, logDate);
        const list = Array.isArray(arr) ? arr : (arr?.items || []);
        // Prefer the EDITABLE document — an amendment child over its locked
        // parent — the same rule every other editor's load applies.
        const existing = list.find((l) => l.is_locked !== true) || list[0] || null;
        if (!alive) return;
        if (existing) {
          setExistingLogId(existing.id || existing._id);
          setLocked(existing.is_locked === true);
          hydrate(existing.data || {});
          if (existing.cp_signature) setCpSignature(existing.cp_signature);
          if (existing.cp_name) setCpName(existing.cp_name);
        }
      } catch (_e) {
        // A failed read is not an empty log. Leave the form as it is and let
        // him work offline; the draft is local-first like every other editor.
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [projectId, logDate]);

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
    setArrivedAt(g('presence').arrived_at || '');
    setDepartedAt(g('presence').departed_at || '');
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
        corrected: typeof c.corrected === 'boolean' ? c.corrected : null,
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

  // ── the document this screen would file ─────────────────────────────────
  const buildData = useCallback((departure) => {
    const both = deriveConditionAndOrderBlocks(findings, noneBoth);
    const dobChosen = dobEntries.filter((e) => e.included && e.text.trim());
    const incChosen = incidentEntries.filter((e) => e.included && e.text.trim());
    return {
      presence: {
        printed_name: printedName.trim(),
        arrived_at: arrivedAt.trim(),
        departed_at: (departure || departedAt).trim(),
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
    printedName, arrivedAt, departedAt, progress, activities, locations,
    inspectedOn, inspectionLocation, inspectionResult, competentPersonName]);

  // THE SUBMIT GATE MIRRORS THE SERVER, WHICH REMAINS THE AUTHORITY.
  // create_logbook raises SUBMIT_UNATTESTED_ITEMS; this only decides whether
  // the button is reachable and names the items so he is not guessing.
  const unanswered = csUnanswered(buildData(departedAt), logDate);

  const handleSubmit = async () => {
    if (signing || locked) return;
    // DEPARTURE IS PREFILLED AT SIGN AND IS STILL HIS. Same rule as arrival —
    // the app suggests the moment he signed; if he is filing from the truck
    // ten minutes later, the field is his to correct before he taps.
    const departure = departedAt.trim() || nowHHMM();
    if (!departedAt.trim()) setDepartedAt(departure);
    if (!isAffirmedSignature(cpSignature)) return;
    if (unanswered.length > 0) return;

    setSigning(true);
    try {
      const payload = {
        project_id: projectId,
        log_type: LOG_TYPE,
        date: logDate,
        data: buildData(departure),
        cp_signature: cpSignature,
        cp_name: printedName.trim() || cpName,
        status: 'submitted',
      };
      const saved = existingLogId
        ? await logbooksAPI.update(existingLogId, payload)
        : await logbooksAPI.create(payload);
      const savedId = saved?.id || saved?._id || existingLogId;
      setExistingLogId(savedId);

      // ── THE SIGNATURE EVENT ────────────────────────────────────────────
      // `superintendent_sign`, NEVER `cp_sign`. See the note at the top of
      // this file: deriveActingCapacity reads the event type first, and the
      // wrong one records this log as signed by a Competent Person.
      if (savedId) {
        // Non-blocking, exactly as every other editor treats it: the log is
        // filed and must not be refused over an audit write.
        recordSignatureEvent({
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
        }).catch((e) => console.warn('Signature audit failed (non-blocking):', e?.message));
      }

      // ── THE FREEZE, AND WHY IT IS AN EXPLICIT CALL ─────────────────────
      // 3301.13.13: "complete such log prior to departing the job site." The
      // signature IS the freeze, as with the nine immediate logs.
      //
      // BUT THE SERVER DOES NOT DO IT ON SUBMIT FOR THIS TYPE. create/update
      // set is_locked from `is_immediate_preshift(log_type)`, which is
      // `timing_class == "immediate"`. This log is class `visit` — a class
      // that today means exactly one thing, "excluded from the end-of-day
      // sweep", and is named by no freeze predicate on either side. So a
      // submitted superintendent log comes back status=submitted,
      // is_locked=False: signed and still editable.
      //
      // /finalize locks any log explicitly and requires both `data` and
      // `cp_signature`, which the payload above carries. Calling it is what
      // makes the freeze real rather than a client-side claim — without it
      // `setLocked(true)` below would be a lie the next load corrects, since
      // the load prefers `is_locked !== true`.
      //
      // THIS IS A STOPGAP AND IT IS THE CLIENT'S. The freeze belongs in the
      // server's lock predicate so it holds for every caller; that is a
      // backend change and it is not in this PR.
      if (savedId) await logbooksAPI.finalize(savedId);

      setLocked(true);
      toast.success(t('filed'));
      router.push('/logbooks');
    } catch (e) {
      toast.error(t('couldNotFile'),
        e?.response?.data?.detail?.code || e?.message || '');
    } finally {
      setSigning(false);
    }
  };

  // ── steps ───────────────────────────────────────────────────────────────
  const Field = ({ label, value, onChangeText, placeholder, multiline }) => (
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

  const Tri = ({ label, note, value, onChange }) => (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={s.reviewLabel}>{label}</Text>
      {/* THREE STATES, NOT A CHECKBOX. An unticked box is ambiguous between
          "no" and "not looked at", and item_state draws exactly that line:
          ATTESTED_NONE is a person's statement that there was nothing to
          report; NOT_REACHED is the absence of any statement. */}
      <View style={{ flexDirection: 'row', gap: 8 }}>
        {[['yes', true], ['no', false]].map(([lbl, v]) => (
          <Pressable
            key={lbl}
            disabled={locked}
            onPress={() => onChange(value === v ? null : v)}
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

  const stepPresence = () => (
    <Card s={s}>
      <StepHeaderBase s={s} title={t('presenceHeading')} />
      <Text style={s.noteText}>{t('presenceNote')}</Text>
      <Field label={t('printedName')} value={printedName} onChangeText={setPrintedName} />
      <Field label={t('arrivedAt')} value={arrivedAt} onChangeText={setArrivedAt} placeholder="HH:MM" />
      <Field label={t('departedAt')} value={departedAt} onChangeText={setDepartedAt} placeholder="HH:MM" />
    </Card>
  );

  const stepWork = () => (
    <>
      <Card s={s}>
        <Field label={t('progressLabel')} value={progress} onChangeText={setProgress}
          placeholder={t('progressPlaceholder')} multiline />
        <Field label={t('activitiesLabel')} value={activities} onChangeText={setActivities}
          placeholder={t('activitiesPlaceholder')} multiline />
        <Field label={t('locationsLabel')} value={locations} onChangeText={setLocations}
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
        <Field label={t('inspectedOn')} value={inspectedOn} onChangeText={setInspectedOn} />
        <Field label={t('inspectionLocation')} value={inspectionLocation}
          onChangeText={setInspectionLocation} />
        <Field label={t('inspectionResult')} value={inspectionResult}
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
          <Field label={t('findingLocation')} value={f.location}
            onChangeText={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, location: v } : x)))} />
          <Field label={t('findingObservedAt')} value={f.observed_at} placeholder="HH:MM"
            onChangeText={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, observed_at: v } : x)))} />
          <Field label={t('findingCondition')} multiline value={f.condition}
            onChangeText={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, condition: v } : x)))} />
          <Field label={t('findingOrder')} multiline value={f.order_given}
            onChangeText={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, order_given: v } : x)))} />
          <Field label={t('findingOrderTo')} value={f.order_to}
            onChangeText={(v) => setFindings((p) => p.map((x, j) => (j === i ? { ...x, order_to: v } : x)))} />
          <Tri label={t('findingCorrected')} value={f.corrected}
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

  const EntryList = ({ heading, note, entries, setEntries, none, setNone, noneLabel }) => (
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

  const stepDob = () => (
    <>
      <EntryList heading={t('dobHeading')} note={t('dobNote')}
        entries={dobEntries} setEntries={setDobEntries}
        none={dobNone} setNone={setDobNone} noneLabel={t('dobNoneToReport')} />
      <EntryList heading={t('incidentsHeading')} note={t('incidentsNote')}
        entries={incidentEntries} setEntries={setIncidentEntries}
        none={incidentsNone} setNone={setIncidentsNone}
        noneLabel={t('incidentsNoneToReport')} />
    </>
  );

  const stepSign = () => {
    const data = buildData(departedAt);
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
          <Field label={t('competentPersonName')} value={competentPersonName}
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
          <SignaturePad
            pinned
            value={cpSignature}
            onChange={setCpSignature}
            name={printedName || cpName}
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

  const unansweredLabels = unanswered
    .map((k) => (CS_LOG_ITEMS.find((i) => i.key === k) || {}).label || k)
    .join(', ');

  return (
    <LogbookStepper
      s={s}
      loading={loading}
      title={t('screenTitle')}
      subtitle={t('screenSub')}
      step={step}
      steps={STEPS}
      onStepChange={setStep}
      onExit={() => router.push('/logbooks')}
      locked={locked}
      logType={LOG_TYPE}
      logId={existingLogId}
      a11yProgressLabel={`Step ${step} of ${TOTAL_STEPS}`}
      nextLabel="Next"
      submitLabel="Sign & complete"
      submitting={signing}
      /* THE STATUTE SAYS "PRIOR TO DEPARTING", so an unsigned or unanswered
         submit must be UNREACHABLE rather than warned about. The server's
         SUBMIT_UNATTESTED_ITEMS is the authority; this stops him arriving at
         a refusal he cannot read. */
      submitDisabled={!isAffirmedSignature(cpSignature) || unanswered.length > 0}
      submitHint={
        !isAffirmedSignature(cpSignature)
          ? t('signatureHint')
          : (unanswered.length > 0
            ? t('unansweredHint').replace('{items}', unansweredLabels)
            : '')
      }
      onSubmit={handleSubmit}
    />
  );
}
