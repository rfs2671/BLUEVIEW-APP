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
  DETAIL_FIELDS, WEATHER_OPTIONS, FORMWORK_ITEMS, CONFIRM_OPTIONS,
  EMPTY_DETAILS, EMPTY_SLUMP_TEST, applySlumpResult, slumpTestsForFiling,
  filledSlumpCount, formworkRecordedCount, detailsFromData,
  incompleteSteps as computeIncomplete, draftBody,
} from '../../src/utils/concreteOperationsModel';
import { applyChecklistAnswer } from '../../src/utils/checklistMap';
import { useT } from '../../src/i18n';
import { spacing, borderRadius, outdoor, touchTarget } from '../../src/styles/theme';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';

/**
 * CONCRETE OPERATIONS LOG — the pour, on the shared stepper.
 *
 * FOUR STEPS, in the order the filed document prints them: the pour, the slump
 * tests, the formwork inspection, then review and sign. The chrome is
 * LogbookStepper's — nothing about the header, pips, lock bar or footer is
 * decided here, so a port cannot quietly lose the 56pt target or the single
 * primary action.
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
 * compressUnderCap. There is no photo on the concrete log — no field, no
 * capture, nothing to persist — so importing them would be dead weight, not
 * safety.
 *
 * NOT CARRIED, because this form builds no roster: nothing here reads
 * /checkins. The empty-roster trap has no surface to appear on.
 *
 * THERE IS NO SAVE DRAFT BUTTON. Every change autosaves to the local draft;
 * the one primary action is Sign and file.
 *
 * THE PAYLOAD IS UNCHANGED — the same eight top-level keys
 * backend/server.py:13411 renders. See concreteOperationsModel.
 */
const LOG_TYPE = 'concrete_operations';
const TOTAL_STEPS = 4;

