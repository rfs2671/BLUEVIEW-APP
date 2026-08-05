import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, Image, Modal,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, Building2, CheckCircle, Save, Plus, Calendar,
  HardHat, Truck, AlertTriangle, Users, Clipboard, CloudSun, Camera, X, ImageIcon,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import LogbookLockBar from '../../src/components/LogbookLockBar';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI, weatherAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, chrome, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';
import FloatingNav from '../../src/components/FloatingNav';
import CameraCaptureModal, { useCameraPrewarmPermission } from '../../src/components/CameraCaptureModal';
import { compressUnderCap } from '../../src/utils/compressPhoto';
import { draftKey, readDraft, writeDraft, setDraftBackendId, markPending, clearPending, persistActivityPhotos, markFinalized } from '../../src/utils/logbookDrafts';
import * as ImagePicker from 'expo-image-picker';
import * as FileSystem from 'expo-file-system';
import { Platform } from 'react-native';

const MAX_PHOTOS_PER_ACTIVITY = 5;

// The in-process camera is native-only (vision-camera cannot run in a browser),
// and the desktop review view must keep the form it has. Everything gated on
// this constant is the CP's phone path and nothing else.
const MOBILE_CAPTURE = Platform.OS !== 'web';

// Client-side only. `pending` marks a photo whose background compression is
// still running; `id` is what lets that background job find its own photo again
// after the CP has kept shooting, deleted a sibling, or switched rows. Both are
// stripped before the log is saved, so the stored shape is unchanged.
let photoSeq = 0;
const newPhotoId = () => `cap_${Date.now()}_${(photoSeq += 1)}`;

const uriToBase64 = async (uri) => {
  try {
    if (!uri) return null;

    // Web: fetch the blob URL and convert to base64 via FileReader
    if (Platform.OS === 'web') {
      const response = await fetch(uri);
      const blob = await response.blob();
      return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onloadend = () => {
          // Strip the data:...;base64, prefix
          const result = reader.result;
          const b64 = result ? result.split(',')[1] : null;
          resolve(b64);
        };
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(blob);
      });
    }

    // Native: use FileSystem
    const b64 = await FileSystem.readAsStringAsync(uri, {
      encoding: FileSystem.EncodingType.Base64,
    });
    return b64;
  } catch (err) {
    console.warn('base64 conversion failed for', uri, err?.message);
    return null;
  }
};
const WEATHER_OPTIONS = ['Sunny', 'Cloudy', 'Rainy', 'Windy', 'Snow', 'Fog', 'Stormy'];
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

const EMPTY_ACTIVITY = () => ({
  crew_id: '',
  company: '',
  num_workers: '',
  work_description: '',
  work_locations: '',
  photos: [],
});

const EMPTY_OBSERVATION = () => ({
  description: '',
  responsible_party: '',
  remedy: '',
  corrected_immediately: null,
});

