import React, {
  useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  View, Text, StyleSheet, Pressable, TextInput, Modal,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { Check, Plus, Trash2 } from 'lucide-react-native';
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
import DateField from '../../src/components/logbookStepper/DateField';
import {
  CERT_TYPES, EMPTY_ENTRY, buildEntriesFromCheckins, entryHasContent,
  applyEntryEdit, entriesForFiling, sharedWorkerIds,
  incompleteSteps as computeIncomplete, draftBody,
} from '../../src/utils/oshaLogModel';
import { useT } from '../../src/i18n';
import { spacing, borderRadius, typography, outdoor, touchTarget } from '../../src/styles/theme';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';

/**
 * OSHA / SST CERTIFICATION REGISTER — on the shared stepper.
 *
 * TWO STEPS, as approved: the certifications, then review and sign. The chrome
 * is LogbookStepper's, not this screen's — header, pips, scroll, lock bar,
 * autosave note and footer come from the one component every form wears, so a
 * port cannot quietly lose the 56pt target or the single primary action.
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
 * compressUnderCap. There is no photo on the OSHA register — no field, no
 * capture, nothing to persist — so importing them would be dead weight, not
 * safety. See the PR note.
 *
 * THERE IS NO SAVE DRAFT BUTTON. Every change autosaves to the local draft;
 * the one primary action is Sign and file. That is the rule the shared stepper
 * asserts (stepper.test.cjs), and it is why the button is gone.
 *
 * THE PAYLOAD IS UNCHANGED — `data.entries[]` with the same eight keys
 * backend/server.py:13458 renders. See oshaLogModel.
 */
const LOG_TYPE = 'osha_log';
const TOTAL_STEPS = 2;

export default function OshaLogBook() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const t = useT('oshaLog');
  const tFinalize = useT('finalize');
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave } = useCpProfile();

  const s = useMemo(() => buildStyles(), []);

  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [step, setStep] = useState(1);
  const [locked, setLocked] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  const [entries, setEntries] = useState([]);
  const [certPickerFor, setCertPickerFor] = useState(null);

  const _key = useMemo(
    () => draftKey({ projectId, logType: LOG_TYPE, date }),
    [projectId, date],
  );

  // The rows as of RIGHT NOW, for the autosave timer and the save path. State
  // read inside a debounced callback is the value captured when the timer was
  // set, which is one keystroke stale.
  const entriesRef = useRef(entries);
  useEffect(() => { entriesRef.current = entries; }, [entries]);

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
      writeDraft(_key, {
        data: draftBody(entriesRef.current),
        cp_signature: cpSignature,
        cp_name: cpName,
      }).catch(() => {});
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, entries, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      await writeDraft(_key, {
        data: draftBody(entriesRef.current),
        cp_signature: cpSignature,
        cp_name: cpName,
      });
    } catch (_e) { /* best-effort; the next change retries */ }
  }, [locked, _key, cpSignature, cpName]);

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
      // LOCAL-FIRST. A local draft wins over the server copy and over the
      // check-in rebuild, so an offline CP reopens to exactly what he filled
      // and unsynced edits are never clobbered.
      const draft = await readDraft(_key);
      if (draft?.data && Array.isArray(draft.data.entries)) {
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

        // AN EMPTY REGISTER MUST STILL REBUILD — the FOURTH form with this
        // trap (toolbox_talk and preshift_signin in #137, daily_jobsite in
        // this PR). The branch condition is `Array.isArray(draft.data.entries)`,
        // which an EMPTY array satisfies, so opening the register before
        // anyone had checked in stored `entries: []` and every reopen set the
        // list to that and returned. buildEntriesFromCheckins was never
        // reached and the register could not recover.
        //
        // REBUILT IN PLACE, not by falling through: falling through would
        // re-hydrate from the server and discard local work. Offline the fetch
        // fails and the empty list stands, which is honest and unchanged.
        const _stored = Array.isArray(draft.data.entries) ? draft.data.entries : [];
        if (_stored.length > 0) {
          setEntries(_stored);
        } else {
          const _fresh = await logbooksAPI
            .getCheckinsForDate(projectId, date).catch(() => null);
          const _built = Array.isArray(_fresh)
            ? buildEntriesFromCheckins(_fresh, date) : [];
          setEntries(_built.length > 0 ? _built : [EMPTY_ENTRY()]);
        }
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        setLoading(false);
        return;
        }
      }

      const [checkins, existingLogs] = await Promise.all([
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        // DATE-SCOPED. Fetching with no date returned the most recent
        // prior-day doc, so on day 2+ the early return below loaded old
        // entries (skipping today's rebuild) AND filing landed on that old
        // doc while the dashboard reads only today's.
        logbooksAPI.getByProject(projectId, LOG_TYPE, date).catch(() => []),
      ]);

      // Prefer the EDITABLE (non-locked) doc — an amendment child — over a
      // locked original that shares (project, type, date).
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find((l) => !l.is_locked) || arr[0] || null;
      if (existing) {
        if (existing.is_locked) { setLocked(true); markFinalized(_key); }
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (Array.isArray(d.entries) && d.entries.length > 0) {
          setEntries(d.entries);
          if (existing.cp_signature) setCpSignature(existing.cp_signature);
          if (existing.cp_name) setCpName(existing.cp_name);
          setLoading(false);
          return;
        }
      }

      const built = buildEntriesFromCheckins(checkins, date);
      setEntries(built.length > 0 ? built : [EMPTY_ENTRY()]);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [_key, projectId, date, setCpName, setCpSignature]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ── Rows ──────────────────────────────────────────────────────────────
  // applyEntryEdit, NOT a spread. Editing the NAME on a row detaches its
  // worker_id: an id is a claim about who this row is, and it is only good for
  // the name the gate attached it to. A signed register in production carried
  // one man's certification against another man's worker record because this
  // edit used to touch `worker_name` alone. See oshaLogModel.applyEntryEdit.
  const updateEntry = (index, field, value) => {
    setEntries((prev) => prev.map((e, i) => (i === index ? applyEntryEdit(e, field, value) : e)));
  };
  const addEntry = () => setEntries((prev) => [...prev, EMPTY_ENTRY()]);
  const removeEntry = (index) => setEntries((prev) => prev.filter((_, i) => i !== index));

  // ── Save ──────────────────────────────────────────────────────────────
  /**
   * Local draft first, server push best-effort. Returns the doc id, `null`
   * when it saved locally with no server id yet (the offline path), or
   * `undefined` when the server REFUSED — which is not offline and must not
   * freeze.
   */
  const persistAndPush = async (submitStatus) => {
    const rows = entriesRef.current?.length ? entriesRef.current : entries;
    // AN ABANDONED ROW IS NOT A RECORD, and one was filed in production: no
    // name, no card number, no certification, company only. On SUBMIT the
    // register is trimmed to the rows that say something — the same rule the
    // PDF renderer already drops rows by, so what is filed and what is printed
    // are the same register.
    //
    // A DRAFT KEEPS EVERYTHING. A half-typed row the CP is still working on
    // must survive a save; it is only at the moment of FILING that an empty
    // row becomes a false entry on a compliance document.
    const filed = submitStatus === 'submitted' ? entriesForFiling(rows) : rows;
    // What he signed is what he sees: the trimmed register is written back to
    // state, so the screen never shows a row the filed document does not have.
    if (submitStatus === 'submitted' && filed.length !== rows.length) setEntries(filed);
    const data = draftBody(filed);

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
      // REFUSAL IS NOT OFFLINE. osha_log is an IMMEDIATE type, so a submitted
      // push IS the finalize — a 4xx here is the server judging the log, not
      // failing to reach it. Freezing on a judgement would tell the CP it was
      // filed, make the draft immutable so he could not fix what was refused,
      // and leave nothing pending for the drain to retry.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      if (refused && submitStatus === 'submitted') {
        const code = finalizeErrorCode(pushErr);
        console.warn('OSHA register REFUSED by the server:', status, code);
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        // 5xx — the server FAILED rather than judged. Retryable, and it must
        // not be announced as filed.
        console.warn('OSHA register push FAILED server-side:', status || pushErr?.message);
        await markPending(_key);
        toast.error(tFinalize('errorTitle'), gateCopy(null));
        return undefined;
      }
      await markPending(_key);
      console.warn('OSHA register push deferred (will sync on reconnect):', pushErr?.message);
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
   * THE one action. osha_log is an IMMEDIATE log: THE SIGNATURE IS THE FREEZE.
   * There is no separate Finalize step and the register is never reopened —
   * corrections go through Amend, a linked child.
   */
  const handleSubmitAndSign = async () => {
    if (signing) return;
    // SIGNATURE CLIENT GUARD. draftSync refuses an unsigned submitted push and
    // records SUBMIT_MISSING_CP_SIGNATURE against the key; catching it here
    // means the CP is told on the screen that can fix it instead of finding a
    // banner later.
    if (!cpSignature) {
      setStep(TOTAL_STEPS);
      toast.warning(t('signatureRequiredTitle'), t('signatureRequiredBody'));
      return;
    }
    // AN EMPTY REGISTER IS NOT A RECORD. The footer button is already disabled
    // for this, so reaching here means the state moved under the press; the
    // check stands anyway rather than filing a document that asserts nothing.
    if (entriesForFiling(entriesRef.current || entries).length === 0) {
      setStep(1);
      toast.warning(t('nothingToFileTitle'), t('nothingToFileBody'));
      return;
    }
    setSigning(true);
    try {
      const savedId = await persistAndPush('submitted');
      // `undefined` = refused or failed, already reported. Nothing may be
      // frozen or announced on a log the server would not take. `null` is
      // different: saved LOCALLY with no server id, which is the offline path
      // and DOES freeze — a register signed at the gate with no signal must
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

  // ── Step navigation ───────────────────────────────────────────────────
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

  const incomplete = computeIncomplete({ entries, cpSignature })
    .filter((n) => n !== step);
  const filledRows = entries.filter(entryHasContent).length;
  // Rows that share a worker_id are the SAME MAN's second certification, not a
  // duplicate. Labelling them is the fix for how the identity defect started:
  // two identical-looking rows read as a mistake, and the CP typed a different
  // man's name over one of them.
  const sharedIds = sharedWorkerIds(entries);
  const plural = (n, base) => t(`${base}_${n === 1 ? 'one' : 'other'}`).replace('{n}', String(n));

  // ── STEP 1 — the certifications ───────────────────────────────────────
  const renderStep1 = () => (
    <View>
      <StepHeader title={t('step1Title')} />
      <Text style={s.noteText}>{t('registerHint')}</Text>

      {entries.length === 0 && <Text style={s.emptyText}>{t('noEntries')}</Text>}

      {entries.map((entry, index) => (
        <Card s={s} key={`${entry.worker_id || 'row'}-${index}`}>
          <View style={s.rowHead}>
            <Text style={s.reviewLabel}>
              {t('entryOf').replace('{n}', String(index + 1)).replace('{m}', String(entries.length))}
            </Text>
            <Pressable
              style={s.rowRemove}
              accessibilityRole="button"
              accessibilityLabel={t('removeEntry')}
              onPress={() => removeEntry(index)}
            >
              <Trash2 size={20} strokeWidth={2} color={outdoor.danger} />
            </Pressable>
          </View>

          {/* A worker the gate turned away. Read-only by nature: the register
              records the refusal, and there is no card to enter. */}
          {entry.blocked && (
            <View style={[s.cardWarn, s.deniedBox]}>
              <Text style={s.warnTitle}>{t('deniedBadge')}</Text>
            </View>
          )}

          {/* NOT A DUPLICATE — the same man's second card. Said out loud
              because a CP who reads two identical rows as a mistake types over
              one of them, which is exactly how a certification ended up filed
              against the wrong worker record. */}
          {entry.worker_id && sharedIds.has(String(entry.worker_id)) && (
            <Text style={s.noteText}>{t('sameWorkerNote')}</Text>
          )}

          {/* The row no longer claims to know who this is. Shown only once the
              CP has edited a gate-recorded name, so it reads as a consequence
              of what he just did rather than as an error. */}
          {entry.worker_id == null && !entry.blocked && entryHasContent(entry) && (
            <Text style={s.noteText}>{t('unlinkedNote')}</Text>
          )}

          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('colWorker')}</Text>
            <TextInput
              style={s.input}
              value={entry.worker_name}
              onChangeText={(v) => updateEntry(index, 'worker_name', v)}
              placeholder={t('phWorker')}
              placeholderTextColor={outdoor.textDim}
            />
          </View>

          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('colCompany')}</Text>
            <TextInput
              style={s.input}
              value={entry.company}
              onChangeText={(v) => updateEntry(index, 'company', v)}
              placeholder={t('phCompany')}
              placeholderTextColor={outdoor.textDim}
            />
          </View>

          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('colCert')}</Text>
            <Pressable
              style={s.input}
              accessibilityRole="button"
              accessibilityLabel={`${t('colCert')}. ${entry.certification_type || t('phCert')}`}
              onPress={() => setCertPickerFor(index)}
            >
              <Text style={entry.certification_type ? s.fieldValueText : s.fieldPlaceholderText}>
                {entry.certification_type || t('phCert')}
              </Text>
            </Pressable>
          </View>

          <View style={s.fieldBlock}>
            <Text style={s.reviewLabel}>{t('colCard')}</Text>
            <TextInput
              style={s.input}
              value={entry.card_number}
              onChangeText={(v) => updateEntry(index, 'card_number', v)}
              placeholder={t('phCard')}
              placeholderTextColor={outdoor.textDim}
            />
          </View>

          <DateField
            s={s}
            label={t('colExpiration')}
            placeholder={t('phExpiration')}
            value={entry.expiration}
            today={date}
            clearLabel={t('dateClear')}
            doneLabel={t('dateDone')}
            onChange={(v) => updateEntry(index, 'expiration', v)}
          />

          <Pressable
            style={[s.toggleRow, entry.signed && s.toggleRowOn]}
            accessibilityRole="button"
            accessibilityState={{ selected: !!entry.signed }}
            onPress={() => updateEntry(index, 'signed', !entry.signed)}
          >
            <View style={[s.toggleBox, entry.signed && s.toggleBoxOn]}>
              {entry.signed && <Check size={18} strokeWidth={3} color={outdoor.ok} />}
            </View>
            <Text style={s.toggleText}>
              {entry.signed ? t('signedOnFile') : t('signedMark')}
            </Text>
          </Pressable>
        </Card>
      ))}

      <Pressable style={s.secondaryBtn} accessibilityRole="button" onPress={addEntry}>
        <Plus size={22} strokeWidth={2.5} color={outdoor.text} />
        <Text style={s.secondaryBtnText}>{t('addEntry')}</Text>
      </Pressable>
    </View>
  );

  // ── STEP 2 — review and sign ──────────────────────────────────────────
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />
      <Text style={s.noteText}>{t('reviewHeading')}</Text>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('reviewEntries')}</Text>
        <Text style={s.reviewValue}>
          {filledRows > 0 ? plural(filledRows, 'entriesCount') : t('reviewNothingYet')}
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

  const STEPS = [
    { render: renderStep1 },
    { render: renderStep2 },
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
      /* osha_log is IMMEDIATE — the server locks on `submitted` alone — so an
         unsigned submit must be UNREACHABLE, not merely warned about. The
         handler keeps its guard as a backstop.
         The second half restores a guard the #123 port dropped: the old screen
         carried `disabled={!cpSignature || entries.length === 0}`. Counting
         rows WITH CONTENT rather than rows is strictly stronger — a register
         of nothing but abandoned rows asserts nothing and cannot be filed. */
      submitDisabled={!isAffirmedSignature(cpSignature) || filledRows === 0}
      submitHint={affirmationHintKey(cpSignature, profileLoaded)
        ? tFinalize(affirmationHintKey(cpSignature, profileLoaded)) : ''}
      onSubmit={handleSubmitAndSign}
      logType={LOG_TYPE}
      logId={existingLogId}
      draftKey={_key}
      onFinalized={() => setLocked(true)}
      onAmended={fetchData}
      autosaveNote={t('savedAutomatically')}
      /* The cert picker is a chip sheet, not PromptModal — that primitive is a
         TEXT prompt and takes no children. Written inline rather than as a
         local component so it is not a new React type on every render. */
      overlays={(
        <Modal
          visible={certPickerFor !== null}
          transparent
          animationType="fade"
          onRequestClose={() => setCertPickerFor(null)}
        >
          <View style={s.modalOverlay}>
            <View style={s.modalCard}>
              <Text style={s.modalTitle}>{t('certPickTitle')}</Text>
              <View style={s.chipWrap}>
                {CERT_TYPES.map((ct) => (
                  <Chip
                    key={ct}
                    label={ct}
                    selected={certPickerFor !== null
                      && entries[certPickerFor]?.certification_type === ct}
                    onPress={() => {
                      updateEntry(certPickerFor, 'certification_type', ct);
                      setCertPickerFor(null);
                    }}
                  />
                ))}
              </View>
              <View style={s.modalActions}>
                <Pressable
                  style={s.secondaryBtn}
                  accessibilityRole="button"
                  onPress={() => setCertPickerFor(null)}
                >
                  <Text style={s.secondaryBtnText}>{t('dateDone')}</Text>
                </Pressable>
              </View>
            </View>
          </View>
        </Modal>
      )}
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
    rowHead: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      gap: spacing.sm,
    },
    rowRemove: {
      minWidth: touchTarget.min, minHeight: touchTarget.min,
      alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.full,
    },
    deniedBox: { borderRadius: borderRadius.lg, padding: spacing.md },
    toggleBoxOn: { borderColor: outdoor.okBorder },
    certOptionText: {
      fontSize: typography.sizes.md, color: outdoor.text,
    },
  });
}
