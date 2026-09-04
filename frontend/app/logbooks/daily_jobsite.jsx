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
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator,
  Image, Modal, Platform,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { LinearGradient } from 'expo-linear-gradient';
import {
  Check, Camera, X, ImageIcon, Plus, AlertTriangle, Lock, Trash2,
} from 'lucide-react-native';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI, weatherAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { useT } from '../../src/i18n';
import {
  spacing, borderRadius, typography, touchTarget, outdoor, outdoorShadow,
} from '../../src/styles/theme';
import { opacity } from '../../src/styles/tokens';
import LogbookStepper from '../../src/components/logbookStepper/LogbookStepper';
import { isAffirmedSignature, affirmationHintKey } from '../../src/utils/signatureAffirmed';
import { buildStepperStyles } from '../../src/components/logbookStepper/styles';
import { Card, ChipBase, StepHeaderBase, PromptModal } from '../../src/components/logbookStepper/primitives';
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
import { compareDraftToServer, submitRefused } from '../../src/utils/draftFreshness';
// finalizeErrorCode is the ONE place a FINALIZE_* code is pulled out of an
// axios error (and the one place that guarantees the server's English `detail`
// never reaches a screen); clearFinalizeError removes the drain's persistent
// "NOT LOCKED ON THE SERVER" banner once this screen finalizes for real;
// recordFinalizeError RAISES that same banner, so a refusal taken here in the
// foreground leaves the identical durable trace a background one does.
import { finalizeErrorCode, clearFinalizeError, recordFinalizeError } from '../../src/utils/draftSync';
import { chooseEditableLog } from '../../src/utils/logbookEditable';
// The app-wide OFFLINE discriminator — the same one settleFetch is built on.
// "Offline" here has to mean what it means everywhere else: no response at all.
import { isOfflineError, settleFetch, failureDetail } from '../../src/utils/offlineState';
import { adoptAmendment } from '../../src/utils/amendmentAdopt';
import * as ImagePicker from 'expo-image-picker';
import { useEsraConsent } from '../../src/hooks/useEsraConsent';
import {
  composeChipBands,
  EMPTY_ACTIVITY, EMPTY_OBSERVATION, newActivityId, buildCrewsFromRoster,
  rosterIdIndex,
  composeSelection, cameraReady, resolveRosterId, isUnboundCrew,
  isUnassignedWorkerRow, workRows, crewsWithoutWork, tradeLabel,
  hasNoWorkersOnSite, reconcileCrewsWithRoster,
  applyHeadcountEdit, isHeadcountOverridden, gateHeadcount, CP_SOURCE,
  isDeletableCrew, crewDeleteImpact,
  INSPECTION_PASS, INSPECTION_FAIL, inspectionRow, incompleteInspections,
  isOtherInspection,
  deriveGeneralDescription,
  observationComplete, incompleteObservations, formatLogDate, formatCheckInTime,
  stepComplete,
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

// A ROW THAT ARRIVES WITHOUT AN activity_id NEVER GETS ONE OTHERWISE.
// EMPTY_ACTIVITY (dailyJobsiteModel.js) is the only writer of that field and
// nothing backfills it, so a row saved by a build older than 2026-08-10 stays
// id-less for the life of the log. Its photos then upload under
// logbook-photos/{project}/{photo_id}/... through the `activityId || photoId`
// fallback in logbookDrafts.js -- addressable, but the activity grouping is
// gone and one document ends up carrying two key shapes.
//
// BACKFILLING CANNOT MOVE AN EXISTING PHOTO. `original_r2_key` is stored per
// photo and read back verbatim (server.py _logbook_photo_sources reads the
// field; it never recomputes), and the ONLY place a capture key is built is
// the upload endpoint, at upload time. Photos already on the row keep their
// cap_ keys and keep resolving; only photos taken AFTER this runs use the
// row's new id. A row may therefore hold both shapes, which is the documented
// state -- server.py:158, "BOTH SCHEMES COEXIST, AND NOTHING IS MIGRATED".
const withActivityIds = (rows) => (rows || []).map(
  (a) => ((a && typeof a === 'object' && !a.activity_id)
    ? { ...a, activity_id: newActivityId() } : a),
);

// Stable identity for one photo tile across re-renders. A saved photo has no
// `id` -- photoForPayload strips it before the row is written -- so the R2 key
// leads, and the position is the last resort for a photo that has neither.
const tileKey = (photo, ai, pi) => String(
  photo?.original_r2_key || photo?.id || `${ai}-${pi}`,
);

// WHERE A PHOTO SITS IN THE DOCUMENT THE SERVER HOLDS.
//
// The served photo url addresses data.activities[ai].photos[pi] on the SERVER
// document (server.py get_logbook_activity_photo walks those two indexes and
// nothing else). The tile was handing it the index of the row IN THIS SCREEN'S
// LIST, and the two are not the same list: reconcileCrewsWithRoster lifts every
// unassigned-worker row out of its stored position and re-appends it at the
// tail (dailyJobsiteModel.js, `if (isUnassignedWorkerRow(row)) continue`), and
// commitAddCrew appends a hand-added crew AFTER those rows. So a sub the CP
// typed in himself moves UP by one on the next load, its tiles request whatever
// now stands at that index, and nothing has been re-saved — the server is still
// holding the old order. A wrong index is a 404 at best and ANOTHER CREW'S
// PHOTO at worst, on a document that gets signed.
//
// KEYED ON THE R2 KEY, which is the photo's only stable identity here: it is a
// pure function of (project_id, activity_id, photo_id), it is read off the
// photo document and never recomputed (server.py:158, "BOTH SCHEMES COEXIST"),
// and photoForPayload strips `id` before the row is ever written.
const photoServeKey = (photo) => String(
  photo?.original_r2_key || photo?.enhanced_r2_key || photo?.thumb_r2_key || '',
);

// The map, built from an activities array AS THE SERVER HOLDS IT. A photo with
// no key is absent from it on purpose: it has no object to serve, so there is
// nothing for a coordinate to address.
const servedPhotoCoords = (activities) => {
  const m = new Map();
  (Array.isArray(activities) ? activities : []).forEach((a, ai) => (
    ((a && a.photos) || []).forEach((p, pi) => {
      const k = photoServeKey(p);
      if (k && !m.has(k)) m.set(k, [ai, pi]);
    })
  ));
  return m;
};

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
    // `uri` IS DROPPED HERE, AND ONLY HERE. A file:///data/user/0/... path is
    // a claim about ONE phone's storage, and writing it into a filed
    // compliance record is what made these photos unviewable on every other
    // device: photoTileUri preferred it, the file did not exist, and a dead
    // path is truthy so the fallback chain never advanced past it.
    //
    // ONLY ONCE THE KEY EXISTS. Before upload, `uri` is the only handle on the
    // image -- photoNeedsUpload and the offline drain find the file through
    // it, and persistPhoto THROWS on a failed copy precisely to guarantee it
    // survives. Stripping it from an un-uploaded photo would lose the photo.
    //
    // THE LOCAL DRAFT KEEPS IT. draftBody passes activities through untouched;
    // this function feeds only the server payload (see payloadActivities). So
    // the capturing phone keeps a fast, offline-readable copy while the record
    // itself stops asserting anything about that phone's filesystem.
    const { upload_pending, upload_rejected, uri, ...done } = stored; // eslint-disable-line no-unused-vars
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
  const consent = useEsraConsent();
  const params = useLocalSearchParams();
  const projectId = params.projectId;
  // A date derived for a query or a record uses the Eastern helper. On the UTC
  // clock this default would ask for TOMORROW from 20:00 EDT and file the log
  // under it. That bug shipped thirteen times; this is not the fourteenth.
  const date = params.date || easternToday();
  const { user } = useAuth();
  const toast = useToast();
  // profileLoaded distinguishes "no signature" from "still loading" — a CP
  // must never be told he is unsigned while his own credential is on its way.
  const {
    cpName, setCpName, cpSignature, setCpSignature, profileLoaded, autoSave,
  } = useCpProfile();
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
  // The EXISTING-LOG read, as a three-way outcome rather than an array. null
  // is "the read came back"; 'offline' / 'error' are the two ways it did not.
  const [logReadFailed, setLogReadFailed] = useState(null);
  const [logReadError, setLogReadError] = useState(null);
  const [signing, setSigning] = useState(false);
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
  // `timeIn` / `timeOut` WERE HERE, AND THEY ARE GONE. Two useState pairs, two
  // payload keys and two hydrate lines, with no control anywhere in the app
  // that ever set either one — so every daily jobsite log since the U1 rebuild
  // filed `time_in: ""` and both PDF renderers printed a row that said N/A
  // forever. A field that is always N/A on a compliance record teaches its
  // reader to skip the row, which is worse than not printing it.
  //
  // NOT REPLACED BY A PICKER HERE. The CP's own hours are not what 3301-02
  // asks this log for; they are item 1 of the SUPERINTENDENT log, where they
  // are now `presence.arrived_at` / `presence.departed_at`, chosen from a
  // clock and required before it will file.
  //
  // THE READERS ARE LEFT STANDING ON PURPOSE. app/site/logbooks.jsx and
  // generate_combined_report both print these keys only when a stored log
  // carries them, so a record filed before the U1 rebuild still shows what it
  // said. Deleting the writer is forward-only; deleting the reader would
  // change what an already-signed document looks like.
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

  // ── APPENDING A PHOTOGRAPH TO A LOG THAT IS ALREADY FILED ─────────────
  //
  // A photograph is not DOB-required daily log content, so adding one is not
  // an amendment to what the CP attested. This state serves the ONE affordance
  // a read-only form still offers; everything else on the screen stays inert
  // behind LogbookStepper's pointerEvents wrapper, which does not move.
  //
  // `filedLog` IS THE SERVER'S DOCUMENT, not `activities`. The panel names rows
  // by the identity the SERVER stored: on a filed-but-unlocked log the local
  // list has been reconciled against the roster and withActivityIds has minted
  // ids for rows that never had one, and neither of those is a row the append
  // could reach. Reading the loaded document keeps the panel honest about which
  // rows exist and which of them can take a photo at all.
  const [filedLog, setFiledLog] = useState(null);

  // ── Modals ────────────────────────────────────────────────────────────
  const [addingCrew, setAddingCrew] = useState(null);      // {company, trade, num}
  // The card the CP has asked to remove, with its impact already computed.
  const [deletingCrew, setDeletingCrew] = useState(null);
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
    areas_visited: areasVisited,
  }), [
    projectAddress, weather, weatherTemp, weatherWind, weatherFetchState,
    generalDescription,
    equipmentOnSite, checklistItems, observations, visitorsDeliveries,
    areasVisited,
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
        // BOTH FAILURE MODES. A false return and a throw both mean the
        // draft was not written; the catch here only ever covered the
        // second, and the first was discarded. Feeds the SUBMIT GATE
        // rather than a toast — see the note in the stepper's
        // submitWarning prop.
        const _ok = await writeDraft(_key, {
          data: draftBody(persisted), cp_signature: cpSignature, cp_name: cpName,
        });
        setAutosaveFailed(!_ok);
      } catch (_e) { setAutosaveFailed(true); }
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
      const _ok = await writeDraft(_key, {
        data: draftBody(persisted), cp_signature: cpSignature, cp_name: cpName,
      });
      setAutosaveFailed(!_ok);
    } catch (_e) { setAutosaveFailed(true); }
  }, [locked, draftBody, cpSignature, cpName]);

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
    setLogReadFailed(null);
    setLogReadError(null);
    try {
      // Local-first: the on-device draft wins, so the screen works fully
      // offline and a reopened log is exactly where the CP left it.
      const draft = await readDraft(_key);
      if (draft?.data && Object.keys(draft.data).length) {
        hydrate(draft.data);
        // AN AMENDMENT MUST REACH THIS SCREEN — device round 5, finding 19.
        // Parent and amendment share ONE draft key (project, logType, date), so
        // a finalized local draft used to lock the editor and return before the
        // server was ever asked: the child sat there unlocked and unreachable
        // while the logbook list showed it as a Draft. amendmentAdopt discards
        // the frozen parent ONLY on server confirmation; offline it is a no-op
        // and the log stays locked, which is honest.
        const _amended = draft.finalized && await adoptAmendment({
          key: _key, projectId, logType: 'daily_jobsite', date,
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
            draft, projectId, logType: 'daily_jobsite', date,
          });
          setDraftConflict(_cmp.conflict ? _cmp : null);
        if (draft.finalized) { setLocked(true); markFinalized(_key); }
        setExistingLogId(draft.backend_id || null);
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);

        // AN EMPTY CREW LIST MUST STILL REBUILD — the third form with this
        // trap (toolbox_talk and preshift_signin were #137; osha_log is the
        // fourth and is fixed in this PR too).
        //
        // The autosave writes `activities: []` the moment the screen settles,
        // so merely OPENING the log before anyone had checked in stored an
        // empty roster for that project and date. This branch then returned
        // before buildCrewsFromRoster could ever run, and the crew list could
        // never recover: thirteen men on site, step 1 listing nobody, across
        // two force-closes.
        //
        // REBUILT IN PLACE rather than by falling through to the server path.
        // Falling through would re-hydrate from the server and discard local
        // work — an offline CP who wrote observations with no crews yet would
        // lose them. Only the roster is rebuilt; everything else the draft
        // holds is left exactly as he left it.
        //
        // Offline the fetches fail, nothing is built, and an empty list is the
        // honest answer — it is also what was already on screen.
        const _storedCrews = Array.isArray(draft.data.activities)
          ? draft.data.activities : [];
        // AND A NON-EMPTY LIST IS RECONCILED. The empty-list rebuild above is
        // unchanged and still necessary; what was missing is the other half.
        // A stored list was never compared against today's roster again, so a
        // crew that arrived after this draft was first opened never reached
        // the log at all, and one that left kept its original headcount for
        // the rest of the day. The fetch is no longer inside the empty branch
        // because both cases need it.
        //
        // OFFLINE IS UNCHANGED: the fetches fail, `_roster` is null, nothing
        // is rebuilt and nothing is reconciled — the stored list stands
        // exactly as he left it, which is also what was already on screen.
        let _resolved = _storedCrews;
        const [_roster, _headcount, _serverLogs] = await Promise.all([
          logbooksAPI.getCheckinsRoster(projectId, date).catch(() => null),
          logbooksAPI.getDailyHeadcount(projectId, date).catch(() => []),
          // THE DAY'S SERVER ROW, FOR ITS ID AND ITS PHOTO LAYOUT ONLY.
          //
          // THE DEFECT THIS CLOSES. This branch set the id from one place —
          // `draft.backend_id || null` above — and daily_jobsite writes
          // backend_id in one place: setDraftBackendId, after THIS DEVICE
          // pushes. A CP who OPENS the superintendent's filed log pushes
          // nothing. The 800ms autosave then writes a draft holding the
          // server's activities with `backend_id: null`, and every later open
          // lands here with existingLogId null.
          //
          // WHICH BLANKS EVERY PHOTO HE DID NOT TAKE. getLogbookPhotoUrl
          // returns null without an id, and a photo captured on another phone
          // has no `uri` on the record (photoForPayload strips it once the R2
          // key exists) and no `base64` (it would blow the 16MB ceiling). So
          // photoTileUri resolves to `undefined` — no request, which means no
          // onError, which means the retry built for exactly this never runs.
          // A blank square, permanently, on every crew the super photographed.
          // cpForeignPhotoResolution.test.cjs prints the resolved value.
          //
          // ONLY THE ID AND THE LAYOUT. The draft still wins on CONTENT — that
          // is this branch's whole purpose, and an offline CP's local work
          // depends on it. Nothing below hydrates from this response.
          //
          // OFFLINE IS UNCHANGED: the read fails, this is null, the id stays
          // exactly what the draft said and the screen is what it was.
          logbooksAPI.getByProject(projectId, 'daily_jobsite', date).catch(() => null),
        ]);
        if (Array.isArray(_serverLogs) && _serverLogs.length > 0) {
          const { log: _serverLog } = chooseEditableLog(_serverLogs);
          const _serverId = _serverLog && (_serverLog.id || _serverLog._id);
          if (_serverId) {
            // Adopted even when the draft already names one: they are the same
            // day's row, and the server is the authority on which document is
            // current after an amendment.
            setExistingLogId(_serverId);
            // Bound so the NEXT open does not have to ask again — and so a save
            // from this device PUTs to the row that exists instead of POSTing a
            // create that upserts over it (api.js:949).
            setDraftBackendId(_key, String(_serverId)).catch(() => {});
            servedCoordsRef.current = servedPhotoCoords(_serverLog.data?.activities);
          }
        }
        if (_roster) {
          rosterIdsRef.current = rosterIdIndex(_headcount);
          const _fresh = buildCrewsFromRoster(_roster.workers || [], _headcount);
          _resolved = reconcileCrewsWithRoster(_storedCrews, _fresh);
          if (_resolved.length > 0) setActivities(withActivityIds(_resolved));
        }
        loadChips(_resolved);
        loadProjectShell();
        setLoading(false);
        return;
        }
      }

      const [projectData, roster, headcount, existingLogsRes] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsRoster(projectId, date).catch(() => null),
        logbooksAPI.getDailyHeadcount(projectId, date).catch(() => []),
        // A LOG READ THAT FAILED IS NOT A DAY WITH NO LOG — the same
        // distinction the roster read below already draws, and it was missing
        // here. `.catch(() => [])` handed an empty array to everything
        // downstream, so `existing` came out null, `locked` stayed false, and
        // the screen rendered an EDITABLE EMPTY FORM for a day that may
        // already be filed. That is what a second device showed the operator
        // on 2026-08-28, one tap away from writing it over the record.
        settleFetch(() => logbooksAPI.getByProject(projectId, 'daily_jobsite', date)),
      ]);

      // FAIL CLOSED. Nothing below this line may run on a read that did not
      // come back: hydrate would not fire, buildCrewsFromRoster would fill the
      // form from the gate roster, and the CP would be looking at a blank day
      // that says nothing about whether one was filed.
      if (existingLogsRes.status !== 'ok') {
        setLogReadFailed(existingLogsRes.status);
        setLogReadError(existingLogsRes.error);
        setLocked(true);
        return;
      }
      const existingLogs = Array.isArray(existingLogsRes.data)
        ? existingLogsRes.data : [];

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
        // A COLLAPSE IS NOT A FAILURE TO CONFIRM — device round 4, finding 12.
        //
        // The server returns ONE boolean: `partial` is
        // `bool(_degraded or _truncated or _collapsed)`. But a collapse is the
        // opposite of a degradation — the server DID read the roster and merged
        // two rows it could not tell apart. Gating the "could not confirm the
        // full list" banner on it told the CP the read had failed on a day
        // nothing failed and nobody was dropped.
        //
        // FORWARD-COMPATIBILITY IS PRESERVED, which is the point of the
        // server's single boolean: anything that sets `partial` still raises
        // the banner UNLESS the only reason given is a collapse. A degradation
        // mode added server-side with no client change still warns.
        const degraded = (roster.degraded_passes || []).length > 0;
        const truncated = (roster.truncated_passes || []).length > 0;
        const collapsed = roster.collapsed || 0;
        const onlyCollapse = Boolean(roster.partial)
          && collapsed > 0 && !degraded && !truncated;
        setRosterPartial(Boolean(roster.partial) && !onlyCollapse);
        setRosterCollapsed(collapsed);
      }

      // Prefer the EDITABLE (non-locked) doc — an amendment child — over a
      // locked original that shares (project, type, date).
      let builtCrews = [];
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const { log: existing, readOnly } = chooseEditableLog(arr);
      if (readOnly) { setLocked(true); markFinalized(_key); }
      // THE SERVER'S DOCUMENT, kept whether or not it is read-only. When it
      // IS read-only this is what LogbookStepper hands FiledLogView, so the
      // filed record renders from what the server holds rather than from the
      // roster-reconciled local list.
      setFiledLog(existing || null);

      if (existing) {
        setExistingLogId(existing.id || existing._id);
        // AND THE DRAFT LEARNS IT. Without this the id is known only for the
        // life of this mount: the autosave 800ms from now writes a draft with
        // backend_id null, and the next open takes the draft branch above with
        // no server id — which is what blanked every photo the CP did not take.
        setDraftBackendId(_key, String(existing.id || existing._id)).catch(() => {});
        // The photo url is addressed by position in THIS document, and the
        // reconcile below is about to move rows relative to it.
        servedCoordsRef.current = servedPhotoCoords(existing.data?.activities);
        // AND THE REFUSAL COMES DOWN. A create the drain gave up on records
        // its refusal against the DRAFT KEY, because there was no logbook id
        // to hang it on. Finding the day on the server is the proof that the
        // banner has nothing left to say: it is filed, the CP is looking at
        // it, and the id it lacked is right here. Cleared on the LOAD rather
        // than on a push, because after the create path started refusing these
        // there may never be another successful push on this key.
        clearFinalizeError(_key).catch(() => {});
        hydrate(existing.data || {});
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
        // `is_amendment !== true` is not an amendment. A truthy-but-not-true
        // value is a shape nobody wrote deliberately and must not be read as a
        // correction on a compliance record.
        setAmendment(existing.is_amendment === true ? {
          reason: (existing.amendment_reason || '').trim() || null,
          by: (existing.created_by_name || '').trim() || null,
          at: String(existing.created_at || '').slice(0, 10) || null,
          has_reason: !!(existing.amendment_reason || '').trim(),
        } : null);
        // THE SAME TRAP, ONE LAYER OUT. Crews were built only in the `else` —
        // so a SERVER log saved with an empty roster never rebuilt either, and
        // a draft pushed before anyone checked in is exactly that log. A filed
        // log is left alone: its roster is part of the record.
        // A FILED LOG IS STILL LEFT ALONE — its roster is part of the record,
        // and that rule is why `is_locked` gates everything below.
        //
        // An unlocked one is now RECONCILED rather than only rebuilt-if-empty,
        // for the reason given on the draft path: a server-saved draft that
        // already held one crew could never learn about the next one to arrive.
        if (!existing.is_locked) {
          const _stored = Array.isArray(existing.data?.activities)
            ? existing.data.activities : [];
          const _fresh = buildCrewsFromRoster(roster?.workers || [], headcount);
          // No roster read (offline / failed) means no opinion: keep what was
          // filed rather than reconciling against an empty list and zeroing
          // every crew on the log.
          builtCrews = roster
            ? reconcileCrewsWithRoster(_stored, _fresh)
            : _stored;
          if (builtCrews.length > 0) setActivities(withActivityIds(builtCrews));
        }
      } else {
        builtCrews = buildCrewsFromRoster(roster?.workers || [], headcount);
        setActivities(builtCrews);
        // Weather and address are OBSERVED FACTS about the day, not asserted
        // work, so auto-filling them states nothing the CP did not witness.
        // This is why they stay auto-populated while work_description does not.
        fetchWeather(fullAddress);
      }
      // builtCrews IS the reconciled list on the `existing` path now, so the
      // old "stored, else built" concat is gone — it would have fetched chips
      // for the pre-reconciliation trades and missed any crew just added.
      loadChips(builtCrews.length > 0
        ? builtCrews
        : ((existing?.data || {}).activities || []));
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
  // FOUR SLOTS, COMPOSED — the composition lives in dailyJobsiteModel so it can
  // be EXECUTED rather than grepped. Inlining ~80 chips was the defect.
  //
  // THE ALWAYS-AVAILABLE BAND IS GONE. It put twelve chips on every crew card
  // regardless of trade, so an HVAC crew was offered "scaffold dismantle" and
  // "site clean-up" — another sub's work. A crew card offers that crew's trade
  // work and nothing else now: the ranker stopped special-casing those ids and
  // they reach the crews whose taxonomy holds them, so the four slots are the
  // only thing that ever competed for.
  const chipBandsFor = (a) => {
    const meta = chipsMetaByTrade[String(a?.trade || '').trim()];
    return composeChipBands({
      chips: chipsFor(a),
      allChips: chipsByTrade[''],
      resolvedTrades: meta?.resolved_trades,
      priorDate: meta?.prior_date,
    });
  };

  const hydrate = (d) => {
    if (d.project_address) setProjectAddress(d.project_address);
    if (d.weather) setWeather(d.weather);
    if (d.weather_temp) setWeatherTemp(d.weather_temp);
    if (d.weather_wind) setWeatherWind(d.weather_wind);
    if (d.weather_fetch_state) setWeatherFetchState(d.weather_fetch_state);
    if (d.general_description) setGeneralDescription(d.general_description);
    if (d.activities?.length) setActivities(withActivityIds(d.activities));
    if (d.equipment_on_site) setEquipmentOnSite(d.equipment_on_site);
    if (d.checklist_items) setChecklistItems(d.checklist_items);
    if (d.observations) setObservations(d.observations);
    if (d.visitors_deliveries) setVisitorsDeliveries(d.visitors_deliveries);
    // NO time_in / time_out HYDRATION. There is no state to hydrate into, and
    // reading a key nothing writes back is how a deleted state block leaves a
    // live call site behind.
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

  /**
   * The CP correcting how many men a crew had on site.
   *
   * WHY THIS IS NOT updateActivity(i, 'num_workers', v). One keystroke has to
   * move THREE fields together -- the printed count, who supplied it, and (when
   * he clears the box) a revert to the gate's own number. Writing them one at a
   * time through the generic setter would leave a row that says 'cp' with the
   * gate's count on it, or the reverse, both of which print.
   *
   * The rule lives in applyHeadcountEdit so the reconcile and the renderer read
   * the same definition of an override rather than three of them.
   */
  const updateCrewHeadcount = (index, raw) => {
    setActivities((prev) => prev.map((a, i) => (
      i === index ? { ...a, ...applyHeadcountEdit(a, raw) } : a
    )));
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

  /**
   * The steps he has WALKED PAST and left unfinished.
   *
   * stepComplete has been a tested pure function called by nothing: its own
   * docstring claimed it drove the progress marks, and the marks were purely
   * positional (`n <= step`). So a crew with no work described first appeared
   * as "— Nothing yet" on the review, with nothing before it.
   *
   * `n < step`, not `n <= step`: the step he is standing on is work in
   * progress, not an omission.
   */
  const stepsLeftIncomplete = useMemo(() => {
    const state = { activities, observations, checklistItems, cpSignature };
    return [1, 2, 3, 4, 5].filter((n) => n < step && !stepComplete(n, state));
  }, [step, activities, observations, checklistItems, cpSignature]);

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

  /**
   * REMOVING A CREW CARD.
   *
   * Two steps on purpose. The confirm states a CONSEQUENCE the CP cannot see
   * from the card in front of him -- deleting the described half of a duplicate
   * leaves the other half holding men with no work recorded, which re-disables
   * Next -- so the impact is computed from the whole list before anything is
   * asked, and the sentence is built from it.
   */
  const requestDeleteCrew = (index) => {
    const impact = crewDeleteImpact(activities, index);
    if (!impact || !impact.deletable) return;
    setDeletingCrew({ index, impact, name: crewName(activities[index]) });
  };

  const confirmDeleteCrew = () => {
    const target = deletingCrew;
    setDeletingCrew(null);
    if (!target) return;
    setActivities((prev) => {
      // RE-CHECKED AGAINST THE LIST AS IT IS NOW, not as it was when the dialog
      // opened. A reconcile can land between the tap and the confirm, and
      // removing by a stale index would take a different crew than the one
      // named in the sentence he agreed to.
      const row = prev[target.index];
      if (!row || !isDeletableCrew(row)) return prev;
      if (crewName(row) !== target.name) return prev;
      return prev.filter((_, i) => i !== target.index);
    });
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
      // AN UNTYPED COUNT IS UNKNOWN, NOT ZERO. This was
      // `String(parseInt(c.num, 10) || 0)`, so leaving the count blank wrote
      // the literal string "0" onto the row — the app asserting, on a record
      // the CP signs, that a crew he had just told it was on site had nobody
      // in it. That manufactured zero is one of the two ways the reported
      // 0-worker crew appears (the other is roster reconciliation, which is
      // entitled to write a real zero because it has actually looked).
      //
      // Blank now stays blank, which hasNoWorkersOnSite reads as "nobody
      // counted" rather than "nobody here", so the crew keeps being asked for
      // its work — he added it precisely because it WAS on site.
      num_workers: Number.isFinite(parseInt(c.num, 10))
        ? String(parseInt(c.num, 10))
        : '',
      // A TYPED COUNT IS THE CP'S, A BLANK ONE IS NOBODY'S. Marking a blank
      // 'cp' would put "(CP)" on the filed record against a number he never
      // supplied; the blank means nobody counted, and that is not an assertion
      // he made.
      num_workers_source: Number.isFinite(parseInt(c.num, 10)) ? CP_SOURCE : undefined,
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
      const key = await uploadCapturePhoto({ projectId, logbookId: existingLogId, activityId, photoId: id, uri: localUri });
      setActivities((prev) => patchPhoto(prev, id, { original_r2_key: key, upload_pending: false }));
    } catch (_e) {
      // DEFERRED, NOT LOST. The file is in documentDirectory and its uri is in
      // the draft, so it survives an app kill; the row keeps `upload_pending`,
      // so every reader falls back to that local file; and the save and the
      // reconnect drain both retry it.
      setActivities((prev) => patchPhoto(prev, id, { upload_pending: true }));
    }
    // `existingLogId` IS IN THE DEPS, and it has to be. It arrives partway
    // through a session — null until the first push lands — so a callback that
    // closed over the null forever would keep telling the capture route it has
    // no log to check, on a screen that does. It cannot cause a re-upload:
    // uploadAttemptedRef holds one attempt per photo per session and the
    // effect below reads it before calling this.
  }, [projectId, existingLogId, toast, t]);

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
    const tIn = Date.now();
    if (cameraTargetIndex == null || !uri) return;
    const target = cameraTargetIndex;
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

  // WHICH COPY TO SHOW, DECIDED BY WHETHER THE PHOTO IS UPLOADED.
  //
  // The old chain was unconditional and put the device-local `uri` first. For
  // a photo taken on ANOTHER phone -- or on this one before the app's data was
  // cleared -- that path is dead, and because a dead path is still a non-empty
  // string the `||` chain never advanced to a copy that would have worked. The
  // served URL sat last and was never reached. Meanwhile `base64` is never
  // written for an uploaded photo (it would blow the 16MB document ceiling)
  // and `thumb_base64` is only written by the finalize purge, so on an
  // unfinalized log the served URL is the ONLY copy any other device can read.
  //
  // REORDERING UNCONDITIONALLY WOULD JUST MOVE THE FAULT. A CP offline with an
  // already-uploaded photo would then get a URL that cannot load, in front of
  // a file sitting on his own phone -- same bug, different victim. So the
  // preference is conditional, and `onError` below makes it a PREFERENCE
  // rather than a commitment: the `||` chain cannot detect a failed LOAD, only
  // a falsy value, which is the whole reason this defect existed.
  const [tileRetry, setTileRetry] = useState({});

  // WHAT THE SERVER'S COPY OF THIS LOG LOOKS LIKE, for the one purpose of
  // addressing a photo in it. Rebuilt every time this screen learns that —
  // both load paths, and after a successful push, which is when the server's
  // order becomes this list's order. A ref, not state: every write is
  // immediately followed by a setActivities that drives the render.
  const servedCoordsRef = useRef(new Map());

  // The (ai, pi) the url must carry. A photo this map cannot place keeps the
  // LIVE position — that is what it had before, and it is the honest answer
  // for a photo the server has never seen: it is only on this device.
  const servedIndex = (photo, ai, pi) => (
    servedCoordsRef.current.get(photoServeKey(photo)) || [ai, pi]
  );

  // WHY THIS LOG IS A DIFFERENT SHAPE THAN HE LEFT IT.
  //
  // The load kept `id`, `data`, `cp_signature` and `cp_name` and DISCARDED
  // is_amendment / amendment_reason / created_by_name / created_at -- so the
  // editor held a corrected document and had no idea it was one. Retained
  // here and handed to the stepper, which renders the banner above the form.
  //
  // Off the RECORD, so it reads the same in December as on the morning after.
  const [amendment, setAmendment] = useState(null);

  // `retried` IS A PARAMETER, NOT CLOSURE STATE, and the body is a single
  // expression. Both are load-bearing: photoPurgeConsumers.test.cjs and
  // logbookPhotoR2.test.cjs slice this declaration out of the file with the
  // terminator "\n  );\n" and eval it with only (logbooksAPI, existingLogId)
  // in scope, then call it. A block body or a reference to component state
  // makes this function untestable by the two suites that own its behaviour.
  //
  // THE CONDITION READS: prefer the served copy when the photo is uploaded,
  // prefer the local copy when it is not, and swap that preference once a
  // tile has reported a failed load.
  //
  //   uploaded + first try  -> served first   (the local path is meaningless
  //                                            on any device but the capturer)
  //   uploaded + retried    -> local first    (offline, with the file to hand)
  //   pending  + first try  -> local first    (mid-capture; nothing uploaded)
  //   pending  + retried    -> served first
  const photoTileUri = (photo, ai, pi, retried) => (
    (photo?.original_r2_key ? !retried : !!retried)
      ? ((existingLogId
        ? logbooksAPI.getLogbookPhotoUrl(existingLogId, ai, pi, 'thumb', photo?.enhance_status || '')
        : null)
        || photo?.uri
        || inlinePhotoData(photo?.base64)
        || inlinePhotoData(photo?.thumb_base64)
        || undefined)
      : (photo?.uri
        || inlinePhotoData(photo?.base64)
        || inlinePhotoData(photo?.thumb_base64)
        || (existingLogId
          ? logbooksAPI.getLogbookPhotoUrl(existingLogId, ai, pi, 'thumb', photo?.enhance_status || '')
          : null)
        || undefined)
  );

  const openPhotoLightbox = (photo, uiAi, uiPi) => {
    if (!photo || photo.pending) return;
    // Same correction as the tile: the full-size view is served by POSITION in
    // the server's document, so it must be given the server's position.
    const [ai, pi] = servedIndex(photo, uiAi, uiPi);
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
    // Let any background compression finish FIRST. A save fired immediately
    // after a capture would otherwise persist and upload the RAW sensor JPEG
    // the pending entry still points at. allSettled, not all: a failed
    // compress must not block the save.
    if (pendingCompressRef.current.length > 0) {
      await Promise.allSettled(pendingCompressRef.current);
    }
    const rows = activitiesRef.current?.length ? activitiesRef.current : activities;
    const persisted = await persistActivityPhotos(rows);
    // THE LOCAL SAVE IS THE OFFLINE RECORD, so its result is not discardable.
    // writeDraft answers with a BOOLEAN and this call used to drop it on the
    // floor; the try below covers a throw, because a caller that handles one
    // failure mode and not the other has fixed half of this. This log carries the day's photos, which makes a quota
    // failure here the likeliest one in the app — and the deferred branches
    // below would still queue the key and report the day as filed, leaving the
    // drain to read a stale autosave or find nothing at all.
    let localSaved = false;
    try {
      localSaved = await writeDraft(_key, {
        data: draftBody(persisted), cp_signature: cpSignature, cp_name: cpName,
        status: submitStatus,
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

    // persistActivityPhotos no longer fails silently.
    const lost = persisted.reduce(
      (n, a) => n + ((a.photos || []).filter((p) => p.persist_failed).length), 0,
    );
    if (lost > 0) toast.error(t('photoNotSavedTitle'), t('photoNotSavedBody'));

    // Most photos are already in R2 — uploaded as they were taken. This
    // catches the stragglers. Bounded: uploadPendingActivityPhotos abandons
    // the loop on the first offline failure or 5xx rather than making the CP
    // wait out a hundred identical timeouts.
    const _uploaded = await uploadPendingActivityPhotos(projectId, persisted, existingLogId);
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
      // THE SERVER NOW HOLDS THIS ORDER. Both writes above $set the whole
      // activities array from payloadActivities, so the coordinates the tiles
      // address are that array's — and photoForPayload's .filter(Boolean) can
      // drop a row, which moves every photo after it.
      servedCoordsRef.current = servedPhotoCoords(payloadActivities);
      await setDraftBackendId(_key, savedId);
      await clearPending(_key);
      // A PUSH THAT LANDED CLEARS A REFUSAL ON RECORD. The banner LogbookLockBar
      // renders is durable by design — it has to survive the CP walking away —
      // so nothing but a successful push may take it down. This used to sit
      // beside the /finalize call; the refusal it clears is now recorded by the
      // push, so the clearing moves with it.
      // BOTH HANDLES. A banner raised while offline was recorded against
      // the DRAFT KEY, because there was no server id yet — clearing only
      // by savedId left it up permanently.
      await clearFinalizeError(_key);
      if (savedId) await clearFinalizeError(savedId);
    } catch (pushErr) {
      // ── REFUSAL IS NOT OFFLINE ──────────────────────────────────────────
      //
      // THIS BLOCK USED TO BE THREE LINES: markPending and a warning, whatever
      // had gone wrong. Every outcome — no network, a 4xx judgement, a 5xx
      // failure — became "queued, will sync on reconnect", and the CP was told
      // nothing at all.
      //
      // It survived because the REAL refusal handling lived in the /finalize
      // call that followed, and end-of-day sign-once removed that call. Taking
      // the finalize out without moving its split here would have left the
      // app's most-filed log with no refusal handling of any kind: a submit
      // the server judged and rejected would queue forever, silently, and his
      // own device would say it was filed.
      //
      // Modelled on ssc_daily_safety_log, which has carried this split since it
      // was ported and is why removing ITS finalize needed nothing else. Three
      // outcomes, and only one of them may promise a sync:
      //
      //   4xx  the server JUDGED the log. It will keep saying no until the log
      //        changes, so the CP is told now, on the screen that can fix it,
      //        and the refusal is RECORDED so the durable banner survives him
      //        walking away. Nothing is queued — a retry would be refused
      //        identically.
      //   5xx  the server FAILED rather than judged. Retryable, queued, and it
      //        must not be announced as filed.
      //   none no response at all. Genuinely offline: queued, and the promise
      //        that it syncs is true.
      const offline = isOfflineError(pushErr);
      const status = pushErr?.response?.status;
      const refused = typeof status === 'number' && status >= 400 && status < 500;
      // KEYED ON THE 4xx, NOT ON THE SUBMIT STATUS. A refusal of a DRAFT
      // save used to match neither this branch nor the 5xx branch below, so it
      // fell through to markPending: the drain would re-send a write the server
      // had already judged, on every reconnect, forever, under a banner
      // promising it would sync. That path is now reachable — create_logbook
      // refuses a data write onto a filed row (409 FILED_LOG_DATA_IMMUTABLE),
      // and a second device saving a DRAFT over a filed day takes it.
      //
      // A 4xx is a judgement the server will keep making whatever the status
      // on the request was. Recording it and showing its copy is right for all
      // of them; queueing it for retry is right for none.
      if (refused) {
        const code = finalizeErrorCode(pushErr);
        console.warn('daily_jobsite REFUSED by the server:', status, code);
        // STALE, AND CORRECTED. This said a 409 for a SUBMITTED row had been
        // "built and withdrawn: the LOCK is the line and signed is not, so an
        // end-of-day log stays writable through the day". That stopped being
        // true: a0d5e6e added exactly that 409, because an end-of-day log
        // being writable after Submit is what let two filed daily_jobsite
        // records at 588 Thomas be overwritten by the CP simply OPENING them.
        //
        // So a filed row can now be refused two ways, and neither needs a
        // special case here:
        //   423  FINALIZED, locked — the lock bar offers an amendment
        //   409  FILED_LOG_DATA_IMMUTABLE, submitted but not yet frozen — the
        //        same remedy, and gateCopy renders the code
        // Both land in the generic refusal path below, which records the code
        // and shows its copy.
        await recordFinalizeError(existingLogId || _key, code, _key, 'editor');
        toast.error(tFinalize('errorTitle'), gateCopy(code));
        return undefined;
      }
      if (!offline && !refused) {
        console.warn('daily_jobsite push FAILED server-side:', status || pushErr?.message);
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
      // SUCCESS, on the strength of a local draft the drain will send later.
      // With no such draft there is no record anywhere, so the key is not
      // queued and nothing is announced.
      if (!localSaved) {
        console.warn('daily_jobsite push deferred but the LOCAL SAVE FAILED; not queued.');
        await recordFinalizeError(
          existingLogId || _key, 'LOCAL_SAVE_FAILED', _key, 'local');
        toast.error(tFinalize('localSaveFailedTitle'), tFinalize('localSaveFailed'));
        return undefined;
      }
      await markPending(_key);
      console.warn('daily_jobsite push deferred (will sync on reconnect):', pushErr?.message);
      // ON THIS DEVICE ONLY — the other half of the same banner. The local
      // write landed, so this log IS safe here and IS queued; what is not true
      // is that anyone else can see it. He is about to attest to a legal
      // record, and a toast saying "will sync" is gone before he has
      // finished reading it, so this goes up durably and comes down when the
      // drain succeeds (clearUnsyncedBanner in draftSync).
      await recordFinalizeError(
        existingLogId || _key, 'NOT_ON_SERVER', _key, 'unsynced');
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
        // ── AWAITED, BECAUSE THIS ROW AND THE SERVER'S RACE FOR THE SAME SLOT
        //
        // The server now DERIVES a ledger row from the document at /finalize,
        // so an offline signature is no longer lost — but the derived row
        // cannot record the signing device or the signing IP, because at
        // derivation time the only ones available belong to whatever had
        // signal later. This POST can, and it is the ONLY writer that can.
        //
        // handleSubmitAndSign calls /finalize a few lines after this returns.
        // Fired and forgotten, the two are in flight together and the server's
        // derivation can win — no duplicate (both writers key on the same
        // signing act) but the genuine device and IP are then never recorded
        // for a CP who was online the whole time. Awaiting orders them.
        //
        // NON-BLOCKING IS UNCHANGED: recordSignatureEvent catches its own
        // error and resolves with null, so it has never rejected and awaiting
        // it cannot refuse the log. Same change, same reasoning, as the
        // awaited call in site_superintendent_log.jsx.
        const _evtId = await recordSignatureEvent({
          documentType: 'logbook', documentId: docId, eventType: 'cp_sign',
          signerName: cpName, signerRole: user?.role || 'cp', signatureData: cpSignature,
          contentSnapshot: {
            log_type: 'daily_jobsite', date, project_id: projectId, data,
            status: submitStatus,
          },
          user,
        });
        if (!_evtId) {
          // Not a failure of the filing, and never surfaced to the CP: the
          // server derives a row at /finalize and the night sweep asks again.
          // This says the DEVICE-accurate row is the one that was lost.
          console.error(
            '[signature-ledger] no contemporaneous row for this signature; '
            + 'the server will derive one without the signing device or IP.',
            { documentId: docId, projectId, date, logType: 'daily_jobsite' },
          );
        }
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
    // AFFIRMED, NOT MERELY PRESENT — round 6, finding 15.
    //
    // This asked `!cpSignature`, and production held `cp_signature: {}`: an
    // empty object, truthy, so a CP with a cached profile credential filed the
    // day's headline log and every section of it printed "UNAFFIRMED —
    // inherited signature, not affirmed for this document". He passed the gate
    // and the document said he had not.
    //
    // The affirmation gate shipped for the NINE immediate types, whose test
    // iterates LOGBOOK_TIMING_CLASS's `immediate` entries. daily_jobsite is
    // END_OF_DAY, so it was never in that loop; ssc_daily_safety_log picked the
    // gate up when it was ported, and this form — the most-filed log in the app
    // and the one that leads the report — was the one left behind.
    if (!isAffirmedSignature(cpSignature)) {
      const hint = affirmationHintKey(cpSignature, profileLoaded);
      toast.warning(
        t('signatureRequiredTitle'),
        hint ? tFinalize(hint) : t('signatureRequiredBody'),
      );
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
    // A CREW ON SITE THAT DID NOTHING RECORDABLE IS A CREW NOBODY DESCRIBED.
    //
    // stepComplete(2) has held this rule the whole time and only MARKED with
    // it. So a filed §3301.2 daily log could name four subcontractors on site
    // and say what none of them did, and the only trace was a pip the CP had
    // already walked past. The document that goes to the DOB, the investor and
    // the lender is the one where that gap shows.
    //
    // Same shape as the two gates above: back to the step that holds it, and
    // name WHICH crews rather than refusing at the signature with no route to
    // a fix. Blocking at submit, never on Next — a crew whose work is not done
    // yet is ordinary at 9am.
    // THE SAME BACKSTOP FOR THE DESCRIPTION. The sign control is disabled while
    // it is empty, so reaching here means the state moved under the press.
    if (String(generalDescription || '').trim() === '') {
      setStep(TOTAL_STEPS);
      toast.warning(t('descriptionRequiredTitle'), t('descriptionRequiredHint'));
      return;
    }
    // THE BACKSTOP. Next is disabled on step 2 until every crew is complete
    // (see nextDisabled below), so reaching here means the state moved under
    // the press — a roster refresh adding a crew while he was on step 5. The
    // check stands rather than filing a log that names a crew and says nothing
    // about it.
    const bareCrews = crewsWithoutWork(activitiesRef.current || activities);
    if (bareCrews.length > 0) {
      setStep(2);
      toast.warning(t('crewWorkMissingTitle'), crewGapSentence(bareCrews));
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
      // `undefined` (not null) = the save itself failed and has already been
      // reported. Nothing may be frozen, recorded or announced on a log that
      // was never written. `null` is different: it saved LOCALLY but has no
      // server id yet, which is the offline path and does freeze below.
      if (savedId === undefined) return;
      // ── SIGN ONCE, FREEZE AT END OF DAY ───────────────────────────────
      //
      // THE SIGNATURE IS NOT THE FREEZE ON THIS LOG. daily_jobsite is
      // END_OF_DAY: the daily narrative, open and accumulating all day. That
      // is what LOGBOOK_TIMING_CLASS says, what logbookTiming.js says, and
      // what /logbook-types serves to clients as `freeze_on_finalize`.
      //
      // It was true nowhere. This block called /finalize the instant he
      // signed, so a log signed at 9am froze at 9am and the photos, injuries
      // and deliveries of the rest of the day had nowhere to go except an
      // amendment. Three descriptions of a property no code produced.
      //
      // He signs once. The record stays editable. sweep_stale_end_of_day_logs
      // freezes it at 3am ET once the day is over — signed and stale, and only
      // then. An UNSIGNED stale log is flagged instead of sealed: a CP who
      // signed and left is a different fact from one who never signed, and
      // sealing the second would close a record nobody attested to.
      //
      // NOTHING IS MARKED FINALIZED HERE, locally or on the server. The old
      // three-way finalize split (offline / refused / failed) went with the
      // call it was written for; the refusal it handled cannot occur, because
      // no finalize is attempted. The submit push above keeps its own split.
      toast.success(t('submittedTitle'), t('signedStaysOpen'));
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


  const crewName = (a) => (String(a.company || '').trim() || t('noCrewWorker'));

  /**
   * WHICH CREW, AND WHAT IT IS MISSING.
   *
   * "Crew 3 of 5 has no activity" tells him where to go. A bare count makes him
   * hunt down the list comparing what he sees against a number, on a phone, in
   * gloves. The company name comes too when the row has one — the position is
   * how he finds the card, the name is how he knows it is the right one.
   *
   * ONE SENTENCE, TWO SURFACES: the disabled-Next hint and the submit backstop
   * read the same function, so the two can never describe the same gap
   * differently.
   */
  const crewGapSentence = useCallback((gaps) => gaps.map((c) => {
    const where = t('crewNofM')
      .replace('{n}', String(c.row)).replace('{m}', String(c.total));
    const who = c.crew ? ` (${c.crew})` : '';
    const what = c.missing.map((k) => t(`crewMissing_${k}`)).join(t('crewMissingJoin'));
    return `${where}${who} ${what}`;
  }).join('; '), [t]);

  // Present on site, not a unit of work. Counted so Step 2 can say why there
  // is no card for him rather than simply omitting him without explanation.
  const unassignedWorkerCount = activities.filter(isUnassignedWorkerRow).length;

  // The crews step 2 is still waiting on. One computation, read by the Next
  // gate and by its hint.
  // #167, UNCONDITIONAL AGAIN. This was relaxed on a no-work day, because a
  // washout had nothing to describe and the gate would have blocked the CP from
  // filing the exact day the log existed to record. The day state is gone — a
  // rain or shutdown day has nobody on site to open the app, so the absence of a
  // log for that date IS the record — so the relaxation has no trigger and the
  // gate goes back to what #167 specified: every crew names its work and where.
  const crewGaps = useMemo(
    () => crewsWithoutWork(activities), [activities],
  );

  /**
   * THE DAY'S DESCRIPTION, EMPTY AT THE MOMENT OF SIGNING.
   *
   * The report printed "Description: — Not recorded" on filed logs, and nothing
   * was losing the field: the payload carries it, both renderers read the right
   * key, and there is a control plus an auto-draft.
   *
   * It was empty because the draft only lands once he REACHES the review step:
   *
   *     if (descriptionTouched) return;
   *     if (step !== TOTAL_STEPS) return;   // only once he is looking at it
   *
   * That rule is correct and stays. He is attesting to that sentence, so the
   * app may propose it and may not put words he never read into the record —
   * drafting sooner would file a sentence nobody had seen, which is worse than
   * a blank.
   *
   * So the fix is not drafting sooner; it is that he cannot SIGN while it is
   * empty. A log filed with "— Not recorded" in the description is a log where
   * the CP never looked at the review step, and the sign control is the last
   * place that can be true and still fixable.
   *
   * It also catches the case the auto-draft cannot: once he has edited the
   * field, `descriptionTouched` is set and the draft never re-lands, so a CP
   * who types and then clears it leaves it empty for good.
   */
  const descriptionEmpty = String(generalDescription || '').trim() === '';

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

      {/* THE READ FAILED. "May be incomplete" is a statement about the
          SERVER, not about the roster, and it must only appear when the
          server could genuinely not confirm the list. */}
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

      {/* TWO ROWS WERE MERGED. A different fact and a different sentence: the
          server read the roster fine and could not tell two men apart. It is
          worth telling the CP — the headcount may be one short — but it is not
          a failed read, and dressing it as one taught him to ignore the
          banner that means the read actually failed. */}
      {!rosterPartial && rosterCollapsed > 0 && (
        <Card s={s} style={s.cardWarn}>
          <AlertTriangle size={20} strokeWidth={2} color={outdoor.warn} />
          <View style={s.warnBody}>
            <Text style={s.warnTitle}>{t('rosterCollapsedTitle')}</Text>
            <Text style={s.warnText}>{t('rosterCollapsedBody')}</Text>
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
            {!flagged && hasNoWorkersOnSite(a) && (
              <Text style={s.crewRowFlag} numberOfLines={2}>{t('emptyCrewHint')}</Text>
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
        const { primary, rest, basis } = chipBandsFor(a);
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
            {/* WHY THIS CARD IS NOT BEING ASKED. crewsWithoutWork skips it, so
                without this the CP sees Next enabled while one card sits empty
                and nothing on screen accounts for the difference. */}
            {hasNoWorkersOnSite(a) && (
              <Text style={s.crewRowFlag}>{t('emptyCrewHint')}</Text>
            )}

            {/* THE CORRECTION. #244 gave the CP a card that explains why it is
                not being asked for work; this is the first release in which he
                can do something about it.
                Editable on a gate row AND a hand-added one: the gate misses men
                (a failed tag, a wrong project) and a hand-added crew can be
                left with no count at all, and both are a headcount he is the
                only one able to fix.
                Correcting 0 to 4 immediately puts this crew back into
                describableRows, so the log starts asking it for an activity and
                a location and Next goes back to disabled. That is the point,
                not a side effect. */}
            <View style={s.headcountRow}>
              <Text style={s.headcountLabel}>{t('headcountLabel')}</Text>
              <TextInput
                style={s.headcountInput}
                value={String(a.num_workers ?? '')}
                onChangeText={(v) => updateCrewHeadcount(i, v)}
                keyboardType="number-pad"
                editable={!locked}
                maxLength={4}
                accessibilityLabel={`${t('headcountLabel')} — ${crewName(a)}`}
                placeholder={t('headcountPlaceholder')}
                placeholderTextColor={outdoor.textSoft}
              />
              {/* WHAT THE TURNSTILE SAID, KEPT VISIBLE WHILE HE OVERRIDES IT.
                  He is editing a 3301.2 record; the number he is standing over
                  should not vanish from the screen the moment he types. */}
              {isHeadcountOverridden(a) && gateHeadcount(a) !== null && (
                <Text style={s.headcountGate}>
                  {t('headcountGateWas').replace('{n}', String(gateHeadcount(a)))}
                </Text>
              )}
            </View>

            {/* REMOVING THE CARD. #244's reconcile deliberately appends a
                second row when the CP hand-added a company the gate later
                reports, and justified it as "visible on the screen and
                correctable". This is what makes correctable true.
                A gate card says WHY it has no Remove rather than simply not
                showing one -- an absent control reads as a bug, and the CP
                would go looking for it. */}
            {!locked && (isDeletableCrew(a) ? (
              <Pressable
                onPress={() => requestDeleteCrew(i)}
                accessibilityRole="button"
                accessibilityLabel={`${t('deleteCrew')} — ${crewName(a)}`}
                style={({ pressed }) => [s.deleteCrewBtn, pressed && s.deleteCrewBtnPressed]}
              >
                <Trash2 size={16} strokeWidth={1.5} color={outdoor.danger} />
                <Text style={s.deleteCrewText}>{t('deleteCrew')}</Text>
              </Pressable>
            ) : (
              <Text style={s.deleteCrewRefused}>{t('deleteCrewRefused')}</Text>
            ))}

            <>
              {/* ACTIVITY. Ranked, never pre-selected. */}
              <Text style={s.question}>{t('activityQuestion')}</Text>
              {/* WHAT THESE FOUR ARE RANKED BY, said plainly. A trade whose
                  activities carry no edges in the sequence graph gets no
                  sequenced chips at all, and presenting its catalogue as though
                  yesterday informed it would claim a ranking that does not
                  exist. */}
              {basis === 'trade' && (
                <Text style={s.chipBasisNote}>{t('chipsFromTrade')}</Text>
              )}
              <View style={s.chipWrap}>
                {primary.map((c) => (
                  <Chip
                    key={c.id} label={c.label}
                    selected={(a.activity_ids || []).includes(c.id)}
                    onPress={() => toggleActivityChip(i, c.id)}
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
            </>

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
                            <Image
                              // servedIndex, NOT (i, pi): the url addresses the
                              // SERVER's activities array and this list has
                              // been reconciled since that document was
                              // written. tileKey stays on the live position —
                              // it identifies a TILE, not a stored photo.
                              source={{ uri: photoTileUri(photo, ...servedIndex(photo, i, pi), tileRetry[tileKey(photo, i, pi)]) }}
                              // The preferred copy did not load. Flip THIS tile
                              // to the other one rather than showing a blank
                              // square: offline with an uploaded photo falls
                              // back to the local file, and a missing local
                              // file falls forward to the served URL.
                              onError={() => setTileRetry((prev) => {
                                const k = tileKey(photo, i, pi);
                                return prev[k] ? prev : { ...prev, [k]: true };
                              })}
                              style={s.photoImage}
                            />
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

            {/* "OTHER" NAMES NOTHING, so pass/fail says nothing about
                anything — a green "Passed: Other" on a filed 3301-02 is a
                claim with no subject. The CP writes what he inspected. */}
            {isOtherInspection(it.key) ? (
              <TextInput
                style={s.input}
                value={row.note}
                onChangeText={(v) => setInspectionNote(it.key, v)}
                placeholder={t('phInspectionOther')}
                placeholderTextColor={outdoor.textDim}
                multiline
              />
            ) : (
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
            )}

            {/* A FAILED INSPECTION MUST SAY WHAT FAILED. Without this the fail
                is the same empty record the tick was. */}
            {failed && !isOtherInspection(it.key) && (
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
          pinned
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

  // The step contract the reference settled on, unchanged: an ordered list,
  // one rendered at a time, 1-indexed.
  const STEPS = [
    { render: renderStep1 }, { render: renderStep2 }, { render: renderStep3 },
    { render: renderStep4 }, { render: renderStep5 },
  ];

  return (
    <LogbookStepper
      s={s}
      loading={loading}
      /* Read-only, with the reason, instead of a blank editable day. */
      unavailable={logReadFailed ? {
        title: t('logUnavailableTitle'),
        body: `${t('logUnavailableBody')} ${failureDetail(
          logReadFailed, logReadError, "today's log")}`,
        retryLabel: t('logUnavailableRetry'),
        onRetry: fetchData,
      } : null}
      title={t('screenTitle')}
      subtitle={`${FORM_NUMBER} · ${formatLogDate(date)}`}
      step={step}
      steps={STEPS}
      onStepChange={(n) => (n > step ? goNext() : goBack())}
      /* GATING NEXT ON STEP 2 — the documented exception, same as toolbox
         step 1. The stepper's rule is MARK, NEVER GATE, because a CP must be
         able to finish a day he cannot complete. This is the case that rule
         was never about: a crew row with no activity and no location makes the
         whole log unfilable, and every one of these fields is known the moment
         the card is on screen — he is standing in front of the crew. Being
         stopped at step 2 is better than discovering it at step 5 with four
         steps behind him. */
      nextDisabled={step === 2 && crewGaps.length > 0}
      nextHint={crewGaps.length > 0 ? crewGapSentence(crewGaps) : ''}
      onExit={() => router.push('/logbooks')}
      locked={locked}
      /* THE SERVER'S DOCUMENT, handed straight to the filed view.
         `filedLog`, never `activities`: the local list has been reconciled
         against the roster and withActivityIds has minted ids for rows that
         never had one, and a photograph aimed at one of those reaches
         nothing. Passing it also spares FiledLogView the refetch it would
         otherwise do for the eleven editors that hold no such state. */
      filedLog={filedLog}
      amendment={amendment}
      incompleteSteps={stepsLeftIncomplete}
      a11yProgressLabel={
        stepsLeftIncomplete.length
          ? t('stepsIncomplete').replace('{steps}', stepsLeftIncomplete.join(', '))
          : t('stepsAllComplete')
      }
      nextLabel={t('next')}
      submitLabel={t('submitAndSign')}
      submitting={signing}
      /* The handler above is the backstop; this is what stops him reaching it.
         Same pair every other form carries — the button is unavailable and the
         hint says WHICH tap fixes it, because "you have no signature" is the
         wrong sentence for a man looking at his own signature. */
      /* TWO REASONS THE DAY CANNOT BE SIGNED, and the hint below names
         whichever applies. The signature one comes first: a CP with no
         affirmed credential cannot fix the description into a filed log
         either, so telling him about the description first would send him to
         the wrong repair. */
      submitDisabled={!isAffirmedSignature(cpSignature) || descriptionEmpty}
      submitHint={affirmationHintKey(cpSignature, profileLoaded)
        ? tFinalize(affirmationHintKey(cpSignature, profileLoaded))
        : (descriptionEmpty ? t('descriptionRequiredHint') : '')}
      onSubmit={handleSubmitAndSign}
      logType={'daily_jobsite'}
      logId={existingLogId}
      draftKey={draftKey({ projectId, logType: 'daily_jobsite', date })}
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
      overlays={(
        <>
          {/* OUTSIDE the SafeAreaView on purpose: on native this is a
              pre-warmed full-screen absolute overlay, and inside the
              SafeAreaView its absolute fill would stop at the safe-area inset
              instead of going full-bleed. */}
          <CameraCaptureModal
            visible={cameraVisible}
            shots={cameraShots}
            /* CLOSING IS THE ONLY THING THIS DOES NOW. It used to also clear
               appendTargetId, the camera's filed-log target — that whole path
               moved to app/logbooks/photos.jsx and the state went with it, but
               this reset was left behind pointing at a binding that no longer
               exists. cameraTargetIndex is deliberately NOT cleared here: it is
               re-set on every open (see openCamera) and the capture effect
               keys off `cameraVisible`, so blanking it on close would only
               race the compress queue that is still draining. */
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

      {/* THE CONSEQUENCE, BEFORE HE TAPS. A bland "are you sure" would let him
          through to discover at a disabled Next, two steps later, that a crew
          he can still see now has men and no work recorded. */}
      <Modal
        visible={!!deletingCrew}
        transparent
        animationType="fade"
        onRequestClose={() => setDeletingCrew(null)}
      >
        <View style={s.modalOverlay}>
          <View style={s.modalCard}>
            <Text style={s.modalTitle}>
              {t('deleteCrewTitle').replace('{crew}', deletingCrew?.name || '')}
            </Text>

            {deletingCrew?.impact?.stranded ? (
              <Text style={s.modalBody}>
                {t('deleteCrewStrands')
                  .replace('{crew}', deletingCrew.impact.stranded.company)
                  .replace('{n}', plural(
                    'workers_one', 'workers_other',
                    deletingCrew.impact.stranded.workers,
                  ))}
              </Text>
            ) : deletingCrew?.impact?.hasDescription ? (
              <Text style={s.modalBody}>{t('deleteCrewLosesWork')}</Text>
            ) : (
              <Text style={s.modalBody}>{t('deleteCrewPlain')}</Text>
            )}

            {/* Deleting everything does not empty the log. Said here, because a
                CP who deletes to a blank screen and reopens to a full one will
                think the app lost his work. */}
            {deletingCrew?.impact?.isLastRow && (
              <Text style={s.modalNote}>{t('deleteCrewLastRow')}</Text>
            )}

            <View style={s.modalActions}>
              <Pressable
                style={s.secondaryBtn}
                accessibilityRole="button"
                onPress={() => setDeletingCrew(null)}
              >
                <Text style={s.secondaryBtnText}>{t('deleteCrewCancel')}</Text>
              </Pressable>
              <Pressable
                style={s.dangerBtn}
                accessibilityRole="button"
                onPress={confirmDeleteCrew}
              >
                <Text style={s.dangerBtnText}>{t('deleteCrewConfirm')}</Text>
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
        </>
      )}
    />
  );
}

function buildStyles() {
  return StyleSheet.create({
    // The 51 CHROME keys now live in buildStepperStyles() and are spread in
    // above — header, pips, footer, cards, chips, inputs, modals. They were
    // lifted verbatim, so this screen renders exactly what it rendered before.
    // Only the keys BELOW are specific to the Daily Jobsite Log.
    ...buildStepperStyles(),
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
    cardFlagged: { borderColor: outdoor.warnBorder },
    crewTop: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      gap: spacing.sm, flexWrap: 'wrap',
    },
    crewName: {
      fontSize: typography.sizes.lg, fontWeight: '700', color: outdoor.text, flexShrink: 1,
    },
    crewMeta: { fontSize: typography.sizes.sm, color: outdoor.textSoft },

    // The headcount editor. Full touch target: this is a gloved thumb on a
    // site, and it is the control the whole card now hangs on.
    headcountRow: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      minHeight: touchTarget.min, marginTop: spacing.sm,
    },
    headcountLabel: {
      fontSize: typography.sizes.sm, fontWeight: '600', color: outdoor.textDim,
    },
    headcountInput: {
      minWidth: 64, minHeight: touchTarget.min,
      paddingHorizontal: spacing.sm,
      borderWidth: 1, borderColor: outdoor.lineStrong,
      borderRadius: borderRadius.md,
      backgroundColor: outdoor.surfaceSunk,
      color: outdoor.text, fontSize: typography.sizes.md, textAlign: 'center',
    },
    headcountGate: {
      flex: 1, fontSize: typography.sizes.fine, color: outdoor.textSoft,
    },

    // ── Removing a crew card ──────────────────────────────────────────────
    // Destructive, so it is NOT a primary button: outlined in the danger
    // colour, full touch target, and it never sits next to Next.
    deleteCrewBtn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.sm, minHeight: touchTarget.min,
      paddingHorizontal: spacing.md, marginTop: spacing.sm,
      alignSelf: 'flex-start',
      borderRadius: borderRadius.full,
      borderWidth: 1, borderColor: outdoor.danger,
    },
    deleteCrewBtnPressed: { opacity: opacity.o50 },
    deleteCrewText: {
      fontSize: typography.sizes.sm, fontWeight: '600', color: outdoor.danger,
    },
    // WHY THERE IS NO REMOVE ON THIS CARD. Stated, not silently absent.
    deleteCrewRefused: {
      fontSize: typography.sizes.fine, color: outdoor.textSoft,
      marginTop: spacing.sm,
    },
    modalBody: {
      fontSize: typography.sizes.md, color: outdoor.text, lineHeight: 22,
    },
    // The last-row note is secondary to the consequence above it.
    modalNote: {
      fontSize: typography.sizes.sm, color: outdoor.textSoft, lineHeight: 20,
    },
    dangerBtn: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
      gap: spacing.sm, minHeight: touchTarget.min,
      paddingHorizontal: spacing.lg, borderRadius: borderRadius.full,
      backgroundColor: outdoor.danger,
    },
    dangerBtnText: {
      // outdoor.textOnSelected, not a raw #ffffff: tokens.test.cjs counts the
      // distinct hex literals in this tree, and the token already IS white.
      fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.textOnSelected,
    },

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

    // ── The filed-log photo panel ──────────────────────────────────────────
    // Amber-bordered rather than the ordinary card surface: it sits under a
    // form the CP has just been told is read-only, and it has to read as the
    // deliberate exception it is rather than as a control that survived.
    appendCard: {
      borderWidth: 1, borderColor: outdoor.warnBorder, backgroundColor: outdoor.warnBg,
      gap: spacing.sm,
    },
    appendTitle: {
      fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.warn,
    },
    appendBody: {
      fontSize: typography.sizes.sm, color: outdoor.text, lineHeight: 20,
    },
    appendRow: { gap: spacing.sm, marginTop: spacing.sm },
    appendRowLabel: {
      fontSize: typography.sizes.sm, fontWeight: '700', color: outdoor.text,
    },
    // The SAME words the report prints under the same photograph, so the CP
    // and the person reading the PDF are looking at one fact.
    appendBadge: {
      marginTop: spacing.xs,
      fontSize: typography.sizes.fine, fontWeight: '700', color: outdoor.warn,
    },

    reviewCrew: {
      fontSize: typography.sizes.md, fontWeight: '700', color: outdoor.text,
    },
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
