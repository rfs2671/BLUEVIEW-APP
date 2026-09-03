import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, Image,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, Users, CheckCircle, XCircle, Save, Plus, Calendar, Lock,
  ShieldAlert, Briefcase, Check, X,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import LogbookLockBar from '../../src/components/LogbookLockBar';
import DraftConflictNotice from '../../src/components/DraftConflictNotice';
import SignatureImage from '../../src/components/SignatureImage';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI, checkinsAPI } from '../../src/utils/api';
import { draftKey, readDraft, writeDraft, setDraftBackendId, markPending, clearPending, markFinalized } from '../../src/utils/logbookDrafts';
import { compareDraftToServer, submitRefused } from '../../src/utils/draftFreshness';
// recordFinalizeError RAISES the durable banner LogbookLockBar renders. Used
// here for the one failure a toast cannot carry: the sheet is signed at the
// gate and the CP walks off with it.
import { recordFinalizeError, clearFinalizeError } from '../../src/utils/draftSync';
import { chooseEditableLog } from '../../src/utils/logbookEditable';
// PER-ROW SAVE STATE. A screen-level "Saving…" is decoration; this is a fact
// about one man's row — see src/utils/rowSaveState.js for why the fact is
// "changed since the last write that landed" rather than a spinner.
import { snapshotRows, unsavedRowKeys, rowKey } from '../../src/utils/rowSaveState';
import { withGateSnapshot, reconcileRoster } from '../../src/utils/rosterReconcile';
import { freezeIfImmediate } from '../../src/utils/logbookTiming';
import { capitalizeFirst } from '../../src/utils/textFormat';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
import { useT } from '../../src/i18n';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';
import { useEsraConsent } from '../../src/hooks/useEsraConsent';
// THE FOUR STATES THIS SCREEN USED TO PRINT AS ONE SENTENCE, plus the ruled
// attestation wording. Both live in one module so the CP's gate screen and its
// tests read the same strings — the copy is the product here, not decoration.
import {
  sstFlagCopy, CARD_CHECK_STATEMENT, cardCheckScopeNote, CARD_CHECK_AFFIRM,
  CARD_CHECK_REFUSE, CARD_CHECK_NO_NUMBER, cardCheckedLine,
} from '../../src/utils/sstFlagCopy';

/**
 * EMPTY_WORKER now includes all fields that come from a worker's sign-in record.
 * - auto_filled: true  → worker came from today's check-ins (name/company/osha locked)
 * - auto_filled: false → manually added row (all fields editable)
 * - worker_signature   → the signature the worker drew when they signed in via NFC/QR
 */
const EMPTY_WORKER = () => ({
  worker_id: null,
  name: '',
  company: '',
  osha_number: '',
  worker_signature: null,
  had_injury: null,    // null | 'yes' | 'no'
  inspected_ppe: null, // null | 'yes' | 'no'
  signed: false,
  auto_filled: false,
});

/**
 * ITEM 2 — WHY A WORKER'S SST CARD IS FLAGGED, IN WORDS HE CAN ACT ON.
 *
 * This replaced a binary ternary:
 *
 *     {f.sst_status === 'expired' ? 'Expired SST card' : 'Unknown SST card'}
 *
 * Two branches for five statuses, so everything that was not `expired` claimed
 * "Unknown SST card" — four materially different production rows, and any
 * status added later. See src/utils/sstFlagCopy.js for which of the two reason
 * vocabularies drives the sentence and why.
 *
 * EXPORTED, AND THAT IS THE POINT. Mount smoke proves a route does not throw;
 * a component returning null passes it. src/utils/sstCardFlagPaints.test.cjs
 * renders THIS function — not a copy of it — and asserts the words come out,
 * for each of the four rows. Nothing else in this repo executes a screen.
 */
export function SstFlagLines({ sstStatus, reviewReason, unknownReason, styles = {} }) {
  const copy = sstFlagCopy({ sstStatus, reviewReason, unknownReason });
  if (!copy) return null;
  return (
    <>
      <View style={styles.flagReasonRow}>
        <ShieldAlert size={14} strokeWidth={2} color={semantic.attention} />
        <Text style={styles.flagReasonText}>{copy.title}</Text>
      </View>
      {copy.detail ? <Text style={styles.flagHint}>{copy.detail}</Text> : null}
    </>
  );
}

/**
 * ITEM 1 — "I CHECKED THIS CARD".
 *
 * The one thing that can clear `needs_review`, and it is an ATTESTATION: the CP
 * is saying he has SEEN the physical card, which is a different claim from
 * dismissing a warning. The words are ruled and are in sstFlagCopy.js.
 *
 * FOUR STATES, and the order they are tested in is the design:
 *
 *   no card number   → NO CONTROL AT ALL, and the screen says why. There is
 *                      nothing to attest against, and a clearance keyed on null
 *                      would carry to every future card this man is issued.
 *   a check stands   → who, when, and against which card number.
 *   a check exists   → but against a DIFFERENT number, so it does not carry:
 *   for another card   the control is offered again, and the stale check is not
 *                      reported as though it still stood. Same join the server
 *                      makes in card_check_covers().
 *   otherwise        → the opener, then a confirm step. One tap must not be an
 *                      attestation.
 *
 * The confirm step has a REFUSAL that records nothing. If the only way out of
 * the dialog is to affirm, the attestation is worthless. It writes nothing
 * deliberately: a recorded "could not check" would be a second server state
 * with no reader, and the row keeps its warning either way, which is the fact
 * that matters.
 */
export function CardCheckLines({
  cardNumber, checkedByName, checkedAt, checkedNumber,
  open, busy, onOpen, onConfirm, onDismiss, styles = {},
}) {
  const number = String(cardNumber || '').trim();
  if (!number) {
    return <Text style={styles.flagHint}>{CARD_CHECK_NO_NUMBER}</Text>;
  }
  const stands = !!checkedAt && String(checkedNumber || '').trim() === number;
  if (stands) {
    return (
      <Text style={styles.flagStatusText}>
        {cardCheckedLine({ name: checkedByName, at: checkedAt, cardNumber: number })}
      </Text>
    );
  }
  if (!open) {
    return (
      <Pressable
        onPress={onOpen}
        disabled={busy}
        style={[styles.flagBtn, styles.flagBtnAssign, busy && styles.flagBtnBusy]}
      >
        <Text style={styles.cardCheckBtnText}>{CARD_CHECK_AFFIRM}</Text>
      </Pressable>
    );
  }
  return (
    <View style={styles.tradePicker}>
      <Text style={styles.flagHint}>{CARD_CHECK_STATEMENT}</Text>
      <Text style={styles.flagHint}>{cardCheckScopeNote(number)}</Text>
      <Pressable
        onPress={onConfirm}
        disabled={busy}
        style={[styles.tradeOption, busy && styles.flagBtnBusy]}
      >
        <Text style={styles.tradeOptionText}>{CARD_CHECK_AFFIRM}</Text>
      </Pressable>
      <Pressable onPress={onDismiss} style={styles.tradeCancel}>
        <Text style={styles.flagHint}>{CARD_CHECK_REFUSE}</Text>
      </Pressable>
    </View>
  );
}

