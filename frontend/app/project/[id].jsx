import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Modal,
  Alert,
  Platform,
  Image,
} from 'react-native';
import { useRouter, useLocalSearchParams, useFocusEffect } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  MapPin,
  Users,
  Building2,
  ClipboardList,
  Settings,
  Wifi,
  ChevronRight,
  HardHat,
  Plus,
  Trash2,
  X,
  Smartphone,
  Key,
  CheckCircle,
  XCircle,
  Mail,
  Cloud,
  FileText,
  Zap,
  Radio,
  Clock,
  Shield,
  MessageCircle,
  ListChecks,
  Activity,
  AlertTriangle,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../src/components/GlassCard';
// RenewalAlertCard is UNMOUNTED — see the note at its two former mount
// sites below, and src/components/RenewalAlertCard.js. The component file
// is kept; nothing imports it.
// Phase V2.1.2 — RiskScoreCard is deprecated and no longer mounted.
// Replaced by RiskScoreCircle (the compact gauge in the project
// header) which itself opens RiskScoreDrawer on click. The old
// RiskScoreCard.jsx is kept as a deprecated reference until the
// redesign is verified, then deleted in a follow-up.
import RiskScoreCircle from '../../src/components/RiskScoreCircle';
import CompliancePanel from '../../src/components/CompliancePanel';
import NotificationsList from '../../src/components/NotificationsList';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast, ToastHost } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useProjects } from '../../src/hooks/useProjects';
import { useCheckIns } from '../../src/hooks/useCheckIns';
import OfflineIndicator from '../../src/components/OfflineIndicator';
import { projectsAPI, checkinsAPI, checklistsAPI, whatsappAPI } from '../../src/utils/api';
import { cacheProject, readCachedProject } from '../../src/utils/projectCache';
import OfflineNotice from '../../src/components/OfflineNotice';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import apiClient from '../../src/utils/api';
import { isValidBin } from '../../src/utils/bin';
import * as NfcHelper from '../../src/utils/nfcHelper';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, chrome, border, surface, text as tokenText, withAlpha } from '../../src/styles/semanticColors';
import { useIsDesktop } from '../../src/hooks/useIsDesktop';
import { useTheme } from '../../src/context/ThemeContext';
import HeaderBrand from '../../src/components/HeaderBrand';

