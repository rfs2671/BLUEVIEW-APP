import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, CheckCircle, Save, Calendar, Flame } from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

const LOG_TYPE = 'hot_work';

const WORK_TYPE_OPTIONS = ['Welding', 'Cutting', 'Brazing', 'Soldering', 'Other'];

const PRECAUTION_ITEMS = [
  { key: 'area_cleared', label: 'Area Cleared of Combustibles (35ft)' },
  { key: 'fire_extinguisher_present', label: 'Fire Extinguisher Present' },
  { key: 'sprinklers_operational', label: 'Sprinklers Operational' },
  { key: 'combustibles_covered', label: 'Combustibles Covered/Protected' },
  { key: 'fire_watch_assigned', label: 'Fire Watch Assigned' },
  { key: 'ventilation_adequate', label: 'Ventilation Adequate' },
  { key: 'permit_posted', label: 'Permit Posted at Location' },
];

/**
 * Calculate fire watch end time = end_time + 30 minutes.
 * Expects end_time in "HH:MM" format. Returns "HH:MM" or empty string.
 */
const calcFireWatchEnd = (endTime) => {
  if (!endTime || !endTime.includes(':')) return '';
  try {
    const [hh, mm] = endTime.split(':').map(Number);
    if (isNaN(hh) || isNaN(mm)) return '';
    const totalMin = hh * 60 + mm + 30;
    const h = Math.floor(totalMin / 60) % 24;
    const m = totalMin % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  } catch {
    return '';
  }
};

