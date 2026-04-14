import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  Modal,
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
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { dailyLogsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

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

export default function SiteDailyLogsScreen() {
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
  const toast = useToast();

  const [activeTab, setActiveTab] = useState('today');
  const [loading, setLoading] = useState(true);
  const [allLogs, setAllLogs] = useState([]);
  const [existingLog, setExistingLog] = useState(null);
  const [saving, setSaving] = useState(false);
  const [selectedPreviousLog, setSelectedPreviousLog] = useState(null);

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

  const fetchLogs = async () => {
    if (!siteProject?.id) return;
    setLoading(true);
    try {
      const logs = await dailyLogsAPI.getByProject(siteProject.id);
      const logsList = Array.isArray(logs) ? logs : [];
      setAllLogs(logsList);

      const today = new Date().toISOString().split('T')[0];
      const todayLog = logsList.find((l) => l.date === today);
      
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
    try {
      const today = new Date().toISOString().split('T')[0];
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

      if (existingLog) {
        await dailyLogsAPI.update(existingLog.id || existingLog._id, logData);
        toast.success('Updated', 'Daily log updated');
      } else {
        const newLog = await dailyLogsAPI.create(logData);
        setExistingLog(newLog);
        toast.success('Created', 'Daily log created');
      }
      fetchLogs();
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
    (log) => log.date !== new Date().toISOString().split('T')[0]
  );

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
            <CheckCircle size={14} strokeWidth={1.5} color={checkData.status === 'checked' ? '#4ade80' : colors.text.muted} />
          </Pressable>
          <Pressable
            onPress={() => handleSafetyCheckChange(item.id, 'unchecked')}
            style={[styles.checkOption, checkData.status === 'unchecked' && styles.checkOptionUnchecked]}
          >
            <XCircle size={14} strokeWidth={1.5} color={checkData.status === 'unchecked' ? '#ef4444' : colors.text.muted} />
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
              <Building2 size={14} strokeWidth={1.5} color="#4ade80" />
              <Text style={styles.siteBadgeText}>SITE DEVICE</Text>
            </View>
            <Text style={styles.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
          </View>
        </View>

        <View style={styles.tabContainer}>
          <Pressable
            onPress={() => setActiveTab('today')}
            style={[styles.tab, activeTab === 'today' && styles.tabActive]}
          >
            <ClipboardList size={16} strokeWidth={1.5} color={activeTab === 'today' ? '#4ade80' : colors.text.muted} />
            <Text style={[styles.tabText, activeTab === 'today' && styles.tabTextActive]}>Today</Text>
          </Pressable>
          <Pressable
            onPress={() => setActiveTab('previous')}
            style={[styles.tab, activeTab === 'previous' && styles.tabActive]}
          >
            <History size={16} strokeWidth={1.5} color={activeTab === 'previous' ? '#4ade80' : colors.text.muted} />
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
                {existingLog && (
                  <View style={styles.existingBadge}>
                    <Check size={12} strokeWidth={2} color="#4ade80" />
                    <Text style={styles.existingText}>Saved</Text>
                  </View>
                )}
              </View>

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
                        <Icon size={20} strokeWidth={1.5} color={isSelected ? '#4ade80' : colors.text.muted} />
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
                  <ShieldCheck size={18} strokeWidth={1.5} color="#f59e0b" />
                  <Text style={styles.sectionTitle}>Safety Checklist</Text>
                </View>
                <View style={styles.checklistContainer}>
                  {SAFETY_CHECKLIST_ITEMS.map(renderSafetyCheckItem)}
                </View>
              </GlassCard>

              {/* Corrective Actions */}
              <GlassCard style={styles.section}>
                <View style={styles.sectionHeader}>
                  <AlertTriangle size={18} strokeWidth={1.5} color="#ef4444" />
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
                  <IconPod size={36}><HardHat size={16} strokeWidth={1.5} color="#f59e0b" /></IconPod>
                  <Text style={styles.signatureTitle}>Superintendent Sign-Off</Text>
                </View>
                <SignaturePad title="Superintendent" signerName={formData.superintendent_name}
                  onNameChange={(n) => setFormData({...formData, superintendent_name: n})}
                  existingSignature={formData.superintendent_signature}
                  onSignatureCapture={(s) => setFormData({...formData, superintendent_signature: s})} />
              </View>

              <GlassButton title={saving ? 'Saving...' : existingLog ? 'Update Log' : 'Submit Log'}
                onPress={handleSubmit} loading={saving} style={styles.submitBtn} />
            </>
          ) : (
            /* Previous Logs */
            previousLogs.length > 0 ? (
              <View style={styles.previousList}>
                {previousLogs.map((log) => {
                  const WeatherIcon = getWeatherIcon(log.weather);
                  return (
                    <GlassListItem key={log.id || log._id} onPress={() => setSelectedPreviousLog(log)} style={styles.logItem}>
                      <View style={styles.logDate}><Text style={styles.logDateText}>{formatDate(log.date)}</Text></View>
                      <View style={styles.logStats}>
                        <WeatherIcon size={14} strokeWidth={1.5} color={colors.text.muted} />
                        <Users size={14} strokeWidth={1.5} color={colors.text.muted} />
                        <Text style={styles.logStatText}>{log.worker_count || 0}</Text>
                        {log.superintendent_signature && <PenTool size={12} strokeWidth={1.5} color="#4ade80" />}
                      </View>
                    </GlassListItem>
                  );
                })}
              </View>
            ) : (
              <GlassCard style={styles.emptyCard}>
                <History size={32} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.emptyTitle}>No Previous Logs</Text>
              </GlassCard>
            )
          )}
        </ScrollView>


        {/* Previous Log Modal */}
        <Modal visible={!!selectedPreviousLog} animationType="slide" transparent onRequestClose={() => setSelectedPreviousLog(null)}>
          <View style={styles.modalOverlay}>
            <View style={styles.modalContent}>
              <View style={styles.modalHeader}>
                <Text style={styles.modalTitle}>{selectedPreviousLog && formatDate(selectedPreviousLog.date)}</Text>
                <Pressable onPress={() => setSelectedPreviousLog(null)}><X size={24} color={colors.text.muted} /></Pressable>
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
                            <Text style={[styles.checkReviewStatus, v.status === 'checked' && {color: '#4ade80'},
                              v.status === 'unchecked' && {color: '#ef4444'}]}>{v.status?.toUpperCase()}</Text>
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

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.08)' },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  siteBadge: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, backgroundColor: 'rgba(74,222,128,0.15)', paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderRadius: borderRadius.full, borderWidth: 1, borderColor: 'rgba(74,222,128,0.3)' },
  siteBadgeText: { fontSize: 10, fontWeight: '600', color: '#4ade80', letterSpacing: 0.5 },
  projectName: { fontSize: 16, fontWeight: '500', color: colors.text.primary, flex: 1 },
  tabContainer: { flexDirection: 'row', paddingHorizontal: spacing.lg, paddingVertical: spacing.md, gap: spacing.sm },
  tab: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, paddingVertical: spacing.md, backgroundColor: colors.glass.background, borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border },
  tabActive: { backgroundColor: 'rgba(74,222,128,0.1)', borderColor: 'rgba(74,222,128,0.3)' },
  tabText: { fontSize: 14, fontWeight: '500', color: colors.text.muted },
  tabTextActive: { color: '#4ade80' },
  badge: { backgroundColor: '#4ade80', paddingHorizontal: 6, paddingVertical: 2, borderRadius: 10 },
  badgeText: { fontSize: 11, fontWeight: '600', color: '#fff' },
  scrollView: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 120 },
  titleSection: { marginBottom: spacing.lg },
  titleLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.sm },
  titleText: { fontSize: 48, fontWeight: '200', color: colors.text.primary, letterSpacing: -1 },
  mb16: { marginBottom: spacing.md },
  dateCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, backgroundColor: colors.glass.background, borderRadius: borderRadius.lg, padding: spacing.md, marginBottom: spacing.lg },
  dateText: { flex: 1, fontSize: 15, color: colors.text.primary },
  existingBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, backgroundColor: 'rgba(74,222,128,0.15)', paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: borderRadius.full },
  existingText: { fontSize: 11, fontWeight: '500', color: '#4ade80' },
  section: { marginBottom: spacing.lg },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  sectionTitle: { fontSize: 16, fontWeight: '500', color: colors.text.primary },
  weatherGrid: { flexDirection: 'row', gap: spacing.sm },
  weatherOption: { flex: 1, alignItems: 'center', gap: spacing.xs, paddingVertical: spacing.md, backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border },
  weatherOptionSelected: { backgroundColor: 'rgba(74,222,128,0.1)', borderColor: '#4ade80' },
  weatherLabel: { fontSize: 11, color: colors.text.muted },
  weatherLabelSelected: { color: '#4ade80' },
  workerRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  workerInput: { fontSize: 28, fontWeight: '200', color: colors.text.primary, minWidth: 50, textAlign: 'center' },
  workerLabel: { fontSize: 14, color: colors.text.muted },
  notesInput: { backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border, padding: spacing.md, color: colors.text.primary, fontSize: 14, minHeight: 80, textAlignVertical: 'top' },
  checklistContainer: { gap: spacing.sm },
  checklistItem: { backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: borderRadius.lg, padding: spacing.md, borderWidth: 1, borderColor: colors.glass.border },
  checklistLabel: { fontSize: 14, color: colors.text.primary, marginBottom: spacing.sm },
  checklistOptions: { flexDirection: 'row', gap: spacing.sm },
  checkOption: { flex: 1, alignItems: 'center', paddingVertical: spacing.sm, backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.glass.border },
  checkOptionActive: { backgroundColor: 'rgba(74,222,128,0.15)', borderColor: '#4ade80' },
  checkOptionUnchecked: { backgroundColor: 'rgba(239,68,68,0.15)', borderColor: '#ef4444' },
  checkOptionNA: { backgroundColor: 'rgba(100,116,139,0.2)', borderColor: colors.text.muted },
  naText: { fontSize: 11, fontWeight: '500', color: colors.text.muted },
  naTextActive: { color: colors.text.primary },
  auditText: { fontSize: 10, color: colors.text.subtle, marginTop: spacing.xs },
  naCheckbox: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.md },
  checkbox: { width: 18, height: 18, borderRadius: 4, borderWidth: 1, borderColor: colors.glass.border, backgroundColor: 'rgba(255,255,255,0.05)', alignItems: 'center', justifyContent: 'center' },
  checkboxChecked: { backgroundColor: '#4ade80', borderColor: '#4ade80' },
  naCheckboxLabel: { fontSize: 13, color: colors.text.secondary },
  signatureSection: { marginBottom: spacing.lg },
  signatureHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginBottom: spacing.md },
  signatureTitle: { fontSize: 15, fontWeight: '500', color: colors.text.primary },
  submitBtn: { marginTop: spacing.md, marginBottom: spacing.xxl },
  previousList: { gap: spacing.sm },
  logItem: { gap: spacing.md },
  logDate: { minWidth: 100 },
  logDateText: { fontSize: 14, color: colors.text.primary },
  logStats: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: spacing.md },
  logStatText: { fontSize: 13, color: colors.text.muted },
  emptyCard: { alignItems: 'center', paddingVertical: spacing.xxl },
  emptyTitle: { fontSize: 16, color: colors.text.muted, marginTop: spacing.md },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'center', alignItems: 'center', padding: spacing.lg },
  modalContent: { backgroundColor: '#1a1a2e', borderRadius: borderRadius.xxl, width: '100%', maxWidth: 500, maxHeight: '80%', borderWidth: 1, borderColor: colors.glass.border },
  modalHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.glass.border },
  modalTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary },
  modalScroll: { padding: spacing.lg },
  modalSection: { marginBottom: spacing.lg },
  modalLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.xs },
  modalValue: { fontSize: 15, color: colors.text.primary },
  checkReview: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.glass.border },
  checkReviewLabel: { fontSize: 13, color: colors.text.secondary },
  checkReviewStatus: { fontSize: 11, fontWeight: '600', color: colors.text.muted },
  closeBtn: { margin: spacing.lg },
});
