import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, Users, CheckCircle, XCircle, Save, Plus, Calendar,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, cpProfileAPI, projectsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

const EMPTY_WORKER = () => ({
  worker_id: null,
  name: '',
  had_injury: null,   // null | 'yes' | 'no'
  inspected_ppe: null, // null | 'yes' | 'no'
  signed: false,
});

export default function PreShiftSignIn() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);
  const [cpProfile, setCpProfile] = useState(null);

  const [company, setCompany] = useState('');
  const [projectLocation, setProjectLocation] = useState('');
  const [workers, setWorkers] = useState(Array.from({ length: 5 }, EMPTY_WORKER));
  const [cpSignature, setCpSignature] = useState(null);
  const [cpName, setCpName] = useState('');

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [projectData, profile, checkins, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        cpProfileAPI.getProfile().catch(() => null),
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'preshift_signin', date).catch(() => []),
      ]);

      if (projectData) {
        setProjectLocation(projectData.address || projectData.location || '');
      }

      if (profile) {
        setCpProfile(profile);
        setCpName(profile.cp_name || '');
        if (profile.cp_signature) setCpSignature(profile.cp_signature);
      }

      const checkinList = Array.isArray(checkins) ? checkins : [];

      const existing = Array.isArray(existingLogs) && existingLogs.length > 0 ? existingLogs[0] : null;
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.company) setCompany(d.company);
        if (d.project_location) setProjectLocation(d.project_location);
        if (d.workers && d.workers.length > 0) {
          setWorkers(d.workers);
        } else {
          buildWorkerList(checkinList);
        }
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      } else {
        buildWorkerList(checkinList);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const buildWorkerList = (checkins) => {
    if (checkins.length === 0) {
      setWorkers(Array.from({ length: 5 }, EMPTY_WORKER));
      return;
    }
    const list = checkins.map((c) => ({
      worker_id: c.worker_id,
      name: c.worker_name || '',
      had_injury: null,
      inspected_ppe: null,
      signed: false,
    }));
    // Pad to at least 5 rows
    while (list.length < 5) list.push(EMPTY_WORKER());
    setWorkers(list);
  };

  const updateWorker = (index, field, value) => {
    setWorkers(prev => prev.map((w, i) => i === index ? { ...w, [field]: value } : w));
  };

  const addRow = () => {
    setWorkers(prev => [...prev, EMPTY_WORKER()]);
  };

  const filledWorkers = workers.filter(w => w.name.trim());

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      const payload = {
        project_id: projectId,
        log_type: 'preshift_signin',
        date,
        data: {
          company,
          project_location: projectLocation,
          workers,
          total_count: filledWorkers.length,
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

      toast.success(submitStatus === 'submitted' ? 'Submitted' : 'Saved', 'Pre-Shift log saved');
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save log');
    } finally {
      setSaving(false);
    }
  };

  const YesNoToggle = ({ value, onChange }) => (
    <View style={styles.ynRow}>
      <Pressable
        onPress={() => onChange(value === 'yes' ? null : 'yes')}
        style={[styles.ynBtn, value === 'yes' && styles.ynBtnYes]}
      >
        <Text style={[styles.ynText, value === 'yes' && styles.ynTextYes]}>Y</Text>
      </Pressable>
      <Pressable
        onPress={() => onChange(value === 'no' ? null : 'no')}
        style={[styles.ynBtn, value === 'no' && styles.ynBtnNo]}
      >
        <Text style={[styles.ynText, value === 'no' && styles.ynTextNo]}>N</Text>
      </Pressable>
    </View>
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
              onPress={() => router.back()}
            />
            <View>
              <Text style={styles.headerTitle}>Daily Pre-Shift Safety Meeting</Text>
              <Text style={styles.headerSub}>Sign-In Sheet</Text>
            </View>
          </View>
          <View style={styles.countBadge}>
            <Users size={14} strokeWidth={1.5} color="#60a5fa" />
            <Text style={styles.countText}>{filledWorkers.length}</Text>
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
            <Text style={styles.sectionTitle}>Meeting Details</Text>
            {[
              { label: 'Company', value: company, setter: setCompany },
              { label: 'Project Location', value: projectLocation, setter: setProjectLocation },
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

          {/* Worker Sign-In Table */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>Worker Sign-In</Text>
            <Text style={styles.sectionSubtitle}>
              Workers auto-populated from today's check-ins. Complete each column.
            </Text>

            {/* Column Headers */}
            <View style={styles.tableHeader}>
              <Text style={[styles.colHeader, { flex: 3 }]}>First & Last Name</Text>
              <Text style={[styles.colHeader, { flex: 2, textAlign: 'center' }]}>Injury / Incident Last Time?</Text>
              <Text style={[styles.colHeader, { flex: 2, textAlign: 'center' }]}>Inspected PPE Today?</Text>
            </View>

            {workers.map((worker, index) => (
              <View key={index} style={styles.workerRow}>
                <View style={{ flex: 3 }}>
                  <TextInput
                    style={styles.nameInput}
                    value={worker.name}
                    onChangeText={(v) => updateWorker(index, 'name', v)}
                    placeholder={`${index + 1}.`}
                    placeholderTextColor={colors.text.subtle}
                  />
                </View>
                <View style={[styles.ynCell, { flex: 2 }]}>
                  <YesNoToggle
                    value={worker.had_injury}
                    onChange={(v) => updateWorker(index, 'had_injury', v)}
                  />
                </View>
                <View style={[styles.ynCell, { flex: 2 }]}>
                  <YesNoToggle
                    value={worker.inspected_ppe}
                    onChange={(v) => updateWorker(index, 'inspected_ppe', v)}
                  />
                </View>
              </View>
            ))}

            <GlassButton
              title="+ Add Row"
              icon={<Plus size={14} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={addRow}
              style={styles.addRowBtn}
            />

            {/* Total */}
            <View style={styles.totalRow}>
              <Text style={styles.totalLabel}>TOTAL COUNT</Text>
              <Text style={styles.totalValue}>{filledWorkers.length}</Text>
            </View>
          </GlassCard>

          {/* CP Signature */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <Users size={16} strokeWidth={1.5} color="#4ade80" />
              <Text style={styles.sectionTitle}>Competent Person Signature</Text>
            </View>
            {cpProfile?.has_signature && cpSignature && (
              <View style={styles.autoSignBadge}>
                <CheckCircle size={14} strokeWidth={1.5} color="#4ade80" />
                <Text style={styles.autoSignText}>Auto-signed from your CP profile</Text>
              </View>
            )}
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
              disabled={!cpSignature || filledWorkers.length === 0}
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
  countBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: 'rgba(59,130,246,0.15)',
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: 'rgba(59,130,246,0.3)',
  },
  countText: { fontSize: 14, fontWeight: '600', color: '#60a5fa' },
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
    flex: 2,
    fontSize: 14,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.sm,
  },
  tableHeader: {
    flexDirection: 'row',
    paddingBottom: spacing.sm,
    marginBottom: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  colHeader: {
    fontSize: 10,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  workerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.04)',
    gap: spacing.sm,
  },
  nameInput: {
    fontSize: 13,
    color: colors.text.primary,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.sm,
  },
  ynCell: { alignItems: 'center', justifyContent: 'center' },
  ynRow: { flexDirection: 'row', gap: 4 },
  ynBtn: {
    width: 30,
    height: 28,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,0.04)',
  },
  ynBtnYes: { backgroundColor: 'rgba(74,222,128,0.15)', borderColor: 'rgba(74,222,128,0.4)' },
  ynBtnNo: { backgroundColor: 'rgba(239,68,68,0.15)', borderColor: 'rgba(239,68,68,0.4)' },
  ynText: { fontSize: 12, fontWeight: '700', color: colors.text.muted },
  ynTextYes: { color: '#4ade80' },
  ynTextNo: { color: '#f87171' },
  addRowBtn: { marginTop: spacing.md },
  totalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.1)',
  },
  totalLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  totalValue: { fontSize: 20, fontWeight: '300', color: colors.text.primary },
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
  submitBtn: { flex: 2, backgroundColor: 'rgba(74,222,128,0.15)', borderColor: 'rgba(74,222,128,0.3)' },
});
