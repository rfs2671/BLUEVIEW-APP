import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  View, Text, StyleSheet, TextInput,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import SignaturePad from '../../src/components/SignaturePad';
import OfflineNotice from '../../src/components/OfflineNotice';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI } from '../../src/utils/api';
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
// settleFetch reports HOW a load ended; isOfflineError is the app-wide OFFLINE
// discriminator — "offline" has to mean what it means everywhere else: no
// response at all.
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import LogbookStepper from '../../src/components/logbookStepper/LogbookStepper';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { Card, ChipBase, StepHeaderBase } from '../../src/components/logbookStepper/primitives';
import TimeField from '../../src/components/logbookStepper/TimeField';
import {
  WORK_TYPE_OPTIONS, DETAIL_FIELDS, PRECAUTION_ITEMS, CONFIRM_OPTIONS,
  EMPTY_DETAILS, calcFireWatchEnd, detailsFromData,
  incompleteSteps as computeIncomplete, draftBody,
} from '../../src/utils/hotWorkModel';
import { applyChecklistAnswer, recordedCount } from '../../src/utils/checklistMap';
import { useT } from '../../src/i18n';
import { spacing, outdoor } from '../../src/styles/theme';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';

/**
 * HOT WORK PERMIT — on the shared stepper.
 *
 * FOUR STEPS, in the order the filed permit prints them: the work, the timing,
 * the seven precautions, then review and sign. The chrome is LogbookStepper's —
 * nothing about the header, pips, lock bar or footer is decided here.
 *
 * WHAT CARRIED FORWARD from the reference (daily_jobsite.jsx), unchanged:
 *   draft lifecycle          readDraft / writeDraft / setDraftBackendId /
 *                            markPending / clearPending / markFinalized
 *   adoptAmendment           an amendment child must reach this screen
 *   signature client guard   no signature, no file — and it says why
 *   gateCopy                 the server names the condition, the client owns
 *                            the wording; the server's English never renders
 *   recordFinalizeError      a foreground refusal leaves the same durable
 *                            banner a background one does
 *
 * AND ONE THIS SCREEN OWNS ALONE: the OFFLINE-AWARE hydrate. A failed load with
 * no local draft must not render as a blank permit — that reads as "no permit
 * exists for today" and invites a duplicate. settleFetch reports how the load
 * ended and OfflineNotice says so, on step 1, which is where the CP lands.
 *
 * NOT CARRIED, because this form has no camera: persistPhoto and
 * compressUnderCap. NOT CARRIED, because this form builds no roster: nothing
 * here reads /checkins.
 *
 * THE PAYLOAD IS UNCHANGED — the same nine top-level keys
 * backend/server.py:13256 renders. Two precaution LABELS did change, to the
 * ones all three readers already print; see hotWorkModel.
 */
const LOG_TYPE = 'hot_work';
const TOTAL_STEPS = 4;

