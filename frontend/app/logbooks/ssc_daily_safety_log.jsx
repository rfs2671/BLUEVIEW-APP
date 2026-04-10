import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator } from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, Shield, CheckCircle, Save, Calendar } from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

const LOG_TYPE = 'ssc_daily_safety_log';

const WEATHER_OPTIONS = ['Sunny', 'Cloudy', 'Rainy', 'Windy', 'Snow', 'Fog', 'Stormy'];

export default function SSCDailySafetyLog() {
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
  const [projectAddress, setProjectAddress] = useState('');
  const [sspNumber, setSspNumber] = useState('');
  const [weather, setWeather] = useState('');
  const [siteConditions, setSiteConditions] = useState('');
  const [safetyViolations, setSafetyViolations] = useState('');
  const [correctiveActions, setCorrectiveActions] = useState('');
  const [incidentsReported, setIncidentsReported] = useState(false);
  const [incidentDetails, setIncidentDetails] = useState('');
  const [workersOnSiteCount, setWorkersOnSiteCount] = useState('');
  const [safetyMeetingsHeld, setSafetyMeetingsHeld] = useState(false);
  const [fireProtectionInPlace, setFireProtectionInPlace] = useState(false);
  const [housekeepingSatisfactory, setHousekeepingSatisfactory] = useState(false);
  const [ppeCompliance, setPpeCompliance] = useState(false);

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [projectData, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getByProject(projectId, LOG_TYPE, date).catch(() => []),
      ]);

      const fullAddress = projectData?.address || projectData?.location || '';
      setProjectAddress(fullAddress);
      if (projectData?.ssp_number) setSspNumber(projectData.ssp_number);

      const existing = Array.isArray(existingLogs) && existingLogs.length > 0 ? existingLogs[0] : null;
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.project_address) setProjectAddress(d.project_address);
        if (d.ssp_number) setSspNumber(d.ssp_number);
        if (d.weather) setWeather(d.weather);
        if (d.site_conditions) setSiteConditions(d.site_conditions);
        if (d.safety_violations_observed) setSafetyViolations(d.safety_violations_observed);
        if (d.corrective_actions_taken) setCorrectiveActions(d.corrective_actions_taken);
        if (d.incidents_reported != null) setIncidentsReported(d.incidents_reported);
        if (d.incident_details) setIncidentDetails(d.incident_details);
        if (d.workers_on_site_count) setWorkersOnSiteCount(d.workers_on_site_count);
        if (d.safety_meetings_held != null) setSafetyMeetingsHeld(d.safety_meetings_held);
        if (d.fire_protection_in_place != null) setFireProtectionInPlace(d.fire_protection_in_place);
        if (d.housekeeping_satisfactory != null) setHousekeepingSatisfactory(d.housekeeping_satisfactory);
        if (d.ppe_compliance != null) setPpeCompliance(d.ppe_compliance);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      const payload = {
        project_id: projectId,
        log_type: LOG_TYPE,
        date,
        data: {
          project_address: projectAddress,
          ssp_number: sspNumber,
          weather,
          site_conditions: siteConditions,
          safety_violations_observed: safetyViolations,
          corrective_actions_taken: correctiveActions,
          incidents_reported: incidentsReported,
          incident_details: incidentDetails,
          workers_on_site_count: workersOnSiteCount,
          safety_meetings_held: safetyMeetingsHeld,
          fire_protection_in_place: fireProtectionInPlace,
          housekeeping_satisfactory: housekeepingSatisfactory,
          ppe_compliance: ppeCompliance,
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
          eventType: 'ssc_sign',
          signerName: cpName,
          signerRole: user?.role || 'ssc',
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
        submitStatus === 'submitted' ? 'Safety log submitted successfully' : 'Draft saved'
      );
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save safety log');
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
          <Text style={s.headerTitle}>SSC/SSM Daily Safety Log</Text>
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

          {/* Project Info */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Project Information</Text>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Project Address</Text>
              <Text style={[s.input, { paddingVertical: spacing.sm }]}>{projectAddress || 'No address on file'}</Text>
            </View>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>SSP Number</Text>
              <Text style={[s.input, { paddingVertical: spacing.sm }]}>{sspNumber || 'N/A'}</Text>
            </View>
          </GlassCard>

          {/* Weather */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Weather Conditions</Text>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs }}>
              {WEATHER_OPTIONS.map((w) => (
                <Pressable
                  key={w}
                  onPress={() => setWeather(weather === w ? '' : w)}
                  style={[s.chip, weather === w && s.chipActive]}
                >
                  <Text style={[s.chipText, weather === w && s.chipTextActive]}>{w}</Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Site Conditions */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Site Conditions</Text>
            <TextInput
              style={[s.input, s.textArea]}
              value={siteConditions}
              onChangeText={setSiteConditions}
              placeholder="Describe current site conditions..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={4}
            />
          </GlassCard>

          {/* Safety Violations */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Safety Violations Observed</Text>
            <TextInput
              style={[s.input, s.textArea]}
              value={safetyViolations}
              onChangeText={setSafetyViolations}
              placeholder="Describe any safety violations observed..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={4}
            />
          </GlassCard>

          {/* Corrective Actions */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Corrective Actions Taken</Text>
            <TextInput
              style={[s.input, s.textArea]}
              value={correctiveActions}
              onChangeText={setCorrectiveActions}
              placeholder="Describe corrective actions taken..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={4}
            />
          </GlassCard>

          {/* Incidents */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Incidents</Text>
            <ToggleRow
              label="Incidents Reported"
              value={incidentsReported}
              onToggle={() => setIncidentsReported(!incidentsReported)}
            />
            {incidentsReported && (
              <TextInput
                style={[s.input, s.textArea, { marginTop: spacing.sm }]}
                value={incidentDetails}
                onChangeText={setIncidentDetails}
                placeholder="Provide incident details..."
                placeholderTextColor={colors.text.subtle}
                multiline
                numberOfLines={4}
              />
            )}
          </GlassCard>

          {/* Workforce & Compliance */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Workforce & Compliance</Text>
            <View style={s.inputGroup}>
              <Text style={s.inputLabel}>Workers on Site</Text>
              <TextInput
                style={s.input}
                value={workersOnSiteCount}
                onChangeText={setWorkersOnSiteCount}
                placeholder="0"
                placeholderTextColor={colors.text.subtle}
                keyboardType="numeric"
              />
            </View>
            <ToggleRow
              label="Safety Meetings Held"
              value={safetyMeetingsHeld}
              onToggle={() => setSafetyMeetingsHeld(!safetyMeetingsHeld)}
            />
            <ToggleRow
              label="Fire Protection in Place"
              value={fireProtectionInPlace}
              onToggle={() => setFireProtectionInPlace(!fireProtectionInPlace)}
            />
            <ToggleRow
              label="Housekeeping Satisfactory"
              value={housekeepingSatisfactory}
              onToggle={() => setHousekeepingSatisfactory(!housekeepingSatisfactory)}
            />
            <ToggleRow
              label="PPE Compliance"
              value={ppeCompliance}
              onToggle={() => setPpeCompliance(!ppeCompliance)}
            />
          </GlassCard>

          {/* SSC/SSM Signature */}
          <GlassCard style={s.section}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm }}>
              <Shield size={16} strokeWidth={1.5} color="#3b82f6" />
              <Text style={s.sectionTitle}>SSC/SSM Sign-Off</Text>
            </View>
            <SignaturePad
              title="SSC/SSM Signature"
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
    chipActive: { backgroundColor: 'rgba(59,130,246,0.2)', borderColor: 'rgba(59,130,246,0.5)' },
    chipText: { fontSize: 13, color: colors.text.muted },
    chipTextActive: { color: '#3b82f6', fontWeight: '600' },
  });
}
