import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, CheckCircle, Save, Plus, Calendar, Trash2 } from 'lucide-react-native';
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

const LOG_TYPE = 'concrete_operations';

const WEATHER_OPTIONS = ['Sunny', 'Cloudy', 'Rainy', 'Windy', 'Snow', 'Fog', 'Stormy'];

const FORMWORK_ITEMS = [
  { key: 'shores_plumb', label: 'Shores Plumb' },
  { key: 'bracing_adequate', label: 'Bracing Adequate' },
  { key: 'formwork_clean', label: 'Formwork Clean' },
  { key: 'no_gaps', label: 'No Gaps' },
];

const EMPTY_SLUMP_TEST = () => ({
  time: '',
  value: '',
  pass: null,
});

export default function ConcreteOperationsLog() {
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
  const [pourLocation, setPourLocation] = useState('');
  const [concreteSupplier, setConcreteSupplier] = useState('');
  const [mixDesign, setMixDesign] = useState('');
  const [volumeOrdered, setVolumeOrdered] = useState('');
  const [slumpTests, setSlumpTests] = useState([EMPTY_SLUMP_TEST()]);
  const [formworkChecklist, setFormworkChecklist] = useState({});
  const [weatherConditions, setWeatherConditions] = useState('');
  const [temperature, setTemperature] = useState('');

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
        if (d.pour_location) setPourLocation(d.pour_location);
        if (d.concrete_supplier) setConcreteSupplier(d.concrete_supplier);
        if (d.mix_design) setMixDesign(d.mix_design);
        if (d.volume_ordered) setVolumeOrdered(d.volume_ordered);
        if (d.slump_tests?.length > 0) setSlumpTests(d.slump_tests);
        if (d.formwork_checklist) setFormworkChecklist(d.formwork_checklist);
        if (d.weather_conditions) setWeatherConditions(d.weather_conditions);
        if (d.temperature) setTemperature(d.temperature);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const updateSlumpTest = (index, field, value) => {
    setSlumpTests(prev => prev.map((t, i) => i === index ? { ...t, [field]: value } : t));
  };

  const addSlumpTest = () => setSlumpTests(prev => [...prev, EMPTY_SLUMP_TEST()]);

  const removeSlumpTest = (index) => {
    setSlumpTests(prev => prev.filter((_, i) => i !== index));
  };

  const toggleFormwork = (key) => {
    setFormworkChecklist(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      const payload = {
        project_id: projectId,
        log_type: LOG_TYPE,
        date,
        data: {
          pour_location: pourLocation,
          concrete_supplier: concreteSupplier,
          mix_design: mixDesign,
          volume_ordered: volumeOrdered,
          slump_tests: slumpTests,
          formwork_checklist: formworkChecklist,
          weather_conditions: weatherConditions,
          temperature,
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
        submitStatus === 'submitted' ? 'Concrete log submitted successfully' : 'Draft saved'
      );
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save concrete operations log');
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
          <Text style={s.headerTitle}>Concrete Operations Log</Text>
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

          {/* Pour Details */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Pour Details</Text>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Pour Location</Text>
              <TextInput
                style={s.input}
                value={pourLocation}
                onChangeText={setPourLocation}
                placeholder="e.g., 3rd Floor Slab, Column C4..."
                placeholderTextColor={colors.text.subtle}
              />
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Concrete Supplier</Text>
              <TextInput
                style={s.input}
                value={concreteSupplier}
                onChangeText={setConcreteSupplier}
                placeholder="Supplier name"
                placeholderTextColor={colors.text.subtle}
              />
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Mix Design</Text>
              <TextInput
                style={s.input}
                value={mixDesign}
                onChangeText={setMixDesign}
                placeholder="e.g., 4000 PSI, 5-inch slump..."
                placeholderTextColor={colors.text.subtle}
              />
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Volume Ordered</Text>
              <TextInput
                style={s.input}
                value={volumeOrdered}
                onChangeText={setVolumeOrdered}
                placeholder="e.g., 50 CY"
                placeholderTextColor={colors.text.subtle}
              />
            </View>
          </GlassCard>

          {/* Slump Tests */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Slump Tests</Text>
            {slumpTests.map((test, i) => (
              <View key={i} style={s.entryCard}>
                <View style={s.entryRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.inputLabel}>Time</Text>
                    <TextInput
                      style={s.input}
                      value={test.time}
                      onChangeText={(v) => updateSlumpTest(i, 'time', v)}
                      placeholder="HH:MM"
                      placeholderTextColor={colors.text.subtle}
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.inputLabel}>Value (in)</Text>
                    <TextInput
                      style={s.input}
                      value={test.value}
                      onChangeText={(v) => updateSlumpTest(i, 'value', v)}
                      placeholder='0"'
                      placeholderTextColor={colors.text.subtle}
                      keyboardType="numeric"
                    />
                  </View>
                  <View style={{ alignItems: 'center' }}>
                    <Text style={s.inputLabel}>Pass</Text>
                    <Pressable onPress={() => updateSlumpTest(i, 'pass', test.pass === true ? null : true)}>
                      <View style={[s.toggleDot, test.pass === true && s.toggleDotActive]} />
                    </Pressable>
                  </View>
                  <View style={{ alignItems: 'center' }}>
                    <Text style={s.inputLabel}>Fail</Text>
                    <Pressable onPress={() => updateSlumpTest(i, 'pass', test.pass === false ? null : false)}>
                      <View style={[s.toggleDot, test.pass === false && s.toggleDotFail]} />
                    </Pressable>
                  </View>
                  {slumpTests.length > 1 && (
                    <Pressable onPress={() => removeSlumpTest(i)} style={{ paddingTop: 16 }}>
                      <Trash2 size={16} strokeWidth={1.5} color="#f87171" />
                    </Pressable>
                  )}
                </View>
              </View>
            ))}
            <GlassButton
              title="+ Add Slump Test"
              onPress={addSlumpTest}
              style={{ marginTop: spacing.xs }}
            />
          </GlassCard>

          {/* Formwork Inspection */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Formwork Inspection</Text>
            {FORMWORK_ITEMS.map((item) => (
              <View key={item.key} style={s.toggleRow}>
                <Text style={s.toggleLabel}>{item.label}</Text>
                <Pressable onPress={() => toggleFormwork(item.key)}>
                  <View style={[s.toggleDot, formworkChecklist[item.key] && s.toggleDotActive]} />
                </Pressable>
              </View>
            ))}
          </GlassCard>

          {/* Weather & Temperature */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Weather & Temperature</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginBottom: spacing.md }}>
              {WEATHER_OPTIONS.map((w) => (
                <Pressable
                  key={w}
                  onPress={() => setWeatherConditions(weatherConditions === w ? '' : w)}
                  style={[s.chip, weatherConditions === w && s.chipActive]}
                >
                  <Text style={[s.chipText, weatherConditions === w && s.chipTextActive]}>{w}</Text>
                </Pressable>
              ))}
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Temperature</Text>
              <TextInput
                style={s.input}
                value={temperature}
                onChangeText={setTemperature}
                placeholder="e.g., 72F"
                placeholderTextColor={colors.text.subtle}
              />
            </View>
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
    toggleDotFail: { backgroundColor: '#f87171', borderColor: '#f87171' },
    buttonRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
    loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' },
    entryCard: {
      borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)', borderRadius: borderRadius.lg,
      padding: spacing.md, marginBottom: spacing.sm,
    },
    entryRow: { flexDirection: 'row', gap: spacing.sm, alignItems: 'flex-end' },
    chip: {
      paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
      borderRadius: borderRadius.full, borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)',
      backgroundColor: 'rgba(255,255,255,0.04)',
    },
    chipActive: { backgroundColor: 'rgba(59,130,246,0.2)', borderColor: 'rgba(59,130,246,0.5)' },
    chipText: { fontSize: 13, color: colors.text.muted },
    chipTextActive: { color: '#3b82f6', fontWeight: '600' },
  });
}
