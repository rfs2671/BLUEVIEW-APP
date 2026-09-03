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
import { compareDraftToServer, submitRefused } from '../../src/utils/draftFreshness';
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
import { useEsraConsent } from '../../src/hooks/useEsraConsent';

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
  const consent = useEsraConsent();
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
  // The last autosave did not land. Sticky: it clears only when a later
  // write succeeds, never on the next keystroke, because a warning that
  // decays is one he can miss by typing.
  const [autosaveFailed, setAutosaveFailed] = useState(false);
  // THE SERVER DISAGREES WITH THIS DRAFT — null when it does not, or when
  // no comparison was possible (offline). Set on the local-first branch
  // below, which until now returned without ever asking the server.
  const [draftConflict, setDraftConflict] = useState(null);
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
        data: draftBody(b.details, b.precautions),
        cp_signature: cpSignature,
        cp_name: cpName,
      })
        .then((_ok) => setAutosaveFailed(!_ok))
        .catch(() => setAutosaveFailed(true));
    }, 800);
    return () => clearTimeout(h);
  }, [loading, locked, _key, details, precautions, cpSignature, cpName]);

  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const b = bodyRef.current;
      const _ok = await writeDraft(_key, {
        data: draftBody(b.details, b.precautions),
        cp_signature: cpSignature,
        cp_name: cpName,
      });
      setAutosaveFailed(!_ok);
    } catch (_e) { setAutosaveFailed(true); }
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
    // AND SO IS THE CONFLICT, for the same reason the lock above it is:
    // a verdict reached on the previous load is not evidence about this one.
    setDraftConflict(null);
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
          // ── ALWAYS ASK THE SERVER, EVEN THOUGH A DRAFT IS IN HAND ──────────
          //
          // Until this line the branch below returned with the server NEVER
          // fetched. Device content and the filed record were pixel-identical
          // on screen, and Submit PUT the whole draft into update_logbook,
          // which applies `data` as a wholesale $set — so a server-side
          // correction was reverted by a CP who did nothing but open his log.
          //
          // OFFLINE IS UNCHANGED, and that is a requirement rather than a
          // side effect: compareDraftToServer never throws, and it reads a
          // failed fetch as "no comparison possible" rather than "the server
          // wins", so a CP with no signal opens exactly the screen he did
          // before. Only a CONFLICT is stored — a clean comparison and an
          // unreachable server are both null, and null blocks nothing.
          //
          // THE DRAFT IS STILL WHAT IS HYDRATED BELOW. Nothing here applies
          // the server document, discards the draft, or chooses between them;
          // choosing is the conflict UI and it is not built.
          const _cmp = await compareDraftToServer({
            draft, projectId, logType: LOG_TYPE, date,
          });
          setDraftConflict(_cmp.conflict ? _cmp : null);
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
    // NO SILENT OVERWRITE — WHICH IS NOT THE SAME AS NO OVERWRITE.
    //
    // This function PUTs `data` as a wholesale $set, so pushing over a
    // changed server document really does revert it. THE CP'S DRAFT WINS
    // anyway: it is the most recent authorship and he is the one who made
    // it. What `submitRefused` withholds is the SILENT case — it stays true
    // until he has been shown the server change and taken the override in
    // the banner, and then it opens.
    //
    // AND IT NEVER OPENS FOR A FILED OR FINALIZED SERVER DOCUMENT. That is
    // a signed compliance record, not a competing draft; the ruling does not
    // reach it, the server refuses the write (423 / 409), and Amend is the
    // route that corrects one. draftFreshness.OVERRIDABLE_REASONS is the
    // single place that line is drawn.
    //
    // THE WHOLE CALL IS REFUSED, not just the push. A local write here
    // would bind a backend_id and a status against a document this device
    // has been told it is behind, which is a half-state nothing later
    // reads correctly. HIS WORK IS NOT AT RISK: the debounced autosave is a
    // separate effect and keeps writing the draft to this device.
    //
    // THE SAME PREDICATE THE SUBMIT BUTTON ASKS, so a live button and a
    // refusing save path cannot disagree. This is the guard for every other
    // caller, now and later.
    if (submitRefused(draftConflict)) return;
    const b = bodyRef.current;
    const data = draftBody(b.details, b.precautions);

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
        console.warn('Hot work permit push deferred but the LOCAL SAVE FAILED; not queued.');
        await recordFinalizeError(
          existingLogId || _key, 'LOCAL_SAVE_FAILED', _key, 'local');
        toast.error(tFinalize('localSaveFailedTitle'), tFinalize('localSaveFailed'));
        return undefined;
      }
      await markPending(_key);
      console.warn('Hot work permit push deferred (will sync on reconnect):', pushErr?.message);
      // ON THIS DEVICE ONLY — the other half of the same banner. The local
      // write landed, so this log IS safe here and IS queued; what is not true
      // is that anyone else can see it. He is about to attest to a legal
      // record, and a toast saying "will sync" is gone before he has
      // finished reading it, so this goes up durably and comes down when the
      // drain succeeds (clearUnsyncedBanner in draftSync).
      await recordFinalizeError(
        existingLogId || _key, 'NOT_ON_SERVER', _key, 'unsynced');
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
    // ── THE AGREEMENT TO SIGN ELECTRONICALLY ───────────────────────────
    // BB 2024-007 sec V.5. One consent per person, keyed on his account and
    // not on this log — if he agreed on any other screen, this never asks.
    // Offline with a remembered yes, it never asks either; see
    // consentCache.js for why an older version still counts there.
    if (!(await consent.ensure())) return;

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
          pinned
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
      submitWarning={autosaveFailed ? tFinalize('autosaveFailedWarning') : ''}
      draftConflict={draftConflict}
      // HE TOOK THE OVERRIDE. Stored ON the verdict rather than beside it, so
      // the load that clears the verdict clears the acknowledgement with it and
      // a NEW server change is never covered by an answer he gave to an old one.
      onConflictAcknowledge={() => setDraftConflict(
        (c) => (c ? { ...c, acknowledged: true } : c),
      )}
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
