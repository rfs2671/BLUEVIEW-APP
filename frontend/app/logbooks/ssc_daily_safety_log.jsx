import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  View, Text, StyleSheet, Pressable, TextInput,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Check } from 'lucide-react-native';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI } from '../../src/utils/api';
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import {
  draftKey, readDraft, writeDraft, setDraftBackendId,
  markPending, clearPending, markFinalized,
} from '../../src/utils/logbookDrafts';
// finalizeErrorCode is the ONE place a FINALIZE_* code is pulled out of an
// axios error (and the one place that guarantees the server's English `detail`
// never reaches a screen); clearFinalizeError removes the drain's persistent
// "NOT LOCKED ON THE SERVER" banner once this screen files for real;
// recordFinalizeError RAISES that same banner, so a refusal taken here in the
// foreground leaves the identical durable trace a background one does.
import { finalizeErrorCode, clearFinalizeError, recordFinalizeError } from '../../src/utils/draftSync';
// The app-wide OFFLINE discriminator — "offline" has to mean what it means
// everywhere else: no response at all.
import { isOfflineError } from '../../src/utils/offlineState';
import LogbookStepper from '../../src/components/logbookStepper/LogbookStepper';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { Card, ChipBase, StepHeaderBase } from '../../src/components/logbookStepper/primitives';
import {
  WEATHER_OPTIONS, PREFILLED_FIELDS, COMPLIANCE_FLAGS, NARRATIVE_FIELDS,
  EMPTY_DETAILS, prefillFromProject, incidentDetailsApply, detailsFromData,
  incompleteSteps as computeIncomplete, draftBody,
} from '../../src/utils/sscDailySafetyLogModel';
import { useT } from '../../src/i18n';
import { spacing, outdoor } from '../../src/styles/theme';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';

/**
 * SSC / SSM DAILY SAFETY LOG — the daily narrative, on the shared stepper.
 *
 * FOUR STEPS, in the order the filed document prints them: the site, the five
 * compliance flags, the narrative, then review and sign. The chrome is
 * LogbookStepper's — nothing about the header, pips, lock bar or footer is
 * decided here.
 *
 * THIS IS AN END_OF_DAY LOG, NOT AN IMMEDIATE ONE. server.py:2933 puts it with
 * daily_jobsite: the narrative stays open and accumulating all day and freezes
 * ONCE, at the end-of-day Submit and Sign. So the closing action is the
 * daily_jobsite one — persist, then an explicit /finalize, then a LOCAL
 * markFinalized — and freezeIfImmediate is deliberately absent. It is the only
 * one of the five ported forms in this part with that shape.
 *
 * THE SIGNATURE IS THIS LOG'S OWN. useCpProfile is deliberately NOT used: a
 * cached personal CP signature would pre-lock the pad for a DIFFERENT signer.
 * The SSC/SSM signs each day's log himself, so cpName/cpSignature are local
 * state seeded only from the loaded document, and the pad opens editable
 * (autoLock={false}).
 *
 * WHAT CARRIED FORWARD from the reference (daily_jobsite.jsx), unchanged:
 *   draft lifecycle          readDraft / writeDraft / setDraftBackendId /
 *                            markPending / clearPending / markFinalized
 *   adoptAmendment           an amendment child must reach this screen
 *   the three finalize outcomes  refused / failed / offline are different
 *                            things and only one may promise a sync
 *   gateCopy                 the server names the condition, the client owns
 *                            the wording; the server's English never renders
 *   recordFinalizeError      a foreground refusal leaves the same durable
 *                            banner a background one does
 *
 * NOT CARRIED, because this form has no camera: persistPhoto and
 * compressUnderCap. NOT CARRIED, because this form builds no roster: nothing
 * here reads /checkins.
 *
 * THE PAYLOAD IS UNCHANGED — the same thirteen top-level keys
 * backend/server.py:13526 renders. See sscDailySafetyLogModel.
 */
const LOG_TYPE = 'ssc_daily_safety_log';
const TOTAL_STEPS = 4;

