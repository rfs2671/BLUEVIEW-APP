import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  Modal,
  KeyboardAvoidingView,
  Platform,
  Image,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Calendar,
  Sun,
  Cloud,
  CloudRain,
  Wind,
  Plus,
  Users,
  Check,
  X,
  ChevronDown,
  FileText,
  Building2,
  ShieldCheck,
  HardHat,
  AlertTriangle,
  ClipboardList,
  History,
  CheckCircle,
  XCircle,
  MinusCircle,
  PenTool,
  Clock,
  Eye,
  CloudOff,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod, GlassListItem } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import GlassInput from '../src/components/GlassInput';
import { GlassSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import SignaturePad from '../src/components/SignaturePad';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { csRegistrationAPI } from '../src/utils/api';
import { sentenceCase } from '../src/utils/textFormat';
import { useProjects } from '../src/hooks/useProjects';
import { useDailyLogs } from '../src/hooks/useDailyLogs';
import OfflineIndicator from '../src/components/OfflineIndicator';
import OfflineNotice from '../src/components/OfflineNotice';
import {
  draftKey,
  readDraft,
  writeDraft,
  setDraftBackendId,
  markPending,
  clearPending,
} from '../src/utils/logbookDrafts';
import { isOfflineError, settleFetch } from '../src/utils/offlineState';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { semantic, chrome, withAlpha } from '../src/styles/semanticColors';
import { useTheme } from '../src/context/ThemeContext';
import HeaderBrand from '../src/components/HeaderBrand';
import { easternToday } from '../src/utils/dates';

const weatherOptions = [
  { value: 'sunny', label: 'Sunny', icon: Sun },
  { value: 'cloudy', label: 'Cloudy', icon: Cloud },
  { value: 'rainy', label: 'Rainy', icon: CloudRain },
  { value: 'windy', label: 'Windy', icon: Wind },
];

// PR #48 — the manual phase dropdown was removed. Project phase is now
// inferred weekly by Gemini (lib/ai/phase_inference.py) from the daily
// log fields below; GCs no longer maintain it by hand. The backend
// DailyLogCreate.phase field + WatermelonDB column remain for
// backward-compat on the read path (existing logs with manual phase
// data still resolve).

const SAFETY_CHECKLIST_ITEMS = [
  { id: 'fall_protection', label: 'Fall Protection' },
  { id: 'scaffolding', label: 'Scaffolding' },
  { id: 'ppe', label: 'PPE (Personal Protective Equipment)' },
  { id: 'hazards', label: 'Hazard Identification' },
  { id: 'base_conditions', label: 'Base Conditions' },
];

// Offline draft identity for this screen. One draft per (project, day), which
// is the same natural key the backend dedups on — see src/utils/logbookDrafts.js.
const LOG_TYPE = 'daily_log';

// The screen has always keyed "today" off the UTC date slice; keep that exact
// convention so the draft key and the server lookup agree with existing rows.
const todayISO = () => easternToday();

export default function DailyLogScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
  const toast = useToast();

  const [activeTab, setActiveTab] = useState('previous'); 
  const [loading, setLoading] = useState(true);
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [allLogs, setAllLogs] = useState([]);
  const [existingLog, setExistingLog] = useState(null);
  const [saving, setSaving] = useState(false);
  const [selectedPreviousLog, setSelectedPreviousLog] = useState(null);
  const [csLicenseNumber, setCsLicenseNumber] = useState('');
  // OFFLINE vs EMPTY: 'ok' | 'offline' | 'error' for the project-logs read. Only
  // 'ok' may render the "No Logs Found" empty state.
  const [logsFetchState, setLogsFetchState] = useState('ok');
  // Server id for TODAY's log, learned either from the server read or from the
  // local draft. This is what makes a save after a FAILED load update the
  // existing document instead of creating a duplicate for the same day.
  const [backendLogId, setBackendLogId] = useState(null);
  // True when a signed log lives on this device but has not landed on the server.
  const [draftPending, setDraftPending] = useState(false);
  // THE OTHER REASON. `draftPending` means "on this device, not on the
  // server" — a queued push, work that is safe. This one is its opposite: the
  // device is not storing the draft at all. Two problems, two fixes, and the
  // banners below say which one he has.
  //
  // Sticky, and not a toast: he may have walked away. Cleared only by a later
  // write that succeeds.
  const [localSaveFailed, setLocalSaveFailed] = useState(false);

  const [formData, setFormData] = useState({
    weather: 'sunny',
    notes: '',
    worker_count: 0,
    subcontractor_cards: [],
    safety_checklist: {},
    corrective_actions: '',
    corrective_actions_na: false,
    incident_log: '',
    incident_log_na: false,
    superintendent_name: '',
    superintendent_signature: null,
    competent_person_name: '',
    competent_person_signature: null,
  });

  const isAdmin = user?.role === 'admin';
  const { projects: projectsList, loading: projectsLoading } = useProjects();
  const { dailyLogs, loading: logsLoading, createDailyLog, updateDailyLog, getProjectLogs } = useDailyLogs(selectedProject?._id || selectedProject?.id);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject) {
      setActiveTab('today');
      setSelectedProject(siteProject);
      fetchLogsForProject(siteProject.id);
    } else if (isAuthenticated && !siteMode) {
      setActiveTab('previous');
      fetchProjects();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  // Autosave EVERY field change (and both signatures) to the LOCAL draft.
  // Debounced so typing doesn't thrash AsyncStorage, and it makes no network
  // call — this is what lets a superintendent fill and sign the whole log in a
  // dead zone, quit the app, and come back to exactly what they entered.
  // `status` is deliberately omitted so an autosave never downgrades a
  // submitted log back to 'draft'.
  useEffect(() => {
    if (loading) return undefined;
    const projectId = getProjectId(selectedProject);
    if (!projectId) return undefined;
    const t = setTimeout(() => {
      // BOTH FAILURE MODES. The boolean was discarded and a throw fell into the
      // same empty catch. Not a toast on every save — a superintendent typing
      // all afternoon would stop seeing it — it drives the banner instead.
      writeDraft(
        draftKey({ projectId, logType: LOG_TYPE, date: todayISO() }),
        {
          data: { ...formData },
          cp_signature: formData.competent_person_signature,
          cp_name: formData.competent_person_name,
        },
      )
        .then((_ok) => setLocalSaveFailed(!_ok))
        .catch(() => setLocalSaveFailed(true));
    }, 800);
    return () => clearTimeout(t);
  }, [loading, selectedProject, formData]);

  const fetchProjects = async () => {
    setLoading(true);
    try {
      setProjects(projectsList);
      if (projectsList.length > 0) {
        const firstProject = projectsList[0];
        setSelectedProject(firstProject);
        await fetchLogsForProject(firstProject._id || firstProject.id);
      }
    } catch (error) {
      console.error('Failed to fetch projects:', error);
      toast.error('Load Error', 'Could not load projects');
    } finally {
      setLoading(false);
    }
  };

  const fetchAndPrefillCS = async (projectId) => {
    // Auto-fill superintendent from CS registration. Non-blocking —
    // CS lookup failure must never break the daily log flow.
    const r = await settleFetch(() => csRegistrationAPI.getForProject(projectId));
    if (r.status !== 'ok') {
      // OFFLINE vs EMPTY: a failed lookup is NOT "no CS registered". Leave the
      // name and licence badge exactly as they are rather than blanking them,
      // which would read as "this project has no Construction Superintendent".
      console.warn('CS lookup unavailable (non-blocking):', r.status, r.error?.message);
      return;
    }
    const csData = r.data;
    if (csData?.registered && csData.full_name) {
      // Only pre-fill if the field is empty — do not overwrite a
      // superintendent who has already signed today's log.
      setFormData((prev) => ({
        ...prev,
        superintendent_name: prev.superintendent_name || csData.full_name,
      }));
      setCsLicenseNumber(csData.license_number || '');
    } else {
      setCsLicenseNumber('');
    }
  };

  const fetchLogsForProject = async (projectId) => {
    const today = todayISO();
    const key = draftKey({ projectId, logType: LOG_TYPE, date: today });
    try {
      // 1) CACHE-FIRST. The on-device draft is the source of truth for TODAY's
      //    in-progress log and is read before any network call, so an offline
      //    superintendent reopens exactly what they typed and signed.
      const draft = await readDraft(key);
      if (draft) {
        populateFormFromDraft(draft.data);
        setBackendLogId(draft.backend_id || null);
        // A submitted draft with no server id has never landed upstream.
        setDraftPending(draft.status === 'submitted' && !draft.backend_id);
      } else {
        setDraftPending(false);
      }

      // 2) Best-effort server read, settled so a dead zone can never be
      //    mistaken for "this project has no logs".
      const r = await getProjectLogs(projectId);
      if (r.status === 'ok') {
        setLogsFetchState('ok');
        setAllLogs(r.data);
        const todayLog = r.data.find((l) => l.date === today) || null;
        setExistingLog(todayLog);
        if (todayLog) {
          // Bind the server id into the draft so the NEXT save updates this
          // document rather than creating a second log for the same day.
          const serverId = todayLog.id || todayLog._id || null;
          setBackendLogId(serverId);
          if (serverId) {
            await setDraftBackendId(key, serverId);
            setDraftPending(false);
          }
          // The local draft is the NEWER, unsynced copy — it wins. Only hydrate
          // the form from the server when there is nothing on this device.
          if (!draft) populateFormFromLog(todayLog);
        } else if (!draft) {
          resetForm();
        }
      } else {
        // OFFLINE / error: keep whatever logs we already have on screen and
        // record the state so the list renders <OfflineNotice/> instead of the
        // "No Logs Found" empty card. Never wipe a draft-backed form here.
        setLogsFetchState(r.status);
        if (!draft) {
          setExistingLog(null);
          resetForm();
        }
      }
      // Always fetch CS — fills the superintendent name if the form is
      // fresh, and gives us the license number for the badge regardless.
      await fetchAndPrefillCS(projectId);
    } catch (error) {
      console.error('Failed to fetch logs:', error);
      // Do NOT setAllLogs([]) — an exception here is not evidence of no logs.
      setLogsFetchState(isOfflineError(error) ? 'offline' : 'error');
    } finally {
      setLoading(false);
    }
  };

  const populateFormFromLog = (log) => {
    setFormData({
      weather: log.weather || 'sunny',
      notes: log.notes || '',
      worker_count: log.worker_count || 0,
      subcontractor_cards: log.subcontractor_cards || [],
      safety_checklist: log.safety_checklist || {},
      corrective_actions: log.corrective_actions || '',
      corrective_actions_na: log.corrective_actions_na || false,
      incident_log: log.incident_log || '',
      incident_log_na: log.incident_log_na || false,
      superintendent_name: log.superintendent_signature?.signer_name || '',
      superintendent_signature: log.superintendent_signature || null,
      competent_person_name: log.competent_person_signature?.signer_name || '',
      competent_person_signature: log.competent_person_signature || null,
    });
  };

  // Rehydrate from the local draft. The draft stores the form verbatim, so we
  // copy back only known form keys and only when they are defined — a partial
  // or older draft can never blank a field the form already has.
  const populateFormFromDraft = (data) => {
    if (!data || typeof data !== 'object') return;
    setFormData((prev) => {
      const next = { ...prev };
      Object.keys(prev).forEach((k) => {
        if (data[k] !== undefined) next[k] = data[k];
      });
      return next;
    });
  };

  const resetForm = () => {
    setFormData({
      weather: 'sunny',
      notes: '',
      worker_count: 0,
      subcontractor_cards: [],
      safety_checklist: {},
      corrective_actions: '',
      corrective_actions_na: false,
      incident_log: '',
      incident_log_na: false,
      superintendent_name: '',
      superintendent_signature: null,
      competent_person_name: '',
      competent_person_signature: null,
    });
  };

  const handleProjectChange = async (project) => {
    setSelectedProject(project);
    setShowProjectPicker(false);
    setLoading(true);
    await fetchLogsForProject(project._id || project.id);
  };

  const handleSafetyCheckChange = (itemId, status) => {
    const now = new Date().toISOString();
    const userName = user?.full_name || user?.name || user?.device_name || 'Unknown';
    
    setFormData((prev) => ({
      ...prev,
      safety_checklist: {
        ...prev.safety_checklist,
        [itemId]: {
          status,
          checked_by: userName,
          checked_at: now,
        },
      },
    }));
  };

  const createAuditTrail = () => {
    return {
      entered_by: user?.full_name || user?.name || user?.device_name || 'Unknown',
      entered_by_id: user?.id,
      entered_at: new Date().toISOString(),
    };
  };

  const handleSubmit = async () => {
    if (!selectedProject) {
      toast.warning('Select Project', 'Please select a project first');
      return;
    }

    setSaving(true);
    const projectId = getProjectId(selectedProject);
    const today = todayISO();
    const key = draftKey({ projectId, logType: LOG_TYPE, date: today });
    // The id we already know for today — from the server read OR, when that
    // read failed, from the local draft. Without this a save after a failed
    // load would POST a duplicate log for the same day.
    const knownId = existingLog?.id || existingLog?._id || backendLogId || null;
    try {
      const logData = {
        project_id: projectId,
        date: today,
        weather: formData.weather,
        notes: formData.notes,
        worker_count: parseInt(formData.worker_count) || 0,
        subcontractor_cards: formData.subcontractor_cards,
        safety_checklist: formData.safety_checklist,
        corrective_actions: formData.corrective_actions,
        corrective_actions_na: formData.corrective_actions_na,
        corrective_actions_audit: formData.corrective_actions ? createAuditTrail() : null,
        incident_log: formData.incident_log,
        incident_log_na: formData.incident_log_na,
        incident_log_audit: formData.incident_log ? createAuditTrail() : null,
        superintendent_signature: formData.superintendent_signature,
        competent_person_signature: formData.competent_person_signature,
      };

      // 1) LOCAL FIRST. The signed log is durable on this device before a single
      //    byte goes to the network, so a failed push can never lose it.
      //    — but only if it actually landed. writeDraft returns false and never
      //    throws, and this call used to discard that, so "so a failed push can
      //    never lose it" was a promise nothing checked. The catch below prints
      //    "Saved on this device", which is the claim this result either makes
      //    true or does not.
      let localSaved = false;
      try {
        localSaved = await writeDraft(key, {
          data: { ...formData },
          cp_signature: formData.competent_person_signature,
          cp_name: formData.competent_person_name,
          status: 'submitted',
          backend_id: knownId,
        });
      } catch (_e) {
        // A THROW IS A FALSE — see the note at the same guard in hot_work.
        localSaved = false;
      }
      setLocalSaveFailed(!localSaved);

      // 2) Best-effort push. Failure is NOT data loss — the draft above already
      //    holds everything, so we record the key for the reconnect flush and
      //    tell the user the truth.
      try {
        let savedId = knownId;
        if (knownId) {
          await updateDailyLog(knownId, logData);
        } else {
          const newLog = await createDailyLog(logData);
          savedId = newLog?.id || newLog?._id || null;
          setExistingLog(newLog);
        }
        setBackendLogId(savedId);
        if (savedId) await setDraftBackendId(key, savedId);
        await clearPending(key);
        setDraftPending(false);
        if (knownId) {
          toast.success('Updated', 'Daily log updated successfully');
        } else {
          toast.success('Created', 'Daily log created successfully');
        }
        await fetchLogsForProject(projectId);
      } catch (pushErr) {
        // NEITHER COPY EXISTS. Both messages below say the log is stored here;
        // one of them calls it a success. If the local write failed there is no
        // device copy to sync from, so nothing is queued — a key queued over a
        // stale autosave would let the drain file unsigned content — and the
        // superintendent is told before he closes the form on the only copy
        // left, the one on screen.
        if (!localSaved) {
          // NOT "saved on this device". The banner below says the true thing and
          // keeps saying it after this toast is gone.
          setDraftPending(false);
          console.warn('Daily log push failed AND the local save failed; not queued.');
          toast.error(
            'Not saved — nothing was filed',
            'This device could not store the log, and it did not reach the server either. Nothing was filed and nothing is queued to retry. Your entries are still on this screen. Free up space on the device, then save again.',
          );
          return;
        }
        await markPending(key);
        setDraftPending(true);
        if (pushErr?.offline || isOfflineError(pushErr)) {
          toast.success(
            'Saved on this device',
            'Your daily log and signatures are stored on this device and will sync when you reconnect.'
          );
        } else {
          toast.error(
            'Not synced yet',
            `${pushErr?.userMessage || pushErr?.response?.data?.detail || 'The server rejected this save.'} Your daily log is saved on this device.`
          );
        }
      }
    } catch (error) {
      console.error('Failed to save log:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not save daily log');
    } finally {
      setSaving(false);
    }
  };

  const getProjectId = (project) => project?._id || project?.id;

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getWeatherIcon = (weather) => {
    const option = weatherOptions.find((w) => w.value === weather);
    return option?.icon || Cloud;
  };

  const previousLogs = allLogs.filter(
    (log) => log.date !== todayISO()
  );

  const renderSafetyCheckItem = (item) => {
    const checkData = formData.safety_checklist[item.id] || { status: 'unchecked' };
    
    return (
      <View key={item.id} style={s.checklistItem}>
        <Text style={s.checklistLabel}>{item.label}</Text>
        <View style={s.checklistOptions}>
          <Pressable
            onPress={() => handleSafetyCheckChange(item.id, 'checked')}
            style={[
              s.checkOption,
              checkData.status === 'checked' && s.checkOptionActive,
            ]}
          >
            <CheckCircle
              size={16}
              strokeWidth={1.5}
              color={checkData.status === 'checked' ? semantic.verified : colors.text.muted}
            />
          </Pressable>
          <Pressable
            onPress={() => handleSafetyCheckChange(item.id, 'unchecked')}
            style={[
              s.checkOption,
              checkData.status === 'unchecked' && s.checkOptionUnchecked,
            ]}
          >
            <XCircle
              size={16}
              strokeWidth={1.5}
              color={checkData.status === 'unchecked' ? semantic.neutral : colors.text.muted}
            />
          </Pressable>
          <Pressable
            onPress={() => handleSafetyCheckChange(item.id, 'na')}
            style={[
              s.checkOption,
              checkData.status === 'na' && s.checkOptionNA,
            ]}
          >
            <Text
              style={[
                s.naText,
                checkData.status === 'na' && s.naTextActive,
              ]}
            >
              N/A
            </Text>
          </Pressable>
        </View>
        {checkData.checked_at && (
          <Text style={s.auditText}>
            {checkData.checked_by} • {formatTimestamp(checkData.checked_at)}
          </Text>
        )}
      </View>
    );
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            {siteMode ? (
              <View style={s.siteBadge}>
                <Building2 size={14} strokeWidth={1.5} color={semantic.neutral} />
                <Text style={s.siteBadgeText}>SITE MODE</Text>
              </View>
            ) : isAdmin ? (
              <View style={[s.siteBadge, s.viewOnlyBadge]}>
                <Eye size={14} strokeWidth={1.5} color="#3b82f6" />
                <Text style={[s.siteBadgeText, s.viewOnlyText]}>VIEW ONLY</Text>
              </View>
            ) : (
              <HeaderBrand />
            )}
          </View>
          <View style={s.headerRight}>
            <OfflineIndicator />
          </View>
        </View>

        {/* Tab Selector */}
        {siteMode && (
          <View style={s.tabContainer}>
            <Pressable
              onPress={() => setActiveTab('today')}
              style={[s.tab, activeTab === 'today' && s.tabActive]}
            >
              <ClipboardList
                size={16}
                strokeWidth={1.5}
                color={activeTab === 'today' ? chrome.brand : colors.text.muted}
              />
              <Text style={[s.tabText, activeTab === 'today' && s.tabTextActive]}>
                Today's Log
              </Text>
            </Pressable>
            <Pressable
              onPress={() => setActiveTab('previous')}
              style={[s.tab, activeTab === 'previous' && s.tabActive]}
            >
              <History
                size={16}
                strokeWidth={1.5}
                color={activeTab === 'previous' ? chrome.brand : colors.text.muted}
              />
              <Text style={[s.tabText, activeTab === 'previous' && s.tabTextActive]}>
                Previous Days
              </Text>
              {previousLogs.length > 0 && (
                <View style={s.badge}>
                  <Text style={s.badgeText}>{previousLogs.length}</Text>
                </View>
              )}
            </Pressable>
          </View>
        )}

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>
              {isAdmin ? 'VIEW' : activeTab === 'today' ? 'CREATE / EDIT' : 'VIEW'}
            </Text>
            <Text style={s.titleText}>Daily Logs</Text>
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={60} borderRadiusValue={borderRadius.xl} style={s.mb16} />
              <GlassSkeleton width="100%" height={200} borderRadiusValue={borderRadius.xxl} style={s.mb16} />
              <GlassSkeleton width="100%" height={150} borderRadiusValue={borderRadius.xl} />
            </>
          ) : (!siteMode || activeTab === 'previous') ? (
            <>
              {isAdmin && (
                <Pressable
                  style={s.projectSelector}
                  onPress={() => setShowProjectPicker(!showProjectPicker)}
                >
                  <IconPod size={40}>
                    <Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />
                  </IconPod>
                  <View style={s.projectInfo}>
                    <Text style={s.projectLabel}>PROJECT</Text>
                    <Text style={s.projectName}>
                      {selectedProject?.name || 'Select project'}
                    </Text>
                  </View>
                  <ChevronDown
                    size={20}
                    strokeWidth={1.5}
                    color={colors.text.muted}
                    style={showProjectPicker && s.iconRotated}
                  />
                </Pressable>
              )}

              {showProjectPicker && (
                <View style={s.dropdown}>
                  {projects.map((p) => (
                    <Pressable
                      key={getProjectId(p)}
                      onPress={() => handleProjectChange(p)}
                      style={[
                        s.dropdownItem,
                        getProjectId(selectedProject) === getProjectId(p) && s.dropdownItemActive,
                      ]}
                    >
                      <Text style={s.dropdownText}>{p.name}</Text>
                    </Pressable>
                  ))}
                </View>
              )}

              {/* OFFLINE vs EMPTY — a failed read is never rendered as
                  "No Logs Found"; that would assert to an inspector that no
                  daily logs exist for this project. */}
              {logsFetchState !== 'ok' && (
                <OfflineNotice
                  mode={logsFetchState === 'offline' ? 'offline' : 'error'}
                  cachedCount={previousLogs.length}
                />
              )}

              {previousLogs.length > 0 ? (
                <View style={s.previousLogsList}>
                  {previousLogs.map((log) => {
                    const WeatherIcon = getWeatherIcon(log.weather);
                    return (
                      <GlassListItem
                        key={log.id || log._id}
                        onPress={() => setSelectedPreviousLog(log)}
                        style={s.previousLogItem}
                      >
                        <View style={s.logDateSection}>
                          <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
                          <Text style={s.logDate}>{formatDate(log.date)}</Text>
                        </View>
                        <View style={s.logSummary}>
                          <View style={s.logStat}>
                            <WeatherIcon size={14} strokeWidth={1.5} color={colors.text.muted} />
                            <Text style={s.logStatText}>{log.weather}</Text>
                          </View>
                          <View style={s.logStat}>
                            <Users size={14} strokeWidth={1.5} color={colors.text.muted} />
                            <Text style={s.logStatText}>{log.worker_count || 0}</Text>
                          </View>
                          {log.superintendent_signature && (
                            <View style={s.signedBadge}>
                              <PenTool size={10} strokeWidth={1.5} color={semantic.verified} />
                            </View>
                          )}
                        </View>
                      </GlassListItem>
                    );
                  })}
                </View>
              ) : logsFetchState === 'ok' ? (
                <GlassCard style={s.emptyCard}>
                  <IconPod size={64}>
                    <History size={28} strokeWidth={1.5} color={colors.text.muted} />
                  </IconPod>
                  <Text style={s.emptyTitle}>No Logs Found</Text>
                  <Text style={s.emptyText}>
                    Daily logs for this project will appear here.
                  </Text>
                </GlassCard>
              ) : null}
            </>
          ) : (
            <>
              {siteMode && siteProject && (
                <View style={s.siteProjectCard}>
                  <Building2 size={16} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={s.siteProjectName}>{siteProject.name}</Text>
                </View>
              )}

              <View style={s.dateCard}>
                <Calendar size={18} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.dateText}>{formatDate(new Date())}</Text>
                {existingLog && (
                  <View style={s.existingBadge}>
                    <Check size={12} strokeWidth={2} color="#4ade80" />
                    <Text style={s.existingText}>Log exists</Text>
                  </View>
                )}
              </View>

              {/* THE WORSE OF THE TWO WINS THE SLOT. "Saved on this device" and
                  "not saved on this device" cannot both be on screen, and if the
                  device is not storing the draft that is the one he must act on:
                  his entries exist only in the form in front of him. */}
              {localSaveFailed && (
                <View style={s.saveFailedBanner}>
                  <CloudOff size={14} strokeWidth={1.5} color={semantic.critical} />
                  <Text style={s.saveFailedText}>
                    NOT saved on this device. Your entries are only on this screen — do not close the form. Free up space, then save again.
                  </Text>
                </View>
              )}

              {/* A push that never landed is not a loss — say so plainly. */}
              {!localSaveFailed && draftPending && (
                <View style={s.pendingBanner}>
                  <CloudOff size={14} strokeWidth={1.5} color={semantic.attention} />
                  <Text style={s.pendingText}>
                    Saved on this device — will sync when you reconnect.
                  </Text>
                </View>
              )}

              <GlassCard style={s.section}>
                <Text style={s.sectionTitle}>Weather Conditions</Text>
                <View style={s.weatherGrid}>
                  {weatherOptions.map((option) => {
                    const Icon = option.icon;
                    const isSelected = formData.weather === option.value;
                    return (
                      <Pressable
                        key={option.value}
                        onPress={() => setFormData({ ...formData, weather: option.value })}
                        style={[s.weatherOption, isSelected && s.weatherOptionSelected]}
                      >
                        <Icon
                          size={24}
                          strokeWidth={1.5}
                          color={isSelected ? chrome.brand : colors.text.muted}
                        />
                        <Text style={[s.weatherLabel, isSelected && s.weatherLabelSelected]}>
                          {option.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </GlassCard>

              {/* PR #48 — the manual "Project Phase" card grid was
                  removed. Phase is now inferred weekly by Gemini from
                  the work/notes/trades fields above. */}

              <GlassCard style={s.section}>
                <Text style={s.sectionTitle}>Worker Count</Text>
                <View style={s.workerCountRow}>
                  <Users size={20} strokeWidth={1.5} color={colors.text.muted} />
                  <TextInput
                    style={s.workerCountInput}
                    value={String(formData.worker_count)}
                    onChangeText={(val) => setFormData({ ...formData, worker_count: val })}
                    keyboardType="numeric"
                    placeholder="0"
                    placeholderTextColor={colors.text.subtle}
                  />
                  <Text style={s.workerCountLabel}>workers on site today</Text>
                </View>
              </GlassCard>

              <GlassCard style={s.section}>
                <Text style={s.sectionTitle}>Daily Notes</Text>
                <TextInput
                  style={s.notesInput}
                  value={formData.notes}
                  onChangeText={(val) => setFormData({ ...formData, notes: val })}
                  placeholder="Enter daily notes, progress updates, etc..."
                  placeholderTextColor={colors.text.subtle}
                  multiline
                  numberOfLines={4}
                />
              </GlassCard>

              <GlassCard style={s.section}>
                <View style={s.sectionHeader}>
                  <ShieldCheck size={20} strokeWidth={1.5} color={semantic.neutral} />
                  <Text style={s.sectionTitle}>Safety Inspection Checklist</Text>
                </View>
                <Text style={s.sectionSubtitle}>
                  Check each item, mark as unchecked if issue found, or N/A if not applicable
                </Text>
                <View style={s.checklistContainer}>
                  {SAFETY_CHECKLIST_ITEMS.map(renderSafetyCheckItem)}
                </View>
              </GlassCard>

              <GlassCard style={s.section}>
                <View style={s.sectionHeader}>
                  <AlertTriangle size={20} strokeWidth={1.5} color={semantic.attention} />
                  <Text style={s.sectionTitle}>Corrective Actions</Text>
                </View>
                <Text style={s.sectionSubtitle}>
                  Document any unsafe conditions found and how they were addressed
                </Text>
                <Pressable
                  onPress={() =>
                    setFormData({ ...formData, corrective_actions_na: !formData.corrective_actions_na })
                  }
                  style={s.naCheckbox}
                >
                  <View
                    style={[s.checkbox, formData.corrective_actions_na && s.checkboxChecked]}
                  >
                    {formData.corrective_actions_na && (
                      <Check size={12} strokeWidth={2} color="#fff" />
                    )}
                  </View>
                  <Text style={s.naCheckboxLabel}>N/A - No corrective actions needed</Text>
                </Pressable>
                {!formData.corrective_actions_na && (
                  <TextInput
                    style={s.notesInput}
                    value={formData.corrective_actions}
                    onChangeText={(val) => setFormData({ ...formData, corrective_actions: val })}
                    placeholder="Describe unsafe conditions and corrective measures taken..."
                    placeholderTextColor={colors.text.subtle}
                    multiline
                    numberOfLines={3}
                  />
                )}
              </GlassCard>

              <GlassCard style={s.section}>
                <View style={s.sectionHeader}>
                  <FileText size={20} strokeWidth={1.5} color="#3b82f6" />
                  <Text style={s.sectionTitle}>Incident Log</Text>
                </View>
                <Text style={s.sectionSubtitle}>
                  Record any accidents, injuries, or near-misses that occurred
                </Text>
                <Pressable
                  onPress={() =>
                    setFormData({ ...formData, incident_log_na: !formData.incident_log_na })
                  }
                  style={s.naCheckbox}
                >
                  <View
                    style={[s.checkbox, formData.incident_log_na && s.checkboxChecked]}
                  >
                    {formData.incident_log_na && (
                      <Check size={12} strokeWidth={2} color="#fff" />
                    )}
                  </View>
                  <Text style={s.naCheckboxLabel}>N/A - No incidents occurred</Text>
                </Pressable>
                {!formData.incident_log_na && (
                  <TextInput
                    style={s.notesInput}
                    value={formData.incident_log}
                    onChangeText={(val) => setFormData({ ...formData, incident_log: val })}
                    placeholder="Describe any incidents, injuries, or near-misses..."
                    placeholderTextColor={colors.text.subtle}
                    multiline
                    numberOfLines={3}
                  />
                )}
              </GlassCard>

              {siteMode && (
                <>
                  <View style={s.signatureSection}>
                    <View style={s.signatureHeader}>
                      <IconPod size={40}>
                        <HardHat size={18} strokeWidth={1.5} color={semantic.neutral} />
                      </IconPod>
                      <Text style={s.signatureTitle}>Superintendent Sign-Off</Text>
                    </View>
                    <SignaturePad
                      title="Superintendent Signature"
                      signerName={formData.superintendent_name}
                      onNameChange={(name) => setFormData({ ...formData, superintendent_name: name })}
                      existingSignature={formData.superintendent_signature}
                      onSignatureCapture={(sig) =>
                        setFormData({ ...formData, superintendent_signature: sig })
                      }
                    />
                    {csLicenseNumber ? (
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 6 }}>
                        <Text style={{ fontSize: 11, color: colors.text.muted }}>CS LICENSE:</Text>
                        <Text
                          style={{
                            fontSize: 11,
                            color: colors.text.muted,
                            fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
                          }}
                        >
                          {csLicenseNumber}
                        </Text>
                      </View>
                    ) : null}
                  </View>

                  <View style={s.signatureSection}>
                    <View style={s.signatureHeader}>
                      <IconPod size={40}>
                        <ShieldCheck size={18} strokeWidth={1.5} color="#3b82f6" />
                      </IconPod>
                      <Text style={s.signatureTitle}>Competent Person Sign-Off</Text>
                    </View>
                    <SignaturePad
                      title="Competent Person Signature"
                      signerName={formData.competent_person_name}
                      onNameChange={(name) => setFormData({ ...formData, competent_person_name: name })}
                      existingSignature={formData.competent_person_signature}
                      onSignatureCapture={(sig) =>
                        setFormData({ ...formData, competent_person_signature: sig })
                      }
                    />
                  </View>

                  <GlassButton
                    title={saving ? 'Saving...' : existingLog ? 'Update Daily Log' : 'Submit Daily Log'}
                    onPress={handleSubmit}
                    loading={saving}
                    style={s.submitButton}
                  />
                </>
              )}
            </>
          )}
        </ScrollView>

        {!siteMode && <FloatingNav />}

        <Modal
          visible={!!selectedPreviousLog}
          animationType="slide"
          transparent={true}
          onRequestClose={() => setSelectedPreviousLog(null)}
        >
          <View style={s.modalOverlay}>
            <View style={s.modalContent}>
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>
                  Log: {selectedPreviousLog && formatDate(selectedPreviousLog.date)}
                </Text>
                <Pressable onPress={() => setSelectedPreviousLog(null)}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>

              <ScrollView style={s.modalScroll}>
                {selectedPreviousLog && (
                  <>
                    <View style={s.modalSection}>
                      <Text style={s.modalLabel}>WEATHER</Text>
                      <Text style={s.modalValue}>{selectedPreviousLog.weather}</Text>
                    </View>
                    <View style={s.modalSection}>
                      <Text style={s.modalLabel}>WORKER COUNT</Text>
                      <Text style={s.modalValue}>{selectedPreviousLog.worker_count || 0}</Text>
                    </View>
                    {selectedPreviousLog.notes && (
                      <View style={s.modalSection}>
                        <Text style={s.modalLabel}>NOTES</Text>
                        {/* PR G: notes are prose — sentence case at display only. */}
                        <Text style={s.modalValue}>{sentenceCase(selectedPreviousLog.notes)}</Text>
                      </View>
                    )}
                    {selectedPreviousLog.safety_checklist && (
                      <View style={s.modalSection}>
                        <Text style={s.modalLabel}>SAFETY CHECKLIST</Text>
                        {Object.entries(selectedPreviousLog.safety_checklist).map(([key, value]) => (
                          <View key={key} style={s.checklistReview}>
                            <Text style={s.checklistReviewLabel}>
                              {SAFETY_CHECKLIST_ITEMS.find((i) => i.id === key)?.label || key}
                            </Text>
                            <View
                              style={[
                                s.statusBadge,
                                value.status === 'checked' && s.statusChecked,
                                value.status === 'unchecked' && s.statusUnchecked,
                                value.status === 'na' && s.statusNA,
                              ]}
                            >
                              <Text style={s.statusText}>{value.status?.toUpperCase()}</Text>
                            </View>
                          </View>
                        ))}
                      </View>
                    )}
                    {(selectedPreviousLog.corrective_actions || selectedPreviousLog.corrective_actions_na) && (
                      <View style={s.modalSection}>
                        <Text style={s.modalLabel}>CORRECTIVE ACTIONS</Text>
                        <Text style={s.modalValue}>
                          {selectedPreviousLog.corrective_actions_na
                            ? 'N/A - No corrective actions needed'
                            : selectedPreviousLog.corrective_actions}
                        </Text>
                      </View>
                    )}
                    {(selectedPreviousLog.incident_log || selectedPreviousLog.incident_log_na) && (
                      <View style={s.modalSection}>
                        <Text style={s.modalLabel}>INCIDENT LOG</Text>
                        <Text style={s.modalValue}>
                          {selectedPreviousLog.incident_log_na
                            ? 'N/A - No incidents occurred'
                            : selectedPreviousLog.incident_log}
                        </Text>
                      </View>
                    )}
                    {selectedPreviousLog.superintendent_signature && (
                      <View style={s.modalSection}>
                        <Text style={s.modalLabel}>SUPERINTENDENT SIGNATURE</Text>
                        <Text style={s.modalValue}>
                          {selectedPreviousLog.superintendent_signature.signer_name}
                        </Text>
                        <Text style={s.auditText}>
                          Signed: {formatTimestamp(selectedPreviousLog.superintendent_signature.signed_at)}
                        </Text>
                      </View>
                    )}
                    {selectedPreviousLog.competent_person_signature && (
                      <View style={s.modalSection}>
                        <Text style={s.modalLabel}>COMPETENT PERSON SIGNATURE</Text>
                        <Text style={s.modalValue}>
                          {selectedPreviousLog.competent_person_signature.signer_name}
                        </Text>
                        <Text style={s.auditText}>
                          Signed: {formatTimestamp(selectedPreviousLog.competent_person_signature.signed_at)}
                        </Text>
                      </View>
                    )}
                  </>
                )}
              </ScrollView>

              <GlassButton
                title="Close"
                onPress={() => setSelectedPreviousLog(null)}
                style={s.closeButton}
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
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.08),
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  logoText: {
    ...typography.label,
    color: colors.text.muted,
  },
  siteBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: withAlpha('#94a3b8', 0.15),
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: withAlpha('#94a3b8', 0.3),
  },
  viewOnlyBadge: {
    backgroundColor: 'rgba(59, 130, 246, 0.15)',
    borderColor: 'rgba(59, 130, 246, 0.3)',
  },
  siteBadgeText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#4ade80',
    letterSpacing: 0.5,
  },
  viewOnlyText: {
    color: '#3b82f6',
  },
  tabContainer: {
    flexDirection: 'row',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  tab: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  tabActive: {
    backgroundColor: semantic.verifiedBg,
    borderColor: semantic.verifiedBorder,
  },
  tabText: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.muted,
  },
  tabTextActive: {
    color: chrome.brand,
  },
  badge: {
    backgroundColor: '#4ade80',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 10,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '600',
    color: '#fff',
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 120,
  },
  titleSection: {
    marginBottom: spacing.lg,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  titleText: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
  },
  mb16: {
    marginBottom: spacing.md,
  },
  projectSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  projectInfo: {
    flex: 1,
  },
  projectLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: 2,
  },
  projectName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  iconRotated: {
    transform: [{ rotate: '180deg' }],
  },
  dropdown: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    marginBottom: spacing.md,
    overflow: 'hidden',
  },
  dropdownItem: {
    padding: spacing.md,
  },
  dropdownItemActive: {
    backgroundColor: withAlpha('#ffffff', 0.1),
  },
  dropdownText: {
    fontSize: 15,
    color: colors.text.secondary,
  },
  siteProjectCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  siteProjectName: {
    fontSize: 15,
    color: colors.text.primary,
  },
  dateCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  dateText: {
    flex: 1,
    fontSize: 15,
    color: colors.text.primary,
  },
  existingBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: semantic.verifiedBg,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.full,
  },
  existingText: {
    fontSize: 11,
    fontWeight: '500',
    color: '#4ade80',
  },
  // Louder than pendingBanner: that one reassures, this one contradicts it.
  saveFailedBanner: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: borderRadius.md, marginTop: spacing.sm,
    backgroundColor: semantic.criticalBg, borderWidth: 1,
    borderColor: semantic.criticalBorder,
  },
  saveFailedText: {
    flex: 1, fontSize: 12, fontWeight: '700', color: semantic.critical,
  },
  pendingBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    backgroundColor: withAlpha(semantic.attention, 0.1),
    borderWidth: 1,
    borderColor: withAlpha(semantic.attention, 0.4),
    borderRadius: borderRadius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginBottom: spacing.lg,
  },
  pendingText: {
    flex: 1,
    fontSize: 12,
    color: semantic.attention,
  },
  section: {
    marginBottom: spacing.lg,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  sectionSubtitle: {
    fontSize: 13,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  weatherGrid: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  weatherOption: {
    flex: 1,
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.lg,
    backgroundColor: withAlpha('#ffffff', 0.05),
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  weatherOptionSelected: {
    backgroundColor: semantic.verifiedBg,
    borderColor: chrome.brand,
  },
  weatherLabel: {
    fontSize: 12,
    color: colors.text.muted,
  },
  weatherLabelSelected: {
    color: chrome.brand,
  },
  workerCountRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  workerCountInput: {
    fontSize: 32,
    fontWeight: '200',
    color: colors.text.primary,
    minWidth: 60,
    textAlign: 'center',
  },
  workerCountLabel: {
    fontSize: 14,
    color: colors.text.muted,
  },
  notesInput: {
    backgroundColor: withAlpha('#ffffff', 0.05),
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    color: colors.text.primary,
    fontSize: 14,
    minHeight: 100,
    textAlignVertical: 'top',
  },
  checklistContainer: {
    gap: spacing.sm,
  },
  checklistItem: {
    backgroundColor: withAlpha('#ffffff', 0.03),
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  checklistLabel: {
    fontSize: 14,
    color: colors.text.primary,
    marginBottom: spacing.sm,
  },
  checklistOptions: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  checkOption: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.sm,
    backgroundColor: withAlpha('#ffffff', 0.05),
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  checkOptionActive: {
    backgroundColor: semantic.verifiedBg,
    borderColor: chrome.brand,
  },
  checkOptionUnchecked: {
    backgroundColor: semantic.criticalBg,
    borderColor: semantic.neutral,
  },
  checkOptionNA: {
    backgroundColor: withAlpha('#64748b', 0.2),
    borderColor: colors.text.muted,
  },
  naText: {
    fontSize: 12,
    fontWeight: '500',
    color: colors.text.muted,
  },
  naTextActive: {
    color: colors.text.primary,
  },
  auditText: {
    fontSize: 11,
    color: colors.text.subtle,
    marginTop: spacing.xs,
  },
  naCheckbox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: colors.glass.border,
    backgroundColor: withAlpha('#ffffff', 0.05),
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxChecked: {
    backgroundColor: semantic.verified,
    borderColor: semantic.verified,
  },
  naCheckboxLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  signatureSection: {
    marginBottom: spacing.lg,
  },
  signatureHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  signatureTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  submitButton: {
    marginTop: spacing.md,
    marginBottom: spacing.xxl,
  },
  previousLogsList: {
    gap: spacing.sm,
  },
  previousLogItem: {
    gap: spacing.md,
  },
  logDateSection: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    minWidth: 140,
  },
  logDate: {
    fontSize: 14,
    color: colors.text.primary,
  },
  logSummary: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: spacing.md,
  },
  logStat: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  logStatText: {
    fontSize: 13,
    color: colors.text.muted,
  },
  signedBadge: {
    backgroundColor: semantic.verifiedBg,
    padding: 4,
    borderRadius: borderRadius.full,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 260,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: withAlpha('#000000', 0.7),
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg,
  },
  modalContent: {
    backgroundColor: '#1a1a2e',
    borderRadius: borderRadius.xxl,
    width: '100%',
    maxWidth: 500,
    maxHeight: '80%',
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
  },
  modalScroll: {
    padding: spacing.lg,
  },
  modalSection: {
    marginBottom: spacing.lg,
  },
  modalLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  modalValue: {
    fontSize: 15,
    color: colors.text.primary,
  },
  checklistReview: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  checklistReviewLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  statusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: borderRadius.sm,
    backgroundColor: colors.glass.background,
  },
  statusChecked: {
    backgroundColor: semantic.verifiedBg,
  },
  statusUnchecked: {
    backgroundColor: semantic.criticalBg,
  },
  statusNA: {
    backgroundColor: withAlpha('#64748b', 0.2),
  },
  statusText: {
    fontSize: 10,
    fontWeight: '600',
    color: colors.text.muted,
  },
  closeButton: {
    margin: spacing.lg,
  },
});
}
