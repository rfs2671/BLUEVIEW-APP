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
import LogbookLockBar from '../../src/components/LogbookLockBar';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI } from '../../src/utils/api';
import { draftKey, readDraft, writeDraft, setDraftBackendId, markPending, clearPending, markFinalized } from '../../src/utils/logbookDrafts';
import { freezeIfImmediate } from '../../src/utils/logbookTiming';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useTheme } from '../../src/context/ThemeContext';

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
  // Tier 1 (1)b: true when the loaded log is finalized (is_locked) — the form
  // renders read-only and only the Amend path can change anything.
  const [locked, setLocked] = useState(false);
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

  // Auto-fill Performed By from CP profile when available
  useEffect(() => {
    if (cpName && !performedBy) {
      setPerformedBy(cpName);
    }
  }, [cpName]);

  // Phase A — autosave every field change to the LOCAL draft (AsyncStorage).
  // Debounced so typing doesn't thrash storage; makes no server call. This is
  // what lets the CP fill with zero network and reopen to the same draft.
  // `status` is intentionally omitted so an autosave never downgrades a
  // submitted log back to draft.
  useEffect(() => {
    if (loading) return undefined;
    const t = setTimeout(() => {
      writeDraft(
        draftKey({ projectId, logType: 'toolbox_talk', date }),
        {
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
        },
      ).catch(() => {});
    }, 800);
    return () => clearTimeout(t);
  }, [
    loading, projectId, date, location, companyName, typeOfWork, meetingTime,
    performedBy, checkedTopics, attendees, cpSignature, cpName,
  ]);

  const fetchData = async () => {
    setLoading(true);
    try {
      // Phase A — local-first: read the on-device draft first. If a local copy
      // exists, hydrate from it and skip the server fetch + check-in
      // auto-populate entirely (works fully offline).
      const key = draftKey({ projectId, logType: 'toolbox_talk', date });
      const draft = await readDraft(key);
      if (draft) {
        // Tier 1 (1)b: a draft marked finalized locks the form read-only.
        if (draft.finalized) {
          setLocked(true);
          markFinalized(key);
        }
        setExistingLogId(draft.backend_id);
        const d = draft.data || {};
        if (d.location) setLocation(d.location);
        if (d.company_name) setCompanyName(d.company_name);
        if (d.type_of_work) setTypeOfWork(d.type_of_work);
        if (d.meeting_time) setMeetingTime(d.meeting_time);
        if (d.performed_by) setPerformedBy(d.performed_by);
        if (d.checked_topics) setCheckedTopics(d.checked_topics);
        if (d.attendees && d.attendees.length > 0) setAttendees(d.attendees);
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        setLoading(false);
        return;
      }

      const [projectData, checkins, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'toolbox_talk', date).catch(() => []),
      ]);

      if (projectData) {
        setProject(projectData);
        setLocation(projectData.address || projectData.location || '');
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

      // Tier 1 (1)b: prefer the EDITABLE (non-locked) doc — an amendment child —
      // over a locked original that shares (project, type, date).
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find(l => !l.is_locked) || arr[0] || null;
      if (existing) {
        if (existing.is_locked) {
          setLocked(true);
          markFinalized(key);  // lock the offline draft too (mirrors the backend 423)
        }
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
          
        // Auto-fill company name from project or user
        if (projectData?.company) {
          setCompanyName(projectData.company);
        } else if (user?.company_name) {
          setCompanyName(user.company_name);
        } else if (user?.name) {
          setCompanyName(user.name.split(' ')[0]); // fallback
        }
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
    const key = draftKey({ projectId, logType: 'toolbox_talk', date });
    const data = {
      location,
      company_name: companyName,
      type_of_work: typeOfWork,
      meeting_time: meetingTime,
      performed_by: performedBy,
      checked_topics: checkedTopics,
      attendees,
    };
    try {
      // Phase A — write the LOCAL draft first. Source of truth, needs no network,
      // so an offline CP completes the log without the "could not save" failure.
      await writeDraft(key, { data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus });

      // Best-effort server push. Offline this throws and is swallowed — the key
      // is recorded in the pending-push list for the Phase B reconnect flush.
      // NOTE: a submit made offline has no server id yet, so the signature-audit
      // record below is skipped until the draft syncs (a Phase B reconcile item).
      let savedId = existingLogId;
      let pushOk = true;
      try {
        if (existingLogId) {
          await logbooksAPI.update(existingLogId, {
            data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
          });
        } else {
          const created = await logbooksAPI.create({
            project_id: projectId, log_type: 'toolbox_talk', date,
            data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus,
          });
          savedId = created.id || created._id;
          setExistingLogId(savedId);
        }
        await setDraftBackendId(key, savedId);
        await clearPending(key);
      } catch (pushErr) {
        pushOk = false;
        await markPending(key);
        console.warn('Logbook server push deferred (will sync on reconnect):', pushErr?.message);
      }

      // FREEZE ON SIGN — toolbox_talk is an IMMEDIATE log: the SIGNATURE IS THE
      // FREEZE. "Submit & Sign" finalizes the record in one action (there is no
      // separate Finalize step, and it is never reopened). This runs after the
      // local writeDraft above — so the frozen draft holds the SIGNED content —
      // and after the push attempt on BOTH paths, because the talk is signed at
      // the muster point with no signal: the freeze must not need the server. A
      // later talk that day is a NEW log; corrections go through Amend.
      if (submitStatus === 'submitted') {
        await freezeIfImmediate(key, 'toolbox_talk');
        setLocked(true);
      }

      await autoSave(cpName, cpSignature).catch(() => {});

      if (submitStatus === 'submitted' && cpSignature && savedId) {
        const { recordSignatureEvent } = require('../../src/utils/signatureAudit');
        recordSignatureEvent({
          documentType: 'logbook', documentId: savedId, eventType: 'cp_sign',
          signerName: cpName, signerRole: user?.role || 'cp',
          signatureData: cpSignature,
          contentSnapshot: { log_type: 'toolbox_talk', date, project_id: projectId, data, status: submitStatus },
          user,
        }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
      }

      toast.success(
        submitStatus === 'submitted' ? 'Signed & Locked' : 'Saved',
        submitStatus !== 'submitted'
          ? 'Tool Box Talk saved'
          : pushOk
            ? 'Signed — this log is now locked. Corrections require an amendment.'
            : 'Signed — locked on this device and will sync when you are back online.');
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
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/logbooks')}
            />
            <View>
              <Text style={s.headerTitle}>Tool Box Talk</Text>
              <Text style={s.headerSub}>OSHA — Weekly Safety Meeting</Text>
            </View>
          </View>
          <View style={s.statRow}>
            <View style={s.statBadge}>
              <Text style={s.statText}>{checkedCount} topics</Text>
            </View>
            <View style={s.statBadge}>
              <Text style={s.statText}>{signedCount} signed</Text>
            </View>
          </View>
        </View>

        <ScrollView style={s.scrollView} contentContainerStyle={s.scrollContent} showsVerticalScrollIndicator={false}>

          {/* Tier 1 (1)b: a finalized log renders read-only. pointerEvents 'none'
              makes EVERY field below non-interactive (no per-field editable flags
              to miss). Scrolling still works; the LockBar stays interactive. */}
          <View pointerEvents={locked ? 'none' : 'auto'}>

          {/* Date */}
          <GlassCard style={s.dateCard}>
            <Calendar size={16} strokeWidth={1.5} color={colors.text.muted} />
            <Text style={s.dateText}>
              {new Date(date + 'T12:00:00').toLocaleDateString('en-US', {
                weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
              })}
            </Text>
          </GlassCard>

          {/* Header Info */}
          <GlassCard style={s.section}>
            <Text style={s.sectionHeader}>Meeting Information</Text>
            {[
              { label: 'Location', value: location, setter: setLocation },
              { label: 'Company Name', value: companyName, setter: setCompanyName },
              { label: 'Type of Work', value: typeOfWork, setter: setTypeOfWork },
              { label: 'Time', value: meetingTime, setter: setMeetingTime },
              { label: 'Performed By (CP)', value: performedBy, setter: setPerformedBy },
            ].map((f) => (
              <View key={f.label} style={s.fieldRow}>
                <Text style={s.fieldLabel}>{f.label}</Text>
                <TextInput
                  style={s.fieldInput}
                  value={f.value}
                  onChangeText={f.setter}
                  placeholder="—"
                  placeholderTextColor={colors.text.subtle}
                />
              </View>
            ))}
          </GlassCard>

          {/* Topics Grid */}
          <GlassCard style={s.section}>
            <Text style={s.sectionHeader}>Topics Covered</Text>
            <Text style={s.sectionSubtitle}>Check all topics discussed in this meeting</Text>
            {Object.entries(TOPICS).map(([category, items]) => (
              <View key={category} style={s.topicCategory}>
                <Text style={s.topicCategoryLabel}>{category}</Text>
                <View style={s.topicGrid}>
                  {items.map((item) => {
                    const isChecked = !!checkedTopics[item.key];
                    return (
                      <Pressable
                        key={item.key}
                        onPress={() => toggleTopic(item.key)}
                        style={[s.topicItem, isChecked && s.topicItemActive]}
                      >
                        <View style={[s.topicCheckbox, isChecked && s.topicCheckboxActive]}>
                          {isChecked && <Check size={12} strokeWidth={2.5} color="#fff" />}
                        </View>
                        <Text style={[s.topicLabel, isChecked && s.topicLabelActive]}>
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
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <Users size={16} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.sectionHeader}>Attendees</Text>
              <Text style={s.attendeeCount}>{attendees.length} workers</Text>
            </View>
            <Text style={s.sectionSubtitle}>
              Workers auto-populated from today's check-ins. Tap to mark as signed.
            </Text>

            {/* Table Header */}
            <View style={s.tableHeader}>
              <Text style={[s.tableHeaderText, { flex: 2 }]}>Name</Text>
              <Text style={[s.tableHeaderText, { flex: 2 }]}>Company</Text>
              <Text style={[s.tableHeaderText, { flex: 1, textAlign: 'center' }]}>Signed</Text>
            </View>

            {attendees.map((attendee, index) => (
              <View key={index} style={s.attendeeRow}>
                <TextInput
                  style={[s.attendeeInput, { flex: 2 }]}
                  value={attendee.name}
                  onChangeText={(v) => updateAttendee(index, 'name', v)}
                  placeholder="Name"
                  placeholderTextColor={colors.text.subtle}
                />
                <TextInput
                  style={[s.attendeeInput, { flex: 2 }]}
                  value={attendee.company}
                  onChangeText={(v) => updateAttendee(index, 'company', v)}
                  placeholder="Company"
                  placeholderTextColor={colors.text.subtle}
                />
                <Pressable
                  onPress={() => toggleAttendeeSign(index)}
                  style={[s.signedToggle, attendee.signed && s.signedToggleActive]}
                >
                  {attendee.signed
                    ? <CheckCircle size={20} strokeWidth={1.5} color={semantic.verified} />
                    : <View style={s.unsignedCircle} />
                  }
                </Pressable>
              </View>
            ))}

            <GlassButton
              title="+ Add Worker"
              onPress={addAttendee}
              style={s.addWorkerBtn}
            />
          </GlassCard>

          {/* CP Signature */}
          <GlassCard style={s.section}>
            <View style={s.sectionHeaderRow}>
              <BookOpen size={16} strokeWidth={1.5} color="#3b82f6" />
              <Text style={s.sectionHeader}>Performed By — CP Signature</Text>
            </View>
            <SignaturePad
              title="Competent Person Signature"
              signerName={cpName}
              onNameChange={setCpName}
              existingSignature={cpSignature}
              onSignatureCapture={setCpSignature}
            />
          </GlassCard>
          </View>

          {/* Actions — hidden when finalized; the LockBar handles finalize/amend. */}
          {!locked && (
          <View style={s.actions}>
            <GlassButton
              title={saving ? 'Saving...' : 'Save Draft'}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => handleSave('draft')}
              loading={saving}
              style={s.draftBtn}
            />
            <GlassButton
              title={saving ? 'Submitting...' : 'Submit & Sign'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color="#fff" />}
              onPress={() => handleSave('submitted')}
              loading={saving}
              disabled={!cpSignature || attendees.length === 0}
              style={s.submitBtn}
            />
          </View>
          )}

          {/* logType drives the FREEZE MODEL: toolbox_talk is IMMEDIATE, so the
              bar hides Finalize (the signature already froze the log) and offers
              only Amend once locked. canFinalize stays false for that reason. */}
          <LogbookLockBar
            locked={locked}
            logId={existingLogId}
            logType="toolbox_talk"
            canFinalize={false}
            onFinalized={() => setLocked(true)}
            onAmended={fetchData}
          />
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: { flex: 1 },
  loadingCenter: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.08),
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
    borderBottomColor: withAlpha('#ffffff', 0.05),
    gap: spacing.md,
  },
  fieldLabel: { flex: 1, fontSize: 13, color: colors.text.secondary },
  fieldInput: {
    flex: 1.5,
    fontSize: 14,
    color: colors.text.primary,
    textAlign: 'right',
    padding: spacing.xs,
    backgroundColor: withAlpha('#ffffff', 0.04),
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
    borderColor: withAlpha('#ffffff', 0.1),
    backgroundColor: withAlpha('#ffffff', 0.04),
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
    borderColor: withAlpha('#ffffff', 0.2),
    backgroundColor: withAlpha('#ffffff', 0.05),
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
    borderBottomColor: withAlpha('#ffffff', 0.08),
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
    borderBottomColor: withAlpha('#ffffff', 0.04),
  },
  attendeeInput: {
    fontSize: 13,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: withAlpha('#ffffff', 0.04),
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
    borderColor: withAlpha('#ffffff', 0.2),
  },
  addWorkerBtn: { marginTop: spacing.md, borderStyle: 'dashed' },
  autoSignBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.md,
    padding: spacing.sm,
    backgroundColor: semantic.verifiedBg,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: semantic.verifiedBorder,
  },
  autoSignText: { fontSize: 12, color: semantic.verified },
  actions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  draftBtn: { flex: 1 },
  submitBtn: { flex: 2, backgroundColor: 'rgba(59,130,246,0.2)', borderColor: 'rgba(59,130,246,0.4)' },
});
}
