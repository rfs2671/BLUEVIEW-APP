import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  View, Text, StyleSheet, Pressable, TextInput,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { AlertTriangle, Check, Plus, Trash2 } from 'lucide-react-native';
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
import {
  SOIL_TYPE_OPTIONS, PROTECTION_SYSTEM_OPTIONS, CONDITION_FLAGS,
  EMPTY_DETAILS, EMPTY_ADJACENT_BUILDING, calcDelta, isOverThreshold,
  thresholdStatusIsMeaningful, filledBuildingCount, detailsFromData,
  unnamedBuildings, incompleteSteps as computeIncomplete, draftBody,
} from '../../src/utils/excavationMonitoringModel';
import { useT } from '../../src/i18n';
import { spacing, borderRadius, outdoor, touchTarget } from '../../src/styles/theme';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';

/**
 * EXCAVATION MONITORING LOG — the cut and what it is doing to the buildings
 * beside it, on the shared stepper.
 *
 * FOUR STEPS, in the order the filed document prints them: the excavation, the
 * adjacent structures, vibration and conditions, then review and sign. The
 * chrome is LogbookStepper's — nothing about the header, pips, lock bar or
 * footer is decided here.
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
 * compressUnderCap. NOT CARRIED, because this form builds no roster: nothing
 * here reads /checkins.
 *
 * THE TWO DERIVED VALUES — per-building `delta` and
 * `vibration_over_threshold` — are computed by draftBody and nowhere else, so
 * the autosave, the flush and the submit all write the same payload. See
 * excavationMonitoringModel for what the old split cost.
 *
 * THE PAYLOAD IS UNCHANGED — the same nine top-level keys
 * backend/server.py:13349 renders.
 */
const LOG_TYPE = 'excavation_monitoring';
const TOTAL_STEPS = 4;

