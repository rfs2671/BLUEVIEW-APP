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
import { useRouter, useLocalSearchParams } from 'expo-router';
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
  Folder,
  FileText,
  Link as LinkIcon,
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
import RenewalAlertCard from '../../src/components/RenewalAlertCard';
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
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { useProjects } from '../../src/hooks/useProjects';
import { useCheckIns } from '../../src/hooks/useCheckIns';
import OfflineIndicator from '../../src/components/OfflineIndicator';
import { projectsAPI, checkinsAPI, checklistsAPI, whatsappAPI } from '../../src/utils/api';
import apiClient from '../../src/utils/api';
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

// Dropbox API for project-specific integration
const dropboxAPI = {
  linkFolder: async (projectId, folderPath) => {
    const response = await apiClient.post(`/api/projects/${projectId}/link-dropbox`, {
      folder_path: folderPath,
    });
    return response.data;
  },
  getFiles: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/dropbox-files`);
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
  const [nfcSupported, setNfcSupported] = useState(false);
  const [nfcEnabled, setNfcEnabled] = useState(false);
  const [nfcTags, setNfcTags] = useState([]);

  // Site devices management
  const [siteDevices, setSiteDevices] = useState([]);
  const [showAddDeviceModal, setShowAddDeviceModal] = useState(false);
  const [newDevice, setNewDevice] = useState({
    device_name: '',
    username: '',
    password: '',
  });
  const [addingDevice, setAddingDevice] = useState(false);
  const [showCredentials, setShowCredentials] = useState(null);

  // Dropbox integration
  const [showDropboxModal, setShowDropboxModal] = useState(false);
  const [dropboxFolder, setDropboxFolder] = useState('');
  const [linkingDropbox, setLinkingDropbox] = useState(false);
  const [dropboxFiles, setDropboxFiles] = useState([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
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
        if (!cancelled) setDobExposure(row);
      } catch (_e) {
        if (!cancelled) setDobExposure(null);
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
      let projectData = await getProjectById(projectId);
      if (!projectData) {
        try {
          projectData = await projectsAPI.getById(projectId);
        } catch (e) {
          console.error('Failed to fetch project from API:', e);
        }
      }
      setProject(projectData);

        try {
          const tags = await projectsAPI.getNfcTags(projectId);
          setNfcTags(Array.isArray(tags) ? tags : []);
        } catch (e) {
          setNfcTags(projectData?.nfc_tags || []);
        }

      // Fetch site devices for this project
      if (isAdmin) {
        try {
          const devices = await siteDevicesAPI.getByProject(projectId);
          setSiteDevices(Array.isArray(devices) ? devices : []);
        } catch (e) {
          setSiteDevices([]);
        }

        // Fetch Dropbox files if connected
        if (projectData.dropbox_enabled && projectData.dropbox_folder) {
          fetchDropboxFiles();
        }
      }

      // Fetch WhatsApp status
      try {
        const waStatus = await whatsappAPI.getStatus();
        const isActive = waStatus?.company_active === true;
        setWhatsappActive(isActive);
        if (isActive) {
          const groups = await whatsappAPI.getGroups(projectId).catch(() => []);
          setWhatsappGroups(Array.isArray(groups) ? groups : []);
        }
      } catch (e) {
        setWhatsappActive(false);
      }

      // Fetch active check-ins for this project
      try {
        const workers = await getActiveCheckIns(projectId);
        
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
      } catch (e) {
        setStats({ onSiteWorkers: 0, subcontractors: 0, subcontractorCount: 0 });
        setWorkersByCompany([]);
      }
    } catch (error) {
      console.error('Failed to fetch project:', error);
      toast.error('Error', 'Could not load project details');
    } finally {
      fetchChecklists();
      setLoading(false);
      setRefreshing(false);
    }
  };

  const fetchDropboxFiles = async () => {
    setLoadingFiles(true);
    try {
      const result = await dropboxAPI.getFiles(projectId);
      // The endpoint returns a BARE ARRAY (not {files:[...]}); reading
      // result.files left this [] on every project. Match the Array.isArray
      // pattern the other file consumers use.
      setDropboxFiles(Array.isArray(result) ? result : []);
    } catch (error) {
      console.error('Failed to fetch Dropbox files:', error);
      setDropboxFiles([]);
    } finally {
      setLoadingFiles(false);
    }
  };

  const fetchChecklists = async () => {
    setLoadingChecklists(true);
    try {
      const data = await checklistsAPI.getByProject(projectId);
      setChecklists(data);
    } catch (error) {
      console.error('Failed to fetch checklists:', error);
      setChecklists([]);
    } finally {
      setLoadingChecklists(false);
    }
  };
  
  const onRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const handleScanNfcTag = async () => {
    if (!nfcEnabled) {
      toast.error('NFC Disabled', 'Please enable NFC in your device settings');
      return;
    }
    setScanningNfc(true);
    toast.info('Ready to Scan', 'Hold your phone near the NFC tag...');
    try {
      const result = await NfcHelper.registerNfcTag(
        projectId,
        'https://levelog.com'
      );
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
      const result = await siteDevicesAPI.create(projectId, newDevice);
      toast.success('Created', 'Site device created successfully');
      
      setShowCredentials({
        ...result,
        password: newDevice.password,
      });

      setNewDevice({ device_name: '', username: '', password: '' });
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

  const handleLinkDropbox = async () => {
    if (!dropboxFolder.trim()) {
      toast.error('Error', 'Please enter a Dropbox folder path');
      return;
    }

    setLinkingDropbox(true);
    try {
      await dropboxAPI.linkFolder(projectId, dropboxFolder);
      toast.success('Connected', 'Dropbox folder linked successfully');
      setDropboxFolder('');
      setShowDropboxModal(false);
      await fetchData();
    } catch (error) {
      console.error('Failed to link Dropbox:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not link Dropbox folder');
    } finally {
      setLinkingDropbox(false);
    }
  };

  const handleDisconnectDropbox = () => {
    const confirmDisconnect = async () => {
      try {
        await dropboxAPI.linkFolder(projectId, '');
        toast.success('Disconnected', 'Dropbox folder unlinked');
        setDropboxFiles([]);
        await fetchData();
      } catch (error) {
        console.error('Failed to disconnect Dropbox:', error);
        toast.error('Error', 'Could not disconnect Dropbox');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Disconnect Dropbox folder from this project?')) {
        confirmDisconnect();
      }
    } else {
      Alert.alert('Disconnect Dropbox', 'Remove Dropbox folder link from this project?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Disconnect', style: 'destructive', onPress: confirmDisconnect },
      ]);
    }
  };

  // No valid BIN flag — mirrors backend _is_placeholder_bin: a BIN must
  // be 7 digits, borough-prefixed (1–5), and not a X000000 placeholder.
  // When false, DOB scans silently return nothing, so we flag it on the
  // DOB Compliance action card (the dob-logs screen has the full
  // "No BIN on File" remediation flow).
  const binStr = String(project?.nyc_bin || '').trim();
  const hasValidBin = /^[1-5]\d{6}$/.test(binStr) && binStr.slice(1) !== '000000';

  const quickActions = [
    { title: 'Plans & Files', icon: FileText, path: `/projects/${projectId}/construction-plans`, color: '#3b82f6' },
    { title: 'Daily Log', icon: ClipboardList, path: `/daily-log?projectId=${projectId}`, color: '#8b5cf6' },
    // MR.14 commit 3 — v1 monitoring product surface. Activity feed
    // sits ABOVE the legacy DOB Compliance entry; both are reachable.
    { title: 'Activity', icon: Activity, path: `/project/${projectId}/activity`, color: '#0ea5e9' },
    { title: 'DOB Compliance', icon: Shield, path: `/project/${projectId}/dob-logs`, color: semantic.neutral, warn: !hasValidBin },
    { title: 'Report Settings', icon: Settings, path: `/project/${projectId}/report-settings`, color: '#f59e0b' },
    { title: 'Check-in Trades', icon: HardHat, path: `/project/${projectId}/trades`, color: semantic.neutral },
  ];

  // ── Desktop 2-column triage layout. Replaces the mobile header + stats +
  //    quick-actions block; the lower detail sections (notifications, NFC,
  //    devices, files) render unchanged below for both. Risk gauge is hidden
  //    on desktop (mobile keeps it); the drawer + mobile path are untouched.
  const renderDesktopTop = () => {
    const addr = project?.address || project?.location || '';
    const title = project?.name || addr || 'Project';
    const showAddr = addr && addr !== title;           // address ONCE, no dup
    const neverSynced = !project?.first_poll_completed_at;
    const exp = dobExposure || {};
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
            <View style={deskStyles.tileRow}>
              <DeskTile loading={dobExpLoading} value={exp.open_violations} label="Open violations" token={semantic.criticalText} />
              <DeskTile loading={dobExpLoading} value={exp.permits_expiring} label="Permits expiring <30d" token={semantic.attention} />
              <DeskTile loading={dobExpLoading} value={exp.open_complaints} label="Open complaints" token={semantic.attention} />
            </View>

            <CompliancePanel projectId={projectId} />

            <Text style={[deskStyles.sectionLabel, { color: tokenText.secondary }]}>ON SITE</Text>
            <View style={deskStyles.tileRow}>
              <DeskTile value={stats.onSiteWorkers} label="On site" token={tokenText.primary} />
              <DeskTile value={nfcTags.length} label="NFC tags" token={tokenText.primary} />
              <DeskTile value={siteDevices.length} label="Devices" token={tokenText.primary} />
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
        <SafeAreaView style={s.container}>
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
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <Text style={s.loadingText}>Project not found</Text>
            <GlassButton title="Go Back" onPress={() => router.back()} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }
  const isDropboxConnected = project?.dropbox_enabled && project?.dropbox_folder;

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
                      color: project.project_class === 'major_b' ? semantic.neutralStrong : '#f59e0b',
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
              <Text style={s.statValue}>{stats.onSiteWorkers}</Text>
              <Text style={s.statLabel}>ON SITE</Text>
            </StatCard>
            <StatCard style={s.statCard}>
              <IconPod style={s.statIcon}>
                <Wifi size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={s.statValue}>{nfcTags.length}</Text>
              <Text style={s.statLabel}>NFC TAGS</Text>
            </StatCard>
            <StatCard style={s.statCard}>
              <IconPod style={s.statIcon}>
                <Smartphone size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={s.statValue}>{siteDevices.length}</Text>
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
                      <AlertTriangle size={12} strokeWidth={2} color="#f59e0b" />
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

          <RenewalAlertCard projectId={projectId} />

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
                        <Wifi size={20} strokeWidth={1.5} color={semantic.neutral} />
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
                    </GlassCard>
                  ))}
                </View>
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
              ) : (
                <GlassCard style={s.emptyCard}>
                  <Smartphone size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No site devices registered</Text>
                  <Text style={s.emptySubtext}>Add devices for on-site access</Text>
                </GlassCard>
              )}
            </>
          )}
          
          {/* Permit Renewal Alert */}
          <RenewalAlertCard projectId={projectId} />
          
          {/* Dropbox Integration Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={s.sectionHeader}>
                <Text style={[s.sectionLabel, s.sectionHeaderLabel]}>DROPBOX INTEGRATION</Text>
                {!isDropboxConnected && (
                  <GlassButton
                    title="Link Folder"
                    icon={<LinkIcon size={16} color={colors.text.primary} />}
                    onPress={() => setShowDropboxModal(true)}
                  />
                )}
              </View>
              
              {isDropboxConnected ? (
                <View style={s.itemsList}>
                  <GlassCard style={s.dropboxCard}>
                    <View style={s.dropboxHeader}>
                      <Cloud size={20} strokeWidth={1.5} color="#0061FF" />
                      <View style={s.dropboxInfo}>
                        <Text style={s.dropboxTitle}>Connected Folder</Text>
                        <Text style={s.dropboxPath}>{project.dropbox_folder}</Text>
                      </View>
                      <Pressable
                        onPress={handleDisconnectDropbox}
                        style={s.disconnectBtn}
                      >
                        <Text style={s.disconnectText}>Disconnect</Text>
                      </Pressable>
                    </View>

                    {loadingFiles ? (
                      <View style={s.filesLoading}>
                        <ActivityIndicator size="small" color={colors.text.primary} />
                        <Text style={s.filesLoadingText}>Loading files...</Text>
                      </View>
                    ) : dropboxFiles.length > 0 ? (
                      <View style={s.filesList}>
                        <Text style={s.filesHeader}>FILES ({dropboxFiles.length})</Text>
                        {dropboxFiles.map((file, idx) => (
                          <View key={idx} style={s.fileRow}>
                            <FileText size={16} strokeWidth={1.5} color={colors.text.muted} />
                            <Text style={s.fileName} numberOfLines={1}>{file.name}</Text>
                          </View>
                        ))}
                      </View>
                    ) : (
                      <View style={s.noFiles}>
                        <Text style={s.noFilesText}>No files in this folder</Text>
                      </View>
                    )}
                  </GlassCard>
                </View>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <Cloud size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyText}>No Dropbox folder linked</Text>
                  <Text style={s.emptySubtext}>Link a Dropbox folder to share project documents</Text>
                </GlassCard>
              )}
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
          ) : (
            <GlassCard style={s.emptyCard}>
              <Users size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyText}>No workers on site</Text>
              <Text style={s.emptySubtext}>Workers will appear here when they check in</Text>
            </GlassCard>
          )}

          {/* Checklists Section */}
          <Text style={s.sectionLabel}>CHECKLISTS</Text>
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
                        <Clock size={24} strokeWidth={1.5} color="#f59e0b" />
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
          ) : (
            <GlassCard style={s.emptyCard}>
              <ClipboardList size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyText}>No checklists assigned</Text>
              <Text style={s.emptySubtext}>Checklists will appear here when assigned to this project</Text>
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
                    <Text style={s.inputLabel}>DEVICE NAME</Text>
                    <GlassInput
                      value={newDevice.device_name}
                      onChangeText={(val) => setNewDevice({ ...newDevice, device_name: val })}
                      placeholder="e.g., Site Tablet 1"
                    />
                  </View>

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
                    <Key size={16} strokeWidth={1.5} color="#f59e0b" />
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

        {/* Link Dropbox Folder Modal */}
        <Modal
          visible={showDropboxModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowDropboxModal(false)}
        >
          <View style={s.modalOverlay}>
            <Pressable style={s.modalBackdrop} onPress={() => setShowDropboxModal(false)} />
            <View style={s.modalContent}>
              <GlassCard variant="modal" style={s.modalCard}>
                <View style={s.modalHeader}>
                  <Text style={s.modalTitle}>Link Dropbox Folder</Text>
                  <Pressable onPress={() => setShowDropboxModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={s.modalDesc}>
                  Enter the path to your Dropbox folder containing project documents.
                </Text>

                <View style={s.modalForm}>
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>FOLDER PATH</Text>
                    <GlassInput
                      value={dropboxFolder}
                      onChangeText={setDropboxFolder}
                      placeholder="/Projects/Downtown Building"
                    />
                  </View>

                  <View style={s.infoBox}>
                    <Folder size={16} strokeWidth={1.5} color="#0061FF" />
                    <Text style={s.infoText}>
                      All users you create will be able to view files from this folder.
                    </Text>
                  </View>

                  <GlassButton
                    title={linkingDropbox ? 'Linking...' : 'Link Folder'}
                    onPress={handleLinkDropbox}
                    loading={linkingDropbox}
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
                  <Text style={s.credentialLabel}>Device</Text>
                  <Text style={s.credentialValueBold}>{showCredentials?.device_name}</Text>
                </View>
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
    color: '#f59e0b',
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
  dropboxCard: {
    padding: spacing.md,
  },
  dropboxHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  dropboxInfo: {
    flex: 1,
  },
  dropboxTitle: {
    fontSize: 13,
    color: colors.text.muted,
    marginBottom: 2,
  },
  dropboxPath: {
    fontSize: 14,
    fontWeight: '500',
    color: '#0061FF',
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  disconnectBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  disconnectText: {
    fontSize: 13,
    color: colors.status.error,
  },
  filesLoading: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.md,
  },
  filesLoadingText: {
    fontSize: 13,
    color: colors.text.muted,
  },
  filesList: {
    gap: spacing.xs,
  },
  filesHeader: {
    ...typography.label,
    fontSize: 10,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  fileRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  fileName: {
    flex: 1,
    fontSize: 13,
    color: colors.text.primary,
  },
  noFiles: {
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  noFilesText: {
    fontSize: 13,
    color: colors.text.muted,
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
    color: '#f59e0b',
    lineHeight: 18,
  },
  addButton: {
    marginTop: spacing.sm,
  },
  credentialsModal: {
    backgroundColor: '#1a1a2e',
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
    color: '#4ade80',
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
    color: '#f59e0b',
    lineHeight: 18,
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