export default function DailyJobsiteLog() {
  const { colors, isDark } = useTheme();
  // Memoized so a re-render (e.g. the camera tap) doesn't rebuild the
  // entire StyleSheet on the critical path.
  const s = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  // Double-tap guard as a ref, NOT state: a setState here would
  // re-render the whole activities/photos tree at the exact moment the
  // native camera intent fires, stalling launch. Refs also update
  // synchronously, so the guard is more reliable against fast taps.
  const capturingRef = useRef(false);
  // In-process camera (CameraCaptureModal) — replaces launchCameraAsync on
  // native so the app is never backgrounded/killed by the OS camera handoff.
  // The surface is pre-warmed at screen mount, so cameraVisible only REVEALS
  // it; it does not create it. cameraTargetIndex remembers which activity the
  // capture belongs to while the camera is open.
  const [cameraVisible, setCameraVisible] = useState(false);
  const [cameraTargetIndex, setCameraTargetIndex] = useState(null);
  // Ids captured since the camera was last opened — the keep-shooting strip
  // shows THIS session's frames, not every photo the row already had.
  const [sessionShotIds, setSessionShotIds] = useState([]);
  // In-flight background compressions. handleSave waits on these so a log can
  // never be submitted carrying a raw multi-megabyte sensor JPEG.
  const pendingCompressRef = useRef([]);
  // id -> compressed uri. handleSave reads this instead of trusting that the
  // state update from a background job has already reached its closure.
  const compressedUriRef = useRef({});

  // ── Which activity does a photo belong to? ────────────────────────────────
  // The FAB is global, so it has to answer this without the CP telling it.
  // Signals, all cheap and all refs so scrolling never re-renders the form:
  //   activitiesBlockYRef — y of the Activity Details card in scroll content
  //   activityLayoutsRef  — per-row {y, h} inside that card
  //   scrollYRef/viewportHRef — where the CP is looking right now
  //   lastEditedRef       — the row whose fields/photos were last touched
  const activitiesBlockYRef = useRef(0);
  const activityLayoutsRef = useRef({});
  const scrollYRef = useRef(0);
  const viewportHRef = useRef(0);
  const lastEditedRef = useRef(null);
  const activitiesRef = useRef([]);
  const [fabTargetIndex, setFabTargetIndex] = useState(0);
  // Resolve the camera permission dialog HERE, at screen mount, so it is not
  // sitting between the capture tap and the preview. No-op on web.
  useCameraPrewarmPermission();
  const [existingLogId, setExistingLogId] = useState(null);
  // Tier 1 (1)b: true when the loaded log is finalized (is_locked) — the form
  // renders read-only and only the Amend path can change anything.
  const [locked, setLocked] = useState(false);

  const [projectAddress, setProjectAddress] = useState('');
  const [weather, setWeather] = useState('');
  const [weatherTemp, setWeatherTemp] = useState('');
  const [weatherWind, setWeatherWind] = useState('');
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [generalDescription, setGeneralDescription] = useState('');
  const [activities, setActivities] = useState([EMPTY_ACTIVITY()]);
  const [equipmentOnSite, setEquipmentOnSite] = useState({});
  const [checklistItems, setChecklistItems] = useState({});
  const [observations, setObservations] = useState([]);
  const [visitorsDeliveries, setVisitorsDeliveries] = useState('');
  const [timeIn, setTimeIn] = useState('');
  const [timeOut, setTimeOut] = useState('');
  const [areasVisited, setAreasVisited] = useState('');

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  // Phase A2 — autosave to the local draft on any change (debounced). Photos are
  // copied to persistent storage so they survive quit/reopen; base64 is NOT
  // stored (built only at server-save). No server call; `status` omitted so an
  // autosave never downgrades a submitted log.
  useEffect(() => {
    if (loading) return undefined;
    const t = setTimeout(async () => {
      try {
        const persistedActivities = await persistActivityPhotos(activities);
        await writeDraft(draftKey({ projectId, logType: 'daily_jobsite', date }), {
          data: {
            project_address: projectAddress,
            weather, weather_temp: weatherTemp, weather_wind: weatherWind,
            general_description: generalDescription,
            activities: persistedActivities,
            equipment_on_site: equipmentOnSite,
            checklist_items: checklistItems,
            observations,
            visitors_deliveries: visitorsDeliveries,
            time_in: timeIn, time_out: timeOut, areas_visited: areasVisited,
          },
          cp_signature: cpSignature,
          cp_name: cpName,
        });
      } catch (_e) { /* draft autosave is best-effort */ }
    }, 800);
    return () => clearTimeout(t);
  }, [
    loading, projectId, date, projectAddress, weather, weatherTemp, weatherWind,
    generalDescription, activities, equipmentOnSite, checklistItems, observations,
    visitorsDeliveries, timeIn, timeOut, areasVisited, cpSignature, cpName,
  ]);

  const fetchData = async () => {
    setLoading(true);
    try {
      // Phase A2 — local-first: read the on-device draft first; if present,
      // hydrate from it and skip the server round-trip (works fully offline).
      const _draft = await readDraft(draftKey({ projectId, logType: 'daily_jobsite', date }));
      if (_draft && _draft.data && Object.keys(_draft.data).length) {
        const d = _draft.data;
        // Tier 1 (1)b: a draft marked finalized locks the form read-only.
        if (_draft.finalized) {
          setLocked(true);
          markFinalized(draftKey({ projectId, logType: 'daily_jobsite', date }));
        }
        setExistingLogId(_draft.backend_id || null);
        if (d.project_address) setProjectAddress(d.project_address);
        if (d.weather) setWeather(d.weather);
        if (d.weather_temp) setWeatherTemp(d.weather_temp);
        if (d.weather_wind) setWeatherWind(d.weather_wind);
        if (d.general_description) setGeneralDescription(d.general_description);
        if (d.activities?.length > 0) setActivities(d.activities);
        if (d.equipment_on_site) setEquipmentOnSite(d.equipment_on_site);
        if (d.checklist_items) setChecklistItems(d.checklist_items);
        if (d.observations) setObservations(d.observations);
        if (d.visitors_deliveries) setVisitorsDeliveries(d.visitors_deliveries);
        if (d.time_in) setTimeIn(d.time_in);
        if (d.time_out) setTimeOut(d.time_out);
        if (d.areas_visited) setAreasVisited(d.areas_visited);
        if (_draft.cp_signature) setCpSignature(_draft.cp_signature);
        if (_draft.cp_name) setCpName(_draft.cp_name);
        setLoading(false);
        return;
      }

      // Daily Jobsite Log is a per-company HEADCOUNT log, not a
      // per-worker signature roster. We hit /daily-headcount which
      // returns pre-aggregated {sub_name, trade, worker_count_today}
      // rows — NOT the per-worker getCheckinsForDate() endpoint.
      const [projectData, headcount, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getDailyHeadcount(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'daily_jobsite', date).catch(() => []),
      ]);

      // FIX #2: Set full project address
      const fullAddress = projectData?.address || projectData?.location || '';
      setProjectAddress(fullAddress);

      // Tier 1 (1)b: prefer the EDITABLE (non-locked) doc — an amendment child —
      // over a locked original that shares (project, type, date).
      const _existingArr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = _existingArr.find(l => !l.is_locked) || _existingArr[0] || null;
      if (existing?.is_locked) {
        setLocked(true);
        markFinalized(draftKey({ projectId, logType: 'daily_jobsite', date }));
      }
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.project_address) setProjectAddress(d.project_address);
        if (d.weather) setWeather(d.weather);
        if (d.weather_temp) setWeatherTemp(d.weather_temp);
        if (d.weather_wind) setWeatherWind(d.weather_wind);
        if (d.general_description) setGeneralDescription(d.general_description);
        if (d.activities?.length > 0) setActivities(d.activities);
        if (d.equipment_on_site) setEquipmentOnSite(d.equipment_on_site);
        if (d.checklist_items) setChecklistItems(d.checklist_items);
        if (d.observations) setObservations(d.observations);
        if (d.visitors_deliveries) setVisitorsDeliveries(d.visitors_deliveries);
        if (d.time_in) setTimeIn(d.time_in);
        if (d.time_out) setTimeOut(d.time_out);
        if (d.areas_visited) setAreasVisited(d.areas_visited);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      } else {
        // Auto-build activities from pre-aggregated per-sub headcount.
        // One activity row per (sub, trade) pair with the count pulled
        // straight from the backend aggregation. No per-worker rows,
        // no per-worker signatures.
        const rows = Array.isArray(headcount) ? headcount : [];
        const autoActivities = rows.map((r, i) => ({
          crew_id: `C${i + 1}`,
          // PR B: 'UNASSIGNED' is a placeholder (worker's sub not on the roster
          // at check-in), not a company. Seed the field EMPTY so it reads as
          // pending and prompts the CP to assign the accountable sub — never
          // stamp the sentinel onto the 3301-02. The headcount is preserved.
          company: (r.sub_name && r.sub_name.toUpperCase() !== 'UNASSIGNED')
            ? r.sub_name : '',
          num_workers: String(r.worker_count_today ?? 0),
          work_description: r.trade || '',
          work_locations: '',
          photos: [],
        }));
        if (autoActivities.length > 0) setActivities(autoActivities);

        // FIX #1: Auto-fetch weather if no existing log
        fetchWeather(fullAddress);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // FIX #1: Weather autofill from API
  const fetchWeather = async (address) => {
    setWeatherLoading(true);
    try {
      const data = await weatherAPI.getCurrent(null, null, address || null);
      if (data?.condition) {
        setWeather(data.condition);
      }
      if (data?.temperature != null) {
        setWeatherTemp(`${Math.round(data.temperature)}°F`);
      }
      if (data?.wind_speed != null) {
        setWeatherWind(`${Math.round(data.wind_speed)} mph`);
      }
    } catch (e) {
      console.warn('Weather autofill failed (non-blocking):', e?.message);
    } finally {
      setWeatherLoading(false);
    }
  };

  const updateActivity = (index, field, value) => {
    lastEditedRef.current = index;
    setActivities(prev => prev.map((a, i) => i === index ? { ...a, [field]: value } : a));
  };

  /**
   * Resolve the activity a globally-launched capture belongs to.
   *
   * A photo landing on the wrong subcontractor is a compliance problem, not a
   * cosmetic one, so the rule is explicit and the answer is shown on the FAB
   * itself before the CP taps it. Cascade, first match wins:
   *
   *   1. The last row the CP EDITED (typed in, or used its own photo buttons),
   *      IF that row is currently on screen. Deliberate intent, still in view.
   *   2. Otherwise the row nearest the vertical CENTRE of the viewport, among
   *      rows currently on screen. "What I'm looking at."
   *   3. Otherwise the last row edited, even though it has scrolled away —
   *      better than silently defaulting when the CP has stated a preference.
   *   4. Otherwise row 1.
   *
   * Reads refs only: no state, no measure() round-trip, nothing awaited. The
   * FAB tap must stay two synchronous setStates.
   */
  const resolveTargetActivity = useCallback((rows) => {
    const n = rows.length;
    if (n <= 1) return 0;

    const scrollY = scrollYRef.current;
    const vh = viewportHRef.current;
    const blockY = activitiesBlockYRef.current;
    const layouts = activityLayoutsRef.current;
    const edited = lastEditedRef.current;
    const editedValid = edited != null && edited >= 0 && edited < n;

    const bounds = (i) => {
      const l = layouts[i];
      if (!l || !vh) return null;
      const top = blockY + l.y;
      return { top, bottom: top + l.h, mid: top + l.h / 2 };
    };
    const onScreen = (i) => {
      const b = bounds(i);
      return !!b && b.bottom > scrollY && b.top < scrollY + vh;
    };

    if (editedValid && onScreen(edited)) return edited;

    const centre = scrollY + vh / 2;
    let best = null;
    let bestDist = Infinity;
    for (let i = 0; i < n; i += 1) {
      if (!onScreen(i)) continue;
      const d = Math.abs(bounds(i).mid - centre);
      if (d < bestDist) { bestDist = d; best = i; }
    }
    if (best != null) return best;

    if (editedValid) return edited;
    return 0;
  }, []);

  // The FAB NAMES its target, so the CP is never guessing where a photo went.
  // Scrolling writes refs (no re-render); this pulls the resolved index into
  // state only when it actually changes, which is a few times per scroll at
  // most rather than once per frame.
  const syncFabTarget = useCallback(() => {
    if (!MOBILE_CAPTURE) return;
    const next = resolveTargetActivity(activitiesRef.current);
    setFabTargetIndex((prev) => (prev === next ? prev : next));
  }, [resolveTargetActivity]);

  // Mirror activities into a ref so the scroll handler and the FAB can read the
  // current rows without either becoming a dependency that re-subscribes.
  useEffect(() => {
    activitiesRef.current = activities;
    syncFabTarget();
  }, [activities, syncFabTarget]);

  const fabTargetLabel = (() => {
    const act = activities[fabTargetIndex];
    if (!act) return '';
    const name = (act.company || '').trim();
    if (name) return name;
    const crew = (act.crew_id || '').trim();
    return crew ? `Crew ${crew}` : `Activity ${fabTargetIndex + 1}`;
  })();

  const pickActivityPhoto = async (activityIndex) => {
    lastEditedRef.current = activityIndex;
    const current = activities[activityIndex]?.photos || [];
    if (current.length >= MAX_PHOTOS_PER_ACTIVITY) {
      toast.warning('Limit Reached', `Maximum ${MAX_PHOTOS_PER_ACTIVITY} photos per subcontractor`);
      return;
    }
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      toast.error('Permission Denied', 'Camera roll access is required to upload photos');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.6,
      base64: false,
      allowsMultipleSelection: true,
      selectionLimit: MAX_PHOTOS_PER_ACTIVITY - current.length,
    });
    if (result.canceled) return;
    const newPhotos = (result.assets || []).map((asset) => ({
      uri: asset.uri,
      base64: null, // deferred — will be converted at save time
      timestamp: new Date().toISOString(),
    }));
    setActivities(prev => prev.map((a, i) => {
      if (i !== activityIndex) return a;
      return { ...a, photos: [...(a.photos || []), ...newPhotos].slice(0, MAX_PHOTOS_PER_ACTIVITY) };
    }));
  };

  const takeActivityPhoto = async (activityIndex) => {
    lastEditedRef.current = activityIndex;
    const current = activities[activityIndex]?.photos || [];
    if (current.length >= MAX_PHOTOS_PER_ACTIVITY) {
      toast.warning('Limit Reached', `Maximum ${MAX_PHOTOS_PER_ACTIVITY} photos per subcontractor`);
      return;
    }
    if (capturingRef.current) return;
    capturingRef.current = true;
    try {
      // Web: camera API isn't available, use gallery
      if (Platform.OS === 'web') {
        const result = await ImagePicker.launchImageLibraryAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.Images,
          quality: 0.6,
          base64: false,
        });
        if (!result || result.canceled) return;
        const asset = result.assets?.[0];
        if (!asset) return;
        setActivities(prev => prev.map((a, idx) => {
          if (idx !== activityIndex) return a;
          return { ...a, photos: [...(a.photos || []), { uri: asset.uri, base64: null, timestamp: new Date().toISOString() }].slice(0, MAX_PHOTOS_PER_ACTIVITY) };
        }));
        return;
      }

      // Native: REVEAL the already-mounted, already-permissioned camera
      // overlay. Capture happens IN-PROCESS (CameraCaptureModal) so the app is
      // never backgrounded and killed by the OS camera handoff — the root
      // cause of the 20-30s cold-boot reload. The photo is appended in
      // handleCameraCapture once the shutter fires.
      //
      // Nothing may be awaited below this line. These setState calls are the
      // ENTIRE tap -> preview path; any fetch, permission request or file read
      // added here goes straight into the user's perceived open time.
      setCameraTargetIndex(activityIndex);
      setSessionShotIds([]);
      setCameraVisible(true);
    } catch (err) {
      console.error('Camera launch failed:', err);
      toast.error('Camera Error', 'Could not open camera. Check permissions in device settings.');
    } finally {
      capturingRef.current = false;
    }
  };

  /**
   * onCapture from CameraCaptureModal — the RAW sensor URI, handed over the
   * instant takePhoto resolves.
   *
   * NOTHING IS AWAITED HERE. The photo is appended immediately in `pending`
   * state so the strip and the activity row both react on the same frame, and
   * compressUnderCap is fired off unawaited. When it lands, the entry is found
   * by id (indexes move: the CP may have deleted a sibling meanwhile) and its
   * uri is swapped for the compressed one. The camera never waits for any of
   * it, which is the whole point — the CP can shoot the next frame now.
   *
   * If compression fails the raw URI stays in place: a full-size photo is worse
   * than a small one, but infinitely better than a lost one. handleSave still
   * encodes it.
   */
  const handleCameraCapture = (uri) => {
    if (cameraTargetIndex == null || !uri) return;
    const target = cameraTargetIndex;
    const existing = activitiesRef.current[target]?.photos || [];
    if (existing.length >= MAX_PHOTOS_PER_ACTIVITY) {
      toast.warning('Limit Reached', `Maximum ${MAX_PHOTOS_PER_ACTIVITY} photos per subcontractor`);
      return;
    }

    const id = newPhotoId();
    const shot = { id, uri, base64: null, pending: true, timestamp: new Date().toISOString() };
    setActivities(prev => prev.map((a, i) => {
      if (i !== target) return a;
      return { ...a, photos: [...(a.photos || []), shot] };
    }));
    setSessionShotIds(prev => [...prev, id]);

    const job = compressUnderCap(uri)
      .then((smallUri) => {
        if (smallUri) compressedUriRef.current[id] = smallUri;
        setActivities(prev => prev.map((a, i) => {
          if (i !== target) return a;
          return {
            ...a,
            photos: (a.photos || []).map(p => (
              p.id === id ? { ...p, uri: smallUri || p.uri, pending: false } : p
            )),
          };
        }));
      })
      .catch((err) => {
        console.warn('photo compression failed, keeping original:', err?.message);
        setActivities(prev => prev.map((a, i) => {
          if (i !== target) return a;
          return {
            ...a,
            photos: (a.photos || []).map(p => (p.id === id ? { ...p, pending: false } : p)),
          };
        }));
      })
      .finally(() => {
        pendingCompressRef.current = pendingCompressRef.current.filter(j => j !== job);
      });
    pendingCompressRef.current.push(job);
  };

  // The keep-shooting strip: this session's frames, in capture order, resolved
  // live out of the activity so `pending` flips to a real thumbnail in place.
  const cameraShots = useMemo(() => {
    if (cameraTargetIndex == null) return [];
    const photos = activities[cameraTargetIndex]?.photos || [];
    const byId = new Map(photos.filter(p => p.id).map(p => [p.id, p]));
    return sessionShotIds.map(id => byId.get(id)).filter(Boolean);
  }, [activities, cameraTargetIndex, sessionShotIds]);

  // Delete a shot straight from the camera strip (item 7 — in-camera review).
  // Removes it from the target activity's photos AND this session's id list so
  // the strip and the row drop it together, and forgets any compressed uri.
  // The CP never leaves the camera to discard a bad frame.
  const handleDeleteShot = (id) => {
    if (cameraTargetIndex == null || !id) return;
    const target = cameraTargetIndex;
    setActivities(prev => prev.map((a, i) => {
      if (i !== target) return a;
      return { ...a, photos: (a.photos || []).filter(p => p.id !== id) };
    }));
    setSessionShotIds(prev => prev.filter(sid => sid !== id));
    delete compressedUriRef.current[id];
  };

  const removeActivityPhoto = (activityIndex, photoIndex) => {
    lastEditedRef.current = activityIndex;
    setActivities(prev => prev.map((a, i) => {
      if (i !== activityIndex) return a;
      return { ...a, photos: (a.photos || []).filter((_, pi) => pi !== photoIndex) };
    }));
  };

  // PR C: tap-to-enlarge so the CP can verify his own evidence before attesting.
  // Mirrors the worker-detail OSHA-card lightbox modal. Shows the ENHANCED
  // derivative for a saved photo (the serving endpoint falls back to the
  // original on any failure, so enhance_status pending/failed never breaks the
  // image); an unsaved photo shows its local capture. Labels which is which.
  const [photoLightbox, setPhotoLightbox] = useState(null);
  const openPhotoLightbox = (photo, activityIndex, photoIndex) => {
    if (!photo || photo.pending) return;
    const done = photo.enhance_status === 'done';
    // A photo already persisted server-side carries an enhance_status; use the
    // server URL so we show the enhanced (or original-fallback) render.
    if (existingLogId && photo.enhance_status) {
      setPhotoLightbox({
        uri: logbooksAPI.getLogbookPhotoUrl(
          existingLogId, activityIndex, photoIndex,
          done ? 'enhanced' : 'original', photo.enhance_status,
        ),
        label: done ? 'Enhanced' : `Original — enhancement ${photo.enhance_status}`,
      });
      return;
    }
    const local = photo.uri || (photo.base64 ? `data:image/jpeg;base64,${photo.base64}` : null);
    if (local) setPhotoLightbox({ uri: local, label: 'Original' });
  };

  const addActivity = () => setActivities(prev => {
    // A freshly added row is what the CP means to work on next, so it becomes
    // the FAB's target immediately.
    lastEditedRef.current = prev.length;
    return [...prev, EMPTY_ACTIVITY()];
  });

  const toggleEquipment = (key) => setEquipmentOnSite(prev => ({ ...prev, [key]: !prev[key] }));
  const toggleChecklist = (key) => setChecklistItems(prev => ({ ...prev, [key]: !prev[key] }));

  const addObservation = () => setObservations(prev => [...prev, EMPTY_OBSERVATION()]);
  const updateObservation = (index, field, value) => {
    setObservations(prev => prev.map((o, i) => i === index ? { ...o, [field]: value } : o));
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      // Phase A2 — write the LOCAL draft first (persistent photos, no base64) so
      // an offline CP completes the log without losing anything. The server push
      // below is best-effort; offline it's deferred (markPending) and the draft
      // stays the source of truth.
      const _key = draftKey({ projectId, logType: 'daily_jobsite', date });
      const _persisted = await persistActivityPhotos(activities);
      await writeDraft(_key, {
        data: {
          project_address: projectAddress, weather, weather_temp: weatherTemp, weather_wind: weatherWind,
          general_description: generalDescription, activities: _persisted,
          equipment_on_site: equipmentOnSite, checklist_items: checklistItems, observations,
          visitors_deliveries: visitorsDeliveries, time_in: timeIn, time_out: timeOut, areas_visited: areasVisited,
        },
        cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
      });

      // Let any background compression finish first. Without this, saving
      // immediately after a capture would base64 the RAW sensor JPEG that the
      // pending entry still points at — several MB inlined into the log.
      // allSettled, not all: a failed compress must not block the save.
      if (pendingCompressRef.current.length > 0) {
        await Promise.allSettled(pendingCompressRef.current);
      }

      // Convert any URI-only photos to base64 before saving. Encode
      // sequentially with a setTimeout(0) yield between photos so the
      // native thread is released between encodes — the old Promise.all
      // burst held the UI thread and froze submit. Payload shape
      // unchanged (base64 still inlined under data.activities).
      const activitiesWithBase64 = [];
      for (const act of activities) {
        if (!act.photos || act.photos.length === 0) {
          activitiesWithBase64.push(act);
          continue;
        }
        const convertedPhotos = [];
        for (const photo of act.photos) {
          // `pending`/`id` are client-side bookkeeping for the background
          // compress. Strip them so the stored photo shape is exactly what it
          // was before keep-shooting existed — and spread the REST through, so
          // fields the backend adds (enhance_status, r2 keys) survive a re-save.
          const { pending, id, ...stored } = photo; // eslint-disable-line no-unused-vars
          if (stored.base64 || !stored.uri) {
            convertedPhotos.push(stored); // already encoded, or nothing to encode
            continue;
          }
          // Prefer the compressed derivative if its job finished. Read from the
          // ref rather than `photo.uri` because that state update may not have
          // reached this closure's copy of `activities` yet.
          const uri = (id && compressedUriRef.current[id]) || stored.uri;
          await new Promise((resolve) => setTimeout(resolve, 0)); // yield before each encode
          const b64 = await uriToBase64(uri);
          convertedPhotos.push({ ...stored, uri, base64: b64 });
        }
        activitiesWithBase64.push({ ...act, photos: convertedPhotos });
      }

      const payload = {
        project_id: projectId,
        log_type: 'daily_jobsite',
        date,
        data: {
          project_address: projectAddress,
          weather,
          weather_temp: weatherTemp,
          weather_wind: weatherWind,
          general_description: generalDescription,
          activities: activitiesWithBase64,
          equipment_on_site: equipmentOnSite,
          checklist_items: checklistItems,
          observations,
          visitors_deliveries: visitorsDeliveries,
          time_in: timeIn,
          time_out: timeOut,
          areas_visited: areasVisited,
          // superintendent fields intentionally omitted — super signs from site device
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
        // Server push landed — bind the id, clear the pending marker.
        await setDraftBackendId(_key, existingLogId || created?.id || created?._id);
        await clearPending(_key);
      } catch (pushErr) {
        // Offline / server error — the local draft is already saved above; defer
        // the push. NOTE: a submit made offline has no server id, so the
        // signature audit below is skipped until it syncs.
        await markPending(_key);
        console.warn('daily_jobsite push deferred (will sync on reconnect):', pushErr?.message);
      }

      await autoSave(cpName, cpSignature);

      // Record signature audit event
      if (submitStatus === 'submitted' && cpSignature) {
        const docId = existingLogId || created?.id || created?._id;
        if (docId) {
          const { recordSignatureEvent } = require('../../src/utils/signatureAudit');
          recordSignatureEvent({
            documentType: 'logbook',
            documentId: docId,
            eventType: 'cp_sign',
            signerName: cpName,
            signerRole: user?.role || 'cp',
            signatureData: cpSignature,
            contentSnapshot: {
              log_type: 'daily_jobsite',
              date,
              project_id: projectId,
              data: payload.data,
              status: submitStatus,
            },
            user,
          }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
        }
      }

      toast.success(submitStatus === 'submitted' ? 'Submitted' : 'Draft Saved',
        submitStatus === 'submitted' ? 'Log submitted successfully' : 'Draft saved');
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save log');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingCenter}>
            <ActivityIndicator size="large" color={colors.text.primary} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/logbooks')}
            />
            <View>
              <Text style={s.headerTitle}>Daily Jobsite Log</Text>
              <Text style={s.headerSub}>NYC DOB 3301-02</Text>
            </View>
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          scrollEventThrottle={64}
          onLayout={(e) => { viewportHRef.current = e.nativeEvent.layout.height; syncFabTarget(); }}
          onScroll={(e) => { scrollYRef.current = e.nativeEvent.contentOffset.y; syncFabTarget(); }}
        >
          {/* Tier 1 (1)b: a finalized log renders read-only. pointerEvents 'none'
              makes EVERY field below non-interactive (inputs, chips, the photo
              add/capture controls, the SignaturePad) — no per-field flags to
              miss. Scrolling still works; the LockBar stays interactive. */}
          <View pointerEvents={locked ? 'none' : 'auto'}>
          {/* Date */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>
                {new Date(date).toLocaleDateString('en-US', {
                  weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
                })}
              </Text>
            </View>
          </GlassCard>

          {/* Project Info — FIX #2: Full address, read-only */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Project Information</Text>
            <View style={s.fieldRow}>
              <Text style={s.fieldLabel}>Address</Text>
              <Text style={s.fieldValueReadonly}>{projectAddress || 'No address on file'}</Text>
            </View>

            {/* Weather — FIX #1: Auto-filled from API */}
            <View style={s.fieldRowVertical}>
              <View style={s.weatherHeader}>
                <Text style={s.fieldLabel}>Weather</Text>
                {weatherTemp ? (
                  <Text style={s.weatherAuto}>
                    {weatherTemp}{weatherWind ? ` • ${weatherWind}` : ''}
                  </Text>
                ) : null}
                {weatherLoading && <ActivityIndicator size="small" color={colors.primary} />}
              </View>
              <View style={s.weatherRow}>
                {WEATHER_OPTIONS.map((w) => (
                  <Pressable
                    key={w}
                    onPress={() => setWeather(weather === w ? '' : w)}
                    style={[s.weatherBtn, weather === w && s.weatherBtnActive]}
                  >
                    <Text style={[s.weatherBtnText, weather === w && s.weatherBtnTextActive]}>{w}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </GlassCard>

          {/* General Description */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>General Description of Today's Activities</Text>
            <TextInput
              style={s.textArea}
              value={generalDescription}
              onChangeText={setGeneralDescription}
              placeholder="Describe the main work performed today..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={4}
            />
          </GlassCard>

          {/* Activity Details Table.
              The wrapper exists to give the FAB a scroll-content-relative y for
              this block; each card then reports its own offset within it. */}
          <View onLayout={(e) => { activitiesBlockYRef.current = e.nativeEvent.layout.y; syncFabTarget(); }}>
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Users size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>Activity Details</Text>
            </View>
            <Text style={s.sectionSubtitle}>Auto-populated from check-ins. Edit as needed.</Text>

            {activities.map((act, i) => (
              <View
                key={i}
                // Only worth marking when there is a choice to get wrong.
                style={[s.activityCard,
                  MOBILE_CAPTURE && activities.length > 1 && i === fabTargetIndex && s.activityCardTarget]}
                onLayout={(e) => {
                  const { y, height } = e.nativeEvent.layout;
                  activityLayoutsRef.current[i] = { y, h: height };
                  syncFabTarget();
                }}
              >
                <View style={s.activityRow}>
                  <View style={s.activityField}>
                    <Text style={s.activityLabel}>CREW</Text>
                    <TextInput style={s.activityInput} value={act.crew_id}
                      onChangeText={(v) => updateActivity(i, 'crew_id', v)}
                      placeholder="C1" placeholderTextColor={colors.text.subtle} />
                  </View>
                  <View style={[s.activityField, { flex: 2 }]}>
                    <Text style={s.activityLabel}>COMPANY</Text>
                    <TextInput style={s.activityInput} value={act.company}
                      onChangeText={(v) => updateActivity(i, 'company', v)}
                      placeholder="Company" placeholderTextColor={colors.text.subtle} />
                    {/* PR B: workers present but no company = pending assignment.
                        Reads as pending in the editor; the 3301-02 export renders
                        it as "Pending assignment" too — never dropped. */}
                    {!((act.company || '').trim()) && (parseInt(act.num_workers, 10) || 0) > 0 ? (
                      <Text style={s.pendingHint}>Pending assignment</Text>
                    ) : null}
                  </View>
                  <View style={s.activityField}>
                    <Text style={s.activityLabel}># WORKERS</Text>
                    <TextInput style={s.activityInput} value={act.num_workers}
                      onChangeText={(v) => updateActivity(i, 'num_workers', v)}
                      placeholder="0" placeholderTextColor={colors.text.subtle} keyboardType="numeric" />
                  </View>
                </View>
                <View style={s.activityField}>
                  <Text style={s.activityLabel}>WORK DESCRIPTION</Text>
                  <TextInput style={s.activityInput} value={act.work_description}
                    onChangeText={(v) => updateActivity(i, 'work_description', v)}
                    placeholder="Work performed..." placeholderTextColor={colors.text.subtle} />
                </View>
                
                <View style={s.activityField}>
                  <Text style={s.activityLabel}>WORK LOCATIONS</Text>
                  <TextInput style={s.activityInput} value={act.work_locations}
                    onChangeText={(v) => updateActivity(i, 'work_locations', v)}
                    placeholder="Floors, areas..." placeholderTextColor={colors.text.subtle} />
                </View>

                {/* Photos */}
                <View style={s.photosSection}>
                  <View style={s.photosHeader}>
                    <Camera size={14} strokeWidth={1.5} color={colors.text.muted} />
                    {/* No "(0/5)" — an empty counter is chrome for something
                        that does not exist yet. The cap only matters once the
                        CP is actually accumulating photos. */}
                    <Text style={s.activityLabel}>
                      PHOTOS{(act.photos || []).length > 0
                        ? ` (${(act.photos || []).length}/${MAX_PHOTOS_PER_ACTIVITY})`
                        : ''}
                    </Text>
                    {/* The strip fits 2.8 tiles at 390px, so from the third
                        photo on the row clips mid-frame. showsHorizontal-
                        ScrollIndicator only paints DURING a scroll (auto-hiding
                        overlay bars on both web and iOS), which is no help to
                        someone looking at a still screen — hence a standing
                        hint as well. */}
                    {(act.photos || []).length >= 3 && (
                      <Text style={s.photoScrollHint}>swipe ›</Text>
                    )}
                  </View>
                  {(act.photos || []).length > 0 && (
                    // Indicator ON: at 390px the third tile clips mid-frame and
                    // read as a broken image rather than as "there is more".
                    <ScrollView horizontal showsHorizontalScrollIndicator style={s.photoScroll}>
                      {(act.photos || []).map((photo, pi) => (
                        <View key={photo.id ?? pi} style={s.photoThumb}>
                          {photo.pending ? (
                            // Placeholder until the background compress lands.
                            // Rendering the raw capture here would make the UI
                            // thread decode a full-size sensor JPEG per tile.
                            <View style={[s.photoImage, s.photoPending]}>
                              <ActivityIndicator size="small" color={colors.text.muted} />
                            </View>
                          ) : (
                            <Pressable onPress={() => openPhotoLightbox(photo, i, pi)}>
                              <Image
                                source={{ uri: photo.uri || (photo.base64 ?
                                  `data:image/jpeg;base64,${photo.base64}` : undefined) }}
                                style={s.photoImage}
                              />
                            </Pressable>
                          )}
                          <Pressable style={s.photoRemove} hitSlop={10} onPress={() => removeActivityPhoto(i, pi)}>
                            <X size={14} strokeWidth={2.5} color="#fff" />
                          </Pressable>
                        </View>
                      ))}
                    </ScrollView>
                  )}
                  {(act.photos || []).length < MAX_PHOTOS_PER_ACTIVITY && (
                    <View style={s.photoActions}>
                      {/* Take Photo is the workflow; Gallery is the fallback.
                          They were identical outline pills, which said neither. */}
                      <Pressable style={s.photoBtnPrimary} onPress={() => takeActivityPhoto(i)}>
                        <Camera size={16} strokeWidth={2} color={colors.white} />
                        <Text style={s.photoBtnPrimaryText}>Take Photo</Text>
                      </Pressable>
                      <Pressable style={s.photoBtn} onPress={() => pickActivityPhoto(i)}>
                        <ImageIcon size={16} strokeWidth={1.5} color={colors.text.muted} />
                        <Text style={s.photoBtnText}>Gallery</Text>
                      </Pressable>
                    </View>
                  )}
                </View>
              </View>
            ))}

            <GlassButton title="+ Add Activity" onPress={addActivity} style={s.addBtn} />
          </GlassCard>
          </View>

          {/* Equipment */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Truck size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>Equipment on Site</Text>
            </View>
            <View style={s.chipRow}>
              {EQUIPMENT_ITEMS.map((item) => (
                <Pressable key={item.key} onPress={() => toggleEquipment(item.key)}
                  style={[s.chip, equipmentOnSite[item.key] && s.chipActive]}>
                  <Text style={[s.chipText, equipmentOnSite[item.key] && s.chipTextActive]}>
                    {item.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Safety Checklist */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Clipboard size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>Items Inspected</Text>
            </View>
            <View style={s.chipRow}>
              {CHECKLIST_ITEMS.map((item) => (
                <Pressable key={item.key} onPress={() => toggleChecklist(item.key)}
                  style={[s.chip, checklistItems[item.key] && s.chipActive]}>
                  {checklistItems[item.key] && <CheckCircle size={14} strokeWidth={2} color={semantic.verified} />}
                  <Text style={[s.chipText, checklistItems[item.key] && s.chipTextActive]}>
                    {item.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Observations */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <AlertTriangle size={16} strokeWidth={1.5} color={semantic.attention} />
              <Text style={s.sectionTitle}>Safety Observations / Violations</Text>
            </View>
            {observations.map((obs, i) => (
              <View key={i} style={s.observationCard}>
                <TextInput style={s.fieldInput} value={obs.description}
                  onChangeText={(v) => updateObservation(i, 'description', v)}
                  placeholder="Describe observation..." placeholderTextColor={colors.text.subtle} multiline />
                <TextInput style={s.fieldInput} value={obs.responsible_party}
                  onChangeText={(v) => updateObservation(i, 'responsible_party', v)}
                  placeholder="Responsible party" placeholderTextColor={colors.text.subtle} />
                <TextInput style={s.fieldInput} value={obs.remedy}
                  onChangeText={(v) => updateObservation(i, 'remedy', v)}
                  placeholder="Remedy / corrective action" placeholderTextColor={colors.text.subtle} />
              </View>
            ))}
            <GlassButton title="+ Add Observation" onPress={addObservation} style={s.addBtn} />
          </GlassCard>

          {/* Visitors / Deliveries */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Visitors / Deliveries</Text>
            <TextInput style={s.textArea} value={visitorsDeliveries}
              onChangeText={setVisitorsDeliveries}
              placeholder="Record any visitors or deliveries..." placeholderTextColor={colors.text.subtle}
              multiline numberOfLines={3} />
          </GlassCard>

          {/* CP Signature ONLY — FIX #3: No superintendent signature */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Building2 size={16} strokeWidth={1.5} color="#3b82f6" />
              <Text style={s.sectionTitle}>Competent Person Sign-Off</Text>
            </View>
            <Text style={s.sectionSubtitle}>
              Superintendent will sign from the site device after review.
            </Text>
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
          <View style={s.actions}>
            <GlassButton
              title={saving ? 'Saving...' : 'Save Draft'}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => handleSave('draft')}
              loading={saving}
              style={s.draftBtn}
            />
            <GlassButton
              title={saving ? 'Saving...' : 'Submit'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
              onPress={() => handleSave('submitted')}
              loading={saving}
              style={s.submitBtn}
            />
          </View>
          )}

          <LogbookLockBar
            locked={locked}
            logId={existingLogId}
            canFinalize={!locked && !!existingLogId}
            onFinalized={() => setLocked(true)}
            onAmended={fetchData}
          />
        </ScrollView>

        {/* PERSISTENT CAPTURE. Take Photo lives 1000px+ down the form, inside
            the 5th slot of an activity card — on a phone, on a jobsite, that is
            a scroll the CP pays for every single photo. This is the same
            action, pinned above the nav, always reachable.

            It NAMES its target row: a photo landing on the wrong subcontractor
            is a compliance defect, and a global button that does not say where
            it is aiming would create them silently. See resolveTargetActivity.

            Native only (MOBILE_CAPTURE) — the desktop review view is unchanged,
            and there is no in-process camera on web to open. Hidden when the log
            is finalized (Tier 1 (1)b) so a locked log can't add photos. */}
        {MOBILE_CAPTURE && !locked && (
          <View style={s.fabWrap} pointerEvents="box-none">
            <Pressable
              style={({ pressed }) => [s.fab, pressed && s.fabPressed]}
              onPress={() => takeActivityPhoto(fabTargetIndex)}
              accessibilityRole="button"
              accessibilityLabel={`Take photo for ${fabTargetLabel}`}
            >
              <Camera size={20} strokeWidth={2} color={colors.white} />
              <View style={s.fabTextWrap}>
                <Text style={s.fabText}>Photo</Text>
                {activities.length > 1 && !!fabTargetLabel && (
                  <Text style={s.fabTarget} numberOfLines={1}>{fabTargetLabel}</Text>
                )}
              </View>
            </Pressable>
          </View>
        )}

        <FloatingNav />
      </SafeAreaView>
      {/* OUTSIDE the SafeAreaView on purpose: on native this is a pre-warmed
          full-screen absolute overlay, and inside the SafeAreaView its absolute
          fill would stop at the safe-area inset instead of going full-bleed.
          On web this resolves to the .web.jsx stub, which renders an RN Modal —
          unaffected by where it sits in the tree. */}
      <CameraCaptureModal
        visible={cameraVisible}
        shots={cameraShots}
        onClose={() => setCameraVisible(false)}
        onCapture={handleCameraCapture}
        onDeleteShot={handleDeleteShot}
      />

      {/* PR C: photo lightbox — mirrors the worker-detail OSHA-card modal. */}
      <Modal
        visible={!!photoLightbox}
        transparent
        animationType="fade"
        onRequestClose={() => setPhotoLightbox(null)}
      >
        <Pressable style={s.lightboxOverlay} onPress={() => setPhotoLightbox(null)}>
          <Pressable style={s.lightboxClose} hitSlop={16} onPress={() => setPhotoLightbox(null)}>
            <X size={26} color="#fff" />
          </Pressable>
          {photoLightbox?.uri ? (
            <Image
              source={{ uri: photoLightbox.uri }}
              style={s.lightboxImage}
              resizeMode="contain"
            />
          ) : null}
          {photoLightbox?.label ? (
            <Text style={s.lightboxLabel}>{photoLightbox.label}</Text>
          ) : null}
        </Pressable>
      </Modal>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: { flex: 1 },
  loadingCenter: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  headerTitle: { fontSize: 17, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 12, color: colors.text.muted },
  scrollView: { flex: 1 },
  // Bottom padding clears BOTH floating layers: FloatingNav (bottom 24, ~56
  // tall) and the capture FAB above it (bottom 96, ~67 tall). At the old 100 the
  // FAB sat on top of Submit at the end of the scroll.
  scrollContent: { padding: spacing.lg, paddingBottom: MOBILE_CAPTURE ? 180 : 100 },
  section: { marginBottom: spacing.md },
  sectionTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.xs },
  sectionSubtitle: { fontSize: 13, color: colors.text.muted, marginBottom: spacing.md },
  sectionHeaderRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  fieldRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: spacing.sm },
  fieldRowVertical: { paddingVertical: spacing.sm },
  fieldLabel: { fontSize: 13, fontWeight: '600', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  fieldValueReadonly: { fontSize: 15, color: colors.text.primary, fontWeight: '500', flex: 1, textAlign: 'right' },
  fieldInput: {
    backgroundColor: withAlpha('#ffffff', 0.05), borderRadius: borderRadius.md,
    padding: spacing.sm, fontSize: 14, color: colors.text.primary,
    borderWidth: 1, borderColor: withAlpha('#ffffff', 0.08), marginTop: spacing.xs,
  },
  textArea: {
    backgroundColor: withAlpha('#ffffff', 0.05), borderRadius: borderRadius.md,
    padding: spacing.md, fontSize: 14, color: colors.text.primary,
    borderWidth: 1, borderColor: withAlpha('#ffffff', 0.08), minHeight: 80, textAlignVertical: 'top',
  },
  weatherHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  weatherAuto: { fontSize: 13, color: colors.primary, fontWeight: '500' },
  weatherRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  weatherBtn: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
    borderRadius: borderRadius.full, borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1),
    backgroundColor: withAlpha('#ffffff', 0.04),
  },
  weatherBtnActive: { backgroundColor: 'rgba(59,130,246,0.2)', borderColor: 'rgba(59,130,246,0.5)' },
  weatherBtnText: { fontSize: 13, color: colors.text.muted },
  weatherBtnTextActive: { color: '#3b82f6', fontWeight: '600' },
  activityCard: {
    borderWidth: 1, borderColor: withAlpha('#ffffff', 0.06), borderRadius: borderRadius.lg,
    padding: spacing.md, marginBottom: spacing.sm, gap: spacing.sm,
  },
  // The row the FAB is currently aiming at.
  activityCardTarget: { borderColor: withAlpha(colors.primary, 0.45), backgroundColor: withAlpha(colors.primary, 0.05) },
  activityRow: { flexDirection: 'row', gap: spacing.sm },
  activityField: { flex: 1, gap: 2 },
  activityLabel: { fontSize: 10, fontWeight: '600', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  activityInput: {
    backgroundColor: withAlpha('#ffffff', 0.04), borderRadius: borderRadius.sm,
    padding: spacing.xs, fontSize: 14, color: colors.text.primary,
  },
  pendingHint: {
    fontSize: 11, fontWeight: '600', color: semantic.attention, marginTop: 2,
  },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: borderRadius.full, borderWidth: 1, borderColor: withAlpha('#ffffff', 0.1),
    backgroundColor: withAlpha('#ffffff', 0.04),
  },
  chipActive: { backgroundColor: semantic.verifiedBg, borderColor: semantic.verifiedBorder },
  chipText: { fontSize: 13, color: colors.text.muted },
  chipTextActive: { color: chrome.brand, fontWeight: '500' },
  observationCard: {
    borderWidth: 1, borderColor: semantic.attentionBorder, borderRadius: borderRadius.lg,
    padding: spacing.md, marginBottom: spacing.sm, gap: spacing.sm,
  },
  addBtn: { marginTop: spacing.xs },
  actions: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.md, marginBottom: spacing.xl },
  draftBtn: { flex: 1 },
  submitBtn: { flex: 1, backgroundColor: semantic.verified, borderColor: semantic.verified },
  photosSection: { gap: spacing.xs, marginTop: spacing.xs },
  photosHeader: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  photoScrollHint: { fontSize: 10, fontWeight: '600', color: colors.primary, letterSpacing: 0.3 },
  photoScroll: { marginTop: spacing.xs, paddingTop: 8, paddingBottom: 4 },
  photoThumb: { width: 80, height: 80, borderRadius: borderRadius.md, marginRight: spacing.sm, position: 'relative', overflow: 'visible' },
  photoImage: { width: 80, height: 80, borderRadius: borderRadius.md },
  lightboxOverlay: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.92)',
    alignItems: 'center', justifyContent: 'center', padding: spacing.lg,
  },
  lightboxImage: { width: '100%', height: '80%' },
  lightboxClose: {
    position: 'absolute', top: 48, right: 24, zIndex: 2, padding: spacing.sm,
  },
  lightboxLabel: {
    marginTop: spacing.md, color: '#fff', fontSize: 13, fontWeight: '600',
    opacity: 0.85,
  },
  photoRemove: {
    // Item 5: was top:-6/right:-6 — OUTSIDE the 80×80 thumbnail, so it got clipped
    // and was untappable. Sit it just inside the corner and make it bigger; the
    // Pressable also gets a hitSlop so the tap target clears the icon.
    position: 'absolute', top: 3, right: 3, width: 26, height: 26, borderRadius: 13,
    backgroundColor: semantic.criticalBg, alignItems: 'center', justifyContent: 'center', zIndex: 2,
  },
  photoPending: {
    backgroundColor: withAlpha('#ffffff', 0.06),
    alignItems: 'center', justifyContent: 'center',
  },
  photoActions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
  // PRIMARY — filled brand. This is the action the log is built around.
  photoBtnPrimary: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    backgroundColor: colors.primary,
  },
  photoBtnPrimaryText: { fontSize: 12, fontWeight: '700', color: colors.white },
  // SECONDARY — neutral outline. Was an identical blue pill to Take Photo.
  photoBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: borderRadius.full, borderWidth: 1, borderColor: withAlpha('#ffffff', 0.12),
    backgroundColor: withAlpha('#ffffff', 0.04),
  },
  photoBtnText: { fontSize: 12, fontWeight: '500', color: colors.text.muted },

  // ── Persistent capture FAB ────────────────────────────────────────────────
  // Sits above FloatingNav (bottom 24 + ~56 pill + breathing room).
  fabWrap: { position: 'absolute', right: spacing.lg, bottom: 96 },
  fab: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingLeft: spacing.md, paddingRight: spacing.lg, paddingVertical: spacing.md,
    borderRadius: borderRadius.full,
    backgroundColor: colors.primary,
    shadowColor: '#000000', shadowOpacity: 0.35, shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 }, elevation: 8,
  },
  fabPressed: { opacity: 0.85 },
  fabTextWrap: { maxWidth: 150 },
  fabText: { fontSize: 15, fontWeight: '700', color: colors.white },
  fabTarget: { fontSize: 11, fontWeight: '500', color: withAlpha('#ffffff', 0.8) },
});
}
