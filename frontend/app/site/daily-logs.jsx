import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  Modal,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Building2,
  ClipboardList,
  Calendar,
  Cloud,
  Sun,
  CloudRain,
  Wind,
  Users,
  History,
  Check,
  X,
  ShieldCheck,
  HardHat,
  AlertTriangle,
  FileText,
  PenTool,
  CheckCircle,
  XCircle,
  Home,
  LogOut,
  CloudOff,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import SignaturePad from '../../src/components/SignaturePad';
import OfflineNotice from '../../src/components/OfflineNotice';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { dailyLogsAPI, csRegistrationAPI } from '../../src/utils/api';
import {
  draftKey,
  readDraft,
  writeDraft,
  setDraftBackendId,
  markPending,
  clearPending,
  getPendingKeys,
} from '../../src/utils/logbookDrafts';
import { settleFetch, isOfflineError } from '../../src/utils/offlineState';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
import { semantic, chrome, surface, withAlpha } from '../../src/styles/semanticColors';
import { useIsWide } from '../../src/hooks/useIsDesktop';
import { easternToday } from '../../src/utils/dates';

const weatherOptions = [
  { value: 'sunny', label: 'Sunny', icon: Sun },
  { value: 'cloudy', label: 'Cloudy', icon: Cloud },
  { value: 'rainy', label: 'Rainy', icon: CloudRain },
  { value: 'windy', label: 'Windy', icon: Wind },
];

const SAFETY_CHECKLIST_ITEMS = [
  { id: 'fall_protection', label: 'Fall Protection' },
  { id: 'scaffolding', label: 'Scaffolding' },
  { id: 'ppe', label: 'PPE' },
  { id: 'hazards', label: 'Hazards' },
  { id: 'base_conditions', label: 'Base Conditions' },
];

// ── Offline draft identity ──────────────────────────────────────────────────
// This screen is the superintendent's REQUIRED §3301.13.13 daily log. Until
// now the typed log lived ONLY in React state: a failed save just toasted, and
// navigating away or an OS kill silently destroyed a legally required record.
// It now uses the same local-first draft store as the CP logbooks
// (src/utils/logbookDrafts.js), keyed by the log's natural identity
// (project + log type + date) — the same key the server dedups on.
const LOG_TYPE = 'site_daily_log';

const todayStr = () => easternToday();