export default function ConcreteOperationsLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const t = useT('concreteOperations');
  const tFinalize = useT('finalize');
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave } = useCpProfile();

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
  const [slumpTests, setSlumpTests] = useState([EMPTY_SLUMP_TEST()]);
  const [formworkChecklist, setFormworkChecklist] = useState({});

  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date }),
    [projectId, date],
  );

  // The body as of RIGHT NOW, for the debounced autosave and the save path.
  // State read inside a timer is the value captured when the timer was set,
  // which is one keystroke stale.
  const bodyRef = useRef({ details, slumpTests, formworkChecklist });
  useEffect(() => {
    bodyRef.current = { details, slumpTests, formworkChecklist };
  }, [details, slumpTests, formworkChecklist]);

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
        data: draftBody(b.details, b.slumpTests, b.formworkChecklist),
        cp_signature: cpSignature,
        cp_name: cpName,
      })
        .then((_ok) => setAutosaveFailed(!_ok))
        .catch(() => setAutosaveFailed(true));
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, details, slumpTests, formworkChecklist, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const b = bodyRef.current;
      const _ok = await writeDraft(_key, {
        data: draftBody(b.details, b.slumpTests, b.formworkChecklist),
        cp_signature: cpSignature,
        cp_name: cpName,
      });
      setAutosaveFailed(!_ok);
    } catch (_e) { setAutosaveFailed(true); }
  }, [locked, _key, cpSignature, cpName]);

  const applyLoaded = useCallback((d) => {
    setDetails(detailsFromData(d));
    if (Array.isArray(d.slump_tests) && d.slump_tests.length > 0) {
      setSlumpTests(d.slump_tests);
    }
    if (d.formwork_checklist && typeof d.formwork_checklist === 'object') {
      setFormworkChecklist(d.formwork_checklist);
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
      // doc, which would load yesterday's pour onto today's screen and file
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
  const setSlumpField = (index, field, value) => setSlumpTests(
    (p) => p.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
  );
  // applySlumpResult, NOT a spread: re-tapping the chosen result returns the
  // row to null — unrecorded, which both renderers print as nothing and never
  // as a Fail. A spread would have no way back to the seeded state.
  const setSlumpResult = (index, value) => setSlumpTests(
    (p) => p.map((row, i) => (i === index ? applySlumpResult(row, value) : row)),
  );
  const addSlumpTest = () => setSlumpTests((p) => [...p, EMPTY_SLUMP_TEST()]);
  const removeSlumpTest = (index) => setSlumpTests((p) => p.filter((_, i) => i !== index));
  // applyChecklistAnswer, NOT `!prev[key]`: the map is TRI-STATE on the filed
  // document — absent is "Not recorded", false is an explicit "No" — and the
  // old dot could not tell those apart. See src/utils/checklistMap.js.
  const setFormwork = (key, value) => setFormworkChecklist(
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
    // AN ABANDONED ROW IS NOT A RECORD. On SUBMIT the slump table is trimmed to
    // the rows that say something — the same rule both renderers already drop
    // rows by, so what is filed and what is printed are the same table.
    //
    // A DRAFT KEEPS EVERYTHING: a half-typed row the CP is still working on
    // must survive a save.
    const filed = submitStatus === 'submitted'
      ? slumpTestsForFiling(b.slumpTests) : b.slumpTests;
    // What he signed is what he sees.
    if (submitStatus === 'submitted' && filed.length !== b.slumpTests.length) {
      setSlumpTests(filed.length > 0 ? filed : [EMPTY_SLUMP_TEST()]);
    }
    const data = draftBody(b.details, filed, b.formworkChecklist);

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
      // BOTH HANDLES. A banner raised while offline was recorded against
      // the DRAFT KEY, because there was no server id yet — clearing only
      // by savedId left it up permanently.
      await clearFinalizeError(_key);
      if (savedId) await clearFinalizeError(savedId);
    } catch (pushErr) {
      // REFUSAL IS NOT OFFLINE. concrete_operations is an IMMEDIATE type, so a
      // submitted push IS the finalize — a 4xx here is the server judging the
      // log, not failing to reach it. Freezing on a judgement would tell the CP
      // it was filed, make the draft immutable so he could not fix what was
      // refused, and leave nothing pending for the drain to retry.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      if (refused && submitStatus === 'submitted') {
        const code = finalizeErrorCode(pushErr);
        console.warn('Concrete log REFUSED by the server:', status, code);
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        // 5xx — the server FAILED rather than judged. Retryable, and it must
        // not be announced as filed.
        console.warn('Concrete log push FAILED server-side:', status || pushErr?.message);
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
        console.warn('Concrete log push deferred but the LOCAL SAVE FAILED; not queued.');
        await recordFinalizeError(
          existingLogId || _key, 'LOCAL_SAVE_FAILED', _key, 'local');
        toast.error(tFinalize('localSaveFailedTitle'), tFinalize('localSaveFailed'));
        return undefined;
      }
      await markPending(_key);
      console.warn('Concrete log push deferred (will sync on reconnect):', pushErr?.message);
      // ON THIS DEVICE ONLY — the other half of the same banner. The local
      // write landed, so this log IS safe here and IS queued; what is not true
      // is that anyone else can see it. He is about to attest to a legal
      // record, and a toast saying "will sync" is gone before he has
      // finished reading it, so this goes up durably and comes down when the
      // drain succeeds (clearUnsyncedBanner in draftSync).
      await recordFinalizeError(
        existingLogId || _key, 'NOT_ON_SERVER', _key, 'unsynced');
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
   * THE one action. concrete_operations is an IMMEDIATE log: THE SIGNATURE IS
   * THE FREEZE. Submitting finalizes the pour record in one action and it is
   * never reopened — a later pour is a NEW log, and corrections go through the
   * amendment-as-child path.
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
      // and DOES freeze — a slab signed off below grade with no signal must
      // still hold.
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
    details, slumpTests, formworkChecklist, cpSignature,
  }).filter((n) => n !== step);
  const filledSlumps = filledSlumpCount(slumpTests);
  const formworkAnswered = formworkRecordedCount(formworkChecklist);

  // ── STEP 1 — the pour ─────────────────────────────────────────────────
  const renderStep1 = () => (
    <View>
      <StepHeader title={t('step1Title')} />
      <Text style={s.noteText}>{t('pourHint')}</Text>

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

        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fWeather')}</Text>
          <View style={s.chipWrap}>
            {WEATHER_OPTIONS.map((w) => (
              <Chip
                key={w}
                label={w}
                selected={details.weather_conditions === w}
                onPress={() => setDetail(
                  'weather_conditions', details.weather_conditions === w ? '' : w,
                )}
              />
            ))}
          </View>
        </View>
      </Card>
    </View>
  );

  // ── STEP 2 — the slump tests ──────────────────────────────────────────
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />
      <Text style={s.noteText}>{t('slumpHint')}</Text>

      {slumpTests.map((row, index) => (
        <Card s={s} key={`slump-${index}`}>
          <View style={s.rowHead}>
            <Text style={s.reviewLabel}>
              {t('slumpOf').replace('{n}', String(index + 1)).replace('{m}', String(slumpTests.length))}
            </Text>
            <Pressable
              style={s.rowRemove}
              accessibilityRole="button"
              accessibilityLabel={t('removeSlump')}
              onPress={() => removeSlumpTest(index)}
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
            onChange={(v) => setSlumpField(index, 'time', v)}
          />

          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('fSlumpValue')}</Text>
            <TextInput
              style={s.input}
              value={row.value}
              onChangeText={(v) => setSlumpField(index, 'value', v)}
              placeholder={t('phSlumpValue')}
              placeholderTextColor={outdoor.textDim}
              keyboardType="numeric"
            />
          </View>

          {/* Pass / Fail / neither. Tapping the chosen one clears it back to
              unrecorded — the state the row is seeded in, and the state both
              renderers print as nothing rather than as a Fail. */}
          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('fResult')}</Text>
            <View style={s.chipWrap}>
              <Chip
                label={t('resultPass')}
                selected={row.pass === true}
                onPress={() => setSlumpResult(index, true)}
              />
              <Chip
                label={t('resultFail')}
                selected={row.pass === false}
                onPress={() => setSlumpResult(index, false)}
              />
            </View>
          </View>
        </Card>
      ))}

      <Pressable style={s.secondaryBtn} accessibilityRole="button" onPress={addSlumpTest}>
        <Plus size={22} strokeWidth={2.5} color={outdoor.text} />
        <Text style={s.secondaryBtnText}>{t('addSlump')}</Text>
      </Pressable>
    </View>
  );

  // ── STEP 3 — the formwork ─────────────────────────────────────────────
  //
  // ONE ITEM PER BLOCK with its two answers beneath it, the shape the scaffold
  // inspection settled on: a right-aligned answer strip beside a wrapping label
  // is unreadable at arm's length outdoors.
  const renderStep3 = () => (
    <View>
      <StepHeader title={t('step3Title')} />
      <Text style={s.noteText}>{t('formworkHint')}</Text>
      <Text style={s.noteText}>
        {t('answeredOf')
          .replace('{n}', String(formworkAnswered))
          .replace('{m}', String(FORMWORK_ITEMS.length))}
      </Text>

      {FORMWORK_ITEMS.map((item) => (
        <Card s={s} key={item.key}>
          <Text style={s.question}>{item.label}</Text>
          <View style={s.chipWrap}>
            {CONFIRM_OPTIONS.map((opt) => (
              <Chip
                key={opt.label}
                label={opt.label}
                selected={formworkChecklist[item.key] === opt.value}
                onPress={() => setFormwork(item.key, opt.value)}
              />
            ))}
          </View>
        </Card>
      ))}
    </View>
  );

  // ── STEP 4 — review and sign ──────────────────────────────────────────
  const renderStep4 = () => {
    const unanswered = FORMWORK_ITEMS.length - formworkAnswered;
    return (
      <View>
        <StepHeader title={t('step4Title')} />
        <Text style={s.noteText}>{t('reviewHeading')}</Text>

        <Card s={s}>
          <Text style={s.reviewLabel}>{t('reviewPour')}</Text>
          {DETAIL_FIELDS.map((f) => (
            <View key={f.key} style={s.reviewRow}>
              <Text style={s.reviewLabel}>{t(f.labelKey)}</Text>
              <Text style={s.reviewValue}>
                {String(details[f.key] || '').trim() || t('notRecorded')}
              </Text>
            </View>
          ))}
          <View style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t('fWeather')}</Text>
            <Text style={s.reviewValue}>
              {details.weather_conditions || t('notRecorded')}
            </Text>
          </View>
        </Card>

        <Card s={s}>
          <Text style={s.reviewLabel}>{t('reviewSlumps')}</Text>
          <Text style={s.reviewValue}>
            {filledSlumps > 0
              ? t(`slumpCount_${filledSlumps === 1 ? 'one' : 'other'}`)
                .replace('{n}', String(filledSlumps))
              : t('reviewNothingYet')}
          </Text>
        </Card>

        <Card s={s} style={unanswered > 0 ? s.cardWarn : undefined}>
          <Text style={s.reviewLabel}>{t('reviewFormwork')}</Text>
          <Text style={s.reviewValue}>
            {unanswered > 0
              ? t('reviewUnanswered').replace('{n}', String(unanswered))
              : t('reviewAllAnswered').replace('{m}', String(FORMWORK_ITEMS.length))}
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
      /* concrete_operations is IMMEDIATE — the server locks on `submitted`
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