export default function HotWorkPermitLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const t = useT('hotWork');
  const tFinalize = useT('finalize');
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave } = useCpProfile();

  const s = useMemo(() => buildStyles(), []);

  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [step, setStep] = useState(1);
  const [locked, setLocked] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  // 'ok' | 'offline' | 'error' — how the LAST server hydrate went. Only used
  // when there is no local draft: a failed load must not masquerade as a blank
  // new permit.
  const [fetchState, setFetchState] = useState('ok');
  const [details, setDetails] = useState(EMPTY_DETAILS);
  const [precautions, setPrecautions] = useState({});

  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date }),
    [projectId, date],
  );

  // The body as of RIGHT NOW, for the debounced autosave and the save path.
  // State read inside a timer is the value captured when the timer was set,
  // which is one keystroke stale.
  const bodyRef = useRef({ details, precautions });
  useEffect(() => { bodyRef.current = { details, precautions }; }, [details, precautions]);

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
  // autosave never downgrades a filed permit back to draft.
  useEffect(() => {
    if (loading || locked) return undefined;
    const h = setTimeout(() => {
      const b = bodyRef.current;
      writeDraft(_key, {
        data: draftBody(b.details, b.precautions),
        cp_signature: cpSignature,
        cp_name: cpName,
      }).catch(() => {});
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, details, precautions, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const b = bodyRef.current;
      await writeDraft(_key, {
        data: draftBody(b.details, b.precautions),
        cp_signature: cpSignature,
        cp_name: cpName,
      });
    } catch (_e) { /* best-effort; the next change retries */ }
  }, [locked, _key, cpSignature, cpName]);

  const applyLoaded = useCallback((d) => {
    setDetails(detailsFromData(d));
    if (d.precautions && typeof d.precautions === 'object') setPrecautions(d.precautions);
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    // THE LOCK IS RE-DERIVED ON EVERY LOAD — device round 5. `locked` could
    // only ever be set TRUE: no path set it back, so once a permit was filed
    // the screen stayed read-only for the life of the mount. After an amendment
    // that is exactly wrong.
    setLocked(false);
    try {
      // LOCAL-FIRST. A local draft wins over the server copy, so an offline CP
      // reopens to exactly what he filled and unsynced edits are never
      // clobbered.
      const draft = await readDraft(_key);
      if (draft?.data && Object.keys(draft.data).length) {
        // AN AMENDMENT MUST REACH THIS SCREEN — device round 5, finding 19.
        // Parent and amendment share ONE draft key (project, logType, date), so
        // a finalized local draft used to lock the editor and return before the
        // server was ever asked: the child sat there unlocked and unreachable
        // while the logbook list showed it as a Draft. amendmentAdopt discards
        // the frozen parent ONLY on server confirmation; offline it is a no-op
        // and the permit stays locked, which is honest.
        const _amended = draft.finalized && await adoptAmendment({
          key: _key, projectId, logType: LOG_TYPE, date,
        });
        if (_amended) {
          // The frozen parent is discarded; fall through to the server path,
          // which already prefers the unlocked document.
        } else {
          setFetchState('ok');
          if (draft.finalized) { setLocked(true); markFinalized(_key); }
          setExistingLogId(draft.backend_id || null);
          applyLoaded(draft.data);
          if (draft.cp_signature) setCpSignature(draft.cp_signature);
          if (draft.cp_name) setCpName(draft.cp_name);
          setLoading(false);
          return;
        }
      }

      // OFFLINE-AWARE, and DATE-SCOPED. `.catch(() => [])` would turn a failed
      // load into a blank permit, which reads as "none exists today"; settleFetch
      // reports the outcome so step 1 can say what actually happened.
      const r = await settleFetch(
        () => logbooksAPI.getByProject(projectId, LOG_TYPE, date),
      );
      setFetchState(r.status);
      // Prefer the EDITABLE (non-locked) doc — an amendment child — over a
      // locked original that shares (project, type, date).
      const arr = Array.isArray(r.data) ? r.data : [];
      const existing = arr.find((l) => !l.is_locked) || arr[0] || null;
      if (existing) {
        if (existing.is_locked) { setLocked(true); markFinalized(_key); }
        setExistingLogId(existing.id || existing._id);
        applyLoaded(existing.data || {});
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [_key, projectId, date, applyLoaded, setCpName, setCpSignature]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── Edits ─────────────────────────────────────────────────────────────
  const setDetail = (key, value) => setDetails((p) => ({ ...p, [key]: value }));
  // applyChecklistAnswer, NOT `!prev[key]`: the map is TRI-STATE on the filed
  // permit — absent is "Not recorded", false is an explicit "No" — and the old
  // dot could not tell those apart. See src/utils/checklistMap.js.
  const setPrecaution = (key, value) => setPrecautions(
    (p) => applyChecklistAnswer(p, key, value),
  );

  // ── Save ──────────────────────────────────────────────────────────────
  /**
   * Local draft first, server push best-effort. Returns the doc id, `null`
   * when it saved locally with no server id yet (the offline path), or
   * `undefined` when the server REFUSED — which is not offline and must not
   * freeze.
   */
  const persistAndPush = async (submitStatus) => {
    const b = bodyRef.current;
    const data = draftBody(b.details, b.precautions);

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
      // REFUSAL IS NOT OFFLINE. hot_work is an IMMEDIATE type, so a submitted
      // push IS the finalize — a 4xx here is the server judging the permit, not
      // failing to reach it. Freezing on a judgement would tell the CP it was
      // filed, make the draft immutable so he could not fix what was refused,
      // and leave nothing pending for the drain to retry.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      if (refused && submitStatus === 'submitted') {
        const code = finalizeErrorCode(pushErr);
        console.warn('Hot work permit REFUSED by the server:', status, code);
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        // 5xx — the server FAILED rather than judged. Retryable, and it must
        // not be announced as filed.
        console.warn('Hot work permit push FAILED server-side:', status || pushErr?.message);
        await markPending(_key);
        toast.error(tFinalize('errorTitle'), gateCopy(null));
        return undefined;
      }
      await markPending(_key);
      console.warn('Hot work permit push deferred (will sync on reconnect):', pushErr?.message);
    }

    // Guarded: a CP-PROFILE save failure must never report a failure on a permit
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
   * THE one action. hot_work is an IMMEDIATE log: THE SIGNATURE IS THE FREEZE.
   * Submitting finalizes the permit in one action and it is never reopened — a
   * second burn is a NEW permit, and a correction is an amendment.
   */
  const handleSubmitAndSign = async () => {
    if (signing) return;
    // SIGNATURE CLIENT GUARD. draftSync refuses an unsigned submitted push and
    // records SUBMIT_MISSING_CP_SIGNATURE against the key; catching it here
    // means the CP is told on the screen that can fix it.
    if (!cpSignature) {
      setStep(TOTAL_STEPS);
      toast.warning(t('signatureRequiredTitle'), t('signatureRequiredBody'));
      return;
    }
    setSigning(true);
    try {
      const savedId = await persistAndPush('submitted');
      // `undefined` = refused or failed, already reported. Nothing may be
      // frozen or announced on a permit the server would not take. `null` is
      // different: saved LOCALLY with no server id, which is the offline path
      // and DOES freeze — a permit signed in a basement must still hold.
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

  // Moving on is never BLOCKED — a CP who cannot complete a step because the
  // data is not there must still finish and sign.
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

  const incomplete = computeIncomplete({ details, precautions, cpSignature })
    .filter((n) => n !== step);
  const precautionsAnswered = recordedCount(precautions, PRECAUTION_ITEMS);
  // Shown live, computed by the SAME function that writes it into the payload —
  // the time on screen is the time that files.
  const fireWatchEnd = calcFireWatchEnd(details.end_time);

  // ── STEP 1 — the work ─────────────────────────────────────────────────
  const renderStep1 = () => (
    <View>
      {/* The load FAILED and there was no local draft to fall back on — say so.
          Without this the screen opens a blank permit, which reads as "no permit
          exists for today" and invites a duplicate entry. */}
      {fetchState !== 'ok' && (
        <OfflineNotice
          mode={fetchState}
          detail={fetchState === 'offline' ? t('offlineDetail') : undefined}
        />
      )}

      <StepHeader title={t('step1Title')} />
      <Text style={s.noteText}>{t('workHint')}</Text>

      <Card s={s}>
        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fWorkType')}</Text>
          <View style={s.chipWrap}>
            {WORK_TYPE_OPTIONS.map((opt) => (
              <Chip
                key={opt}
                label={opt}
                selected={details.work_type === opt}
                onPress={() => setDetail('work_type', details.work_type === opt ? '' : opt)}
              />
            ))}
          </View>
        </View>

        {DETAIL_FIELDS.map((f) => (
          <View key={f.key} style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t(f.labelKey)}</Text>
            <TextInput
              style={s.input}
              value={details[f.key] || ''}
              onChangeText={(v) => setDetail(f.key, v)}
              placeholder={t('phField')}
              placeholderTextColor={outdoor.textDim}
            />
          </View>
        ))}
      </Card>
    </View>
  );

  // ── STEP 2 — the timing ───────────────────────────────────────────────
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />
      <Text style={s.noteText}>{t('timingHint')}</Text>

      <Card s={s}>
        <TimeField
          s={s}
          label={t('fStartTime')}
          placeholder={t('phTime')}
          value={details.start_time}
          clearLabel={t('dateClear')}
          doneLabel={t('dateDone')}
          onChange={(v) => setDetail('start_time', v)}
        />
        <TimeField
          s={s}
          label={t('fEndTime')}
          placeholder={t('phTime')}
          value={details.end_time}
          clearLabel={t('dateClear')}
          doneLabel={t('dateDone')}
          onChange={(v) => setDetail('end_time', v)}
        />

        {/* DERIVED, AND IT SAYS SO. This permit captures no real watch-until;
            FDNY can require sixty minutes, so the screen labels it the computed
            default it is — the same words all three readers print beside it. */}
        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fFireWatchUntil')}</Text>
          <View style={s.readOnlyValue}>
            <Text style={s.readOnlyText}>{fireWatchEnd || t('needsEndTime')}</Text>
            <Text style={s.noteText}>{t('fireWatchDerived')}</Text>
          </View>
        </View>

        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fFireWatchName')}</Text>
          <TextInput
            style={s.input}
            value={details.fire_watch_name || ''}
            onChangeText={(v) => setDetail('fire_watch_name', v)}
            placeholder={t('phField')}
            placeholderTextColor={outdoor.textDim}
          />
        </View>
      </Card>
    </View>
  );

  // ── STEP 3 — the seven precautions ────────────────────────────────────
  //
  // ONE ITEM PER BLOCK with its two answers beneath it, the shape the scaffold
  // inspection settled on: a right-aligned answer strip beside a wrapping label
  // is unreadable at arm's length outdoors.
  const renderStep3 = () => (
    <View>
      <StepHeader title={t('step3Title')} />
      <Text style={s.noteText}>{t('precautionsHint')}</Text>
      <Text style={s.noteText}>
        {t('answeredOf')
          .replace('{n}', String(precautionsAnswered))
          .replace('{m}', String(PRECAUTION_ITEMS.length))}
      </Text>

      {PRECAUTION_ITEMS.map((item, i) => (
        <Card s={s} key={item.key}>
          <Text style={s.reviewLabel}>
            {t('itemOf')
              .replace('{n}', String(i + 1))
              .replace('{m}', String(PRECAUTION_ITEMS.length))}
          </Text>
          <Text style={s.question}>{item.label}</Text>
          <View style={s.chipWrap}>
            {CONFIRM_OPTIONS.map((opt) => (
              <Chip
                key={opt.label}
                label={opt.label}
                selected={precautions[item.key] === opt.value}
                onPress={() => setPrecaution(item.key, opt.value)}
              />
            ))}
          </View>
        </Card>
      ))}
    </View>
  );

  // ── STEP 4 — review and sign ──────────────────────────────────────────
  const renderStep4 = () => {
    const unanswered = PRECAUTION_ITEMS.length - precautionsAnswered;
    return (
      <View>
        <StepHeader title={t('step4Title')} />
        <Text style={s.noteText}>{t('reviewHeading')}</Text>

        <Card s={s}>
          <Text style={s.reviewLabel}>{t('reviewWork')}</Text>
          <View style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t('fWorkType')}</Text>
            <Text style={s.reviewValue}>{details.work_type || t('notRecorded')}</Text>
          </View>
          {DETAIL_FIELDS.map((f) => (
            <View key={f.key} style={s.reviewRow}>
              <Text style={s.reviewLabel}>{t(f.labelKey)}</Text>
              <Text style={s.reviewValue}>
                {String(details[f.key] || '').trim() || t('notRecorded')}
              </Text>
            </View>
          ))}
        </Card>

        <Card s={s}>
          <Text style={s.reviewLabel}>{t('reviewTiming')}</Text>
          <View style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t('fStartTime')}</Text>
            <Text style={s.reviewValue}>{details.start_time || t('notRecorded')}</Text>
          </View>
          <View style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t('fEndTime')}</Text>
            <Text style={s.reviewValue}>{details.end_time || t('notRecorded')}</Text>
          </View>
          <View style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t('fFireWatchUntil')}</Text>
            <Text style={s.reviewValue}>
              {fireWatchEnd ? `${fireWatchEnd} ${t('fireWatchDerived')}` : t('notRecorded')}
            </Text>
          </View>
          <View style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t('fFireWatchName')}</Text>
            <Text style={s.reviewValue}>
              {String(details.fire_watch_name || '').trim() || t('notRecorded')}
            </Text>
          </View>
        </Card>

        <Card s={s} style={unanswered > 0 ? s.cardWarn : undefined}>
          <Text style={s.reviewLabel}>{t('reviewPrecautions')}</Text>
          <Text style={s.reviewValue}>
            {unanswered > 0
              ? t('reviewUnanswered').replace('{n}', String(unanswered))
              : t('reviewAllAnswered').replace('{m}', String(PRECAUTION_ITEMS.length))}
          </Text>
        </Card>

        <Card s={s}>
          <Text style={s.reviewLabel}>
            {incomplete.length > 0 ? t('stepsIncomplete') : t('stepsAllComplete')}
          </Text>
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
  };

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
      /* hot_work is IMMEDIATE — the server locks on `submitted` alone — so an
         unsigned submit must be UNREACHABLE, not merely warned about. The
         handler keeps its guard as a backstop. */
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
  });
}
