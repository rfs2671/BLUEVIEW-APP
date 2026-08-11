/**
 * DAILY JOBSITE LOG — NYC DOB 3301-02, as a five-step stepper.
 *
 * WHO THIS IS FOR. A Competent Person who is older and not technical, on his
 * own phone, outdoors, gloved, one-handed. That outranks aesthetics wherever
 * the two conflict. The rules it is built to, all of them load-bearing:
 *
 *   • TAP ONLY. No swipe, no long-press, no hidden gesture. The photo strip is
 *     a wrapping grid, not a horizontal scroller, because a horizontal
 *     scroller IS a swipe affordance.
 *   • 56pt minimum touch target (touchTarget.min), applied as a minimum, never
 *     as a size.
 *   • ONE primary action per screen, and it is the largest element on it.
 *   • No screen needs more than twelve words read to know what to do.
 *   • Light, high-contrast surfaces (theme.outdoor) that do NOT flip with the
 *     app theme — direct sun does not care what theme the CP picked.
 *   • Every colour, size and spacing comes from the token file.
 *   • English. A logbook is a legal record filed with the DOB. The one place
 *     Spanish belongs is the sentence a worker signs, and SignaturePad owns
 *     that itself.
 *
 * WHAT CHANGED ABOUT THE RECORD, AND WHAT DID NOT. Every legal field the old
 * single-scroll form captured is still captured; only the capture method
 * changed. No field was added or removed. The one behavioural correction:
 *
 *   THE APP NO LONGER WRITES THE WORK DESCRIPTION. The previous screen seeded
 *   `work_description: r.trade`, so a signed log asserted that the Concrete
 *   crew performed "Concrete" — the app wrote that sentence, not the CP. Now
 *   the CP taps what actually happened and an unselected activity is EMPTY,
 *   never guessed. See composeSelection in src/utils/dailyJobsiteModel.js.
 *
 * WHERE THE DECISIONS LIVE. Anything that decides what reaches the signed
 * record — who was on site, whether the camera may open, whether an
 * observation is complete — is a pure function in
 * src/utils/dailyJobsiteModel.js so it can be executed by a test rather than
 * grepped. This file renders.
 */
import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
  Image, Modal, Platform,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { LinearGradient } from 'expo-linear-gradient';
