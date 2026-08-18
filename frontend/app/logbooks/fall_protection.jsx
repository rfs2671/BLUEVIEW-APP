import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  View, Text, StyleSheet, Pressable, TextInput, Image,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Plus, Trash2, Camera } from 'lucide-react-native';
import * as ImagePicker from 'expo-image-picker';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import {
  draftKey, readDraft, writeDraft, setDraftBackendId,
  markPending, clearPending, markFinalized,
  persistActivityPhotos, uploadPendingActivityPhotos, hasPendingPhotoUploads,
} from '../../src/utils/logbookDrafts';
import compressUnderCap from '../../src/utils/compressPhoto';
import { freezeIfImmediate } from '../../src/utils/logbookTiming';
import { finalizeErrorCode, clearFinalizeError, recordFinalizeError } from '../../src/utils/draftSync';
import { isOfflineError } from '../../src/utils/offlineState';
import LogbookStepper from '../../src/components/logbookStepper/LogbookStepper';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { Card, ChipBase, StepHeaderBase } from '../../src/components/logbookStepper/primitives';
import DateField from '../../src/components/logbookStepper/DateField';
import {
  EQUIPMENT_TYPES, RESULTS, EMPTY_ROW, buildRowsFromCheckins, isAdverse,
  applyResult, applyImpactLoaded, rowHasContent, rowsForFiling, unfilableRows,
  rowsMissingAdverseDetail, impactLoadedNotRemoved,
  incompleteSteps as computeIncomplete, draftBody,
} from '../../src/utils/fallProtectionModel';
import { useT } from '../../src/i18n';
import { spacing, borderRadius, outdoor, touchTarget } from '../../src/styles/theme';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';

/**
 * THE FALL PROTECTION EQUIPMENT LOG — on the shared stepper.
 *
 * WHAT THIS LOG IS. OSHA 1926.502(d)(21) mandates the INSPECTION, not a
 * written record of each one; the documented inspection comes from ANSI Z359,
 * an industry consensus standard. The app says so on the review step and both
 * renderers print it on the document, from ONE string
 * (FALL_PROTECTION_NOTICE, backend/server.py) so it cannot say two things.
 *
 * TWO STEPS: the equipment, then review and sign. Chrome is LogbookStepper's.
 *
 * WHAT THE SUBMIT GATE REFUSES, and it is more than the register's:
 *   a row that names nobody          — the Group 1 rule, reused not rewritten
 *   a row graded with no verdict     — a started row left ungraded
 *   Fail / Removed with no defect,
 *     no action, or no photo         — "failed" with nothing named is the
 *                                      empty record the tick was, and the
 *                                      photo is the part an inspector can
 *                                      actually check
 * All three block at FINAL SUBMIT and never on Next — a half-typed row is
 * ordinary work mid-shift.
 *
 * IMPACT LOADING IS A WARNING, NOT A CORRECTION. 1926.502(d)(19) makes an
 * impact-loaded component mandatory to remove from service. When the record
 * says impact-loaded and the verdict is not Removed, the CP is told; the app
 * never rewrites what he recorded.
 */
const LOG_TYPE = 'fall_protection';
const TOTAL_STEPS = 2;

