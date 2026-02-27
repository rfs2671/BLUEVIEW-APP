import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, BookOpen, Check, CheckCircle, Save, Users, Calendar,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

const TOPICS = {
  'PPE': [
    { key: 'hard_hats', label: 'Hard Hats' },
    { key: 'safety_boots', label: 'Safety Boots' },
    { key: 'safety_glasses', label: 'Safety Glasses' },
    { key: 'harness', label: 'Harness' },
    { key: 'gloves', label: 'Gloves' },
    { key: 'covid19', label: 'Covid-19' },
  ],
  'Fall Protection': [
    { key: 'ladder_safety', label: 'Ladder Safety' },
    { key: 'harness_fp', label: 'Harness' },
    { key: 'guard_rails', label: 'Guard Rails' },
    { key: 'slopes', label: 'Slopes' },
  ],
  'Hazards': [
    { key: 'tripping_hazards', label: 'Tripping Hazards' },
    { key: 'fire_hazards', label: 'Fire Hazards' },
    { key: 'egress', label: 'Egress' },
    { key: 'flammables', label: 'Flammables' },
  ],
  'Equipment': [
    { key: 'electric_tool_safety', label: 'Electric Tool Safety' },
    { key: 'scaffold_safety', label: 'Scaffold Safety' },
    { key: 'excavator', label: 'Excavator' },
    { key: 'generator', label: 'Generator' },
  ],
  'Public Safety': [
    { key: 'flags_man_regulations', label: 'Flags / Man Regulations' },
    { key: 'sidewalk', label: 'Side Walk' },
    { key: 'street_safety', label: 'Street Safety' },
    { key: 'adjacent_property', label: 'Adjacent Property' },
  ],
};

