import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Modal,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  ShieldCheck,
  CheckCircle,
  Save,
  User,
  Calendar,
  ChevronDown,
  ChevronUp,
  Plus,
  CloudOff,
} from 'lucide-react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import LogbookLockBar from '../../src/components/LogbookLockBar';
import OfflineNotice from '../../src/components/OfflineNotice';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { collapseChains } from '../../src/utils/amendmentChain';
import { logbooksAPI } from '../../src/utils/api';
import { finalizeErrorCode, recordFinalizeError, clearFinalizeError } from '../../src/utils/draftSync';
import { draftKey, readDraft, writeDraft, setDraftBackendId, markPending, clearPending } from '../../src/utils/logbookDrafts';
import { freezeIfImmediate } from '../../src/utils/logbookTiming';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { easternToday } from '../../src/utils/dates';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { useT } from '../../src/i18n';
import { useEsraConsent } from '../../src/hooks/useEsraConsent';

const LANGUAGE_LABELS = {
  en: 'English',
  es: 'Español',
};

const ORIENTATION_SECTIONS = [
  {
    section: 'General Safety Rules',
    items: [
      { key: 'hard_hats', label: 'Hard hats required at all times on site' },
      { key: 'safety_boots', label: 'Safety boots required (steel toe, ANSI rated)' },
      { key: 'safety_glasses', label: 'Safety glasses / eye protection required' },
      { key: 'high_vis', label: 'High-visibility vest required near traffic' },
      { key: 'no_horseplay', label: 'No horseplay, running, or unsafe behavior' },
      { key: 'report_hazards', label: 'Report all hazards to CP immediately' },
    ],
  },
  {
    section: 'Fall Protection',
    items: [
      { key: 'fall_protection_required', label: 'Fall protection required at 6 ft and above' },
      { key: 'harness_inspection', label: 'Inspect harness before each use' },
      { key: 'ladder_safety', label: 'Three-point contact on ladders at all times' },
      { key: 'scaffold_rules', label: 'Only use scaffold as erected — no modifications' },
    ],
  },
  {
    section: 'Emergency Procedures',
    items: [
      { key: 'emergency_exits', label: 'Emergency exit locations reviewed' },
      { key: 'first_aid', label: 'First aid kit location reviewed' },
      { key: 'emergency_contact', label: 'Emergency contact numbers provided' },
      { key: 'incident_reporting', label: 'All incidents must be reported immediately' },
    ],
  },
  {
    section: 'Site Rules',
    items: [
      { key: 'no_drugs_alcohol', label: 'Zero tolerance for drugs and alcohol on site' },
      { key: 'sign_in_out', label: 'Must sign in and out every day' },
      { key: 'authorized_areas', label: 'Only enter authorized work areas' },
      { key: 'housekeeping', label: 'Keep work area clean at all times' },
    ],
  },
];

const ALL_KEYS = ORIENTATION_SECTIONS.flatMap(s => s.items.map(i => i.key));

const LOG_TYPE = 'subcontractor_orientation';

/**
 * Phase A, MULTI-RECORD variant.
 *
 * Every other logbook editor is ONE document per (project, type, date), so the
 * single-doc draft pattern fits. This screen is a MANAGER over N per-worker
 * orientation documents, so it needs two separate offline stores:
 *
 *   1. the LIST cache (below) — so an offline open shows the REAL roster
 *      instead of "No orientations yet", which on a gate screen reads as a
 *      false compliance claim (no one has been oriented).
 *   2. a per-worker DRAFT (logbookDrafts, keyed with draftKey's optional
 *      `workerId` discriminator) — so an unsaved manual entry survives a quit,
 *      and so a sign/create made in a dead zone is durable and gets replayed by
 *      the Phase B reconnect flush.
 *
 * This is the screen where offline matters most: a first-day worker is oriented
 * AT THE GATE, which is exactly where the signal is worst.
 */
const LIST_CACHE_PREFIX = 'bv_orientations:';
const DRAFT_PTR_PREFIX = 'bv_orientation_draft_ptr:';

const todayISO = () => easternToday();

const recordIdOf = (o) => o?.id || o?._id || null;
const workerIdOf = (o) => o?.data?.worker_id || null;

/** Same underlying orientation? Server id when both have one, else worker id. */
const sameRecord = (a, b) => {
  const ai = recordIdOf(a);
  const bi = recordIdOf(b);
  if (ai && bi) return ai === bi;
  const aw = workerIdOf(a);
  return !!aw && aw === workerIdOf(b);
};

