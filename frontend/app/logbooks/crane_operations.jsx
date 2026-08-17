import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  View, Text, StyleSheet, Pressable, TextInput,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Plus, Trash2 } from 'lucide-react-native';
import SignaturePad from '../../src/components/SignaturePad';
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
// The app-wide OFFLINE discriminator — "offline" has to mean what it means
// everywhere else: no response at all.
import { isOfflineError } from '../../src/utils/offlineState';
import LogbookStepper from '../../src/components/logbookStepper/LogbookStepper';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { Card, ChipBase, StepHeaderBase } from '../../src/components/logbookStepper/primitives';
import TimeField from '../../src/components/logbookStepper/TimeField';
import {
  DETAIL_FIELDS, PRE_OP_CHECKLIST_ITEMS, CONFIRM_OPTIONS,
  EMPTY_DETAILS, EMPTY_LOAD_ENTRY, loadEntriesForFiling, filledLiftCount,
  preOpRecordedCount, detailsFromData,
  incompleteSteps as computeIncomplete, draftBody,
} from '../../src/utils/craneOperationsModel';
import { applyChecklistAnswer } from '../../src/utils/checklistMap';
import { useT } from '../../src/i18n';
import { spacing, borderRadius, outdoor, touchTarget } from '../../src/styles/theme';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';

/**
 * CRANE OPERATIONS LOG — the crane, the pre-lift checks, and every lift, on the
 * shared stepper.
 *
 * FOUR STEPS, in the order the filed document prints them: the crane and its
 * operator, the fifteen pre-operation checks, the lift log, then review and
 * sign. The chrome is LogbookStepper's — nothing about the header, pips, lock
 * bar or footer is decided here.
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
 * NOT CARRIED, because this form has no camera: persistPhoto and
 * compressUnderCap. There is no photo on the crane log.
 *
 * NOT CARRIED, because this form builds no roster: nothing here reads
 * /checkins. The empty-roster trap has no surface to appear on.
 *
 * THERE IS NO SAVE DRAFT BUTTON. Every change autosaves to the local draft;
 * the one primary action is Sign and file.
 *
 * THE PAYLOAD IS UNCHANGED — the same six top-level keys
 * backend/server.py:13295 renders. See craneOperationsModel.
 */
const LOG_TYPE = 'crane_operations';
const TOTAL_STEPS = 4;