export default function PreShiftSignIn() {
  // Theme read at RENDER time. A module-scope StyleSheet snapshots colors.*
  // at import (the DARK palette), so on the light theme this screen rendered
  // near-white text on a pale background. Same tokens, live values.
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  const router = useRouter();
  const consent = useEsraConsent();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave } = useCpProfile();
  const tFinalize = useT('finalize');

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  // The last autosave did not land. Sticky — cleared only by a later write
  // that succeeds, never by the next keystroke.
  const [autosaveFailed, setAutosaveFailed] = useState(false);
  // THE SERVER DISAGREES WITH THIS DRAFT — null when it does not, or when
  // no comparison was possible (offline). Set on the local-first branch
  // below, which until now returned without ever asking the server.
  const [draftConflict, setDraftConflict] = useState(null);
  // The rows as of the last write that RETURNED TRUE. null until the form has
  // finished loading — see the seeding effect below.
  const [savedSnapshot, setSavedSnapshot] = useState(null);
  const [existingLogId, setExistingLogId] = useState(null);
  // Tier 1 (1)b: true when the loaded log is finalized (is_locked) — the form
  // renders read-only and only the Amend path can change anything.
  const [locked, setLocked] = useState(false);

  const [company, setCompany] = useState('');
  const [projectLocation, setProjectLocation] = useState('');
  const [workers, setWorkers] = useState([]);

  /**
   * FIX 1 — ADMITTED-WITH-WARNINGS state, held DELIBERATELY OUTSIDE `workers`.
   *
   * `workers` is posted verbatim as logbook data.workers[] (see handleSave),
   * so anything written onto a worker row is persisted into the logbook and
   * flows on to the HTML report, the PDF, the kiosk viewer and the emailed
   * report. The reason a worker is flagged must NOT go there: the state
   * already lives on the check-in row behind /checkins/{id}/review and
   * /checkins/{id}/assign-trade, and duplicating it into a signed logbook
   * would create a second, frozen copy that can never be corrected.
   *
   * So the flags live in this separate map, keyed by worker_id, and are
   * rendered from component state only. Shape per entry:
   *   { checkin_id, sst_status, needs_trade, review_decision,
   *     assigned_trade, assigned_company }
   * checkin_id === null means the worker has no check-in row to act on
   * (gate sign-in or turned-away) — the UI then offers NO action rather than
   * pretending one exists.
   */
  const [flags, setFlags] = useState({});
  // The project's configured trade roster. Same list the worker picks from at
  // sign-in: both are `_active_assignments(project)` server-side.
  const [roster, setRoster] = useState([]);
  // worker_id whose trade picker is currently open (one at a time).
  const [tradePickerFor, setTradePickerFor] = useState(null);
  // worker_id whose card-check confirm step is open (one at a time). An
  // attestation must never be one tap away, so the opener sets this and the
  // statement is only affirmed from inside it.
  const [cardCheckFor, setCardCheckFor] = useState(null);
  // Per worker: how many OTHER check-ins this project holds for him. The
  // confirm step names it, because "earlier check-ins keep what they recorded"
  // is abstract until a CP sees it means four of them.
  const [priorCounts, setPriorCounts] = useState({});
  // The assignment awaiting confirmation: { workerKey, index, assignment }.
  // A trade correction is not retroactive and the CP has to be told that
  // BEFORE it happens, not in a toast afterwards.
  const [pendingTrade, setPendingTrade] = useState(null);
  // worker_id with an in-flight review / assign call.
  const [actingId, setActingId] = useState(null);

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  // Phase A2 — autosave to the local draft on any change (debounced); no server
  // call; `status` omitted so an autosave never downgrades a submitted log.
  useEffect(() => {
    if (loading) return undefined;
    const t = setTimeout(() => {
      writeDraft(draftKey({ projectId, logType: 'preshift_signin', date }), {
        data: {
          company,
          project_location: projectLocation,
          workers,
          total_count: workers.filter(w => (w.name || '').trim()).length,
        },
        cp_signature: cpSignature,
        cp_name: cpName,
      })
        // BOTH FAILURE MODES. The boolean was discarded and a throw fell into
        // the same empty catch; either one means the sheet is not on the
        // device. Reported at the SUBMIT GATE below rather than as a toast:
        // this screen autosaves on every tap of every worker row, and a
        // message that fires that often is one he stops seeing.
        .then((_ok) => {
          setAutosaveFailed(!_ok);
          // ONLY ON A CONFIRMED WRITE. writeDraft returns false rather than
          // throwing, so snapshotting unconditionally would mark every row
          // saved on a device that is storing nothing — the per-row marker
          // would then be the same lie as "Saved automatically", drawn once
          // per man.
          if (_ok) setSavedSnapshot(snapshotRows(workers));
        })
        .catch(() => setAutosaveFailed(true));
    }, 700);
    return () => clearTimeout(t);
  }, [loading, projectId, date, company, projectLocation, workers, cpSignature, cpName]);

  // SEED AT LOAD. A draft read off disk is ALREADY on disk, and a roster built
  // from today's check-ins has not been typed by anyone — neither is an unsaved
  // edit. Without this every row lights up the moment the form opens, which is
  // how a marker stops being read. Runs once, after loading settles.
  useEffect(() => {
    if (loading || savedSnapshot !== null) return;
    setSavedSnapshot(snapshotRows(workers));
  }, [loading, savedSnapshot, workers]);

  const unsavedRows = unsavedRowKeys(workers, savedSnapshot);

  const fetchData = async () => {
    setLoading(true);
    // THE LOCK IS RE-DERIVED ON EVERY LOAD — device round 5. `locked` could
    // only ever be set TRUE: no path set it back, so once a log was filed the
    // screen stayed read-only for the life of the mount. After an amendment
    // that is exactly wrong — #143 makes the editable child reachable, and
    // this is what lets the screen show it without the CP backing out and
    // re-entering. Everything below decides locked-ness from what it loads.
    setLocked(false);
    // AND SO IS THE CONFLICT, for the same reason the lock above it is:
    // a verdict reached on the previous load is not evidence about this one.
    setDraftConflict(null);
    try {
      // Phase A2 — local-first: read the on-device draft first; if present,
      // hydrate from it and skip the server round-trip (works fully offline).
      const _draft = await readDraft(draftKey({ projectId, logType: 'preshift_signin', date }));
      if (_draft && _draft.data && (_draft.data.workers?.length || _draft.data.company)) {
        const d = _draft.data;
        // Tier 1 (1)b: a draft marked finalized locks the form read-only.
        // AN AMENDMENT MUST REACH THIS SCREEN — device round 5, finding 19.
        // Parent and amendment share ONE draft key (project, logType, date), so
        // a finalized local draft used to lock the editor and return before the
        // server was ever asked. amendmentAdopt discards the frozen parent ONLY
        // on server confirmation; offline it is a no-op and the log stays
        // locked, which is honest.
        const _amended = _draft.finalized && await adoptAmendment({
          key: draftKey({ projectId, logType: 'preshift_signin', date }), projectId, logType: 'preshift_signin', date,
        });
        if (_amended) {
          // The frozen parent is discarded; fall through to the server
          // path, which already prefers the unlocked document.
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
            draft: _draft, projectId, logType: 'preshift_signin', date,
          });
          setDraftConflict(_cmp.conflict ? _cmp : null);
        if (_draft.finalized) {
          setLocked(true);
          markFinalized(draftKey({ projectId, logType: 'preshift_signin', date }));
        }
        setExistingLogId(_draft.backend_id || null);
        if (d.company) setCompany(d.company);
        if (d.project_location) setProjectLocation(d.project_location);
        // RE-CHECK AGAINST TODAY, even on the draft path. This early return
        // used to skip /checkins-today entirely, so a stored roster persisted
        // unchecked — six men on a sheet on a day five checked in, the sixth
        // having been refused at the gate. Best-effort: offline the fetch
        // fails, `fresh` is empty, and reconcileRoster keeps everything, which
        // is the same behaviour as before this change.
        // AN EMPTY STORED ROSTER MUST STILL REBUILD — same defect as
        // toolbox_talk, same origin (#130's `length > 0` guard), and this form
        // trips it more easily: the draft branch is entered on
        // `(d.workers?.length || d.company)`, and `company` is prefilled from
        // the project, so an empty roster with a prefilled company was enough.
        // The morning sign-in sheet listing nobody while men are at the gate is
        // the worst version of it.
        const _fresh = await logbooksAPI
          .getCheckinsForDate(projectId, date).catch(() => null);
        const _stored = Array.isArray(d.workers) ? d.workers : [];
        if (_stored.length > 0) {
          setWorkers(_reconcileWorkers(_stored, _fresh));
        } else if (Array.isArray(_fresh)) {
          // Offline (`_fresh` null) there is nothing to build from, and an
          // empty list is both honest and unchanged from what was on screen.
          buildWorkerList(_fresh);
        }
        if (_draft.cp_signature) setCpSignature(_draft.cp_signature);
        if (_draft.cp_name) setCpName(_draft.cp_name);
        setLoading(false);
        return;
        }
      }

      const [projectData, checkins, existingLogs, flaggedData] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'preshift_signin', date).catch(() => []),
        // FIX 1 — the trade roster for the assign-trade picker. This is the
        // SAME data the worker's own sign-in dropdown offers: the flagged
        // endpoint returns `trade_assignments: _active_assignments(project)`
        // (server.py, get_flagged_project_checkins) and the public sign-in
        // info endpoint builds its list from the same _active_assignments
        // call. Read through the authenticated endpoint because the sign-in
        // one is tag-scoped and public.
        checkinsAPI.getFlagged(projectId).catch(() => null),
      ]);

      setRoster(Array.isArray(flaggedData?.trade_assignments) ? flaggedData.trade_assignments : []);
      // Absent on an older server, or when the aggregate failed. The confirm
      // step then omits the number rather than printing a wrong one.
      setPriorCounts(
        flaggedData?.prior_checkin_counts && typeof flaggedData.prior_checkin_counts === 'object'
          ? flaggedData.prior_checkin_counts
          : {},
      );

      if (projectData) {
        setProjectLocation(projectData.address || projectData.location || projectData.name || '');
        // Pre-fill company from project data if available
        const companyVal = projectData.company_name || projectData.company || '';
        if (companyVal) setCompany(companyVal);
      }

      const checkinList = Array.isArray(checkins) ? checkins : [];
      // Built from the check-ins on EVERY path — including the one where the
      // saved logbook already has its worker rows — so re-opening a saved
      // draft still shows why a worker is flagged. Never merged into `workers`.
      buildFlagMap(
        checkinList,
        Array.isArray(flaggedData?.items) ? flaggedData.items : [],
      );

      // Tier 1 (1)b: prefer the EDITABLE (non-locked) doc — an amendment child —
      // over a locked original that shares (project, type, date).
      const _existingArr = Array.isArray(existingLogs) ? existingLogs : [];
      const { log: existing, readOnly } = chooseEditableLog(_existingArr);
      if (readOnly) {
        setLocked(true);
        markFinalized(draftKey({ projectId, logType: 'preshift_signin', date }));
      }
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.company) setCompany(d.company);
        if (d.project_location) setProjectLocation(d.project_location);
        if (d.workers && d.workers.length > 0) {
          // Saved log already has full worker data — but re-check it against
          // today's check-ins before trusting it. See _reconcileWorkers.
          setWorkers(_reconcileWorkers(d.workers, checkinList));
        } else {
          buildWorkerList(checkinList);
        }
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      } else {
        buildWorkerList(checkinList);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // What the GATE supplies and the CP can then change. A field differing from
  // its snapshot proves he edited the row; `had_injury` / `inspected_ppe` /
  // `signed` are things the gate NEVER supplies, so any value there is his too.
  // See src/utils/rosterReconcile.js.
  const PRESHIFT_GATE_FIELDS = ['name', 'company', 'osha_number'];
  const PRESHIFT_ANSWER_FIELDS = ['had_injury', 'inspected_ppe', 'signed'];

  /**
   * Re-check a stored roster against today's check-ins.
   *
   * `fresh` null means the fetch failed (offline). Everything is kept — the
   * app must never delete a man because it could not reach the server.
   */
  const _reconcileWorkers = (stored, fresh) => {
    if (!Array.isArray(fresh)) return stored;
    const built = fresh
      .filter((c) => c && c.blocked !== true && c.source !== 'cert_block')
      .map((c) => withGateSnapshot({
        worker_id: c.worker_id,
        name: c.worker_name || '',
        company: c.company || '',
        osha_number: c.osha_number || '',
        signin_id: c.signin_id || null,
        worker_signature: c.worker_signature || c.signature || null,
        had_injury: null,
        inspected_ppe: null,
        signed: false,
        auto_filled: true,
      }, PRESHIFT_GATE_FIELDS));
    return reconcileRoster({
      stored,
      fresh: built,
      fields: PRESHIFT_GATE_FIELDS,
      answers: PRESHIFT_ANSWER_FIELDS,
    }).rows;
  };

  /**
   * Builds the worker list from today's check-ins.
   * Captures: name, company, osha_number, and worker_signature — all locked (read-only).
   * Rows come ONLY from check-ins; no blank padding. The CP adds any manual
   * entries with "+ Add Row", so an empty check-in list starts with no rows
   * rather than five empty numbered slots.
   */
  const buildWorkerList = (checkins) => {
    const list = checkins.map((c) => withGateSnapshot({
      worker_id: c.worker_id,
      name: c.worker_name || '',
      company: c.company || '',
      osha_number: c.osha_number || '',
      // New-system rows carry signin_id → authed proxy endpoint.
      // Legacy rows carry inline base64 in worker_signature.
      signin_id: c.signin_id || null,
      worker_signature: c.worker_signature || c.signature || null,
      had_injury: null,
      inspected_ppe: null,
      signed: false,
      auto_filled: true, // Lock identity fields — came from sign-in system
      // NOTE: no flag/reason fields here on purpose. See the `flags` state
      // above — this object is persisted verbatim into the logbook.
    }, PRESHIFT_GATE_FIELDS));
    setWorkers(list);
  };

  /**
   * FIX 1 — which of today's check-ins were ADMITTED WITH WARNINGS.
   *
   *   sst_status             → the SST warning line (see SstFlagLines)
   *   needs_trade_assignment → no trade assigned  → assign-trade
   *
   * The BLOCKED population (missing OSHA, `blocked: true` rows sourced from
   * compliance_alerts) is NOT included: those workers never completed sign-in,
   * have no check-in row, and there is nothing here to approve.
   *
   * ITEM 2 — THE STATUS GATE IS GONE. It read:
   *
   *     const sst = c.sst_status === 'expired' || c.sst_status === 'unknown'
   *       ? c.sst_status : null;
   *
   * so `missing` — a worker with no SST card on file at all — never reached
   * this screen, and any status added later would have been discarded here
   * before the render ever saw it. The whole status is carried now and
   * sstFlagCopy decides what, if anything, it says; an unrecognised value
   * yields no line rather than borrowing another state's sentence.
   *
   * WHAT DOES NOT WIDEN: approve / send-home is still offered on `expired` and
   * `unknown` only. Those are the two the review queue treats as decisions
   * (server.py, get_flagged_project_checkins); naming a third state on screen
   * is not the same as inventing a decision for it.
   *
   * SECOND ARGUMENT — the flagged endpoint's rows, which this screen already
   * fetches for the trade roster. /checkins-today carries `sst_status` but
   * neither reason field, so without this merge the screen can name the status
   * and not the cause. Nothing new is requested and nothing new is persisted.
   *
   * Result goes into `flags`, never into `workers`.
   */
  const buildFlagMap = (checkins, flaggedItems = []) => {
    const map = {};
    const byWorker = {};
    for (const it of (Array.isArray(flaggedItems) ? flaggedItems : [])) {
      if (it && it.worker_id) byWorker[String(it.worker_id)] = it;
    }
    for (const c of checkins) {
      const key = c.worker_id;
      if (!key) continue;
      if (c.blocked) continue;   // out of scope: never admitted, no row to act on
      const sst = c.sst_status || null;
      const fl = byWorker[String(key)] || {};
      const needsTrade = !!c.needs_trade_assignment;
      // THE GATE IS LIFTED, and this is the whole defect it caused.
      //
      // It read `if (!sst && !needsTrade) continue;`, so a row only appeared
      // when something was WRONG with it. A worker who picked a VALID roster
      // entry that was simply the WRONG one had no flag, no row, and no way to
      // be corrected -- the pairing was fixed by hand in mongosh twice this
      // week.
      //
      // Every non-blocked check-in now gets an entry. `sst` and `needs_trade`
      // still drive which WARNINGS are drawn; they no longer decide whether the
      // worker is reachable at all.
      map[key] = {
        // null for gate sign-ins / turned-away rows: no check-in row exists,
        // so no action can be offered. Never fabricated client-side either.
        checkin_id: c.checkin_id || null,
        sst_status: sst,
        needs_trade: needsTrade,
        review_decision: c.review_decision || null,
        assigned_trade: '',
        assigned_company: '',
        // What the check-in currently records, so a row can show what it is
        // being changed FROM. Read-only; never written into `workers`.
        current_trade: c.worker_trade || c.trade || '',
        current_company: c.worker_company || c.company || '',
        // ── ITEM 2 — the two reason vocabularies, both carried, neither
        //    reconciled here. sstFlagCopy owns which one leads and why.
        //    `sst_review_reason` is the LIVE cert code the flagged endpoint
        //    already surfaces; `sst_unknown_reason` is the copy FROZEN onto the
        //    row at check-in. Absent on rows the flagged endpoint does not
        //    return (a decided one, a `missing`/`expiring_soon` one), and the
        //    copy falls back to the narrower true sentence rather than
        //    guessing.
        review_reason: fl.sst_review_reason || null,
        unknown_reason: fl.sst_unknown_reason || null,
        // ── ITEM 1 — what the card check is made AGAINST, and what stands.
        //    The number is the one FROZEN on the check-in row, and it is posted
        //    back so the server can refuse if the record has moved on. Never
        //    the worker document's `osha_number`: that is a different field
        //    with a different lifetime, and attesting against it would key the
        //    clearance to a number the CP was never shown.
        sst_card_number: fl.sst_card_number || null,
        // DID THE FLAGGED ENDPOINT ACTUALLY RETURN THIS WORKER? It returns
        // UNREVIEWED expired/unknown rows and no-trade rows, so a row that has
        // already been approved or sent home is simply absent from it. Without
        // this flag an absent row and a row with a genuinely null card number
        // are indistinguishable, and the screen would tell the CP "no card
        // number is recorded for this worker" about a man whose card number it
        // merely did not fetch. Absent means the control is not offered AND no
        // claim is made about why.
        sst_row_known: Object.prototype.hasOwnProperty.call(byWorker, String(key)),
        card_checked_number: fl.sst_card_checked_number || null,
        card_checked_by_name: fl.sst_card_checked_by_name || null,
        card_checked_at: fl.sst_card_checked_at || null,
      };
    }
    setFlags(map);
  };

  const setFlag = (workerKey, patch) => {
    setFlags(prev => (
      prev[workerKey] ? { ...prev, [workerKey]: { ...prev[workerKey], ...patch } } : prev
    ));
  };

  /**
   * Approve / deny an expired or unknown SST card.
   *
   * DENY MARKS, IT NEVER REMOVES: 'sent_home' is recorded on the check-in row
   * and the worker stays on this roster. Both buttons stay available after a
   * decision because re-review is allowed — the endpoint overwrites the
   * decision on the row and audit_logs keeps every one of them.
   */
  const handleReview = async (workerKey, decision) => {
    const f = flags[workerKey];
    if (!f?.checkin_id) return;
    setActingId(workerKey);
    try {
      const res = await checkinsAPI.review(f.checkin_id, decision);
      setFlag(workerKey, { review_decision: res.review_decision });
      toast.success(
        decision === 'approved' ? 'Approved' : 'Denied',
        decision === 'approved'
          ? 'Recorded — the worker stays on the sign-in sheet.'
          : 'Recorded as sent home — the worker stays on the sign-in sheet.',
      );
    } catch (e) {
      // Nothing reached the server, so the row keeps its flag and says so.
      toast.error('Not recorded', e?.response?.data?.detail || 'Could not save the decision.');
    } finally {
      setActingId(null);
    }
  };

  /**
   * ITEM 1 — record that the CP has SEEN this worker's physical SST card.
   *
   * The only thing in the product that can clear `needs_review`. Before it, the
   * flag could be raised and never lowered: the sole `needs_review = False` in
   * the backend was a Pydantic model default, and the approve/deny above writes
   * `review_decision` to a DIFFERENT COLLECTION (`checkins`) from the one the
   * flag lives in (`workers`). Twenty workers carried it.
   *
   * THE CARD NUMBER IS POSTED BACK, not just read. It is what the CP was shown
   * and what the clearance is keyed to; if the record's number has changed
   * since this screen loaded, the server refuses (409) rather than recording an
   * attestation about a card nobody looked at.
   *
   * It is NOT approve. Nothing here touches `review_decision`, and the row
   * keeps whatever warning it had until the record itself is complete.
   */
  const handleCardCheck = async (workerKey) => {
    const f = flags[workerKey];
    if (!f?.checkin_id || !f?.sst_card_number) return;
    setActingId(workerKey);
    try {
      const res = await checkinsAPI.cardCheck(f.checkin_id, f.sst_card_number);
      setFlag(workerKey, {
        card_checked_number: res.card_number,
        card_checked_by_name: res.checked_by_name,
        card_checked_at: res.checked_at,
      });
      setCardCheckFor(null);
      toast.success(
        'Card checked',
        `Recorded against card number ${res.card_number}.`,
      );
    } catch (e) {
      // Nothing reached the server, so nothing is attested and the confirm step
      // stays open. An attestation that silently did not land is worse than
      // none.
      toast.error(
        'Not recorded',
        e?.response?.data?.detail || 'Could not record the card check.',
      );
    } finally {
      setActingId(null);
    }
  };

  /**
   * Assign a trade to a check-in that arrived without one.
   *
   * Only ever offered where NO trade was captured — trade is confirmed per
   * project at check-in, and the CP never changes one that is already set.
   * assign-trade clears needs_trade_assignment server-side, which is what
   * retires the flag.
   */
  /**
   * What a trade change does and does not touch, in the CP's words.
   *
   * NEVER "corrected" OR "fixed". Both imply the record was wrong and is now
   * right everywhere, and neither is true: the change applies to the pairing
   * and to future check-ins on this project. Earlier check-ins keep what they
   * recorded, and a filed logbook cannot be rewritten at all.
   */
  const tradeChangeCaveat = (workerKey) => {
    const n = priorCounts[workerKey];
    if (typeof n === 'number' && n > 0) {
      return `Future check-ins on this project will use it. ${n} earlier `
        + `check-in${n === 1 ? '' : 's'} and any filed logs keep what they recorded.`;
    }
    // No number rather than a wrong one -- see prior_checkin_counts on the
    // server, which omits the field rather than guessing when the count fails.
    return 'Future check-ins on this project will use it. Earlier check-ins and '
      + 'any filed logs keep what they recorded.';
  };

  const handleAssignTrade = async (workerKey, index, assignment) => {
    const f = flags[workerKey];
    if (!f?.checkin_id || !assignment) return;
    setActingId(workerKey);
    try {
      const res = await checkinsAPI.assignTrade(
        f.checkin_id, assignment.trade, assignment.company,
      );
      setFlag(workerKey, {
        needs_trade: false,
        assigned_trade: res.trade,
        assigned_company: res.company,
      });
      // The roster row showed the placeholder the gate stored when no trade
      // could be selected. `company` is an EXISTING logbook field holding an
      // existing kind of value — this corrects it from the server's response.
      // No reason string or flag state is written here.
      if (res.company) updateWorker(index, 'company', res.company);
      setTradePickerFor(null);
      setPendingTrade(null);
      toast.success(
        'Trade updated',
        `${res.trade} — ${res.company}. ${tradeChangeCaveat(workerKey)}`,
      );
    } catch (e) {
      // Picker stays open and the flag stays up: nothing reached the server.
      toast.error('Not assigned', e?.response?.data?.detail || 'Could not assign the trade.');
    } finally {
      setActingId(null);
    }
  };

  const updateWorker = (index, field, value) => {
    setWorkers(prev => prev.map((w, i) => i === index ? { ...w, [field]: value } : w));
  };

  const addRow = () => {
    setWorkers(prev => [...prev, EMPTY_WORKER()]);
  };

  const filledWorkers = workers.filter(w => w.name.trim());

  /**
   * INJURY AND PPE ARE REQUIRED, per operator ruling.
   *
   * Both are null until the CP taps one — `null | 'yes' | 'no'` — so an
   * untouched row submitted a sign-in sheet asserting nothing about either,
   * and the report printed an em-dash. On a pre-shift sign-in those two
   * questions are the point of the form.
   *
   * ONLY ROWS WITH A NAME. A blank spare row is not a worker and must not
   * block the CP; the same rule filledWorkers already uses.
   *
   * CLIENT-SIDE ONLY, deliberately. This form has no server gate and one was
   * held back on purpose (see _SUBMIT_ROW_CONTENT_RULES_DEFERRED in
   * backend/server.py): a refusal from the server would meet a CP mid-shift at
   * the gate with nothing on screen to act on. The button names the fix and
   * the offending rows outline in red.
   */
  // `!= null` CATCHES BOTH null AND undefined, and the difference is not
  // academic: a row that never carried the key at all — an old payload, a
  // hand-built row from another build — reads `undefined`, and `!== null` let
  // it through as answered. The reconcile returns kept rows VERBATIM by
  // ruling, so a row missing the key keeps missing it forever. The drain has
  // always checked both (draftSync.js); this closes the client side to match,
  // so the two gates cannot disagree about the same draft.
  const answeredBoth = (w) => w.had_injury != null && w.inspected_ppe != null;
  const rowNeedsAnswers = (w) => !!w.name.trim() && !answeredBoth(w);
  const unansweredCount = workers.filter(rowNeedsAnswers).length;

  const handleSave = async (submitStatus = 'draft') => {
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
    // ── THE AGREEMENT TO SIGN ELECTRONICALLY ───────────────────────────────
    // BB 2024-007 sec V.5. One consent per person, keyed on his account and
    // not on this log — if he agreed on any other screen, this never asks.
    //
    // ON THE SUBMIT ONLY. This handler serves both buttons, and a DRAFT is not
    // a signature: gating it would stop a CP saving his work for a reason that
    // has nothing to do with drafts. Refusing the submit therefore costs him
    // nothing — Save Draft is still there, beside the button he just pressed.
    //
    // Placed before setSaving so a refusal does not leave the sheet spinning,
    // and before the local write below, which is where the signature becomes
    // durable on the device.
    if (submitStatus === 'submitted' && !(await consent.ensure())) return;

    setSaving(true);
    try {
      // Phase A2 — write the LOCAL draft first (works offline), then best-effort push.
      const _key = draftKey({ projectId, logType: 'preshift_signin', date });
      // THE LOCAL SAVE IS THE OFFLINE RECORD, and this sheet is the one signed
      // at the gate with no signal, so it is the record more often than the
      // server copy is. writeDraft returns false and never THROWS; the result
      // used to be discarded, and the freeze + "will sync when you are back
      // online" below fired regardless — announcing a signed, locked log that
      // existed nowhere. Carried down to both.
      let localSaved = false;
      try {
        localSaved = await writeDraft(_key, {
          data: { company, project_location: projectLocation, workers, total_count: filledWorkers.length },
          cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
        });
      } catch (_e) {
        // A THROW IS A FALSE — see the note at the same guard in hot_work.
        localSaved = false;
      }
      setAutosaveFailed(!localSaved);
      if (localSaved) setSavedSnapshot(snapshotRows(workers));

      const payload = {
        project_id: projectId,
        log_type: 'preshift_signin',
        date,
        data: {
          company,
          project_location: projectLocation,
          workers,
          total_count: filledWorkers.length,
        },
        cp_signature: cpSignature,
        cp_name: cpName,
        status: submitStatus,
      };

      // FIX (PR F): `created` MUST be declared OUTSIDE the else. Referencing it
      // at `docId = existingLogId || created?.id` below (a different block)
      // threw ReferenceError on the FIRST submit of a new log — the record was
      // written but the client errored, so recordSignatureEvent never fired and
      // the CP was trained to press Submit twice. Hoisting fixes both.
      let created = null;
      let pushOk = true;
      try {
        if (existingLogId) {
          await logbooksAPI.update(existingLogId, {
            data: payload.data,
            cp_signature: cpSignature,
            cp_name: cpName,
            status: submitStatus,
          });
        } else {
          created = await logbooksAPI.create(payload);
          setExistingLogId(created.id || created._id);
        }
        await setDraftBackendId(_key, existingLogId || created?.id || created?._id);
        await clearPending(_key);
        // The push landed, so any banner from a previous offline submit comes
        // down. Both handles — an offline submit had no server id to record
        // against and used the draft key.
        await clearFinalizeError(_key);
        const _sid = existingLogId || created?.id || created?._id;
        if (_sid) await clearFinalizeError(_sid);
      } catch (pushErr) {
        pushOk = false;
        // Queue only a key whose draft actually holds this content. The
        // debounced autosave writes this same key WITHOUT a status, so a stale
        // draft here is this morning's half-filled sheet still marked 'draft'
        // — and the drain reads the draft, not this scope. Queuing over it
        // files the sheet unsigned, which is the one thing the CP was just told
        // had not happened.
        if (localSaved) {
          await markPending(_key);
          console.warn('preshift push deferred (will sync on reconnect):', pushErr?.message);
          // ON THIS DEVICE ONLY. The sheet is safe here and queued, and the
          // toast below says so — for four seconds, to a CP walking into the
          // pre-shift meeting. He is attesting to who was on site; that nobody
          // else can see it yet outlives the toast, so it goes up durably.
          await recordFinalizeError(
            existingLogId || _key, 'NOT_ON_SERVER', _key, 'unsynced');
        } else {
          console.warn('preshift push deferred but the LOCAL SAVE FAILED; not queued.');
        }
      }

      // NEITHER COPY EXISTS. The server refused or could not be reached AND the
      // device did not store the sheet, so there is no signed record anywhere
      // and nothing queued to make one. Returning here is what stops the freeze
      // below: freezing would lock an empty or stale draft, and `router.back()`
      // would take the CP away from the only remaining copy — the rows on
      // screen — while telling him they were filed.
      if (!localSaved && !pushOk) {
        // A BANNER, NOT ONLY A TOAST. This sheet is signed at the gate and the
        // CP walks straight into the meeting; a message that removed itself
        // four seconds later is the same as no message. Recorded against the
        // same handle the drain uses, so LogbookLockBar carries it on his next
        // visit to this log.
        await recordFinalizeError(
          existingLogId || _key, 'LOCAL_SAVE_FAILED', _key, 'local');
        toast.error(tFinalize('localSaveFailedTitle'), tFinalize('localSaveFailed'));
        return;
      }

      // FREEZE ON SIGN — preshift_signin is an IMMEDIATE log: the SIGNATURE IS
      // THE FREEZE. Submitting finalizes the record in one action (there is no
      // separate Finalize step, and it is never reopened). This runs after the
      // local writeDraft above — so the frozen draft holds the SIGNED content —
      // and after the push attempt on BOTH paths, because a pre-shift meeting is
      // signed at the gate with no signal: the freeze must not need the server.
      // Corrections from here go through Amend (a linked child).
      if (submitStatus === 'submitted') {
        await freezeIfImmediate(_key, 'preshift_signin');
        setLocked(true);
      }

      await autoSave(cpName, cpSignature).catch(() => {});  // guarded: a CP-PROFILE save failure must never report "Could not save log" on a log that was already saved (and, for immediate types, already FROZEN)

      if (submitStatus === 'submitted' && cpSignature) {
        const docId = existingLogId || created?.id || created?._id;
        if (docId) {
          const { recordSignatureEvent } = require('../../src/utils/signatureAudit');
          recordSignatureEvent({
            documentType: 'logbook', documentId: docId, eventType: 'cp_sign',
            signerName: cpName, signerRole: user?.role || 'cp',
            signatureData: cpSignature,
            contentSnapshot: { log_type: 'preshift_signin', date, project_id: projectId, data: payload.data, status: submitStatus },
            user,
          }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
        }
      }

      toast.success(
        submitStatus === 'submitted' ? 'Signed & Locked' : 'Draft Saved',
        submitStatus !== 'submitted'
          ? 'Draft saved'
          : pushOk
            ? 'Signed — this log is now locked. Corrections require an amendment.'
            : 'Signed — locked on this device and will sync when you are back online.');
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save log');
    } finally {
      setSaving(false);
    }
  };

  const YesNoToggle = ({ value, onChange }) => (
    <View style={styles.ynRow}>
      <Pressable
        onPress={() => onChange(value === 'yes' ? null : 'yes')}
        style={[styles.ynBtn, value === 'yes' && styles.ynBtnYes]}
      >
        <Text style={[styles.ynText, value === 'yes' && styles.ynTextYes]}>Y</Text>
      </Pressable>
      <Pressable
        onPress={() => onChange(value === 'no' ? null : 'no')}
        style={[styles.ynBtn, value === 'no' && styles.ynBtnNo]}
      >
        <Text style={[styles.ynText, value === 'no' && styles.ynTextNo]}>N</Text>
      </Pressable>
    </View>
  );

  /**
   * FIX 1 — the per-row warning block.
   *
   * SOFT by design: it never hides the row, never disables a field and never
   * gates Submit. The CP can sign the sheet with every one of these still
   * open. It also never says "flagged" — each line names the specific reason.
   *
   * Tap-only: every control is a Pressable with onPress. No gestures.
   */
  const renderWorkerFlags = (worker, index) => {
    const key = worker.worker_id;
    const f = key ? flags[key] : null;
    if (!f) return null;
    const busy = actingId === key;
    // ITEM 2 — the WARNING is drawn for every status the copy can name, so
    // `missing` finally reaches this screen. The DECISION below it is still
    // scoped to the two the review queue treats as decisions.
    const sstFlagged = !!sstFlagCopy({
      sstStatus: f.sst_status,
      reviewReason: f.review_reason,
      unknownReason: f.unknown_reason,
    });
    const sstReviewable = f.sst_status === 'expired' || f.sst_status === 'unknown';
    // ITEM 1 — the card check answers "has a human looked at this card", which
    // is only the question being asked when the card itself could not be
    // confirmed. An expired card is not a reading problem and looking at it
    // will not renew it; a missing one has no card to look at.
    const canCardCheck = f.sst_status === 'unknown';
    const canAct = !!f.checkin_id;

    return (
      <View style={styles.flagBlock}>
        {sstFlagged && (
          <>
            <SstFlagLines
              sstStatus={f.sst_status}
              reviewReason={f.review_reason}
              unknownReason={f.unknown_reason}
              styles={styles}
            />
            {canAct && canCardCheck && f.sst_row_known ? (
              <CardCheckLines
                cardNumber={f.sst_card_number}
                checkedByName={f.card_checked_by_name}
                checkedAt={f.card_checked_at}
                checkedNumber={f.card_checked_number}
                open={cardCheckFor === key}
                busy={busy}
                onOpen={() => setCardCheckFor(key)}
                onConfirm={() => handleCardCheck(key)}
                onDismiss={() => setCardCheckFor(null)}
                styles={styles}
              />
            ) : null}
            {sstReviewable && f.review_decision && (
              <Text style={styles.flagStatusText}>
                {f.review_decision === 'approved'
                  ? 'Approved — recorded on this check-in.'
                  : 'Denied — recorded as sent home. Still listed below.'}
              </Text>
            )}
            {!sstReviewable ? null : canAct ? (
              /* Both buttons stay available after a decision — re-review is
                 allowed and the latest decision wins on the check-in row. */
              <View style={styles.flagActions}>
                <Pressable
                  onPress={() => handleReview(key, 'approved')}
                  disabled={busy}
                  style={[styles.flagBtn, styles.flagBtnApprove, busy && styles.flagBtnBusy]}
                >
                  <Check size={14} strokeWidth={2} color={semantic.verified} />
                  <Text style={[styles.flagBtnText, { color: semantic.verified }]}>
                    Approve
                  </Text>
                </Pressable>
                <Pressable
                  onPress={() => handleReview(key, 'sent_home')}
                  disabled={busy}
                  style={[styles.flagBtn, styles.flagBtnDeny, busy && styles.flagBtnBusy]}
                >
                  <X size={14} strokeWidth={2} color={semantic.attention} />
                  <Text style={[styles.flagBtnText, { color: semantic.attention }]}>
                    Deny
                  </Text>
                </Pressable>
              </View>
            ) : (
              /* No check-in row behind this worker (gate sign-in), so there is
                 nothing to approve or deny. Say so rather than show a button
                 that cannot work. */
              <Text style={styles.flagHint}>
                No check-in record to review for this worker.
              </Text>
            )}
          </>
        )}

        {/*
          EVERY ROW IS REACHABLE, not only flagged ones. `needs_trade` still
          decides the WARNING above; it no longer decides whether the picker
          exists. A worker who picked a valid roster entry that was the wrong
          one had no route here at all.
        */}
        {true && (
          <>
            {f.needs_trade ? (
              <View style={styles.flagReasonRow}>
                <Briefcase size={14} strokeWidth={2} color="#93c5fd" />
                <Text style={[styles.flagReasonText, { color: '#93c5fd' }]}>
                  No trade assigned
                </Text>
              </View>
            ) : f.current_trade ? (
              <Text style={styles.flagHint}>
                Trade on this check-in: {f.current_trade}
                {f.current_company ? ` — ${f.current_company}` : ''}
              </Text>
            ) : null}
            {!canAct ? (
              <Text style={styles.flagHint}>
                No check-in record to assign a trade on for this worker.
              </Text>
            ) : roster.length === 0 ? (
              <Text style={styles.flagHint}>
                This project has no trades configured yet, so there is nothing
                to pick from. An admin adds them on the project.
              </Text>
            ) : pendingTrade?.workerKey === key ? (
              /*
                THE CONFIRM STEP. It names what is NOT changing, with a count,
                BEFORE the write -- a toast afterwards is too late to be a
                decision. The verb is "update", never "correct" or "fix":
                nothing retroactive happens.
              */
              <View style={styles.tradePicker}>
                <Text style={styles.flagHint}>
                  Set {pendingTrade.assignment.trade} — {pendingTrade.assignment.company}?
                </Text>
                <Text style={styles.flagHint}>
                  {tradeChangeCaveat(key)}
                </Text>
                <Pressable
                  onPress={() => handleAssignTrade(
                    key, pendingTrade.index, pendingTrade.assignment)}
                  disabled={busy}
                  style={[styles.tradeOption, busy && styles.flagBtnBusy]}
                >
                  <Text style={styles.tradeOptionText}>Update trade</Text>
                </Pressable>
                <Pressable onPress={() => setPendingTrade(null)} style={styles.tradeCancel}>
                  <Text style={styles.flagHint}>Cancel</Text>
                </Pressable>
              </View>
            ) : tradePickerFor === key ? (
              <View style={styles.tradePicker}>
                <Text style={styles.flagHint}>Select this worker's trade &amp; company</Text>
                {roster.map((a, i) => (
                  <Pressable
                    key={`${a.trade}|${a.company}|${i}`}
                    onPress={() => setPendingTrade({ workerKey: key, index, assignment: a })}
                    disabled={busy}
                    style={[styles.tradeOption, busy && styles.flagBtnBusy]}
                  >
                    <Text style={styles.tradeOptionText}>{a.trade}</Text>
                    <Text style={styles.tradeOptionSub}>{a.company}</Text>
                  </Pressable>
                ))}
                <Pressable onPress={() => setTradePickerFor(null)} style={styles.tradeCancel}>
                  <Text style={styles.flagHint}>Cancel</Text>
                </Pressable>
              </View>
            ) : (
              <Pressable
                onPress={() => setTradePickerFor(key)}
                disabled={busy}
                style={[styles.flagBtn, styles.flagBtnAssign, busy && styles.flagBtnBusy]}
              >
                <Briefcase size={14} strokeWidth={2} color="#93c5fd" />
                <Text style={[styles.flagBtnText, { color: '#93c5fd' }]}>
                  {f.needs_trade ? 'Assign Trade' : 'Change Trade'}
                </Text>
              </Pressable>
            )}
          </>
        )}

        {!f.needs_trade && f.assigned_trade ? (
          <Text style={styles.flagStatusText}>
            Trade assigned: {f.assigned_trade} — {f.assigned_company}
          </Text>
        ) : null}
      </View>
    );
  };

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container} edges={['top']}>
          <View style={styles.loadingCenter}>
            <ActivityIndicator size="large" color={colors.text.primary} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/logbooks')}
            />
            <View>
              {/* The CP fills the same record the PDF files and the worker
                  signs for at the gate, so it carries the same name here.
                  The subtitle keeps what the old title said — this IS the
                  safety meeting — and adds the citation the registry already
                  holds, rather than dropping the fact on the floor. */}
              <Text style={styles.headerTitle}>Daily Pre-Shift Sign-In</Text>
              <Text style={styles.headerSub}>Safety meeting — OSHA 1926.21</Text>
            </View>
          </View>
          <View style={styles.countBadge}>
            <Users size={14} strokeWidth={1.5} color="#60a5fa" />
            <Text style={styles.countText}>{filledWorkers.length}</Text>
          </View>
        </View>

        <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>

          {/* THE DRAFT ON SCREEN IS NOT THE RECORD, said before he touches
              anything. This screen owns no LogbookStepper — the other ten
              editors get this banner from the stepper itself — so it renders
              the SAME shared component rather than a tenth wording of its own.
              OUTSIDE the pointerEvents wrapper below, for the reason the lock
              bar is: an explanation a CP cannot select or scroll is not one. */}
          <DraftConflictNotice
            conflict={draftConflict}
            // HE TOOK THE OVERRIDE. Stored ON the verdict rather than beside it,
            // so the load that clears the verdict clears the acknowledgement with
            // it and a NEW server change is never covered by an answer he gave to
            // an old one. Identical to the handler the stepper passes for the
            // other ten — this screen owns no stepper, not a different policy.
            onAcknowledge={() => setDraftConflict(
              (c) => (c ? { ...c, acknowledged: true } : c),
            )}
          />

          {/* Tier 1 (1)b: a finalized log renders read-only. pointerEvents 'none'
              makes EVERY field below non-interactive (no per-field editable flags
              to miss). Scrolling still works; the LockBar stays interactive. */}
          <View pointerEvents={locked ? 'none' : 'auto'}>

          {/* Date */}
          <GlassCard style={styles.dateCard}>
            <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
            <Text style={styles.dateText}>
              {new Date(date + 'T12:00:00').toLocaleDateString('en-US', {
                weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
              })}
            </Text>
          </GlassCard>

          {/* Header Info */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>Meeting Details</Text>
            {[
              { label: 'Company', value: company, setter: setCompany },
              { label: 'Project Location', value: projectLocation, setter: setProjectLocation },
            ].map((f) => (
              <View key={f.label} style={styles.fieldRow}>
                <Text style={styles.fieldLabel}>{f.label}</Text>
                <TextInput
                  style={styles.fieldInput}
                  value={f.value}
                  onChangeText={f.setter}
                  placeholder="—"
                  placeholderTextColor={colors.text.subtle}
                />
              </View>
            ))}
          </GlassCard>

          {/* Worker Sign-In Table */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>Worker Sign-In</Text>
            <Text style={styles.sectionSubtitle}>
              Workers auto-populated from today's check-ins. Complete each column.
            </Text>

            {workers.map((worker, index) => (
              <View key={index} style={styles.workerCard}>

                {/* Row number + lock badge */}
                <View style={styles.workerCardHeader}>
                  <Text style={styles.workerIndex}>{index + 1}</Text>
                  {worker.auto_filled && (
                    <View style={styles.autoFilledBadge}>
                      <Lock size={10} strokeWidth={2} color="#60a5fa" />
                      <Text style={styles.autoFilledText}>Auto-filled</Text>
                    </View>
                  )}
                  {/* A FACT ABOUT THIS ROW: what is typed here is not on disk
                      yet. No spinner — a row is on disk or it is not, and the
                      in-flight moment is a few milliseconds. Only the negative
                      state renders, so the marker means something when it is
                      there. */}
                  {unsavedRows.has(rowKey(worker, index)) && (
                    <View style={styles.rowUnsavedBadge}>
                      <Text style={styles.rowUnsavedText}>Not saved</Text>
                    </View>
                  )}
                </View>

                {/* FIX 1 — why this worker is flagged, and what the CP can do
                    about it. Soft: the row is never removed and Submit is
                    never blocked. */}
                {renderWorkerFlags(worker, index)}

                {/* Name */}
                <View style={styles.workerField}>
                  <Text style={styles.workerFieldLabel}>NAME</Text>
                  {worker.auto_filled ? (
                    <Text style={styles.workerFieldValueLocked}>{worker.name || '—'}</Text>
                  ) : (
                    <TextInput
                      style={styles.workerFieldInput}
                      value={worker.name}
                      onChangeText={(v) => updateWorker(index, 'name', v)}
                      placeholder="First & Last Name"
                      placeholderTextColor={colors.text.subtle}
                    />
                  )}
                </View>

                {/* Company */}
                <View style={styles.workerField}>
                  <Text style={styles.workerFieldLabel}>COMPANY</Text>
                  {worker.auto_filled ? (
                    // PR G: company is short-entry — capitalize first at display only.
                    <Text style={styles.workerFieldValueLocked}>{capitalizeFirst(worker.company) || '—'}</Text>
                  ) : (
                    <TextInput
                      style={styles.workerFieldInput}
                      value={worker.company}
                      onChangeText={(v) => updateWorker(index, 'company', v)}
                      placeholder="Company name"
                      placeholderTextColor={colors.text.subtle}
                    />
                  )}
                </View>

                {/* OSHA Number */}
                <View style={styles.workerField}>
                  <Text style={styles.workerFieldLabel}>OSHA #</Text>
                  {worker.auto_filled ? (
                    <Text style={styles.workerFieldValueLocked}>
                      {worker.osha_number || <Text style={styles.workerFieldEmpty}>—</Text>}
                    </Text>
                  ) : (
                    <TextInput
                      style={styles.workerFieldInput}
                      value={worker.osha_number}
                      onChangeText={(v) => updateWorker(index, 'osha_number', v)}
                      placeholder="OSHA card number"
                      placeholderTextColor={colors.text.subtle}
                    />
                  )}
                </View>

                {/* Worker Signature — auto-filled from gate sign-in
                    via authenticated proxy endpoint, or inline base64
                    for legacy checkins. */}
                <View style={styles.workerField}>
                  <Text style={styles.workerFieldLabel}>WORKER SIGNATURE</Text>
                  {(worker.signin_id || worker.worker_signature) ? (
                    <View style={styles.sigContainer}>
                      <SignatureImage
                        signInId={worker.signin_id}
                        fallbackBase64={worker.worker_signature}
                        style={styles.sigImage}
                      />
                    </View>
                  ) : (
                    <View style={styles.sigMissing}>
                      <XCircle size={14} strokeWidth={1.5} color={colors.text.subtle} />
                      <Text style={styles.sigMissingText}>Not signed</Text>
                    </View>
                  )}
                </View>

                {/* Y/N Questions */}
                <View style={styles.ynBlock}>
                  {/* Required. Outlined red and labelled only once the row
                      has a NAME — an untouched spare row is not a worker and
                      must not be scolded. */}
                  <View style={[
                    styles.ynItem,
                    !!worker.name.trim() && worker.had_injury == null && styles.ynItemRequired,
                  ]}>
                    <Text style={styles.ynLabel}>Injury / Incident last time?</Text>
                    <YesNoToggle
                      value={worker.had_injury}
                      onChange={(v) => updateWorker(index, 'had_injury', v)}
                    />
                    {!!worker.name.trim() && worker.had_injury == null && (
                      <Text style={styles.requiredText}>Required field</Text>
                    )}
                  </View>
                  <View style={[
                    styles.ynItem,
                    !!worker.name.trim() && worker.inspected_ppe == null && styles.ynItemRequired,
                  ]}>
                    <Text style={styles.ynLabel}>Inspected PPE today?</Text>
                    <YesNoToggle
                      value={worker.inspected_ppe}
                      onChange={(v) => updateWorker(index, 'inspected_ppe', v)}
                    />
                    {!!worker.name.trim() && worker.inspected_ppe == null && (
                      <Text style={styles.requiredText}>Required field</Text>
                    )}
                  </View>
                </View>

              </View>
            ))}

            <GlassButton
              title="+ Add Row"
              icon={<Plus size={14} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={addRow}
              style={styles.addRowBtn}
            />

            {/* Total */}
            <View style={styles.totalRow}>
              <Text style={styles.totalLabel}>TOTAL COUNT</Text>
              <Text style={styles.totalValue}>{filledWorkers.length}</Text>
            </View>
          </GlassCard>

          {/* CP Signature */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Users size={16} strokeWidth={1.5} color={semantic.neutral} />
              <Text style={styles.sectionTitle}>Competent Person Signature</Text>
            </View>
            <SignaturePad
              title="Competent Person Signature"
              signerName={cpName}
              onNameChange={setCpName}
              existingSignature={cpSignature}
              onSignatureCapture={setCpSignature}
            />
          </GlassCard>
          </View>

          {/* Actions — hidden when finalized; the LockBar handles finalize/amend. */}
          {!locked && (
          <>
          <View style={styles.actions}>
            <GlassButton
              title={saving ? 'Saving...' : 'Save Draft'}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => handleSave('draft')}
              loading={saving}
              style={styles.draftBtn}
            />
            <GlassButton
              title={saving ? 'Submitting...' : 'Submit'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color={semantic.verified} />}
              onPress={() => handleSave('submitted')}
              loading={saving}
              // AND A NEWER SERVER DOCUMENT IS A GATE — UNTIL HE OPENS IT.
              // handleSave asks the same predicate, but a button that looks
              // live and does nothing is the dead-end this codebase keeps
              // writing hints to avoid. `submitRefused` holds it only until the
              // CP takes the override in the banner above (his draft is the
              // newer work and the ruling is that it wins); on a FILED or
              // finalized server log it never opens, because that is a signed
              // record and the server refuses the write regardless.
              disabled={!isAffirmedSignature(cpSignature) || unansweredCount > 0
                || submitRefused(draftConflict)}
              style={styles.submitBtn}
            />
          </View>
          {/* A disabled button with no reason stops a CP at the start of his
              shift. The signature hint below already says this; the same rule
              applies to the new required answers, so the count and the fix are
              named rather than left to be discovered by tapping. */}
          {!!cpSignature && unansweredCount > 0 && (
            <Text style={styles.requiredSummary}>
              {unansweredCount === 1
                ? '1 worker still needs the injury and PPE answers.'
                : `${unansweredCount} workers still need the injury and PPE answers.`}
            </Text>
          )}
          {/* Pre-shift sign-in is an IMMEDIATE log: it freezes the moment it is
              submitted, so submitting unsigned would mint a locked, unsigned
              legal record. This is the morning screen, so the hint matters more
              here than anywhere — a disabled button with no reason stops a CP at
              the start of his shift. There is no separate profile screen for the
              signature (nothing under app/settings writes cp_signature), so the
              hint names the pad directly above. */}
          {/* THE SAME FAILURE, ONE STEP EARLIER. Not a gate: a device that has
              stopped storing the draft does not stop the sheet reaching the
              server, and blocking Submit would turn a storage fault into an
              inability to file at all. It sits above the other two reasons
              because it is the only one he cannot discover by tapping. */}
          {autosaveFailed && (
            <Text style={styles.saveFailedWarn}>
              {tFinalize('autosaveFailedWarning')}
            </Text>
          )}
          {!!affirmationHintKey(cpSignature, profileLoaded) && (
            <Text style={styles.signHint}>
              {tFinalize(affirmationHintKey(cpSignature, profileLoaded))}
            </Text>
          )}
          </>
          )}

          {/* logType drives the FREEZE MODEL: preshift_signin is IMMEDIATE, so the
              bar hides Finalize (the signature already froze the log) and offers
              only Amend once locked. canFinalize stays false for that reason. */}
          <LogbookLockBar
            locked={locked}
            logId={existingLogId}
            draftKey={draftKey({ projectId, logType: 'preshift_signin', date })}
            logType="preshift_signin"
            canFinalize={false}
            onFinalized={() => setLocked(true)}
            onAmended={fetchData}
          />

        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: { flex: 1 },
  loadingCenter: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flex: 1 },
  headerTitle: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 12, color: colors.text.muted },
  countBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(96,165,250,0.15)',
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(96,165,250,0.3)',
  },
  countText: { fontSize: 13, fontWeight: '700', color: '#60a5fa' },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: spacing.md, paddingBottom: spacing.xl * 2 },
  dateCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
    padding: spacing.md,
  },
  dateText: { fontSize: 14, color: colors.text.secondary },
  section: { marginBottom: spacing.md, padding: spacing.lg },
  sectionTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.md },
  sectionHeaderRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.md },
  sectionSubtitle: { fontSize: 12, color: colors.text.muted, marginBottom: spacing.md, marginTop: -spacing.sm },
  fieldRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.05),
    gap: spacing.md,
  },
  fieldLabel: { flex: 1, fontSize: 13, color: colors.text.secondary },
  fieldInput: {
    flex: 2,
    fontSize: 14,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: withAlpha('#ffffff', 0.04),
    borderRadius: borderRadius.sm,
  },

  // Worker card layout — one card per worker instead of a flat table row
  workerCard: {
    backgroundColor: withAlpha('#ffffff', 0.03),
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.07),
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  workerCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  workerIndex: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  autoFilledBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(96,165,250,0.1)',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(96,165,250,0.25)',
  },
  autoFilledText: { fontSize: 10, color: '#60a5fa', fontWeight: '600' },

  // FIX 1 — per-row warning block (specific reason + tap-only actions)
  flagBlock: {
    marginBottom: spacing.sm,
    padding: spacing.sm,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
    backgroundColor: semantic.attentionBg,
    gap: spacing.xs,
  },
  flagReasonRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  flagReasonText: { flex: 1, fontSize: 13, fontWeight: '700', color: semantic.attention },
  flagStatusText: { fontSize: 12, color: colors.text.secondary },
  flagHint: { fontSize: 12, color: colors.text.muted },
  flagActions: { flexDirection: 'row', gap: spacing.sm },
  flagBtn: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    minHeight: 40,
  },
  flagBtnBusy: { opacity: 0.5 },
  flagBtnApprove: {
    borderColor: semantic.verifiedBorder,
    backgroundColor: semantic.verifiedBg,
  },
  flagBtnDeny: {
    borderColor: semantic.criticalBorder,
    backgroundColor: semantic.criticalBg,
  },
  // Tints here are theme tokens, not new literals: src/styles/tokens.js is a
  // MEASURED census of the colour literals on these screens and
  // src/styles/tokens.test.cjs re-counts them on every run, so a fresh
  // withAlpha()/rgba() string in this file would falsify that census.
  flagBtnAssign: {
    alignSelf: 'flex-start',
    flex: 0,
    borderColor: colors.glass.border,
  },
  flagBtnText: { fontSize: 13, fontWeight: '600' },
  // "I checked this card". Deliberately the QUIETEST control in the block: it
  // carries no approve/deny tint, because it is not a decision about the
  // worker — it is a statement about what the CP looked at. Tokens only; the
  // colour census in src/styles/tokens.test.cjs re-measures this file.
  cardCheckBtnText: { fontSize: 13, fontWeight: '600', color: colors.text.secondary },
  tradePicker: {
    gap: spacing.xs,
    padding: spacing.sm,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  tradeOption: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
    minHeight: 44,
    justifyContent: 'center',
  },
  tradeOptionText: { fontSize: 14, color: colors.text.primary, fontWeight: '600' },
  tradeOptionSub: { fontSize: 12, color: colors.text.muted },
  tradeCancel: { paddingVertical: spacing.sm, alignItems: 'center' },

  workerField: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.04),
    gap: spacing.sm,
    minHeight: 36,
  },
  workerFieldLabel: {
    width: 110,
    fontSize: 10,
    fontWeight: '700',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  workerFieldValueLocked: {
    flex: 1,
    fontSize: 14,
    color: colors.text.primary,
    fontWeight: '500',
  },
  workerFieldEmpty: {
    color: colors.text.subtle,
  },
  workerFieldInput: {
    flex: 1,
    fontSize: 14,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: withAlpha('#ffffff', 0.05),
    borderRadius: borderRadius.sm,
  },

  // Signature display inside worker card
  sigContainer: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  sigImage: {
    width: 120,
    height: 36,
    backgroundColor: withAlpha('#ffffff', 0.05),
    borderRadius: borderRadius.sm,
  },
  sigSignedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  sigSignedText: { fontSize: 11, color: semantic.verified, fontWeight: '600' },
  sigMissing: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  sigMissingText: { fontSize: 12, color: colors.text.subtle, fontStyle: 'italic' },

  // Y/N block
  ynBlock: {
    marginTop: spacing.sm,
    gap: spacing.xs,
  },
  ynItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 2,
  },
  ynItemRequired: {
    borderWidth: 1,
    borderColor: semantic.critical,
    borderRadius: borderRadius.sm,
    padding: spacing.xs,
  },
  requiredText: {
    fontSize: 11,
    color: semantic.critical,
    fontWeight: '600',
    marginTop: 2,
  },
  requiredSummary: {
    fontSize: 12,
    color: semantic.critical,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
  ynLabel: { flex: 1, fontSize: 12, color: colors.text.secondary },
  ynRow: { flexDirection: 'row', gap: 4 },
  ynBtn: {
    width: 32,
    height: 26,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.1),
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: withAlpha('#ffffff', 0.04),
  },
  ynBtnYes: { backgroundColor: semantic.verifiedBg, borderColor: semantic.verified },
  ynBtnNo: { backgroundColor: semantic.criticalBg, borderColor: semantic.attention },
  ynText: { fontSize: 11, fontWeight: '700', color: colors.text.muted },
  ynTextYes: { color: semantic.verified },
  ynTextNo: { color: semantic.attention },

  addRowBtn: { marginTop: spacing.sm, alignSelf: 'flex-start' },
  totalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: withAlpha('#ffffff', 0.1),
  },
  totalLabel: { fontSize: 11, fontWeight: '700', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  totalValue: { fontSize: 22, fontWeight: '800', color: colors.text.primary },

  signHint: {
    fontSize: 13, fontWeight: '600', color: semantic.attention,
    marginTop: spacing.sm, marginBottom: spacing.xl, textAlign: 'center',
  },

  // Louder than signHint. signHint explains a button he can see is dead; this
  // contradicts the reassurance he has been reading all morning.
  rowUnsavedBadge: {
    paddingHorizontal: 8, paddingVertical: 2, borderRadius: borderRadius.sm,
    backgroundColor: semantic.attentionBg, borderWidth: 1,
    borderColor: semantic.attentionBorder,
  },
  rowUnsavedText: {
    fontSize: 10, fontWeight: '700', color: semantic.attention,
    textTransform: 'uppercase', letterSpacing: 0.5,
  },

  saveFailedWarn: {
    fontSize: 13, fontWeight: '700', color: semantic.critical,
    marginTop: spacing.sm, textAlign: 'center',
  },

  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
    marginBottom: spacing.xl,
  },
  draftBtn: { flex: 1 },
  submitBtn: { flex: 1 },
  });
}