export default function ExcavationMonitoringLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const t = useT('excavationMonitoring');
  const tFinalize = useT('finalize');
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave } = useCpProfile();

  const s = useMemo(() => buildStyles(), []);

  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [step, setStep] = useState(1);
  const [locked, setLocked] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  const [details, setDetails] = useState(EMPTY_DETAILS);
  const [adjacentBuildings, setAdjacentBuildings] = useState([EMPTY_ADJACENT_BUILDING()]);

  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date }),
    [projectId, date],
  );

  // The body as of RIGHT NOW, for the debounced autosave and the save path.
  // State read inside a timer is the value captured when the timer was set,
  // which is one keystroke stale.
  const bodyRef = useRef({ details, adjacentBuildings });
  useEffect(() => {
    bodyRef.current = { details, adjacentBuildings };
  }, [details, adjacentBuildings]);

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
        data: draftBody(b.details, b.adjacentBuildings),
        cp_signature: cpSignature,
        cp_name: cpName,
      }).catch(() => {});
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, details, adjacentBuildings, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const b = bodyRef.current;
      await writeDraft(_key, {
        data: draftBody(b.details, b.adjacentBuildings),
        cp_signature: cpSignature,
        cp_name: cpName,
      });
    } catch (_e) { /* best-effort; the next change retries */ }
  }, [locked, _key, cpSignature, cpName]);

  const applyLoaded = useCallback((d) => {
    setDetails(detailsFromData(d));
    if (Array.isArray(d.adjacent_buildings) && d.adjacent_buildings.length > 0) {
      setAdjacentBuildings(d.adjacent_buildings);
    }
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    // THE LOCK IS RE-DERIVED ON EVERY LOAD — device round 5. `locked` could
    // only ever be set TRUE: no path set it back, so once a log was filed the
    // screen stayed read-only for the life of the mount. After an amendment
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
      // doc, which would load yesterday's readings onto today's screen and file
      // today's signature against them.
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
  const toggleFlag = (key) => setDetails((p) => ({ ...p, [key]: !p[key] }));
  const setBuildingField = (index, field, value) => setAdjacentBuildings(
    (p) => p.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
  );
  const addBuilding = () => setAdjacentBuildings((p) => [...p, EMPTY_ADJACENT_BUILDING()]);
  const removeBuilding = (index) => setAdjacentBuildings((p) => p.filter((_, i) => i !== index));

  // ── Save ──────────────────────────────────────────────────────────────
  /**
   * Local draft first, server push best-effort. Returns the doc id, `null`
   * when it saved locally with no server id yet (the offline path), or
   * `undefined` when the server REFUSED — which is not offline and must not
   * freeze.
   */
  const persistAndPush = async (submitStatus) => {
    const b = bodyRef.current;
    const filing = submitStatus === 'submitted';
    // AN ABANDONED ROW IS NOT A MONITORING POINT. On SUBMIT the table is
    // trimmed to the rows that say something — the same rule all three
    // renderers already drop rows by, so what is filed and what is printed are
    // the same table. A DRAFT KEEPS EVERYTHING.
    const data = draftBody(b.details, b.adjacentBuildings, { forFiling: filing });
    // What he signed is what he sees.
    if (filing && data.adjacent_buildings.length !== b.adjacentBuildings.length) {
      setAdjacentBuildings(data.adjacent_buildings.length > 0
        ? data.adjacent_buildings : [EMPTY_ADJACENT_BUILDING()]);
    }

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
      // REFUSAL IS NOT OFFLINE. excavation_monitoring is an IMMEDIATE type, so
      // a submitted push IS the finalize — a 4xx here is the server judging the
      // log, not failing to reach it. Freezing on a judgement would tell the CP
      // it was filed, make the draft immutable so he could not fix what was
      // refused, and leave nothing pending for the drain to retry.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      if (refused && submitStatus === 'submitted') {
        const code = finalizeErrorCode(pushErr);
        console.warn('Excavation log REFUSED by the server:', status, code);
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        // 5xx — the server FAILED rather than judged. Retryable, and it must
        // not be announced as filed.
        console.warn('Excavation log push FAILED server-side:', status || pushErr?.message);
        await markPending(_key);
        toast.error(tFinalize('errorTitle'), gateCopy(null));
        return undefined;
      }
      await markPending(_key);
      console.warn('Excavation log push deferred (will sync on reconnect):', pushErr?.message);
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
   * THE one action. excavation_monitoring is an IMMEDIATE log: THE SIGNATURE IS
   * THE FREEZE. Submitting finalizes the record in one action and it is never
   * reopened — a later reading is a NEW discrete log, and a correction is an
   * amendment.
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
    // A MONITORING POINT WITH NO ADDRESS NAMES NO BUILDING, and it is dropped
    // at filing either way — this is what stops the dropping being SILENT. A
    // CP who typed a baseline and a current reading into a row and then signed
    // would otherwise get the record back with that row simply gone.
    //
    // BLOCKING AT SUBMIT, NOT ON NEXT. A half-filled row is ordinary work: the
    // readings are taken at the wall and the address is often typed after. It
    // is only at the moment of FILING that a reading against no building
    // becomes vibration data nobody can act on.
    const unnamed = unnamedBuildings(adjacentBuildings);
    if (unnamed.length > 0) {
      setStep(2);
      toast.warning(
        t('unnamedPointTitle'),
        t('unnamedPointBody').replace(
          '{rows}',
          unnamed.map((u) => {
            const held = [u.baseline, u.current].filter(Boolean).join(' / ');
            return held ? `${u.row} (${held})` : String(u.row);
          }).join('; '),
        ),
      );
      return;
    }
    setSigning(true);
    try {
      const savedId = await persistAndPush('submitted');
      // `undefined` = refused or failed, already reported. Nothing may be
      // frozen or announced on a log the server would not take. `null` is
      // different: saved LOCALLY with no server id, which is the offline path
      // and DOES freeze — a reading taken in a hole with no signal must still
      // hold.
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

  const incomplete = computeIncomplete({ details, adjacentBuildings, cpSignature })
    .filter((n) => n !== step);
  const filledPoints = filledBuildingCount(adjacentBuildings);
  const overThreshold = isOverThreshold(details.vibration_threshold, details.vibration_current);
  const thresholdMeaningful = thresholdStatusIsMeaningful(
    details.vibration_threshold, details.vibration_current,
  );

  // ── STEP 1 — the excavation ───────────────────────────────────────────
  const renderStep1 = () => (
    <View>
      <StepHeader title={t('step1Title')} />
      <Text style={s.noteText}>{t('cutHint')}</Text>

      <Card s={s}>
        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fDepth')}</Text>
          <TextInput
            style={s.input}
            value={details.excavation_depth || ''}
            onChangeText={(v) => setDetail('excavation_depth', v)}
            placeholder={t('phField')}
            placeholderTextColor={outdoor.textDim}
            keyboardType="numeric"
          />
        </View>

        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fSoilType')}</Text>
          <View style={s.chipWrap}>
            {SOIL_TYPE_OPTIONS.map((opt) => (
              <Chip
                key={opt}
                label={opt}
                selected={details.soil_type === opt}
                onPress={() => setDetail('soil_type', details.soil_type === opt ? '' : opt)}
              />
            ))}
          </View>
        </View>

        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fProtection')}</Text>
          <View style={s.chipWrap}>
            {PROTECTION_SYSTEM_OPTIONS.map((opt) => (
              <Chip
                key={opt}
                label={opt}
                selected={details.protection_system === opt}
                onPress={() => setDetail(
                  'protection_system', details.protection_system === opt ? '' : opt,
                )}
              />
            ))}
          </View>
        </View>
      </Card>
    </View>
  );

  // ── STEP 2 — the adjacent structures ──────────────────────────────────
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />
      <Text style={s.noteText}>{t('pointsHint')}</Text>

      {adjacentBuildings.map((row, index) => {
        // Shown live, computed by the SAME function that writes it into the
        // payload — the number on screen is the number that files.
        const delta = calcDelta(row.baseline_reading, row.current_reading);
        return (
          <Card s={s} key={`bldg-${index}`}>
            <View style={s.rowHead}>
              <Text style={s.reviewLabel}>
                {t('pointOf').replace('{n}', String(index + 1)).replace('{m}', String(adjacentBuildings.length))}
              </Text>
              <Pressable
                style={s.rowRemove}
                accessibilityRole="button"
                accessibilityLabel={t('removePoint')}
                onPress={() => removeBuilding(index)}
              >
                <Trash2 size={20} strokeWidth={2} color={outdoor.danger} />
              </Pressable>
            </View>

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('fAddress')}</Text>
              <TextInput
                style={s.input}
                value={row.address}
                onChangeText={(v) => setBuildingField(index, 'address', v)}
                placeholder={t('phAddress')}
                placeholderTextColor={outdoor.textDim}
              />
            </View>

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('fBaseline')}</Text>
              <TextInput
                style={s.input}
                value={row.baseline_reading}
                onChangeText={(v) => setBuildingField(index, 'baseline_reading', v)}
                placeholder={t('phReading')}
                placeholderTextColor={outdoor.textDim}
                keyboardType="numeric"
              />
            </View>

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('fCurrent')}</Text>
              <TextInput
                style={s.input}
                value={row.current_reading}
                onChangeText={(v) => setBuildingField(index, 'current_reading', v)}
                placeholder={t('phReading')}
                placeholderTextColor={outdoor.textDim}
                keyboardType="numeric"
              />
            </View>

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('fMovement')}</Text>
              <View style={s.readOnlyValue}>
                <Text style={s.readOnlyText}>{delta || t('notRecorded')}</Text>
                <Text style={s.noteText}>{t('movementDerived')}</Text>
              </View>
            </View>
          </Card>
        );
      })}

      <Pressable style={s.secondaryBtn} accessibilityRole="button" onPress={addBuilding}>
        <Plus size={22} strokeWidth={2.5} color={outdoor.text} />
        <Text style={s.secondaryBtnText}>{t('addPoint')}</Text>
      </Pressable>
    </View>
  );

  // ── STEP 3 — vibration and conditions ─────────────────────────────────
  const renderStep3 = () => (
    <View>
      <StepHeader title={t('step3Title')} />
      <Text style={s.noteText}>{t('vibrationHint')}</Text>

      <Card s={s} style={overThreshold ? s.cardWarn : undefined}>
        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fThreshold')}</Text>
          <TextInput
            style={s.input}
            value={details.vibration_threshold || ''}
            onChangeText={(v) => setDetail('vibration_threshold', v)}
            placeholder={t('phReading')}
            placeholderTextColor={outdoor.textDim}
            keyboardType="numeric"
          />
        </View>

        <View style={s.fieldBlock}>
          <Text style={s.reviewLabel}>{t('fCurrentReading')}</Text>
          <TextInput
            style={[s.input, overThreshold && s.inputRequired]}
            value={details.vibration_current || ''}
            onChangeText={(v) => setDetail('vibration_current', v)}
            placeholder={t('phReading')}
            placeholderTextColor={outdoor.textDim}
            keyboardType="numeric"
          />
        </View>

        {/* The reading is only a FINDING alongside a threshold. Below both
            readings, so the CP reads the numbers and then what they mean. */}
        {overThreshold && (
          <View style={s.warnRow}>
            <AlertTriangle size={22} strokeWidth={2} color={outdoor.warn} />
            <View style={s.warnBody}>
              <Text style={s.warnTitle}>{t('overThresholdTitle')}</Text>
              <Text style={s.warnText}>{t('overThresholdBody')}</Text>
            </View>
          </View>
        )}
      </Card>

      {/* TWO REAL BOOLEANS, not a three-state checklist: both renderers print a
          bare Yes/No for these and have no "not recorded" branch to print, so
          the control has exactly the two states the document has. */}
      <Card s={s}>
        <Text style={s.reviewLabel}>{t('conditionsLabel')}</Text>
        {CONDITION_FLAGS.map((f) => (
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
            <Text style={s.toggleText}>{t(f.labelKey)}</Text>
          </Pressable>
        ))}
      </Card>
    </View>
  );

  // ── STEP 4 — review and sign ──────────────────────────────────────────
  const renderStep4 = () => (
    <View>
      <StepHeader title={t('step4Title')} />
      <Text style={s.noteText}>{t('reviewHeading')}</Text>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewCut')}</Text>
        <View style={s.reviewRow}>
          <Text style={s.reviewLabel}>{t('fDepth')}</Text>
          <Text style={s.reviewValue}>
            {String(details.excavation_depth || '').trim() || t('notRecorded')}
          </Text>
        </View>
        <View style={s.reviewRow}>
          <Text style={s.reviewLabel}>{t('fSoilType')}</Text>
          <Text style={s.reviewValue}>{details.soil_type || t('notRecorded')}</Text>
        </View>
        <View style={s.reviewRow}>
          <Text style={s.reviewLabel}>{t('fProtection')}</Text>
          <Text style={s.reviewValue}>{details.protection_system || t('notRecorded')}</Text>
        </View>
      </Card>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewPoints')}</Text>
        <Text style={s.reviewValue}>
          {filledPoints > 0
            ? t(`pointCount_${filledPoints === 1 ? 'one' : 'other'}`)
              .replace('{n}', String(filledPoints))
            : t('reviewNothingYet')}
        </Text>
      </Card>

      {/* The status line, exactly as the renderers decide it: a bare "within
          threshold" over a missing reading is a finding the CP never made. */}
      <Card s={s} style={thresholdMeaningful && overThreshold ? s.cardWarn : undefined}>
        <Text style={s.reviewLabel}>{t('reviewVibration')}</Text>
        <Text style={s.reviewValue}>
          {thresholdMeaningful
            ? (overThreshold ? t('overThresholdTitle') : t('withinThreshold'))
            : t('notRecorded')}
        </Text>
      </Card>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewConditions')}</Text>
        {CONDITION_FLAGS.map((f) => (
          <View key={f.key} style={s.reviewRow}>
            <Text style={s.reviewLabel}>{t(f.labelKey)}</Text>
            <Text style={s.reviewValue}>{details[f.key] ? t('yes') : t('no')}</Text>
          </View>
        ))}
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
      /* excavation_monitoring is IMMEDIATE — the server locks on `submitted`
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
    warnRow: {
      flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm,
    },
    toggleBoxOn: { borderColor: outdoor.okBorder },
  });
}