import {
  ArrowLeft, ArrowRight, Check, Camera, X, ImageIcon, Plus, AlertTriangle, Lock,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import SignaturePad from '../../src/components/SignaturePad';
import LogbookLockBar from '../../src/components/LogbookLockBar';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI, weatherAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { useT } from '../../src/i18n';
import {
  spacing, borderRadius, typography, touchTarget, outdoor, outdoorShadow,
} from '../../src/styles/theme';
import CameraCaptureModal, { useCameraPrewarmPermission } from '../../src/components/CameraCaptureModal';
import { compressUnderCap } from '../../src/utils/compressPhoto';
import { easternToday } from '../../src/utils/dates';
import {
  draftKey, readDraft, writeDraft, setDraftBackendId, markPending, clearPending,
  persistActivityPhotos, markFinalized,
  // persistPhoto THROWS on a failed copy. That throw IS the offline photo
  // guarantee: it used to return the OS cache uri and say nothing, so the
  // draft recorded a path the app does not own, the cache was evicted, and the
  // photo was gone with nothing having reported it. Reverting it to a swallow
  // is a regression, not a simplification.
  persistPhoto, uploadCapturePhoto, uploadPendingActivityPhotos,
  photoNeedsUpload, hasPendingPhotoUploads,
} from '../../src/utils/logbookDrafts';
// finalizeErrorCode is the ONE place a FINALIZE_* code is pulled out of an
// axios error (and the one place that guarantees the server's English `detail`
// never reaches a screen); clearFinalizeError removes the drain's persistent
// "NOT LOCKED ON THE SERVER" banner once this screen finalizes for real;
// recordFinalizeError RAISES that same banner, so a refusal taken here in the
// foreground leaves the identical durable trace a background one does.
import { finalizeErrorCode, clearFinalizeError, recordFinalizeError } from '../../src/utils/draftSync';
// The app-wide OFFLINE discriminator — the same one settleFetch is built on.
// "Offline" here has to mean what it means everywhere else: no response at all.
import { isOfflineError, settleFetch } from '../../src/utils/offlineState';
import * as ImagePicker from 'expo-image-picker';
import {
  EMPTY_ACTIVITY, EMPTY_OBSERVATION, buildCrewsFromRoster, rosterIdIndex,
  composeSelection, cameraReady, resolveRosterId, isUnboundCrew,
  isUnassignedWorkerRow, workRows, tradeLabel,
  INSPECTION_PASS, INSPECTION_FAIL, inspectionRow, incompleteInspections,
  deriveGeneralDescription,
  observationComplete, incompleteObservations, formatLogDate, formatCheckInTime,
  rosterKey,
} from '../../src/utils/dailyJobsiteModel';

// The DOB form number is an identifier, not prose — identical in every
// language — so it is a module constant rather than a catalogue string.
const FORM_NUMBER = 'NYC DOB 3301-02';

const TOTAL_STEPS = 5;

// ── THE PHOTO CAP: 10 PER SUBCONTRACTOR, AGGREGATED ─────────────────────────
// Counted across EVERY row that names the sub, not per row. There is no
// project-wide cap. The buckets are:
//
//   • each distinct subcontractor_id  -> 10, shared across all of its rows
//   • each row with NO roster id      -> its own 10, NEVER shared
//   • each blank-company row          -> its own 10, NEVER merged
//
// The last two are the point. A CP standing on a jobsite with three crews the
// admin has not entered yet is looking at an ADMIN failure, not committing an
// abuse. Making those rows share one bucket would take the evidence he can
// collect away from him as a punishment for someone else's unfinished data
// entry.
const MAX_PHOTOS_PER_SUBCONTRACTOR = 10;

const photoBucketKey = (activity, index) => {
  const subId = String(activity?.subcontractor_id || '').trim();
  if (subId) return `sub:${subId}`;
  const rowId = String(activity?.activity_id || '').trim();
  if (rowId) return `row:${rowId}`;
  return `row-index:${index}`;
};

/** Photos already attached to `index`'s bucket, across every row in it. */
const photosInBucket = (rows, index) => {
  const key = photoBucketKey(rows?.[index], index);
  let n = 0;
  (rows || []).forEach((a, i) => {
    if (photoBucketKey(a, i) === key) n += (a?.photos || []).length;
  });
  return n;
};

/** How many more photos `index` may still take. Never negative. */
const bucketRemaining = (rows, index) => Math.max(
  0, MAX_PHOTOS_PER_SUBCONTRACTOR - photosInBucket(rows, index),
);

// The in-process camera is native-only (vision-camera cannot run in a browser).
const MOBILE_CAPTURE = Platform.OS !== 'web';

let photoSeq = 0;
const newPhotoId = () => `cap_${Date.now()}_${(photoSeq += 1)}`;

// A saved photo's full-size `base64` is DROPPED when its log is finalized
// (server.py _purge_finalized_photo_base64), and only once R2 has confirmed
// both derivatives. `thumb_base64` is the ~400px copy written in its place and
// is never removed, so it is the last inline copy any screen can count on.
const inlinePhotoData = (b64) => (
  !b64 ? null : (b64.startsWith('data:') ? b64 : `data:image/jpeg;base64,${b64}`)
);

// Has the backend already purged this photo's full-size copy? If so its `uri`
// must NOT be re-encoded on save — that would push the full-size base64 back
// into the document the purge just shrank, without any of the R2 proof the
// purge required.
const isPurgedPhoto = (photo) => Boolean(
  photo && (photo.base64_purged_at || photo.thumb_base64),
);

// Patch ONE photo wherever it currently lives, matched by its CAPTURE ID — not
// by (row index, photo index). A background upload can land after the CP has
// added a row, deleted a sibling or switched crews, and both indexes move when
// he does. The id does not.
const patchPhoto = (rows, photoId, patch) => (rows || []).map((a) => (
  ((a.photos || []).some((p) => p.id === photoId))
    ? { ...a, photos: a.photos.map((p) => (p.id === photoId ? { ...p, ...patch } : p)) }
    : a
));

const dropPhoto = (rows, photoId) => (rows || []).map((a) => (
  ((a.photos || []).some((p) => p.id === photoId))
    ? { ...a, photos: a.photos.filter((p) => p.id !== photoId) }
    : a
));

/**
 * ONE photo, as it is written into the logbook document.
 *
 * THE DOCUMENT DOES NOT CARRY FULL-SIZE IMAGE DATA. A logbook is one MongoDB
 * document with a 16MB ceiling, and re-encoding each photo to base64 at save
 * time cost ~200KB apiece: ten subcontractors at ten photos each measured
 * 20,510,438 bytes, so the END-OF-DAY save was rejected outright, on a signed
 * record, after the CP had done the whole day. Photos go to R2 as they are
 * taken; the row carries the key.
 */
const photoForPayload = (photo) => {
  if (!photo || typeof photo !== 'object') return photo;
  const { pending, id, persist_failed, ...stored } = photo; // eslint-disable-line no-unused-vars
  if (stored.original_r2_key) {
    const { upload_pending, upload_rejected, ...done } = stored; // eslint-disable-line no-unused-vars
    return done;
  }
  if (stored.base64 || isPurgedPhoto(stored)) return stored;
  if (!stored.uri) return null;
  return { ...stored, upload_pending: true };
};

// The closed set of conditions the weather API is expected to report. No
// longer rendered as a chooser — weather is fetched, not picked — but kept
// as the documented vocabulary that `weather` on the record draws from.
export const WEATHER_OPTIONS = ['Sunny', 'Cloudy', 'Rainy', 'Windy', 'Snow', 'Fog', 'Stormy'];

const EQUIPMENT_ITEMS = [
  { key: 'elevator', label: 'Elevator' },
  { key: 'compressor', label: 'Compressor' },
  { key: 'pump', label: 'Pump' },
  { key: 'hoist', label: 'Hoist' },
  { key: 'boom_crane', label: 'Boom/Crane' },
  { key: 'other_equipment', label: 'Other' },
];

const CHECKLIST_ITEMS = [
  { key: 'street_frontage', label: 'Street Frontage' },
  { key: 'fire_safety', label: 'Fire Safety' },
  { key: 'perimeter_fence', label: 'Perimeter Fence' },
  { key: 'fall_protections', label: 'Fall Protections' },
  { key: 'neighbors_property', label: "Neighbor's Property" },
  { key: 'license_spot_check', label: 'License Spot-Check' },
  { key: 'plans', label: 'Plans' },
  { key: 'permits', label: 'Permits' },
  { key: 'other_checklist', label: 'Other' },
];

/**
 * Location chips are DERIVED, not invented.
 *
 * There is no location vocabulary anywhere in this codebase and no endpoint
 * serving one, so authoring a fixed list of jobsite areas here would be
 * putting made-up terms into a legal record. What the project record actually
 * knows is how many storeys the building has (`building_stories`,
 * backend/server.py:1472), so the floors are offered as chips and everything
 * else goes through "Somewhere else", which is free text the CP writes
 * himself. A project with no storey count set gets no floor chips at all —
 * that is the honest state, and the CP still has free text.
 */
const floorChips = (stories) => {
  const n = parseInt(stories, 10);
  if (!Number.isFinite(n) || n <= 0) return [];
  return Array.from({ length: Math.min(n, 60) }, (_, i) => ({
    id: `floor_${i + 1}`, label: `Floor ${i + 1}`,
  }));
};

const OTHER_LOCATION_ID = 'location_other';
const OTHER_ACTIVITY_ID = 'other';

export default function DailyJobsiteLog() {
  const router = useRouter();
  const params = useLocalSearchParams();
  const projectId = params.projectId;
  // A date derived for a query or a record uses the Eastern helper. On the UTC
  // clock this default would ask for TOMORROW from 20:00 EDT and file the log
  // under it. That bug shipped thirteen times; this is not the fourteenth.
  const date = params.date || easternToday();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave } = useCpProfile();
  const t = useT('dailyJobsite');
  // LogbookLockBar's namespace, reused verbatim so a server refusal reads
  // identically wherever the CP meets it.
  const tFinalize = useT('finalize');
  const s = useMemo(() => buildStyles(), []);

  /**
   * The server names the condition, the client owns the wording — the same
   * rule LogbookLockBar's gateCopy follows, over the same `finalize`
   * namespace. `translate` returns the KEY on a miss, which is how an unmapped
   * code is detected; the server's English `detail` is never rendered.
   */
  const gateCopy = (code) => {
    if (!code) return tFinalize('genericError');
    const key = `code_${code}`;
    const copy = tFinalize(key);
    return copy && copy !== key ? copy : tFinalize('genericError');
  };
  // The cap is one number in one place; the copy takes it rather than
  // repeating it, so the message can never drift from what is enforced.
  const capMessage = () => t('photoCapBody').replace('{n}', String(MAX_PHOTOS_PER_SUBCONTRACTOR));
  const plural = (oneKey, otherKey, n) => (
    n === 1 ? t(oneKey) : t(otherKey).replace('{n}', String(n))
  );

  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(true);
  const [signing, setSigning] = useState(false);
  const [locked, setLocked] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);

  // ── The record ────────────────────────────────────────────────────────
  const [projectAddress, setProjectAddress] = useState('');
  const [buildingStories, setBuildingStories] = useState(null);
  const [weather, setWeather] = useState('');
  const [weatherTemp, setWeatherTemp] = useState('');
  const [weatherWind, setWeatherWind] = useState('');
  const [weatherLoading, setWeatherLoading] = useState(false);
  // 'ok' | 'offline' | 'error' | null(not attempted yet). This RIDES ON THE
  // RECORD. Weather is read-only now, so when the fetch fails the CP has no
  // way to fill it in — which means a blank weather field on a signed log
  // would be indistinguishable from a question nobody asked. The state is
  // what lets the log say "could not be retrieved" instead.
  const [weatherFetchState, setWeatherFetchState] = useState(null);
  const [generalDescription, setGeneralDescription] = useState('');
  const [activities, setActivities] = useState([]);
  const [equipmentOnSite, setEquipmentOnSite] = useState({});
  const [checklistItems, setChecklistItems] = useState({});
  const [observations, setObservations] = useState([]);
  const [visitorsDeliveries, setVisitorsDeliveries] = useState('');
  const [timeIn, setTimeIn] = useState('');
  const [timeOut, setTimeOut] = useState('');
  const [areasVisited, setAreasVisited] = useState('');

  // ── Roster integrity ──────────────────────────────────────────────────
  // A short roster shown as complete is a fabricated record, so what the
  // server could not confirm is carried and stated, never swallowed.
  const [rosterPartial, setRosterPartial] = useState(false);
  const [rosterCollapsed, setRosterCollapsed] = useState(0);

  // ── Chips ─────────────────────────────────────────────────────────────
  // CHIPS ARE PER TRADE, NOT PER PROJECT. An electrical crew was being offered
  // drywall because one shared list was fetched for the whole project and the
  // ranking keyed off the project's prior day. Keyed by the crew's roster
  // trade; '' is the unfiltered list, used for a crew whose trade is blank.
  const [chipsByTrade, setChipsByTrade] = useState({});
  const [chipsMetaByTrade, setChipsMetaByTrade] = useState({});
  const [expandedChips, setExpandedChips] = useState({});   // activity_id -> bool
  const [equipmentOpen, setEquipmentOpen] = useState(false);

  const rosterIdsRef = useRef(new Map());
  const activitiesRef = useRef([]);

  // ── Camera ────────────────────────────────────────────────────────────
  const capturingRef = useRef(false);
  const [cameraVisible, setCameraVisible] = useState(false);
  const [cameraTargetIndex, setCameraTargetIndex] = useState(null);
  const [sessionShotIds, setSessionShotIds] = useState([]);
  const pendingCompressRef = useRef([]);
  const compressedUriRef = useRef({});
  const uploadAttemptedRef = useRef(new Set());
  // Resolve the camera permission dialog HERE, at screen mount, so it is not
  // sitting between the capture tap and the preview. No-op on web.
  useCameraPrewarmPermission();

  // ── Modals ────────────────────────────────────────────────────────────
  const [addingCrew, setAddingCrew] = useState(null);      // {company, trade, num}
  const [otherPrompt, setOtherPrompt] = useState(null);    // {index, kind, value}
  const [photoLightbox, setPhotoLightbox] = useState(null);

  useEffect(() => { activitiesRef.current = activities; }, [activities]);

  useEffect(() => { fetchData(); }, [projectId, date]);

  // A string, not a call: the pending-marker guarantee is pinned on the
  // literal `markPending(_key)` shape in logbookPhotoR2.test.cjs.
  const _key = useMemo(
    () => draftKey({ projectId, logType: 'daily_jobsite', date }),
    [projectId, date],
  );

  const draftBody = useCallback((acts) => ({
    project_address: projectAddress,
    weather, weather_temp: weatherTemp, weather_wind: weatherWind,
    weather_fetch_state: weatherFetchState,
    general_description: generalDescription,
    activities: acts,
    equipment_on_site: equipmentOnSite,
    checklist_items: checklistItems,
    observations,
    visitors_deliveries: visitorsDeliveries,
    time_in: timeIn, time_out: timeOut, areas_visited: areasVisited,
  }), [
    projectAddress, weather, weatherTemp, weatherWind, weatherFetchState,
    generalDescription,
    equipmentOnSite, checklistItems, observations, visitorsDeliveries,
    timeIn, timeOut, areasVisited,
  ]);

  // ── AUTOSAVE ──────────────────────────────────────────────────────────
  // There is no "Save Draft" button. The CP never has to remember to save,
  // because forgetting would cost him a day of work he has already done.
  //
  // While the camera is OPEN this is skipped: every capture calls
  // setActivities, and running persistActivityPhotos (a file copy per photo)
  // plus a JSON.stringify of the whole draft lands on the JS thread while the
  // CP is lining up the next frame. `cameraVisible` is in the deps, so closing
  // the camera re-runs it immediately and writes everything the session
  // captured.
  useEffect(() => {
    if (loading || locked || cameraVisible) return undefined;
    const h = setTimeout(async () => {
      try {
        const persisted = await persistActivityPhotos(activitiesRef.current);
        await writeDraft(_key, {
          data: draftBody(persisted), cp_signature: cpSignature, cp_name: cpName,
        });
      } catch (_e) { /* autosave is best-effort; the next change retries */ }
    }, 800);
    return () => clearTimeout(h);
  }, [
    loading, locked, cameraVisible, activities, draftBody, cpSignature, cpName,
  ]);

  /** Flush the draft NOW — used when leaving a step, so a step boundary is a
   *  save point even if the app dies before the debounce fires. */
  const flushDraft = useCallback(async () => {
    if (locked) return;
    try {
      const persisted = await persistActivityPhotos(activitiesRef.current);
      await writeDraft(_key, {
        data: draftBody(persisted), cp_signature: cpSignature, cp_name: cpName,
      });
    } catch (_e) { /* best-effort */ }
  }, [locked, draftBody, cpSignature, cpName]);

  const fetchData = async () => {
    setLoading(true);
    try {
      // Local-first: the on-device draft wins, so the screen works fully
      // offline and a reopened log is exactly where the CP left it.
      const draft = await readDraft(_key);
      if (draft?.data && Object.keys(draft.data).length) {
        hydrate(draft.data);
        if (draft.finalized) { setLocked(true); markFinalized(_key); }
        setExistingLogId(draft.backend_id || null);
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        loadChips(draft.data.activities || []);
        loadProjectShell();
        setLoading(false);
        return;
      }

      const [projectData, roster, headcount, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsRoster(projectId, date).catch(() => null),
        logbooksAPI.getDailyHeadcount(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'daily_jobsite', date).catch(() => []),
      ]);

      const fullAddress = projectData?.address || projectData?.location || '';
      setProjectAddress(fullAddress);
      setBuildingStories(projectData?.building_stories ?? null);
      rosterIdsRef.current = rosterIdIndex(headcount);

      // A roster read that FAILED is not an empty jobsite. Null here means the
      // request itself did not come back, which is exactly the case the CP
      // must not read as "nobody was here".
      if (!roster) {
        setRosterPartial(true);
      } else {
        setRosterPartial(Boolean(roster.partial));
        setRosterCollapsed(roster.collapsed || 0);
      }

      // Prefer the EDITABLE (non-locked) doc — an amendment child — over a
      // locked original that shares (project, type, date).
      let builtCrews = [];
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find((l) => !l.is_locked) || arr[0] || null;
      if (existing?.is_locked) { setLocked(true); markFinalized(_key); }

      if (existing) {
        setExistingLogId(existing.id || existing._id);
        hydrate(existing.data || {});
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      } else {
        builtCrews = buildCrewsFromRoster(roster?.workers || [], headcount);
        setActivities(builtCrews);
        // Weather and address are OBSERVED FACTS about the day, not asserted
        // work, so auto-filling them states nothing the CP did not witness.
        // This is why they stay auto-populated while work_description does not.
        fetchWeather(fullAddress);
      }
      loadChips(existing ? (existing.data || {}).activities || [] : builtCrews);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  /** Address + storeys only — used on the draft path, which skips the rest. */
  const loadProjectShell = async () => {
    try {
      const p = await projectsAPI.getById(projectId);
      if (p?.building_stories != null) setBuildingStories(p.building_stories);
      const [headcount] = await Promise.all([
        logbooksAPI.getDailyHeadcount(projectId, date).catch(() => []),
      ]);
      rosterIdsRef.current = rosterIdIndex(headcount);
    } catch (_e) { /* non-blocking */ }
  };

  /**
   * One fetch per DISTINCT crew trade on site — a handful, not one per crew.
   * Each is cached under its trade key, so revisiting Step 2 refetches nothing.
   */
  const loadChips = async (rows) => {
    // workRows drops the unassigned-worker rows: a worker with no company is
    // present on site and is not a unit of work, so he gets no activity card
    // and there is no crew trade to fetch a list for. Restored now that the
    // helper is on main — it was left out only to avoid stacking on an open PR.
    const wanted = [...new Set(
      workRows(rows).map((a) => String(a.trade || '').trim()),
    )];
    // ALWAYS the unfiltered list too. A trade-filtered response contains only
    // that trade's activities, so without this there is no "everything else"
    // to put behind the catalogue toggle — and the toggle would repeat the
    // chips already shown inline. Keyed on '' and cached like any other.
    if (!wanted.includes('')) wanted.push('');
    await Promise.all(wanted.map(async (tr) => {
      try {
        const res = await logbooksAPI.getActivityChips(projectId, date, tr || null);
        setChipsByTrade((p) => ({ ...p, [tr]: Array.isArray(res?.chips) ? res.chips : [] }));
        setChipsMetaByTrade((p) => ({ ...p, [tr]: res || null }));
      } catch (_e) {
        // Chips never block an entry. With no ranking the CP still has
        // "Other", which is free text, so the day can always be logged.
        setChipsByTrade((p) => ({ ...p, [tr]: [] }));
        setChipsMetaByTrade((p) => ({ ...p, [tr]: null }));
      }
    }));
  };

  /** The chip list for one crew — its own trade's, never another's. */
  const chipsFor = (a) => chipsByTrade[String(a?.trade || '').trim()] || [];

  /**
   * The chips this crew sees ON THE CARD, in order, and the remainder behind
   * the catalogue toggle.
   *
   * THE DEFECT THIS FIXES. The trade filter worked — an electrical crew's 16
   * activities came back correctly — and every one of them landed in the
   * CATALOG band, which renders collapsed. The SUGGESTED band was empty, so
   * the card showed "Other" and nothing else. For the 249 taxonomy activities
   * that band is empty by construction: they carry no edges, so nothing can
   * ever sequence them.
   *
   * FOR A CREW WHOSE ACTIVITIES HAVE NO EDGES, ITS TRADE'S WORK IS THE
   * SUGGESTION. There is nothing better to offer, so it renders inline.
   *
   * A REAL PRIOR STILL OUTRANKS IT. Sequenced chips keep their position above
   * the trade list — that ordering is what the sequence engine is for, and
   * this must not cost it. Neither band is ever pre-selected.
   */
  const chipBandsFor = (a) => {
    const mine = chipsFor(a);
    const resolved = chipsMetaByTrade[String(a?.trade || '').trim()]?.resolved_trades;
    const filtered = Array.isArray(resolved) && resolved.length > 0;

    const sequenced = mine.filter((c) => c.band === 'suggested');
    // Promoted ONLY when a trade actually resolved. For a crew with no trade
    // `mine` IS the whole catalogue, and inlining it would put ~80 chips on
    // the card — the opposite of the fix.
    const tradeWork = filtered
      ? mine.filter((c) => c.band === 'catalog' && c.id !== OTHER_ACTIVITY_ID)
      : [];

    const shown = new Set([...sequenced, ...tradeWork].map((c) => c.id));
    // The remainder is drawn from the UNFILTERED list, so "All activities"
    // means all activities rather than "the rest of this trade's".
    const everything = filtered ? (chipsByTrade[''] || mine) : mine;
    const rest = everything.filter(
      (c) => !shown.has(c.id) && c.id !== OTHER_ACTIVITY_ID,
    );
    return { sequenced, tradeWork, rest };
  };

  const hydrate = (d) => {
    if (d.project_address) setProjectAddress(d.project_address);
    if (d.weather) setWeather(d.weather);
    if (d.weather_temp) setWeatherTemp(d.weather_temp);
    if (d.weather_wind) setWeatherWind(d.weather_wind);
    if (d.weather_fetch_state) setWeatherFetchState(d.weather_fetch_state);
    if (d.general_description) setGeneralDescription(d.general_description);
    if (d.activities?.length) setActivities(d.activities);
    if (d.equipment_on_site) setEquipmentOnSite(d.equipment_on_site);
    if (d.checklist_items) setChecklistItems(d.checklist_items);
    if (d.observations) setObservations(d.observations);
    if (d.visitors_deliveries) setVisitorsDeliveries(d.visitors_deliveries);
    if (d.time_in) setTimeIn(d.time_in);
    if (d.time_out) setTimeOut(d.time_out);
    if (d.areas_visited) setAreasVisited(d.areas_visited);
  };

  /**
   * Weather is an OBSERVED FACT, fetched, never typed.
   *
   * It used to be an editable chip row with a silent catch: a failed fetch left
   * the field empty and said nothing, and the CP could sign a log whose weather
   * was blank. Now that the chips are gone he cannot even paper over it, so the
   * failure has to be recorded rather than swallowed.
   *
   * settleFetch is the app-wide three-way discriminator — the same one the
   * roster envelope and report-settings use — so "offline" means here exactly
   * what it means everywhere else: no response at all, as opposed to a server
   * that answered badly. Both are failures; only one is the CP's signal problem.
   */
  const fetchWeather = async (address) => {
    setWeatherLoading(true);
    const r = await settleFetch(() => weatherAPI.getCurrent(null, null, address || null));
    if (r.status === 'ok') {
      const data = r.data;
      if (data?.condition) setWeather(data.condition);
      if (data?.temperature != null) setWeatherTemp(`${Math.round(data.temperature)}°F`);
      if (data?.wind_speed != null) setWeatherWind(`${Math.round(data.wind_speed)} mph`);
    } else {
      console.warn('Weather fetch failed:', r.status, r.error?.message);
    }
    // Recorded on EVERY outcome, including success — a reader must be able to
    // tell "retrieved and it was Sunny" from "we never got an answer".
    setWeatherFetchState(r.status);
    setWeatherLoading(false);
    return r.status;
  };

  // ── Row edits ─────────────────────────────────────────────────────────
  const updateActivity = (index, field, value) => {
    setActivities((prev) => prev.map((a, i) => (i === index ? { ...a, [field]: value } : a)));
  };

  const addActivity = () => setActivities((prev) => [...prev, {
    ...EMPTY_ACTIVITY(), crew_id: `C${prev.length + 1}`,
  }]);

  const addObservation = () => setObservations((prev) => [...prev, EMPTY_OBSERVATION()]);
  const updateObservation = (index, field, value) => setObservations(
    (prev) => prev.map((o, i) => (i === index ? { ...o, [field]: value } : o)),
  );
  const removeObservation = (index) => setObservations(
    (prev) => prev.filter((_, i) => i !== index),
  );

  const toggleEquipment = (key) => setEquipmentOnSite((p) => ({ ...p, [key]: !p[key] }));

  /**
   * What the collapsed equipment row says. NAMES the plant rather than
   * counting it, so a CP scanning Step 1 sees the hoist without expanding.
   *
   * Nothing ticked reads as NOT RECORDED, never as "none": an empty equipment
   * list and an unanswered one are different facts on a filed document — the
   * same distinction _display_weather draws server-side.
   */
  const equipmentSummary = useMemo(() => {
    const on = EQUIPMENT_ITEMS.filter((it) => equipmentOnSite[it.key]).map((it) => it.label);
    return on.length ? on.join(', ') : t('notRecorded');
  }, [equipmentOnSite, t]);

  /**
   * Set one inspection's result. Tapping the result it already holds clears
   * it back to NOT WALKED — the CP must be able to undo a mis-tap, and there
   * is no third chip to mean "actually I did not walk this".
   *
   * The note SURVIVES a result change. A CP who taps Pass by mistake after
   * typing what he found must not lose the typing; and a note under a Pass is
   * harmless, because only a fail's note is printed as a failure.
   */
  const setInspection = (key, result) => setChecklistItems((p) => {
    const row = inspectionRow(p, key);
    return {
      ...p,
      [key]: { result: row.result === result ? null : result, note: row.note },
    };
  });

  const setInspectionNote = (key, note) => setChecklistItems((p) => ({
    ...p, [key]: { ...inspectionRow(p, key), note },
  }));

  // Chip labels for composing the sentence the PDF prints.
  const allChips = useMemo(
    () => Object.values(chipsByTrade).flat(), [chipsByTrade],
  );
  const chipLabels = useMemo(() => {
    const m = new Map();
    allChips.forEach((c) => m.set(c.id, c.label));
    return m;
  }, [allChips]);

  // chip id -> the WorkPackage's trade, newly carried on ActivityChip. This is
  // the only grouping signal the client has; see deriveGeneralDescription.
  const chipTrades = useMemo(() => {
    const m = new Map();
    allChips.forEach((c) => { if (c.trade) m.set(c.id, c.trade); });
    return m;
  }, [allChips]);

  // The DRAFT sentence, recomputed from what the CP has tapped so far.
  const suggestedDescription = useMemo(
    () => deriveGeneralDescription(activities, chipTrades),
    [activities, chipTrades],
  );

  // THE CP IS ATTESTING TO THIS SENTENCE, so the app may draft it and may not
  // write it for him. The draft only lands in the record when he has been on
  // the review step to see it — `descriptionTouched` flips the moment he edits,
  // after which the app never overwrites his words.
  const [descriptionTouched, setDescriptionTouched] = useState(false);
  useEffect(() => {
    if (descriptionTouched) return;
    if (step !== TOTAL_STEPS) return;   // only once he is looking at it
    setGeneralDescription(suggestedDescription);
  }, [step, suggestedDescription, descriptionTouched]);

  const locationChips = useMemo(() => floorChips(buildingStories), [buildingStories]);
  const locationLabels = useMemo(() => {
    const m = new Map();
    locationChips.forEach((c) => m.set(c.id, c.label));
    return m;
  }, [locationChips]);

  /**
   * Toggle one activity chip on a crew, and re-compose the sentence that
   * reaches the record. NOTHING is pre-selected — a chip is only ever in
   * `activity_ids` because the CP tapped it.
   */
  const toggleActivityChip = (index, chipId) => {
    if (chipId === OTHER_ACTIVITY_ID) {
      setOtherPrompt({ index, kind: 'activity', value: '' });
      return;
    }
    setActivities((prev) => prev.map((a, i) => {
      if (i !== index) return a;
      const has = (a.activity_ids || []).includes(chipId);
      const ids = has
        ? a.activity_ids.filter((x) => x !== chipId)
        : [...(a.activity_ids || []), chipId];
      return {
        ...a,
        activity_ids: ids,
        work_description: composeSelection(ids, mergedActivityLabels(a)),
      };
    }));
  };

  const toggleLocationChip = (index, chipId) => {
    if (chipId === OTHER_LOCATION_ID) {
      setOtherPrompt({ index, kind: 'location', value: '' });
      return;
    }
    setActivities((prev) => prev.map((a, i) => {
      if (i !== index) return a;
      const has = (a.location_ids || []).includes(chipId);
      const ids = has
        ? a.location_ids.filter((x) => x !== chipId)
        : [...(a.location_ids || []), chipId];
      return {
        ...a,
        location_ids: ids,
        work_locations: composeSelection(ids, mergedLocationLabels(a)),
      };
    }));
  };

  // A free-text entry becomes a chip on its own row, so it renders and
  // composes exactly like a ranked one and survives a reload.
  const mergedActivityLabels = (a) => {
    const m = new Map(chipLabels);
    Object.entries(a.custom_activity_labels || {}).forEach(([k, v]) => m.set(k, v));
    return m;
  };
  const mergedLocationLabels = (a) => {
    const m = new Map(locationLabels);
    Object.entries(a.custom_location_labels || {}).forEach(([k, v]) => m.set(k, v));
    return m;
  };

  const commitOther = () => {
    const p = otherPrompt;
    if (!p) return;
    const label = String(p.value || '').trim();
    if (!label) { setOtherPrompt(null); return; }
    const id = `other:${label}`;
    setActivities((prev) => prev.map((a, i) => {
      if (i !== p.index) return a;
      if (p.kind === 'activity') {
        const labels = { ...(a.custom_activity_labels || {}), [id]: label };
        const ids = (a.activity_ids || []).includes(id)
          ? a.activity_ids : [...(a.activity_ids || []), id];
        const m = new Map(chipLabels);
        Object.entries(labels).forEach(([k, v]) => m.set(k, v));
        return {
          ...a, custom_activity_labels: labels, activity_ids: ids,
          work_description: composeSelection(ids, m),
        };
      }
      const labels = { ...(a.custom_location_labels || {}), [id]: label };
      const ids = (a.location_ids || []).includes(id)
        ? a.location_ids : [...(a.location_ids || []), id];
      const m = new Map(locationLabels);
      Object.entries(labels).forEach(([k, v]) => m.set(k, v));
      return {
        ...a, custom_location_labels: labels, location_ids: ids,
        work_locations: composeSelection(ids, m),
      };
    }));
    setOtherPrompt(null);
  };

  const commitAddCrew = () => {
    const c = addingCrew;
    if (!c) return;
    const company = String(c.company || '').trim();
    if (!company) { setAddingCrew(null); return; }
    const trade = String(c.trade || '').trim();
    setActivities((prev) => [...prev, {
      ...EMPTY_ACTIVITY(),
      crew_id: `C${prev.length + 1}`,
      company,
      trade,
      num_workers: String(parseInt(c.num, 10) || 0),
      // Added by hand — it did NOT come from the gate and must not claim to.
      gate_sourced: false,
      subcontractor_id: resolveRosterId(company, trade, rosterIdsRef.current),
    }]);
    setAddingCrew(null);
  };

  // ── THE CAPTURE-TIME UPLOAD ───────────────────────────────────────────
  // Photos go to R2 as they are TAKEN, so the document never carries full-size
  // image data. Driven off `activities` rather than bolted onto each capture
  // path, because there are FOUR ways a photo arrives — the in-process
  // shutter, the gallery picker, the web picker, and a draft rehydrated after
  // the app was killed — and a guarantee that has to hold for all four should
  // not be written four times.
  //
  // ONE ATTEMPT PER PHOTO PER SESSION: the id stays in the set whether the
  // attempt succeeded or failed, so a failure cannot re-trigger this effect
  // through its own setActivities and spin.
  const uploadOneCapture = useCallback(async (activityId, photo) => {
    const id = photo.id;
    let localUri = photo.uri;
    try {
      localUri = await persistPhoto(photo.uri, id);
    } catch (_e) {
      // THE PHOTO DID NOT SAVE, AND THE CP IS TOLD SO. A photo whose copy
      // failed is not recorded at all — nothing on screen claims evidence that
      // does not exist — and he is asked to retake it. He is NOT blocked from
      // finishing the log.
      setActivities((prev) => dropPhoto(prev, id));
      setSessionShotIds((prev) => prev.filter((sid) => sid !== id));
      toast.error(t('photoNotSavedTitle'), t('photoNotSavedBody'));
      return;
    }
    if (localUri !== photo.uri) setActivities((prev) => patchPhoto(prev, id, { uri: localUri }));
    try {
      const key = await uploadCapturePhoto({ projectId, activityId, photoId: id, uri: localUri });
      setActivities((prev) => patchPhoto(prev, id, { original_r2_key: key, upload_pending: false }));
    } catch (_e) {
      // DEFERRED, NOT LOST. The file is in documentDirectory and its uri is in
      // the draft, so it survives an app kill; the row keeps `upload_pending`,
      // so every reader falls back to that local file; and the save and the
      // reconnect drain both retry it.
      setActivities((prev) => patchPhoto(prev, id, { upload_pending: true }));
    }
  }, [projectId, toast, t]);

  useEffect(() => {
    if (loading || locked || !projectId) return;
    activities.forEach((a) => ((a && a.photos) || []).forEach((p) => {
      // `pending` means the background compress has not finished; uploading
      // now would send the RAW sensor JPEG the entry still points at.
      if (!p || !p.id || p.pending) return;
      if (!photoNeedsUpload(p) || uploadAttemptedRef.current.has(p.id)) return;
      uploadAttemptedRef.current.add(p.id);
      uploadOneCapture(a.activity_id, p);
    }));
  }, [activities, loading, locked, projectId, uploadOneCapture]);

  const takeActivityPhoto = async (activityIndex) => {
    // The camera cannot be reached before crew, activity and location are set,
    // so every frame carries all three. This is the last line of that gate —
    // the button is not rendered either.
    if (!cameraReady(activities[activityIndex])) return;
    if (bucketRemaining(activities, activityIndex) <= 0) {
      toast.warning(t('photoCapTitle'), capMessage());
      return;
    }
    if (capturingRef.current) return;
    capturingRef.current = true;
    try {
      if (Platform.OS === 'web') {
        const result = await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.Images, quality: 0.6, base64: false,
        });
        if (!result || result.canceled) return;
        const asset = result.assets?.[0];
        if (!asset) return;
        setActivities((prev) => {
          if (bucketRemaining(prev, activityIndex) <= 0) return prev;
          return prev.map((a, i) => (i === activityIndex ? {
            ...a,
            photos: [...(a.photos || []), {
              id: newPhotoId(), uri: asset.uri, base64: null,
              timestamp: new Date().toISOString(),
            }],
          } : a));
        });
        return;
      }
      // Native: REVEAL the already-mounted, already-permissioned camera
      // overlay. Capture happens IN-PROCESS so the app is never backgrounded
      // and killed by the OS camera handoff — the root cause of the 20-30s
      // cold-boot reload. Nothing may be awaited below this line.
      setCameraTargetIndex(activityIndex);
      setSessionShotIds([]);
      setCameraVisible(true);
    } catch (err) {
      console.error('Camera launch failed:', err);
      toast.error(t('cameraErrorTitle'), t('cameraErrorBody'));
    } finally {
      capturingRef.current = false;
    }
  };

  const pickActivityPhoto = async (activityIndex) => {
    if (!cameraReady(activities[activityIndex])) return;
    const remaining = bucketRemaining(activities, activityIndex);
    if (remaining <= 0) { toast.warning(t('photoCapTitle'), capMessage()); return; }
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      toast.error(t('permissionDeniedTitle'), t('permissionDeniedBody'));
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.6, base64: false, allowsMultipleSelection: true,
      selectionLimit: remaining,
    });
    if (result.canceled) return;
    const picked = (result.assets || []).map((asset) => ({
      id: newPhotoId(), uri: asset.uri, base64: null,
      timestamp: new Date().toISOString(),
    }));
    setActivities((prev) => {
      // Re-measured against `prev`: a background compress or another row's
      // capture can land while the CP is choosing, and selectionLimit is a
      // hint the picker is free to ignore. The trim enforces the cap.
      const room = bucketRemaining(prev, activityIndex);
      if (room <= 0) return prev;
      return prev.map((a, i) => (i === activityIndex
        ? { ...a, photos: [...(a.photos || []), ...picked.slice(0, room)] } : a));
    });
  };

  /**
   * onCapture from CameraCaptureModal — the RAW sensor URI, handed over the
   * instant the capture resolves.
   *
   * NOTHING IS AWAITED HERE. The photo is appended immediately in `pending`
   * state so the strip reacts on the same frame, and compressUnderCap is fired
   * off unawaited. When it lands the entry is found BY ID (indexes move: the
   * CP may have deleted a sibling meanwhile) and its uri is swapped for the
   * compressed one. If compression fails the raw URI stays: a full-size photo
   * is worse than a small one and infinitely better than a lost one.
   */
  const handleCameraCapture = (uri, report) => {
    if (cameraTargetIndex == null || !uri) return;
    const target = cameraTargetIndex;
    const tIn = Date.now();
    if (bucketRemaining(activitiesRef.current, target) <= 0) {
      toast.warning(t('photoCapTitle'), capMessage());
      return;
    }
    const id = newPhotoId();
    const shot = { id, uri, base64: null, pending: true, timestamp: new Date().toISOString() };
    setActivities(prev => {
      // Second, authoritative check: the guard above reads a ref refreshed
      // only after a commit, so two shutters inside one frame would both pass.
      if (bucketRemaining(prev, target) <= 0) return prev;
      return prev.map((a, i) => (i === target
        ? { ...a, photos: [...(a.photos || []), shot] } : a));
    });
    setSessionShotIds((prev) => [...prev, id]);
    requestAnimationFrame(() => report?.('paint', Date.now() - tIn));

    const started = Date.now();
    const job = compressUnderCap(uri)
      .then((smallUri) => {
        if (smallUri) compressedUriRef.current[id] = smallUri;
        report?.('compress', Date.now() - started);
        setActivities((prev) => patchPhoto(prev, id, {
          uri: smallUri || uri, pending: false,
        }));
      })
      .catch((err) => {
        console.warn('photo compression failed, keeping original:', err?.message);
        report?.('compress', Date.now() - started);
        setActivities((prev) => patchPhoto(prev, id, { pending: false }));
      })
      .finally(() => {
        pendingCompressRef.current = pendingCompressRef.current.filter((j) => j !== job);
      });
    pendingCompressRef.current.push(job);
  };

  const cameraShots = useMemo(() => {
    if (cameraTargetIndex == null) return [];
    const photos = activities[cameraTargetIndex]?.photos || [];
    const byId = new Map(photos.filter((p) => p.id).map((p) => [p.id, p]));
    return sessionShotIds.map((id) => byId.get(id)).filter(Boolean);
  }, [activities, cameraTargetIndex, sessionShotIds]);

  const handleDeleteShot = (id) => {
    if (cameraTargetIndex == null || !id) return;
    setActivities((prev) => dropPhoto(prev, id));
    setSessionShotIds((prev) => prev.filter((sid) => sid !== id));
    delete compressedUriRef.current[id];
  };

  const removeActivityPhoto = (activityIndex, photoIndex) => {
    setActivities((prev) => prev.map((a, i) => (i === activityIndex
      ? { ...a, photos: (a.photos || []).filter((_, pi) => pi !== photoIndex) } : a)));
  };

  const photoTileUri = (photo, ai, pi) => (
    photo?.uri
    || inlinePhotoData(photo?.base64)
    || inlinePhotoData(photo?.thumb_base64)
    || (existingLogId
      ? logbooksAPI.getLogbookPhotoUrl(existingLogId, ai, pi, 'thumb', photo?.enhance_status || '')
      : null)
    || undefined
  );

  const openPhotoLightbox = (photo, ai, pi) => {
    if (!photo || photo.pending) return;
    const done = photo.enhance_status === 'done';
    if (existingLogId && photo.enhance_status) {
      setPhotoLightbox({
        uri: logbooksAPI.getLogbookPhotoUrl(
          existingLogId, ai, pi, done ? 'enhanced' : 'original', photo.enhance_status,
        ),
        label: done ? 'Enhanced' : `Original — enhancement ${photo.enhance_status}`,
      });
      return;
    }
    const local = photo.uri || inlinePhotoData(photo.base64) || inlinePhotoData(photo.thumb_base64);
    if (local) setPhotoLightbox({ uri: local, label: 'Original' });
  };

  // ── SAVE ──────────────────────────────────────────────────────────────
  const persistAndPush = async (submitStatus) => {
    // Let any background compression finish FIRST. A save fired immediately
    // after a capture would otherwise persist and upload the RAW sensor JPEG
    // the pending entry still points at. allSettled, not all: a failed
    // compress must not block the save.
    if (pendingCompressRef.current.length > 0) {
      await Promise.allSettled(pendingCompressRef.current);
    }
    const rows = activitiesRef.current?.length ? activitiesRef.current : activities;
    const persisted = await persistActivityPhotos(rows);
    await writeDraft(_key, {
      data: draftBody(persisted), cp_signature: cpSignature, cp_name: cpName,
      status: submitStatus,
    });

    // persistActivityPhotos no longer fails silently.
    const lost = persisted.reduce(
      (n, a) => n + ((a.photos || []).filter((p) => p.persist_failed).length), 0,
    );
    if (lost > 0) toast.error(t('photoNotSavedTitle'), t('photoNotSavedBody'));

    // Most photos are already in R2 — uploaded as they were taken. This
    // catches the stragglers. Bounded: uploadPendingActivityPhotos abandons
    // the loop on the first offline failure or 5xx rather than making the CP
    // wait out a hundred identical timeouts.
    const _uploaded = await uploadPendingActivityPhotos(projectId, persisted);
    if (_uploaded.uploaded > 0) {
      const keyById = new Map();
      _uploaded.activities.forEach((a) => (a.photos || []).forEach((p) => {
        if (p.id && p.original_r2_key) keyById.set(p.id, p.original_r2_key);
      }));
      setActivities((prev) => prev.map((a) => ({
        ...a,
        photos: (a.photos || []).map((p) => (keyById.has(p.id)
          ? { ...p, original_r2_key: keyById.get(p.id), upload_pending: false } : p)),
      })));
      await writeDraft(_key, { data: draftBody(_uploaded.activities) });
    }

    const payloadActivities = _uploaded.activities.map((act) => ({
      ...act,
      photos: (act.photos || []).map(photoForPayload).filter(Boolean),
    }));

    const data = {
      ...draftBody(payloadActivities),
      // superintendent fields intentionally omitted — the super signs from the
      // site device.
    };

    let created = null;
    let savedId = existingLogId;
    try {
      if (existingLogId) {
        await logbooksAPI.update(existingLogId, {
          data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
        });
      } else {
        created = await logbooksAPI.create({
          project_id: projectId, log_type: 'daily_jobsite', date, data,
          cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
        });
        savedId = created.id || created._id;
        setExistingLogId(savedId);
      }
      await setDraftBackendId(_key, savedId);
      await clearPending(_key);
    } catch (pushErr) {
      // Offline / server error — the local draft is already saved above.
      await markPending(_key);
      console.warn('daily_jobsite push deferred (will sync on reconnect):', pushErr?.message);
    }

    // A PHOTO THAT HAS NOT REACHED R2 KEEPS THE DRAFT PENDING, even when the
    // content push SUCCEEDED and cleared the marker above. The reconnect drain
    // only looks at keys in the pending index — without this, a photo whose
    // upload failed while the rest of the day saved fine would sit on the
    // device forever with nothing ever trying again.
    if (hasPendingPhotoUploads(_uploaded.activities)) await markPending(_key);

    // Guarded: a CP-PROFILE save failure must never report a failure on a log
    // that was already saved.
    await autoSave(cpName, cpSignature).catch(() => {});

    if (submitStatus === 'submitted' && cpSignature) {
      const docId = existingLogId || created?.id || created?._id;
      if (docId) {
        const { recordSignatureEvent } = require('../../src/utils/signatureAudit');
        recordSignatureEvent({
          documentType: 'logbook', documentId: docId, eventType: 'cp_sign',
          signerName: cpName, signerRole: user?.role || 'cp', signatureData: cpSignature,
          contentSnapshot: {
            log_type: 'daily_jobsite', date, project_id: projectId, data,
            status: submitStatus,
          },
          user,
        }).catch((e) => console.warn('Signature audit failed (non-blocking):', e?.message));
      }
    }
    return savedId || null;
  };

  /**
   * THE end-of-day action — one button, one freeze.
   *
   *   1. content, photos and signature into the local draft first; server push
   *      best-effort (markPending on failure; draftSync drains it and re-applies
   *      /finalize on reconnect).
   *   2. server /finalize when the doc has an id.
   *   3. LOCAL freeze — but ONLY when the server never ANSWERED.
   *   4. flip the form read-only.
   *
   * REFUSAL IS NOT OFFLINE. Treating every finalize failure as offline
   * produced three compounding lies: the CP was told the log was signed,
   * locked and would sync when the server had said no and would keep saying
   * no; markFinalized made the draft IMMUTABLE so he could not fix the very
   * condition being refused; and the content push had SUCCEEDED, so no pending
   * key existed and the drain would never retry. Silent, permanent, and his
   * own device showed FINALIZED.
   *
   * So there are THREE outcomes and only one of them may promise a sync.
   */
  const handleSubmitAndSign = async () => {
    if (signing) return;
    if (!cpSignature) {
      toast.warning(t('signatureRequiredTitle'), t('signatureRequiredBody'));
      return;
    }
    const blocking = incompleteObservations(observations);
    if (blocking.length > 0) {
      setStep(3);
      toast.warning(t('sectionObservations'), t('observationRemedyMissing'));
      return;
    }
    // A FAILED INSPECTION WITHOUT ITS NOTE IS THE EMPTY RECORD THE TICK WAS.
    // Same shape as the observation gate above: send him back to the step
    // that holds it rather than refusing at the signature with no route to a
    // fix. Only a fail blocks — an item he did not walk is a real answer.
    const badInspections = incompleteInspections(checklistItems);
    if (badInspections.length > 0) {
      setStep(4);
      toast.warning(t('sectionInspected'), t('inspectionNoteMissing'));
      return;
    }
    setSigning(true);
    try {
      const savedId = await persistAndPush('submitted');
      // `undefined` (not null) = the save itself failed and has already been
      // reported. Nothing may be frozen, recorded or announced on a log that
      // was never written. `null` is different: it saved LOCALLY but has no
      // server id yet, which is the offline path and does freeze below.
      if (savedId === undefined) return;
      let serverLocked = false;
      if (savedId) {
        try {
          await logbooksAPI.finalize(savedId);
          serverLocked = true;
          await clearFinalizeError(savedId);
        } catch (finalizeErr) {
          const offline = isOfflineError(finalizeErr);
          const status = finalizeErr?.response?.status;
          const refused = typeof status === 'number' && status >= 400 && status < 500;
          if (!offline && !refused) {
            // 5xx — the server FAILED rather than judged. Nothing is queued and
            // nothing is locked, so it is simply retryable and must not be
            // announced as synced.
            console.warn('Finalize FAILED server-side — not locked, not queued:', status || finalizeErr?.message);
            toast.error(tFinalize('errorTitle'), gateCopy(null));
            return;
          }
          if (refused) {
            // NOT frozen, NOT announced, NOT navigated away from: the CP has to
            // be able to fix what was refused, on this screen, right now. BOTH a
            // toast and a record — the toast is gone in four seconds, and the
            // record is what is still there when he comes back.
            const code = finalizeErrorCode(finalizeErr);
            console.warn('Finalize REFUSED by the server:', status, code);
            await recordFinalizeError(savedId, code, _key, 'editor');
            toast.error(tFinalize('errorTitle'), gateCopy(code));
            return;
          }
          // GENUINELY OFFLINE. The local freeze below stands — an EOD sign with
          // no signal must still hold — and the drain re-applies /finalize once
          // the push lands, which is what makes the promise below true.
          console.warn('Finalize deferred (will re-apply on reconnect):', finalizeErr?.message);
        }
      }
      await markFinalized(_key);
      setLocked(true);
      toast.success(
        t('submittedTitle'),
        serverLocked ? t('signingClosesDay') : t('submittedOfflineBody'),
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
  // Autosave after every step. Moving on is never BLOCKED — a CP who cannot
  // complete a step because the data is not there must still finish his day.
  const goNext = async () => {
    await flushDraft();
    setStep((n) => Math.min(TOTAL_STEPS, n + 1));
  };
  const goBack = async () => {
    await flushDraft();
    setStep((n) => Math.max(1, n - 1));
  };

  // ── Small shared pieces ───────────────────────────────────────────────
  // ChipBase / StepHeaderBase are declared at MODULE level (bottom of file)
  // and bound to the stylesheet here. A component declared inline in this
  // function would be a NEW type on every render, so React would unmount and
  // remount every chip on the screen for each keystroke. On the older phone
  // this screen is built for, that is the difference between usable and not.
  // `s` is memoized with a stable dep, so these identities are stable too.
  const Chip = useCallback((p) => <ChipBase s={s} {...p} />, [s]);
  const StepHeader = useCallback((p) => (
    <StepHeaderBase
      s={s}
      count={t('stepOf').replace('{n}', String(step)).replace('{m}', String(TOTAL_STEPS))}
      {...p}
    />
  ), [s, step, t]);


  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingCenter}>
            <ActivityIndicator size="large" color={outdoor.text} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  const crewName = (a) => (String(a.company || '').trim() || t('noCrewWorker'));

  // Present on site, not a unit of work. Counted so Step 2 can say why there
  // is no card for him rather than simply omitting him without explanation.
  const unassignedWorkerCount = activities.filter(isUnassignedWorkerRow).length;

  // ── STEP 1 — what was on site ─────────────────────────────────────────
  //
  // COMPACT BY RULING. This step has no editable field in the ordinary case —
  // it is a confirmation — so it must not cost a full scrolling screen to
  // read. Measured against the real tokens on 390x844: chrome takes 188pt
  // (header 72, pips 12, footer 104), leaving 527pt; fixed content is 228pt
  // (step header 28, add-crew 64, equipment summary 56, weather 80), so 299pt
  // remains and a 40pt row fits SEVEN crews before scrolling. On a 4.7" SE the
  // same arithmetic gives FOUR.
  //
  // 40pt IS ONLY HONEST BECAUSE THE ROWS ARE NOT TAPPABLE. They display locked
  // gate data and there is nothing to tap. Anything that makes a row
  // interactive has to go back to touchTarget.min and the arithmetic above has
  // to be redone.
  const renderStep1 = () => (
    <View>
      <StepHeader title={t('step1Title')} />

      {rosterPartial && (
        <Card s={s} style={s.cardWarn}>
          <AlertTriangle size={20} strokeWidth={2} color={outdoor.warn} />
          <View style={s.warnBody}>
            <Text style={s.warnTitle}>{t('rosterPartialTitle')}</Text>
            <Text style={s.warnText}>{t('rosterPartialBody')}</Text>
            {rosterCollapsed > 0 && (
              <Text style={s.warnText}>{t('rosterCollapsedBody')}</Text>
            )}
          </View>
        </Card>
      )}

      {activities.length === 0 && (
        <Text style={s.emptyText}>{t('noCrews')}</Text>
      )}

      {/* One row per crew. Two lines at 13pt, not a card. */}
      {activities.map((a, i) => {
        const flagged = isUnassignedWorkerRow(a);
        return (
          <View
            key={a.activity_id || i}
            style={[s.crewRow, flagged && s.crewRowFlagged]}
          >
            <View style={s.crewRowMain}>
              <Text style={s.crewRowName} numberOfLines={1}>
                {flagged ? t('unassignedTitle') : crewName(a)}
              </Text>
              {/* The badge shrinks but does not go: it is the only thing
                  saying this data is locked and came from the gate. */}
              {a.gate_sourced && (
                <Lock size={12} strokeWidth={2} color={outdoor.textSoft} />
              )}
            </View>
            <Text style={s.crewRowMeta} numberOfLines={1}>
              {[
                tradeLabel(a.trade),
                plural('workers_one', 'workers_other', parseInt(a.num_workers, 10) || 0),
                a.check_in_time ? formatCheckInTime(a.check_in_time) : t('checkInTimeUnknown'),
              ].join(' · ')}
            </Text>
            {/* He is the one row here that needs attention, so compaction
                must not bury him: he keeps his own line at full contrast. */}
            {flagged && (
              <Text style={s.crewRowFlag} numberOfLines={2}>{t('unassignedHint')}</Text>
            )}
            {isUnboundCrew(a) && (
              <Text style={s.crewRowFlag} numberOfLines={2}>{t('unboundCrewHint')}</Text>
            )}
            {!!a.company_gate && rosterKey(a.company_gate) !== rosterKey(a.company) && (
              <Text style={s.crewRowFlag} numberOfLines={1}>
                {t('correctedFrom')}: {a.company_gate}
              </Text>
            )}
          </View>
        );
      })}

      <Pressable
        style={s.secondaryBtn}
        accessibilityRole="button"
        onPress={() => setAddingCrew({ company: '', trade: '', num: '1' })}
      >
        <Plus size={20} strokeWidth={2} color={outdoor.text} />
        <Text style={s.secondaryBtnText}>{t('addCrew')}</Text>
      </Pressable>

      {/* EQUIPMENT — one summary line, expanding to the chips. Folded rather
          than the crews because Step 1 exists to confirm WHO was on site.
          It NAMES the plant, so a CP scanning sees it without expanding, and
          an empty list reads as not recorded rather than as none: those are
          different facts on a filed record. */}
      <Pressable
        style={s.summaryRow}
        accessibilityRole="button"
        accessibilityState={{ expanded: equipmentOpen }}
        onPress={() => setEquipmentOpen((v) => !v)}
      >
        <Text style={s.summaryLabel}>{t('sectionEquipment')}</Text>
        <Text style={s.summaryValue} numberOfLines={1}>{equipmentSummary}</Text>
      </Pressable>
      {equipmentOpen && (
        <View style={s.chipWrap}>
          {EQUIPMENT_ITEMS.map((it) => (
            <Chip
              key={it.key} label={it.label} selected={!!equipmentOnSite[it.key]}
              onPress={() => toggleEquipment(it.key)}
            />
          ))}
        </View>
      )}

      {/* READ-ONLY. Weather is observed and fetched, never chosen: the CP is
          reporting what the sky did, and a tappable list invites him to record
          what he remembers rather than what was measured. When the fetch
          failed, the failure is shown — it is never left looking unanswered. */}
      <Text style={s.question}>{t('fieldWeather')}</Text>
      {weatherLoading ? (
        <ActivityIndicator size="small" color={outdoor.textDim} />
      ) : weatherFetchState === 'ok' && weather ? (
        <View style={s.readOnlyValue}>
          <Text style={s.readOnlyText}>
            {[weather, weatherTemp, weatherWind].filter(Boolean).join(' · ')}
          </Text>
        </View>
      ) : (
        <Card s={s} style={s.cardWarn}>
          <AlertTriangle size={20} strokeWidth={2} color={outdoor.warn} />
          <View style={s.warnBody}>
            <Text style={s.warnTitle}>{t('weatherUnavailableTitle')}</Text>
            <Text style={s.warnText}>
              {weatherFetchState === 'offline'
                ? t('weatherUnavailableOffline')
                : t('weatherUnavailableBody')}
            </Text>
          </View>
        </Card>
      )}
    </View>
  );

  // ── STEP 2 — one card per crew ────────────────────────────────────────
  const renderStep2 = () => (
    <View>
      <StepHeader title={t('step2Title')} />

      {(() => {
        const anyMeta = Object.values(chipsMetaByTrade).find(Boolean);
        return (
          <>
            {anyMeta && anyMeta.structural_system_set === false && (
              <Text style={s.noteText}>{t('structuralSystemUnknown')}</Text>
            )}
            {anyMeta && !anyMeta.prior_date && (
              <Text style={s.noteText}>{t('chipsNoPriorDay')}</Text>
            )}
          </>
        );
      })()}

      {/* AN ACTIVITY ROW IS A COMPANY'S WORK. A man who came through the gate
          with no company assignment gets NO card here — no activity, no
          location, no camera. Giving him one lets the CP log work against
          nobody, which is a line in a signed record that cannot be true. He is
          shown on Step 1 instead, present and flagged for assignment.

          The INDEX is the one from the full `activities` array, not the
          filtered one: the photo bucket, the chip toggles and every patch
          helper address rows by their real position. Filtering the map without
          keeping the original index would silently write to the wrong crew. */}
      {unassignedWorkerCount > 0 && (
        <Text style={s.noteText}>
          {plural('unassignedNoCard_one', 'unassignedNoCard_other', unassignedWorkerCount)}
        </Text>
      )}

      {activities.map((a, i) => {
        if (isUnassignedWorkerRow(a)) return null;
        // THIS crew's chips, not the project's. An electrical crew must never
        // be offered drywall.
        const { sequenced, tradeWork, rest } = chipBandsFor(a);
        const open = !!expandedChips[a.activity_id];
        const ready = cameraReady(a);
        const customA = Object.entries(a.custom_activity_labels || {});
        const customL = Object.entries(a.custom_location_labels || {});
        return (
          <Card s={s} key={a.activity_id || i}>
            {/* Locked, gate-sourced facts, restated so the card shows exactly
                what a photo taken from it will be tagged with. */}
            <View style={s.crewTop}>
              <Text style={s.crewName}>{crewName(a)}</Text>
              {a.gate_sourced && (
                <View style={s.gateBadge}>
                  <Lock size={14} strokeWidth={2} color={outdoor.textSoft} />
                  <Text style={s.gateBadgeText}>{t('gateLocked')}</Text>
                </View>
              )}
            </View>
            <Text style={s.crewMeta}>
              {[tradeLabel(a.trade), plural('workers_one', 'workers_other', parseInt(a.num_workers, 10) || 0),
                a.check_in_time ? formatCheckInTime(a.check_in_time) : null]
                .filter(Boolean).join(' · ')}
            </Text>

            {/* ACTIVITY. Ranked, never pre-selected. */}
            <Text style={s.question}>{t('activityQuestion')}</Text>
            <View style={s.chipWrap}>
              {/* Sequenced off the prior day FIRST — a real prior outranks a
                  trade list, and that ordering is what the engine is for. */}
              {sequenced.map((c) => (
                <Chip
                  key={c.id} label={c.label}
                  selected={(a.activity_ids || []).includes(c.id)}
                  onPress={() => toggleActivityChip(i, c.id)}
                />
              ))}
              {/* Then this crew's own trade. Empty unless a trade resolved. */}
              {tradeWork.map((c) => (
                <Chip
                  key={c.id} label={c.label}
                  selected={(a.activity_ids || []).includes(c.id)}
                  onPress={() => toggleActivityChip(i, c.id)}
                />
              ))}
              {customA.map(([id, label]) => (
                <Chip
                  key={id} label={label}
                  selected={(a.activity_ids || []).includes(id)}
                  onPress={() => toggleActivityChip(i, id)}
                />
              ))}
              {/* "Other" is ALWAYS last and always visible without scrolling —
                  it is rendered here, beside the suggested band, not at the
                  bottom of the full catalogue. */}
              <Chip
                label={t('chipOther')} selected={false}
                onPress={() => toggleActivityChip(i, OTHER_ACTIVITY_ID)}
              />
            </View>

            {rest.length > 0 && (
              <>
                <Pressable
                  style={s.secondaryBtn}
                  accessibilityRole="button"
                  onPress={() => setExpandedChips((p) => ({
                    ...p, [a.activity_id]: !open,
                  }))}
                >
                  <Text style={s.secondaryBtnText}>{t('chipsCatalog')}</Text>
                </Pressable>
                {open && (
                  <View style={s.chipWrap}>
                    {rest.map((c) => (
                      <Chip
                        key={c.id} label={c.label}
                        selected={(a.activity_ids || []).includes(c.id)}
                        onPress={() => toggleActivityChip(i, c.id)}
                      />
                    ))}
                  </View>
                )}
              </>
            )}

            {/* LOCATION */}
            <Text style={s.question}>{t('locationQuestion')}</Text>
            <View style={s.chipWrap}>
              {locationChips.map((c) => (
                <Chip
                  key={c.id} label={c.label}
                  selected={(a.location_ids || []).includes(c.id)}
                  onPress={() => toggleLocationChip(i, c.id)}
                />
              ))}
              {customL.map(([id, label]) => (
                <Chip
                  key={id} label={label}
                  selected={(a.location_ids || []).includes(id)}
                  onPress={() => toggleLocationChip(i, id)}
                />
              ))}
              <Chip
                label={t('locationOther')} selected={false}
                onPress={() => toggleLocationChip(i, OTHER_LOCATION_ID)}
              />
            </View>

            {/* CAMERA — only once crew, activity and location are all set. */}
            {!ready ? (
              <Text style={s.lockedHint}>{t('cameraLockedHint')}</Text>
            ) : (
              <View style={s.photoBlock}>
                <Text style={s.taggedWith}>
                  {t('photoTaggedWith')} {crewName(a)} · {a.work_description} · {a.work_locations}
                </Text>
                {/* The BUCKET's count, not this row's: the cap is per
                    subcontractor and shared across its rows. No counter until
                    there is something to count. */}
                {(a.photos || []).length > 0 && (
                  <Text style={s.photoCount}>
                    {`${t('photoLabel')} ${photosInBucket(activities, i)}/${MAX_PHOTOS_PER_SUBCONTRACTOR}`}
                  </Text>
                )}

                {(a.photos || []).length > 0 && (
                  // A WRAPPING GRID, NOT A HORIZONTAL SCROLLER. A horizontal
                  // scroller is a swipe affordance, and this screen is tap-only.
                  <View style={s.photoGrid}>
                    {(a.photos || []).map((photo, pi) => (
                      <View key={photo.id ?? pi} style={s.photoThumb}>
                        {photo.pending ? (
                          <View style={[s.photoImage, s.photoPending]}>
                            <ActivityIndicator size="small" color={outdoor.textDim} />
                          </View>
                        ) : (
                          <Pressable onPress={() => openPhotoLightbox(photo, i, pi)}>
                            <Image source={{ uri: photoTileUri(photo, i, pi) }} style={s.photoImage} />
                          </Pressable>
                        )}
                        <Pressable
                          style={s.photoRemove}
                          hitSlop={16}
                          accessibilityRole="button"
                          onPress={() => removeActivityPhoto(i, pi)}
                        >
                          <X size={16} strokeWidth={3} color={outdoor.textOnSelected} />
                        </Pressable>
                      </View>
                    ))}
                  </View>
                )}

                {bucketRemaining(activities, i) <= 0 ? (
                  <Text style={s.lockedHint}>{t('photoCapRowHint')}</Text>
                ) : (
                  <View style={s.photoActions}>
                    <Pressable
                      style={s.photoBtn}
                      accessibilityRole="button"
                      onPress={() => takeActivityPhoto(i)}
                    >
                      <Camera size={22} strokeWidth={2} color={outdoor.textOnSelected} />
                      <Text style={s.photoBtnText}>{t('photoTake')}</Text>
                    </Pressable>
                    <Pressable
                      style={s.photoBtnGhost}
                      accessibilityRole="button"
                      onPress={() => pickActivityPhoto(i)}
                    >
                      <ImageIcon size={22} strokeWidth={2} color={outdoor.text} />
                      <Text style={s.photoBtnGhostText}>{t('photoGallery')}</Text>
                    </Pressable>
                  </View>
                )}
              </View>
            )}
          </Card>
        );
      })}
    </View>
  );

  // ── STEP 3 — safety observations ──────────────────────────────────────
  const renderStep3 = () => (
    <View>
      <StepHeader title={t('step3Title')} />
      {observations.length === 0 && (
        <Text style={s.emptyText}>{t('noObservations')}</Text>
      )}
      {observations.map((o, i) => {
        const missing = !observationComplete(o);
        return (
          <Card s={s} key={i} style={missing ? s.cardFlagged : null}>
            <TextInput
              style={s.input}
              value={o.description}
              onChangeText={(v) => updateObservation(i, 'description', v)}
              placeholder={t('phObservation')}
              placeholderTextColor={outdoor.textDim}
              multiline
            />

            {/* Responsible party is PICKED from the crews on site, never typed:
                a typed name cannot be matched to anyone and a misspelling is
                an unattributable hazard on a signed record. */}
            <Text style={s.question}>{t('observationWho')}</Text>
            <Text style={s.noteText}>{t('observationWhoHint')}</Text>
            <View style={s.chipWrap}>
              {activities.map((a, ai) => (
                <Chip
                  key={a.activity_id || ai}
                  label={crewName(a)}
                  selected={o.responsible_party === crewName(a)}
                  onPress={() => updateObservation(i, 'responsible_party', crewName(a))}
                />
              ))}
            </View>

            {/* An observation cannot be saved without a corrective action. A
                logged hazard with no remedy records that something was seen and
                nothing was done. */}
            <Text style={s.question}>{t('observationRemedyRequired')}</Text>
            <TextInput
              style={s.input}
              value={o.remedy}
              onChangeText={(v) => updateObservation(i, 'remedy', v)}
              placeholder={t('phRemedy')}
              placeholderTextColor={outdoor.textDim}
              multiline
            />
            <Pressable
              style={[s.toggleRow, o.corrected_immediately === true && s.toggleRowOn]}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: o.corrected_immediately === true }}
              onPress={() => updateObservation(
                i, 'corrected_immediately', o.corrected_immediately === true ? null : true,
              )}
            >
              {o.corrected_immediately === true
                ? <Check size={22} strokeWidth={3} color={outdoor.ok} />
                : <View style={s.toggleBox} />}
              <Text style={s.toggleText}>{t('correctedImmediately')}</Text>
            </Pressable>

            {missing && (
              <Text style={s.errorText}>{t('observationRemedyMissing')}</Text>
            )}

            <Pressable
              style={s.secondaryBtn}
              accessibilityRole="button"
              onPress={() => removeObservation(i)}
            >
              <Text style={s.secondaryBtnText}>{t('removeObservation')}</Text>
            </Pressable>
          </Card>
        );
      })}

      <Pressable style={s.secondaryBtn} accessibilityRole="button" onPress={addObservation}>
        <Plus size={20} strokeWidth={2} color={outdoor.text} />
        <Text style={s.secondaryBtnText}>{t('addObservation')}</Text>
      </Pressable>

      {/* Who came onto the site who was not working on it — a delivery, a
          visitor, or an INSPECTOR turning up. An inspector's visit belongs
          here, with the other arrivals; the nine items the CP walks himself
          are Step 4, and they are a different statement. Key unchanged. */}
      <Text style={s.question}>{t('sectionVisitors')}</Text>
      <TextInput
        style={s.input}
        value={visitorsDeliveries}
        onChangeText={setVisitorsDeliveries}
        placeholder={t('phVisitors')}
        placeholderTextColor={outdoor.textDim}
        multiline
      />
    </View>
  );

  // ── STEP 4 — the nine daily inspections, walked ───────────────────────
  //
  // These were nine tick-chips under "Items Inspected". A tick could only
  // ever record THAT the CP looked, never what he found — and on a filed DOB
  // 3301-02 a tick beside "Fall Protections" reads as "fall protections are
  // fine", with no way for it to say otherwise.
  //
  // Each item now carries a result and, on a fail, a note saying what failed.
  // NOT WALKED stays a real answer: the CP is not forced through all nine, and
  // an item he did not reach is printed as not inspected rather than being
  // quietly counted as fine.
  const renderStep4 = () => (
    <View>
      <StepHeader title={t('step4Title')} />
      <Text style={s.noteText}>{t('inspectionsHint')}</Text>

      {CHECKLIST_ITEMS.map((it) => {
        const row = inspectionRow(checklistItems, it.key);
        const failed = row.result === INSPECTION_FAIL;
        const noteMissing = failed && !String(row.note || '').trim();
        return (
          <Card s={s} key={it.key} style={noteMissing ? s.cardFlagged : null}>
            <Text style={s.crewName}>{it.label}</Text>
            {row.legacy_ticked && (
              <Text style={s.noteText}>{t('inspectionLegacyTicked')}</Text>
            )}

            <View style={s.chipWrap}>
              <Chip
                label={t('inspectionPass')}
                selected={row.result === INSPECTION_PASS}
                onPress={() => setInspection(it.key, INSPECTION_PASS)}
              />
              <Chip
                label={t('inspectionFail')}
                selected={failed}
                onPress={() => setInspection(it.key, INSPECTION_FAIL)}
              />
            </View>

            {/* A FAILED INSPECTION MUST SAY WHAT FAILED. Without this the fail
                is the same empty record the tick was. */}
            {failed && (
              <>
                <Text style={s.question}>{t('inspectionNoteRequired')}</Text>
                <TextInput
                  style={s.input}
                  value={row.note}
                  onChangeText={(v) => setInspectionNote(it.key, v)}
                  placeholder={t('phInspectionNote')}
                  placeholderTextColor={outdoor.textDim}
                  multiline
                />
                {noteMissing && (
                  <Text style={s.errorText}>{t('inspectionNoteMissing')}</Text>
                )}
              </>
            )}
          </Card>
        );
      })}
    </View>
  );

  // ── STEP 5 — review and sign ──────────────────────────────────────────
  const renderStep5 = () => (
    <View>
      <StepHeader title={t('step5Title')} />
      <Text style={s.question}>{t('reviewHeading')}</Text>

      <Card s={s}>
        <Text style={s.reviewLabel}>{t('fieldAddress')}</Text>
        <Text style={s.reviewValue}>{projectAddress || t('reviewNothingYet')}</Text>
        <Text style={s.reviewLabel}>{t('fieldWeather')}</Text>
        <Text style={s.reviewValue}>
          {weatherFetchState === 'ok' && weather
            ? [weather, weatherTemp, weatherWind].filter(Boolean).join(' · ')
            : t('weatherUnavailableTitle')}
        </Text>
      </Card>

      {activities.map((a, i) => (
        <Card s={s} key={a.activity_id || i}>
          <Text style={s.reviewCrew}>{a.crew_id} · {crewName(a)}</Text>
          {/* He is NOT dropped from the review. He was on site and the signed
              record has to say so — it simply does not claim he did work. */}
          {isUnassignedWorkerRow(a) && (
            <Text style={s.correctedNote}>{t('unassignedTitle')}</Text>
          )}
          {!!a.company_gate && rosterKey(a.company_gate) !== rosterKey(a.company) && (
            <Text style={s.correctedNote}>{t('correctedFrom')}: {a.company_gate}</Text>
          )}
          <Text style={s.reviewValue}>
            {plural('workers_one', 'workers_other', parseInt(a.num_workers, 10) || 0)}
          </Text>
          <Text style={s.reviewLabel}>{t('colWorkDescription')}</Text>
          <Text style={s.reviewValue}>{a.work_description || t('reviewNothingYet')}</Text>
          <Text style={s.reviewLabel}>{t('colWorkLocations')}</Text>
          <Text style={s.reviewValue}>{a.work_locations || t('reviewNothingYet')}</Text>
          {(a.photos || []).length > 0 && (
            <Text style={s.reviewValue}>
              {plural('photosCount_one', 'photosCount_other', (a.photos || []).length)}
            </Text>
          )}
        </Card>
      ))}

      {observations.length > 0 && (
        <Card s={s}>
          <Text style={s.reviewLabel}>{t('sectionObservations')}</Text>
          {observations.map((o, i) => (
            <Text key={i} style={s.reviewValue}>
              {o.description || t('reviewNothingYet')}
              {o.responsible_party ? ` — ${o.responsible_party}` : ''}
            </Text>
          ))}
        </Card>
      )}

      {/* THE INSPECTIONS, AS THEY WILL PRINT. A fail is called a fail here,
          in red, with what failed — the CP is signing this, and the one thing
          he must not be able to sign without seeing is an inspection he
          recorded as failed. Items he did not walk are named too: a missing
          item is not a passed one. */}
      <Card s={s}>
        <Text style={s.reviewLabel}>{t('sectionInspected')}</Text>
        {(() => {
          const rows = CHECKLIST_ITEMS.map((it) => ({
            it, row: inspectionRow(checklistItems, it.key),
          }));
          const passed = rows.filter((r) => r.row.result === INSPECTION_PASS);
          const failed = rows.filter((r) => r.row.result === INSPECTION_FAIL);
          const unwalked = rows.filter((r) => r.row.result === null);
          if (passed.length === 0 && failed.length === 0) {
            return <Text style={s.reviewValue}>{t('reviewInspectionsNone')}</Text>;
          }
          return (
            <>
              {failed.map(({ it, row }) => (
                <Text key={it.key} style={s.errorText}>
                  {t('inspectionFail').toUpperCase()} — {it.label}
                  {row.note ? `: ${row.note}` : ''}
                </Text>
              ))}
              {passed.length > 0 && (
                <Text style={s.reviewValue}>
                  {t('reviewInspectionsPassed')}: {passed.map((r) => r.it.label).join(', ')}
                </Text>
              )}
              {unwalked.length > 0 && (
                <Text style={s.reviewValue}>
                  {t('reviewInspectionsNotWalked')}: {unwalked.map((r) => r.it.label).join(', ')}
                </Text>
              )}
            </>
          );
        })()}
      </Card>

      {/* DRAFTED, NOT WRITTEN. Composed from the trades of the chips the CP
          tapped, shown here before he signs, and editable — he is attesting to
          this sentence, so the app may propose it and may not put words he
          never read into the record. Empty when nothing was tapped. */}
      <Card s={s}>
        <Text style={s.reviewLabel}>{t('fieldGeneralDescription')}</Text>
        <TextInput
          style={s.input}
          value={generalDescription}
          onChangeText={(v) => { setDescriptionTouched(true); setGeneralDescription(v); }}
          placeholder={t('phGeneralDescription')}
          placeholderTextColor={outdoor.textDim}
          multiline
        />
        <Text style={s.noteText}>
          {suggestedDescription ? t('descriptionDrafted') : t('descriptionEmpty')}
        </Text>
      </Card>

      <Card s={s}>
        <SignaturePad
          title={t('sectionSignOff')}
          signerName={cpName}
          onNameChange={setCpName}
          existingSignature={cpSignature}
          onSignatureCapture={setCpSignature}
        />
      </Card>

      <Text style={s.noteText}>{t('signingClosesDay')}</Text>
    </View>
  );

  const STEPS = {
    1: renderStep1, 2: renderStep2, 3: renderStep3, 4: renderStep4, 5: renderStep5,
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <View style={s.header}>
          <Pressable
            style={s.headerBack}
            accessibilityRole="button"
            accessibilityLabel={t('back')}
            onPress={() => (step === 1 ? router.push('/logbooks') : goBack())}
          >
            <ArrowLeft size={24} strokeWidth={2} color={outdoor.text} />
          </Pressable>
          <View style={s.headerText}>
            <Text style={s.headerTitle}>{t('screenTitle')}</Text>
            <Text style={s.headerSub}>{FORM_NUMBER} · {formatLogDate(date)}</Text>
          </View>
        </View>

        {/* Progress — marks only. It never gates. */}
        <View style={s.progressRow}>
          {[1, 2, 3, 4, 5].map((n) => (
            <View key={n} style={[s.progressPip, n <= step && s.progressPipOn]} />
          ))}
        </View>

        <ScrollView style={s.scroll} contentContainerStyle={s.scrollContent}>
          {/* A finalized log renders read-only. pointerEvents 'none' makes
              EVERY control below non-interactive — no per-field flags to miss.
              Scrolling still works; the LockBar stays interactive. */}
          <View pointerEvents={locked ? 'none' : 'auto'}>
            {STEPS[step]()}
          </View>

          <LogbookLockBar
            logType={'daily_jobsite'}
            locked={locked}
            logId={existingLogId}
            draftKey={draftKey({ projectId, logType: 'daily_jobsite', date })}
            canFinalize={false}
            onFinalized={() => setLocked(true)}
            onAmended={fetchData}
          />
          <Text style={s.autosaveNote}>{t('savedAutomatically')}</Text>
        </ScrollView>

        {/* ONE PRIMARY ACTION, and it is the largest element on the screen. */}
        {!locked && (
          <View style={s.footer}>
            {step < TOTAL_STEPS ? (
              <Pressable
                style={s.primaryBtn}
                accessibilityRole="button"
                accessibilityLabel={t('next')}
                onPress={goNext}
              >
                <Text style={s.primaryBtnText}>{t('next')}</Text>
                <ArrowRight size={26} strokeWidth={2.5} color={outdoor.textOnSelected} />
              </Pressable>
            ) : (
              <Pressable
                style={s.primaryBtn}
                accessibilityRole="button"
                accessibilityLabel={t('submitAndSign')}
                disabled={signing}
                onPress={handleSubmitAndSign}
              >
                {signing
                  ? <ActivityIndicator size="small" color={outdoor.textOnSelected} />
                  : <Check size={26} strokeWidth={2.5} color={outdoor.textOnSelected} />}
                <Text style={s.primaryBtnText}>{t('submitAndSign')}</Text>
              </Pressable>
            )}
          </View>
        )}
      </SafeAreaView>

      {/* OUTSIDE the SafeAreaView on purpose: on native this is a pre-warmed
          full-screen absolute overlay, and inside the SafeAreaView its absolute
          fill would stop at the safe-area inset instead of going full-bleed. */}
      <CameraCaptureModal
        visible={cameraVisible}
        shots={cameraShots}
        onClose={() => setCameraVisible(false)}
        onCapture={handleCameraCapture}
        onDeleteShot={handleDeleteShot}
      />

      <PromptModal
        visible={!!otherPrompt}
        title={otherPrompt?.kind === 'location' ? t('locationOtherPrompt') : t('chipOtherPrompt')}
        value={otherPrompt?.value || ''}
        placeholder={otherPrompt?.kind === 'location' ? t('phWorkLocations') : t('phWorkPerformed')}
        onChange={(v) => setOtherPrompt((p) => ({ ...p, value: v }))}
        onCancel={() => setOtherPrompt(null)}
        onConfirm={commitOther}
        confirmLabel={t('next')}
        cancelLabel={t('cancel')}
        s={s}
      />

      <Modal
        visible={!!addingCrew}
        transparent
        animationType="fade"
        onRequestClose={() => setAddingCrew(null)}
      >
        <View style={s.modalOverlay}>
          <View style={s.modalCard}>
            <Text style={s.modalTitle}>{t('addCrewTitle')}</Text>
            <TextInput
              style={s.input}
              value={addingCrew?.company || ''}
              onChangeText={(v) => setAddingCrew((p) => ({ ...p, company: v }))}
              placeholder={t('phCompany')}
              placeholderTextColor={outdoor.textDim}
            />
            <TextInput
              style={s.input}
              value={addingCrew?.num || ''}
              onChangeText={(v) => setAddingCrew((p) => ({ ...p, num: v }))}
              placeholder={t('workers_one')}
              placeholderTextColor={outdoor.textDim}
              keyboardType="numeric"
            />
            <View style={s.modalActions}>
              <Pressable
                style={s.secondaryBtn}
                accessibilityRole="button"
                onPress={() => setAddingCrew(null)}
              >
                <Text style={s.secondaryBtnText}>{t('cancel')}</Text>
              </Pressable>
              <Pressable style={s.primaryBtn} accessibilityRole="button" onPress={commitAddCrew}>
                <Text style={s.primaryBtnText}>{t('next')}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      <Modal
        visible={!!photoLightbox}
        transparent
        animationType="fade"
        onRequestClose={() => setPhotoLightbox(null)}
      >
        <Pressable style={s.lightboxOverlay} onPress={() => setPhotoLightbox(null)}>
          <Pressable
            style={s.lightboxClose}
            hitSlop={16}
            accessibilityRole="button"
            onPress={() => setPhotoLightbox(null)}
          >
            <X size={28} color={outdoor.textOnSelected} />
          </Pressable>
          {photoLightbox?.uri ? (
            <Image source={{ uri: photoLightbox.uri }} style={s.lightboxImage} resizeMode="contain" />
          ) : null}
          {photoLightbox?.label ? (
            <Text style={s.lightboxLabel}>{photoLightbox.label}</Text>
          ) : null}
        </Pressable>
      </Modal>
    </AnimatedBackground>
  );
}