export default function SiteDailyLogsScreen() {
  // Theme read at RENDER time. A module-scope StyleSheet snapshots colors.*
  // at import (the DARK palette), so on the light theme this screen rendered
  // near-white text on a pale background. Same tokens, live values.
  const { colors, isDark } = useTheme();
  const isWide = useIsWide();
  const styles = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading, siteMode, siteProject, logout } = useAuth();
  const toast = useToast();

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const [activeTab, setActiveTab] = useState('today');
  const [loading, setLoading] = useState(true);
  const [allLogs, setAllLogs] = useState([]);
  const [existingLog, setExistingLog] = useState(null);
  const [saving, setSaving] = useState(false);
  const [selectedPreviousLog, setSelectedPreviousLog] = useState(null);
  const [csLicenseNumber, setCsLicenseNumber] = useState('');

  // The server id of TODAY's log, kept independently of `existingLog` and
  // persisted in the local draft. `existingLog` is only ever set from a
  // SUCCESSFUL list read, so when the read failed it stayed null and the next
  // save took the CREATE branch — duplicating a log that already existed on the
  // server. This id survives that failed read, so the save still UPDATEs.
  const [existingLogId, setExistingLogId] = useState(null);
  // 'ok' | 'offline' | 'error' — a failed load must never render as "no logs".
  const [fetchState, setFetchState] = useState('ok');
  // True when the local draft holds changes the server has not accepted yet.
  const [pendingSync, setPendingSync] = useState(false);

  const [formData, setFormData] = useState({
    weather: 'sunny',
    notes: '',
    worker_count: 0,
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

  useEffect(() => {
    if (!authLoading && isAuthenticated !== undefined) {
      if (!isAuthenticated) {
        router.replace('/login');
      } else if (isAuthenticated && !siteMode && siteProject === null) {
        router.replace('/');
      }
    }
  }, [isAuthenticated, authLoading, siteMode, siteProject]);
  
  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchLogs();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  // The draft key for TODAY's log on the active project (null before a project
  // is known, so no draft can ever be written to the wrong key).
  const currentDraftKey = () =>
    (siteProject?.id ? draftKey({ projectId: siteProject.id, logType: LOG_TYPE, date: todayStr() }) : null);

  // Debounced autosave of the WHOLE form (fields + both signatures) to the
  // local draft. No network. This is what makes a navigate-away or a process
  // kill non-destructive: whatever is on screen is already on disk within a
  // second. `status` is deliberately not written here so an autosave can never
  // downgrade a submitted log back to a draft.
  useEffect(() => {
    if (loading) return undefined;
    const key = currentDraftKey();
    if (!key) return undefined;
    const t = setTimeout(() => {
      writeDraft(key, { data: formData }).catch(() => {});
    }, 800);
    return () => clearTimeout(t);
  }, [loading, siteProject?.id, formData]);

  const fetchLogs = async () => {
    if (!siteProject?.id) return;
    setLoading(true);
    const key = currentDraftKey();
    try {
      // ── 1. LOCAL FIRST ────────────────────────────────────────────────────
      // The on-device draft is what the superintendent actually typed, so it is
      // read and rendered BEFORE any network call. Offline, this is the whole
      // screen; online, it is just replaced a moment later by the server copy.
      let draft = null;
      let draftPending = false;
      try {
        draft = await readDraft(key);
        draftPending = (await getPendingKeys()).includes(key);
      } catch (e) {
        console.warn('Draft read failed (non-blocking):', e?.message);
      }
      const hasDraftData = !!draft?.data && Object.keys(draft.data).length > 0;
      if (hasDraftData) setFormData((prev) => ({ ...prev, ...draft.data }));
      if (draft?.backend_id) setExistingLogId(draft.backend_id);
      setPendingSync(draftPending);

      // ── 2. THEN THE SERVER ────────────────────────────────────────────────
      const res = await settleFetch(() => dailyLogsAPI.getByProject(siteProject.id));

      if (res.status === 'ok') {
        setFetchState('ok');
        const logsList = Array.isArray(res.data) ? res.data : [];
        setAllLogs(logsList);

        const today = todayStr();
        const todayLog = logsList.find((l) => l.date === today);

        if (todayLog) {
          const serverId = todayLog.id || todayLog._id;
          setExistingLog(todayLog);
          setExistingLogId(serverId);
          setDraftBackendId(key, serverId).catch(() => {});
          // A draft with an un-pushed change WINS over the server copy —
          // otherwise reconnecting would silently overwrite work done offline.
          // Otherwise hydrate from the server and write through to the draft,
          // so the device copy and the server copy agree.
          if (!draftPending) {
            const form = formFromLog(todayLog);
            setFormData(form);
            writeDraft(key, { data: form, backend_id: serverId }).catch(() => {});
          }
        } else {
          setExistingLog(null);
          // The list is sorted date-descending, so a successful read without
          // today's date is authoritative: any id we were holding is stale and
          // must not be reused, or the next save would PUT to a deleted doc.
          if (draft?.backend_id) {
            setExistingLogId(null);
            writeDraft(key, { backend_id: null }).catch(() => {});
          }
          // Only wipe the form when there is nothing local to lose. A draft
          // with no server twin is a log typed offline today — it stays.
          if (!hasDraftData) resetForm();
        }
      } else {
        // NOT an empty state. Keep the draft-hydrated form and whatever list is
        // already in state; the UI renders <OfflineNotice> instead of "no logs".
        setFetchState(res.status);
        console.warn('Failed to fetch logs:', res.error?.message);
      }

      // Auto-fill superintendent from CS registration. Non-blocking —
      // only pre-fills if the field is empty (existing signed log is
      // never overwritten). Also gives us the license number for the
      // badge under the signature pad.
      try {
        const csData = await csRegistrationAPI.getForProject(siteProject.id);
        if (csData?.registered && csData.full_name) {
          setFormData((prev) => ({
            ...prev,
            superintendent_name: prev.superintendent_name || csData.full_name,
          }));
          setCsLicenseNumber(csData.license_number || '');
        } else {
          setCsLicenseNumber('');
        }
      } catch (e) {
        console.warn('CS lookup failed (non-blocking):', e?.message);
        setCsLicenseNumber('');
      }
    } catch (error) {
      // Never strand the screen in its skeleton state — the draft above is
      // already on screen, so this is only a guard, not a data path.
      console.error('Failed to load daily log:', error);
    } finally {
      setLoading(false);
    }
  };

  // Server log -> form shape. Split out of the old populateFormFromLog so the
  // SAME object can be both put on screen and written through to the draft.
  const formFromLog = (log) => ({
    weather: log.weather || 'sunny',
    notes: log.notes || '',
    worker_count: log.worker_count || 0,
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

  const resetForm = () => {
    setFormData({
      weather: 'sunny',
      notes: '',
      worker_count: 0,
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

  const handleSafetyCheckChange = (itemId, status) => {
    const now = new Date().toISOString();
    const userName = user?.name || user?.device_name || 'Site Device';
    
    setFormData((prev) => ({
      ...prev,
      safety_checklist: {
        ...prev.safety_checklist,
        [itemId]: { status, checked_by: userName, checked_at: now },
      },
    }));
  };

  const handleSubmit = async () => {
    setSaving(true);
    const key = currentDraftKey();
    try {
      const today = todayStr();
      const logData = {
        project_id: siteProject.id,
        date: today,
        weather: formData.weather,
        notes: formData.notes,
        worker_count: parseInt(formData.worker_count) || 0,
        safety_checklist: formData.safety_checklist,
        corrective_actions: formData.corrective_actions,
        corrective_actions_na: formData.corrective_actions_na,
        corrective_actions_audit: formData.corrective_actions ? {
          entered_by: user?.name || user?.device_name,
          entered_by_id: user?.id,
          entered_at: new Date().toISOString(),
        } : null,
        incident_log: formData.incident_log,
        incident_log_na: formData.incident_log_na,
        incident_log_audit: formData.incident_log ? {
          entered_by: user?.name || user?.device_name,
          entered_by_id: user?.id,
          entered_at: new Date().toISOString(),
        } : null,
        superintendent_signature: formData.superintendent_signature,
        competent_person_signature: formData.competent_person_signature,
      };

      // LOCAL FIRST. The device copy is written before anything touches the
      // network, so from here on the log cannot be lost — the server push below
      // is best-effort and its failure only delays the sync.
      await writeDraft(key, { data: formData, status: 'submitted' });

      // Prefer the id we know about from ANY source: the loaded log, or the one
      // persisted in the draft when the load failed. Falling back to CREATE
      // because a load failed is what duplicated server logs.
      const targetId = existingLog?.id || existingLog?._id || existingLogId;

      try {
        let savedId = targetId;
        if (targetId) {
          const updated = await dailyLogsAPI.update(targetId, logData);
          if (updated?.id || updated?._id) setExistingLog(updated);
          toast.success('Updated', 'Daily log updated');
        } else {
          const newLog = await dailyLogsAPI.create(logData);
          savedId = newLog?.id || newLog?._id || null;
          setExistingLog(newLog);
          toast.success('Created', 'Daily log created');
        }
        setExistingLogId(savedId);
        await setDraftBackendId(key, savedId);
        await clearPending(key);
        setPendingSync(false);
        fetchLogs();
      } catch (pushErr) {
        // The log IS saved — on this device. Say that, because "Could not save
        // log" reads as "your entry is gone" and pushes a superintendent to
        // retype a required record they still have.
        await markPending(key);
        setPendingSync(true);
        console.warn('Daily log server push deferred (will sync on reconnect):', pushErr?.message);
        if (isOfflineError(pushErr)) {
          toast.success('Saved on this device', 'No connection — this log will sync when you are back online.');
        } else {
          toast.warning('Saved on this device', 'The server rejected the sync. Your log is safe here and will retry.');
        }
      }
    } catch (error) {
      console.error('Failed to save:', error);
      toast.error('Error', 'Could not save log');
    } finally {
      setSaving(false);
    }
  };

  const formatDate = (dateStr) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
  };

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return '';
    return new Date(timestamp).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getWeatherIcon = (weather) => {
    return weatherOptions.find((w) => w.value === weather)?.icon || Cloud;
  };

  const previousLogs = allLogs.filter(
    (log) => log.date !== todayStr()
  );

  // A log exists on the server if we loaded it OR if the draft remembers its
  // id from a previous successful push — the label and the save branch must
  // agree, or the button says "Submit" while the save correctly UPDATEs.
  const hasServerLog = !!(existingLog || existingLogId);

  const renderSafetyCheckItem = (item) => {
    const checkData = formData.safety_checklist[item.id] || { status: 'unchecked' };
    
    return (
      <View key={item.id} style={styles.checklistItem}>
        <Text style={styles.checklistLabel}>{item.label}</Text>
        <View style={styles.checklistOptions}>
          <Pressable
            onPress={() => handleSafetyCheckChange(item.id, 'checked')}
            style={[styles.checkOption, checkData.status === 'checked' && styles.checkOptionActive]}
          >
            <CheckCircle size={14} strokeWidth={1.5} color={checkData.status === 'checked' ? semantic.verified : colors.text.muted} />
          </Pressable>
          <Pressable
            onPress={() => handleSafetyCheckChange(item.id, 'unchecked')}
            style={[styles.checkOption, checkData.status === 'unchecked' && styles.checkOptionUnchecked]}
          >
            <XCircle size={14} strokeWidth={1.5} color={checkData.status === 'unchecked' ? semantic.neutral : colors.text.muted} />
          </Pressable>
          <Pressable
            onPress={() => handleSafetyCheckChange(item.id, 'na')}
            style={[styles.checkOption, checkData.status === 'na' && styles.checkOptionNA]}
          >
            <Text style={[styles.naText, checkData.status === 'na' && styles.naTextActive]}>N/A</Text>
          </Pressable>
        </View>
        {checkData.checked_at && (
          <Text style={styles.auditText}>{checkData.checked_by} • {formatTimestamp(checkData.checked_at)}</Text>
        )}
      </View>
    );
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<Home size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/site')}
            />
            <View style={styles.siteBadge}>
              <Building2 size={14} strokeWidth={1.5} color={semantic.neutral} />
              <Text style={styles.siteBadgeText}>SITE DEVICE</Text>
            </View>
            <Text style={styles.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
          </View>
          <Pressable
            onPress={handleLogout}
            style={styles.logoutBtn}
            hitSlop={12}
          >
            <LogOut size={18} strokeWidth={1.5} color="#64748b" />
          </Pressable>
        </View>

        <View style={styles.tabContainer}>
          <Pressable
            onPress={() => setActiveTab('today')}
            style={[styles.tab, activeTab === 'today' && styles.tabActive]}
          >
            <ClipboardList size={16} strokeWidth={1.5} color={activeTab === 'today' ? chrome.brand : colors.text.muted} />
            <Text style={[styles.tabText, activeTab === 'today' && styles.tabTextActive]}>Today</Text>
          </Pressable>
          <Pressable
            onPress={() => setActiveTab('previous')}
            style={[styles.tab, activeTab === 'previous' && styles.tabActive]}
          >
            <History size={16} strokeWidth={1.5} color={activeTab === 'previous' ? chrome.brand : colors.text.muted} />
            <Text style={[styles.tabText, activeTab === 'previous' && styles.tabTextActive]}>Previous</Text>
            {previousLogs.length > 0 && (
              <View style={styles.badge}><Text style={styles.badgeText}>{previousLogs.length}</Text></View>
            )}
          </Pressable>
        </View>

        <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={styles.titleSection}>
            <Text style={styles.titleLabel}>DAILY</Text>
            <Text style={styles.titleText}>Log Books</Text>
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={100} borderRadiusValue={borderRadius.xl} style={styles.mb16} />
              <GlassSkeleton width="100%" height={200} borderRadiusValue={borderRadius.xl} />
            </>
          ) : activeTab === 'today' ? (
            <>
              <View style={styles.dateCard}>
                <Calendar size={18} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.dateText}>{formatDate(new Date())}</Text>
                {pendingSync ? (
                  <View style={styles.pendingBadge}>
                    <CloudOff size={12} strokeWidth={2} color={semantic.attention} />
                    <Text style={styles.pendingText}>Saved on device</Text>
                  </View>
                ) : hasServerLog ? (
                  <View style={styles.existingBadge}>
                    <Check size={12} strokeWidth={2} color="#4ade80" />
                    <Text style={styles.existingText}>Saved</Text>
                  </View>
                ) : null}
              </View>

              {/* A failed load must not be silent here either: without this the
                  form looks like a blank new day even when today's log exists
                  on a server we simply could not reach. */}
              {fetchState !== 'ok' && (
                <OfflineNotice
                  mode={fetchState}
                  cachedCount={hasServerLog || pendingSync ? 1 : 0}
                  detail={
                    fetchState === 'offline'
                      ? 'Offline — this is your on-device copy of today’s log. Keep working; it saves here and syncs when you reconnect.'
                      : 'Could not load today’s log from the server. You are seeing the on-device copy — anything you enter is saved here.'
                  }
                />
              )}

              {/* Weather */}
              <GlassCard style={styles.section}>
                <Text style={styles.sectionTitle}>Weather</Text>
                <View style={styles.weatherGrid}>
                  {weatherOptions.map((opt) => {
                    const Icon = opt.icon;
                    const isSelected = formData.weather === opt.value;
                    return (
                      <Pressable key={opt.value} onPress={() => setFormData({...formData, weather: opt.value})}
                        style={[styles.weatherOption, isSelected && styles.weatherOptionSelected]}>
                        <Icon size={20} strokeWidth={1.5} color={isSelected ? chrome.brand : colors.text.muted} />
                        <Text style={[styles.weatherLabel, isSelected && styles.weatherLabelSelected]}>{opt.label}</Text>
                      </Pressable>
                    );
                  })}
                </View>
              </GlassCard>

              {/* Worker Count */}
              <GlassCard style={styles.section}>
                <Text style={styles.sectionTitle}>Workers</Text>
                <View style={styles.workerRow}>
                  <Users size={20} strokeWidth={1.5} color={colors.text.muted} />
                  <TextInput style={styles.workerInput} value={String(formData.worker_count)}
                    onChangeText={(v) => setFormData({...formData, worker_count: v})}
                    keyboardType="numeric" placeholder="0" placeholderTextColor={colors.text.subtle} />
                  <Text style={styles.workerLabel}>on site</Text>
                </View>
              </GlassCard>

              {/* Notes */}
              <GlassCard style={styles.section}>
                <Text style={styles.sectionTitle}>Notes</Text>
                <TextInput style={styles.notesInput} value={formData.notes}
                  onChangeText={(v) => setFormData({...formData, notes: v})}
                  placeholder="Daily notes..." placeholderTextColor={colors.text.subtle} multiline numberOfLines={3} />
              </GlassCard>

              {/* Safety Checklist */}
              <GlassCard style={styles.section}>
                <View style={styles.sectionHeader}>
                  <ShieldCheck size={18} strokeWidth={1.5} color={semantic.neutral} />
                  <Text style={styles.sectionTitle}>Safety Checklist</Text>
                </View>
                <View style={styles.checklistContainer}>
                  {SAFETY_CHECKLIST_ITEMS.map(renderSafetyCheckItem)}
                </View>
              </GlassCard>

              {/* Corrective Actions */}
              <GlassCard style={styles.section}>
                <View style={styles.sectionHeader}>
                  <AlertTriangle size={18} strokeWidth={1.5} color={semantic.attention} />
                  <Text style={styles.sectionTitle}>Corrective Actions</Text>
                </View>
                <Pressable onPress={() => setFormData({...formData, corrective_actions_na: !formData.corrective_actions_na})}
                  style={styles.naCheckbox}>
                  <View style={[styles.checkbox, formData.corrective_actions_na && styles.checkboxChecked]}>
                    {formData.corrective_actions_na && <Check size={12} strokeWidth={2} color="#fff" />}
                  </View>
                  <Text style={styles.naCheckboxLabel}>N/A</Text>
                </Pressable>
                {!formData.corrective_actions_na && (
                  <TextInput style={styles.notesInput} value={formData.corrective_actions}
                    onChangeText={(v) => setFormData({...formData, corrective_actions: v})}
                    placeholder="Describe corrections..." placeholderTextColor={colors.text.subtle} multiline numberOfLines={2} />
                )}
              </GlassCard>

              {/* Incident Log */}
              <GlassCard style={styles.section}>
                <View style={styles.sectionHeader}>
                  <FileText size={18} strokeWidth={1.5} color="#3b82f6" />
                  <Text style={styles.sectionTitle}>Incident Log</Text>
                </View>
                <Pressable onPress={() => setFormData({...formData, incident_log_na: !formData.incident_log_na})}
                  style={styles.naCheckbox}>
                  <View style={[styles.checkbox, formData.incident_log_na && styles.checkboxChecked]}>
                    {formData.incident_log_na && <Check size={12} strokeWidth={2} color="#fff" />}
                  </View>
                  <Text style={styles.naCheckboxLabel}>N/A - No incidents</Text>
                </Pressable>
                {!formData.incident_log_na && (
                  <TextInput style={styles.notesInput} value={formData.incident_log}
                    onChangeText={(v) => setFormData({...formData, incident_log: v})}
                    placeholder="Record incidents..." placeholderTextColor={colors.text.subtle} multiline numberOfLines={2} />
                )}
              </GlassCard>

              {/* Superintendent Signature */}
              <View style={styles.signatureSection}>
                <View style={styles.signatureHeader}>
                  <IconPod size={36}><HardHat size={16} strokeWidth={1.5} color={semantic.neutral} /></IconPod>
                  <Text style={styles.signatureTitle}>Superintendent Sign-Off</Text>
                </View>
                <SignaturePad title="Superintendent" signerName={formData.superintendent_name}
                  onNameChange={(n) => setFormData({...formData, superintendent_name: n})}
                  existingSignature={formData.superintendent_signature}
                  onSignatureCapture={(s) => setFormData({...formData, superintendent_signature: s})} />
                {csLicenseNumber ? (
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 6 }}>
                    <Text style={{ fontSize: 14, color: colors.text.muted }}>CS LICENSE:</Text>
                    <Text
                      style={{
                        fontSize: 14,
                        color: colors.text.muted,
                        fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
                      }}
                    >
                      {csLicenseNumber}
                    </Text>
                  </View>
                ) : null}
              </View>

              <GlassButton title={saving ? 'Saving...' : hasServerLog ? 'Update Log' : 'Submit Log'}
                onPress={handleSubmit} loading={saving} style={styles.submitBtn} />
            </>
          ) : (
            /* Previous Logs */
            <>
            {/* "No Previous Logs" on a failed load asserts to a DOB inspector
                that no records exist. Say what actually happened instead. */}
            {fetchState !== 'ok' && (
              <OfflineNotice mode={fetchState} cachedCount={previousLogs.length} />
            )}
            {previousLogs.length > 0 ? (
              <View style={styles.previousList}>
                {previousLogs.map((log) => {
                  const WeatherIcon = getWeatherIcon(log.weather);
                  const signed = !!log.superintendent_signature;
                  return (
                    <GlassListItem key={log.id || log._id} onPress={() => setSelectedPreviousLog(log)} style={styles.logItem}>
                      {/* The row used to be a date on the left and a number on
                          the right with ~990px of nothing between them, and no
                          way to tell a signed log from an unsigned one without
                          opening it. It now carries what an inspector is
                          actually scanning for. */}
                      <View style={styles.logDate}><Text style={styles.logDateText}>{formatDate(log.date)}</Text></View>
                      <View style={styles.logSummary}>
                        <View style={styles.logStat}>
                          <WeatherIcon size={18} strokeWidth={1.5} color={colors.text.muted} />
                          <Text style={styles.logStatText}>{log.weather || '—'}</Text>
                        </View>
                        <View style={styles.logStat}>
                          <Users size={18} strokeWidth={1.5} color={colors.text.muted} />
                          <Text style={styles.logStatText}>{log.worker_count || 0} workers</Text>
                        </View>
                        {!!log.notes && (
                          <Text style={styles.logNotes} numberOfLines={1}>{log.notes}</Text>
                        )}
                      </View>
                      <View style={[styles.logSignState, signed ? styles.logSignedOn : styles.logSignedOff]}>
                        <PenTool
                          size={16}
                          strokeWidth={1.5}
                          color={signed ? semantic.verified : colors.text.muted}
                        />
                        <Text style={[styles.logSignText, signed && styles.logSignTextOn]}>
                          {signed ? 'Signed' : 'Unsigned'}
                        </Text>
                      </View>
                    </GlassListItem>
                  );
                })}
              </View>
            ) : fetchState === 'ok' ? (
              <GlassCard style={styles.emptyCard}>
                <History size={32} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.emptyTitle}>No Previous Logs</Text>
              </GlassCard>
            ) : null}
            </>
          )}
        </ScrollView>


        {/* Previous Log Modal */}
        <Modal visible={!!selectedPreviousLog} animationType="slide" transparent onRequestClose={() => setSelectedPreviousLog(null)}>
          <View style={styles.modalOverlay}>
            <View style={[styles.modalContent, isWide && styles.modalContentWide]}>
              <View style={styles.modalHeader}>
                <Text style={styles.modalTitle}>{selectedPreviousLog && formatDate(selectedPreviousLog.date)}</Text>
                <Pressable
                  onPress={() => setSelectedPreviousLog(null)}
                  style={styles.modalClose}
                  hitSlop={12}
                  accessibilityRole="button"
                  accessibilityLabel="Close"
                >
                  <X size={24} color={colors.text.muted} />
                </Pressable>
              </View>
              <ScrollView style={styles.modalScroll}>
                {selectedPreviousLog && (
                  <>
                    <View style={styles.modalSection}>
                      <Text style={styles.modalLabel}>WEATHER</Text>
                      <Text style={styles.modalValue}>{selectedPreviousLog.weather}</Text>
                    </View>
                    <View style={styles.modalSection}>
                      <Text style={styles.modalLabel}>WORKERS</Text>
                      <Text style={styles.modalValue}>{selectedPreviousLog.worker_count}</Text>
                    </View>
                    {selectedPreviousLog.notes && (
                      <View style={styles.modalSection}>
                        <Text style={styles.modalLabel}>NOTES</Text>
                        <Text style={styles.modalValue}>{selectedPreviousLog.notes}</Text>
                      </View>
                    )}
                    {selectedPreviousLog.safety_checklist && (
                      <View style={styles.modalSection}>
                        <Text style={styles.modalLabel}>SAFETY CHECKLIST</Text>
                        {Object.entries(selectedPreviousLog.safety_checklist).map(([k, v]) => (
                          <View key={k} style={styles.checkReview}>
                            <Text style={styles.checkReviewLabel}>{SAFETY_CHECKLIST_ITEMS.find(i => i.id === k)?.label || k}</Text>
                            <Text style={[styles.checkReviewStatus, v.status === 'checked' && {color: semantic.verified},
                              v.status === 'unchecked' && {color: semantic.neutral}]}>{v.status?.toUpperCase()}</Text>
                          </View>
                        ))}
                      </View>
                    )}
                    {selectedPreviousLog.superintendent_signature && (
                      <View style={styles.modalSection}>
                        <Text style={styles.modalLabel}>SUPERINTENDENT</Text>
                        <Text style={styles.modalValue}>{selectedPreviousLog.superintendent_signature.signer_name}</Text>
                        <Text style={styles.auditText}>Signed: {formatTimestamp(selectedPreviousLog.superintendent_signature.signed_at)}</Text>
                      </View>
                    )}
                    {selectedPreviousLog.competent_person_signature && (
                      <View style={styles.modalSection}>
                        <Text style={styles.modalLabel}>COMPETENT PERSON</Text>
                        <Text style={styles.modalValue}>{selectedPreviousLog.competent_person_signature.signer_name}</Text>
                        <Text style={styles.auditText}>Signed: {formatTimestamp(selectedPreviousLog.competent_person_signature.signed_at)}</Text>
                      </View>
                    )}
                  </>
                )}
              </ScrollView>
              <GlassButton title="Close" onPress={() => setSelectedPreviousLog(null)} style={styles.closeBtn} />
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: withAlpha('#ffffff', 0.08) },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  // 44 minimum - operated with work gloves.
  logoutBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: borderRadius.md, backgroundColor: withAlpha('#ffffff', 0.05) },
  siteBadge: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, backgroundColor: withAlpha('#94a3b8', 0.15), paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderRadius: borderRadius.full, borderWidth: 1, borderColor: withAlpha('#94a3b8', 0.3) },
  siteBadgeText: { fontSize: 14, fontWeight: '600', color: '#4ade80', letterSpacing: 0.5 },
  projectName: { fontSize: 18, fontWeight: '500', color: colors.text.primary, flex: 1 },
  tabContainer: { flexDirection: 'row', paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.sm },
  tab: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, paddingVertical: spacing.md, backgroundColor: colors.glass.background, borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border },
  tabActive: { backgroundColor: semantic.verifiedBg, borderColor: semantic.verifiedBorder },
  tabText: { fontSize: 17, fontWeight: '500', color: colors.text.muted },
  tabTextActive: { color: chrome.brand },
  badge: { backgroundColor: '#4ade80', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 10 },
  badgeText: { fontSize: 14, fontWeight: '600', color: '#fff' },
  scrollView: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 120 },
  titleSection: { marginBottom: spacing.lg },
  titleLabel: { ...typography.label, fontSize: 14, color: colors.text.muted, marginBottom: spacing.sm },
  titleText: { fontSize: 48, fontWeight: '200', color: colors.text.primary, letterSpacing: -1 },
  mb16: { marginBottom: spacing.md },
  dateCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: colors.glass.background, borderRadius: borderRadius.lg, padding: spacing.md, marginBottom: spacing.lg },
  dateText: { flex: 1, fontSize: 18, color: colors.text.primary },
  existingBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: semantic.verifiedBg, paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: borderRadius.full },
  existingText: { fontSize: 14, fontWeight: '500', color: '#4ade80' },
  // "Saved on device" — the log is safe locally but has not reached the server.
  pendingBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: withAlpha(semantic.attention, 0.15), paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: borderRadius.full, borderWidth: 1, borderColor: withAlpha(semantic.attention, 0.4) },
  pendingText: { fontSize: 14, fontWeight: '500', color: semantic.attention },
  section: { marginBottom: spacing.lg },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  sectionTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary },
  weatherGrid: { flexDirection: 'row', gap: spacing.sm },
  weatherOption: { flex: 1, alignItems: 'center', gap: spacing.xs, paddingVertical: spacing.md, backgroundColor: withAlpha('#ffffff', 0.05), borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border },
  weatherOptionSelected: { backgroundColor: semantic.verifiedBg, borderColor: chrome.brand },
  weatherLabel: { fontSize: 15, color: colors.text.muted },
  weatherLabelSelected: { color: chrome.brand },
  workerRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  workerInput: { fontSize: 28, fontWeight: '200', color: colors.text.primary, minWidth: 50, textAlign: 'center' },
  workerLabel: { fontSize: 17, color: colors.text.muted },
  notesInput: { backgroundColor: withAlpha('#ffffff', 0.05), borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border, padding: spacing.md, color: colors.text.primary, fontSize: 17, minHeight: 96, textAlignVertical: 'top' },
  checklistContainer: { gap: spacing.sm },
  checklistItem: { backgroundColor: withAlpha('#ffffff', 0.03), borderRadius: borderRadius.lg, padding: spacing.md, borderWidth: 1, borderColor: colors.glass.border },
  checklistLabel: { fontSize: 17, color: colors.text.primary, marginBottom: spacing.sm },
  checklistOptions: { flexDirection: 'row', gap: spacing.sm },
  // Was ~30px tall around a 14px icon. Fifteen of these per screen.
  checkOption: { flex: 1, alignItems: 'center', justifyContent: 'center', minHeight: 48, paddingVertical: spacing.md, backgroundColor: withAlpha('#ffffff', 0.05), borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.glass.border },
  checkOptionActive: { backgroundColor: semantic.verifiedBg, borderColor: chrome.brand },
  checkOptionUnchecked: { backgroundColor: semantic.criticalBg, borderColor: semantic.neutral },
  checkOptionNA: { backgroundColor: withAlpha('#64748b', 0.2), borderColor: colors.text.muted },
  naText: { fontSize: 15, fontWeight: '500', color: colors.text.muted },
  naTextActive: { color: colors.text.primary },
  // colors.text.subtle is the WCAG-EXEMPT placeholder/disabled token (see
  // theme.js). This line is real compliance attribution - who checked the
  // item and when - so it takes a readable token and a readable size.
  auditText: { fontSize: 14, color: colors.text.muted, marginTop: spacing.xs },
  // The ROW is the target (44 tall), not the 18px box that used to be it.
  naCheckbox: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, minHeight: 44, paddingVertical: spacing.sm, marginBottom: spacing.sm },
  checkbox: { width: 26, height: 26, borderRadius: 6, borderWidth: 1, borderColor: colors.glass.border, backgroundColor: withAlpha('#ffffff', 0.05), alignItems: 'center', justifyContent: 'center' },
  checkboxChecked: { backgroundColor: semantic.verified, borderColor: semantic.verified },
  naCheckboxLabel: { fontSize: 17, color: colors.text.secondary },
  signatureSection: { marginBottom: spacing.lg },
  signatureHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginBottom: spacing.md },
  signatureTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary },
  submitBtn: { marginTop: spacing.md, marginBottom: spacing.xxl },
  previousList: { gap: spacing.sm },
  logItem: { gap: spacing.lg, minHeight: 64 },
  logDate: { minWidth: 170 },
  logDateText: { fontSize: 18, fontWeight: '600', color: colors.text.primary },
  logSummary: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: spacing.lg, flexWrap: 'wrap' },
  logStat: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  logStatText: { fontSize: 16, color: colors.text.muted, textTransform: 'capitalize' },
  logNotes: { flex: 1, minWidth: 160, fontSize: 15, color: colors.text.muted },
  logSignState: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: borderRadius.full, borderWidth: 1 },
  logSignedOn: { backgroundColor: semantic.verifiedBg, borderColor: semantic.verifiedBorder },
  logSignedOff: { backgroundColor: 'transparent', borderColor: colors.glass.border },
  logSignText: { fontSize: 15, fontWeight: '600', color: colors.text.muted },
  logSignTextOn: { color: semantic.verified },
  emptyCard: { alignItems: 'center', paddingVertical: spacing.xxl },
  emptyTitle: { fontSize: 20, color: colors.text.muted, marginTop: spacing.md },
  modalOverlay: { flex: 1, backgroundColor: withAlpha('#000000', 0.7), justifyContent: 'center', alignItems: 'center', padding: spacing.lg },
  // Was a hardcoded '#1a1a2e' in BOTH themes, so on light the panel was
  // near-black behind dark text and the whole record was unreadable.
  // surface.menu is the opaque theme-aware token for panels that occlude.
  modalContent: { backgroundColor: surface.menu, borderRadius: borderRadius.xxl, width: '100%', maxWidth: 560, maxHeight: '80%', borderWidth: 1, borderColor: colors.glass.border },
  // A 500px card centred on a 1280px tablet used 39% of the screen to show
  // a day's compliance record.
  modalContentWide: { maxWidth: 980, maxHeight: '86%' },
  modalClose: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  modalHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.glass.border },
  modalTitle: { fontSize: 22, fontWeight: '600', color: colors.text.primary },
  modalScroll: { padding: spacing.lg },
  modalSection: { marginBottom: spacing.lg },
  modalLabel: { ...typography.label, fontSize: 14, color: colors.text.muted, marginBottom: spacing.xs },
  modalValue: { fontSize: 18, color: colors.text.primary, lineHeight: 26 },
  checkReview: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.glass.border },
  checkReviewLabel: { fontSize: 17, color: colors.text.secondary },
  checkReviewStatus: { fontSize: 15, fontWeight: '600', color: colors.text.muted },
  closeBtn: { margin: spacing.lg },
  });
}
