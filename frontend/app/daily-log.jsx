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
  LogOut,
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
import { useProjects } from '../src/hooks/useProjects';
import { useDailyLogs } from '../src/hooks/useDailyLogs';
import OfflineIndicator from '../src/components/OfflineIndicator';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { useTheme } from '../src/context/ThemeContext';

const weatherOptions = [
  { value: 'sunny', label: 'Sunny', icon: Sun },
  { value: 'cloudy', label: 'Cloudy', icon: Cloud },
  { value: 'rainy', label: 'Rainy', icon: CloudRain },
  { value: 'windy', label: 'Windy', icon: Wind },
];

const SAFETY_CHECKLIST_ITEMS = [
  { id: 'fall_protection', label: 'Fall Protection' },
  { id: 'scaffolding', label: 'Scaffolding' },
  { id: 'ppe', label: 'PPE (Personal Protective Equipment)' },
  { id: 'hazards', label: 'Hazard Identification' },
  { id: 'base_conditions', label: 'Base Conditions' },
];

export default function DailyLogScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
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
  const { dailyLogs, loading: logsLoading, createDailyLog, updateDailyLog } = useDailyLogs(selectedProject?._id || selectedProject?.id);

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

  const fetchLogsForProject = async (projectId) => {
    try {
      setAllLogs(dailyLogs);
      const today = new Date().toISOString().split('T')[0];
      const todayLog = dailyLogs.find((l) => l.date === today);
      
      if (todayLog) {
        setExistingLog(todayLog);
        populateFormFromLog(todayLog);
      } else {
        setExistingLog(null);
        resetForm();
      }
    } catch (error) {
      console.error('Failed to fetch logs:', error);
      setAllLogs([]);
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
    try {
      const today = new Date().toISOString().split('T')[0];
      const logData = {
        project_id: selectedProject._id || selectedProject.id,
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
      if (existingLog) {
        await updateDailyLog(existingLog.id || existingLog._id, logData);
        toast.success('Updated', 'Daily log updated successfully');
      } else {
        const newLog = await createDailyLog(logData);
        setExistingLog(newLog);
        toast.success('Created', 'Daily log created successfully');
      }
      await fetchLogsForProject(selectedProject._id || selectedProject.id);
    } catch (error) {
      console.error('Failed to save log:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not save daily log');
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
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
    (log) => log.date !== new Date().toISOString().split('T')[0]
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
              color={checkData.status === 'checked' ? '#4ade80' : colors.text.muted}
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
              color={checkData.status === 'unchecked' ? '#ef4444' : colors.text.muted}
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
                <Building2 size={14} strokeWidth={1.5} color="#4ade80" />
                <Text style={s.siteBadgeText}>SITE MODE</Text>
              </View>
            ) : isAdmin ? (
              <View style={[s.siteBadge, s.viewOnlyBadge]}>
                <Eye size={14} strokeWidth={1.5} color="#3b82f6" />
                <Text style={[s.siteBadgeText, s.viewOnlyText]}>VIEW ONLY</Text>
              </View>
            ) : (
              <Image source={require('../assets/logo-header.png')} style={{ width: 180, height: 48, resizeMode: 'contain' }} />
            )}
          </View>
          <View style={s.headerRight}>
            <OfflineIndicator />
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
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
                color={activeTab === 'today' ? '#4ade80' : colors.text.muted}
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
                color={activeTab === 'previous' ? '#4ade80' : colors.text.muted}
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
                              <PenTool size={10} strokeWidth={1.5} color="#4ade80" />
                            </View>
                          )}
                        </View>
                      </GlassListItem>
                    );
                  })}
                </View>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <IconPod size={64}>
                    <History size={28} strokeWidth={1.5} color={colors.text.muted} />
                  </IconPod>
                  <Text style={s.emptyTitle}>No Logs Found</Text>
                  <Text style={s.emptyText}>
                    Daily logs for this project will appear here.
                  </Text>
                </GlassCard>
              )}
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
                          color={isSelected ? '#4ade80' : colors.text.muted}
                        />
                        <Text style={[s.weatherLabel, isSelected && s.weatherLabelSelected]}>
                          {option.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </GlassCard>

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
                  <ShieldCheck size={20} strokeWidth={1.5} color="#f59e0b" />
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
                  <AlertTriangle size={20} strokeWidth={1.5} color="#ef4444" />
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
                        <HardHat size={18} strokeWidth={1.5} color="#f59e0b" />
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
                        <Text style={s.modalValue}>{selectedPreviousLog.notes}</Text>
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
    borderBottomColor: 'rgba(255, 255, 255, 0.08)',
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
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(74, 222, 128, 0.3)',
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
    backgroundColor: 'rgba(74, 222, 128, 0.1)',
    borderColor: 'rgba(74, 222, 128, 0.3)',
  },
  tabText: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.muted,
  },
  tabTextActive: {
    color: '#4ade80',
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
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
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
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.full,
  },
  existingText: {
    fontSize: 11,
    fontWeight: '500',
    color: '#4ade80',
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
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  weatherOptionSelected: {
    backgroundColor: 'rgba(74, 222, 128, 0.1)',
    borderColor: '#4ade80',
  },
  weatherLabel: {
    fontSize: 12,
    color: colors.text.muted,
  },
  weatherLabelSelected: {
    color: '#4ade80',
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
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
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
    backgroundColor: 'rgba(255, 255, 255, 0.03)',
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
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  checkOptionActive: {
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
    borderColor: '#4ade80',
  },
  checkOptionUnchecked: {
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
    borderColor: '#ef4444',
  },
  checkOptionNA: {
    backgroundColor: 'rgba(100, 116, 139, 0.2)',
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
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxChecked: {
    backgroundColor: '#4ade80',
    borderColor: '#4ade80',
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
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
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
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
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
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
  },
  statusUnchecked: {
    backgroundColor: 'rgba(239, 68, 68, 0.15)',
  },
  statusNA: {
    backgroundColor: 'rgba(100, 116, 139, 0.2)',
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
