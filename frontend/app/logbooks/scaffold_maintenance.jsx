import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  View, Text, StyleSheet, Pressable, TextInput,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
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
import { isOfflineError } from '../../src/utils/offlineState';
import LogbookStepper from '../../src/components/logbookStepper/LogbookStepper';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { Card, ChipBase, StepHeaderBase } from '../../src/components/logbookStepper/primitives';
import DateField from '../../src/components/logbookStepper/DateField';
import {
  GENERAL_INFO_FIELDS, SHED_TYPES, MAINTENANCE_QUESTIONS, ANSWER_OPTIONS,
  EMPTY_GENERAL_INFO, prefillFromScaffoldInfo, scaffoldInfoForSave,
  answeredCount, incompleteSteps as computeIncomplete, draftBody,
} from '../../src/utils/scaffoldMaintenanceModel';
import { useT } from '../../src/i18n';
import { spacing, borderRadius, typography, outdoor, touchTarget } from '../../src/styles/theme';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';

/**
 * SCAFFOLD MAINTENANCE LOG — the NYC DOB sidewalk-shed daily inspection, on the
 * shared stepper.
 *
 * THREE STEPS, as approved: the scaffold (8 fields + shed type, prefilled from
 * project memory), the 19 checks, then review and sign. The chrome is
 * LogbookStepper's — nothing about the header, pips, lock bar or footer is
 * decided here.
 *
 * WHAT CARRIED FORWARD from the reference (daily_jobsite.jsx), unchanged:
 *   draft lifecycle          readDraft / writeDraft / setDraftBackendId /
 *                            markPending / clearPending / markFinalized
 *   signature client guard   no signature, no file — and it says why
 *   gateCopy                 the server names the condition, the client owns
 *                            the wording; the server's English never renders
 *   recordFinalizeError      a foreground refusal leaves the same durable
 *                            banner a background one does
 *
 * NOT CARRIED, because this form has no camera: persistPhoto and
 * compressUnderCap. There is no photo on the shed inspection. See the PR note.
 *
 * THE PAYLOAD IS UNCHANGED — `{ general_info, answers }`, the same nine info
 * keys and nineteen answer keys backend/server.py:13321 renders.
 *
 * drawings_on_site IS A QUESTION AND NOTHING ELSE. It is not a general_info
 * key, nothing seeds it, and it appears in this screen only as one of the 19.
 * See scaffoldMaintenanceModel for the whole account.
 */
const LOG_TYPE = 'scaffold_maintenance';
const TOTAL_STEPS = 3;

export default function ScaffoldMaintenanceLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const t = useT('scaffoldMaintenance');
  const tFinalize = useT('finalize');
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave } = useCpProfile();

  const s = useMemo(() => buildStyles(), []);

  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [step, setStep] = useState(1);
  const [locked, setLocked] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  const [generalInfo, setGeneralInfo] = useState(EMPTY_GENERAL_INFO);
  const [answers, setAnswers] = useState({});

  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date }),
    [projectId, date],
  );

  const bodyRef = useRef({ generalInfo, answers });
  useEffect(() => { bodyRef.current = { generalInfo, answers }; }, [generalInfo, answers]);

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
  useEffect(() => {
    if (loading || locked) return undefined;
    const h = setTimeout(() => {
      const b = bodyRef.current;
      writeDraft(_key, {
        data: draftBody(b.generalInfo, b.answers),
        cp_signature: cpSignature,
        cp_name: cpName,
      }).catch(() => {});
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, generalInfo, answers, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const b = bodyRef.current;
      await writeDraft(_key, {
        data: draftBody(b.generalInfo, b.answers),
        cp_signature: cpSignature,
        cp_name: cpName,
      });
    } catch (_e) { /* best-effort */ }
  }, [locked, _key, cpSignature, cpName]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      // LOCAL-FIRST. A local draft wins over both the project-memory prefill
      // and the server copy, so an offline CP reopens to what he filled.
      const draft = await readDraft(_key);
      if (draft?.data && Object.keys(draft.data).length) {
        if (draft.finalized) { setLocked(true); markFinalized(_key); }
        setExistingLogId(draft.backend_id || null);
        if (draft.data.general_info) setGeneralInfo(draft.data.general_info);
        if (draft.data.answers) setAnswers(draft.data.answers);
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        setLoading(false);
        return;
      }

      const [scaffoldInfo, existingLogs] = await Promise.all([
        logbooksAPI.getScaffoldInfo(projectId).catch(() => ({})),
        logbooksAPI.getByProject(projectId, LOG_TYPE, date).catch(() => []),
      ]);

      // PREFILLED FROM PROJECT MEMORY. The shed does not change from day to
      // day; retyping the erector's name and the permit number every morning
      // is how those fields end up blank.
      setGeneralInfo(prefillFromScaffoldInfo(scaffoldInfo));

      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find((l) => !l.is_locked) || arr[0] || null;
      if (existing) {
        if (existing.is_locked) { setLocked(true); markFinalized(_key); }
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.general_info) setGeneralInfo(d.general_info);
        if (d.answers) setAnswers(d.answers);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [_key, projectId, date, setCpName, setCpSignature]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const setField = (key, value) => setGeneralInfo((p) => ({ ...p, [key]: value }));
  const setAnswer = (key, value) => setAnswers((p) => ({ ...p, [key]: value }));

  // ── Save ──────────────────────────────────────────────────────────────
  const persistAndPush = async (submitStatus) => {
    const b = bodyRef.current;
    const data = draftBody(b.generalInfo, b.answers);

    // Project memory, so tomorrow's inspection opens prefilled.
    // update_scaffold_info writes every key it is HANDED, so an undefined key
    // would be stored as null over whatever the project already had. Dropping
    // undefined keys leaves them untouched.
    await logbooksAPI.saveScaffoldInfo(
      projectId, scaffoldInfoForSave(b.generalInfo),
    ).catch(() => {});

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
      // REFUSAL IS NOT OFFLINE — see the same note in osha_log.jsx.
      // scaffold_maintenance is an IMMEDIATE type, so a submitted push IS the
      // finalize and a 4xx is the server JUDGING the inspection.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      if (refused && submitStatus === 'submitted') {
        const code = finalizeErrorCode(pushErr);
        console.warn('Scaffold inspection REFUSED by the server:', status, code);
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        console.warn('Scaffold inspection push FAILED server-side:', status || pushErr?.message);
        await markPending(_key);
        toast.error(tFinalize('errorTitle'), gateCopy(null));
        return undefined;
      }
      await markPending(_key);
      console.warn('Scaffold inspection push deferred (will sync on reconnect):', pushErr?.message);
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
   * scaffold_maintenance is an IMMEDIATE log: THE SIGNATURE IS THE FREEZE.
   * Submitting finalizes the inspection in one action and it is never
   * reopened — a post-alteration re-inspection is a NEW log, and corrections
   * go through the amendment-as-child path.
   */
  const handleSubmitAndSign = async () => {
    if (signing) return;
    // SIGNATURE CLIENT GUARD — see osha_log.jsx.
    if (!cpSignature) {
      setStep(TOTAL_STEPS);
      toast.warning(t('signatureRequiredTitle'), t('signatureRequiredBody'));
      return;
    }
    setSigning(true);
    try {
      const savedId = await persistAndPush('submitted');
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

  const incomplete = computeIncomplete({ generalInfo, answers, cpSignature })
    .filter((n) => n !== step);
  const answered = answeredCount(answers);
  const totalQuestions = MAINTENANCE_QUESTIONS.length;

  // ── STEP 1 — the scaffold ─────────────────────────────────────────────
  const renderStep1 = () => (
    <View>
      <StepHeader title={t('step1Title')} />
      <Text style={s.noteText}>{t('shedHint')}</Text>

      <Card s={s}>
        {GENERAL_INFO_FIELDS.map((f) => (f.kind === 'date' ? (
          <DateField
            key={f.key}
            s={s}
            label={t(f.labelKey)}
            placeholder={t('phDate')}
            value={generalInfo[f.key] || ''}
            today={date}
            clearLabel={t('dateClear')}
            doneLabel={t('dateDone')}
            onChange={(v) => setField(f.key, v)}
          />
        ) : (
          <View key={f.key} style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t(f.labelKey)}</Text>
            <TextInput
              style={s.input}
              value={generalInfo[f.key] || ''}
              onChangeText={(v) => setField(f.key, v)}
              placeholder={t('phField')}
              placeholderTextColor={outdoor.textDim}
              keyboardType={f.kind === 'phone' ? 'phone-pad'
                : (f.kind === 'number' ? 'number-pad' : 'default')}
            />
          </View>
        )))}

        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fShedType')}</Text>
          <View style={s.chipWrap}>
            {SHED_TYPES.map((type) => (
              <Chip
                key={type}
                label={type}
                selected={generalInfo.shed_type === type}
                onPress={() => setField('shed_type', type)}
              />
            ))}
          </View>
        </View>
      </Card>
    </View>
  );

  // ── STEP 2 — the 19 checks ────────────────────────────────────────────
  //
  // ONE QUESTION PER BLOCK with its three answers beneath it, rather than a
  // dense table. The question text runs long ("Are the guardrails and toe
  // boards secured at all places where required?") and a right-aligned answer
  // strip beside it is unreadable at arm's length outdoors.
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />
      <Text style={s.noteText}>{t('checksHint')}</Text>
      <Text style={s.noteText}>
        {t('answeredOf').replace('{n}', String(answered)).replace('{m}', String(totalQuestions))}
      </Text>

      {MAINTENANCE_QUESTIONS.map((q, i) => (
        <Card s={s} key={q.key}>
          <Text style={s.reviewLabel}>
            {t('questionOf').replace('{n}', String(i + 1)).replace('{m}', String(totalQuestions))}
          </Text>
          <Text style={s.question}>{q.label}</Text>
          <View style={s.chipWrap}>
            {ANSWER_OPTIONS.map((opt) => (
              <Chip
                key={opt}
                label={opt}
                selected={answers[q.key] === opt}
                onPress={() => setAnswer(q.key, opt)}
              />
            ))}
          </View>
        </Card>
      ))}
    </View>
  );

  // ── STEP 3 — review and sign ──────────────────────────────────────────
  const renderStep3 = () => {
    const unanswered = totalQuestions - answered;
    return (
      <View>
        <StepHeader title={t('step3Title')} />
        <Text style={s.noteText}>{t('reviewHeading')}</Text>

        <Card s={s}>
          <Text style={s.reviewLabel}>{t('reviewShed')}</Text>
          {GENERAL_INFO_FIELDS.map((f) => (
            <View key={f.key} style={s.reviewRow}>
              <Text style={s.reviewLabel}>{t(f.labelKey)}</Text>
              <Text style={s.reviewValue}>
                {String(generalInfo[f.key] || '').trim() || t('notRecorded')}
              </Text>
            </View>
          ))}
          <View style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t('fShedType')}</Text>
            <Text style={s.reviewValue}>{generalInfo.shed_type || t('notRecorded')}</Text>
          </View>
        </Card>

        <Card s={s} style={unanswered > 0 ? s.cardWarn : undefined}>
          <Text style={s.reviewLabel}>{t('reviewChecks')}</Text>
          <Text style={s.reviewValue}>
            {unanswered > 0
              ? t('reviewUnanswered').replace('{n}', String(unanswered))
              : t('reviewAllAnswered').replace('{m}', String(totalQuestions))}
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
      /* scaffold_maintenance is IMMEDIATE — the server locks on `submitted`
         alone — so an unsigned submit must be UNREACHABLE, not merely warned
         about. The handler keeps its guard as a backstop. */
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
    reviewRow: {
      gap: spacing.xs / 2,
      paddingVertical: spacing.xs,
    },
    shedBtn: {
      minHeight: touchTarget.min,
      paddingHorizontal: spacing.lg,
      borderRadius: borderRadius.full,
    },
    shedBtnText: { fontSize: typography.sizes.md, color: outdoor.text },
  });
}