// Site device API for project-specific devices
const siteDevicesAPI = {
  getByProject: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/site-devices`);
    return response.data;
  },
  create: async (projectId, deviceData) => {
    const response = await apiClient.post(`/api/projects/${projectId}/site-devices`, { ...deviceData, project_id: projectId });
    return response.data;
  },
  delete: async (projectId, deviceId) => {
    const response = await apiClient.delete(`/api/projects/${projectId}/site-devices/${deviceId}`);
    return response.data;
  },
  toggle: async (projectId, deviceId) => {
    const response = await apiClient.put(`/api/projects/${projectId}/site-devices/${deviceId}/toggle`);
    return response.data;
  },
};

// ── Desktop 2-column layout (RN-Web >=1024). Layout only; colors come from
//    semantic tokens inline so they stay theme-aware. Mobile never renders any
//    of this. ─────────────────────────────────────────────────────────────
const deskStyles = StyleSheet.create({
  header: {
    flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.sm,
    borderWidth: 1, borderRadius: borderRadius.lg,
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg, marginBottom: spacing.lg,
  },
  headerTitle: { fontSize: typography.sizes.lg, fontWeight: '600' },
  headerMeta: { fontSize: typography.sizes.sm },
  headerDot: { fontSize: typography.sizes.sm },
  chip: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: borderRadius.full, borderWidth: 1 },
  chipText: { fontSize: 10, fontWeight: '600', letterSpacing: 0.5 },
  cols: { flexDirection: 'row', gap: spacing.lg, alignItems: 'flex-start' },
  colLeft: { flex: 2, minWidth: 0, gap: spacing.md },
  colRight: { flex: 1, minWidth: 240, gap: spacing.sm },
  sectionLabel: { ...typography.label, marginBottom: spacing.xs, marginTop: spacing.sm },
  tileRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  tile: {
    flex: 1, minWidth: 150, borderWidth: 1, borderRadius: borderRadius.lg,
    paddingVertical: spacing.md, paddingHorizontal: spacing.md,
  },
  tileNumber: { fontSize: 32, fontWeight: '300', letterSpacing: -0.5 },
  tileLabel: { fontSize: typography.sizes.sm, marginTop: 2 },
  qaItem: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm, height: 44,
    paddingHorizontal: spacing.md, borderWidth: 1, borderRadius: borderRadius.md,
  },
  qaLabel: { flex: 1, fontSize: typography.sizes.sm, fontWeight: '500' },
});

// One stat tile. For the DOB exception tiles a zero (or loading) renders
// neutral — a 0 is good news, not painted with a state color. Operational
// tiles pass token=primary so their number stays legible at any value.
function DeskTile({ value, label, token, loading }) {
  const isZero = !loading && (value == null || value === 0);
  const numColor = loading || isZero ? semantic.neutral : (token || semantic.neutral);
  return (
    <View style={[deskStyles.tile, { backgroundColor: surface.card, borderColor: border.subtle }]}>
      <Text style={[deskStyles.tileNumber, { color: numColor }]}>{loading ? '—' : (value ?? 0)}</Text>
      <Text style={[deskStyles.tileLabel, { color: tokenText.secondary }]}>{label}</Text>
    </View>
  );
}

export default function ProjectDetailScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();
  // Desktop (RN-Web >=1024) renders the 2-column triage layout; mobile renders
  // exactly what it does today. Called unconditionally (hooks rule).
  const isDesktop = useIsDesktop();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [project, setProject] = useState(null);
  // DOB standing-open exposure for THIS project, one call to dob-summary
  // (?project_id). Desktop-only; fetch is gated on isDesktop below.
  const [dobExposure, setDobExposure] = useState(null);
  const [dobExpLoading, setDobExpLoading] = useState(true);
  // ── OFFLINE vs EMPTY ────────────────────────────────────────────────────
  // Every sub-panel on this screen used to `.catch(() => [])`, so a dead zone
  // rendered "No workers on site", "No site devices registered", "No checklists
  // assigned", "No files in this folder" and 0-valued stat tiles — each an
  // assertion about the project that the app never actually verified.
  // 'ok' | 'offline' | 'error' per read; the render branches on these BEFORE
  // reaching any empty state.
  const [projectState, setProjectState] = useState('ok');
  const [projectFromCache, setProjectFromCache] = useState(false);
  const [dobExpState, setDobExpState] = useState('ok');
  const [nfcState, setNfcState] = useState('ok');
  const [devicesState, setDevicesState] = useState('ok');
  const [onSiteState, setOnSiteState] = useState('ok');
  const [checklistsState, setChecklistsState] = useState('ok');
  const [waGroupsState, setWaGroupsState] = useState('ok');
  const { getProjectById } = useProjects();
  const { getActiveCheckIns } = useCheckIns();
  const [stats, setStats] = useState({
    onSiteWorkers: 0,
    subcontractors: 0,
    subcontractorCount: 0,
  });
  const [workersByCompany, setWorkersByCompany] = useState([]);
  
  // NFC management
  const [showAddNfcModal, setShowAddNfcModal] = useState(false);
  const [nfcTagId, setNfcTagId] = useState('');
  const [addingNfc, setAddingNfc] = useState(false);
  const [scanningNfc, setScanningNfc] = useState(false);
  // The tag_id currently being programmed, so the banner can show progress on
  // the RIGHT row when a project holds more than one provisional gate.
  const [programmingTag, setProgrammingTag] = useState(null);
  const [nfcSupported, setNfcSupported] = useState(false);
  const [nfcEnabled, setNfcEnabled] = useState(false);
  const [nfcTags, setNfcTags] = useState([]);

  // Site devices management
  const [siteDevices, setSiteDevices] = useState([]);
  const [showAddDeviceModal, setShowAddDeviceModal] = useState(false);
  const [newDevice, setNewDevice] = useState({
    username: '',
    password: '',
  });
  const [addingDevice, setAddingDevice] = useState(false);
  const [showCredentials, setShowCredentials] = useState(null);

  const [checklists, setChecklists] = useState([]);
  const [loadingChecklists, setLoadingChecklists] = useState(false);
  const [whatsappActive, setWhatsappActive] = useState(false);
  const [whatsappGroups, setWhatsappGroups] = useState([]);

  // V2.3 Commit 7 — inline notifications unread count. The
  // NotificationsList child reports unread count up via the
  // onUnreadCountChange callback so we can decorate the section
  // heading with a badge. (Global badge across all projects is
  // deferred to a future commit — see Q7 in inventory.)
  const [notificationsUnreadCount, setNotificationsUnreadCount] = useState(0);

  const isAdmin = user?.role === 'admin';

  // WHO MAY CHOOSE WHICH FILES A GATE TABLET READS. Deliberately NOT the
  // `isAdmin` above: that one excludes 'owner', which is the role every
  // self-serve signup receives, while projects/[id]/files.jsx — the screen
  // this row opens — admits `['owner', 'admin']`, and so does the server
  // (get_admin_user, and the count on GET /projects/{id}). Gating the row on
  // `isAdmin` would hide the backlog from an owner on the screen while the
  // screen behind it happily let him work it, which is the operator's failure
  // mode exactly: he would never see the count.
  //
  // Scoped to this row on purpose. `isAdmin` also gates NFC TAGS and SITE
  // DEVICES, and widening those is a decision about two other sections that
  // does not belong in a change about a file count.
  const canSelectSiteFiles = ['owner', 'admin']
    .includes(String(user?.role || '').toLowerCase());

  // FILES A SYNC OR AN UPLOAD BROUGHT IN THAT NOBODY HAS CHOSEN YET.
  //
  // Three answers, not two. A number renders; a 0 renders as "everything is
  // published"; and ABSENT renders as nothing at all — an older cached
  // project doc, or a role the server does not tell. Collapsing absent into 0
  // would make the screen assert that nothing is waiting, which is the single
  // claim this feature exists to stop it making falsely.
  const awaitingSelection =
    typeof project?.files_awaiting_site_selection === 'number'
      ? project.files_awaiting_site_selection
      : null;

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) {
      fetchData();
    }
  }, [isAuthenticated, projectId]);

  // RE-READ THE PROJECT WHEN THIS SCREEN COMES BACK INTO VIEW.
  //
  // The awaiting-selection count rides on the project document, and the one
  // thing that changes it is publishing files on projects/[id]/files — which
  // the admin reaches from this screen and returns to with router.back().
  // Without this, the amber count is stale at precisely the moment it matters
  // most: he has just chosen the files, and the row still says they are
  // waiting. A feature that lies about its own subject is worse than no
  // feature.
  //
  // ONLY the project, not fetchData(). A full refetch is seven requests
  // (NFC, devices, WhatsApp status + groups, active check-ins, checklists) to
  // refresh one integer. Mirrors the useFocusEffect in logbooks/index.jsx and
  // project/[id]/report-settings.jsx, narrowed to the read that can change.
  //
  // The mount pass is skipped: the effect above has already fetched, and
  // firing both would double every project read on every screen open.
  const focusedOnce = React.useRef(false);
  useFocusEffect(
    React.useCallback(() => {
      if (!focusedOnce.current) { focusedOnce.current = true; return; }
      if (!isAuthenticated || !projectId) return;
      let cancelled = false;
      (async () => {
        try {
          const fresh = await projectsAPI.getById(projectId);
          if (cancelled || !fresh) return;
          cacheProject(fresh);
          setProject(fresh);
          setProjectState('ok');
          setProjectFromCache(false);
        } catch (e) {
          // Best-effort. The copy already on screen stays, and its own
          // offline/error banner is unchanged — a failed refresh tells the
          // reader nothing new about this job.
          //
          // (That sentence deliberately does not end on the word p-r-o-j-e-c-t
          // followed by a full stop: test_project_response_delivers_what_the_
          // app_reads scans this file as TEXT, and `project.` immediately
          // above an identifier reads to its regex as a field access —
          // `project` `.` `console` — and fails the build.)
          console.warn('[project] focus refresh failed:', e?.message);
        }
      })();
      return () => { cancelled = true; };
    }, [isAuthenticated, projectId])
  );

  // DOB exposure rollup for the desktop tiles — ONE GET
  // /api/projects/dob-summary?project_id={id}. Desktop only; degrades to
  // muted "—" tiles on failure and never blocks the page.
  useEffect(() => {
    if (!isDesktop || !isAuthenticated || !projectId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        setDobExpLoading(true);
        const r = await apiClient.get(`/api/projects/dob-summary?project_id=${projectId}`);
        const row = r?.data?.by_project?.[projectId] || null;
        if (!cancelled) { setDobExposure(row); setDobExpState('ok'); }
      } catch (_e) {
        if (!cancelled) {
          setDobExposure(null);
          // UNKNOWN, not zero — DeskTile renders "—" off this state.
          setDobExpState(isOfflineError(_e) ? 'offline' : 'error');
        }
      } finally {
        if (!cancelled) setDobExpLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [isDesktop, isAuthenticated, projectId]);

  // Check NFC capability
  useEffect(() => {
    const checkNfcCapability = async () => {
      await NfcHelper.initNfc();
      const supported = await NfcHelper.isNfcSupported();
      setNfcSupported(supported);
      if (supported) {
        const enabled = await NfcHelper.isNfcEnabled();
        setNfcEnabled(enabled);
      }
    };
    checkNfcCapability();
  }, []);

  const fetchData = async () => {
    try {
      // PR D: read the SERVER object FIRST. WatermelonDB's local projects schema
      // omits ~29 server fields (nyc_bin, project_class, last_dob_sync_at,
      // dropbox_folder_path, …), so a local-first read renders "No BIN" etc.
      // even when the server has the value. The local record is the OFFLINE
      // FALLBACK only — this screen needs the network anyway (DOB tiles, sync
      // state, plans). We deliberately do NOT mirror those columns locally;
      // that recreates the divergence every time the server model grows.
      let projectData = null;
      let projectError = null;
      try {
        projectData = await projectsAPI.getById(projectId);
        cacheProject(projectData);  // P1: cache for offline selection
        setProjectState('ok');
        setProjectFromCache(false);
      } catch (e) {
        projectError = e;
        console.warn('Server project fetch failed, using local fallback:', e?.message);
      }
      if (!projectData) {
        // P1: AsyncStorage cache first (populated on every online load). The
        // WatermelonDB getProjectById stays as a last resort but is empty in
        // practice (dormant store), which is why offline used to error here.
        projectData = await readCachedProject(projectId) || await getProjectById(projectId);
        // Cached data is fine to show — but the screen has to SAY it is a saved
        // copy, otherwise stale fields read as current server truth.
        setProjectState(isOfflineError(projectError) ? 'offline' : 'error');
        setProjectFromCache(!!projectData);
      }
      setProject(projectData);

        {
          const nfcR = await settleFetch(() => projectsAPI.getNfcTags(projectId));
          setNfcState(nfcR.status);
          if (nfcR.status === 'ok') {
            setNfcTags(Array.isArray(nfcR.data) ? nfcR.data : []);
          } else {
            // The project payload carries its own tag list — a real (possibly
            // cached) fallback, not a fabricated empty.
            setNfcTags(projectData?.nfc_tags || []);
          }
        }

      // Fetch site devices for this project
      if (isAdmin) {
        const devR = await settleFetch(() => siteDevicesAPI.getByProject(projectId));
        setDevicesState(devR.status);
        if (devR.status === 'ok') {
          setSiteDevices(Array.isArray(devR.data) ? devR.data : []);
        }
      }

      // Fetch WhatsApp status
      try {
        const waStatus = await whatsappAPI.getStatus();
        const isActive = waStatus?.company_active === true;
        setWhatsappActive(isActive);
        if (isActive) {
          const groupsR = await settleFetch(() => whatsappAPI.getGroups(projectId));
          setWaGroupsState(groupsR.status);
          if (groupsR.status === 'ok') {
            setWhatsappGroups(Array.isArray(groupsR.data) ? groupsR.data : []);
          }
        }
      } catch (e) {
        // Status itself is unknown — the card stays hidden rather than claiming
        // anything about linked groups.
        setWhatsappActive(false);
      }

      // Fetch active check-ins for this project
      {
        const workersR = await settleFetch(() => getActiveCheckIns(projectId));
        setOnSiteState(workersR.status);
        if (workersR.status === 'ok') {
          const workers = Array.isArray(workersR.data) ? workersR.data : [];

          // Group workers by company
          const grouped = workers.reduce((acc, worker) => {
            const company = worker.company || 'Unassigned';
            if (!acc[company]) {
              acc[company] = [];
            }
            acc[company].push(worker);
            return acc;
          }, {});

          const companiesArray = Object.entries(grouped).map(([name, workers]) => ({
            name,
            workers,
          }));

          setWorkersByCompany(companiesArray);
          setStats({
            onSiteWorkers: workers.length,
            subcontractors: companiesArray.length,
            subcontractorCount: companiesArray.length,
          });
        }
        // On failure: leave stats/workersByCompany untouched. The ON SITE tile
        // renders "—" and the ON-SITE WORKERS section renders a notice, so
        // nothing here ever says "no workers on site" on our behalf.
      }
    } catch (error) {
      console.error('Failed to fetch project:', error);
      toast.error(
        isOfflineError(error) ? 'Offline' : 'Error',
        isOfflineError(error)
          ? 'Could not reach the server — some sections are unavailable.'
          : 'Could not load project details',
      );
    } finally {
      fetchChecklists();
      setLoading(false);
      setRefreshing(false);
    }
  };

  const fetchChecklists = async () => {
    setLoadingChecklists(true);
    const r = await settleFetch(() => checklistsAPI.getByProject(projectId));
    setChecklistsState(r.status);
    if (r.status === 'ok') {
      setChecklists(Array.isArray(r.data) ? r.data : []);
    } else {
      console.error('Failed to fetch checklists:', r.error);
    }
    setLoadingChecklists(false);
  };
  
  const onRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  /**
   * PROGRAM A BLANK STICKER WITH AN EXISTING GATE'S ID.
   *
   * Not registerNfcTag. That one READS the chip's UID and registers THAT as a
   * new tag, which would leave the provisional gate untouched and create a
   * second one beside it - two gates on one entrance, and the check-ins
   * already recorded against the first stranded on a row still marked
   * provisional. writeNfcTag takes an EXPLICIT id, so the chip's own UID is
   * irrelevant: the sticker is programmed to carry THIS gate's qr- id, the row
   * is unchanged, and every check-in against it stays attached.
   *
   * THE CHIP IS WRITTEN FIRST AND THE FLAG FLIPS SECOND. If the flag flipped
   * first and the write then failed, the record would claim a physical tag
   * that does not exist - exactly the silent state the flag exists to prevent.
   * The other way round is merely over-cautious: the banner stays up, and
   * re-writing the same URL to the same chip is idempotent.
   */
  const handleProgramProvisionalTag = async (tagId) => {
    if (!nfcEnabled) {
      toast.error('NFC Disabled', 'Please enable NFC in your device settings');
      return;
    }
    setProgrammingTag(tagId);
    toast.info('Ready to Program', 'Hold your phone near a blank NFC tag...');
    try {
      const result = await NfcHelper.writeNfcTag(projectId, tagId);
      if (!result.success) {
        toast.error('Write Failed', result.error || 'Could not write to the tag');
        return;
      }

      // Only now. See the ordering note above.
      try {
        await projectsAPI.markCheckinPointProgrammed(projectId, tagId);
        toast.success('Tag Programmed', 'This check-in point now has a physical tag');
        await fetchData();
      } catch (error) {
        // NAMED, and it says the tag IS written. "Failed" alone would send an
        // admin to reprogram a sticker that is already correct, and the retry
        // they actually need is this call, not the write.
        toast.error(
          'Tag Written, Record Not Updated',
          error.response?.data?.detail
            || 'The tag is programmed. Tap again to finish updating the record.',
        );
      }
    } catch (error) {
      console.error('Program provisional tag error:', error);
      toast.error('Error', 'Failed to program the tag');
    } finally {
      setProgrammingTag(null);
      await NfcHelper.cancelNfc();
    }
  };

  const handleScanNfcTag = async () => {
    if (!nfcEnabled) {
      toast.error('NFC Disabled', 'Please enable NFC in your device settings');
      return;
    }
    setScanningNfc(true);
    toast.info('Ready to Scan', 'Hold your phone near the NFC tag...');
    try {
      const result = await NfcHelper.registerNfcTag(projectId);
      if (result.success) {
        toast.success('Tag Scanned!', `Tag ID: ${result.tagId}`);
        
        setAddingNfc(true);
        try {
          const response = await projectsAPI.addNfcTag(projectId, {
            tag_id: result.tagId,
          });
          
          if (response.project) {
            setProject(response.project);
          }
          
          toast.success('Success!', 'NFC tag registered to project');
          setShowAddNfcModal(false);
          await fetchData();
        } catch (error) {
          console.error('Failed to register tag:', error);
          toast.error('Registration Failed', error.response?.data?.detail || 'Could not register tag to project');
        } finally {
          setAddingNfc(false);
        }
      } else {
        toast.error('Scan Failed', result.error || 'Could not scan NFC tag');
      }
    } catch (error) {
      console.error('NFC scan error:', error);
      toast.error('Error', 'Failed to scan NFC tag');
    } finally {
      setScanningNfc(false);
      await NfcHelper.cancelNfc();
    }
  };

  const handleAddNfcTag = async () => {
    if (!nfcTagId.trim()) {
      toast.error('Error', 'Please enter a tag ID');
      return;
    }

    setAddingNfc(true);
    try {
      await projectsAPI.addNfcTag(projectId, {
        tag_id: nfcTagId,
      });

      toast.success('Added', 'NFC tag registered successfully');
      setNfcTagId('');
      setShowAddNfcModal(false);
      await fetchData();
    } catch (error) {
      console.error('Failed to add NFC tag:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not add NFC tag');
    } finally {
      setAddingNfc(false);
    }
  };

  const handleDeleteNfcTag = (tagId) => {
    const confirmDelete = async () => {
      try {
        await projectsAPI.deleteNfcTag(projectId, tagId);
        toast.success('Deleted', 'NFC tag removed');
        await fetchData();
      } catch (error) {
        console.error('Failed to delete NFC tag:', error);
        toast.error('Error', 'Could not delete NFC tag');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Remove this NFC tag?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Remove NFC Tag', 'Are you sure?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const handleAddDevice = async () => {
    if (!newDevice.username.trim() || !newDevice.password.trim()) {
      toast.error('Error', 'Please fill in username and password');
      return;
    }

    setAddingDevice(true);
    try {
      // The form no longer collects a separate display name — the username IS
      // the device's identity. Sent explicitly so the device list shows it
      // rather than the backend's "Site Device" default.
      const result = await siteDevicesAPI.create(projectId, {
        ...newDevice,
        device_name: newDevice.username,
      });
      toast.success('Created', 'Site device created successfully');
      
      setShowCredentials({
        ...result,
        password: newDevice.password,
      });

      setNewDevice({ username: '', password: '' });
      setShowAddDeviceModal(false);
      await fetchData();
    } catch (error) {
      console.error('Failed to create device:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not create site device');
    } finally {
      setAddingDevice(false);
    }
  };

  const handleDeleteDevice = (deviceId) => {
    const confirmDelete = async () => {
      try {
        await siteDevicesAPI.delete(projectId, deviceId);
        toast.success('Deleted', 'Site device removed');
        await fetchData();
      } catch (error) {
        console.error('Failed to delete device:', error);
        toast.error('Error', 'Could not delete site device');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Remove this site device?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Remove Site Device', 'Are you sure?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const handleToggleDevice = async (device) => {
    try {
      await siteDevicesAPI.toggle(projectId, device.id);
      toast.success('Updated', `Device ${device.is_active ? 'disabled' : 'enabled'}`);
      await fetchData();
    } catch (error) {
      console.error('Failed to toggle device:', error);
      toast.error('Error', 'Could not update device');
    }
  };

  // No valid BIN flag — shared isValidBin() (mirrors backend
  // _is_placeholder_bin). When false, DOB scans silently return nothing, so we
  // flag it on the DOB Compliance action card (the dob-logs screen has the full
  // "No BIN on File" remediation flow). Same predicate as the DOB tab.
  const hasValidBin = isValidBin(project?.nyc_bin);

  const quickActions = [
    { title: 'Plans & Files', icon: FileText, path: `/projects/${projectId}/files`, color: '#3b82f6' },
    { title: 'Daily Log', icon: ClipboardList, path: `/daily-log?projectId=${projectId}`, color: '#8b5cf6' },
    // MR.14 commit 3 — v1 monitoring product surface. Activity feed
    // sits ABOVE the legacy DOB Compliance entry; both are reachable.
    { title: 'Activity', icon: Activity, path: `/project/${projectId}/activity`, color: '#0ea5e9' },
    // DOB Compliance + Check-in Trades are CORE modules — give them active
    // accent colors (like Plans/Daily Log/Activity) so they don't read as
    // disabled/greyed. They were never gated; the grey was only this hardcoded
    // semantic.neutral. Report Settings stays neutral (genuinely secondary).
    { title: 'DOB Compliance', icon: Shield, path: `/project/${projectId}/dob-logs`, color: '#ef4444', warn: !hasValidBin },
    { title: 'Report Settings', icon: Settings, path: `/project/${projectId}/report-settings`, color: semantic.neutral },
    { title: 'Check-in Trades', icon: HardHat, path: `/project/${projectId}/trades`, color: '#f59e0b' },
  ];

  // ── Desktop 2-column triage layout. Replaces the mobile header + stats +
  //    quick-actions block; the lower detail sections (notifications, NFC,
  //    devices, files) render unchanged below for both. Risk gauge is hidden
  //    on desktop (mobile keeps it); the drawer + mobile path are untouched.
  const renderDesktopTop = () => {
    const addr = project?.address || project?.location || '';
    const title = project?.name || addr || 'Project';
    const showAddr = addr && addr !== title;           // address ONCE, no dup
    // last_dob_sync_at, not first_poll_completed_at. This screen reads
    // GET /projects/{id}, which filters through ProjectResponse — the old field
    // was never declared there, so it arrived undefined and this badge showed
    // "NEVER SYNCED" on every project regardless of its real sync state.
    // last_dob_sync_at IS declared on the model, so the badge now tells the truth.
    const neverSynced = !project?.last_dob_sync_at;
    const exp = dobExposure || {};
    const dobUnknown = dobExpLoading || dobExpState !== 'ok';
    const cls = project?.project_class;
    const clsLabel = cls === 'major_b' ? 'MAJOR B' : cls === 'major_a' ? 'MAJOR A' : null;
    const Dot = () => <Text style={[deskStyles.headerDot, { color: tokenText.muted }]}>·</Text>;
    return (
      <>
        {/* Compressed single-row header — address once, no risk gauge. */}
        <View style={[deskStyles.header, { backgroundColor: surface.glass, borderColor: border.subtle }]}>
          <Text style={[deskStyles.headerTitle, { color: tokenText.primary }]} numberOfLines={1}>{title}</Text>
          {showAddr ? (<><Dot /><Text style={[deskStyles.headerMeta, { color: tokenText.secondary }]} numberOfLines={1}>{addr}</Text></>) : null}
          {project?.nyc_bin ? (<><Dot /><Text style={[deskStyles.headerMeta, { color: tokenText.secondary }]}>BIN {project.nyc_bin}</Text></>) : null}
          {project?.status ? (<><Dot /><Text style={[deskStyles.headerMeta, { color: tokenText.secondary }]}>{project.status}</Text></>) : null}
          {clsLabel ? (
            <View style={[deskStyles.chip, { backgroundColor: semantic.neutralBg, borderColor: border.subtle }]}>
              <Text style={[deskStyles.chipText, { color: semantic.neutralStrong }]}>{clsLabel}</Text>
            </View>
          ) : null}
          {neverSynced ? (
            <View style={[deskStyles.chip, { backgroundColor: surface.card, borderColor: border.subtle }]}>
              <Text style={[deskStyles.chipText, { color: tokenText.muted }]}>NEVER SYNCED</Text>
            </View>
          ) : null}
        </View>

        <View style={deskStyles.cols}>
          {/* LEFT (primary) — DOB exposure, forecast, operational tiles. */}
          <View style={deskStyles.colLeft}>
            <Text style={[deskStyles.sectionLabel, { color: tokenText.secondary }]}>DOB EXPOSURE</Text>
            {!dobExpLoading && dobExpState !== 'ok' && (
              <OfflineNotice
                mode={dobExpState}
                detail={
                  dobExpState === 'offline'
                    ? 'Exposure counts could not be fetched. The tiles show "—" because the totals are unknown, not zero.'
                    : 'The server could not return exposure counts. The tiles show "—" because the totals are unknown, not zero.'
                }
              />
            )}
            <View style={deskStyles.tileRow}>
              {/* `loading` == "no number to show" (renders "—"). A failed
                  dob-summary is exactly that: unknown, not zero. */}
              <DeskTile loading={dobUnknown} value={exp.open_violations} label="Open violations" token={semantic.criticalText} />
              <DeskTile loading={dobUnknown} value={exp.permits_expiring} label="Permits expiring <30d" token={semantic.attention} />
              <DeskTile loading={dobUnknown} value={exp.open_complaints} label="Open complaints" token={semantic.attention} />
            </View>

            <CompliancePanel projectId={projectId} />

            <Text style={[deskStyles.sectionLabel, { color: tokenText.secondary }]}>ON SITE</Text>
            <View style={deskStyles.tileRow}>
              {/* A read that never landed shows "—". Rendering 0 here would
                  assert an empty site / no tags / no devices. */}
              <DeskTile loading={onSiteState !== 'ok'} value={stats.onSiteWorkers} label="On site" token={tokenText.primary} />
              <DeskTile loading={nfcState !== 'ok' && nfcTags.length === 0} value={nfcTags.length} label="NFC tags" token={tokenText.primary} />
              <DeskTile loading={devicesState !== 'ok'} value={siteDevices.length} label="Devices" token={tokenText.primary} />
            </View>
          </View>

          {/* RIGHT (secondary) — quick actions as a compact list. */}
          <View style={deskStyles.colRight}>
            <Text style={[deskStyles.sectionLabel, { color: tokenText.secondary }]}>QUICK ACTIONS</Text>
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <Pressable
                  key={action.title}
                  onPress={() => router.push(action.path)}
                  accessibilityRole="link"
                  accessibilityLabel={action.title}
                  style={({ hovered }) => [
                    deskStyles.qaItem,
                    { backgroundColor: surface.glass, borderColor: border.subtle },
                    hovered && { backgroundColor: surface.glassHover, borderColor: border.medium },
                  ]}
                >
                  <Icon size={16} strokeWidth={1.5} color={chrome.icon} />
                  <Text style={[deskStyles.qaLabel, { color: tokenText.primary }]} numberOfLines={1}>{action.title}</Text>
                  {action.warn ? (
                    <Text style={{ fontSize: 10, fontWeight: '600', color: semantic.attention }}>No BIN</Text>
                  ) : null}
                </Pressable>
              );
            })}
          </View>
        </View>
      </>
    );
  };

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={s.loadingText}>Loading project...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

    if (!project) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingContainer}>
            {/* "Project not found" is what a 404 means. When the read FAILED and
                nothing is cached, the project's existence is unknown. */}
            {projectState !== 'ok' ? (
              <OfflineNotice
                mode={projectState}
                detail={
                  projectState === 'offline'
                    ? 'This project could not be loaded and no copy is saved on this device. It has not been deleted — reconnect and try again.'
                    : 'This project could not be read from the server. Try again.'
                }
              />
            ) : (
              <Text style={s.loadingText}>Project not found</Text>
            )}
            <GlassButton title="Go Back" onPress={() => router.back()} />
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
              onPress={() => router.back()}
            />
            <HeaderBrand />
          </View>
          <View style={s.headerRight}>
            <OfflineIndicator />
          </View>
        </View>
        
        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text.primary} />
          }
        >
          {/* The project object on screen is a saved copy, not a live read.
              Say so once, at the top, rather than letting stale fields pass as
              current server state. */}
          {projectState !== 'ok' && projectFromCache && (
            <OfflineNotice mode={projectState} cachedCount={1} />
          )}

          {isDesktop ? renderDesktopTop() : (
          <>
          {/* Project Header */}
          <GlassCard style={s.projectHeader}>
            <View style={s.projectTitleRow}>
              <View style={s.projectInfo}>
                {/* PR #51 L2 — title on its own row (flexShrink so a
                    long name never pushes into the risk donut). The
                    project_class badge moved OUT of the inline title row
                    to its own line below the address — it was
                    overlapping the size-84 RiskScoreCircle. */}
                <Text style={s.projectName} numberOfLines={2}>
                  {project?.name || 'Project'}
                </Text>
                <View style={s.locationRow}>
                  <MapPin size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.locationText} numberOfLines={1} ellipsizeMode="tail">
                    {project?.location || project?.address || 'No location'}
                  </Text>
                </View>
                {project?.project_class && project.project_class !== 'regular' && (
                  <View style={[s.projectClassBadge, {
                    backgroundColor: project.project_class === 'major_b' ? semantic.neutralBg : semantic.attentionBg,
                  }]}>
                    <Text style={{
                      fontSize: 10, fontWeight: '700', letterSpacing: 0.5,
                      color: project.project_class === 'major_b' ? semantic.neutralStrong : semantic.neutralStrong,
                    }}>
                      {project.project_class === 'major_b' ? 'MAJOR B · SSM' : 'MAJOR A · SSC'}
                    </Text>
                  </View>
                )}
              </View>
              {/* Phase V2.1.2 — compact risk score gauge in the
                  project header right cluster. Self-gates on
                  v2_risk_score flag; renders nothing for v1 users.
                  Click opens RiskScoreDrawer with the full
                  breakdown. Replaces the old full-width
                  RiskScoreCard mount (deprecated). */}
              <RiskScoreCircle
                projectId={projectId}
                isAdmin={isAdmin}
                size={84}
              />
            </View>
          </GlassCard>

          {/* PR #15D — Compliance Risk forecast panel.
              Consumes GET /api/projects/{id}/prediction. Self-gates:
              renders a graceful unavailable card if the project has
              no fit yet (prediction_available=false) OR a muted error
              line if the API call fails. Lives directly below the
              header card so it sits adjacent to the RiskScoreCircle
              — the two together give the operator a same-glance view
              of "current state" (risk score) + "near-term forecast"
              (this panel). */}
          <CompliancePanel projectId={projectId} />

          {/* Stats Row */}
          <View style={s.statsRow}>
            <StatCard style={s.statCard}>
              <IconPod style={s.statIcon}>
                <Users size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              {/* "—" when the check-in read failed: unknown, never a 0 that
                  claims the site is empty. */}
              <Text style={s.statValue}>{onSiteState === 'ok' ? stats.onSiteWorkers : '—'}</Text>
              <Text style={s.statLabel}>ON SITE</Text>
            </StatCard>
            <StatCard style={s.statCard}>
              <IconPod style={s.statIcon}>
                <Wifi size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={s.statValue}>
                {nfcState !== 'ok' && nfcTags.length === 0 ? '—' : nfcTags.length}
              </Text>
              <Text style={s.statLabel}>NFC TAGS</Text>
            </StatCard>
            <StatCard style={s.statCard}>
              <IconPod style={s.statIcon}>
                <Smartphone size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={s.statValue}>{devicesState === 'ok' ? siteDevices.length : '—'}</Text>
              <Text style={s.statLabel}>DEVICES</Text>
            </StatCard>
          </View>

          {/* Quick Actions */}
          <Text style={s.sectionLabel}>QUICK ACTIONS</Text>
          <View style={s.actionsGrid}>
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <Pressable
                  key={action.title}
                  onPress={() => router.push(action.path)}
                  style={({ pressed }) => [
                    s.actionCard,
                    pressed && s.actionCardPressed,
                  ]}
                >
                  <View style={[s.actionIcon, { backgroundColor: `${action.color}20` }]}>
                    <Icon size={24} strokeWidth={1.5} color={action.color} />
                  </View>
                  <Text style={s.actionTitle}>{action.title}</Text>
                  {action.warn && (
                    <View style={s.actionWarnBadge}>
                      <AlertTriangle size={12} strokeWidth={2} color={semantic.attention} />
                      <Text style={s.actionWarnText}>No BIN</Text>
                    </View>
                  )}
                </Pressable>
              );
            })}
          </View>
          </>
          )}

          {/* V2.3 Commit 7 — Notifications inbox inline preview.
              Up to 3 most-recent unread items + a "See all →" link
              to the standalone route at /project/{id}/notifications.
              Per Q2 in inventory: Option 4C — inline section here +
              standalone route page. The unread count flows up via
              onUnreadCountChange for the section heading badge. */}
          <View style={s.sectionHeader}>
            <Text style={[s.sectionLabel, s.sectionHeaderLabel]}>NOTIFICATIONS</Text>
            {notificationsUnreadCount > 0 && (
              <View style={s.notificationsBadge}>
                <Text style={s.notificationsBadgeText}>
                  {notificationsUnreadCount > 99 ? '99+' : notificationsUnreadCount}
                </Text>
              </View>
            )}
          </View>
          <NotificationsList
            projectId={projectId}
            mode="inline"
            onUnreadCountChange={setNotificationsUnreadCount}
            onSeeAll={() => router.push(`/project/${projectId}/notifications`)}
          />

          {/* WhatsApp Status — auto-detect linked groups */}
          {whatsappActive && (
            <Pressable
              onPress={() => router.push(`/projects/${projectId}/whatsapp-groups`)}
              style={({ pressed }) => [
                { flexDirection: 'row', alignItems: 'center', padding: spacing.md,
                  borderRadius: 12, backgroundColor: 'rgba(37,211,102,0.08)', /* brand: WhatsApp - intentional, not a token */
                  borderWidth: 1, borderColor: 'rgba(37,211,102,0.2)', /* brand: WhatsApp - intentional, not a token */
                  marginBottom: spacing.md },
                pressed && { opacity: 0.7 },
              ]}
            >
              <MessageCircle size={20} strokeWidth={1.5} color="#25D366" />
              <View style={{ flex: 1, marginLeft: spacing.sm }}>
                {whatsappGroups.length > 0 ? (
                  <>
                    <Text style={{ color: '#25D366', fontSize: 13, fontWeight: '600' }}>
                      WhatsApp Connected
                    </Text>
                    <Text style={{ color: colors.text.muted, fontSize: 12, marginTop: 2 }}>
                      {whatsappGroups.length} group{whatsappGroups.length !== 1 ? 's' : ''} linked · {whatsappGroups.reduce((sum, g) => sum + (g.message_count || 0), 0)} messages
                    </Text>
                  </>
                ) : waGroupsState !== 'ok' ? (
                  /* The group list never loaded — "Link a WhatsApp Group"
                     would imply none are linked. */
                  <>
                    <Text style={{ color: colors.text.secondary, fontSize: 13, fontWeight: '600' }}>
                      WhatsApp status unavailable
                    </Text>
                    <Text style={{ color: colors.text.muted, fontSize: 12, marginTop: 2 }}>
                      {waGroupsState === 'offline'
                        ? 'Linked groups could not be fetched offline'
                        : 'Linked groups could not be read from the server'}
                    </Text>
                  </>
                ) : (
                  <>
                    <Text style={{ color: colors.text.secondary, fontSize: 13, fontWeight: '600' }}>
                      Link a WhatsApp Group
                    </Text>
                    <Text style={{ color: colors.text.muted, fontSize: 12, marginTop: 2 }}>
                      Enable messaging and daily summaries
                    </Text>
                  </>
                )}
              </View>
              <ChevronRight size={16} strokeWidth={1.5} color={colors.text.muted} />
            </Pressable>
          )}

          {/* Action Items (visible when a group has checklist extraction enabled) */}
          {whatsappActive && whatsappGroups.some((g) => g?.bot_config?.checklist_extraction_enabled) && (
            <Pressable
              onPress={() => router.push(`/projects/${projectId}/whatsapp-checklists`)}
              style={({ pressed }) => [
                { flexDirection: 'row', alignItems: 'center', padding: spacing.md,
                  borderRadius: 12, backgroundColor: 'rgba(59,130,246,0.08)',
                  borderWidth: 1, borderColor: 'rgba(59,130,246,0.2)',
                  marginBottom: spacing.md },
                pressed && { opacity: 0.7 },
              ]}
            >
              <ListChecks size={20} strokeWidth={1.5} color="#3b82f6" />
              <View style={{ flex: 1, marginLeft: spacing.sm }}>
                <Text style={{ color: '#3b82f6', fontSize: 13, fontWeight: '600' }}>
                  Action Items
                </Text>
                <Text style={{ color: colors.text.muted, fontSize: 12, marginTop: 2 }}>
                  View and complete items extracted from WhatsApp
                </Text>
              </View>
              <ChevronRight size={16} strokeWidth={1.5} color={colors.text.muted} />
            </Pressable>
          )}

          {/* RenewalAlertCard — REMOVED (mounted here and again ~110
              lines below; both are gone).

              It read /api/permit-renewals directly and rendered
              "N days until permit expires" from days_until_expiry — a
              field the v2 dispatcher adapter measures against a
              different date than the current_expiration stored beside
              it (lib/eligibility_dispatcher.py:172,181). Its mini-bars
              printed the literal word "Permit" when job_number was
              null, which the same adapter hardcodes it to be. A control
              asserting a specific thing is N days from expiring while
              unable to name which thing.

              Neither mount carried a role guard, and the route guard
              (app/_layout.jsx) confines only `cp` and `site_device` —
              so admin, owner, pm and user all saw it, twice.

              The dob_logs-sourced "Permits expiring <30d" tile above
              stays: it dedupes by raw_dob_id and renders an em dash,
              not a zero, when the read fails.

              The component file is kept, unreferenced. It comes back
              when the writer keys on a stable permit identity and the
              adapter stops nulling the fields.

              See docs/audits/permit-expiry-claim-2026-08-27.md §7. */}

          {/* NFC Tags Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={s.sectionHeader}>
                <Text style={[s.sectionLabel, s.sectionHeaderLabel]}>NFC CHECK-IN TAGS</Text>
                <Pressable
                  onPress={() => setShowAddNfcModal(true)}
                  style={s.headerAddBtn}
                  hitSlop={8}
                  accessibilityLabel="Add NFC tag"
                >
                  <Plus size={18} strokeWidth={2} color={colors.text.primary} />
                </Pressable>
              </View>
              
              {nfcTags.length > 0 ? (
                <View style={s.itemsList}>
                  {nfcTags.map((tag) => (
                    <GlassCard key={tag.tag_id} style={s.itemCard}>
                      <View style={s.itemHeader}>
                        <Wifi size={20} strokeWidth={1.5} color={tag.provisional ? semantic.attention : semantic.neutral} />
                        <View style={s.itemInfo}>
                          <Text style={s.itemId}>{tag.tag_id}</Text>
                          <Text style={s.itemLocation}>{tag.location || 'Check-In Point'}</Text>
                        </View>
                        <Pressable
                          onPress={() => handleDeleteNfcTag(tag.tag_id)}
                          style={s.deleteBtn}
                        >
                          <Trash2 size={16} color={colors.status.error} />
                        </Pressable>
                      </View>

                      {/* PROVISIONAL — a gate a CP minted in the field because
                          this project had none. There is no chip carrying this
                          id, so it is QR-ONLY, and a printed QR is permanently
                          shareable. Without this banner the emergency fix
                          silently becomes the permanent state and the admin is
                          never told. It names the id because programming a
                          sticker with THAT id is the fix — it keeps the row,
                          and every check-in already recorded against it. */}
                      {tag.provisional && (
                        <View style={s.warningBox}>
                          <Text style={s.warningText}>
                            Provisional — created on site, no physical tag. Program
                            an NFC tag with ID {tag.tag_id} to make it tappable.
                          </Text>

                          {/* The ONLY thing that clears this flag. There is no
                              dismiss: the flag means "no chip exists", so the
                              only honest way out is for a chip to exist. */}
                          {nfcSupported && (
                            <GlassButton
                              title={programmingTag === tag.tag_id
                                ? 'Hold phone near a blank tag…'
                                : 'Program a tag for this'}
                              icon={<Zap size={18} strokeWidth={1.5} color={colors.text.primary} />}
                              onPress={() => handleProgramProvisionalTag(tag.tag_id)}
                              disabled={!nfcEnabled || programmingTag !== null}
                              style={s.provisionalBtn}
                            />
                          )}
                        </View>
                      )}
                    </GlassCard>
                  ))}
                </View>
              ) : nfcState !== 'ok' ? (
                /* The tag list failed to load AND the project payload carried
                   none — "No NFC tags registered" would be a guess. */
                <OfflineNotice mode={nfcState} />
              ) : (
                <GlassCard style={s.emptyCard}>
                  <Wifi size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No NFC tags registered</Text>
                  <Text style={s.emptySubtext}>Add NFC tags for worker check-in</Text>
                </GlassCard>
              )}
            </>
          )}

          {/* Site Devices Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={s.sectionHeader}>
                <Text style={[s.sectionLabel, s.sectionHeaderLabel]}>SITE DEVICES</Text>
                <Pressable
                  onPress={() => setShowAddDeviceModal(true)}
                  style={s.headerAddBtn}
                  hitSlop={8}
                  accessibilityLabel="Add site device"
                >
                  <Plus size={18} strokeWidth={2} color={colors.text.primary} />
                </Pressable>
              </View>
              
              {siteDevices.length > 0 ? (
                <View style={s.itemsList}>
                  {siteDevices.map((device) => (
                    <GlassCard key={device.id} style={s.deviceCard}>
                      <View style={s.deviceHeader}>
                        <Smartphone size={20} strokeWidth={1.5} color={device.is_active ? semantic.verified : colors.text.muted} />
                        <View style={s.deviceInfo}>
                          <Text style={s.deviceName}>{device.device_name}</Text>
                          <Text style={s.deviceUsername}>@{device.username}</Text>
                        </View>
                        <View style={[s.deviceStatusBadge, device.is_active && s.deviceStatusActive]}>
                          <Text style={[s.deviceStatusText, device.is_active && s.deviceStatusTextActive]}>
                            {device.is_active ? 'Active' : 'Disabled'}
                          </Text>
                        </View>
                      </View>
                      <View style={s.deviceActions}>
                        <GlassButton
                          title={device.is_active ? 'Disable' : 'Enable'}
                          onPress={() => handleToggleDevice(device)}
                          style={s.toggleBtn}
                        />
                        <Pressable
                          onPress={() => handleDeleteDevice(device.id)}
                          style={s.deleteBtn}
                        >
                          <Trash2 size={16} color={colors.status.error} />
                        </Pressable>
                      </View>
                    </GlassCard>
                  ))}
                </View>
              ) : devicesState !== 'ok' ? (
                <OfflineNotice mode={devicesState} />
              ) : (
                <GlassCard style={s.emptyCard}>
                  <Smartphone size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No site devices registered</Text>
                  <Text style={s.emptySubtext}>Add devices for on-site access</Text>
                </GlassCard>
              )}
            </>
          )}

          {/* Permit Renewal Alert — REMOVED. Second of two identical
              mounts; see the note at the first one above. */}

          {/* ── FILES ────────────────────────────────────────────────────
              ONE ROW, AND THIS SCREEN IS NOT THE WRITER.

              What stood here was a whole second Dropbox surface: a free-text
              path modal, a Disconnect button, and a file list — all of it
              behind `project.dropbox_enabled && project.dropbox_folder`, two
              fields create_project writes once and nothing has written since.
              So the section rendered its empty state on every project forever,
              and the Disconnect inside it — which sent '' where the server
              reads '' as "link to the ROOT of the Dropbox scope" — was never
              reachable to fire. A dead control guarding a live trap.

              Linked-ness is `bool(dropbox_folder_path)` and the folder is
              managed on projects/[id]/files, which is the screen that renders
              the tree. This row states which it is and taps through. */}
          {canSelectSiteFiles && (
            <>
              <Text style={s.sectionLabel}>FILES</Text>
              <Pressable
                onPress={() => router.push(`/projects/${projectId}/files`)}
                style={({ pressed }) => [pressed && { opacity: 0.7 }]}
              >
                {/* THE BACKLOG, ON THE ROW THAT ALREADY GOES THERE.
                    Not a new section. The count's whole job is to be seen by
                    an admin who was not going to open Plans & Files, and a
                    row he has to scroll past a second time is a row he learns
                    to scroll past. This one already says what state the files
                    are in and already taps through; it now says how many of
                    them are waiting on him.

                    Amber tint only when something IS waiting, so the row
                    stays quiet chrome on a project with nothing outstanding.
                    A permanent badge nobody can clear is wallpaper. */}
                <GlassCard
                  style={[
                    s.dropboxRow,
                    awaitingSelection > 0 && s.dropboxRowAwaiting,
                  ]}
                >
                  <Cloud size={20} strokeWidth={1.5} color="#0061FF" />
                  <View style={s.dropboxRowInfo}>
                    <Text style={s.dropboxRowPath} numberOfLines={1}>
                      {project?.dropbox_folder_path || 'Not linked'}
                    </Text>
                    {/* NOT AN ERROR, AND THE WORDING CARRIES THAT. A file
                        waiting to be chosen is what a correct system looks
                        like the morning after a sync — the second sentence
                        says so outright, because a bare count next to an
                        amber border reads as a fault otherwise.

                        `awaitingSelection > 0` and not `awaitingSelection &&`:
                        a 0 is falsy but React Native renders the numeral, and
                        `null` (unknown) must fall through to the neutral hint
                        rather than claim a clean slate. */}
                    {awaitingSelection > 0 ? (
                      <Text style={s.dropboxRowAwaitingHint}>
                        {awaitingSelection} file{awaitingSelection === 1 ? '' : 's'} awaiting
                        selection · nothing goes to site tablets until you choose it
                      </Text>
                    ) : (
                      <Text style={s.dropboxRowHint}>
                        {project?.dropbox_folder_path
                          ? 'Open the project files'
                          : 'Choose a Dropbox folder for this project'}
                      </Text>
                    )}
                  </View>
                  {awaitingSelection > 0 && (
                    <View style={s.awaitingBadge}>
                      <Text style={s.awaitingBadgeText}>{awaitingSelection}</Text>
                    </View>
                  )}
                  <ChevronRight size={18} strokeWidth={1.5} color={colors.text.muted} />
                </GlassCard>
              </Pressable>
            </>
          )}

          {/* On-Site Workers */}
          <Text style={s.sectionLabel}>ON-SITE WORKERS</Text>
          {workersByCompany.length > 0 ? (
            workersByCompany.map((company) => (
              <GlassCard key={company.name} style={s.companyCard}>
                <View style={s.companyHeader}>
                  <Building2 size={18} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.companyName}>{company.name}</Text>
                  <View style={s.workerCount}>
                    <Text style={s.workerCountText}>{company.workers.length}</Text>
                  </View>
                </View>
                <View style={s.workerTags}>
                  {company.workers.map((worker, idx) => (
                    <View key={idx} style={s.workerTag}>
                      <Text style={s.workerTagName}>{worker.name || worker.worker_name}</Text>
                      <Text style={s.workerTagTrade}>{worker.trade || 'Worker'}</Text>
                    </View>
                  ))}
                </View>
              </GlassCard>
            ))
          ) : onSiteState !== 'ok' ? (
            /* "No workers on site" is a safety claim. It may only render when
               the check-in endpoint actually answered with an empty list. */
            <OfflineNotice
              mode={onSiteState}
              detail={
                onSiteState === 'offline'
                  ? 'Check-ins could not be fetched, so who is on site is unknown. This is NOT a confirmation that the site is empty.'
                  : 'Check-ins could not be read from the server, so who is on site is unknown.'
              }
            />
          ) : (
            <GlassCard style={s.emptyCard}>
              <Users size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyText}>No workers on site</Text>
              <Text style={s.emptySubtext}>Workers will appear here when they check in</Text>
            </GlassCard>
          )}

          {/* ── CHECKLISTS ───────────────────────────────────────────────
              THE ASSIGN PATH ALREADY EXISTS AND WORKS. app/admin/checklists
              has the full create/assign/track UI and
              POST /api/admin/checklists/{id}/assign behind it, reachable from
              the home screen tile. What was missing was any route to it from
              HERE — the one screen that tells an admin a project has no
              checklist. The empty card said "Checklists will appear here when
              assigned to this project" and named nothing that could assign
              one.

              Admin only: the endpoint behind that screen is /api/admin/*, so
              a CP standing on the same empty card gets the message without a
              button that would 403. */}
          {isAdmin ? (
            <View style={s.sectionHeader}>
              <Text style={[s.sectionLabel, s.sectionHeaderLabel]}>CHECKLISTS</Text>
              <Pressable
                onPress={() => router.push(`/admin/checklists?assignTo=${encodeURIComponent(projectId)}`)}
                style={s.headerAddBtn}
                hitSlop={8}
                accessibilityLabel="Assign a checklist to this project"
              >
                <Plus size={18} strokeWidth={2} color={colors.text.primary} />
              </Pressable>
            </View>
          ) : (
            <Text style={s.sectionLabel}>CHECKLISTS</Text>
          )}
          {loadingChecklists ? (
            <ActivityIndicator size="small" color={colors.text.primary} style={{ marginVertical: spacing.lg }} />
          ) : checklists.length > 0 ? (
            <View style={s.itemsList}>
              {checklists.map((assignment) => {
                const completedCount = assignment.completions?.filter(
                  c => c.progress?.completed === c.progress?.total
                ).length || 0;
                const totalAssigned = assignment.assigned_users?.length || 0;
                const allComplete = completedCount === totalAssigned && totalAssigned > 0;

                return (
                  <GlassCard key={assignment.id} style={s.checklistCard}>
                    <View style={s.checklistHeader}>
                      <View style={s.checklistInfo}>
                        <Text style={s.checklistTitle}>
                          {assignment.checklist?.title || 'Checklist'}
                        </Text>
                        {assignment.checklist?.description && (
                          <Text style={s.checklistDescription} numberOfLines={2}>
                            {assignment.checklist.description}
                          </Text>
                        )}
                      </View>
                      {allComplete ? (
                        <CheckCircle size={24} strokeWidth={1.5} color={semantic.verified} />
                      ) : (
                        <Clock size={24} strokeWidth={1.5} color={semantic.attention} />
                      )}
                    </View>

                    <View style={s.checklistStats}>
                      <View style={s.checklistStatItem}>
                        <Text style={s.checklistStatLabel}>Items</Text>
                        <Text style={s.checklistStatValue}>
                          {assignment.checklist?.items?.length || 0}
                        </Text>
                      </View>
                      <View style={s.checklistStatDivider} />
                      <View style={s.checklistStatItem}>
                        <Text style={s.checklistStatLabel}>Assigned</Text>
                        <Text style={s.checklistStatValue}>{totalAssigned}</Text>
                      </View>
                      <View style={s.checklistStatDivider} />
                      <View style={s.checklistStatItem}>
                        <Text style={s.checklistStatLabel}>Complete</Text>
                        <Text style={[
                          s.checklistStatValue,
                          allComplete && s.checklistStatValueComplete
                        ]}>
                          {completedCount}/{totalAssigned}
                        </Text>
                      </View>
                    </View>

                    {assignment.assigned_users && assignment.assigned_users.length > 0 && (
                      <View style={s.assignedUsers}>
                        <Text style={s.assignedUsersLabel}>Assigned to:</Text>
                        <View style={s.assignedUsersList}>
                          {assignment.assigned_users.map((user) => {
                            const userCompletion = assignment.completions?.find(
                              c => c.user_id === user.id
                            );
                            const progress = userCompletion?.progress || { completed: 0, total: 0 };
                            const isComplete = progress.completed === progress.total && progress.total > 0;

                            return (
                              <View key={user.id} style={s.assignedUserItem}>
                                <View style={s.assignedUserInfo}>
                                  <Text style={s.assignedUserName}>{user.name}</Text>
                                  <Text style={s.assignedUserProgress}>
                                    {progress.completed}/{progress.total}
                                  </Text>
                                </View>
                                {isComplete && (
                                  <CheckCircle size={14} strokeWidth={1.5} color={semantic.verified} />
                                )}
                              </View>
                            );
                          })}
                        </View>
                      </View>
                    )}
                  </GlassCard>
                );
              })}
            </View>
          ) : checklistsState !== 'ok' ? (
            <OfflineNotice mode={checklistsState} />
          ) : (
            <GlassCard style={s.emptyCard}>
              <ClipboardList size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyText}>No checklists assigned</Text>
              <Text style={s.emptySubtext}>
                {isAdmin
                  ? 'Pick a checklist and assign it to this project.'
                  : 'Checklists will appear here when assigned to this project'}
              </Text>
              {/* The dead end is felt HERE, so the way out is here too — not
                  only on the section header an admin has already scrolled
                  past. Both land on the same screen with this project
                  pre-ticked. */}
              {isAdmin && (
                <GlassButton
                  title="Assign a Checklist"
                  icon={<Plus size={16} strokeWidth={2} color={colors.text.primary} />}
                  onPress={() => router.push(`/admin/checklists?assignTo=${encodeURIComponent(projectId)}`)}
                  style={s.emptyCardBtn}
                />
              )}
            </GlassCard>
          )}
        </ScrollView>

        {/* Add NFC Tag Modal */}
        <Modal
          visible={showAddNfcModal}
          transparent
          animationType="slide"
          onRequestClose={() => {
            setShowAddNfcModal(false);
            NfcHelper.cancelNfc();
          }}
        >
          <View style={s.modalOverlay}>
            {/* Tag programming reports EVERY outcome through a toast - Scan
                Failed, Registration Failed, and the "unsupported tag api" the
                library raises. A native Modal is its own OS window, so the
                app-wide stack paints behind this sheet and an admin holding a
                phone to a tag would see nothing happen at all. Same stack,
                same component, rendered in this window. */}
            <ToastHost />
            <Pressable 
              style={s.modalBackdrop} 
              onPress={() => {
                setShowAddNfcModal(false);
                NfcHelper.cancelNfc();
              }} 
            />
            <View style={s.modalContent}>
              <GlassCard variant="modal" style={s.modalCard}>
                <View style={s.modalHeader}>
                  <Text style={s.modalTitle}>Register NFC Tag</Text>
                  <Pressable 
                    onPress={() => {
                      setShowAddNfcModal(false);
                      NfcHelper.cancelNfc();
                    }}
                  >
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={s.modalInstructions}>
                  {nfcSupported 
                    ? 'Scan a blank NFC tag to automatically program it with this project\'s check-in link.'
                    : 'NFC not available. You can register tags manually by entering the tag ID.'}
                </Text>

                <View style={s.modalForm}>
                  {nfcSupported && (
                    <>
                      <View style={s.scanSection}>
                        <View style={s.scanHeader}>
                          <Radio size={20} strokeWidth={1.5} color="#3b82f6" />
                          <Text style={s.scanTitle}>Scan NFC Tag</Text>
                        </View>

                        {!nfcEnabled && (
                          <View style={s.warningBox}>
                            <Text style={s.warningText}>
                              ⚠️ NFC is disabled. Please enable NFC in your device settings.
                            </Text>
                          </View>
                        )}

                        <GlassButton
                          title={scanningNfc ? 'Scanning... Hold phone near tag' : 'Scan & Program Tag'}
                          icon={
                            <Zap 
                              size={20} 
                              strokeWidth={1.5} 
                              color={scanningNfc ? '#4ade80' : colors.text.primary} 
                            />
                          }
                          onPress={handleScanNfcTag}
                          loading={scanningNfc}
                          disabled={!nfcEnabled || addingNfc}
                          style={[
                            s.scanButton,
                            scanningNfc && s.scanButtonActive,
                          ]}
                        />

                        <View style={s.infoBox}>
                          <Text style={s.infoText}>
                            💡 This will read the tag ID and write the check-in URL to the tag automatically.
                          </Text>
                        </View>
                      </View>

                      <View style={s.divider}>
                        <View style={s.dividerLine} />
                        <Text style={s.dividerText}>OR</Text>
                        <View style={s.dividerLine} />
                      </View>
                    </>
                  )}

                  <View style={s.manualSection}>
                    <Text style={s.manualTitle}>Manual Entry</Text>
                    
                    <View style={s.inputGroup}>
                      <Text style={s.inputLabel}>TAG ID</Text>
                      <GlassInput
                        value={nfcTagId}
                        onChangeText={setNfcTagId}
                        placeholder="e.g., 04:A1:B2:C3:D4:E5:F6"
                        editable={!scanningNfc && !addingNfc}
                      />
                      <Text style={s.inputHint}>
                        Enter the NFC tag ID manually if scanning is unavailable
                      </Text>
                    </View>

                    <GlassButton
                      title={addingNfc ? 'Adding...' : 'Add Manually'}
                      onPress={handleAddNfcTag}
                      loading={addingNfc}
                      disabled={!nfcTagId.trim() || scanningNfc}
                      style={s.manualButton}
                    />
                  </View>
                </View>
              </GlassCard>
            </View>
          </View>
        </Modal>

        {/* Add Site Device Modal */}
        <Modal
          visible={showAddDeviceModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowAddDeviceModal(false)}
        >
          <View style={s.modalOverlay}>
            <Pressable style={s.modalBackdrop} onPress={() => setShowAddDeviceModal(false)} />
            <View style={s.modalContent}>
              <GlassCard variant="modal" style={s.modalCard}>
                <View style={s.modalHeader}>
                  <Text style={s.modalTitle}>Add Site Device</Text>
                  <Pressable onPress={() => setShowAddDeviceModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={s.modalDesc}>
                  Create credentials for an on-site device (tablet or phone) to access this project.
                </Text>

                <View style={s.modalForm}>
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>USERNAME</Text>
                    <GlassInput
                      value={newDevice.username}
                      onChangeText={(val) => setNewDevice({ ...newDevice, username: val })}
                      placeholder="e.g., site-tablet-1"
                      autoCapitalize="none"
                    />
                  </View>

                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>PASSWORD</Text>
                    <GlassInput
                      value={newDevice.password}
                      onChangeText={(val) => setNewDevice({ ...newDevice, password: val })}
                      placeholder="Create a secure password"
                      secureTextEntry
                    />
                  </View>

                  <View style={s.infoBox}>
                    <Key size={16} strokeWidth={1.5} color={semantic.attention} />
                    <Text style={s.infoText}>
                      Save these credentials securely. The password cannot be recovered after creation.
                    </Text>
                  </View>

                  <GlassButton
                    title={addingDevice ? 'Creating...' : 'Create Device'}
                    onPress={handleAddDevice}
                    loading={addingDevice}
                    style={s.addButton}
                  />
                </View>
              </GlassCard>
            </View>
          </View>
        </Modal>

        {/* Credentials Display Modal */}
        <Modal
          visible={!!showCredentials}
          transparent
          animationType="fade"
          onRequestClose={() => setShowCredentials(null)}
        >
          <View style={s.modalOverlay}>
            <View style={s.credentialsModal}>
              <View style={s.successIcon}>
                <CheckCircle size={48} strokeWidth={1.5} color={semantic.verified} />
              </View>
              <Text style={s.credentialsTitle}>Device Created!</Text>
              <Text style={s.credentialsSubtitle}>
                Save these credentials for the on-site device:
              </Text>

              <View style={s.credentialsBox}>
                <View style={s.credentialRow}>
                  <Text style={s.credentialLabel}>Username</Text>
                  <Text style={s.credentialValueMono}>{showCredentials?.username}</Text>
                </View>
                <View style={s.credentialRow}>
                  <Text style={s.credentialLabel}>Password</Text>
                  <Text style={s.credentialValueMono}>{showCredentials?.password}</Text>
                </View>
              </View>

              <GlassButton
                title="Done"
                onPress={() => setShowCredentials(null)}
                style={s.doneBtn}
              />
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
  },
  loadingText: {
    color: colors.text.muted,
    fontSize: 14,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.08),
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  logoText: {
    ...typography.label,
    color: colors.text.muted,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 120,
  },
  projectHeader: {
    marginBottom: spacing.lg,
  },
  projectTitleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  projectInfo: {
    flex: 1,
    // minWidth:0 lets this column shrink below its content width so the
    // address ellipsis engages instead of wrapping per-character when
    // the size-84 risk ring takes its fixed slice of the row.
    minWidth: 0,
  },
  projectName: {
    fontSize: 28,
    fontWeight: '300',
    color: colors.text.primary,
    marginBottom: spacing.xs,
    flexShrink: 1,
  },
  // PR #51 L2 — project_class badge on its own line below the address,
  // left-aligned, so it never overlaps the risk-score donut.
  projectClassBadge: {
    alignSelf: 'flex-start',
    marginTop: spacing.sm,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  locationRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    minWidth: 0,
  },
  locationText: {
    flex: 1,
    minWidth: 0,
    fontSize: 14,
    color: colors.text.muted,
  },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
  },
  statIcon: {
    marginBottom: spacing.sm,
  },
  statValue: {
    fontSize: 28,
    fontWeight: '200',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  statLabel: {
    ...typography.label,
    fontSize: 9,
    color: colors.text.muted,
  },
  sectionLabel: {
    ...typography.label,
    color: colors.text.muted,
    // Standalone section headers (QUICK ACTIONS, ON-SITE WORKERS, CHECKLISTS)
    // get the same top breathing room as the sectionHeader rows (NOTIFICATIONS,
    // etc.) so every section header is spaced consistently below the card above.
    marginTop: spacing.lg,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.xs,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.lg,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.xs,
  },
  // sectionLabel carries its own marginBottom + paddingHorizontal for
  // standalone use; inside the centered sectionHeader row those throw off
  // vertical centering (text jams to the top) and double the left inset.
  // Strip them when the label lives in a header.
  sectionHeaderLabel: {
    // The sectionHeader row already supplies marginTop; zero it on the label
    // inside so in-header labels don't double the top margin.
    marginTop: 0,
    marginBottom: 0,
    paddingHorizontal: 0,
  },
  dropboxRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  dropboxRowInfo: {
    flex: 1,
  },
  dropboxRowPath: {
    fontSize: 15,
    color: colors.text.primary,
  },
  dropboxRowHint: {
    fontSize: 12,
    color: colors.text.muted,
    marginTop: 2,
  },
  // `attention` is amber — "needs review / advisory", per the taxonomy in
  // semanticColors.js. The same token files.jsx uses on its own unpublished
  // card, so the two screens describing the same fact do not disagree about
  // how serious it is. NOT `critical`: nothing here is an enforcement matter.
  dropboxRowAwaiting: {
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
    backgroundColor: semantic.attentionBg,
  },
  // The hint text carries `text.secondary`, not the amber. The saturated
  // state tokens are theme-insensitive and do not clear WCAG AA as body text
  // on a tinted card (semanticColors.js) — the border and the badge carry the
  // colour, the sentence carries the meaning.
  dropboxRowAwaitingHint: {
    fontSize: 12,
    color: colors.text.secondary,
    marginTop: 2,
  },
  awaitingBadge: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    paddingHorizontal: 6,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: semantic.attentionBg,
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
  },
  awaitingBadgeText: {
    color: semantic.attention,
    fontSize: 11,
    fontWeight: '700',
  },
  headerAddBtn: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  notificationsBadge: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    paddingHorizontal: 6,
    backgroundColor: 'rgba(96, 165, 250, 0.25)',
    borderWidth: 1,
    borderColor: 'rgba(96, 165, 250, 0.6)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  notificationsBadgeText: {
    color: '#60a5fa',
    fontSize: 11,
    fontWeight: '700',
  },
  actionsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  actionCard: {
    width: '47%',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
    alignItems: 'center',
    gap: spacing.sm,
  },
  actionCardPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.98 }],
  },
  actionIcon: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  actionWarnBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.full || 999,
    backgroundColor: semantic.attentionBg,
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
  },
  actionWarnText: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.3,
    color: semantic.attention,
  },
  itemsList: {
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  itemCard: {
    padding: spacing.md,
  },
  itemHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  itemInfo: {
    flex: 1,
  },
  itemId: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  itemLocation: {
    fontSize: 13,
    color: colors.text.muted,
  },
  deleteBtn: {
    padding: spacing.sm,
  },
  deviceCard: {
    padding: spacing.md,
  },
  deviceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  deviceInfo: {
    flex: 1,
  },
  deviceName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  deviceUsername: {
    fontSize: 13,
    color: colors.text.muted,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  deviceStatusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: withAlpha('#64748b', 0.2),
    borderRadius: borderRadius.full,
  },
  deviceStatusActive: {
    backgroundColor: semantic.verifiedBg,
  },
  deviceStatusText: {
    fontSize: 11,
    fontWeight: '500',
    color: colors.text.muted,
  },
  deviceStatusTextActive: {
    color: semantic.verified,
  },
  deviceActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
    paddingTop: spacing.md,
  },
  toggleBtn: {
    flex: 1,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  emptyText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.muted,
  },
  emptyCardBtn: {
    marginTop: spacing.lg,
  },
  emptySubtext: {
    fontSize: 13,
    color: colors.text.subtle,
  },
  companyCard: {
    marginBottom: spacing.md,
  },
  companyHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  companyName: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerCount: {
    backgroundColor: colors.glass.background,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
  },
  workerCountText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.primary,
  },
  workerTags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  workerTag: {
    backgroundColor: withAlpha('#ffffff', 0.05),
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  workerTagName: {
    fontSize: 13,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerTagTrade: {
    fontSize: 11,
    color: colors.text.muted,
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: withAlpha('#000000', 0.85),
  },
  modalContent: {
    padding: spacing.lg,
  },
  modalCard: {
    maxWidth: 500,
    alignSelf: 'center',
    width: '100%',
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  modalDesc: {
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.lg,
  },
  modalForm: {
    gap: spacing.md,
  },
  inputGroup: {
    gap: spacing.sm,
  },
  inputLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  infoBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    backgroundColor: semantic.attentionBg,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
  },
  infoText: {
    flex: 1,
    fontSize: 13,
    color: semantic.attention,
    lineHeight: 18,
  },
  addButton: {
    marginTop: spacing.sm,
  },
  credentialsModal: {
    // Opaque AND theme-aware (the surface.menu value). Was a hardcoded
    // '#1a1a2e': the text here uses colors.text.*, which is DARK in the light
    // theme, so "Device Created!" and the labels were dark-on-dark.
    backgroundColor: colors.background.middle,
    borderRadius: borderRadius.xxl,
    padding: spacing.xl,
    maxWidth: 400,
    alignSelf: 'center',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.glass.border,
    margin: spacing.lg,
  },
  successIcon: {
    marginBottom: spacing.lg,
  },
  credentialsTitle: {
    fontSize: 24,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.sm,
  },
  credentialsSubtitle: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    marginBottom: spacing.lg,
  },
  credentialsBox: {
    width: '100%',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    marginBottom: spacing.lg,
  },
  credentialRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  credentialLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  credentialValueBold: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  credentialValueMono: {
    fontSize: 14,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    color: colors.state.verified,
  },
  doneBtn: {
    width: '100%',
  },
  modalInstructions: {
    fontSize: 14,
    color: colors.text.muted,
    lineHeight: 20,
    marginBottom: spacing.lg,
  },
  inputHint: {
    fontSize: 12,
    color: colors.text.subtle,
    marginTop: spacing.xs,
  },
  scanSection: {
    marginBottom: spacing.lg,
  },
  scanHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  scanTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  warningBox: {
    backgroundColor: semantic.attentionBg,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
    marginBottom: spacing.md,
  },
  warningText: {
    fontSize: 13,
    color: semantic.attention,
    lineHeight: 18,
  },
  provisionalBtn: {
    marginTop: spacing.md,
  },
  scanButton: {
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderColor: 'rgba(59, 130, 246, 0.3)',
  },
  scanButtonActive: {
    backgroundColor: semantic.verifiedBg,
    borderColor: semantic.verifiedBorder,
  },
  divider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: spacing.lg,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.glass.border,
  },
  dividerText: {
    ...typography.label,
    fontSize: 11,
    color: colors.text.subtle,
    paddingHorizontal: spacing.md,
  },
  manualSection: {
    // manual section styles
  },
  manualTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.md,
  },
  manualButton: {
    marginTop: spacing.sm,
  },
  checklistCard: {
    marginBottom: spacing.md,
    padding: spacing.lg,
  },
  checklistHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  checklistInfo: {
    flex: 1,
    marginRight: spacing.md,
  },
  checklistTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  checklistDescription: {
    fontSize: 13,
    color: colors.text.secondary,
    lineHeight: 18,
  },
  checklistStats: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: withAlpha('#ffffff', 0.03),
    borderRadius: borderRadius.md,
  },
  checklistStatItem: {
    flex: 1,
    alignItems: 'center',
  },
  checklistStatLabel: {
    fontSize: 10,
    color: colors.text.muted,
    marginBottom: spacing.xs,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  checklistStatValue: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
  },
  checklistStatValueComplete: {
    color: semantic.verified,
  },
  checklistStatDivider: {
    width: 1,
    height: 28,
    backgroundColor: colors.glass.border,
  },
  assignedUsers: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
  },
  assignedUsersLabel: {
    fontSize: 11,
    color: colors.text.muted,
    marginBottom: spacing.sm,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  assignedUsersList: {
    gap: spacing.sm,
  },
  assignedUserItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
  },
  assignedUserInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    flex: 1,
  },
  assignedUserName: {
    fontSize: 13,
    color: colors.text.primary,
  },
  assignedUserProgress: {
    fontSize: 11,
    color: colors.text.muted,
  },
});
}
