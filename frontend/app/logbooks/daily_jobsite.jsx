import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, Building2, CheckCircle, Save, Plus, Calendar,
  HardHat, Truck, AlertTriangle, Users, Clipboard,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

const WEATHER_OPTIONS = ['Sunny', 'Cloudy', 'Rainy', 'Windy', 'Snow', 'Fog'];

const EQUIPMENT_ITEMS = [
  { key: 'elevator', label: 'Elevator' },
  { key: 'compressor', label: 'Compressor' },
  { key: 'pump', label: 'Pump' },
  { key: 'hoist', label: 'Hoist' },
  { key: 'boom_crane', label: 'Boom/Crane' },
  { key: 'other_equipment', label: 'Other' },
];

const CHECKLIST_ITEMS = [
  { key: 'street_frontage', label: 'Street Frontage' },
  { key: 'fire_safety', label: 'Fire Safety' },
  { key: 'perimeter_fence', label: 'Perimeter Fence' },
  { key: 'fall_protections', label: 'Fall Protections' },
  { key: 'neighbors_property', label: "Neighbor's Property" },
  { key: 'license_spot_check', label: 'License Spot-Check' },
  { key: 'plans', label: 'Plans' },
  { key: 'permits', label: 'Permits' },
  { key: 'other_checklist', label: 'Other' },
];

const EMPTY_ACTIVITY = () => ({
  crew_id: '',
  company: '',
  num_workers: '',
  work_description: '',
  work_locations: '',
});

const EMPTY_OBSERVATION = () => ({
  description: '',
  responsible_party: '',
  remedy: '',
  corrected_immediately: null,
});