async function readCachedList(projectId) {
  try {
    const raw = await AsyncStorage.getItem(LIST_CACHE_PREFIX + projectId);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch (_e) {
    return [];
  }
}

async function writeCachedList(projectId, list) {
  try {
    await AsyncStorage.setItem(LIST_CACHE_PREFIX + projectId, JSON.stringify(Array.isArray(list) ? list : []));
    return true;
  } catch (_e) {
    return false;
  }
}

/**
 * Pointer to the manual entry currently being typed: { workerId, date }. The
 * draft itself lives under the worker-scoped draftKey; this is just how we find
 * it again after a cold start (AsyncStorage has no "the draft I was on" index).
 */
async function readDraftPointer(projectId) {
  try {
    const raw = await AsyncStorage.getItem(DRAFT_PTR_PREFIX + projectId);
    return raw ? JSON.parse(raw) : null;
  } catch (_e) {
    return null;
  }
}

async function writeDraftPointer(projectId, ptr) {
  try {
    if (ptr) await AsyncStorage.setItem(DRAFT_PTR_PREFIX + projectId, JSON.stringify(ptr));
    else await AsyncStorage.removeItem(DRAFT_PTR_PREFIX + projectId);
  } catch (_e) { /* non-fatal — the draft itself is already safe locally */ }
}

/**
 * Fold a fresh server list over the local one. Records written offline are the
 * whole point, so they must NOT be wiped by the first successful refresh:
 *   • a pending record the server has never seen  -> kept, still flagged
 *   • a pending edit the server has now caught up on -> flag cleared, server
 *     copy wins (this is how a card stops saying "not yet synced" after the
 *     Phase B reconnect flush drained it)
 *   • a pending edit the server has NOT caught up on -> the local copy wins
 *     (otherwise a signature captured in a dead zone visibly disappears the
 *     moment the phone finds signal)
 */
function mergeWithPending(serverList, localList) {
  const pendingByWorker = new Map();
  localList.forEach((o) => {
    const w = workerIdOf(o);
    if (o?._pending && w) pendingByWorker.set(w, o);
  });
  const merged = serverList.map((srv) => {
    const w = workerIdOf(srv);
    const local = w ? pendingByWorker.get(w) : null;
    if (!local) return srv;
    pendingByWorker.delete(w);
    const synced = srv.status === local.status
      && (srv.cp_signature || null) === (local.cp_signature || null);
    if (synced) return srv;
    return { ...srv, ...local, id: recordIdOf(srv), _id: srv._id, _pending: true };
  });
  return [...pendingByWorker.values(), ...merged];
}

export default function SubcontractorOrientation() {
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
  const { cpName: newCpName, setCpName: setNewCpName, cpSignature: newCpSignature, setCpSignature: setNewCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  // The SYNCHRONOUS half of the create guard. `saving` drives what the button
  // looks like; this decides whether the handler runs. setState is async, so
  // between the first tap calling setSaving(true) and React re-rendering the
  // button as disabled there is a window in which a second tap still lands on
  // an enabled button and enters the handler — and `saving` is still false
  // when it reads it. A ref is written and read in the same tick, so the
  // second entry sees it and leaves.
  const savingRef = useRef(false);
  // 'ok' | 'offline' | 'error' — how the LAST roster refresh went. Drives the
  // OfflineNotice; an empty list is only ever presented as "none exist" when
  // the server actually answered.
  const [fetchState, setFetchState] = useState('ok');
  // { workerId, date } for the manual entry in progress, or null.
  const [draftIdent, setDraftIdent] = useState(null);
  // Resume the in-progress draft ONCE per mount — fetchData also runs as the
  // finalize/amend callback, and that must not re-open a form the CP closed.
  const resumedRef = useRef(false);

  // All orientation documents for this project
  const [orientations, setOrientations] = useState([]);
  // Which card is expanded
  const [expandedIndex, setExpandedIndex] = useState(null);
  // Show form to add new manual orientation
  const [showAddForm, setShowAddForm] = useState(false);

  // New manual entry form state
  const [newName, setNewName] = useState('');
  const [newCompany, setNewCompany] = useState('');
  const [newTrade, setNewTrade] = useState('');
  // {orientation, value} — the inline "assign a trade" prompt. A refusal
  // that names no worker and offers no fix is a dead end on a screen that
  // may list a dozen of them.
  const [assigningTrade, setAssigningTrade] = useState(null);
  const [newOsha, setNewOsha] = useState('');
  const [newChecklist, setNewChecklist] = useState({});
  const [newOrientationNum, setNewOrientationNum] = useState('');

  useEffect(() => {
    fetchData();
  }, [projectId]);

  // Autosave the in-progress manual entry to its per-worker draft. Debounced,
  // no server call; `status` omitted so an autosave never downgrades a record.
  useEffect(() => {
    if (loading || !showAddForm || !draftIdent) return undefined;
    const t = setTimeout(() => {
      writeDraft(
        draftKey({ projectId, logType: LOG_TYPE, date: draftIdent.date, workerId: draftIdent.workerId }),
        {
          data: {
            worker_id: draftIdent.workerId,
            worker_name: newName,
            worker_company: newCompany,
            worker_trade: newTrade,
            osha_number: newOsha,
            orientation_number: newOrientationNum,
            checklist: newChecklist,
            language_provided: 'en',
          },
          cp_signature: newCpSignature,
          cp_name: newCpName,
        },
      ).catch(() => {});
    }, 600);
    return () => clearTimeout(t);
  }, [
    loading, showAddForm, draftIdent, projectId, newName, newCompany, newTrade,
    newOsha, newOrientationNum, newChecklist, newCpSignature, newCpName,
  ]);

  const fetchData = async () => {
    setLoading(true);
    try {
      // Cache-first: paint the locally cached roster before touching the network,
      // so the gate screen is usable immediately and stays truthful offline.
      const cached = await readCachedList(projectId);
      // COLLAPSED HERE TOO. The offline path set the cached list raw, so a
      // CP with no signal saw the six uncollapsed rows and a header counting
      // documents — the exact bug, reachable by losing signal.
      if (cached.length > 0) setOrientations(collapseChains(cached));

      // Resume a manual entry that was interrupted (app quit / phone locked).
      if (!resumedRef.current) {
        resumedRef.current = true;
        const ptr = await readDraftPointer(projectId);
        if (ptr?.workerId) {
          setDraftIdent(ptr);
          const d = await readDraft(draftKey({
            projectId, logType: LOG_TYPE, date: ptr.date, workerId: ptr.workerId,
          }));
          const f = d?.data || {};
          if (f.worker_name || f.worker_company || f.worker_trade || f.osha_number
            || f.orientation_number || Object.keys(f.checklist || {}).length > 0) {
            setNewName(f.worker_name || '');
            setNewCompany(f.worker_company || '');
            setNewTrade(f.worker_trade || '');
            setNewOsha(f.osha_number || '');
            setNewOrientationNum(f.orientation_number || '');
            setNewChecklist(f.checklist || {});
            if (d?.cp_signature) setNewCpSignature(d.cp_signature);
            if (d?.cp_name) setNewCpName(d.cp_name);
            setShowAddForm(true);
          }
        }
      }

      // Get ALL orientation docs for this project (no date filter — these are
      // ongoing). Offline-aware: a failed refresh keeps the cache on screen and
      // says so, instead of the old `.catch(() => [])` blank roster.
      const r = await settleFetch(() => logbooksAPI.getByProject(projectId, LOG_TYPE));
      setFetchState(r.status);
      if (r.status === 'ok') {
        const merged = collapseChains(
          mergeWithPending(Array.isArray(r.data) ? r.data : [], cached),
        );
        setOrientations(merged);
        await writeCachedList(projectId, merged);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // CP signs an existing orientation document — LOCAL FIRST, then best-effort push.
  //
  // FREEZE-ON-SIGN: subcontractor_orientation is an IMMEDIATE log, so THE
  // SIGNATURE IS THE FREEZE — signing finalizes THAT record in one action and it
  // is never reopened. There is no separate Finalize step, and the freeze must
  // hold with no signal (a first-day worker is oriented AT THE GATE), so it is
  // applied to the on-device draft whether or not the push lands. New
  // information later is a NEW orientation record; corrections go through the
  // amendment-as-child path.
  /**
   * Assign the missing trade, in place, on the row that is missing it.
   *
   * Written to the on-device draft FIRST so it survives with no signal, then
   * pushed best-effort as a plain draft update — this does NOT submit. The CP
   * signs afterwards, which is the action that files the record.
   */
  const handleAssignTrade = async () => {
    const a = assigningTrade;
    if (!a) return;
    const trade = String(a.value || '').trim();
    if (!trade) { setAssigningTrade(null); return; }
    const orientation = a.orientation;
    const nextData = { ...(orientation.data || {}), worker_trade: trade };
    const key = draftKey({
      projectId, logType: LOG_TYPE,
      date: orientation.date || todayISO(),
      workerId: workerIdOf(orientation),
    });
    try {
      await writeDraft(key, { data: nextData, status: 'draft' });
      const next = orientations.map((o) => (
        sameRecord(o, orientation) ? { ...o, data: nextData } : o
      ));
      setOrientations(next);
      await writeCachedList(projectId, next);

      const id = recordIdOf(orientation);
      if (id) {
        try {
          await logbooksAPI.update(id, { data: nextData, status: 'draft' });
          await clearPending(key);
        } catch (pushErr) {
          await markPending(key);
          console.warn('Trade assignment deferred (will sync on reconnect):', pushErr?.message);
        }
      } else {
        await markPending(key);
      }
      toast.success('Trade assigned', `${nextData.worker_name || 'Worker'} — ${trade}`);
    } catch (e) {
      toast.error('Could not save', 'The trade was not assigned. Try again.');
    }
    setAssigningTrade(null);
  };

  /** A submitted orientation must name the trade the worker was oriented to do. */
  const orientationTrade = (o) => String((o?.data || {}).worker_trade || '').trim();

  const handleSignExisting = async (orientation, cpSig, cpN) => {
    // PRE-FLIGHT. The server refuses this submit (SUBMIT_MISSING_TRADE), and
    // catching it here means the CP is not asked to sign a record that is about
    // to be rejected — and is offered the fix on the spot instead of a dead end.
    // The server check is still the real gate; this only saves a round trip.
    if (!orientationTrade(orientation)) {
      setAssigningTrade({ orientation, value: '' });
      toast.warning(
        'Trade required',
        `Assign a trade for ${(orientation.data || {}).worker_name || 'this worker'} before signing.`,
      );
      return;
    }
    // ── THE AGREEMENT TO SIGN ELECTRONICALLY ─────────────────────────────
    // BB 2024-007 sec V.5. One consent per person, keyed on his account and
    // not on this log — if he agreed on any other screen, this never asks.
    //
    // AFTER the trade pre-flight, so he is not asked about consent on a submit
    // the server was about to refuse anyway, and BEFORE the local write below,
    // which is the point the signature becomes durable. handleSign delegates
    // here, so both signing entry points are covered by this one line.
    if (!(await consent.ensure())) return;

    const id = recordIdOf(orientation);
    const key = draftKey({
      projectId,
      logType: LOG_TYPE,
      date: orientation.date || todayISO(),
      workerId: workerIdOf(orientation),
    });
    try {
      // 1. The signature is durable on device before any network is attempted
      //    — if the write landed. writeDraft returns false and never throws,
      //    and this call used to discard that, so step 4 froze the record and
      //    step 5 said "Signed & locked on this device" whether or not the
      //    device held anything.
      let localSaved = false;
      try {
        localSaved = await writeDraft(key, {
          data: orientation.data || {},
          cp_signature: cpSig,
          cp_name: cpN,
          status: 'submitted',
        });
      } catch (_e) {
        // A THROW IS A FALSE — see the note at the same guard in hot_work.
        localSaved = false;
      }

      // 2. Show it as signed immediately, flagged unsynced until the push lands.
      let next = orientations.map(o => (
        sameRecord(o, orientation)
          ? { ...o, cp_signature: cpSig, cp_name: cpN, status: 'submitted', _pending: true }
          : o
      ));

      // 3. Best-effort push. A record created offline has no server id yet, so
      //    there is nothing to update — it stays pending and the Phase B
      //    reconnect flush replays the draft.
      let landed = false;
      if (id) {
        try {
          await logbooksAPI.update(id, {
            cp_signature: cpSig,
            cp_name: cpN,
            status: 'submitted',
          });
          landed = true;
        } catch (pushErr) {
          // THREE OUTCOMES, NOT TWO — the same split daily_jobsite makes on
          // finalize. Treating a REFUSAL as "deferred" would freeze the record
          // below and tell the CP it was signed, while the server keeps saying
          // no and the drain has nothing queued that would ever fix it.
          const offline = isOfflineError(pushErr);
          const status = pushErr?.response?.status;
          const refused = typeof status === 'number' && status >= 400 && status < 500;
          if (refused) {
            const code = finalizeErrorCode(pushErr);
            const who = pushErr?.response?.data?.detail?.worker_name
              || (orientation.data || {}).worker_name || 'this worker';
            // Roll the optimistic state back: nothing was submitted, nothing is
            // frozen, and the draft stays a draft so it can still be fixed.
            await writeDraft(key, {
              data: orientation.data || {}, cp_signature: cpSig, cp_name: cpN,
              status: 'draft',
            });
            if (code === 'SUBMIT_MISSING_TRADE') {
              setAssigningTrade({ orientation, value: '' });
              toast.error('Trade required', `${who} has no trade assigned. Assign one, then sign.`);
            } else {
              toast.error('Not submitted', 'The server refused this orientation. It is still on this device and still editable.');
            }
            return;   // NOT frozen, NOT announced as signed
          }
          if (!offline) {
            // 5xx — the server failed rather than judged. Retryable; nothing is
            // frozen and nothing claims success.
            console.warn('Orientation push FAILED server-side:', status);
            toast.error('Not submitted', 'The server could not be reached properly. Try again.');
            return;
          }
          console.warn('Orientation signature push deferred (will sync on reconnect):', pushErr?.message);
        }
      }

      // NEITHER COPY EXISTS. The push did not land and the device did not store
      // the signature, so nothing is queued — the drain reads the DRAFT, not the
      // cached list, and a queued key with no draft is cleared as `no-draft`.
      // Returning here is what stops the freeze and the success toast below; the
      // optimistic `next` was never committed, so the card stays unsigned and
      // signable rather than showing locked over a record that does not exist.
      if (!landed && !localSaved) {
        console.warn('Orientation signature push deferred but the LOCAL SAVE FAILED; not queued.');
        // A BANNER TOO. The per-worker key IS the handle here: with no server
        // id there is nothing else to record against, and LogbookLockBar
        // already reads `logId || draftKey` for exactly this case.
        await recordFinalizeError(id || key, 'LOCAL_SAVE_FAILED', key, 'local');
        toast.error(
          'Not signed — nothing was saved',
          'This device could not store the signature, and it did not reach the server either. Nothing was filed and nothing is queued to retry. Free up space on the device, then sign again.',
        );
        return;
      }

      if (landed) {
        await clearPending(key);
        // The push landed: take down any banner from an earlier offline sign.
        await clearFinalizeError(key);
        if (id) await clearFinalizeError(id);
        next = next.map(o => (sameRecord(o, orientation) ? { ...o, _pending: false } : o));
      } else {
        await markPending(key);
        // ON THIS DEVICE ONLY — this worker's orientation is signed here and
        // queued, and the card's _pending flag says so while this screen is
        // open. The banner is what survives him leaving it.
        await recordFinalizeError(id || key, 'NOT_ON_SERVER', key, 'unsynced');
      }

      // 4. THE SIGNATURE IS THE FREEZE. Applied after the draft write and after
      //    the push attempt — success OR failure — so a gate-side sign in a dead
      //    zone is locked on device immediately, not only once it syncs. The
      //    row flips to is_locked so the card re-renders read-only (its sign
      //    panel disappears) and LogbookLockBar shows the amend path.
      const froze = await freezeIfImmediate(key, LOG_TYPE);
      if (froze) {
        next = next.map(o => (sameRecord(o, orientation) ? { ...o, is_locked: true } : o));
      }

      setOrientations(next);
      await writeCachedList(projectId, next);

      // ── "AN OFFLINE SIGN IS AUDITED WHEN IT SYNCS" — IT NOW IS ────────────
      //
      // This comment used to say that as a statement of fact and it was FALSE
      // for as long as it stood. draftSync pushed the drained orientation with
      // its signature and its `submitted` status and wrote NO ledger event,
      // ever; nothing failed, so nothing was reported, and the signature was
      // filed with no audit row. Thirty-three signatures on the live project
      // are in that state.
      //
      // It is true now, and NOT because of anything on this line. The server
      // DERIVES the row from the accepted document
      // (ensure_signature_ledger_row, called at /finalize, which the drain's
      // applyRemoteFreeze reaches for every locally-finalized draft — which is
      // every signed one). A row derived from the document cannot be lost
      // separately from the document; a queue on this device could.
      //
      // THIS CALL STILL MATTERS AND IS NOT REDUNDANT. It is the only writer
      // that can record the SIGNING device and the SIGNING IP. The derived row
      // marks both as not-recorded, because at derivation time the only ones
      // available belong to whatever had signal later.
      //
      // The `if (landed)` guard therefore stays exactly as it is: with no
      // server id there is nothing to post against, and the durable half is
      // now server-side rather than missing.
      // recordSignatureEvent imported at top level
      if (landed) {
        recordSignatureEvent({
          documentType: 'logbook', documentId: id, eventType: 'cp_sign',
          signerName: cpN, signerRole: user?.role || 'cp',
          signatureData: cpSig,
          contentSnapshot: {
            log_type: LOG_TYPE,
            worker_name: orientation.data?.worker_name,
            worker_company: orientation.data?.worker_company,
            language_provided: orientation.data?.language_provided || 'en',
            project_id: orientation.project_id || projectId,
          },
          user,
        }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
      }

      const who = orientation.data?.worker_name || 'worker';
      if (landed) {
        toast.success(
          'Signed & locked',
          `Orientation for ${who} is signed and locked. Corrections require an amendment.`,
        );
      } else {
        toast.success(
          'Signed & locked on this device',
          `Orientation for ${who} is signed and locked on this device — it syncs when you reconnect.`,
        );
      }
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save signature');
    }
  };

  /**
   * Open the manual-entry form, minting the identity the draft is keyed by.
   *
   * Per-worker dedup key for the orientation upsert. A manual entry has no
   * real worker_id (no NFC registration), so mint a stable, non-null one:
   * the server keys the (project, log_type, date) upsert on data.worker_id
   * for orientations, and a null/omitted id is rejected 400 (a null would
   * collide every manual entry onto one row). Unique per entry so two
   * manual entries never overwrite each other — and it doubles as the
   * draftKey discriminator, so each worker gets an independent draft.
   */
  const openAddForm = async () => {
    if (!draftIdent) {
      const ident = {
        workerId: `manual_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
        date: todayISO(),
      };
      setDraftIdent(ident);
      await writeDraftPointer(projectId, ident);
    }
    setShowAddForm(true);
  };

  // Create a brand new manual orientation — LOCAL FIRST, then best-effort push.
  //
  // FREEZE-ON-SIGN also applies at creation: a record created WITH a CP
  // signature ('submitted') is signed, so it is frozen in the same action.
  // Created WITHOUT one it is a plain draft and stays open until someone signs
  // it from its card. Creating a SECOND orientation for the same worker on the
  // same day is a NEW DISCRETE RECORD (its own minted workerId, its own draft)
  // and is deliberately never blocked — that is the correct path for new
  // information later in the day.
  const handleCreateNew = async () => {
    // FIRST LINE, BEFORE THE VALIDATION RETURNS. The guard used to sit below
    // them, so a double-tap raced through validation twice before anything was
    // set. Claiming the handler is now the first thing it does, and the
    // validation return releases the claim on its way out.
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    if (!newName.trim() || !newCompany.trim()) {
      toast.warning('Required', 'Worker name and company are required');
      savingRef.current = false;
      setSaving(false);
      return;
    }
    const ident = draftIdent || {
      workerId: `manual_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`,
      date: todayISO(),
    };
    const key = draftKey({ projectId, logType: LOG_TYPE, date: ident.date, workerId: ident.workerId });
    const status = isAffirmedSignature(newCpSignature) ? 'submitted' : 'draft';
    const data = {
      worker_id: ident.workerId,
      worker_name: newName.trim(),
      worker_company: newCompany.trim(),
      worker_trade: newTrade.trim(),
      osha_number: newOsha.trim(),
      orientation_number: newOrientationNum.trim(),
      checklist: newChecklist,
      completed_at: new Date().toISOString(),
      worker_signature: null,
      language_provided: 'en',
    };
    try {
      // 1. The orientation is durable on device before any network is attempted
      //    — this is what makes a gate-side orientation possible with no signal.
      //    Same caveat as the sign path: writeDraft returns false and never
      //    throws. The offline branch below announces "Signed & locked on this
      //    device", and this result is the only thing that makes it true.
      let localSaved = false;
      try {
        localSaved = await writeDraft(key, { data, cp_signature: newCpSignature, cp_name: newCpName, status });
      } catch (_e) {
        // A THROW IS A FALSE — see the note at the same guard in hot_work.
        localSaved = false;
      }

      const localRecord = {
        _local_id: ident.workerId,
        project_id: projectId,
        log_type: LOG_TYPE,
        date: ident.date,
        data,
        cp_signature: newCpSignature,
        cp_name: newCpName,
        status,
        _pending: true,
      };
      let next = [localRecord, ...orientations];
      setOrientations(next);
      await writeCachedList(projectId, next);

      // 2. Best-effort push; on failure the key goes in the pending-push list
      //    for the Phase B reconnect flush and the card stays flagged.
      try {
        const created = await logbooksAPI.create({
          project_id: projectId,
          log_type: LOG_TYPE,
          date: ident.date,
          cp_signature: newCpSignature,
          cp_name: newCpName,
          status,
          data,
        });
        await setDraftBackendId(key, created.id || created._id);
        await clearPending(key);
        next = next.map(o => (o._local_id === ident.workerId ? { ...created, _pending: false } : o));
        setOrientations(next);
        await writeCachedList(projectId, next);
        if (status === 'submitted') {
          toast.success('Signed & locked', 'Orientation signed and locked. Corrections require an amendment.');
        } else {
          toast.success('Created', 'Orientation record added');
        }
      } catch (pushErr) {
        // NEITHER COPY EXISTS. The optimistic row went into the list above, but
        // the reconnect drain reads the DRAFT store and nothing else — so with
        // no draft that row would sit there looking filed, unsyncable, and (once
        // frozen) not even signable. It is rolled back rather than left: the
        // entries are not lost, because the add form is still standing with them
        // in it (this return skips the reset below), and that is now the only
        // copy. Nothing is queued and nothing is frozen.
        if (!localSaved) {
          console.warn('Orientation push deferred but the LOCAL SAVE FAILED; not queued.');
          await recordFinalizeError(key, 'LOCAL_SAVE_FAILED', key, 'local');
          setOrientations(orientations);
          await writeCachedList(projectId, orientations);
          toast.error(
            'Not saved — nothing was filed',
            'This device could not store the orientation, and it did not reach the server either. Nothing was filed and nothing is queued to retry. Free up space on the device, then add it again.',
          );
          return;
        }
        await markPending(key);
        console.warn('Orientation push deferred (will sync on reconnect):', pushErr?.message);
        // ON THIS DEVICE ONLY, on the CREATE path as well. Both success toasts
        // below say "on this device" and then leave; this is what is still
        // there when he comes back to the worker's card. Recorded against the
        // key: an offline create has no server id yet.
        await recordFinalizeError(key, 'NOT_ON_SERVER', key, 'unsynced');
        if (status === 'submitted') {
          toast.success(
            'Signed & locked on this device',
            'Orientation signed and locked on this device — it syncs when you reconnect.',
          );
        } else {
          toast.success('Saved on this device', 'Orientation recorded — it syncs when you reconnect');
        }
      }

      // Signed at creation => frozen at creation. Runs AFTER the push branch so
      // the success path's setDraftBackendId still lands (writeDraft no-ops once
      // the draft is finalized), and it runs on the failure path too so an
      // offline gate-side orientation is locked on device right away. An unsigned
      // draft is NOT frozen — it is still open for a signature from its card.
      if (status === 'submitted') {
        const froze = await freezeIfImmediate(key, LOG_TYPE);
        if (froze) {
          next = next.map(o => (
            (o._local_id === ident.workerId || workerIdOf(o) === ident.workerId)
              ? { ...o, is_locked: true }
              : o
          ));
          setOrientations(next);
          await writeCachedList(projectId, next);
        }
      }

      // Reset form and retire the in-progress draft pointer
      setNewName('');
      setNewCompany('');
      setNewTrade('');
      setNewOsha('');
      setNewOrientationNum('');
      setNewChecklist({});
      setShowAddForm(false);
      setDraftIdent(null);
      await writeDraftPointer(projectId, null);
      await autoSave(newCpName, newCpSignature).catch(() => {});
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not create orientation');
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const toggleNewChecklistItem = (key) => {
    setNewChecklist(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const getChecklistCompletion = (checklist) => {
    if (!checklist) return { checked: 0, total: ALL_KEYS.length };
    const checked = ALL_KEYS.filter(k => checklist[k]).length;
    return { checked, total: ALL_KEYS.length };
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
              <Text style={styles.headerTitle}>Subcontractor Safety Orientation</Text>
              <Text style={styles.headerSub}>
                {orientations.length} worker{orientations.length !== 1 ? 's' : ''} on record
              </Text>
            </View>
          </View>
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >

          {/* The roster refresh failed. Say so — and say whether what is on
              screen is a saved copy. An empty list here must never be presented
              as "nobody has been oriented". */}
          {fetchState !== 'ok' && (
            <OfflineNotice
              mode={fetchState}
              cachedCount={orientations.length}
              detail={fetchState === 'offline' && orientations.length === 0
                ? 'No saved orientations on this device yet. You can still record a new one below — it syncs when you reconnect.'
                : undefined}
            />
          )}

          {/* Add new button */}
          <GlassButton
            title="+ Add Manual Orientation"
            icon={<Plus size={16} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => (showAddForm ? setShowAddForm(false) : openAddForm())}
            style={styles.addBtn}
          />

          {/* Manual add form */}
          {showAddForm && (
            <GlassCard style={styles.addForm}>
              <Text style={styles.sectionTitle}>New Orientation Record</Text>

              {[
                { label: 'Worker Full Name *', value: newName, setter: setNewName },
                { label: 'Company *', value: newCompany, setter: setNewCompany },
                { label: 'Trade', value: newTrade, setter: setNewTrade },
                { label: 'OSHA Card #', value: newOsha, setter: setNewOsha },
                { label: 'Orientation # (optional)', value: newOrientationNum, setter: setNewOrientationNum },
              ].map((f) => (
                <View key={f.label} style={styles.fieldRow}>
                  <Text style={styles.fieldLabel}>{f.label}</Text>
                  <TextInput
                    style={styles.fieldInput}
                    value={f.value}
                    onChangeText={f.setter}
                    placeholder="—"
                    placeholderTextColor={colors.text.subtle}
                    autoCapitalize="words"
                  />
                </View>
              ))}

              {/* Checklist */}
              <Text style={[styles.sectionTitle, { marginTop: spacing.md }]}>
                Safety Topics Reviewed
              </Text>
              {ORIENTATION_SECTIONS.map((section) => (
                <View key={section.section} style={styles.sectionBlock}>
                  <Text style={styles.sectionLabel}>{section.section}</Text>
                  {section.items.map((item) => (
                    <Pressable
                      key={item.key}
                      onPress={() => toggleNewChecklistItem(item.key)}
                      style={styles.checkRow}
                    >
                      <View style={[
                        styles.checkbox,
                        newChecklist[item.key] && styles.checkboxActive,
                      ]}>
                        {newChecklist[item.key] && (
                          <CheckCircle size={14} strokeWidth={2} color={semantic.verified} />
                        )}
                      </View>
                      <Text style={[
                        styles.checkLabel,
                        newChecklist[item.key] && styles.checkLabelActive,
                      ]}>
                        {item.label}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              ))}

              {/* CP signature */}
              <Text style={[styles.sectionTitle, { marginTop: spacing.md }]}>CP Signature</Text>
              {newCpSignature && (
                <View style={styles.autoSignBadge}>
                  <CheckCircle size={14} strokeWidth={1.5} color={semantic.verified} />
                  <Text style={styles.autoSignText}>Auto-filled from your saved profile</Text>
                </View>
              )}
              <SignaturePad
                title="Competent Person Signature"
                signerName={newCpName}
                onNameChange={setNewCpName}
                existingSignature={newCpSignature}
                onSignatureCapture={setNewCpSignature}
              />

              <View style={styles.formActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => setShowAddForm(false)}
                  style={styles.cancelBtn}
                />
                {/* `disabled` EXPLICITLY, not left to `loading`. GlassButton
                    happens to pass `disabled || loading` down to the Pressable
                    today, so the loading prop disables it as a side effect —
                    but that is GlassButton's internal choice and nothing here
                    depends on it on purpose. This says what it means, and it
                    keeps meaning it if the spinner ever moves. */}
                <GlassButton
                  title={saving ? 'Saving...' : 'Save Orientation'}
                  onPress={handleCreateNew}
                  loading={saving}
                  disabled={saving}
                  style={styles.saveBtn}
                />
              </View>
            </GlassCard>
          )}

          {/* Existing orientation cards. The "none yet" card is only honest when
              the server actually answered — otherwise the notice above stands in. */}
          {orientations.length === 0 ? (
            fetchState === 'ok' ? (
              <GlassCard style={styles.emptyCard}>
                <ShieldCheck size={40} strokeWidth={1} color={colors.text.subtle} />
                <Text style={styles.emptyTitle}>No orientations yet</Text>
                <Text style={styles.emptySubtitle}>
                  Orientations are automatically created when workers register via NFC.
                  You can also add one manually above.
                </Text>
              </GlassCard>
            ) : null
          ) : (
            <>
              <Text style={styles.listLabel}>ORIENTATION RECORDS</Text>
              {orientations.map((orient, index) => {
                const d = orient.data || {};
                const isExpanded = expandedIndex === index;
                const isSigned = orient.status === 'submitted' && orient.cp_signature;
                const isLocked = !!orient.is_locked;
                const { checked, total } = getChecklistCompletion(d.checklist);

                return (
                  <GlassCard key={orient._id || orient.id || orient._local_id || index} style={styles.orientCard}>

                    {/* Card header — always visible */}
                    <Pressable
                      style={styles.orientHeader}
                      onPress={() => setExpandedIndex(isExpanded ? null : index)}
                    >
                      <View style={styles.orientAvatar}>
                        <User size={18} strokeWidth={1.5} color={colors.text.secondary} />
                      </View>
                      <View style={styles.orientInfo}>
                        <Text style={styles.orientName}>{d.worker_name || 'Unknown Worker'}</Text>
                        <Text style={styles.orientMeta}>
                          {d.worker_company || '—'}
                          {d.worker_trade ? ` · ${d.worker_trade}` : ''}
                        </Text>
                        <Text style={styles.orientDate}>
                          {d.completed_at
                            ? new Date(d.completed_at).toLocaleDateString('en-US', {
                                month: 'short', day: 'numeric', year: 'numeric',
                              })
                            : orient.date}
                        </Text>
                        {/* THE DOCUMENT HAS A HISTORY, AND THE HEAD LOOKS LIKE
                            AN ORIGINAL WITHOUT THIS. A reader cannot tell an
                            amended record from a first draft, which is how six
                            rows read as six duplicates. The count is documents
                            in the chain, so a record corrected four times is
                            five links. */}
                        {orient._chain_length > 1 && (
                          <Text style={styles.orientDate}>
                            {`Corrected ${orient._chain_length - 1} time`}
                            {orient._chain_length - 1 === 1 ? '' : 's'}
                          </Text>
                        )}
                        {/* AN OPEN CORRECTION IS NOT THE RECORD YET, and the row
                            must not imply it is. The card shows the last SIGNED
                            link — that is what stands — and says plainly that
                            something unsigned is waiting. */}
                        {(orient._open_corrections || []).length === 1 && (
                          <Text style={styles.orientDate}>
                            Correction open — not signed yet
                          </Text>
                        )}
                        {/* THE FORK, SHOWN AS A FORK. Two unsigned children of
                            one parent are two competing claims about what the
                            record should say, and neither is the record while
                            both are unsigned. Picking one to display would be
                            choosing a winner silently — so both are counted and
                            the consequence of signing is stated, because
                            "supersedes the other" is the part he cannot work
                            out from the screen. */}
                        {(orient._open_corrections || []).length > 1 && (
                          <Text style={styles.orientDate}>
                            {`${orient._open_corrections.length} competing corrections open — `}
                            signing either supersedes the other
                          </Text>
                        )}
                        {orient._pending && (
                          <View style={styles.pendingRow}>
                            <CloudOff size={11} strokeWidth={1.8} color={semantic.attention} />
                            <Text style={styles.pendingText}>Saved on this device — syncs when you reconnect</Text>
                          </View>
                        )}
                      </View>
                      <View style={styles.orientRight}>
                        <View style={[styles.statusBadge, isSigned ? styles.statusSigned : styles.statusPending]}>
                          {isSigned
                            ? <CheckCircle size={12} strokeWidth={2} color={semantic.verified} />
                            : null}
                          <Text style={[styles.statusText, isSigned ? styles.statusTextSigned : [styles.statusTextPending, { color: semantic.attention }]]}>
                            {isSigned ? 'Signed' : 'Needs CP sig'}
                          </Text>
                        </View>
                        {isExpanded
                          ? <ChevronUp size={16} strokeWidth={1.5} color={colors.text.muted} />
                          : <ChevronDown size={16} strokeWidth={1.5} color={colors.text.muted} />}
                      </View>
                    </Pressable>

                    {/* Expanded detail */}
                    {isExpanded && (
                      <View style={styles.orientDetail}>
                        <View style={styles.orientDetailDivider} />

                        {/* Worker details */}
                        <View style={styles.detailGrid}>
                          {[
                            { label: 'OSHA #', value: d.osha_number },
                            { label: 'Orientation #', value: d.orientation_number },
                          ].filter(f => f.value).map((f) => (
                            <View key={f.label} style={styles.detailRow}>
                              <Text style={styles.detailLabel}>{f.label}</Text>
                              <Text style={styles.detailValue}>{f.value}</Text>
                            </View>
                          ))}
                        </View>

                        {/* Language provided badge */}
                        {d.language_provided && (
                          <View style={{
                            flexDirection: 'row', alignItems: 'center', gap: 4,
                            marginTop: spacing.xs, marginBottom: spacing.sm,
                            paddingHorizontal: spacing.sm, paddingVertical: 3,
                            backgroundColor: 'rgba(59,130,246,0.1)',
                            borderRadius: borderRadius.full,
                            borderWidth: 1, borderColor: 'rgba(59,130,246,0.2)',
                            alignSelf: 'flex-start',
                          }}>
                            <Text style={{ fontSize: 11, fontWeight: '600', color: '#60a5fa' }}>
                              🌐 Orientation in: {d.language_provided === 'es' ? 'Español' : 'English'}
                            </Text>
                          </View>
                        )}

                        {/* Checklist summary */}
                        <View style={styles.checklistSummary}>
                          <Text style={styles.checklistSummaryLabel}>
                            Checklist: {checked}/{total} items reviewed
                          </Text>
                          <View style={styles.checklistBar}>
                            <View style={[
                              styles.checklistBarFill,
                              { width: `${Math.round((checked / total) * 100)}%` },
                            ]} />
                          </View>
                        </View>

                        {/* Show all checklist items */}
                        {ORIENTATION_SECTIONS.map((section) => (
                          <View key={section.section} style={styles.sectionBlock}>
                            <Text style={styles.sectionLabel}>{section.section}</Text>
                            {section.items.map((item) => {
                              const isChecked = d.checklist ? !!d.checklist[item.key] : false;
                              return (
                                <View key={item.key} style={styles.readonlyCheckRow}>
                                  <View style={[styles.checkbox, isChecked && styles.checkboxActive]}>
                                    {isChecked && <CheckCircle size={12} strokeWidth={2} color={semantic.verified} />}
                                  </View>
                                  <Text style={[styles.checkLabel, isChecked && styles.checkLabelActive]}>
                                    {item.label}
                                  </Text>
                                </View>
                              );
                            })}
                          </View>
                        ))}

                        {/* CP signature — add if not yet signed AND not finalized.
                            A finalized (is_locked) row must never be re-signable. */}
                        {/* NO TRADE, NO SUBMIT. Stated on the row itself, with
                            the fix beside it — a refusal the CP meets only
                            after signing, on a screen listing a dozen workers,
                            names nobody and offers nothing. */}
                        {!isSigned && !isLocked && !String(d.worker_trade || '').trim() && (
                          <View style={styles.tradeMissingBox}>
                            <Text style={styles.tradeMissingTitle}>No trade assigned</Text>
                            <Text style={styles.tradeMissingText}>
                              This orientation cannot be signed until {d.worker_name || 'this worker'} has a trade.
                            </Text>
                            <Pressable
                              style={styles.tradeAssignBtn}
                              accessibilityRole="button"
                              onPress={() => setAssigningTrade({ orientation: orient, value: '' })}
                            >
                              <Text style={styles.tradeAssignBtnText}>Assign trade</Text>
                            </Pressable>
                          </View>
                        )}

                        {!isSigned && !isLocked && (
                          <OrientationSignaturePanel
                          onSign={(sig, name) => handleSignExisting(orient, sig, name)}
                          />
                        )}

                        {isSigned && (
                          <View style={styles.signedBanner}>
                            <CheckCircle size={16} strokeWidth={1.5} color={semantic.verified} />
                            <Text style={styles.signedBannerText}>
                              Signed by {orient.cp_name}
                            </Text>
                          </View>
                        )}

                        {/* Per-card lock / amend. An orientation is an IMMEDIATE
                            log: signing already froze this row, so Finalize is
                            never offered (canFinalize false, and logType makes
                            the bar hide it regardless). A locked row shows the
                            read-only banner + Amend (which mints a new child row). */}
                        <LogbookLockBar
                          locked={isLocked}
                          logId={orient.id || orient._id}
                          canFinalize={false}
                          logType={LOG_TYPE}
                          onFinalized={fetchData}
                          onAmended={fetchData}
                        />
                      </View>
                    )}

                  </GlassCard>
                );
              })}
            </>
          )}
        </ScrollView>
      </SafeAreaView>

      {/* Assign the missing trade without leaving the screen. */}
      <Modal
        visible={!!assigningTrade}
        transparent
        animationType="fade"
        onRequestClose={() => setAssigningTrade(null)}
      >
        <View style={styles.tradeModalOverlay}>
          <GlassCard style={styles.tradeModalCard}>
            <Text style={styles.sectionTitle}>Assign a trade</Text>
            <Text style={styles.tradeMissingText}>
              {(assigningTrade?.orientation?.data || {}).worker_name || 'This worker'}
              {' — the orientation cannot be signed without one.'}
            </Text>
            <TextInput
              style={styles.fieldInput}
              value={assigningTrade?.value || ''}
              onChangeText={(v) => setAssigningTrade((prev) => ({ ...prev, value: v }))}
              placeholder="Trade"
              placeholderTextColor={colors.text.subtle}
              autoCapitalize="words"
              autoFocus
            />
            <View style={styles.tradeModalActions}>
              <GlassButton title="Cancel" onPress={() => setAssigningTrade(null)} />
              <GlassButton title="Assign" onPress={handleAssignTrade} />
            </View>
          </GlassCard>
        </View>
      </Modal>
    </AnimatedBackground>
  );
}

/**
 * Inline signature panel for adding CP sig to an existing orientation.
 * Separate component so each card can have its own signature state.
 */
function OrientationSignaturePanel({ onSign }) {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const { cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave: innerAutoSave } = useCpProfile();
  const tFinalize = useT('finalize');
  const hintKey = affirmationHintKey(cpSignature, profileLoaded);
  const [saving, setSaving] = useState(false);
  // Same synchronous guard as handleCreateNew, and it matters MORE here.
  // This panel FREEZES the record — the signature is the freeze for an
  // IMMEDIATE type — so a second entry is not a duplicate draft, it is a
  // second finalize against something already locked.
  const savingRef = useRef(false);

  const handleSign = async () => {
    // Claimed before the affirmation check, released if that check turns the
    // tap away — the same order as handleCreateNew, for the same reason.
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    if (!isAffirmedSignature(cpSignature)) {
      savingRef.current = false;
      setSaving(false);
      return;
    }
    try {
      await innerAutoSave(cpName, cpSignature);
      await onSign(cpSignature, cpName);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return (
    <View style={s.signPanel}>
      <Text style={s.sectionTitle}>Add Your CP Signature</Text>
      <SignaturePad
        title="Competent Person Signature"
        signerName={cpName}
        onNameChange={setCpName}
        existingSignature={cpSignature}
        onSignatureCapture={setCpSignature}
      />
      <GlassButton
        title={saving ? 'Signing...' : 'Sign This Orientation'}
        icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
        onPress={handleSign}
        loading={saving}
        // `saving` explicitly, alongside the affirmation gate — the button is
        // dead both while there is nothing to sign and while a sign is in
        // flight, and neither reason is left to GlassButton to infer.
        disabled={saving || !isAffirmedSignature(cpSignature)}
        style={s.signBtn}
      />
      {/* This panel FREEZES the record — status is derived from the signature,
          so there is no draft to come back to. A dead button here with no
          reason is the worst version of the dead button. */}
      {!!hintKey && <Text style={s.signHint}>{tFinalize(hintKey)}</Text>}
    </View>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: { flex: 1 },
  loadingCenter: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.08),
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  headerTitle: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 11, color: colors.text.muted },
  scrollView: { flex: 1 },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 100,
    maxWidth: 720,
    width: '100%',
    alignSelf: 'center',
  },
  addBtn: { marginBottom: spacing.md },
  addForm: { marginBottom: spacing.md, padding: spacing.lg },
  sectionTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: spacing.sm,
  },
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
    flex: 1.5,
    fontSize: 14,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: withAlpha('#ffffff', 0.04),
    borderRadius: borderRadius.sm,
  },
  sectionBlock: { marginBottom: spacing.md },
  sectionLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: spacing.sm,
    marginTop: spacing.sm,
  },
  checkRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  readonlyCheckRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
    opacity: 0.9,
  },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.15),
    backgroundColor: withAlpha('#ffffff', 0.04),
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 1,
    flexShrink: 0,
  },
  checkboxActive: {
    backgroundColor: semantic.verifiedBg,
    borderColor: semantic.verified,
  },
  checkLabel: { flex: 1, fontSize: 13, color: colors.text.muted, lineHeight: 18 },
  checkLabelActive: { color: colors.text.secondary },
  autoSignBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.md,
    padding: spacing.sm,
    backgroundColor: semantic.verifiedBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: semantic.verifiedBorder,
  },
  autoSignText: { fontSize: 12, color: semantic.verified },
  formActions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md },
  cancelBtn: { flex: 1 },
  saveBtn: {
    flex: 2,
    backgroundColor: 'rgba(139,92,246,0.2)',
    borderColor: 'rgba(139,92,246,0.4)',
  },
  emptyCard: {
    alignItems: 'center',
    padding: spacing.xxl,
    gap: spacing.md,
  },
  emptyTitle: { fontSize: 17, fontWeight: '500', color: colors.text.primary },
  emptySubtitle: {
    fontSize: 13,
    color: colors.text.muted,
    textAlign: 'center',
    lineHeight: 20,
  },
  listLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
    marginTop: spacing.sm,
  },
  orientCard: { marginBottom: spacing.sm, padding: 0, overflow: 'hidden' },
  tradeMissingBox: {
    marginTop: spacing.md, padding: spacing.md,
    borderRadius: borderRadius.md, borderWidth: 1,
    borderColor: semantic.attentionBorder, backgroundColor: semantic.attentionBg,
    gap: spacing.xs,
  },
  tradeMissingTitle: {
    fontSize: typography.sizes.sm, fontWeight: '700', color: colors.text.primary,
  },
  tradeMissingText: { fontSize: typography.sizes.sm, color: colors.text.secondary },
  tradeAssignBtn: {
    marginTop: spacing.sm, minHeight: 44, alignItems: 'center',
    justifyContent: 'center', borderRadius: borderRadius.md,
    borderWidth: 1, borderColor: semantic.attentionBorder,
  },
  tradeAssignBtnText: {
    fontSize: typography.sizes.sm, fontWeight: '700', color: colors.text.primary,
  },
  tradeModalOverlay: {
    flex: 1, alignItems: 'center', justifyContent: 'center',
    padding: spacing.lg, backgroundColor: withAlpha('#000000', 0.6),
  },
  tradeModalCard: { width: '100%', padding: spacing.lg, gap: spacing.sm },
  tradeModalActions: {
    flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm,
  },
  orientHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
  },
  orientAvatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(139,92,246,0.15)',
    borderWidth: 1,
    borderColor: 'rgba(139,92,246,0.3)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  orientInfo: { flex: 1 },
  orientName: { fontSize: 15, fontWeight: '500', color: colors.text.primary },
  orientMeta: { fontSize: 12, color: colors.text.muted, marginTop: 1 },
  orientDate: { fontSize: 11, color: colors.text.subtle, marginTop: 2 },
  pendingRow: { flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 3 },
  pendingText: { fontSize: 10, color: semantic.attention, fontWeight: '600', flexShrink: 1 },
  orientRight: { alignItems: 'flex-end', gap: spacing.xs },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderRadius: borderRadius.full,
  },
  statusSigned: { backgroundColor: semantic.verifiedBg },
  statusPending: { backgroundColor: semantic.attentionBg },
  statusText: { fontSize: 11, fontWeight: '600' },
  statusTextSigned: { color: semantic.verified },
  statusTextPending: {},
  orientDetail: { paddingHorizontal: spacing.md, paddingBottom: spacing.md },
  orientDetailDivider: {
    height: 1,
    backgroundColor: withAlpha('#ffffff', 0.08),
    marginBottom: spacing.md,
  },
  detailGrid: { marginBottom: spacing.sm },
  detailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.04),
  },
  detailLabel: { fontSize: 11, color: colors.text.muted, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5 },
  detailValue: { fontSize: 13, color: colors.text.primary },
  checklistSummary: { marginBottom: spacing.md },
  checklistSummaryLabel: { fontSize: 12, color: colors.text.muted, marginBottom: spacing.xs },
  checklistBar: {
    height: 4,
    backgroundColor: withAlpha('#ffffff', 0.08),
    borderRadius: 2,
    overflow: 'hidden',
  },
  checklistBarFill: {
    height: '100%',
    backgroundColor: '#8b5cf6',
    borderRadius: 2,
  },
  signPanel: { marginTop: spacing.md },
  signHint: {
    fontSize: typography.sizes.fine, color: semantic.attention,
    textAlign: 'center', marginTop: spacing.sm,
  },
  signBtn: {
    marginTop: spacing.md,
    backgroundColor: 'rgba(139,92,246,0.2)',
    borderColor: 'rgba(139,92,246,0.4)',
  },
  signedBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.md,
    padding: spacing.sm,
    backgroundColor: semantic.verifiedBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: semantic.verifiedBorder,
  },
  signedBannerText: { fontSize: 13, color: semantic.verified, fontWeight: '500' },
  });
}
