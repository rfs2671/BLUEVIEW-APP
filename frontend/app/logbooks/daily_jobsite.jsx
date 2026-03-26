import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, Image,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, Building2, CheckCircle, Save, Plus, Calendar,
  HardHat, Truck, AlertTriangle, Users, Clipboard, CloudSun, Camera, X, ImageIcon,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI, weatherAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
import * as ImagePicker from 'expo-image-picker';
import { Platform } from 'react-native';
let CameraView, useCameraPermissions;
if (Platform.OS !== 'web') {
  try {
    const mod = require('expo-camera');
    CameraView = mod.CameraView;
    useCameraPermissions = mod.useCameraPermissions;
  } catch (e) {}
}
import { Modal } from 'react-native';

const MAX_PHOTOS_PER_ACTIVITY = 5;
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
  photos: [],
});

const EMPTY_OBSERVATION = () => ({
  description: '',
  responsible_party: '',
  remedy: '',
  corrected_immediately: null,
});

export default function DailyJobsiteLog() {
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

  const openZoomedCamera = async (activityIndex) => {
    const current = activities[activityIndex]?.photos || [];
    if (current.length >= MAX_PHOTOS_PER_ACTIVITY) {
      toast.warning('Limit Reached', `Maximum ${MAX_PHOTOS_PER_ACTIVITY} photos per subcontractor`);
      return;
    }
    if (!cameraPermission?.granted) {
      const { granted } = await requestCameraPermission();
      if (!granted) {
        toast.error('Permission Denied', 'Camera access is required to take photos');
        return;
      }
    }
    setPendingActivityIndex(activityIndex);
    setCameraVisible(true);
  };

  const captureZoomedPhoto = async () => {
    if (!cameraRef.current || pendingActivityIndex === null) return;
    try {
      const photo = await cameraRef.current.takePictureAsync({
        quality: 0.6,
        base64: true,
        exif: false,
      });
      const newPhoto = {
        uri: photo.uri,
        base64: photo.base64,
        timestamp: new Date().toISOString(),
      };
      setActivities(prev => prev.map((a, i) => {
        if (i !== pendingActivityIndex) return a;
        return { ...a, photos: [...(a.photos || []), newPhoto].slice(0, MAX_PHOTOS_PER_ACTIVITY) };
      }));
      setCameraVisible(false);
      setPendingActivityIndex(null);
    } catch (err) {
      console.error('Capture failed:', err);
      toast.error('Error', 'Could not capture photo');
    }
  };
  const pickActivityPhoto = async (activityIndex) => {
    const current = activities[activityIndex]?.photos || [];
    if (current.length >= MAX_PHOTOS_PER_ACTIVITY) {
      toast.warning('Limit Reached', `Maximum ${MAX_PHOTOS_PER_ACTIVITY} photos per subcontractor`);
      return;
    }
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      toast.error('Permission Denied', 'Camera roll access is required to upload photos');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 0.6,
      base64: true,
      allowsMultipleSelection: true,
      selectionLimit: MAX_PHOTOS_PER_ACTIVITY - current.length,
    });
    if (result.canceled) return;
    const newPhotos = (result.assets || []).map((asset) => ({
      uri: asset.uri,
      base64: asset.base64,
      timestamp: new Date().toISOString(),
    }));
    setActivities(prev => prev.map((a, i) => {
      if (i !== activityIndex) return a;
      return { ...a, photos: [...(a.photos || []), ...newPhotos].slice(0, MAX_PHOTOS_PER_ACTIVITY) };
    }));
  };

  const takeActivityPhoto = async (activityIndex) => {
    const current = activities[activityIndex]?.photos || [];
    if (current.length >= MAX_PHOTOS_PER_ACTIVITY) {
      toast.warning('Limit Reached', `Maximum ${MAX_PHOTOS_PER_ACTIVITY} photos per subcontractor`);
      return;
    }
    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') {
      toast.error('Permission Denied', 'Camera access is required to take photos');
      return;
    }
    let result;
    try {
      result = await ImagePicker.launchCameraAsync({
        quality: 0.3,
        base64: true,
        exif: false,
        allowsEditing: false,
      });
    } catch (err) {
      console.error('Camera launch failed:', err);
      toast.error('Camera Error', 'Could not open camera. Please check permissions in device settings.');
      return;
    }
    if (!result || result.canceled) return;
    const asset = result.assets?.[0];
    if (!asset) return;
    const newPhoto = {
      uri: asset.uri,
      base64: asset.base64,
      timestamp: new Date().toISOString(),
    };
    setActivities(prev => prev.map((a, i) => {
      if (i !== activityIndex) return a;
      return { ...a, photos: [...(a.photos || []), newPhoto].slice(0, MAX_PHOTOS_PER_ACTIVITY) };
    }));
  };

  const removeActivityPhoto = (activityIndex, photoIndex) => {
    setActivities(prev => prev.map((a, i) => {
      if (i !== activityIndex) return a;
      return { ...a, photos: (a.photos || []).filter((_, pi) => pi !== photoIndex) };
    }));
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
        <SafeAreaView style={s.container} edges={['top']}>
          <View style={s.loadingCenter}>
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
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/logbooks')}
            />
            <View>
              <Text style={s.headerTitle}>Daily Jobsite Log</Text>
              <Text style={s.headerSub}>NYC DOB 3301-02</Text>
            </View>
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Date */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>
                {new Date(date).toLocaleDateString('en-US', {
                  weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
                })}
              </Text>
            </View>
          </GlassCard>

          {/* Project Info — FIX #2: Full address, read-only */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Project Information</Text>
            <View style={s.fieldRow}>
              <Text style={s.fieldLabel}>Address</Text>
              <Text style={s.fieldValueReadonly}>{projectAddress || 'No address on file'}</Text>
            </View>

            {/* Weather — FIX #1: Auto-filled from API */}
            <View style={s.fieldRowVertical}>
              <View style={s.weatherHeader}>
                <Text style={s.fieldLabel}>Weather</Text>
                {weatherTemp ? (
                  <Text style={s.weatherAuto}>
                    {weatherTemp}{weatherWind ? ` • ${weatherWind}` : ''}
                  </Text>
                ) : null}
                {weatherLoading && <ActivityIndicator size="small" color={colors.primary} />}
              </View>
              <View style={s.weatherRow}>
                {WEATHER_OPTIONS.map((w) => (
                  <Pressable
                    key={w}
                    onPress={() => setWeather(weather === w ? '' : w)}
                    style={[s.weatherBtn, weather === w && s.weatherBtnActive]}
                  >
                    <Text style={[s.weatherBtnText, weather === w && s.weatherBtnTextActive]}>{w}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </GlassCard>

          {/* General Description */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>General Description of Today's Activities</Text>
            <TextInput
              style={s.textArea}
              value={generalDescription}
              onChangeText={setGeneralDescription}
              placeholder="Describe the main work performed today..."
              placeholderTextColor={colors.text.subtle}
              multiline
              numberOfLines={4}
            />
          </GlassCard>

          {/* Activity Details Table */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Users size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>Activity Details</Text>
            </View>
            <Text style={s.sectionSubtitle}>Auto-populated from check-ins. Edit as needed.</Text>

            {activities.map((act, i) => (
              <View key={i} style={s.activityCard}>
                <View style={s.activityRow}>
                  <View style={s.activityField}>
                    <Text style={s.activityLabel}>CREW</Text>
                    <TextInput style={s.activityInput} value={act.crew_id}
                      onChangeText={(v) => updateActivity(i, 'crew_id', v)}
                      placeholder="C1" placeholderTextColor={colors.text.subtle} />
                  </View>
                  <View style={[s.activityField, { flex: 2 }]}>
                    <Text style={s.activityLabel}>COMPANY</Text>
                    <TextInput style={s.activityInput} value={act.company}
                      onChangeText={(v) => updateActivity(i, 'company', v)}
                      placeholder="Company" placeholderTextColor={colors.text.subtle} />
                  </View>
                  <View style={s.activityField}>
                    <Text style={s.activityLabel}># WORKERS</Text>
                    <TextInput style={s.activityInput} value={act.num_workers}
                      onChangeText={(v) => updateActivity(i, 'num_workers', v)}
                      placeholder="0" placeholderTextColor={colors.text.subtle} keyboardType="numeric" />
                  </View>
                </View>
                <View style={s.activityField}>
                  <Text style={s.activityLabel}>WORK DESCRIPTION</Text>
                  <TextInput style={s.activityInput} value={act.work_description}
                    onChangeText={(v) => updateActivity(i, 'work_description', v)}
                    placeholder="Work performed..." placeholderTextColor={colors.text.subtle} />
                </View>
                
                <View style={s.activityField}>
                  <Text style={s.activityLabel}>WORK LOCATIONS</Text>
                  <TextInput style={s.activityInput} value={act.work_locations}
                    onChangeText={(v) => updateActivity(i, 'work_locations', v)}
                    placeholder="Floors, areas..." placeholderTextColor={colors.text.subtle} />
                </View>

                {/* Photos */}
                <View style={s.photosSection}>
                  <View style={s.photosHeader}>
                    <Camera size={14} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.activityLabel}>PHOTOS ({(act.photos || []).length}/{MAX_PHOTOS_PER_ACTIVITY})</Text>
                  </View>
                  {(act.photos || []).length > 0 && (
                    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.photoScroll}>
                      {(act.photos || []).map((photo, pi) => (
                        <View key={pi} style={s.photoThumb}>
                          <Image
                            source={{ uri: photo.base64 ? `data:image/jpeg;base64,${photo.base64}` : photo.uri }}
                            style={s.photoImage}
                          />
                          <Pressable style={s.photoRemove} onPress={() => removeActivityPhoto(i, pi)}>
                            <X size={12} strokeWidth={2} color="#fff" />
                          </Pressable>
                        </View>
                      ))}
                    </ScrollView>
                  )}
                  {(act.photos || []).length < MAX_PHOTOS_PER_ACTIVITY && (
                    <View style={s.photoActions}>
                      <Pressable style={s.photoBtn} onPress={() => takeActivityPhoto(i)}>
                        <Camera size={16} strokeWidth={1.5} color={colors.primary} />
                        <Text style={s.photoBtnText}>Take Photo</Text>
                      </Pressable>
                      <Pressable style={s.photoBtn} onPress={() => pickActivityPhoto(i)}>
                        <ImageIcon size={16} strokeWidth={1.5} color={colors.primary} />
                        <Text style={s.photoBtnText}>Gallery</Text>
                      </Pressable>
                    </View>
                  )}
                </View>
              </View>
            ))}

            <GlassButton title="+ Add Activity" onPress={addActivity} style={s.addBtn} />
          </GlassCard>

          {/* Equipment */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Truck size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>Equipment on Site</Text>
            </View>
            <View style={s.chipRow}>
              {EQUIPMENT_ITEMS.map((item) => (
                <Pressable key={item.key} onPress={() => toggleEquipment(item.key)}
                  style={[s.chip, equipmentOnSite[item.key] && s.chipActive]}>
                  <Text style={[s.chipText, equipmentOnSite[item.key] && s.chipTextActive]}>
                    {item.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Safety Checklist */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Clipboard size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionTitle}>Items Inspected</Text>
            </View>
            <View style={s.chipRow}>
              {CHECKLIST_ITEMS.map((item) => (
                <Pressable key={item.key} onPress={() => toggleChecklist(item.key)}
                  style={[s.chip, checklistItems[item.key] && s.chipActive]}>
                  {checklistItems[item.key] && <CheckCircle size={14} strokeWidth={2} color="#4ade80" />}
                  <Text style={[s.chipText, checklistItems[item.key] && s.chipTextActive]}>
                    {item.label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Observations */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <AlertTriangle size={16} strokeWidth={1.5} color="#f59e0b" />
              <Text style={s.sectionTitle}>Safety Observations / Violations</Text>
            </View>
            {observations.map((obs, i) => (
              <View key={i} style={s.observationCard}>
                <TextInput style={s.fieldInput} value={obs.description}
                  onChangeText={(v) => updateObservation(i, 'description', v)}
                  placeholder="Describe observation..." placeholderTextColor={colors.text.subtle} multiline />
                <TextInput style={s.fieldInput} value={obs.responsible_party}
                  onChangeText={(v) => updateObservation(i, 'responsible_party', v)}
                  placeholder="Responsible party" placeholderTextColor={colors.text.subtle} />
                <TextInput style={s.fieldInput} value={obs.remedy}
                  onChangeText={(v) => updateObservation(i, 'remedy', v)}
                  placeholder="Remedy / corrective action" placeholderTextColor={colors.text.subtle} />
              </View>
            ))}
            <GlassButton title="+ Add Observation" onPress={addObservation} style={s.addBtn} />
          </GlassCard>

          {/* Visitors / Deliveries */}
          <GlassCard style={s.section}>
            <Text style={s.sectionTitle}>Visitors / Deliveries</Text>
            <TextInput style={s.textArea} value={visitorsDeliveries}
              onChangeText={setVisitorsDeliveries}
              placeholder="Record any visitors or deliveries..." placeholderTextColor={colors.text.subtle}
              multiline numberOfLines={3} />
          </GlassCard>

          {/* CP Signature ONLY — FIX #3: No superintendent signature */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Building2 size={16} strokeWidth={1.5} color="#3b82f6" />
              <Text style={s.sectionTitle}>Competent Person Sign-Off</Text>
            </View>
            <Text style={s.sectionSubtitle}>
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
          <View style={s.actions}>
            <GlassButton
              title={saving ? 'Saving...' : 'Save Draft'}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => handleSave('draft')}
              loading={saving}
              style={s.draftBtn}
            />
            <GlassButton
              title={saving ? 'Saving...' : 'Submit'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
              onPress={() => handleSave('submitted')}
              loading={saving}
              style={s.submitBtn}
            />
          </View>
        </ScrollView>
        <FloatingNav />
      </SafeAreaView>

      {/* 0.5x Zoom Camera Modal */}
      <Modal visible={cameraVisible} animationType="slide" statusBarTranslucent>
        <View style={{ flex: 1, backgroundColor: '#000' }}>
          <CameraView
            ref={cameraRef}
            style={{ flex: 1 }}
            facing="back"
            zoom={0.0}
            // zoom: 0.0 = widest (0.5x on ultrawide devices), 1.0 = max zoom
            // On iPhone with ultrawide: zoom=0.0 activates the 0.5x lens
          />
          {/* Controls */}
          <View style={{
            position: 'absolute', bottom: 0, left: 0, right: 0,
            paddingBottom: 48, paddingHorizontal: 32,
            flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <Pressable
              onPress={() => { setCameraVisible(false); setPendingActivityIndex(null); }}
              style={{ padding: 16 }}
            >
              <Text style={{ color: '#fff', fontSize: 16 }}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={captureZoomedPhoto}
              style={{
                width: 72, height: 72, borderRadius: 36,
                backgroundColor: '#fff', borderWidth: 4, borderColor: 'rgba(255,255,255,0.5)',
              }}
            />
            <View style={{ width: 64 }} />
          </View>
        </View>
      </Modal>

    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
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
  photosSection: { gap: spacing.xs, marginTop: spacing.xs },
  photosHeader: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  photoScroll: { marginTop: spacing.xs, paddingTop: 8, paddingBottom: 4 },
  photoThumb: { width: 80, height: 80, borderRadius: borderRadius.md, marginRight: spacing.sm, position: 'relative', overflow: 'visible' },
  photoImage: { width: 80, height: 80, borderRadius: borderRadius.md },
  photoRemove: {
    position: 'absolute', top: -6, right: -6, width: 22, height: 22, borderRadius: 11,
    backgroundColor: 'rgba(248,113,113,0.9)', alignItems: 'center', justifyContent: 'center',
  },
  photoActions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
  photoBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: borderRadius.full, borderWidth: 1, borderColor: 'rgba(59,130,246,0.3)',
    backgroundColor: 'rgba(59,130,246,0.08)',
  },
  photoBtnText: { fontSize: 12, fontWeight: '500', color: colors.primary },
});
}
