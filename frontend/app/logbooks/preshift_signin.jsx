import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, Image,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, Users, CheckCircle, XCircle, Save, Plus, Calendar, Lock,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import SignatureImage from '../../src/components/SignatureImage';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI, projectsAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

/**
 * EMPTY_WORKER now includes all fields that come from a worker's sign-in record.
 * - auto_filled: true  → worker came from today's check-ins (name/company/osha locked)
 * - auto_filled: false → manually added row (all fields editable)
 * - worker_signature   → the signature the worker drew when they signed in via NFC/QR
 */
const EMPTY_WORKER = () => ({
  worker_id: null,
  name: '',
  company: '',
  osha_number: '',
  worker_signature: null,
  had_injury: null,    // null | 'yes' | 'no'
  inspected_ppe: null, // null | 'yes' | 'no'
  signed: false,
  auto_filled: false,
});

export default function PreShiftSignIn() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);

  const [company, setCompany] = useState('');
  const [projectLocation, setProjectLocation] = useState('');
  const [workers, setWorkers] = useState(Array.from({ length: 5 }, EMPTY_WORKER));

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [projectData, checkins, existingLogs] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        logbooksAPI.getByProject(projectId, 'preshift_signin', date).catch(() => []),
      ]);

      if (projectData) {
        setProjectLocation(projectData.address || projectData.location || projectData.name || '');
        // Pre-fill company from project data if available
        const companyVal = projectData.company_name || projectData.company || '';
        if (companyVal) setCompany(companyVal);
      }

      const checkinList = Array.isArray(checkins) ? checkins : [];

      const existing = Array.isArray(existingLogs) && existingLogs.length > 0 ? existingLogs[0] : null;
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.company) setCompany(d.company);
        if (d.project_location) setProjectLocation(d.project_location);
        if (d.workers && d.workers.length > 0) {
          // Saved log already has full worker data — use it
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

  /**
   * Builds the worker list from today's check-ins.
   * Captures: name, company, osha_number, and worker_signature — all locked (read-only).
   * Pads to at least 5 rows with empty editable rows.
   */
  const buildWorkerList = (checkins) => {
    if (checkins.length === 0) {
      setWorkers(Array.from({ length: 5 }, EMPTY_WORKER));
      return;
    }
    const list = checkins.map((c) => ({
      worker_id: c.worker_id,
      name: c.worker_name || '',
      company: c.company || '',
      osha_number: c.osha_number || '',
      // New-system rows carry signin_id → authed proxy endpoint.
      // Legacy rows carry inline base64 in worker_signature.
      signin_id: c.signin_id || null,
      worker_signature: c.worker_signature || c.signature || null,
      had_injury: null,
      inspected_ppe: null,
      signed: false,
      auto_filled: true, // Lock identity fields — came from sign-in system
    }));
    // Pad with empty manual rows
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

      await autoSave(cpName, cpSignature);

      if (submitStatus === 'submitted' && cpSignature) {
        const docId = existingLogId || created?.id || created?._id;
        if (docId) {
          const { recordSignatureEvent } = require('../../src/utils/signatureAudit');
          recordSignatureEvent({
            documentType: 'logbook', documentId: docId, eventType: 'cp_sign',
            signerName: cpName, signerRole: user?.role || 'cp',
            signatureData: cpSignature,
            contentSnapshot: { log_type: 'preshift_signin', date, project_id: projectId, data: payload.data, status: submitStatus },
            user,
          }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
        }
      }

      toast.success(submitStatus === 'submitted' ? 'Submitted' : 'Draft Saved',
        submitStatus === 'submitted' ? 'Pre-shift sign-in submitted' : 'Draft saved');
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
              onPress={() => router.push('/logbooks')}
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

            {workers.map((worker, index) => (
              <View key={index} style={styles.workerCard}>

                {/* Row number + lock badge */}
                <View style={styles.workerCardHeader}>
                  <Text style={styles.workerIndex}>{index + 1}</Text>
                  {worker.auto_filled && (
                    <View style={styles.autoFilledBadge}>
                      <Lock size={10} strokeWidth={2} color="#60a5fa" />
                      <Text style={styles.autoFilledText}>Auto-filled</Text>
                    </View>
                  )}
                </View>

                {/* Name */}
                <View style={styles.workerField}>
                  <Text style={styles.workerFieldLabel}>NAME</Text>
                  {worker.auto_filled ? (
                    <Text style={styles.workerFieldValueLocked}>{worker.name || '—'}</Text>
                  ) : (
                    <TextInput
                      style={styles.workerFieldInput}
                      value={worker.name}
                      onChangeText={(v) => updateWorker(index, 'name', v)}
                      placeholder="First & Last Name"
                      placeholderTextColor={colors.text.subtle}
                    />
                  )}
                </View>

                {/* Company */}
                <View style={styles.workerField}>
                  <Text style={styles.workerFieldLabel}>COMPANY</Text>
                  {worker.auto_filled ? (
                    <Text style={styles.workerFieldValueLocked}>{worker.company || '—'}</Text>
                  ) : (
                    <TextInput
                      style={styles.workerFieldInput}
                      value={worker.company}
                      onChangeText={(v) => updateWorker(index, 'company', v)}
                      placeholder="Company name"
                      placeholderTextColor={colors.text.subtle}
                    />
                  )}
                </View>

                {/* OSHA Number */}
                <View style={styles.workerField}>
                  <Text style={styles.workerFieldLabel}>OSHA #</Text>
                  {worker.auto_filled ? (
                    <Text style={styles.workerFieldValueLocked}>
                      {worker.osha_number || <Text style={styles.workerFieldEmpty}>—</Text>}
                    </Text>
                  ) : (
                    <TextInput
                      style={styles.workerFieldInput}
                      value={worker.osha_number}
                      onChangeText={(v) => updateWorker(index, 'osha_number', v)}
                      placeholder="OSHA card number"
                      placeholderTextColor={colors.text.subtle}
                    />
                  )}
                </View>

                {/* Worker Signature — auto-filled from gate sign-in
                    via authenticated proxy endpoint, or inline base64
                    for legacy checkins. */}
                <View style={styles.workerField}>
                  <Text style={styles.workerFieldLabel}>WORKER SIGNATURE</Text>
                  {(worker.signin_id || worker.worker_signature) ? (
                    <View style={styles.sigContainer}>
                      <SignatureImage
                        signInId={worker.signin_id}
                        fallbackBase64={worker.worker_signature}
                        style={styles.sigImage}
                      />
                    </View>
                  ) : (
                    <View style={styles.sigMissing}>
                      <XCircle size={14} strokeWidth={1.5} color={colors.text.subtle} />
                      <Text style={styles.sigMissingText}>Not signed</Text>
                    </View>
                  )}
                </View>

                {/* Y/N Questions */}
                <View style={styles.ynBlock}>
                  <View style={styles.ynItem}>
                    <Text style={styles.ynLabel}>Injury / Incident last time?</Text>
                    <YesNoToggle
                      value={worker.had_injury}
                      onChange={(v) => updateWorker(index, 'had_injury', v)}
                    />
                  </View>
                  <View style={styles.ynItem}>
                    <Text style={styles.ynLabel}>Inspected PPE today?</Text>
                    <YesNoToggle
                      value={worker.inspected_ppe}
                      onChange={(v) => updateWorker(index, 'inspected_ppe', v)}
                    />
                  </View>
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
              title={saving ? 'Submitting...' : 'Submit'}
              icon={<CheckCircle size={16} strokeWidth={1.5} color="#4ade80" />}
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
  loadingCenter: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flex: 1 },
  headerTitle: { fontSize: 15, fontWeight: '600', color: colors.text.primary },
  headerSub: { fontSize: 12, color: colors.text.muted },
  countBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(96,165,250,0.15)',
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(96,165,250,0.3)',
  },
  countText: { fontSize: 13, fontWeight: '700', color: '#60a5fa' },
  scrollView: { flex: 1 },
  scrollContent: { paddingHorizontal: spacing.md, paddingBottom: spacing.xl * 2 },
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

  // Worker card layout — one card per worker instead of a flat table row
  workerCard: {
    backgroundColor: 'rgba(255,255,255,0.03)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.07)',
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  workerCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  workerIndex: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  autoFilledBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: 'rgba(96,165,250,0.1)',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(96,165,250,0.25)',
  },
  autoFilledText: { fontSize: 10, color: '#60a5fa', fontWeight: '600' },

  workerField: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.04)',
    gap: spacing.sm,
    minHeight: 36,
  },
  workerFieldLabel: {
    width: 110,
    fontSize: 10,
    fontWeight: '700',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  workerFieldValueLocked: {
    flex: 1,
    fontSize: 14,
    color: colors.text.primary,
    fontWeight: '500',
  },
  workerFieldEmpty: {
    color: colors.text.subtle,
  },
  workerFieldInput: {
    flex: 1,
    fontSize: 14,
    color: colors.text.primary,
    padding: spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: borderRadius.sm,
  },

  // Signature display inside worker card
  sigContainer: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  sigImage: {
    width: 120,
    height: 36,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: borderRadius.sm,
  },
  sigSignedBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  sigSignedText: { fontSize: 11, color: '#4ade80', fontWeight: '600' },
  sigMissing: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  sigMissingText: { fontSize: 12, color: colors.text.subtle, fontStyle: 'italic' },

  // Y/N block
  ynBlock: {
    marginTop: spacing.sm,
    gap: spacing.xs,
  },
  ynItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 2,
  },
  ynLabel: { flex: 1, fontSize: 12, color: colors.text.secondary },
  ynRow: { flexDirection: 'row', gap: 4 },
  ynBtn: {
    width: 32,
    height: 26,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.04)',
  },
  ynBtnYes: { backgroundColor: 'rgba(74,222,128,0.15)', borderColor: '#4ade80' },
  ynBtnNo: { backgroundColor: 'rgba(239,68,68,0.15)', borderColor: '#ef4444' },
  ynText: { fontSize: 11, fontWeight: '700', color: colors.text.muted },
  ynTextYes: { color: '#4ade80' },
  ynTextNo: { color: '#ef4444' },

  addRowBtn: { marginTop: spacing.sm, alignSelf: 'flex-start' },
  totalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.1)',
  },
  totalLabel: { fontSize: 11, fontWeight: '700', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 0.5 },
  totalValue: { fontSize: 22, fontWeight: '800', color: colors.text.primary },

  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
    marginBottom: spacing.xl,
  },
  draftBtn: { flex: 1 },
  submitBtn: { flex: 1 },
});
