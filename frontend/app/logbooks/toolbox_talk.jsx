import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  View, Text, StyleSheet, Pressable, TextInput,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Check, Plus, Trash2 } from 'lucide-react-native';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import {
  draftKey, readDraft, writeDraft, setDraftBackendId,
  markPending, clearPending, markFinalized,
} from '../../src/utils/logbookDrafts';
import { freezeIfImmediate } from '../../src/utils/logbookTiming';
// finalizeErrorCode is the ONE place a FINALIZE_* code is pulled out of an
// axios error (and the one place that guarantees the server's English `detail`
// never reaches a screen); clearFinalizeError removes the drain's persistent
// "NOT LOCKED ON THE SERVER" banner once this screen files for real;
// recordFinalizeError RAISES that same banner, so a refusal taken here in the
// foreground leaves the identical durable trace a background one does.
import { finalizeErrorCode, clearFinalizeError, recordFinalizeError } from '../../src/utils/draftSync';
import { isOfflineError } from '../../src/utils/offlineState';
import LogbookStepper from '../../src/components/logbookStepper/LogbookStepper';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { Card, ChipBase, StepHeaderBase } from '../../src/components/logbookStepper/primitives';
import TimeField from '../../src/components/logbookStepper/TimeField';
import {
  TOPICS, TOPIC_GROUPS, EMPTY_ATTENDEE, formatClock, buildAttendees,
  ATTENDEE_SOURCES, missingStepOneFields, weeklyGapWorkers, weeklyGapAttendee,
  reconcileAttendees, topicCount, namedAttendees,
  incompleteSteps as computeIncomplete, draftBody,
} from '../../src/utils/toolboxTalkModel';
import { useT } from '../../src/i18n';
import { spacing, borderRadius, outdoor, touchTarget } from '../../src/styles/theme';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';

/**
 * TOOL BOX TALK — NYC DOB §3301.12.3 / OSHA 29 CFR 1926.21 — on the shared
 * stepper.
 *
 * FOUR STEPS, as approved: the talk, the topics, who attended, review and sign.
 * The chrome is LogbookStepper's — header, pips, scroll, lock bar, autosave
 * note and footer — so a port cannot quietly lose the 56pt target or the
 * single primary action.
 *
 * WHAT CARRIED FORWARD, unchanged:
 *   draft lifecycle          readDraft / writeDraft / setDraftBackendId /
 *                            markPending / clearPending / markFinalized
 *   signature client guard   toolbox_talk is IMMEDIATE — the server locks on
 *                            `status: submitted` alone — so an unsigned submit
 *                            must be UNREACHABLE, not merely warned about
 *   gateCopy                 the server names the condition, the client owns
 *                            the wording; the server's English never renders
 *   recordFinalizeError      a foreground refusal leaves the same durable
 *                            banner a background one does
 *   THE #130 RECONCILE       both load paths re-check the stored roster against
 *                            today's check-ins. This is the piece most at risk
 *                            in a rewrite: without it a man who never checked
 *                            in stays on a signed sheet. It is asserted in
 *                            rosterReconcile.test.cjs and toolboxTalk.test.cjs.
 *
 * NOT CARRIED, because this form has no camera: persistPhoto and
 * compressUnderCap. There is no photo on a toolbox talk.
 *
 * THE PAYLOAD IS UNCHANGED — the same seven keys both PDF renderers and the
 * kiosk read. See toolboxTalkModel.
 *
 * A WORKER DOES NOT SIGN A TOOLBOX TALK. The CP's signature over the roster is
 * the legal attestation; `signed` is his presence tick and `gate_confirmed` is
 * the worker's voluntary tap. Neither is a signature and the copy says so.
 */
const LOG_TYPE = 'toolbox_talk';
const TOTAL_STEPS = 4;