/**
 * A card, rendered the way the rest of the app renders one.
 *
 * This is GlassCard's light-mode appearance, rebuilt rather than reused: a
 * white->blue-100 vertical gradient, a 32pt corner, a soft diffuse shadow and
 * the glass border. GlassCard itself is theme-aware and would go dark for a CP
 * with dark mode on, which the outdoor rule forbids — see the note on
 * `outdoor` in theme.js.
 *
 * TWO NESTED VIEWS ON PURPOSE. The shadow lives on the OUTER view and the
 * gradient on the inner one: a shadow and `overflow: 'hidden'` on the same view
 * clip each other on iOS, so the rounded gradient would square off or the
 * shadow would vanish.
 */
function Card({ s, style, children }) {
  return (
    <View style={[s.cardShadow, style]}>
      <LinearGradient
        colors={[outdoor.cardTop, outdoor.cardBottom]}
        start={{ x: 0.5, y: 0 }}
        end={{ x: 0.5, y: 1 }}
        style={s.cardFill}
      >
        {children}
      </LinearGradient>
    </View>
  );
}

/**
 * One chip. Selection is carried on accessibilityState as well as in the
 * styling, so the state is available to a screen reader and to a test — not
 * only to someone who can see the colour.
 */
function ChipBase({ s, label, selected, onPress }) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityState={{ selected: !!selected }}
      accessibilityLabel={label}
      style={[s.chip, selected && s.chipSelected]}
    >
      <Text style={[s.chipText, selected && s.chipTextSelected]}>{label}</Text>
    </Pressable>
  );
}