export default function FallProtectionLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const t = useT('fallProtection');
  const tFinalize = useT('finalize');
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave } = useCpProfile();

  const s = useMemo(() => buildStyles(), []);

  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [step, setStep] = useState(1);
  const [locked, setLocked] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  const [rows, setRows] = useState([]);

  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date }),
    [projectId, date],
  );

  // The rows as of RIGHT NOW. State read inside a debounced callback is the
  // value captured when the timer was set, which is one keystroke stale.
  const rowsRef = useRef(rows);
  useEffect(() => { rowsRef.current = rows; }, [rows]);

  // Row ids must be unique across a session and stable for the life of a row —
  // they name the photo's folder in R2. A counter plus the mount time is
  // enough and needs no native module.
  const mintRef = useRef(0);
  const mintId = useCallback(() => {
    mintRef.current += 1;
    return `${Date.now().toString(36)}_${mintRef.current}`;
  }, []);

  /** The server names the condition, the client owns the wording. */
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
      writeDraft(_key, {
        data: draftBody(rowsRef.current),
        cp_signature: cpSignature,
        cp_name: cpName,
      }).catch(() => {});
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, rows, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const persisted = await persistActivityPhotos(rowsRef.current);
      await writeDraft(_key, {
        data: draftBody(persisted), cp_signature: cpSignature, cp_name: cpName,
      });
    } catch (_e) { /* best-effort; the next change retries */ }
  }, [locked, _key, cpSignature, cpName]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    // Re-derived every load, so an amendment can unlock the screen.
    setLocked(false);
    try {
      const draft = await readDraft(_key);
      if (draft?.data && Array.isArray(draft.data.activities)) {
        const _amended = draft.finalized && await adoptAmendment({
          key: _key, projectId, logType: LOG_TYPE, date,
        });
        if (_amended) {
          // Fall through to the server path, which prefers the unlocked doc.
        } else {
          if (draft.finalized) { setLocked(true); markFinalized(_key); }
          setExistingLogId(draft.backend_id || null);
          // AN EMPTY ROSTER MUST STILL REBUILD — the trap four other forms
          // hit. `Array.isArray` is satisfied by an EMPTY array, so opening
          // this log before anyone checked in stored `activities: []` and
          // every reopen set the list to that and returned.
          const _stored = draft.data.activities;
          if (_stored.length > 0) {
            setRows(_stored);
          } else {
            const _fresh = await logbooksAPI
              .getCheckinsForDate(projectId, date).catch(() => null);
            const _built = Array.isArray(_fresh)
              ? buildRowsFromCheckins(_fresh, mintId()) : [];
            setRows(_built.length > 0 ? _built : [EMPTY_ROW(mintId())]);
          }
          if (draft.cp_signature) setCpSignature(draft.cp_signature);
          if (draft.cp_name) setCpName(draft.cp_name);
          setLoading(false);
          return;
        }
      }

      const [checkins, existingLogs] = await Promise.all([
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, LOG_TYPE, date).catch(() => []),
      ]);

      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find((l) => !l.is_locked) || arr[0] || null;
      if (existing) {
        if (existing.is_locked) { setLocked(true); markFinalized(_key); }
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (Array.isArray(d.activities) && d.activities.length > 0) {
          setRows(d.activities);
          if (existing.cp_signature) setCpSignature(existing.cp_signature);
          if (existing.cp_name) setCpName(existing.cp_name);
          setLoading(false);
          return;
        }
      }

      const built = buildRowsFromCheckins(checkins, mintId());
      setRows(built.length > 0 ? built : [EMPTY_ROW(mintId())]);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [_key, projectId, date, mintId, setCpName, setCpSignature]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── Rows ──────────────────────────────────────────────────────────────
  const updateRow = (index, field, value) => {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, [field]: value } : r)));
  };
  const setResult = (index, value) => {
    setRows((prev) => prev.map((r, i) => (i === index ? applyResult(r, value) : r)));
  };
  const setImpact = (index, value) => {
    setRows((prev) => prev.map((r, i) => (i === index ? applyImpactLoaded(r, value) : r)));
  };
  const addRow = () => setRows((prev) => [...prev, EMPTY_ROW(mintId())]);
  const removeRow = (index) => setRows((prev) => prev.filter((_, i) => i !== index));

  /**
   * Attach a photo to one row.
   *
   * The gallery path is deliberately offered beside the camera: a defect is
   * often photographed the moment it is found, minutes before the log is
   * opened, and telling a CP to retake it is how the photo requirement gets
   * worked around instead of met.
   */
  const addPhoto = async (index, fromCamera) => {
    try {
      const perm = fromCamera
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (perm.status !== 'granted') {
        toast.warning(t('photoPermTitle'), t('photoPermBody'));
        return;
      }
      const result = fromCamera
        ? await ImagePicker.launchCameraAsync({ quality: 0.6, base64: false })
        : await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 0.6, base64: false,
        });
      if (result.canceled || !result.assets?.length) return;
      const photoId = `ph_${mintId()}`;
      // Under the cap BEFORE it is stored, so the draft never holds a raw
      // sensor JPEG and the upload never has one to refuse.
      const uri = await compressUnderCap(result.assets[0].uri).catch(
        () => result.assets[0].uri,
      );
      setRows((prev) => prev.map((r, i) => (i === index
        ? { ...r, photos: [...(r.photos || []), { id: photoId, uri, upload_pending: true }] }
        : r)));
    } catch (e) {
      toast.error(t('photoFailedTitle'), t('photoFailedBody'));
    }
  };

  const removePhoto = (index, photoId) => {
    setRows((prev) => prev.map((r, i) => (i === index
      ? { ...r, photos: (r.photos || []).filter((p) => p.id !== photoId) }
      : r)));
  };

  // ── Save ──────────────────────────────────────────────────────────────
  const persistAndPush = async (submitStatus) => {
    const current = rowsRef.current?.length ? rowsRef.current : rows;
    // Photos into documentDirectory first, so a row survives an app kill with
    // its evidence attached.
    const persisted = await persistActivityPhotos(current);
    // A ROW THAT NAMES NOBODY, OR CARRIES NO VERDICT, IS NOT FILED. The same
    // split the register uses: a DRAFT keeps everything, because a half-typed
    // row is work in progress; it is only at the moment of FILING that an
    // ungraded row becomes a blank inspection line on a document whose whole
    // subject is inspections.
    const filed = submitStatus === 'submitted' ? rowsForFiling(persisted) : persisted;
    // What he signed is what he sees.
    if (submitStatus === 'submitted' && filed.length !== persisted.length) setRows(filed);

    await writeDraft(_key, {
      data: draftBody(filed), cp_signature: cpSignature, cp_name: cpName,
      status: submitStatus,
    });

    const uploaded = await uploadPendingActivityPhotos(projectId, filed);
    if (uploaded.uploaded > 0) setRows(uploaded.activities);
    const data = draftBody(uploaded.activities);
    await writeDraft(_key, { data });

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
      // REFUSAL IS NOT OFFLINE. This is an IMMEDIATE type, so a submitted push
      // IS the finalize — a 4xx is the server judging the log, not failing to
      // reach it.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      if (refused && submitStatus === 'submitted') {
        const code = finalizeErrorCode(pushErr);
        console.warn('Fall protection log REFUSED by the server:', status, code);
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        console.warn('Fall protection push FAILED server-side:', status || pushErr?.message);
        await markPending(_key);
        toast.error(tFinalize('errorTitle'), gateCopy(null));
        return undefined;
      }
      await markPending(_key);
      console.warn('Fall protection push deferred (will sync on reconnect):', pushErr?.message);
    }

    // A photo that has not reached R2 keeps the draft pending even when the
    // content push succeeded — the drain is the only thing that will retry it.
    if (hasPendingPhotoUploads(uploaded.activities)) await markPending(_key);

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

  const handleSubmitAndSign = async () => {
    if (signing) return;
    if (!cpSignature) {
      setStep(TOTAL_STEPS);
      toast.warning(t('signatureRequiredTitle'), t('signatureRequiredBody'));
      return;
    }
    const now = rowsRef.current || rows;

    // A FAILED INSPECTION WITH NOTHING NAMED IS THE EMPTY RECORD THE TICK WAS.
    // Checked before the drop rules below, because these rows WILL be filed —
    // they are complete enough to file and incomplete in the way that matters.
    const missing = rowsMissingAdverseDetail(now);
    if (missing.length > 0) {
      setStep(1);
      toast.warning(
        t('adverseIncompleteTitle'),
        t('adverseIncompleteBody').replace(
          '{rows}',
          missing.map((m) => `${m.row}${m.worker_name ? ` (${m.worker_name})` : ''}: `
            + m.missing.map((k) => t(`missing_${k}`)).join(', ')).join('; '),
        ),
      );
      return;
    }

    // Rows he touched that will be DROPPED, named before they go.
    const unfilable = unfilableRows(now);
    if (unfilable.length > 0) {
      setStep(1);
      toast.warning(
        t('notFiledTitle'),
        t('notFiledBody').replace(
          '{rows}',
          unfilable.map((u) => `${u.row}${u.worker_name ? ` (${u.worker_name})` : ''} — `
            + t(u.reason === 'unnamed' ? 'reasonUnnamed' : 'reasonNoResult')).join('; '),
        ),
      );
      return;
    }

    if (rowsForFiling(now).length === 0) {
      setStep(1);
      toast.warning(t('nothingToFileTitle'), t('nothingToFileBody'));
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

  // Moving on is never BLOCKED.
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

  const STEPS = [
    { render: () => renderStep1() },
    { render: () => renderStep2() },
  ];

  const incomplete = computeIncomplete({ rows, cpSignature }).filter((n) => n !== step);
  const filedCount = rowsForFiling(rows).length;
  const impactWarnings = impactLoadedNotRemoved(rows);


  // ── STEP 1 — the equipment ────────────────────────────────────────────
  const renderStep1 = () => (
    <View>
      <StepHeader title={t('step1Title')} />
      <Text style={s.noteText}>{t('registerHint')}</Text>

      {rows.map((row, index) => {
        const adverse = isAdverse(row.result);
        return (
          <Card s={s} key={row.activity_id || `row-${index}`}>
            <View style={s.rowHead}>
              <Text style={s.reviewLabel}>
                {t('rowOf').replace('{n}', String(index + 1)).replace('{m}', String(rows.length))}
              </Text>
              <Pressable
                style={s.rowRemove}
                accessibilityRole="button"
                accessibilityLabel={t('removeRow')}
                onPress={() => removeRow(index)}
              >
                <Trash2 size={20} strokeWidth={2} color={outdoor.danger} />
              </Pressable>
            </View>

            {/* PICKED, NOT TYPED — the name and company come off the gate
                check-in. A hand-added row is editable and says so. */}
            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('colWorker')}</Text>
              <TextInput
                style={s.input}
                value={row.worker_name}
                onChangeText={(v) => updateRow(index, 'worker_name', v)}
                placeholder={t('phWorker')}
                placeholderTextColor={outdoor.textDim}
              />
            </View>
            {row.worker_id == null && rowHasContent(row) && (
              <Text style={s.noteText}>{t('unlinkedNote')}</Text>
            )}

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('colCompany')}</Text>
              <TextInput
                style={s.input}
                value={row.company}
                onChangeText={(v) => updateRow(index, 'company', v)}
                placeholder={t('phCompany')}
                placeholderTextColor={outdoor.textDim}
              />
            </View>

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('colEquipment')}</Text>
              <View style={s.chipWrap}>
                {EQUIPMENT_TYPES.map((et) => (
                  <Chip
                    key={et}
                    label={et}
                    selected={row.equipment_type === et}
                    onPress={() => updateRow(index, 'equipment_type',
                      row.equipment_type === et ? '' : et)}
                  />
                ))}
              </View>
            </View>

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('colEquipmentId')}</Text>
              <TextInput
                style={s.input}
                value={row.equipment_id}
                onChangeText={(v) => updateRow(index, 'equipment_id', v)}
                placeholder={t('phEquipmentId')}
                placeholderTextColor={outdoor.textDim}
              />
            </View>

            <DateField
              s={s}
              label={t('colMfgDate')}
              value={row.manufacture_date}
              onChange={(v) => updateRow(index, 'manufacture_date', v)}
            />

            {/* THREE STATES. Re-tapping the selected chip returns the row to
                unrecorded — the state it opens in must be reachable, or a CP
                who taps twice files a verdict he believes he cleared (#153). */}
            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('colResult')}</Text>
              <View style={s.chipWrap}>
                {RESULTS.map((r) => (
                  <Chip
                    key={r}
                    label={r}
                    selected={row.result === r}
                    onPress={() => setResult(index, r)}
                  />
                ))}
              </View>
            </View>

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('colImpact')}</Text>
              <View style={s.chipWrap}>
                <Chip label={t('yes')} selected={row.impact_loaded === true}
                  onPress={() => setImpact(index, true)} />
                <Chip label={t('no')} selected={row.impact_loaded === false}
                  onPress={() => setImpact(index, false)} />
              </View>
              {/* 1926.502(d)(19) — mandatory removal. Said, never done FOR him:
                  the app does not rewrite a verdict a person recorded. */}
              {row.impact_loaded === true && row.result !== 'Removed from service' && (
                <View style={s.cardWarn}>
                  <Text style={s.warnText}>{t('impactWarning')}</Text>
                </View>
              )}
            </View>

            {/* Only on Fail / Removed. A defect box on a passing row invites a
                note about equipment that is fine. */}
            {adverse && (
              <>
                <View style={s.fieldBlock}>
                  <Text style={s.reviewLabel}>{t('colDefect')}</Text>
                  <TextInput
                    style={[s.input, s.inputMultiline]}
                    value={row.defect_found}
                    onChangeText={(v) => updateRow(index, 'defect_found', v)}
                    placeholder={t('phDefect')}
                    placeholderTextColor={outdoor.textDim}
                    multiline
                  />
                </View>
                <View style={s.fieldBlock}>
                  <Text style={s.reviewLabel}>{t('colAction')}</Text>
                  <TextInput
                    style={[s.input, s.inputMultiline]}
                    value={row.action_taken}
                    onChangeText={(v) => updateRow(index, 'action_taken', v)}
                    placeholder={t('phAction')}
                    placeholderTextColor={outdoor.textDim}
                    multiline
                  />
                </View>
              </>
            )}

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>{t('colAnchor')}</Text>
              <TextInput
                style={s.input}
                value={row.anchor_point}
                onChangeText={(v) => updateRow(index, 'anchor_point', v)}
                placeholder={t('phAnchor')}
                placeholderTextColor={outdoor.textDim}
              />
            </View>

            <View style={s.fieldBlock}>
              <Text style={s.reviewLabel}>
                {adverse ? t('colPhotoRequired') : t('colPhoto')}
              </Text>
              <View style={s.photoStrip}>
                {(row.photos || []).map((p) => (
                  <Pressable
                    key={p.id}
                    onPress={() => removePhoto(index, p.id)}
                    accessibilityRole="button"
                    accessibilityLabel={t('removePhoto')}
                  >
                    <Image source={{ uri: p.uri }} style={s.photoThumb} />
                  </Pressable>
                ))}
                <Pressable
                  style={s.photoAdd}
                  accessibilityRole="button"
                  accessibilityLabel={t('takePhoto')}
                  onPress={() => addPhoto(index, true)}
                >
                  <Camera size={22} strokeWidth={1.75} color={outdoor.textDim} />
                </Pressable>
                <Pressable
                  style={s.photoAdd}
                  accessibilityRole="button"
                  accessibilityLabel={t('choosePhoto')}
                  onPress={() => addPhoto(index, false)}
                >
                  <Plus size={22} strokeWidth={1.75} color={outdoor.textDim} />
                </Pressable>
              </View>
            </View>
          </Card>
        );
      })}

      <Pressable style={s.secondaryBtn} accessibilityRole="button" onPress={addRow}>
        <Plus size={22} strokeWidth={2.5} color={outdoor.text} />
        <Text style={s.secondaryBtnText}>{t('addRow')}</Text>
      </Pressable>
    </View>
  );

  // ── STEP 2 — review and sign ──────────────────────────────────────────
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewRows')}</Text>
        <Text style={s.reviewValue}>
          {filedCount > 0
            ? t(`rowsCount_${filedCount === 1 ? 'one' : 'other'}`).replace('{n}', String(filedCount))
            : t('reviewNothingYet')}
        </Text>
      </Card>

      {impactWarnings.length > 0 && (
        <View style={s.cardWarn}>
          <Text style={s.warnTitle}>{t('impactWarningTitle')}</Text>
          <Text style={s.warnText}>
            {t('impactWarningBody').replace(
              '{rows}',
              impactWarnings.map((w) => `${w.row}${w.worker_name ? ` (${w.worker_name})` : ''}`).join(', '),
            )}
          </Text>
        </View>
      )}

      {/* WHAT THIS LOG IS, on the screen the CP signs from. He is attesting to
          an inspection record, and he should know what kind of record it is
          before he signs it — the same sentence both renderers print. */}
      <View style={s.noticeBox}>
        <Text style={s.noticeText}>{t('standardNotice')}</Text>
      </View>

      <SignaturePad
        value={cpSignature}
        onChange={setCpSignature}
        signerName={cpName}
        onSignerNameChange={setCpName}
      />
    </View>
  );

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
      /* IMMEDIATE — the server locks on `submitted` alone, so an unsigned
         submit must be unreachable rather than merely warned about. The
         handler keeps its guard as a backstop. */
      submitDisabled={!isAffirmedSignature(cpSignature) || rows.every((r) => !rowHasContent(r))}
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
      flexDirection: 'row', alignItems: 'center',
      justifyContent: 'space-between', marginBottom: spacing.sm,
    },
    rowRemove: {
      minWidth: touchTarget.min, minHeight: touchTarget.min,
      alignItems: 'center', justifyContent: 'center',
    },
    inputMultiline: { minHeight: 88, textAlignVertical: 'top' },
    photoStrip: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
    photoThumb: {
      width: 72, height: 72, borderRadius: borderRadius.md,
      borderWidth: 1, borderColor: outdoor.border,
    },
    photoAdd: {
      width: 72, height: 72, borderRadius: borderRadius.md,
      borderWidth: 1, borderColor: outdoor.border,
      alignItems: 'center', justifyContent: 'center',
    },
    noticeBox: {
      borderTopWidth: 1, borderTopColor: outdoor.border,
      marginTop: spacing.lg, paddingTop: spacing.md,
    },
    noticeText: { fontSize: 12, lineHeight: 18, color: outdoor.textDim },
  });
}