export default function SSCDailySafetyLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const t = useT('sscDailySafetyLog');
  const tFinalize = useT('finalize');

  const s = useMemo(() => buildStyles(), []);

  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [step, setStep] = useState(1);
  const [locked, setLocked] = useState(false);
  // The last autosave did not land. Sticky: it clears only when a later
  // write succeeds, never on the next keystroke, because a warning that
  // decays is one he can miss by typing.
  const [autosaveFailed, setAutosaveFailed] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  const [details, setDetails] = useState(EMPTY_DETAILS);
  // LOCAL to this logbook, never useCpProfile — see the header.
  const [cpName, setCpName] = useState('');
  const [cpSignature, setCpSignature] = useState(null);

  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date }),
    [projectId, date],
  );

  // The body as of RIGHT NOW, for the debounced autosave and the save path.
  // State read inside a timer is the value captured when the timer was set,
  // which is one keystroke stale — and this form is nothing but long prose.
  const bodyRef = useRef(details);
  useEffect(() => { bodyRef.current = details; }, [details]);

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
  // Debounced autosave on every change. `status` is deliberately omitted so an
  // autosave never downgrades a filed log back to draft.
  useEffect(() => {
    if (loading || locked) return undefined;
    const h = setTimeout(() => {
      // BOTH FAILURE MODES, because both mean the same thing: the draft
      // was not written. writeDraft returns false for a refused write and
      // this call used to discard it; a throw would have been swallowed by
      // the same `.catch(() => {})`. Handling one and not the other leaves
      // exactly the half nobody exercises.
      //
      // NOT A TOAST. A CP saving every few seconds does not need a message
      // each time, and one that fires constantly is one he stops reading.
      // This drives the SUBMIT GATE instead — he is told once, at the
      // moment before he signs, which is the last moment it can still matter.
      writeDraft(_key, {
        data: draftBody(bodyRef.current),
        cp_signature: cpSignature,
        cp_name: cpName,
      })
        .then((_ok) => setAutosaveFailed(!_ok))
        .catch(() => setAutosaveFailed(true));
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, details, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const _ok = await writeDraft(_key, {
        data: draftBody(bodyRef.current),
        cp_signature: cpSignature,
        cp_name: cpName,
      });
      setAutosaveFailed(!_ok);
    } catch (_e) { setAutosaveFailed(true); }
  }, [locked, _key, cpSignature, cpName]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    // THE LOCK IS RE-DERIVED ON EVERY LOAD — device round 5. `locked` could
    // only ever be set TRUE: no path set it back, so once a log was filed the
    // screen stayed read-only for the life of the mount. After an amendment
    // that is exactly wrong.
    setLocked(false);
    try {
      // LOCAL-FIRST. A local draft wins over both the project prefill and the
      // server copy, so an offline SSC reopens to the same in-progress log.
      const draft = await readDraft(_key);
      if (draft?.data && Object.keys(draft.data).length) {
        // AN AMENDMENT MUST REACH THIS SCREEN — device round 5, finding 19.
        // Parent and amendment share ONE draft key (project, logType, date), so
        // a finalized local draft used to lock the editor and return before the
        // server was ever asked. amendmentAdopt discards the frozen parent ONLY
        // on server confirmation; offline it is a no-op and the log stays
        // locked, which is honest.
        const _amended = draft.finalized && await adoptAmendment({
          key: _key, projectId, logType: LOG_TYPE, date,
        });
        if (_amended) {
          // The frozen parent is discarded; fall through to the server path,
          // which already prefers the unlocked document.
        } else {
          if (draft.finalized) { setLocked(true); markFinalized(_key); }
          setExistingLogId(draft.backend_id || null);
          setDetails(detailsFromData(draft.data));
          // Seeded from THIS log only, never a profile cache.
          if (draft.cp_signature) setCpSignature(draft.cp_signature);
          if (draft.cp_name) setCpName(draft.cp_name);
          setLoading(false);
          return;
        }
      }

      const [projectData, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        // DATE-SCOPED. Fetching with no date returns the most recent prior-day
        // doc, which would load yesterday's narrative onto today's screen and
        // file today's signature against it.
        logbooksAPI.getByProject(projectId, LOG_TYPE, date).catch(() => []),
      ]);

      // The address and the SSP number are properties of the JOB. Retyping them
      // every morning is how they end up wrong on a filed document.
      setDetails((p) => ({ ...p, ...prefillFromProject(projectData) }));

      // Prefer the EDITABLE (non-locked) doc — an amendment child — over a
      // locked original that shares (project, type, date).
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find((l) => !l.is_locked) || arr[0] || null;
      if (existing) {
        if (existing.is_locked) { setLocked(true); markFinalized(_key); }
        setExistingLogId(existing.id || existing._id);
        setDetails(detailsFromData(existing.data || {}));
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [_key, projectId, date]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── Edits ─────────────────────────────────────────────────────────────
  const setField = (key, value) => setDetails((p) => ({ ...p, [key]: value }));
  // A PLAIN BOOLEAN FLIP, deliberately. These five are two-state on every
  // reader — the combined report prints a bare Yes/No with no not-recorded
  // branch — so a third state would file something it cannot print. See
  // sscDailySafetyLogModel.
  const toggleFlag = (key) => setDetails((p) => ({ ...p, [key]: !p[key] }));

  // ── Save ──────────────────────────────────────────────────────────────
  /**
   * Local draft first, server push best-effort. Returns the doc id, `null`
   * when it saved locally with no server id yet (the offline path), or
   * `undefined` when the server REFUSED — which is not offline and must not
   * freeze.
   */
  const persistAndPush = async (submitStatus) => {
    const data = draftBody(bodyRef.current);

    // THE LOCAL SAVE IS THE OFFLINE RECORD, so its result is not discardable.
    // writeDraft answers with a BOOLEAN and this call used to drop it on the
    // floor; the try below covers a throw, because a caller that handles one
    // failure mode and not the other has fixed half of this.
    //
    // When it fails, what the CP has just signed exists only in React state
    // — and the deferred branches below would still queue the
    // key and report the log as filed, so the drain later reads a stale
    // autosave (unsigned content, filed under this key) or finds nothing and
    // clears the key as `no-draft`. Carried down to the branches that promise
    // a later sync, because that promise is the thing it invalidates.
    let localSaved = false;
    try {
      localSaved = await writeDraft(_key, {
        data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
      });
    } catch (_e) {
      // A THROW IS A FALSE. writeDraft catches its own storage errors today,
      // so this is unreachable from that function as written — and that is
      // exactly why it is here. The next person to make it throw will not
      // come back and audit fourteen call sites, and the branch they would
      // have needed is the one nobody would have tested.
      localSaved = false;
    }
    setAutosaveFailed(!localSaved);

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
      // A PUSH THAT LANDED TAKES THE BANNER DOWN. This screen imported
      // clearFinalizeError and never called it, so the durable banner had no
      // way down at all here — harmless while nothing raised one, and not
      // harmless now. Both handles: a banner raised while offline was recorded
      // against the DRAFT KEY, there being no server id yet.
      await clearFinalizeError(_key);
      if (savedId) await clearFinalizeError(savedId);
    } catch (pushErr) {
      // REFUSAL IS NOT OFFLINE. A 4xx is the server JUDGING the log, not
      // failing to reach it — and on this end-of-day type the content push and
      // the /finalize are two separate calls, so a refused push must not go on
      // to finalize anything.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      if (refused && submitStatus === 'submitted') {
        const code = finalizeErrorCode(pushErr);
        console.warn('Safety log REFUSED by the server:', status, code);
        // NO SPECIAL CASE FOR "already filed" HERE, deliberately. A 409 was
        // built for a SUBMITTED row and withdrawn: the LOCK is the line and
        // signed is not, so an end-of-day log stays writable through the day
        // and the server never refuses on that ground. The only refusal that
        // reaches here on a filed row is 423, which the lock bar already
        // handles by offering an amendment.
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        // 5xx — the server FAILED rather than judged. Retryable, and it must
        // not be announced as filed.
        console.warn('Safety log push FAILED server-side:', status || pushErr?.message);
        // Queue only a key whose draft actually holds this content — see the
        // localSaved note at the save above. A key queued over a stale draft
        // is worse than no retry: the drain would file the stale content.
        if (localSaved) await markPending(_key);
        // A BANNER, NOT ONLY A TOAST. He may have walked away by the time
        // this resolves. Recorded against the same handle the drain's
        // refusals use, so LogbookLockBar renders it on his next visit to
        // this exact log.
        // ONE OF THE TWO ALWAYS FIRES. A 5xx is the push not landing, which is
        // the same condition as offline: the work is on this device and not on
        // the server. The error toast says so and then leaves. Recording it
        // means the two reasons are exhaustive on a failed push — either the
        // device does not hold it, or the server does not.
        if (!localSaved) {
          await recordFinalizeError(
            existingLogId || _key, 'LOCAL_SAVE_FAILED', _key, 'local');
        } else {
          await recordFinalizeError(
            existingLogId || _key, 'NOT_ON_SERVER', _key, 'unsynced');
        }
        toast.error(
          tFinalize('errorTitle'),
          localSaved ? gateCopy(null) : tFinalize('localSaveFailed'),
        );
        return undefined;
      }
      // NOTHING TO DEFER TO. Offline is the one failing path that still reports
      // SUCCESS — the log is announced as filed and, for an immediate type,
      // frozen — and it does so on the strength of a local draft the drain will
      // send later. With no such draft there is no record anywhere, so the key
      // is not queued and nothing is announced.
      if (!localSaved) {
        console.warn('Safety log push deferred but the LOCAL SAVE FAILED; not queued.');
        await recordFinalizeError(
          existingLogId || _key, 'LOCAL_SAVE_FAILED', _key, 'local');
        toast.error(tFinalize('localSaveFailedTitle'), tFinalize('localSaveFailed'));
        return undefined;
      }
      await markPending(_key);
      console.warn('Safety log push deferred (will sync on reconnect):', pushErr?.message);
      // ON THIS DEVICE ONLY — the other half of the same banner. The local
      // write landed, so this log IS safe here and IS queued; what is not true
      // is that anyone else can see it. He is about to attest to a legal
      // record, and a toast saying "will sync" is gone before he has
      // finished reading it, so this goes up durably and comes down when the
      // drain succeeds (clearUnsyncedBanner in draftSync).
      await recordFinalizeError(
        existingLogId || _key, 'NOT_ON_SERVER', _key, 'unsynced');
    }

    if (submitStatus === 'submitted' && cpSignature) {
      const docId = existingLogId || created?.id || created?._id;
      if (docId) {
        recordSignatureEvent({
          documentType: 'logbook', documentId: docId, eventType: 'ssc_sign',
          signerName: cpName, signerRole: user?.role || 'ssc',
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
   * THE end-of-day action — one button, one freeze. daily_jobsite's shape,
   * because this is the other log that wears it.
   *
   *   1. content and signature into the local draft first; server push
   *      best-effort (markPending on failure; the drain re-applies /finalize
   *      on reconnect).
   *   2. server /finalize when the doc has an id.
   *   3. LOCAL freeze — but ONLY when the server never ANSWERED.
   *   4. flip the form read-only.
   *
   * REFUSAL IS NOT OFFLINE. Treating every finalize failure as offline
   * produced three compounding lies on daily_jobsite: the CP was told the log
   * was signed, locked and would sync when the server had said no and would
   * keep saying no; markFinalized made the draft IMMUTABLE so he could not fix
   * the very condition being refused; and the content push had SUCCEEDED, so
   * no pending key existed and the drain would never retry.
   *
   * So there are THREE outcomes and only one of them may promise a sync.
   */
  const handleSubmitAndSign = async () => {
    if (signing) return;
    // SIGNATURE CLIENT GUARD. The footer button is already disabled for this,
    // so reaching here means the state moved under the press.
    if (!isAffirmedSignature(cpSignature)) {
      setStep(TOTAL_STEPS);
      toast.warning(t('signatureRequiredTitle'), t('signatureRequiredBody'));
      return;
    }
    setSigning(true);
    try {
      const savedId = await persistAndPush('submitted');
      // `undefined` = refused or failed, already reported. Nothing may be
      // frozen or announced on a log that was never written. `null` is
      // different: saved LOCALLY with no server id, which is the offline path
      // and DOES freeze below.
      if (savedId === undefined) return;
      // ── SIGN ONCE, FREEZE AT END OF DAY ───────────────────────────────
      //
      // THE SIGNATURE IS NOT THE FREEZE ON THIS LOG. ssc_daily_safety_log is
      // END_OF_DAY, the same class as daily_jobsite: the daily narrative,
      // open and accumulating. LOGBOOK_TIMING_CLASS says so, logbookTiming.js
      // says so, and /logbook-types serves it to clients as
      // `freeze_on_finalize` — and it was true nowhere, because this block
      // called /finalize the instant the SSC signed.
      //
      // He signs once. The record stays editable. sweep_stale_end_of_day_logs
      // freezes it at 3am ET once the day is over — signed and stale, and only
      // then. An UNSIGNED stale log is flagged instead of sealed.
      //
      // The three-way finalize split went with the call it was written for:
      // no finalize is attempted, so its refusal cannot occur. The submit push
      // above keeps its own split, which is where a server judgement still
      // reaches this screen.
      toast.success(t('submittedTitle'), t('signedStaysOpen'));
      router.back();
    } catch (e) {
      console.error(e);
      toast.error(t('saveFailedTitle'), t('saveFailedTitle'));
    } finally {
      setSigning(false);
    }
  };

  // Moving on is never BLOCKED — an SSC who cannot complete a step because the
  // day is not over must still be able to close it out.
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

  const incomplete = computeIncomplete({ details, cpSignature }).filter((n) => n !== step);
  const showIncident = incidentDetailsApply(details);
  // The other four ported forms read this from useCpProfile, which has a real
  // loading window. THIS pad is the log's own and nothing is fetched for it, so
  // the signature is either affirmed or it is not and the hint never has a
  // "still loading" state to report. Named rather than passed inline so the
  // five screens spell the gate the same way.
  const profileLoaded = true;

  // ── STEP 1 — the site ─────────────────────────────────────────────────
  const renderStep1 = () => (
    <View>
      <StepHeader title={t('step1Title')} />
      <Text style={s.noteText}>{t('siteHint')}</Text>

      <Card s={s}>
        {/* Carried from the project record, not typed here. Shown read-only
            because the SSP number and the address are properties of the JOB;
            correcting them on one day's log would not correct the job. */}
        {PREFILLED_FIELDS.map((f) => (
          <View key={f.key} style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t(f.labelKey)}</Text>
            <View style={s.readOnlyValue}>
              <Text style={s.readOnlyText}>{details[f.key] || t('notOnFile')}</Text>
            </View>
          </View>
        ))}
        <Text style={s.noteText}>{t('fromProjectNote')}</Text>

        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fWeather')}</Text>
          <View style={s.chipWrap}>
            {WEATHER_OPTIONS.map((w) => (
              <Chip
                key={w}
                label={w}
                selected={details.weather === w}
                onPress={() => setField('weather', details.weather === w ? '' : w)}
              />
            ))}
          </View>
        </View>

        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fWorkers')}</Text>
          <TextInput
            style={s.input}
            value={details.workers_on_site_count || ''}
            onChangeText={(v) => setField('workers_on_site_count', v)}
            placeholder={t('phField')}
            placeholderTextColor={outdoor.textDim}
            keyboardType="numeric"
          />
        </View>
      </Card>
    </View>
  );

  // ── STEP 2 — compliance ───────────────────────────────────────────────
  //
  // FIVE TWO-STATE SWITCHES. Not the three-state chip pair the checklists on
  // the other ported forms use: every reader of this document prints a bare
  // Yes/No for these and has no "not recorded" to print. The note below says
  // what an unticked one means on the filed page — the same caveat both PDF
  // surfaces already print under the table.
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />
      <Text style={s.noteText}>{t('complianceHint')}</Text>

      <Card s={s}>
        {COMPLIANCE_FLAGS.map((f) => (
          <Pressable
            key={f.key}
            style={[s.toggleRow, details[f.key] && s.toggleRowOn]}
            accessibilityRole="button"
            accessibilityState={{ selected: !!details[f.key] }}
            onPress={() => toggleFlag(f.key)}
          >
            <View style={[s.toggleBox, details[f.key] && s.toggleBoxOn]}>
              {details[f.key] && <Check size={18} strokeWidth={3} color={outdoor.ok} />}
            </View>
            <Text style={s.toggleText}>{f.label}</Text>
          </Pressable>
        ))}
      </Card>
      <Text style={s.noteText}>{t('complianceDefaultNote')}</Text>
    </View>
  );

  // ── STEP 3 — the narrative ────────────────────────────────────────────
  const renderStep3 = () => (
    <View>
      <StepHeader title={t('step3Title')} />
      <Text style={s.noteText}>{t('narrativeHint')}</Text>

      {NARRATIVE_FIELDS.map((f) => (
        <Card s={s} key={f.key}>
          <Text style={s.question}>{f.label}</Text>
          <TextInput
            style={[s.input, s.textArea]}
            value={details[f.key] || ''}
            onChangeText={(v) => setField(f.key, v)}
            placeholder={t('phNarrative')}
            placeholderTextColor={outdoor.textDim}
            multiline
            numberOfLines={4}
          />
        </Card>
      ))}

      {/* Only when an incident WAS reported — the same condition all three
          readers print it under. If one was, a missing detail is an unanswered
          question on the filed document, not silence, so the step stays
          incomplete until it is written. */}
      {showIncident && (
        <Card s={s} style={String(details.incident_details || '').trim() ? undefined : s.cardWarn}>
          <Text style={s.question}>{t('fIncidentDetails')}</Text>
          <Text style={s.noteText}>{t('incidentDetailsHint')}</Text>
          <TextInput
            style={[s.input, s.textArea]}
            value={details.incident_details || ''}
            onChangeText={(v) => setField('incident_details', v)}
            placeholder={t('phNarrative')}
            placeholderTextColor={outdoor.textDim}
            multiline
            numberOfLines={4}
          />
        </Card>
      )}
    </View>
  );

  // ── STEP 4 — review and sign ──────────────────────────────────────────
  const renderStep4 = () => (
    <View>
      <StepHeader title={t('step4Title')} />
      <Text style={s.noteText}>{t('reviewHeading')}</Text>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewSite')}</Text>
        {PREFILLED_FIELDS.map((f) => (
          <View key={f.key} style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t(f.labelKey)}</Text>
            <Text style={s.reviewValue}>{details[f.key] || t('notRecorded')}</Text>
          </View>
        ))}
        <View style={s.reviewRow}>
          <Text style={s.reviewLabel}>{t('fWeather')}</Text>
          <Text style={s.reviewValue}>{details.weather || t('notRecorded')}</Text>
        </View>
        <View style={s.reviewRow}>
          <Text style={s.reviewLabel}>{t('fWorkers')}</Text>
          <Text style={s.reviewValue}>
            {String(details.workers_on_site_count || '').trim() || t('notRecorded')}
          </Text>
        </View>
      </Card>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewCompliance')}</Text>
        {COMPLIANCE_FLAGS.map((f) => (
          <View key={f.key} style={s.reviewRow}>
            <Text style={s.reviewLabel}>{f.label}</Text>
            <Text style={s.reviewValue}>{details[f.key] ? t('yes') : t('no')}</Text>
          </View>
        ))}
      </Card>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewNarrative')}</Text>
        {NARRATIVE_FIELDS.map((f) => (
          <View key={f.key} style={s.reviewRow}>
            <Text style={s.reviewLabel}>{f.label}</Text>
            <Text style={s.reviewValue}>
              {String(details[f.key] || '').trim() || t('notRecorded')}
            </Text>
          </View>
        ))}
        {showIncident && (
          <View style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t('fIncidentDetails')}</Text>
            <Text style={s.reviewValue}>
              {String(details.incident_details || '').trim() || t('notRecorded')}
            </Text>
          </View>
        )}
      </Card>

      <Card s={s}>
        <Text style={s.reviewLabel}>
          {incomplete.length > 0 ? t('stepsIncomplete') : t('stepsAllComplete')}
        </Text>
        <Text style={s.noteText}>{t('signingClosesDay')}</Text>
        {/* THIS LOG'S OWN PAD. autoLock={false} keeps it editable so the
            SSC/SSM signs each day himself rather than inheriting a cached
            credential belonging to somebody else. */}
        <SignaturePad
          pinned
          title="SSC/SSM Signature"
          signerName={cpName}
          onNameChange={setCpName}
          existingSignature={cpSignature}
          onSignatureCapture={setCpSignature}
          autoLock={false}
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
      submitLabel={t('submitAndSign')}
      submitting={signing}
      /* END_OF_DAY, so the signature is not itself the freeze — but this is
         still the single irreversible closing action, and it mints a signed
         legal record. An unaffirmed signature makes it UNREACHABLE rather than
         merely warned about, which also refuses the `cp_signature: {}` that
         satisfied the old presence check. */
      submitDisabled={!isAffirmedSignature(cpSignature)}
      submitHint={affirmationHintKey(cpSignature, profileLoaded)
        ? tFinalize(affirmationHintKey(cpSignature, profileLoaded)) : ''}
      onSubmit={handleSubmitAndSign}
      logType={LOG_TYPE}
      logId={existingLogId}
      draftKey={_key}
      onFinalized={() => setLocked(true)}
      onAmended={fetchData}
      submitWarning={autosaveFailed ? tFinalize('autosaveFailedWarning') : ''}
      autosaveNote={t('savedAutomatically')}
    />
  );
}

/**
 * The shared chrome plus the handful of keys only this form uses. Spreading
 * rather than forking is what keeps the shared names identical across forms.
 */
function buildStyles() {
  return StyleSheet.create({
    ...buildStepperStyles(),
    reviewRow: {
      gap: spacing.xs / 2,
      paddingVertical: spacing.xs,
    },
    // The narrative prompts are prose, not one-liners: this log IS the
    // sentences the SSC writes, so the boxes are sized for them.
    textArea: {
      minHeight: spacing.xxl * 2,
      paddingTop: spacing.sm,
      textAlignVertical: 'top',
    },
    toggleBoxOn: { borderColor: outdoor.okBorder },
  });
}