function StepHeaderBase({ s, count, title }) {
  return (
    <View style={s.stepHeader}>
      <Text style={s.stepCount}>{count}</Text>
      <Text style={s.stepTitle}>{title}</Text>
    </View>
  );
}

/** One text prompt, used by the company correction and both "Other" entries. */
function PromptModal({
  visible, title, hint, value, placeholder, onChange, onCancel, onConfirm,
  confirmLabel, cancelLabel, s,
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={s.modalOverlay}>
        <View style={s.modalCard}>
          <Text style={s.modalTitle}>{title}</Text>
          {!!hint && <Text style={s.noteText}>{hint}</Text>}
          <TextInput
            style={s.input}
            value={value}
            onChangeText={onChange}
            placeholder={placeholder}
            placeholderTextColor={outdoor.textDim}
            autoFocus
          />
          <View style={s.modalActions}>
            <Pressable style={s.secondaryBtn} accessibilityRole="button" onPress={onCancel}>
              <Text style={s.secondaryBtnText}>{cancelLabel}</Text>
            </Pressable>
            <Pressable style={s.primaryBtn} accessibilityRole="button" onPress={onConfirm}>
              <Text style={s.primaryBtnText}>{confirmLabel}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/**
 * Every value below comes from the token file. No literal colour, size, radius
 * or spacing appears in this StyleSheet — that is asserted by
 * src/utils/dailyJobsiteStepper.test.cjs, which fails on a raw hex, rgba(), or
 * a numeric fontSize.
 *
 * Not theme-dependent, so it is built once: the outdoor palette deliberately
 * does not flip (see theme.js).
 */
function buildStyles() {
  return StyleSheet.create({
    container: { flex: 1 },
    loadingCenter: { flex: 1, alignItems: 'center', justifyContent: 'center' },

    header: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.md,
      paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    },
    // GlassButton's icon variant is a 44x44 circular pill. Same look here, but
    // the 56pt floor wins over the visual size: the constraint is a gloved
    // thumb outdoors, not the component.
    headerBack: {
      minWidth: touchTarget.min, minHeight: touchTarget.min,
      alignItems: 'center', justifyContent: 'center',
      borderRadius: borderRadius.full,
      backgroundColor: outdoor.surface,
      borderWidth: 1, borderColor: outdoor.line,
    },
    headerText: { flex: 1 },
    headerTitle: {
      fontSize: typography.sizes.lg, fontWeight: '700', color: outdoor.text,
    },
    headerSub: { fontSize: typography.sizes.fine, color: outdoor.textDim },

    progressRow: {
      flexDirection: 'row', gap: spacing.xs, paddingHorizontal: spacing.md,
      paddingBottom: spacing.sm,
    },
    progressPip: {
      flex: 1, height: spacing.xs, borderRadius: borderRadius.sm,
      backgroundColor: outdoor.line,
    },
    progressPipOn: { backgroundColor: outdoor.surfaceSelected },
    // ── COMPACT STEP 1 ────────────────────────────────────────────────
    // 40pt: two 13pt lines plus 4pt padding. NOT a touch target, because the
    // row is not tappable — see the note above renderStep1. Anything that
    // makes it interactive goes back to touchTarget.min and the fit
    // arithmetic has to be redone.
    crewRow: {
      paddingVertical: spacing.xs, paddingHorizontal: spacing.sm,
      borderBottomWidth: 1, borderBottomColor: outdoor.line,
    },
    crewRowFlagged: {
      backgroundColor: outdoor.warnBg,
      borderLeftWidth: 2, borderLeftColor: outdoor.warn,   // bw2
    },
    crewRowMain: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
    crewRowName: {
      flex: 1, fontSize: typography.sizes.dense, fontWeight: '700',
      color: outdoor.text,
    },
    crewRowMeta: { fontSize: typography.sizes.fine, color: outdoor.textSoft },
    crewRowFlag: { fontSize: typography.sizes.fine, color: outdoor.warn },
    // The equipment summary IS tappable, so it carries the full minimum.
    summaryRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      minHeight: touchTarget.min, paddingHorizontal: spacing.sm,
      marginTop: spacing.md,
    },
    summaryLabel: {
      fontSize: typography.sizes.fine, fontWeight: '600', color: outdoor.textDim,
    },
    summaryValue: {
      flex: 1, fontSize: typography.sizes.dense, color: outdoor.text,
      textAlign: 'right',
    },

    // NO background colour. The flat grey was covering AnimatedBackground's
    // blue-tinted gradient, which is what made this screen read as foreign
    // beside every other one.
    scroll: { flex: 1 },
    scrollContent: { padding: spacing.md, paddingBottom: spacing.xxl },

    stepHeader: { marginBottom: spacing.md },
    stepCount: {
      fontSize: typography.sizes.fine, fontWeight: '600', color: outdoor.textDim,
      letterSpacing: spacing.xs / 4, textTransform: 'uppercase',
    },
    stepTitle: {
      fontSize: typography.sizes.xl, fontWeight: '700', color: outdoor.text,
    },

    // Shadow on the outer view, gradient on the inner - see Card.
    cardShadow: {
      borderRadius: borderRadius.xxl,
      marginBottom: spacing.md,
      backgroundColor: outdoor.cardTop,
      ...outdoorShadow,
    },
    cardFill: {
      borderRadius: borderRadius.xxl,
      borderWidth: 1,
      borderColor: outdoor.line,
      padding: spacing.xl,
      gap: spacing.sm,
      overflow: 'hidden',
    },
    cardFlagged: { borderColor: outdoor.warnBorder },
    cardWarn: { backgroundColor: outdoor.warnBg },
    crewTop: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      gap: spacing.sm, flexWrap: 'wrap',
    },
    crewName: {
      fontSize: typography.sizes.lg, fontWeight: '700', color: outdoor.text, flexShrink: 1,
    },
    crewMeta: { fontSize: typography.sizes.sm, color: outdoor.textSoft },

    // The app renders a count / status as a small rounded pill badge - see the
    // reference screen's countBadge and autoFilledBadge.
    gateBadge: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.xs,
      backgroundColor: outdoor.accentBg, borderRadius: borderRadius.full,
      borderWidth: 1, borderColor: outdoor.accentBorder,
      paddingHorizontal: spacing.sm, paddingVertical: spacing.xs,
    },
    gateBadgeText: {
      fontSize: typography.sizes.fine, fontWeight: '700', color: outdoor.accent,
    },

    correctedNote: {
      fontSize: typography.sizes.fine, color: outdoor.textDim, fontStyle: 'italic',
    },

    unboundBox: {
      backgroundColor: outdoor.warnBg, borderRadius: borderRadius.lg,
      borderWidth: 1, borderColor: outdoor.warnBorder, padding: spacing.md,
    },
    unboundTitle: {
      fontSize: typography.sizes.dense, fontWeight: '700', color: outdoor.text,
    },
    unboundText: { fontSize: typography.sizes.fine, color: outdoor.textSoft },

    // The warning is now the CONTENT of a Card, so it carries only its layout.
    warnCard: {
      flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-start',
    },
    warnBody: { flex: 1, gap: spacing.xs },
    warnTitle: {
      fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
    },
    warnText: { fontSize: typography.sizes.sm, color: outdoor.textSoft },

    question: {
      fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
      marginTop: spacing.sm,
    },
    noteText: { fontSize: typography.sizes.dense, color: outdoor.textDim },
    emptyText: {
      fontSize: typography.sizes.md, color: outdoor.textSoft, paddingVertical: spacing.md,
    },
    errorText: {
      fontSize: typography.sizes.dense, fontWeight: '600', color: outdoor.danger,
    },
    lockedHint: {
      fontSize: typography.sizes.sm, color: outdoor.textSoft,
      backgroundColor: outdoor.surfaceSunk, borderRadius: borderRadius.lg,
      padding: spacing.md,
    },

    chipWrap: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
    chip: {
      minHeight: touchTarget.min, justifyContent: 'center',
      paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
      borderRadius: borderRadius.full, borderWidth: 1,
      borderColor: outdoor.lineStrong, backgroundColor: outdoor.surface,
    },
    chipSelected: {
      backgroundColor: outdoor.surfaceSelected, borderColor: outdoor.surfaceSelected,
    },
    chipText: {
      fontSize: typography.sizes.md, fontWeight: '600', color: outdoor.text,
    },
    chipTextSelected: { color: outdoor.textOnSelected },

    input: {
      minHeight: touchTarget.min, borderRadius: borderRadius.lg, borderWidth: 1,
      borderColor: outdoor.lineStrong, backgroundColor: outdoor.surface,
      paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
      fontSize: typography.sizes.md, color: outdoor.text,
    },

    toggleRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      minHeight: touchTarget.min, paddingHorizontal: spacing.md,
      borderRadius: borderRadius.full, borderWidth: 1,
      borderColor: outdoor.lineStrong,
    },
    toggleRowOn: { borderColor: outdoor.okBorder, backgroundColor: outdoor.okBg },
    toggleBox: {
      width: spacing.lg, height: spacing.lg, borderRadius: borderRadius.sm,
      borderWidth: 2, borderColor: outdoor.lineStrong,
    },
    toggleText: { fontSize: typography.sizes.md, color: outdoor.text, flex: 1 },

    photoBlock: { gap: spacing.sm },
    taggedWith: {
      fontSize: typography.sizes.fine, color: outdoor.textSoft,
      backgroundColor: outdoor.surfaceSunk, borderRadius: borderRadius.lg,
      padding: spacing.md,
    },
    photoCount: {
      fontSize: typography.sizes.fine, fontWeight: '600', color: outdoor.textDim,
    },
    photoGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
    photoThumb: { position: 'relative' },
    photoImage: {
      width: touchTarget.primary, height: touchTarget.primary,
      borderRadius: borderRadius.sm, backgroundColor: outdoor.surfaceSunk,
    },
    photoPending: { alignItems: 'center', justifyContent: 'center' },
    photoRemove: {
      position: 'absolute', top: 0, right: 0,
      width: spacing.lg, height: spacing.lg, borderRadius: borderRadius.full,
      alignItems: 'center', justifyContent: 'center',
      backgroundColor: outdoor.danger,
    },
    photoActions: { flexDirection: 'row', gap: spacing.sm },
    photoBtn: {
      flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.sm, minHeight: touchTarget.min,
      borderRadius: borderRadius.full,
      backgroundColor: outdoor.surfaceSelected,
    },
    photoBtnText: {
      fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.textOnSelected,
    },
    photoBtnGhost: {
      flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.sm, minHeight: touchTarget.min,
      borderRadius: borderRadius.full,
      borderWidth: 1, borderColor: outdoor.lineStrong,
      backgroundColor: outdoor.surface,
    },
    photoBtnGhostText: {
      fontSize: typography.sizes.md, fontWeight: '600', color: outdoor.text,
    },

    readOnlyValue: {
      backgroundColor: outdoor.surfaceSunk, borderRadius: borderRadius.lg,
      padding: spacing.md, gap: spacing.xs,
    },
    readOnlyText: {
      fontSize: typography.sizes.lg, fontWeight: '600', color: outdoor.text,
    },
    reviewCrew: {
      fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
    },
    reviewLabel: {
      fontSize: typography.sizes.fine, fontWeight: '600', color: outdoor.textDim,
      textTransform: 'uppercase',
    },
    reviewValue: { fontSize: typography.sizes.md, color: outdoor.text },

    secondaryBtn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.sm, minHeight: touchTarget.min,
      paddingHorizontal: spacing.lg, borderRadius: borderRadius.full,
      borderWidth: 1, borderColor: outdoor.lineStrong,
      backgroundColor: outdoor.surface,
    },
    secondaryBtnText: {
      fontSize: typography.sizes.md, fontWeight: '600', color: outdoor.text,
    },

    footer: { padding: spacing.md },
    primaryBtn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.sm, minHeight: touchTarget.primary,
      borderRadius: borderRadius.full, backgroundColor: outdoor.surfaceSelected,
      paddingHorizontal: spacing.xl,
      ...outdoorShadow,
    },
    primaryBtnText: {
      fontSize: typography.sizes.xl, fontWeight: '700', color: outdoor.textOnSelected,
    },

    autosaveNote: {
      fontSize: typography.sizes.fine, color: outdoor.textDim,
      textAlign: 'center', paddingVertical: spacing.sm,
    },

    modalOverlay: {
      flex: 1, alignItems: 'center', justifyContent: 'center',
      backgroundColor: outdoor.scrim, padding: spacing.md,
    },
    modalCard: {
      width: '100%', backgroundColor: outdoor.cardTop,
      borderRadius: borderRadius.xxl,
      padding: spacing.xl, gap: spacing.sm, ...outdoorShadow,
    },
    modalTitle: {
      fontSize: typography.sizes.lg, fontWeight: '700', color: outdoor.text,
    },
    modalActions: { flexDirection: 'row', gap: spacing.sm },

    lightboxOverlay: {
      flex: 1, alignItems: 'center', justifyContent: 'center',
      backgroundColor: outdoor.scrim,
    },
    lightboxClose: {
      position: 'absolute', top: spacing.xl, right: spacing.lg,
      minWidth: touchTarget.min, minHeight: touchTarget.min,
      alignItems: 'center', justifyContent: 'center',
    },
    lightboxImage: { width: '100%', height: '80%' },
    lightboxLabel: {
      position: 'absolute', bottom: spacing.xl,
      fontSize: typography.sizes.sm, color: outdoor.textOnSelected,
    },
  });
}