export default function DailyJobsiteLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);

  const [projectAddress, setProjectAddress] = useState('');
  const [weather, setWeather] = useState('');
  const [generalDescription, setGeneralDescription] = useState('');
  const [activities, setActivities] = useState([EMPTY_ACTIVITY()]);
  const [equipmentOnSite, setEquipmentOnSite] = useState({});
  const [checklistItems, setChecklistItems] = useState({});
  const [observations, setObservations] = useState([]);
  const [visitorsDeliveries, setVisitorsDeliveries] = useState('');
  const [timeIn, setTimeIn] = useState('');
  const [timeOut, setTimeOut] = useState('');
  const [areasVisited, setAreasVisited] = useState('');
  const [superintendentName, setSuperintendentName] = useState('');
  const [superintendentSignature, setSuperintendentSignature] = useState(null);

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [projectData, profile, checkins, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'daily_jobsite', date).catch(() => []),
      ]);

      if (projectData) {
        setProjectAddress(projectData.address || projectData.location || '');
      }
      const existing = Array.isArray(existingLogs) && existingLogs.length > 0 ? existingLogs[0] : null;
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.project_address) setProjectAddress(d.project_address);
        if (d.weather) setWeather(d.weather);
        if (d.general_description) setGeneralDescription(d.general_description);
        if (d.activities?.length > 0) setActivities(d.activities);
        if (d.equipment_on_site) setEquipmentOnSite(d.equipment_on_site);
        if (d.checklist_items) setChecklistItems(d.checklist_items);
        if (d.observations) setObservations(d.observations);
        if (d.visitors_deliveries) setVisitorsDeliveries(d.visitors_deliveries);
        if (d.time_in) setTimeIn(d.time_in);
        if (d.time_out) setTimeOut(d.time_out);
        if (d.areas_visited) setAreasVisited(d.areas_visited);
        if (d.superintendent_name) setSuperintendentName(d.superintendent_name);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
        if (d.superintendent_signature) setSuperintendentSignature(d.superintendent_signature);
      } else {
        // Auto-build activities from check-ins grouped by company
        const checkinList = Array.isArray(checkins) ? checkins : [];
        const companyMap = {};
        for (const c of checkinList) {
          const co = c.company || 'Unknown';
          if (!companyMap[co]) companyMap[co] = { company: co, workers: [], trades: [] };
          companyMap[co].workers.push(c.worker_name);
          if (c.trade && !companyMap[co].trades.includes(c.trade)) companyMap[co].trades.push(c.trade);
        }
        const autoActivities = Object.values(companyMap).map((co, i) => ({
          crew_id: `C${i + 1}`,
          company: co.company,
          num_workers: String(co.workers.length),
          work_description: co.trades.join(', '),
          work_locations: '',
        }));
        if (autoActivities.length > 0) setActivities(autoActivities);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const updateActivity = (index, field, value) => {
    setActivities(prev => prev.map((a, i) => i === index ? { ...a, [field]: value } : a));
  };

  const addActivity = () => setActivities(prev => [...prev, EMPTY_ACTIVITY()]);

  const toggleEquipment = (key) => setEquipmentOnSite(prev => ({ ...prev, [key]: !prev[key] }));
  const toggleChecklist = (key) => setChecklistItems(prev => ({ ...prev, [key]: !prev[key] }));

  const addObservation = () => setObservations(prev => [...prev, EMPTY_OBSERVATION()]);
  const updateObservation = (index, field, value) => {
    setObservations(prev => prev.map((o, i) => i === index ? { ...o, [field]: value } : o));
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      const payload = {
        project_id: projectId,
        log_type: 'daily_jobsite',
        date,
        data: {
          project_address: projectAddress,
          weather,
          general_description: generalDescription,
          activities,
          equipment_on_site: equipmentOnSite,
          checklist_items: checklistItems,
          observations,
          visitors_deliveries: visitorsDeliveries,
          time_in: timeIn,
          time_out: timeOut,
          areas_visited: areasVisited,
          superintendent_name: superintendentName,
          superintendent_signature: superintendentSignature,
        },
        cp_signature: cpSignature,
        cp_name: cpName,
        status: submitStatus,
      };

      if (existingLogId) {
        await logbooksAPI.update(existingLogId, {
          data: payload.data,
          cp_signature: cpSignature,
          cp_name: cpName,
          status: submitStatus,
        });
      } else {
        const created = await logbooksAPI.create(payload);
        setExistingLogId(created.id || created._id);
      }

      await autoSave(cpName, cpSignature);
      toast.success(submitStatus === 'submitted' ? 'Submitted' : 'Saved', 'Jobsite log saved');
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save log');
    } finally {
      setSaving(false);
    }
  };

  const CheckboxItem = ({ label, checked, onPress }) => (
    <Pressable onPress={onPress} style={styles.checkboxRow}>
      <View style={[styles.checkbox, checked && styles.checkboxActive]}>
        {checked && <CheckCircle size={14} strokeWidth={2} color="#4ade80" />}
      </View>
      <Text style={[styles.checkboxLabel, checked && styles.checkboxLabelActive]}>{label}</Text>
    </Pressable>
  );

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container} edges={['top']}>
          <View style={styles.loadingCenter}>
            <ActivityIndicator size="large" color={colors.text.primary} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/logbooks')}
            />
            <View>
              <Text style={styles.headerTitle}>Daily Jobsite Log</Text>
              <Text style={styles.headerSub}>NYC DOB Form 3301-02</Text>
            </View>
          </View>
        </View>

        <ScrollView style={styles.scrollView} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>

          {/* Date */}
          <GlassCard style={styles.dateCard}>
            <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
            <Text style={styles.dateText}>
              {new Date(date + 'T12:00:00').toLocaleDateString('en-US', {
                weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
              })}
            </Text>
          </GlassCard>

          {/* Project Info */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>Project Information</Text>
            <View style={styles.fieldRow}>
              <Text style={styles.fieldLabel}>Address</Text>
              <TextInput
                style={styles.fieldInput}
                value={projectAddress}
                onChangeText={setProjectAddress}
                placeholder="—"
                placeholderTextColor={colors.text.subtle}
              />
            </View>

            {/* Weather */}
            <View style={styles.fieldRowVertical}>
              <Text style={styles.fieldLabel}>Weather</Text>
              <View style={styles.weatherRow}>
                {WEATHER_OPTIONS.map((w) => (
                  <Pressable
                    key={w}
                    onPress={() => setWeather(weather === w ? '' : w)}
                    style={[styles.weatherBtn, weather === w && styles.weatherBtnActive]}
                  >
                    <Text style={[styles.weatherBtnText, weather === w && styles.weatherBtnTextActive]}>{w}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </GlassCard>

          {/* General Description */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>General Description of Today's Activities</Text>
            <TextInput
              style={styles.textArea}
              value={generalDescription}
              onChangeText={setGeneralDescription}
              placeholder="Describe the main work performed today..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={4}
            />
          </GlassCard>

          {/* Activity Details Table */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Users size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.sectionTitle}>Activity Details</Text>
            </View>
            <Text style={styles.sectionSubtitle}>Auto-populated from check-ins. Edit as needed.</Text>

            {activities.map((act, index) => (
              <View key={index} style={styles.activityBlock}>
                <Text style={styles.activityNum}>#{index + 1}</Text>
                <View style={styles.activityGrid}>
                  {[
                    { label: 'Crew ID', key: 'crew_id', flex: 1 },
                    { label: 'Company', key: 'company', flex: 2 },
                    { label: '# Workers', key: 'num_workers', flex: 1 },
                  ].map((f) => (
                    <View key={f.key} style={[styles.activityField, { flex: f.flex }]}>
                      <Text style={styles.activityFieldLabel}>{f.label}</Text>
                      <TextInput
                        style={styles.activityInput}
                        value={act[f.key]}
                        onChangeText={(v) => updateActivity(index, f.key, v)}
                        placeholder="—"
                        placeholderTextColor={colors.text.subtle}
                        keyboardType={f.key === 'num_workers' ? 'numeric' : 'default'}
                      />
                    </View>
                  ))}
                </View>
                <View style={styles.activityGrid}>
                  {[
                    { label: 'Work Description', key: 'work_description', flex: 2 },
                    { label: 'Work Locations', key: 'work_locations', flex: 2 },
                  ].map((f) => (
                    <View key={f.key} style={[styles.activityField, { flex: f.flex }]}>
                      <Text style={styles.activityFieldLabel}>{f.label}</Text>
                      <TextInput
                        style={styles.activityInput}
                        value={act[f.key]}
                        onChangeText={(v) => updateActivity(index, f.key, v)}
                        placeholder="—"
                        placeholderTextColor={colors.text.subtle}
                      />
                    </View>
                  ))}
                </View>
                {index < activities.length - 1 && <View style={styles.divider} />}
              </View>
            ))}

            <GlassButton
              title="+ Add Activity"
              icon={<Plus size={14} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={addActivity}
              style={styles.addBtn}
            />
          </GlassCard>

          {/* Maintenance & Checklist */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>Maintenance & Checklist</Text>

            <Text style={styles.subLabel}>Equipment On Site</Text>
            <View style={styles.checkboxGrid}>
              {EQUIPMENT_ITEMS.map((item) => (
                <CheckboxItem
                  key={item.key}
                  label={item.label}
                  checked={!!equipmentOnSite[item.key]}
                  onPress={() => toggleEquipment(item.key)}
                />
              ))}
            </View>

            <Text style={[styles.subLabel, { marginTop: spacing.md }]}>Checklist Performed</Text>
            <View style={styles.checkboxGrid}>
              {CHECKLIST_ITEMS.map((item) => (
                <CheckboxItem
                  key={item.key}
                  label={item.label}
                  checked={!!checklistItems[item.key]}
                  onPress={() => toggleChecklist(item.key)}
                />
              ))}
            </View>
          </GlassCard>

          {/* Observations & Notes */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <AlertTriangle size={16} strokeWidth={1.5} color="#ef4444" />
              <Text style={styles.sectionTitle}>Observations & Notes</Text>
            </View>
            <Text style={styles.sectionSubtitle}>
              Unsafe conditions, accidents, violations, warnings issued
            </Text>

            {observations.map((obs, index) => (
              <View key={index} style={styles.observationBlock}>
                <TextInput
                  style={styles.textArea}
                  value={obs.description}
                  onChangeText={(v) => updateObservation(index, 'description', v)}
                  placeholder="Description of unsafe condition / incident..."
                  placeholderTextColor={colors.text.subtle}
                  multiline
                  numberOfLines={2}
                />
                <View style={styles.obsRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.obsLabel}>Responsible Party</Text>
                    <TextInput
                      style={styles.obsInput}
                      value={obs.responsible_party}
                      onChangeText={(v) => updateObservation(index, 'responsible_party', v)}
                      placeholder="—"
                      placeholderTextColor={colors.text.subtle}
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.obsLabel}>Remedy</Text>
                    <TextInput
                      style={styles.obsInput}
                      value={obs.remedy}
                      onChangeText={(v) => updateObservation(index, 'remedy', v)}
                      placeholder="—"
                      placeholderTextColor={colors.text.subtle}
                    />
                  </View>
                </View>
                <View style={styles.correctedRow}>
                  <Text style={styles.obsLabel}>Corrected Immediately?</Text>
                  <View style={styles.ynRow}>
                    {['yes', 'no'].map((v) => (
                      <Pressable
                        key={v}
                        onPress={() => updateObservation(index, 'corrected_immediately', obs.corrected_immediately === v ? null : v)}
                        style={[styles.ynBtn, obs.corrected_immediately === v && (v === 'yes' ? styles.ynBtnYes : styles.ynBtnNo)]}
                      >
                        <Text style={[styles.ynText,
                          obs.corrected_immediately === v && (v === 'yes' ? styles.ynTextYes : styles.ynTextNo)
                        ]}>{v.toUpperCase()}</Text>
                      </Pressable>
                    ))}
                  </View>
                </View>
                {index < observations.length - 1 && <View style={styles.divider} />}
              </View>
            ))}

            <GlassButton
              title="+ Add Observation"
              icon={<Plus size={14} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={addObservation}
              style={styles.addBtn}
            />
          </GlassCard>

          {/* Visitors & Deliveries */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>Visitors & Deliveries</Text>
            <TextInput
              style={styles.textArea}
              value={visitorsDeliveries}
              onChangeText={setVisitorsDeliveries}
              placeholder="Note any site visitors or material deliveries..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={3}
            />
          </GlassCard>

          {/* Supervision */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Clipboard size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.sectionTitle}>Supervision</Text>
            </View>
            {[
              { label: 'Time In', value: timeIn, setter: setTimeIn, placeholder: '7:00 AM' },
              { label: 'Time Out', value: timeOut, setter: setTimeOut, placeholder: '4:00 PM' },
              { label: 'Areas Visited', value: areasVisited, setter: setAreasVisited, placeholder: 'All floors, exterior...' },
            ].map((f) => (
              <View key={f.label} style={styles.fieldRow}>
                <Text style={styles.fieldLabel}>{f.label}</Text>
                <TextInput
                  style={styles.fieldInput}
                  value={f.value}
                  onChangeText={f.setter}
                  placeholder={f.placeholder}
                  placeholderTextColor={colors.text.subtle}
                />
              </View>
            ))}
          </GlassCard>

          {/* Superintendent Signature */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <HardHat size={16} strokeWidth={1.5} color="#f59e0b" />
              <Text style={styles.sectionTitle}>Registered Superintendent</Text>
            </View>
            <SignaturePad
              title="Superintendent Signature"
              signerName={superintendentName}
              onNameChange={setSuperintendentName}
              existingSignature={superintendentSignature}
              onSignatureCapture={setSuperintendentSignature}
            />
          </GlassCard>

          {/* CP / Foreman Signature */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Building2 size={16} strokeWidth={1.5} color="#ef4444" />
              <Text style={styles.sectionTitle}>Foreman / Competent Person</Text>
            </View>
            <SignaturePad
              title="Competent Person Signature"
              signerName={cpName}
              onNameChange={setCpName}
              existingSignature={cpSignature}
              onSignatureCapture={setCpSignature}
            />
          </GlassCard>

          {/* Actions */}
          <View style={styles.actions}>
            <GlassButton
              title={saving ? 'Saving...' : 'Save Draft'}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => handleSave('draft')}
              loading={saving}
              style={styles.draftBtn}
            />
            <GlassButton
              title={saving ? 'Submitting...' : 'Submit & Sign'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
              onPress={() => handleSave('submitted')}
              loading={saving}
              disabled={!cpSignature}
              style={styles.submitBtn}
            />
          </View>
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  loadingCenter: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.08)',
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  headerTitle: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 11, color: colors.text.muted },
  scrollView: { flex: 1 },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 100,
    maxWidth: 720,
    width: '100%',
    alignSelf: 'center',
  },
  dateCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
    padding: spacing.md,
  },
  dateText: { fontSize: 14, color: colors.text.secondary },
  section: { marginBottom: spacing.md, padding: spacing.lg },
  sectionTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.md },
  sectionHeaderRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.md },
  sectionSubtitle: { fontSize: 12, color: colors.text.muted, marginBottom: spacing.md, marginTop: -spacing.sm },
  subLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: spacing.sm,
  },
  fieldRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.05)',
    gap: spacing.md,
  },
  fieldRowVertical: { marginTop: spacing.sm },
  fieldLabel: { flex: 1, fontSize: 13, color: colors.text.secondary },
  fieldInput: {
    flex: 2,
    fontSize: 14,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.sm,
  },
  weatherRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginTop: spacing.xs },
  weatherBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  weatherBtnActive: { backgroundColor: 'rgba(59,130,246,0.2)', borderColor: '#3b82f6' },
  weatherBtnText: { fontSize: 13, color: colors.text.muted },
  weatherBtnTextActive: { color: '#93c5fd', fontWeight: '600' },
  textArea: {
    fontSize: 14,
    color: colors.text.primary,
    padding: spacing.md,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
    minHeight: 80,
    textAlignVertical: 'top',
  },
  activityBlock: { marginBottom: spacing.sm },
  activityNum: { fontSize: 11, fontWeight: '700', color: colors.text.muted, marginBottom: spacing.xs },
  activityGrid: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.xs },
  activityField: {},
  activityFieldLabel: { fontSize: 10, color: colors.text.muted, marginBottom: 2, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5 },
  activityInput: {
    fontSize: 13,
    color: colors.text.primary,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
  },
  checkboxGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  checkboxRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    width: '47%',
    paddingVertical: spacing.xs,
  },
  checkbox: {
    width: 22,
    height: 22,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.04)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxActive: { backgroundColor: 'rgba(74,222,128,0.1)', borderColor: '#4ade80' },
  checkboxLabel: { fontSize: 13, color: colors.text.muted },
  checkboxLabelActive: { color: colors.text.secondary },
  observationBlock: { marginBottom: spacing.md },
  obsRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  obsLabel: { fontSize: 11, color: colors.text.muted, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 },
  obsInput: {
    fontSize: 13,
    color: colors.text.primary,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
  },
  correctedRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginTop: spacing.sm },
  ynRow: { flexDirection: 'row', gap: spacing.xs },
  ynBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    backgroundColor: 'rgba(255,255,255,0.04)',
  },
  ynBtnYes: { backgroundColor: 'rgba(74,222,128,0.15)', borderColor: 'rgba(74,222,128,0.4)' },
  ynBtnNo: { backgroundColor: 'rgba(239,68,68,0.15)', borderColor: 'rgba(239,68,68,0.4)' },
  ynText: { fontSize: 12, fontWeight: '700', color: colors.text.muted },
  ynTextYes: { color: '#4ade80' },
  ynTextNo: { color: '#f87171' },
  divider: { height: 1, backgroundColor: 'rgba(255,255,255,0.06)', marginTop: spacing.sm },
  addBtn: { marginTop: spacing.md },
  autoSignBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.md,
    padding: spacing.sm,
    backgroundColor: 'rgba(74,222,128,0.08)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(74,222,128,0.2)',
  },
  autoSignText: { fontSize: 12, color: '#4ade80' },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  draftBtn: { flex: 1 },
  submitBtn: { flex: 2, backgroundColor: 'rgba(239,68,68,0.15)', borderColor: 'rgba(239,68,68,0.3)' },
});