export default function ToolboxTalkLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const t = useT('toolboxTalk');
  const tFinalize = useT('finalize');
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave } = useCpProfile();

  const s = useMemo(() => buildStyles(), []);

  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [step, setStep] = useState(1);
  const [locked, setLocked] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);

  const [location, setLocation] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [typeOfWork, setTypeOfWork] = useState('');
  const [meetingTime, setMeetingTime] = useState(
    () => new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
  );
  const [performedBy, setPerformedBy] = useState('');
  const [checkedTopics, setCheckedTopics] = useState({});
  const [attendees, setAttendees] = useState([]);
  // Men who worked THIS WEEK and have not had a talk. Ruling C: today's
  // check-ins stay the default roster; these are offered beneath it.
  const [weeklyMissing, setWeeklyMissing] = useState([]);

  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date }),
    [projectId, date],
  );

  // The form as of RIGHT NOW, for the debounced autosave and the save path.
  // State read inside a timer is the value captured when the timer was set.
  const bodyRef = useRef({});
  useEffect(() => {
    bodyRef.current = {
      location, companyName, typeOfWork, meetingTime, performedBy,
      checkedTopics, attendees,
    };
  }, [location, companyName, typeOfWork, meetingTime, performedBy, checkedTopics, attendees]);

  /**
   * The server names the condition, the client owns the wording — the same
   * rule LogbookLockBar's gateCopy follows, over the same `finalize`
   * namespace. `translate` returns the KEY on a miss, which is how an unmapped
   * code is detected; the server's English `detail` is never rendered.
   */
  const gateCopy = useCallback((code) => {
    if (!code) return tFinalize('genericError');
    const key = `code_${code}`;
    const copy = tFinalize(key);
    return copy && copy !== key ? copy : tFinalize('genericError');
  }, [tFinalize]);

  // ── Draft ─────────────────────────────────────────────────────────────
  // `status` is deliberately omitted so an autosave never downgrades a filed
  // log back to draft.
  useEffect(() => {
    if (loading || locked) return undefined;
    const h = setTimeout(() => {
      writeDraft(_key, {
        data: draftBody(bodyRef.current),
        cp_signature: cpSignature,
        cp_name: cpName,
      }).catch(() => {});
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, location, companyName, typeOfWork, meetingTime,
    performedBy, checkedTopics, attendees, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      await writeDraft(_key, {
        data: draftBody(bodyRef.current),
        cp_signature: cpSignature,
        cp_name: cpName,
      });
    } catch (_e) { /* best-effort; the next change retries */ }
  }, [locked, _key, cpSignature, cpName]);

  const hydrate = (d) => {
    if (d.location) setLocation(d.location);
    if (d.company_name) setCompanyName(d.company_name);
    if (d.type_of_work) setTypeOfWork(d.type_of_work);
    if (d.meeting_time) setMeetingTime(d.meeting_time);
    if (d.performed_by) setPerformedBy(d.performed_by);
    if (d.checked_topics) setCheckedTopics(d.checked_topics);
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    // THE LOCK IS RE-DERIVED ON EVERY LOAD — device round 5. `locked` could
    // only ever be set TRUE: no path set it back, so once a log was filed the
    // screen stayed read-only for the life of the mount. After an amendment
    // that is exactly wrong — #143 makes the editable child reachable, and
    // this is what lets the screen show it without the CP backing out and
    // re-entering. Everything below decides locked-ness from what it loads.
    setLocked(false);
    try {
      // LOCAL-FIRST. A local draft wins over the server copy, so an offline CP
      // reopens to exactly what he filled.
      const draft = await readDraft(_key);
      if (draft?.data && Object.keys(draft.data).length) {
        // AN AMENDMENT MUST REACH THIS SCREEN — device round 5, finding 19.
        // Parent and amendment share ONE draft key (project, logType, date), so
        // a finalized local draft used to lock the editor and return before the
        // server was ever asked: the child sat there unlocked and unreachable
        // while the logbook list showed it as a Draft. amendmentAdopt discards
        // the frozen parent ONLY on server confirmation; offline it is a no-op
        // and the log stays locked, which is honest.
        const _amended = draft.finalized && await adoptAmendment({
          key: _key, projectId, logType: LOG_TYPE, date,
        });
        if (_amended) {
          // The frozen parent is discarded; fall through to the server
          // path, which already prefers the unlocked document.
        } else {
        if (draft.finalized) { setLocked(true); markFinalized(_key); }
        setExistingLogId(draft.backend_id || null);
        hydrate(draft.data);
        // RE-CHECK AGAINST TODAY, even on the draft path (#130). This early
        // return used to skip /checkins-today entirely, so a stored roster
        // persisted unchecked — six men on a sheet on a day five checked in,
        // the sixth having been refused at the gate. Offline the fetch fails,
        // `fresh` is null, and reconcileAttendees keeps everything.
        // AN EMPTY STORED ROSTER MUST STILL REBUILD.
        //
        // The `length > 0` guard came in with #130 and was the bug: it only
        // reconciled when there was something stored to reconcile against, and
        // an empty roster is precisely the case that needs building. The
        // autosave writes `attendees: []` 800ms after load, so merely OPENING
        // this form before anyone had tapped in wrote a permanent empty roster
        // for that project and date — men arrived, the CP reopened, and the
        // list could never rebuild because the branch that would rebuild it
        // never ran. Production: 13 checked in, step 3 listed nobody, and four
        // men were added by hand to work around it.
        //
        // The fetch is unconditional now; what differs is what to do with it.
        const [fresh, notif] = await Promise.all([
          logbooksAPI.getCheckinsForDate(projectId, date).catch(() => null),
          logbooksAPI.getNotifications(projectId).catch(() => null),
        ]);
        setWeeklyMissing(notif?.missing_toolbox_talk || []);
        const storedRoster = Array.isArray(draft.data.attendees)
          ? draft.data.attendees : [];
        setAttendees(
          storedRoster.length > 0
            // Something stored: RECONCILE, so a man refused at the gate does
            // not stay on the sheet and a man who arrived later is added.
            ? reconcileAttendees(storedRoster, fresh)
            // Nothing stored: BUILD. Offline (`fresh` null) there is nothing
            // to build from and an empty list is the honest answer — it is
            // also what was already on screen.
            : buildAttendees(Array.isArray(fresh) ? fresh : []),
        );
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        setLoading(false);
        return;
        }
      }

      const [projectData, checkins, existingLogs, notif] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, LOG_TYPE, date).catch(() => []),
        logbooksAPI.getNotifications(projectId).catch(() => null),
      ]);
      const checkinList = Array.isArray(checkins) ? checkins : [];
      setWeeklyMissing(notif?.missing_toolbox_talk || []);

      // Prefer the EDITABLE (non-locked) doc — an amendment child — over a
      // locked original that shares (project, type, date).
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find((l) => !l.is_locked) || arr[0] || null;

      if (existing) {
        if (existing.is_locked) { setLocked(true); markFinalized(_key); }
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        hydrate(d);
        setAttendees(
          Array.isArray(d.attendees) && d.attendees.length > 0
            ? reconcileAttendees(d.attendees, checkinList)   // #130
            : buildAttendees(checkinList),
        );
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      } else {
        setAttendees(buildAttendees(checkinList));
      }

      // Company falls back through the same chain it always did.
      if (!existing?.data?.company_name) {
        if (projectData?.company) setCompanyName(projectData.company);
        else if (user?.company_name) setCompanyName(user.company_name);
        else if (user?.name) setCompanyName(user.name.split(' ')[0]);
      }

      // LOCATION AND PERFORMED BY AUTOFILL — device round 4, finding 7. Both
      // are known and nobody should be typing either: the location is the
      // project the CP is standing on, and the man performing the talk is the
      // man holding the phone. Same fallback chain shape the company already
      // used, and the same rule — a value already on the record WINS, so this
      // can never overwrite what a CP typed or what was filed.
      if (!existing?.data?.location) {
        const _loc = projectData?.address || projectData?.location || projectData?.name;
        if (_loc) setLocation(_loc);
      }
      if (!existing?.data?.performed_by) {
        // `user`, not cpName: cpName arrives asynchronously from useCpProfile
        // and reading it here would either capture '' in a stale closure or
        // force fetchData to re-run when the profile lands, re-fetching the
        // whole screen. The logged-in user is the same man and is already a
        // dependency.
        const _by = user?.full_name || user?.name;
        if (_by) setPerformedBy(_by);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [_key, projectId, date, user, setCpName, setCpSignature]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── Edits ─────────────────────────────────────────────────────────────
  const toggleTopic = (key) => setCheckedTopics((p) => ({ ...p, [key]: !p[key] }));
  const updateAttendee = (i, field, value) => setAttendees(
    (p) => p.map((a, n) => (n === i ? { ...a, [field]: value } : a)),
  );
  const addAttendee = () => setAttendees((p) => [...p, EMPTY_ATTENDEE()]);
  const removeAttendee = (i) => setAttendees((p) => p.filter((_, n) => n !== i));

  // ── Save ──────────────────────────────────────────────────────────────
  const persistAndPush = async (submitStatus) => {
    const data = draftBody(bodyRef.current);
    await writeDraft(_key, {
      data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
    });

    let created = null;
    let savedId = existingLogId;
    try {
      if (existingLogId) {
        await logbooksAPI.update(existingLogId, {
          data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
        });
      } else {
        created = await logbooksAPI.create({
          project_id: projectId, log_type: LOG_TYPE, date, data,
          cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
        });
        savedId = created.id || created._id;
        setExistingLogId(savedId);
      }
      if (savedId) await setDraftBackendId(_key, savedId);
      await clearPending(_key);
      if (savedId) await clearFinalizeError(savedId);
    } catch (pushErr) {
      // REFUSAL IS NOT OFFLINE. toolbox_talk is an IMMEDIATE type, so a
      // submitted push IS the finalize — a 4xx is the server judging the
      // record, not failing to reach it. Freezing on a judgement would tell
      // the CP it was filed, make the draft immutable so he could not fix what
      // was refused, and leave nothing pending for the drain to retry.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      if (refused && submitStatus === 'submitted') {
        const code = finalizeErrorCode(pushErr);
        console.warn('Toolbox talk REFUSED by the server:', status, code);
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        console.warn('Toolbox talk push FAILED server-side:', status || pushErr?.message);
        await markPending(_key);
        toast.error(tFinalize('errorTitle'), gateCopy(null));
        return undefined;
      }
      await markPending(_key);
      console.warn('Toolbox talk push deferred (will sync on reconnect):', pushErr?.message);
    }

    // Guarded: a CP-PROFILE save failure must never report a failure on a log
    // that was already saved (and, for an immediate type, already FROZEN).
    await autoSave(cpName, cpSignature).catch(() => {});

    if (submitStatus === 'submitted' && cpSignature) {
      const docId = existingLogId || created?.id || created?._id;
      if (docId) {
        recordSignatureEvent({
          documentType: 'logbook', documentId: docId, eventType: 'cp_sign',
          signerName: cpName, signerRole: user?.role || 'cp',
          signatureData: cpSignature,
          contentSnapshot: {
            log_type: LOG_TYPE, date, project_id: projectId, data, status: submitStatus,
          },
          user,
        }).catch((e) => console.warn('Signature audit failed (non-blocking):', e?.message));
      }
    }
    return savedId || null;
  };

  /**
   * toolbox_talk is an IMMEDIATE log: THE SIGNATURE IS THE FREEZE. There is no
   * separate Finalize step and the record is never reopened — a later talk that
   * day is a NEW log, and corrections go through Amend.
   */
  const handleSubmitAndSign = async () => {
    if (signing) return;
    // SIGNATURE CLIENT GUARD, backing up the disabled button below.
    if (!cpSignature) {
      setStep(TOTAL_STEPS);
      toast.warning(t('signatureRequiredTitle'), t('signatureRequiredBody'));
      return;
    }
    setSigning(true);
    try {
      const savedId = await persistAndPush('submitted');
      // `undefined` = refused or failed, already reported. Nothing may be
      // frozen or announced on a record the server would not take. `null` is
      // the offline path and DOES freeze — a talk given at the muster point
      // with no signal must still hold.
      if (savedId === undefined) return;
      await freezeIfImmediate(_key, LOG_TYPE);
      setLocked(true);
      toast.success(
        t('submittedTitle'),
        savedId ? t('submittedBody') : t('submittedOfflineBody'),
      );
      router.back();
    } catch (e) {
      console.error(e);
      toast.error(t('saveFailedTitle'), t('saveFailedTitle'));
    } finally {
      setSigning(false);
    }
  };

  const onStepChange = async (next) => {
    await flushDraft();
    setStep(Math.max(1, Math.min(TOTAL_STEPS, next)));
  };

  const Chip = useCallback((p) => <ChipBase s={s} {...p} />, [s]);
  const StepHeader = useCallback((p) => (
    <StepHeaderBase
      s={s}
      count={t('stepOf').replace('{n}', String(step)).replace('{m}', String(TOTAL_STEPS))}
      {...p}
    />
  ), [s, step, t]);

  const incomplete = computeIncomplete({
    location, companyName, typeOfWork, meetingTime, performedBy,
    checkedTopics, attendees, cpSignature,
  }).filter((n) => n !== step);
  // Which of step 1's five are still empty. Drives both the per-control marking
  // and the Next gate, so the button and the fields can never disagree.
  const missingStep1 = missingStepOneFields({
    location, companyName, typeOfWork, meetingTime, performedBy,
  });
  const nTopics = topicCount(checkedTopics);
  const named = namedAttendees(attendees);
  // RULING C. Today's check-ins are the default roster; these are the men who
  // worked this WEEK without a talk and are not already on the sheet. A toolbox
  // talk is a weekly obligation built from a daily roster, so without this the
  // CP was never offered the men who worked Monday-Wednesday and not today —
  // production had 26 on the week against 13 on the day.
  const weeklyGap = useMemo(
    () => weeklyGapWorkers(weeklyMissing, attendees),
    [weeklyMissing, attendees],
  );

  // Adding him is the CP ASSERTING he attended — `added_from` records that, and
  // `signed` starts false so adding is still not the same as marking present.
  const addFromWeeklyGap = (w) => setAttendees((prev) => [...prev, weeklyGapAttendee(w)]);
  const addAllFromWeeklyGap = () => setAttendees(
    (prev) => [...prev, ...weeklyGap.map(weeklyGapAttendee)],
  );

  const plural = (n, base) => t(`${base}_${n === 1 ? 'one' : 'other'}`).replace('{n}', String(n));

  // `field` names the STEP 1 key this row edits; passing it turns on the
  // required marking. A row with no field name is not a gated control.
  const textRow = (labelKey, value, onChangeText, phKey = 'phField', field = null) => {
    const missing = !!field && missingStep1.includes(field);
    return (
      <View style={s.fieldBlock}>
        <Text style={s.reviewLabel}>{t(labelKey)}</Text>
        <TextInput
          style={[s.input, missing && s.inputRequired]}
          value={value}
          onChangeText={onChangeText}
          placeholder={t(phKey)}
          placeholderTextColor={outdoor.textDim}
        />
        {missing && <Text style={s.requiredText}>{t('requiredField')}</Text>}
      </View>
    );
  };

  // ── STEP 1 — the talk ─────────────────────────────────────────────────
  const renderStep1 = () => (
    <View>
      <StepHeader title={t('step1Title')} />
      <Card s={s}>
        {textRow('fLocation', location, setLocation, 'phField', 'location')}
        {textRow('fCompany', companyName, setCompanyName, 'phField', 'companyName')}
        {textRow('fTypeOfWork', typeOfWork, setTypeOfWork, 'phField', 'typeOfWork')}
        <TimeField
          s={s}
          label={t('fMeetingTime')}
          placeholder={t('phTime')}
          value={meetingTime}
          clearLabel={t('dateClear')}
          doneLabel={t('dateDone')}
          onChange={setMeetingTime}
          required={missingStep1.includes('meetingTime')}
          requiredLabel={t('requiredField')}
        />
        {textRow('fPerformedBy', performedBy, setPerformedBy, 'phField', 'performedBy')}
      </Card>
    </View>
  );

  // ── STEP 2 — the topics ───────────────────────────────────────────────
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />
      <Text style={s.noteText}>{t('topicsHint')}</Text>
      <Text style={s.noteText}>{t('topicsCount').replace('{n}', String(nTopics))}</Text>
      {TOPIC_GROUPS.map((group) => (
        <Card s={s} key={group}>
          <Text style={s.question}>{group}</Text>
          <View style={s.chipWrap}>
            {TOPICS[group].map((topic) => (
              <Chip
                key={topic.key}
                label={topic.label}
                selected={checkedTopics[topic.key] === true}
                onPress={() => toggleTopic(topic.key)}
              />
            ))}
          </View>
        </Card>
      ))}
    </View>
  );

  // ── STEP 3 — who attended ─────────────────────────────────────────────
  const renderStep3 = () => (
    <View>
      <StepHeader title={t('step3Title')} />
      <Text style={s.noteText}>{t('rosterHint')}</Text>
      {attendees.length === 0 && <Text style={s.emptyText}>{t('noAttendees')}</Text>}

      {attendees.map((a, i) => (
        <Card s={s} key={`${a.worker_id || 'row'}-${i}`}>
          <View style={s.rowHead}>
            <Text style={s.reviewLabel}>
              {t('attendeeOf').replace('{n}', String(i + 1)).replace('{m}', String(attendees.length))}
            </Text>
            <Pressable
              style={s.rowRemove}
              accessibilityRole="button"
              accessibilityLabel={t('removeAttendee')}
              onPress={() => removeAttendee(i)}
            >
              <Trash2 size={20} strokeWidth={2} color={outdoor.danger} />
            </Pressable>
          </View>

          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('colName')}</Text>
            <TextInput
              style={s.input}
              value={a.name}
              onChangeText={(v) => updateAttendee(i, 'name', v)}
              placeholder={t('phName')}
              placeholderTextColor={outdoor.textDim}
            />
          </View>
          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('colTitle')}</Text>
            <TextInput
              style={s.input}
              value={a.title}
              onChangeText={(v) => updateAttendee(i, 'title', v)}
              placeholder={t('phTitle')}
              placeholderTextColor={outdoor.textDim}
            />
          </View>
          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('colCompany')}</Text>
            <TextInput
              style={s.input}
              value={a.company}
              onChangeText={(v) => updateAttendee(i, 'company', v)}
              placeholder={t('phCompany')}
              placeholderTextColor={outdoor.textDim}
            />
          </View>

          {!!formatClock(a.time) && (
            <Text style={s.noteText}>
              {`${t('colTime')}: ${formatClock(a.time)}`}
            </Text>
          )}
          {a.gate_confirmed && (
            <Text style={s.noteText}>{t('gateConfirmed')}</Text>
          )}
          {/* WHOSE CLAIM THIS ROW IS. The gate saying a man was on site and the
              CP saying a man attended are different assertions, and a signed
              sheet that shows them identically is the stronger one borrowing
              the weaker one's authority. */}
          {a.added_from === ATTENDEE_SOURCES.WEEKLY_GAP && (
            <Text style={s.noteText}>{t('addedFromWeek')}</Text>
          )}

          {/* The CP's presence tick. NOT a signature — a worker is not required
              to sign a toolbox talk, and the copy must not imply he did. */}
          <Pressable
            style={[s.toggleRow, a.signed && s.toggleRowOn]}
            accessibilityRole="button"
            accessibilityState={{ selected: !!a.signed }}
            onPress={() => updateAttendee(i, 'signed', !a.signed)}
          >
            <View style={[s.toggleBox, a.signed && s.toggleBoxOn]}>
              {a.signed && <Check size={18} strokeWidth={3} color={outdoor.ok} />}
            </View>
            <Text style={s.toggleText}>{a.signed ? t('presentOn') : t('presentMark')}</Text>
          </Pressable>
        </Card>
      ))}

      {/* THE WEEKLY GAP. Named, not silently absent: the CP home screen counts
          these men against him and until now the form gave him no way to put
          any of them on a sheet. Each row is one tap; a man added this way is
          marked in the payload as the CP's assertion, never the gate's. */}
      {weeklyGap.length > 0 && (
        <Card s={s}>
          <Text style={s.question}>
            {plural(weeklyGap.length, 'weeklyGapCount')}
          </Text>
          <Text style={s.noteText}>{t('weeklyGapHint')}</Text>
          {weeklyGap.map((w, i) => (
            <Pressable
              key={`${w.worker_id || w.worker_name}-${i}`}
              style={s.secondaryBtn}
              accessibilityRole="button"
              accessibilityLabel={t('weeklyGapAdd').replace('{name}', w.worker_name || '')}
              onPress={() => addFromWeeklyGap(w)}
            >
              <Plus size={20} strokeWidth={2.5} color={outdoor.text} />
              <Text style={s.secondaryBtnText}>
                {w.company ? `${w.worker_name} — ${w.company}` : w.worker_name}
              </Text>
            </Pressable>
          ))}
          {weeklyGap.length > 1 && (
            <Pressable
              style={s.secondaryBtn}
              accessibilityRole="button"
              onPress={addAllFromWeeklyGap}
            >
              <Plus size={20} strokeWidth={2.5} color={outdoor.text} />
              <Text style={s.secondaryBtnText}>
                {t('weeklyGapAddAll').replace('{n}', String(weeklyGap.length))}
              </Text>
            </Pressable>
          )}
        </Card>
      )}

      <Text style={s.noteText}>{t('gateNote')}</Text>
      <Pressable style={s.secondaryBtn} accessibilityRole="button" onPress={addAttendee}>
        <Plus size={22} strokeWidth={2.5} color={outdoor.text} />
        <Text style={s.secondaryBtnText}>{t('addAttendee')}</Text>
      </Pressable>
    </View>
  );

  // ── STEP 4 — review and sign ──────────────────────────────────────────
  const renderStep4 = () => (
    <View>
      <StepHeader title={t('step4Title')} />
      <Text style={s.noteText}>{t('reviewHeading')}</Text>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewTopics')}</Text>
        <Text style={s.reviewValue}>
          {nTopics > 0 ? t('topicsCount').replace('{n}', String(nTopics)) : t('reviewNothingYet')}
        </Text>
      </Card>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewAttendees')}</Text>
        <Text style={s.reviewValue}>
          {named.length > 0 ? plural(named.length, 'attendeesCount') : t('reviewNothingYet')}
        </Text>
      </Card>

      <Card s={s}>
        <Text style={s.reviewLabel}>
          {incomplete.length > 0 ? t('stepsIncomplete') : t('stepsAllComplete')}
        </Text>
        <Text style={s.noteText}>{t('signAttests')}</Text>
        <SignaturePad
          title="Competent Person Signature"
          signerName={cpName}
          onNameChange={setCpName}
          existingSignature={cpSignature}
          onSignatureCapture={setCpSignature}
        />
      </Card>
    </View>
  );

  const STEPS = [
    { render: renderStep1 },
    { render: renderStep2 },
    { render: renderStep3 },
    { render: renderStep4 },
  ];

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
      incompleteSteps={incomplete}
      a11yProgressLabel={t('stepOf')
        .replace('{n}', String(step)).replace('{m}', String(TOTAL_STEPS))}
      nextLabel={t('next')}
      /* STEP 1 IS THE ONE GATED STEP IN THE APP, and it is the IDENTITY-FIELD
         exception rather than a change of rule — see LogbookStepper's
         nextDisabled. All five identify the talk on a filed §3301.12.3 record,
         two autofill, and none can be "not known yet". Steps 2-4 page freely,
         because the topics covered, who attended and the signature are work,
         and a CP is never trapped on work. */
      nextDisabled={step === 1 && missingStep1.length > 0}
      nextHint={step === 1 && missingStep1.length > 0
        ? t('step1Required').replace('{n}', String(missingStep1.length)) : ''}
      submitLabel={t('submitAndSign')}
      submitting={signing}
      /* toolbox_talk is IMMEDIATE — the server locks on `submitted` alone — so
         an unsigned submit must be UNREACHABLE, not merely warned about. */
      submitDisabled={!isAffirmedSignature(cpSignature)}
      submitHint={affirmationHintKey(cpSignature, profileLoaded)
        ? tFinalize(affirmationHintKey(cpSignature, profileLoaded)) : ''}
      onSubmit={handleSubmitAndSign}
      logType={LOG_TYPE}
      logId={existingLogId}
      draftKey={_key}
      onFinalized={() => setLocked(true)}
      onAmended={fetchData}
      autosaveNote={t('savedAutomatically')}
    />
  );
}

function buildStyles() {
  return StyleSheet.create({
    ...buildStepperStyles(),
    rowHead: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      gap: spacing.sm,
    },
    rowRemove: {
      minWidth: touchTarget.min, minHeight: touchTarget.min,
      alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.full,
    },
    toggleBoxOn: { borderColor: outdoor.okBorder },
  });
}
