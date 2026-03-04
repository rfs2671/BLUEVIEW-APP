import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, Building2, CheckCircle, Save, Plus, Calendar,
  HardHat, Truck, AlertTriangle, Users, Clipboard, CloudSun,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI, weatherAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

const WEATHER_OPTIONS = ['Sunny', 'Cloudy', 'Rainy', 'Windy', 'Snow', 'Fog', 'Stormy'];

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
  const [weatherTemp, setWeatherTemp] = useState('');
  const [weatherWind, setWeatherWind] = useState('');
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [generalDescription, setGeneralDescription] = useState('');
  const [activities, setActivities] = useState([EMPTY_ACTIVITY()]);
  const [equipmentOnSite, setEquipmentOnSite] = useState({});
  const [checklistItems, setChecklistItems] = useState({});
  const [observations, setObservations] = useState([]);
  const [visitorsDeliveries, setVisitorsDeliveries] = useState('');
  const [timeIn, setTimeIn] = useState('');
  const [timeOut, setTimeOut] = useState('');
  const [areasVisited, setAreasVisited] = useState('');

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [projectData, checkins, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'daily_jobsite', date).catch(() => []),
      ]);

      // FIX #2: Set full project address
      const fullAddress = projectData?.address || projectData?.location || '';
      setProjectAddress(fullAddress);

      const existing = Array.isArray(existingLogs) && existingLogs.length > 0 ? existingLogs[0] : null;
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.project_address) setProjectAddress(d.project_address);
        if (d.weather) setWeather(d.weather);
        if (d.weather_temp) setWeatherTemp(d.weather_temp);
        if (d.weather_wind) setWeatherWind(d.weather_wind);
        if (d.general_description) setGeneralDescription(d.general_description);
        if (d.activities?.length > 0) setActivities(d.activities);
        if (d.equipment_on_site) setEquipmentOnSite(d.equipment_on_site);
        if (d.checklist_items) setChecklistItems(d.checklist_items);
        if (d.observations) setObservations(d.observations);
        if (d.visitors_deliveries) setVisitorsDeliveries(d.visitors_deliveries);
        if (d.time_in) setTimeIn(d.time_in);
        if (d.time_out) setTimeOut(d.time_out);
        if (d.areas_visited) setAreasVisited(d.areas_visited);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
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

        // FIX #1: Auto-fetch weather if no existing log
        fetchWeather(fullAddress);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // FIX #1: Weather autofill from API
  const fetchWeather = async (address) => {
    setWeatherLoading(true);
    try {
      const data = await weatherAPI.getCurrent(null, null, address || null);
      if (data?.condition) {
        setWeather(data.condition);
      }
      if (data?.temperature != null) {
        setWeatherTemp(`${Math.round(data.temperature)}°F`);
      }
      if (data?.wind_speed != null) {
        setWeatherWind(`${Math.round(data.wind_speed)} mph`);
      }
    } catch (e) {
      console.warn('Weather autofill failed (non-blocking):', e?.message);
    } finally {
      setWeatherLoading(false);
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

  // FIX #3: No superintendent signature in payload — CP only
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
          weather_temp: weatherTemp,
          weather_wind: weatherWind,
          general_description: generalDescription,
          activities,
          equipment_on_site: equipmentOnSite,
          checklist_items: checklistItems,
          observations,
          visitors_deliveries: visitorsDeliveries,
          time_in: timeIn,
          time_out: timeOut,
          areas_visited: areasVisited,
          // superintendent fields intentionally omitted — super signs from site device
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
      toast.success(submitStatus === 'submitted' ? 'Submitted' : 'Draft Saved',
        submitStatus === 'submitted' ? 'Daily jobsite log submitted' : 'Draft saved');
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save log');
    } finally {
      setSaving(false);
    }
  };

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
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/logbooks')}
            />
            <View>
              <Text style={styles.headerTitle}>Daily Jobsite Log</Text>
              <Text style={styles.headerSub}>NYC DOB 3301-02</Text>
            </View>
          </View>
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Date */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.sectionTitle}>
                {new Date(date).toLocaleDateString('en-US', {
                  weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
                })}
              </Text>
            </View>
          </GlassCard>

          {/* Project Info — FIX #2: Full address, read-only */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>Project Information</Text>
            <View style={styles.fieldRow}>
              <Text style={styles.fieldLabel}>Address</Text>
              <Text style={styles.fieldValueReadonly}>{projectAddress || 'No address on file'}</Text>
            </View>

            {/* Weather — FIX #1: Auto-filled from API */}
            <View style={styles.fieldRowVertical}>
              <View style={styles.weatherHeader}>
                <Text style={styles.fieldLabel}>Weather</Text>
                {weatherTemp ? (
                  <Text style={styles.weatherAuto}>
                    {weatherTemp}{weatherWind ? ` • ${weatherWind}` : ''}
                  </Text>
                ) : null}
                {weatherLoading && <ActivityIndicator size="small" color={colors.primary} />}
              </View>
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

            {activities.map((act, i) => (
              <View key={i} style={styles.activityCard}>
                <View style={styles.activityRow}>
                  <View style={styles.activityField}>
                    <Text style={styles.activityLabel}>CREW</Text>
                    <TextInput style={styles.activityInput} value={act.crew_id}
                      onChangeText={(v) => updateActivity(i, 'crew_id', v)}
                      placeholder="C1" placeholderTextColor={colors.text.subtle} />
                  </View>
                  <View style={[styles.activityField, { flex: 2 }]}>
                    <Text style={styles.activityLabel}>COMPANY</Text>
                    <TextInput style={styles.activityInput} value={act.company}
                      onChangeText={(v) => updateActivity(i, 'company', v)}
                      placeholder="Company" placeholderTextColor={colors.text.subtle} />
                  </View>
                  <View style={styles.activityField}>
                    <Text style={styles.activityLabel}># WORKERS</Text>
                    <TextInput style={styles.activityInput} value={act.num_workers}
                      onChangeText={(v) => updateActivity(i, 'num_workers', v)}
                      placeholder="0" placeholderTextColor={colors.text.subtle} keyboardType="numeric" />
                  </View>
                </View>
                <View style={styles.activityField}>
                  <Text style={styles.activityLabel}>WORK DESCRIPTION</Text>
                  <TextInput style={styles.activityInput} value={act.work_description}
                    onChangeText={(v) => updateActivity(i, 'work_description', v)}
                    placeholder="Work performed..." placeholderTextColor={colors.text.subtle} />
                </View>
                <View style={styles.activityField}>
                  <Text style={styles.activityLabel}>WORK LOCATIONS</Text>
                  <TextInput style={styles.activityInput} value={act.work_locations}
                    onChangeText={(v) => updateActivity(i, 'work_locations', v)}
                    placeholder="Floors, areas..." placeholderTextColor={colors.text.subtle} />
                </View>
              </View>
            ))}

            <GlassButton title="+ Add Activity" onPress={addActivity} style={styles.addBtn} />
          </GlassCard>

          {/* Equipment */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Truck size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.sectionTitle}>Equipment on Site</Text>
            </View>
            <View style={styles.chipRow}>
              {EQUIPMENT_ITEMS.map((item) => (
                <Pressable key={item.key} onPress={() => toggleEquipment(item.key)}
                  style={[styles.chip, equipmentOnSite[item.key] && styles.chipActive]}>
                  <Text style={[styles.chipText, equipmentOnSite[item.key] && styles.chipTextActive]}>
                    {item.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Safety Checklist */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Clipboard size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.sectionTitle}>Items Inspected</Text>
            </View>
            <View style={styles.chipRow}>
              {CHECKLIST_ITEMS.map((item) => (
                <Pressable key={item.key} onPress={() => toggleChecklist(item.key)}
                  style={[styles.chip, checklistItems[item.key] && styles.chipActive]}>
                  {checklistItems[item.key] && <CheckCircle size={14} strokeWidth={2} color="#4ade80" />}
                  <Text style={[styles.chipText, checklistItems[item.key] && styles.chipTextActive]}>
                    {item.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Observations */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <AlertTriangle size={16} strokeWidth={1.5} color="#f59e0b" />
              <Text style={styles.sectionTitle}>Safety Observations / Violations</Text>
            </View>
            {observations.map((obs, i) => (
              <View key={i} style={styles.observationCard}>
                <TextInput style={styles.fieldInput} value={obs.description}
                  onChangeText={(v) => updateObservation(i, 'description', v)}
                  placeholder="Describe observation..." placeholderTextColor={colors.text.subtle} multiline />
                <TextInput style={styles.fieldInput} value={obs.responsible_party}
                  onChangeText={(v) => updateObservation(i, 'responsible_party', v)}
                  placeholder="Responsible party" placeholderTextColor={colors.text.subtle} />
                <TextInput style={styles.fieldInput} value={obs.remedy}
                  onChangeText={(v) => updateObservation(i, 'remedy', v)}
                  placeholder="Remedy / corrective action" placeholderTextColor={colors.text.subtle} />
              </View>
            ))}
            <GlassButton title="+ Add Observation" onPress={addObservation} style={styles.addBtn} />
          </GlassCard>

          {/* Visitors / Deliveries */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>Visitors / Deliveries</Text>
            <TextInput style={styles.textArea} value={visitorsDeliveries}
              onChangeText={setVisitorsDeliveries}
              placeholder="Record any visitors or deliveries..." placeholderTextColor={colors.text.subtle}
              multiline numberOfLines={3} />
          </GlassCard>

          {/* CP Signature ONLY — FIX #3: No superintendent signature */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Building2 size={16} strokeWidth={1.5} color="#3b82f6" />
              <Text style={styles.sectionTitle}>Competent Person Sign-Off</Text>
            </View>
            <Text style={styles.sectionSubtitle}>
              Superintendent will sign from the site device after review.
            </Text>
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
              title={saving ? 'Saving...' : 'Submit'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
              onPress={() => handleSave('submitted')}
              loading={saving}
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
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  headerTitle: { fontSize: 17, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 12, color: colors.text.muted },
  scrollView: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 100 },
  section: { marginBottom: spacing.md },
  sectionTitle: { fontSize: 16, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.xs },
  sectionSubtitle: { fontSize: 13, color: colors.text.muted, marginBottom: spacing.md },
  sectionHeaderRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  fieldRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: spacing.sm },
  fieldRowVertical: { paddingVertical: spacing.sm },
  fieldLabel: { fontSize: 13, fontWeight: '600', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  fieldValueReadonly: { fontSize: 15, color: colors.text.primary, fontWeight: '500', flex: 1, textAlign: 'right' },
  fieldInput: {
    backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: borderRadius.md,
    padding: spacing.sm, fontSize: 14, color: colors.text.primary,
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)', marginTop: spacing.xs,
  },
  textArea: {
    backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: borderRadius.md,
    padding: spacing.md, fontSize: 14, color: colors.text.primary,
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)', minHeight: 80, textAlignVertical: 'top',
  },
  weatherHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  weatherAuto: { fontSize: 13, color: colors.primary, fontWeight: '500' },
  weatherRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  weatherBtn: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
    borderRadius: borderRadius.full, borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)',
    backgroundColor: 'rgba(255,255,255,0.04)',
  },
  weatherBtnActive: { backgroundColor: 'rgba(59,130,246,0.2)', borderColor: 'rgba(59,130,246,0.5)' },
  weatherBtnText: { fontSize: 13, color: colors.text.muted },
  weatherBtnTextActive: { color: '#3b82f6', fontWeight: '600' },
  activityCard: {
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.06)', borderRadius: borderRadius.lg,
    padding: spacing.md, marginBottom: spacing.sm, gap: spacing.sm,
  },
  activityRow: { flexDirection: 'row', gap: spacing.sm },
  activityField: { flex: 1, gap: 2 },
  activityLabel: { fontSize: 10, fontWeight: '600', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  activityInput: {
    backgroundColor: 'rgba(255,255,255,0.04)', borderRadius: borderRadius.sm,
    padding: spacing.xs, fontSize: 14, color: colors.text.primary,
  },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: borderRadius.full, borderWidth: 1, borderColor: 'rgba(255,255,255,0.1)',
    backgroundColor: 'rgba(255,255,255,0.04)',
  },
  chipActive: { backgroundColor: 'rgba(74,222,128,0.15)', borderColor: 'rgba(74,222,128,0.4)' },
  chipText: { fontSize: 13, color: colors.text.muted },
  chipTextActive: { color: '#4ade80', fontWeight: '500' },
  observationCard: {
    borderWidth: 1, borderColor: 'rgba(245,158,11,0.15)', borderRadius: borderRadius.lg,
    padding: spacing.md, marginBottom: spacing.sm, gap: spacing.sm,
  },
  addBtn: { marginTop: spacing.xs },
  actions: { flexDirection: 'row', gap: spacing.md, marginTop: spacing.md, marginBottom: spacing.xl },
  draftBtn: { flex: 1 },
  submitBtn: { flex: 1, backgroundColor: '#4ade80', borderColor: '#4ade80' },
});