export default function ToolboxTalkLog() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  const [project, setProject] = useState(null);

  const [location, setLocation] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [typeOfWork, setTypeOfWork] = useState('');
  const [meetingTime, setMeetingTime] = useState(
    new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  );
  const [performedBy, setPerformedBy] = useState('');
  const [checkedTopics, setCheckedTopics] = useState({});
  const [attendees, setAttendees] = useState([]);

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [projectData, profile, checkins, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'toolbox_talk', date).catch(() => []),
      ]);

      if (projectData) {
        setProject(projectData);
        setLocation(projectData.address || projectData.location || '');
      }

      if (profile) {
        setCpProfile(profile);
        setCpName(profile.cp_name || '');
        setPerformedBy(profile.cp_name || '');
        if (profile.cp_signature) setCpSignature(profile.cp_signature);
      }

      // Build attendee list from check-ins
      const checkinList = Array.isArray(checkins) ? checkins : [];
      const autoAttendees = checkinList.map((c) => ({
        worker_id: c.worker_id,
        name: c.worker_name || '',
        company: c.company || '',
        signed: false,
        signature: null,
      }));

      const existing = Array.isArray(existingLogs) && existingLogs.length > 0 ? existingLogs[0] : null;
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.location) setLocation(d.location);
        if (d.company_name) setCompanyName(d.company_name);
        if (d.type_of_work) setTypeOfWork(d.type_of_work);
        if (d.meeting_time) setMeetingTime(d.meeting_time);
        if (d.performed_by) setPerformedBy(d.performed_by);
        if (d.checked_topics) setCheckedTopics(d.checked_topics);
        if (d.attendees && d.attendees.length > 0) {
          setAttendees(d.attendees);
        } else {
          setAttendees(autoAttendees);
        }
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      } else {
        setAttendees(autoAttendees);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const toggleTopic = (key) => {
    setCheckedTopics(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const toggleAttendeeSign = (index) => {
    setAttendees(prev => prev.map((a, i) =>
      i === index ? { ...a, signed: !a.signed } : a
    ));
  };

  const addAttendee = () => {
    setAttendees(prev => [...prev, { worker_id: null, name: '', company: '', signed: false }]);
  };

  const updateAttendee = (index, field, value) => {
    setAttendees(prev => prev.map((a, i) =>
      i === index ? { ...a, [field]: value } : a
    ));
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      const payload = {
        project_id: projectId,
        log_type: 'toolbox_talk',
        date,
        data: {
          location,
          company_name: companyName,
          type_of_work: typeOfWork,
          meeting_time: meetingTime,
          performed_by: performedBy,
          checked_topics: checkedTopics,
          attendees,
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
      toast.success(submitStatus === 'submitted' ? 'Submitted' : 'Saved', 'Tool Box Talk saved');
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save log');
    } finally {
      setSaving(false);
    }
  };

  const checkedCount = Object.values(checkedTopics).filter(Boolean).length;
  const signedCount = attendees.filter(a => a.signed).length;

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
              <Text style={styles.headerTitle}>Tool Box Talk</Text>
              <Text style={styles.headerSub}>OSHA — Weekly Safety Meeting</Text>
            </View>
          </View>
          <View style={styles.statRow}>
            <View style={styles.statBadge}>
              <Text style={styles.statText}>{checkedCount} topics</Text>
            </View>
            <View style={styles.statBadge}>
              <Text style={styles.statText}>{signedCount} signed</Text>
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

          {/* Header Info */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionHeader}>Meeting Information</Text>
            {[
              { label: 'Location', value: location, setter: setLocation },
              { label: 'Company Name', value: companyName, setter: setCompanyName },
              { label: 'Type of Work', value: typeOfWork, setter: setTypeOfWork },
              { label: 'Time', value: meetingTime, setter: setMeetingTime },
              { label: 'Performed By (CP)', value: performedBy, setter: setPerformedBy },
            ].map((f) => (
              <View key={f.label} style={styles.fieldRow}>
                <Text style={styles.fieldLabel}>{f.label}</Text>
                <TextInput
                  style={styles.fieldInput}
                  value={f.value}
                  onChangeText={f.setter}
                  placeholder="—"
                  placeholderTextColor={colors.text.subtle}
                />
              </View>
            ))}
          </GlassCard>

          {/* Topics Grid */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionHeader}>Topics Covered</Text>
            <Text style={styles.sectionSubtitle}>Check all topics discussed in this meeting</Text>
            {Object.entries(TOPICS).map(([category, items]) => (
              <View key={category} style={styles.topicCategory}>
                <Text style={styles.topicCategoryLabel}>{category}</Text>
                <View style={styles.topicGrid}>
                  {items.map((item) => {
                    const isChecked = !!checkedTopics[item.key];
                    return (
                      <Pressable
                        key={item.key}
                        onPress={() => toggleTopic(item.key)}
                        style={[styles.topicItem, isChecked && styles.topicItemActive]}
                      >
                        <View style={[styles.topicCheckbox, isChecked && styles.topicCheckboxActive]}>
                          {isChecked && <Check size={12} strokeWidth={2.5} color="#fff" />}
                        </View>
                        <Text style={[styles.topicLabel, isChecked && styles.topicLabelActive]}>
                          {item.label}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              </View>
            ))}
          </GlassCard>

          {/* Worker Sign-In */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Users size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.sectionHeader}>Attendees</Text>
              <Text style={styles.attendeeCount}>{attendees.length} workers</Text>
            </View>
            <Text style={styles.sectionSubtitle}>
              Workers auto-populated from today's check-ins. Tap to mark as signed.
            </Text>

            {/* Table Header */}
            <View style={styles.tableHeader}>
              <Text style={[styles.tableHeaderText, { flex: 2 }]}>Name</Text>
              <Text style={[styles.tableHeaderText, { flex: 2 }]}>Company</Text>
              <Text style={[styles.tableHeaderText, { flex: 1, textAlign: 'center' }]}>Signed</Text>
            </View>

            {attendees.map((attendee, index) => (
              <View key={index} style={styles.attendeeRow}>
                <TextInput
                  style={[styles.attendeeInput, { flex: 2 }]}
                  value={attendee.name}
                  onChangeText={(v) => updateAttendee(index, 'name', v)}
                  placeholder="Name"
                  placeholderTextColor={colors.text.subtle}
                />
                <TextInput
                  style={[styles.attendeeInput, { flex: 2 }]}
                  value={attendee.company}
                  onChangeText={(v) => updateAttendee(index, 'company', v)}
                  placeholder="Company"
                  placeholderTextColor={colors.text.subtle}
                />
                <Pressable
                  onPress={() => toggleAttendeeSign(index)}
                  style={[styles.signedToggle, attendee.signed && styles.signedToggleActive]}
                >
                  {attendee.signed
                    ? <CheckCircle size={20} strokeWidth={1.5} color="#4ade80" />
                    : <View style={styles.unsignedCircle} />
                  }
                </Pressable>
              </View>
            ))}

            <GlassButton
              title="+ Add Worker"
              onPress={addAttendee}
              style={styles.addWorkerBtn}
            />
          </GlassCard>

          {/* CP Signature */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <BookOpen size={16} strokeWidth={1.5} color="#3b82f6" />
              <Text style={styles.sectionHeader}>Performed By — CP Signature</Text>
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
              disabled={!cpSignature || attendees.length === 0}
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
  statRow: { flexDirection: 'row', gap: spacing.xs },
  statBadge: {
    backgroundColor: 'rgba(59,130,246,0.15)',
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
    borderWidth: 1,
    borderColor: 'rgba(59,130,246,0.3)',
  },
  statText: { fontSize: 11, color: '#60a5fa', fontWeight: '600' },
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
  sectionHeader: { fontSize: 16, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.md },
  sectionHeaderRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.md },
  sectionSubtitle: { fontSize: 12, color: colors.text.muted, marginBottom: spacing.md, marginTop: -spacing.sm },
  attendeeCount: { marginLeft: 'auto', fontSize: 12, color: colors.text.muted },
  fieldRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.05)',
    gap: spacing.md,
  },
  fieldLabel: { flex: 1, fontSize: 13, color: colors.text.secondary },
  fieldInput: {
    flex: 1.5,
    fontSize: 14,
    color: colors.text.primary,
    textAlign: 'right',
    padding: spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.sm,
  },
  topicCategory: { marginBottom: spacing.md },
  topicCategoryLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: spacing.sm,
  },
  topicGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  topicItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    backgroundColor: 'rgba(255,255,255,0.04)',
  },
  topicItemActive: {
    backgroundColor: 'rgba(59,130,246,0.15)',
    borderColor: 'rgba(59,130,246,0.4)',
  },
  topicCheckbox: {
    width: 18,
    height: 18,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.2)',
    backgroundColor: 'rgba(255,255,255,0.05)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  topicCheckboxActive: { backgroundColor: '#3b82f6', borderColor: '#3b82f6' },
  topicLabel: { fontSize: 13, color: colors.text.muted },
  topicLabelActive: { color: '#93c5fd', fontWeight: '500' },
  tableHeader: {
    flexDirection: 'row',
    paddingBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.08)',
    marginBottom: spacing.xs,
  },
  tableHeaderText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  attendeeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.04)',
  },
  attendeeInput: {
    fontSize: 13,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.sm,
  },
  signedToggle: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.xs,
  },
  signedToggleActive: {},
  unsignedCircle: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.2)',
  },
  addWorkerBtn: { marginTop: spacing.md, borderStyle: 'dashed' },
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
  submitBtn: { flex: 2, backgroundColor: 'rgba(59,130,246,0.2)', borderColor: 'rgba(59,130,246,0.4)' },
});
