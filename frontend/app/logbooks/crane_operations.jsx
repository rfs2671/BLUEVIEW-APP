import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, CheckCircle, Save, Calendar, Trash2 } from 'lucide-react-native';
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

const LOG_TYPE = 'crane_operations';

const PRE_OP_CHECKLIST_ITEMS = [
  { key: 'wire_ropes', label: 'Wire Ropes Inspected' },
  { key: 'hooks_latches', label: 'Hooks & Latches Secure' },
  { key: 'brakes', label: 'Brakes Functional' },
  { key: 'outriggers', label: 'Outriggers Deployed' },
  { key: 'load_chart', label: 'Load Chart Available' },
  { key: 'boom_condition', label: 'Boom Condition OK' },
  { key: 'anti_two_block', label: 'Anti Two-Block Device' },
  { key: 'fire_extinguisher', label: 'Fire Extinguisher Present' },
  { key: 'signals_reviewed', label: 'Signals Reviewed' },
  { key: 'area_barricaded', label: 'Area Barricaded' },
  { key: 'wind_speed_checked', label: 'Wind Speed Checked' },
  { key: 'power_lines_clear', label: 'Power Lines Clear' },
  { key: 'load_weight_known', label: 'Load Weight Known' },
  { key: 'rigging_inspected', label: 'Rigging Inspected' },
  { key: 'swing_radius_clear', label: 'Swing Radius Clear' },
];

const EMPTY_LOAD_ENTRY = () => ({
  time: '',
  description: '',
  load_weight: '',
  radius: '',
});

export default function CraneOperationsLog() {
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
  const [craneType, setCraneType] = useState('');
  const [craneId, setCraneId] = useState('');
  const [operatorName, setOperatorName] = useState('');
  const [operatorLicense, setOperatorLicense] = useState('');
  const [preOpChecklist, setPreOpChecklist] = useState({});
  const [loadEntries, setLoadEntries] = useState([EMPTY_LOAD_ENTRY()]);

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
        if (d.crane_type) setCraneType(d.crane_type);
        if (d.crane_id) setCraneId(d.crane_id);
        if (d.operator_name) setOperatorName(d.operator_name);
        if (d.operator_license) setOperatorLicense(d.operator_license);
        if (d.pre_operation_checklist) setPreOpChecklist(d.pre_operation_checklist);
        if (d.load_entries?.length > 0) setLoadEntries(d.load_entries);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const togglePreOp = (key) => {
    setPreOpChecklist(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const updateLoadEntry = (index, field, value) => {
    setLoadEntries(prev => prev.map((entry, i) => i === index ? { ...entry, [field]: value } : entry));
  };

  const addLoadEntry = () => setLoadEntries(prev => [...prev, EMPTY_LOAD_ENTRY()]);

  const removeLoadEntry = (index) => {
    setLoadEntries(prev => prev.filter((_, i) => i !== index));
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      const payload = {
        project_id: projectId,
        log_type: LOG_TYPE,
        date,
        data: {
          crane_type: craneType,
          crane_id: craneId,
          operator_name: operatorName,
          operator_license: operatorLicense,
          pre_operation_checklist: preOpChecklist,
          load_entries: loadEntries,
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
        submitStatus === 'submitted' ? 'Crane log submitted successfully' : 'Draft saved'
      );
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save crane operations log');
    } finally {
      setSaving(false);
    }
  };

  const checklistComplete = PRE_OP_CHECKLIST_ITEMS.filter(item => preOpChecklist[item.key]).length;
  const checklistTotal = PRE_OP_CHECKLIST_ITEMS.length;

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
          <Text style={s.headerTitle}>Crane Operations Log</Text>
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

          {/* Crane & Operator Info */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Crane Information</Text>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Crane Type</Text>
              <TextInput
                style={s.input}
                value={craneType}
                onChangeText={setCraneType}
                placeholder="e.g., Tower Crane, Mobile Crane..."
                placeholderTextColor={colors.text.subtle}
              />
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Crane ID / Serial Number</Text>
              <TextInput
                style={s.input}
                value={craneId}
                onChangeText={setCraneId}
                placeholder="Equipment ID"
                placeholderTextColor={colors.text.subtle}
              />
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Operator Name</Text>
              <TextInput
                style={s.input}
                value={operatorName}
                onChangeText={setOperatorName}
                placeholder="Full name"
                placeholderTextColor={colors.text.subtle}
              />
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Operator License Number</Text>
              <TextInput
                style={s.input}
                value={operatorLicense}
                onChangeText={setOperatorLicense}
                placeholder="License #"
                placeholderTextColor={colors.text.subtle}
              />
            </View>
          </GlassCard>

          {/* Pre-Operation Checklist */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>
              Pre-Operation Checklist ({checklistComplete}/{checklistTotal})
            </Text>
            {PRE_OP_CHECKLIST_ITEMS.map((item) => (
              <View key={item.key} style={s.toggleRow}>
                <Text style={s.toggleLabel}>{item.label}</Text>
                <Pressable onPress={() => togglePreOp(item.key)}>
                  <View style={[s.toggleDot, preOpChecklist[item.key] && s.toggleDotActive]} />
                </Pressable>
              </View>
            ))}
          </GlassCard>

          {/* Load Log */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Load Log</Text>
            {loadEntries.map((entry, i) => (
              <View key={i} style={s.entryCard}>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xs }}>
                  <Text style={[s.inputLabel, { marginBottom: 0 }]}>Lift #{i + 1}</Text>
                  {loadEntries.length > 1 && (
                    <Pressable onPress={() => removeLoadEntry(i)}>
                      <Trash2 size={16} strokeWidth={1.5} color="#f87171" />
                    </Pressable>
                  )}
                </View>
                <View style={s.entryRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.inputLabel}>Time</Text>
                    <TextInput
                      style={s.input}
                      value={entry.time}
                      onChangeText={(v) => updateLoadEntry(i, 'time', v)}
                      placeholder="HH:MM"
                      placeholderTextColor={colors.text.subtle}
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.inputLabel}>Weight (lbs)</Text>
                    <TextInput
                      style={s.input}
                      value={entry.load_weight}
                      onChangeText={(v) => updateLoadEntry(i, 'load_weight', v)}
                      placeholder="0"
                      placeholderTextColor={colors.text.subtle}
                      keyboardType="numeric"
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.inputLabel}>Radius (ft)</Text>
                    <TextInput
                      style={s.input}
                      value={entry.radius}
                      onChangeText={(v) => updateLoadEntry(i, 'radius', v)}
                      placeholder="0"
                      placeholderTextColor={colors.text.subtle}
                      keyboardType="numeric"
                    />
                  </View>
                </View>
                <View style={s.inputGroup}>
                  <Text style={s.inputLabel}>Description</Text>
                  <TextInput
                    style={s.input}
                    value={entry.description}
                    onChangeText={(v) => updateLoadEntry(i, 'description', v)}
                    placeholder="Load description..."
                    placeholderTextColor={colors.text.subtle}
                  />
                </View>
              </View>
            ))}
            <GlassButton
              title="+ Add Load Entry"
              onPress={addLoadEntry}
              style={{ marginTop: spacing.xs }}
            />
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
    entryCard: {
      borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)', borderRadius: borderRadius.lg,
      padding: spacing.md, marginBottom: spacing.sm, gap: spacing.sm,
    },
    entryRow: { flexDirection: 'row', gap: spacing.sm },
  });
}
