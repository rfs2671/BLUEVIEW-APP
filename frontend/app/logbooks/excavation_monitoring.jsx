import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, CheckCircle, Save, Calendar, AlertTriangle, Trash2 } from 'lucide-react-native';
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

const LOG_TYPE = 'excavation_monitoring';

const SOIL_TYPE_OPTIONS = ['Rock', 'Hard Clay', 'Soft Clay', 'Sand', 'Fill'];
const PROTECTION_SYSTEM_OPTIONS = ['Sloping', 'Shoring', 'Shield'];

const EMPTY_ADJACENT_BUILDING = () => ({
  address: '',
  baseline_reading: '',
  current_reading: '',
});

export default function ExcavationMonitoringLog() {
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
  const [excavationDepth, setExcavationDepth] = useState('');
  const [soilType, setSoilType] = useState('');
  const [adjacentBuildings, setAdjacentBuildings] = useState([EMPTY_ADJACENT_BUILDING()]);
  const [vibrationThreshold, setVibrationThreshold] = useState('');
  const [vibrationCurrent, setVibrationCurrent] = useState('');
  const [protectionSystem, setProtectionSystem] = useState('');
  const [groundwaterObserved, setGroundwaterObserved] = useState(false);
  const [atmosphericTesting, setAtmosphericTesting] = useState(false);

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
        if (d.excavation_depth) setExcavationDepth(d.excavation_depth);
        if (d.soil_type) setSoilType(d.soil_type);
        if (d.adjacent_buildings?.length > 0) setAdjacentBuildings(d.adjacent_buildings);
        if (d.vibration_threshold) setVibrationThreshold(d.vibration_threshold);
        if (d.vibration_current) setVibrationCurrent(d.vibration_current);
        if (d.protection_system) setProtectionSystem(d.protection_system);
        if (d.groundwater_observed != null) setGroundwaterObserved(d.groundwater_observed);
        if (d.atmospheric_testing != null) setAtmosphericTesting(d.atmospheric_testing);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const updateAdjacentBuilding = (index, field, value) => {
    setAdjacentBuildings(prev => prev.map((b, i) => i === index ? { ...b, [field]: value } : b));
  };

  const addAdjacentBuilding = () => {
    setAdjacentBuildings(prev => [...prev, EMPTY_ADJACENT_BUILDING()]);
  };

  const removeAdjacentBuilding = (index) => {
    setAdjacentBuildings(prev => prev.filter((_, i) => i !== index));
  };

  const calcDelta = (baseline, current) => {
    const b = parseFloat(baseline);
    const c = parseFloat(current);
    if (isNaN(b) || isNaN(c)) return '';
    const delta = Math.abs(c - b);
    return delta.toFixed(3);
  };

  const vibrationOverThreshold = (() => {
    const t = parseFloat(vibrationThreshold);
    const c = parseFloat(vibrationCurrent);
    if (isNaN(t) || isNaN(c)) return false;
    return c > t;
  })();

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      // Compute deltas for adjacent buildings
      const buildingsWithDelta = adjacentBuildings.map(b => ({
        ...b,
        delta: calcDelta(b.baseline_reading, b.current_reading),
      }));

      const payload = {
        project_id: projectId,
        log_type: LOG_TYPE,
        date,
        data: {
          excavation_depth: excavationDepth,
          soil_type: soilType,
          adjacent_buildings: buildingsWithDelta,
          vibration_threshold: vibrationThreshold,
          vibration_current: vibrationCurrent,
          vibration_over_threshold: vibrationOverThreshold,
          protection_system: protectionSystem,
          groundwater_observed: groundwaterObserved,
          atmospheric_testing: atmosphericTesting,
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
        submitStatus === 'submitted' ? 'Excavation log submitted successfully' : 'Draft saved'
      );
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save excavation monitoring log');
    } finally {
      setSaving(false);
    }
  };

  const ToggleRow = ({ label, value, onToggle }) => (
    <View style={s.toggleRow}>
      <Text style={s.toggleLabel}>{label}</Text>
      <Pressable onPress={onToggle}>
        <View style={[s.toggleDot, value && s.toggleDotActive]} />
      </Pressable>
    </View>
  );

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
          <Text style={s.headerTitle}>Excavation Monitoring Log</Text>
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

          {/* Excavation Details */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Excavation Details</Text>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Excavation Depth (ft)</Text>
              <TextInput
                style={s.input}
                value={excavationDepth}
                onChangeText={setExcavationDepth}
                placeholder="0"
                placeholderTextColor={colors.text.subtle}
                keyboardType="numeric"
              />
            </View>

            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Soil Type</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs }}>
                {SOIL_TYPE_OPTIONS.map((opt) => (
                  <Pressable
                    key={opt}
                    onPress={() => setSoilType(soilType === opt ? '' : opt)}
                    style={[s.chip, soilType === opt && s.chipActive]}
                  >
                    <Text style={[s.chipText, soilType === opt && s.chipTextActive]}>{opt}</Text>
                  </Pressable>
                ))}
              </View>
            </View>

            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Protection System</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs }}>
                {PROTECTION_SYSTEM_OPTIONS.map((opt) => (
                  <Pressable
                    key={opt}
                    onPress={() => setProtectionSystem(protectionSystem === opt ? '' : opt)}
                    style={[s.chip, protectionSystem === opt && s.chipActive]}
                  >
                    <Text style={[s.chipText, protectionSystem === opt && s.chipTextActive]}>{opt}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </GlassCard>

          {/* Adjacent Buildings */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Adjacent Building Monitoring</Text>
            {adjacentBuildings.map((bldg, i) => {
              const delta = calcDelta(bldg.baseline_reading, bldg.current_reading);
              return (
                <View key={i} style={s.entryCard}>
                  <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xs }}>
                    <Text style={[s.inputLabel, { marginBottom: 0 }]}>Building #{i + 1}</Text>
                    {adjacentBuildings.length > 1 && (
                      <Pressable onPress={() => removeAdjacentBuilding(i)}>
                        <Trash2 size={16} strokeWidth={1.5} color="#f87171" />
                      </Pressable>
                    )}
                  </View>
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>Address</Text>
                    <TextInput
                      style={s.input}
                      value={bldg.address}
                      onChangeText={(v) => updateAdjacentBuilding(i, 'address', v)}
                      placeholder="Building address"
                      placeholderTextColor={colors.text.subtle}
                    />
                  </View>
                  <View style={{ flexDirection: 'row', gap: spacing.sm }}>
                    <View style={{ flex: 1 }}>
                      <Text style={s.inputLabel}>Baseline</Text>
                      <TextInput
                        style={s.input}
                        value={bldg.baseline_reading}
                        onChangeText={(v) => updateAdjacentBuilding(i, 'baseline_reading', v)}
                        placeholder="0.000"
                        placeholderTextColor={colors.text.subtle}
                        keyboardType="numeric"
                      />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={s.inputLabel}>Current</Text>
                      <TextInput
                        style={s.input}
                        value={bldg.current_reading}
                        onChangeText={(v) => updateAdjacentBuilding(i, 'current_reading', v)}
                        placeholder="0.000"
                        placeholderTextColor={colors.text.subtle}
                        keyboardType="numeric"
                      />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={s.inputLabel}>Delta</Text>
                      <View style={[s.input, { paddingVertical: spacing.sm, justifyContent: 'center' }]}>
                        <Text style={{ color: delta ? colors.text.primary : colors.text.subtle }}>
                          {delta || '--'}
                        </Text>
                      </View>
                    </View>
                  </View>
                </View>
              );
            })}
            <GlassButton
              title="+ Add Building"
              onPress={addAdjacentBuilding}
              style={{ marginTop: spacing.xs }}
            />
          </GlassCard>

          {/* Vibration Monitoring */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Vibration Monitoring</Text>
            <View style={{ flexDirection: 'row', gap: spacing.sm }}>
              <View style={{ flex: 1, ...s.inputGroup }}>
                <Text style={s.inputLabel}>Threshold (in/s)</Text>
                <TextInput
                  style={s.input}
                  value={vibrationThreshold}
                  onChangeText={setVibrationThreshold}
                  placeholder="0.00"
                  placeholderTextColor={colors.text.subtle}
                  keyboardType="numeric"
                />
              </View>
              <View style={{ flex: 1, ...s.inputGroup }}>
                <Text style={s.inputLabel}>Current Reading (in/s)</Text>
                <TextInput
                  style={[s.input, vibrationOverThreshold && s.inputWarning]}
                  value={vibrationCurrent}
                  onChangeText={setVibrationCurrent}
                  placeholder="0.00"
                  placeholderTextColor={colors.text.subtle}
                  keyboardType="numeric"
                />
              </View>
            </View>
            {vibrationOverThreshold && (
              <View style={s.warningBanner}>
                <AlertTriangle size={16} strokeWidth={2} color="#f59e0b" />
                <Text style={s.warningText}>
                  Current vibration exceeds threshold! Review and take corrective action.
                </Text>
              </View>
            )}
          </GlassCard>

          {/* Environmental */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Environmental Conditions</Text>
            <ToggleRow
              label="Groundwater Observed"
              value={groundwaterObserved}
              onToggle={() => setGroundwaterObserved(!groundwaterObserved)}
            />
            <ToggleRow
              label="Atmospheric Testing Performed"
              value={atmosphericTesting}
              onToggle={() => setAtmosphericTesting(!atmosphericTesting)}
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
    inputWarning: {
      borderColor: 'rgba(245,158,11,0.6)', borderWidth: 2,
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
    chip: {
      paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
      borderRadius: borderRadius.full, borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)',
      backgroundColor: 'rgba(255,255,255,0.04)',
    },
    chipActive: { backgroundColor: 'rgba(59,130,246,0.2)', borderColor: 'rgba(59,130,246,0.5)' },
    chipText: { fontSize: 13, color: colors.text.muted },
    chipTextActive: { color: '#3b82f6', fontWeight: '600' },
    warningBanner: {
      flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
      backgroundColor: 'rgba(245,158,11,0.12)', borderRadius: borderRadius.md,
      padding: spacing.md, marginTop: spacing.sm,
      borderWidth: 1, borderColor: 'rgba(245,158,11,0.3)',
    },
    warningText: { color: '#f59e0b', fontSize: 13, fontWeight: '500', flex: 1 },
  });
}