export default function CraneOperationsLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const t = useT('craneOperations');
  const tFinalize = useT('finalize');
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave } = useCpProfile();

  const s = useMemo(() => buildStyles(), []);

  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [step, setStep] = useState(1);
  const [locked, setLocked] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  const [details, setDetails] = useState(EMPTY_DETAILS);
  const [preOpChecklist, setPreOpChecklist] = useState({});
  const [loadEntries, setLoadEntries] = useState([EMPTY_LOAD_ENTRY()]);

  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date }),
    [projectId, date],
  );

  // The body as of RIGHT NOW, for the debounced autosave and the save path.
  // State read inside a timer is the value captured when the timer was set,
  // which is one keystroke stale.
  const bodyRef = useRef({ details, preOpChecklist, loadEntries });
  useEffect(() => {
    bodyRef.current = { details, preOpChecklist, loadEntries };
  }, [details, preOpChecklist, loadEntries]);

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
      const b = bodyRef.current;
      writeDraft(_key, {
        data: draftBody(b.details, b.preOpChecklist, b.loadEntries),
        cp_signature: cpSignature,
        cp_name: cpName,
      }).catch(() => {});
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, details, preOpChecklist, loadEntries, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const b = bodyRef.current;
      await writeDraft(_key, {
        data: draftBody(b.details, b.preOpChecklist, b.loadEntries),
        cp_signature: cpSignature,
        cp_name: cpName,
      });
    } catch (_e) { /* best-effort; the next change retries */ }
  }, [locked, _key, cpSignature, cpName]);

  const applyLoaded = useCallback((d) => {
    setDetails(detailsFromData(d));
    if (d.pre_operation_checklist && typeof d.pre_operation_checklist === 'object') {
      setPreOpChecklist(d.pre_operation_checklist);
    }
    if (Array.isArray(d.load_entries) && d.load_entries.length > 0) {
      setLoadEntries(d.load_entries);
    }
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    // THE LOCK IS RE-DERIVED ON EVERY LOAD — device round 5. `locked` could
    // only ever be set TRUE: no path set it back, so once a log was filed the
    // screen stayed read-only for the life of the mount. After an amendment
    // that is exactly wrong. Everything below decides locked-ness from what it
    // loads.
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
        // and the log stays locked, which is honest.
        const _amended = draft.finalized && await adoptAmendment({
          key: _key, projectId, logType: LOG_TYPE, date,
        });
        if (_amended) {
          // The frozen parent is discarded; fall through to the server path,
          // which already prefers the unlocked document.
        } else {
          if (draft.finalized) { setLocked(true); markFinalized(_key); }
          setExistingLogId(draft.backend_id || null);
          applyLoaded(draft.data);
          if (draft.cp_signature) setCpSignature(draft.cp_signature);
          if (draft.cp_name) setCpName(draft.cp_name);
          setLoading(false);
          return;
        }
      }

      // DATE-SCOPED. Fetching with no date returns the most recent prior-day
      // doc, which would load yesterday's lifts onto today's screen and file
      // today's signature against it.
      const existingLogs = await logbooksAPI
        .getByProject(projectId, LOG_TYPE, date).catch(() => []);
      // Prefer the EDITABLE (non-locked) doc — an amendment child — over a
      // locked original that shares (project, type, date).
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
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
  // document — absent is "Not recorded", false is an explicit "No" — and the
  // old dot could not tell those apart. See src/utils/checklistMap.js.
  const setPreOp = (key, value) => setPreOpChecklist(
    (p) => applyChecklistAnswer(p, key, value),
  );
  const setLiftField = (index, field, value) => setLoadEntries(
    (p) => p.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
  );
  const addLoadEntry = () => setLoadEntries((p) => [...p, EMPTY_LOAD_ENTRY()]);
  const removeLoadEntry = (index) => setLoadEntries((p) => p.filter((_, i) => i !== index));

  // ── Save ──────────────────────────────────────────────────────────────
  /**
   * Local draft first, server push best-effort. Returns the doc id, `null`
   * when it saved locally with no server id yet (the offline path), or
   * `undefined` when the server REFUSED — which is not offline and must not
   * freeze.
   */
  const persistAndPush = async (submitStatus) => {
    const b = bodyRef.current;
    // AN ABANDONED ROW IS NOT A LIFT. On SUBMIT the lift log is trimmed to the
    // rows that say something — the same rule all three renderers already drop
    // rows by, so what is filed and what is printed are the same log.
    //
    // A DRAFT KEEPS EVERYTHING: a half-typed row the operator is still working
    // on must survive a save.
    const filed = submitStatus === 'submitted'
      ? loadEntriesForFiling(b.loadEntries) : b.loadEntries;
    // What he signed is what he sees.
    if (submitStatus === 'submitted' && filed.length !== b.loadEntries.length) {
      setLoadEntries(filed.length > 0 ? filed : [EMPTY_LOAD_ENTRY()]);
    }
    const data = draftBody(b.details, b.preOpChecklist, filed);

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
      // REFUSAL IS NOT OFFLINE. crane_operations is an IMMEDIATE type, so a
      // submitted push IS the finalize — a 4xx here is the server judging the
      // log, not failing to reach it. Freezing on a judgement would tell the CP
      // it was filed, make the draft immutable so he could not fix what was
      // refused, and leave nothing pending for the drain to retry.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      if (refused && submitStatus === 'submitted') {
        const code = finalizeErrorCode(pushErr);
        console.warn('Crane log REFUSED by the server:', status, code);
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        // 5xx — the server FAILED rather than judged. Retryable, and it must
        // not be announced as filed.
        console.warn('Crane log push FAILED server-side:', status || pushErr?.message);
        await markPending(_key);
        toast.error(tFinalize('errorTitle'), gateCopy(null));
        return undefined;
      }
      await markPending(_key);
      console.warn('Crane log push deferred (will sync on reconnect):', pushErr?.message);
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
   * THE one action. crane_operations is an IMMEDIATE log: THE SIGNATURE IS THE
   * FREEZE. Submitting finalizes the record in one action and it is never
   * reopened — a later lift record is a NEW discrete log, and a correction is
   * an amendment.
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
      // frozen or announced on a log the server would not take. `null` is
      // different: saved LOCALLY with no server id, which is the offline path
      // and DOES freeze — a lift signed off with no signal must still hold.
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

  const incomplete = computeIncomplete({
    details, preOpChecklist, loadEntries, cpSignature,
  }).filter((n) => n !== step);
  const preOpAnswered = preOpRecordedCount(preOpChecklist);
  const filledLifts = filledLiftCount(loadEntries);

  // ── STEP 1 — the crane and its operator ───────────────────────────────
  const renderStep1 = () => (
    <View>
      <StepHeader title={t('step1Title')} />
      <Text style={s.noteText}>{t('craneHint')}</Text>

      <Card s={s}>
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

  // ── STEP 2 — the fifteen pre-operation checks ─────────────────────────
  //
  // ONE ITEM PER BLOCK with its two answers beneath it, the shape the scaffold
  // inspection settled on: a right-aligned answer strip beside a wrapping label
  // is unreadable at arm's length outdoors.
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />
      <Text style={s.noteText}>{t('preOpHint')}</Text>
      <Text style={s.noteText}>
        {t('answeredOf')
          .replace('{n}', String(preOpAnswered))
          .replace('{m}', String(PRE_OP_CHECKLIST_ITEMS.length))}
      </Text>

      {PRE_OP_CHECKLIST_ITEMS.map((item, i) => (
        <Card s={s} key={item.key}>
          <Text style={s.reviewLabel}>
            {t('itemOf')
              .replace('{n}', String(i + 1))
              .replace('{m}', String(PRE_OP_CHECKLIST_ITEMS.length))}
          </Text>
          <Text style={s.question}>{item.label}</Text>
          <View style={s.chipWrap}>
            {CONFIRM_OPTIONS.map((opt) => (
              <Chip
                key={opt.label}
                label={opt.label}
                selected={preOpChecklist[item.key] === opt.value}
                onPress={() => setPreOp(item.key, opt.value)}
              />
            ))}
          </View>
        </Card>
      ))}
    </View>
  );

  // ── STEP 3 — the lift log ─────────────────────────────────────────────
  const renderStep3 = () => (
    <View>
      <StepHeader title={t('step3Title')} />
      <Text style={s.noteText}>{t('liftHint')}</Text>

      {loadEntries.map((row, index) => (
        <Card s={s} key={`lift-${index}`}>
          <View style={s.rowHead}>
            <Text style={s.reviewLabel}>
              {t('liftOf').replace('{n}', String(index + 1)).replace('{m}', String(loadEntries.length))}
            </Text>
            <Pressable
              style={s.rowRemove}
              accessibilityRole="button"
              accessibilityLabel={t('removeLift')}
              onPress={() => removeLoadEntry(index)}
            >
              <Trash2 size={20} strokeWidth={2} color={outdoor.danger} />
            </Pressable>
          </View>

          <TimeField
            s={s}
            label={t('fTime')}
            placeholder={t('phTime')}
            value={row.time}
            clearLabel={t('dateClear')}
            doneLabel={t('dateDone')}
            onChange={(v) => setLiftField(index, 'time', v)}
          />

          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('fDescription')}</Text>
            <TextInput
              style={s.input}
              value={row.description}
              onChangeText={(v) => setLiftField(index, 'description', v)}
              placeholder={t('phDescription')}
              placeholderTextColor={outdoor.textDim}
            />
          </View>

          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('fLoadWeight')}</Text>
            <TextInput
              style={s.input}
              value={row.load_weight}
              onChangeText={(v) => setLiftField(index, 'load_weight', v)}
              placeholder={t('phNumber')}
              placeholderTextColor={outdoor.textDim}
              keyboardType="numeric"
            />
          </View>

          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('fRadius')}</Text>
            <TextInput
              style={s.input}
              value={row.radius}
              onChangeText={(v) => setLiftField(index, 'radius', v)}
              placeholder={t('phNumber')}
              placeholderTextColor={outdoor.textDim}
              keyboardType="numeric"
            />
          </View>
        </Card>
      ))}

      <Pressable style={s.secondaryBtn} accessibilityRole="button" onPress={addLoadEntry}>
        <Plus size={22} strokeWidth={2.5} color={outdoor.text} />
        <Text style={s.secondaryBtnText}>{t('addLift')}</Text>
      </Pressable>
    </View>
  );

  // ── STEP 4 — review and sign ──────────────────────────────────────────
  const renderStep4 = () => {
    const unanswered = PRE_OP_CHECKLIST_ITEMS.length - preOpAnswered;
    return (
      <View>
        <StepHeader title={t('step4Title')} />
        <Text style={s.noteText}>{t('reviewHeading')}</Text>

        <Card s={s}>
          <Text style={s.reviewLabel}>{t('reviewCrane')}</Text>
          {DETAIL_FIELDS.map((f) => (
            <View key={f.key} style={s.reviewRow}>
              <Text style={s.reviewLabel}>{t(f.labelKey)}</Text>
              <Text style={s.reviewValue}>
                {String(details[f.key] || '').trim() || t('notRecorded')}
              </Text>
            </View>
          ))}
        </Card>

        <Card s={s} style={unanswered > 0 ? s.cardWarn : undefined}>
          <Text style={s.reviewLabel}>{t('reviewPreOp')}</Text>
          <Text style={s.reviewValue}>
            {unanswered > 0
              ? t('reviewUnanswered').replace('{n}', String(unanswered))
              : t('reviewAllAnswered').replace('{m}', String(PRE_OP_CHECKLIST_ITEMS.length))}
          </Text>
        </Card>

        <Card s={s}>
          <Text style={s.reviewLabel}>{t('reviewLifts')}</Text>
          <Text style={s.reviewValue}>
            {filledLifts > 0
              ? t(`liftCount_${filledLifts === 1 ? 'one' : 'other'}`)
                .replace('{n}', String(filledLifts))
              : t('reviewNothingYet')}
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
      /* crane_operations is IMMEDIATE — the server locks on `submitted` alone
         — so an unsigned submit must be UNREACHABLE, not merely warned about.
         The handler keeps its guard as a backstop. */
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
    rowHead: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      gap: spacing.sm,
    },
    rowRemove: {
      minWidth: touchTarget.min, minHeight: touchTarget.min,
      alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.full,
    },
  });
}