export default function HotWorkPermitLog() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);

  // Form fields
  const [workType, setWorkType] = useState('');
  const [location, setLocation] = useState('');
  const [workerName, setWorkerName] = useState('');
  const [workerCertNumber, setWorkerCertNumber] = useState('');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [fireWatchName, setFireWatchName] = useState('');
  const [precautions, setPrecautions] = useState({});

  const fireWatchEndTime = calcFireWatchEnd(endTime);

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const existingLogs = await logbooksAPI.getByProject(projectId, LOG_TYPE, date).catch(() => []);

      const existing = Array.isArray(existingLogs) && existingLogs.length > 0 ? existingLogs[0] : null;
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.work_type) setWorkType(d.work_type);
        if (d.location) setLocation(d.location);
        if (d.worker_name) setWorkerName(d.worker_name);
        if (d.worker_cert_number) setWorkerCertNumber(d.worker_cert_number);
        if (d.start_time) setStartTime(d.start_time);
        if (d.end_time) setEndTime(d.end_time);
        if (d.fire_watch_name) setFireWatchName(d.fire_watch_name);
        if (d.precautions) setPrecautions(d.precautions);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const togglePrecaution = (key) => {
    setPrecautions(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      const payload = {
        project_id: projectId,
        log_type: LOG_TYPE,
        date,
        data: {
          work_type: workType,
          location,
          worker_name: workerName,
          worker_cert_number: workerCertNumber,
          start_time: startTime,
          end_time: endTime,
          fire_watch_end_time: fireWatchEndTime,
          fire_watch_name: fireWatchName,
          precautions,
        },
        cp_signature: cpSignature,
        cp_name: cpName,
        status: submitStatus,
      };

      let savedId = existingLogId;
      if (existingLogId) {
        await logbooksAPI.update(existingLogId, {
          data: payload.data,
          cp_signature: cpSignature,
          cp_name: cpName,
          status: submitStatus,
        });
      } else {
        const created = await logbooksAPI.create(payload);
        savedId = created.id || created._id;
        setExistingLogId(savedId);
      }

      await autoSave(cpName, cpSignature);

      if (submitStatus === 'submitted' && cpSignature && savedId) {
        recordSignatureEvent({
          documentType: 'logbook',
          documentId: savedId,
          eventType: 'cp_sign',
          signerName: cpName,
          signerRole: user?.role || 'cp',
          signatureData: cpSignature,
          contentSnapshot: {
            log_type: LOG_TYPE,
            date,
            project_id: projectId,
            data: payload.data,
            status: submitStatus,
          },
          user,
        }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
      }

      toast.success(
        submitStatus === 'submitted' ? 'Submitted' : 'Draft Saved',
        submitStatus === 'submitted' ? 'Hot work permit submitted successfully' : 'Draft saved'
      );
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save hot work permit log');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingContainer}>
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
          <GlassButton
            variant="icon"
            icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => router.back()}
          />
          <Text style={s.headerTitle}>Hot Work Permit Log</Text>
        </View>

        <ScrollView
          style={{ flex: 1 }}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Date */}
          <GlassCard style={s.section}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
              <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>
                {new Date(date).toLocaleDateString('en-US', {
                  weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
                })}
              </Text>
            </View>
          </GlassCard>

          {/* Work Type Picker */}
          <GlassCard style={s.section}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm }}>
              <Flame size={16} strokeWidth={1.5} color="#f59e0b" />
              <Text style={s.sectionTitle}>Type of Hot Work</Text>
            </View>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs }}>
              {WORK_TYPE_OPTIONS.map((opt) => (
                <Pressable
                  key={opt}
                  onPress={() => setWorkType(workType === opt ? '' : opt)}
                  style={[s.chip, workType === opt && s.chipActive]}
                >
                  <Text style={[s.chipText, workType === opt && s.chipTextActive]}>{opt}</Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Location & Worker */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Work Details</Text>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Location</Text>
              <TextInput
                style={s.input}
                value={location}
                onChangeText={setLocation}
                placeholder="Floor, area, or room..."
                placeholderTextColor={colors.text.subtle}
              />
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Worker Name</Text>
              <TextInput
                style={s.input}
                value={workerName}
                onChangeText={setWorkerName}
                placeholder="Full name of worker performing hot work"
                placeholderTextColor={colors.text.subtle}
              />
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Worker Certification Number</Text>
              <TextInput
                style={s.input}
                value={workerCertNumber}
                onChangeText={setWorkerCertNumber}
                placeholder="Cert #"
                placeholderTextColor={colors.text.subtle}
              />
            </View>
          </GlassCard>

          {/* Timing */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Timing</Text>
            <View style={{ flexDirection: 'row', gap: spacing.sm }}>
              <View style={{ flex: 1, ...s.inputGroup }}>
                <Text style={s.inputLabel}>Start Time</Text>
                <TextInput
                  style={s.input}
                  value={startTime}
                  onChangeText={setStartTime}
                  placeholder="HH:MM"
                  placeholderTextColor={colors.text.subtle}
                />
              </View>
              <View style={{ flex: 1, ...s.inputGroup }}>
                <Text style={s.inputLabel}>End Time</Text>
                <TextInput
                  style={s.input}
                  value={endTime}
                  onChangeText={setEndTime}
                  placeholder="HH:MM"
                  placeholderTextColor={colors.text.subtle}
                />
              </View>
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Fire Watch End Time (auto: end + 30 min)</Text>
              <View style={[s.input, { paddingVertical: spacing.sm }]}>
                <Text style={{ color: fireWatchEndTime ? colors.text.primary : colors.text.subtle }}>
                  {fireWatchEndTime || 'Enter end time above'}
                </Text>
              </View>
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Fire Watch Person Name</Text>
              <TextInput
                style={s.input}
                value={fireWatchName}
                onChangeText={setFireWatchName}
                placeholder="Full name"
                placeholderTextColor={colors.text.subtle}
              />
            </View>
          </GlassCard>

          {/* Precautions Checklist */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Precautions Checklist</Text>
            {PRECAUTION_ITEMS.map((item) => (
              <View key={item.key} style={s.toggleRow}>
                <Text style={s.toggleLabel}>{item.label}</Text>
                <Pressable onPress={() => togglePrecaution(item.key)}>
                  <View style={[s.toggleDot, precautions[item.key] && s.toggleDotActive]} />
                </Pressable>
              </View>
            ))}
          </GlassCard>

          {/* CP Signature */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Competent Person Sign-Off</Text>
            <SignaturePad
              title="CP Signature"
              signerName={cpName}
              onNameChange={setCpName}
              existingSignature={cpSignature}
              onSignatureCapture={setCpSignature}
            />
          </GlassCard>

          {/* Actions */}
          <View style={s.buttonRow}>
            <GlassButton
              title={saving ? 'Saving...' : 'Save Draft'}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => handleSave('draft')}
              loading={saving}
              style={{ flex: 1 }}
            />
            <GlassButton
              title={saving ? 'Saving...' : 'Submit'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
              onPress={() => handleSave('submitted')}
              loading={saving}
              style={{ flex: 1, backgroundColor: '#4ade80', borderColor: '#4ade80' }}
            />
          </View>
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },
    header: { flexDirection: 'row', alignItems: 'center', padding: spacing.lg, gap: spacing.md },
    headerTitle: { fontSize: 20, fontWeight: '700', color: colors.text.primary, flex: 1 },
    section: { marginBottom: spacing.md },
    sectionTitle: { ...typography.label, color: colors.text.muted, marginBottom: spacing.sm },
    inputGroup: { marginBottom: spacing.md },
    inputLabel: { ...typography.label, color: colors.text.muted, marginBottom: 4 },
    input: {
      backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: borderRadius.md,
      padding: spacing.sm, color: colors.text.primary,
      borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)',
    },
    textArea: { minHeight: 80, textAlignVertical: 'top' },
    toggleRow: {
      flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
      paddingVertical: spacing.sm,
    },
    toggleLabel: { color: colors.text.secondary, fontSize: 14 },
    toggleDot: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.text.subtle },
    toggleDotActive: { backgroundColor: '#4ade80', borderColor: '#4ade80' },
    buttonRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
    loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' },
    chip: {
      paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
      borderRadius: borderRadius.full, borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)',
      backgroundColor: 'rgba(255,255,255,0.04)',
    },
    chipActive: { backgroundColor: 'rgba(245,158,11,0.2)', borderColor: 'rgba(245,158,11,0.5)' },
    chipText: { fontSize: 13, color: colors.text.muted },
    chipTextActive: { color: '#f59e0b', fontWeight: '600' },
  });
}
