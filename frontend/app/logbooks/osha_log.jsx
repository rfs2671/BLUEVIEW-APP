import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, ClipboardList, CheckCircle, Save, Plus, Calendar, CreditCard,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

const CERT_TYPES = ['OSHA 10', 'OSHA 30', 'OSHA 40hr', 'OSHA 62hr', 'SST', 'Flagman', 'Forklift', 'Scaffold', 'Other'];

const EMPTY_ENTRY = () => ({
  worker_id: null,
  worker_name: '',
  company: '',
  certification_type: '',
  card_number: '',
  expiration: '',
  signed: false,
  date: new Date().toISOString().split('T')[0],
});

export default function OshaLogBook() {
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);

  const [entries, setEntries] = useState([]);
  const [showCertPicker, setShowCertPicker] = useState(null); // index of row being edited

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [profile, checkins, existingLogs] = await Promise.all([
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        // OSHA log is ongoing — get all entries for project (no date filter)
        logbooksAPI.getByProject(projectId, 'osha_log').catch(() => []),
      ]);
      const existing = Array.isArray(existingLogs) && existingLogs.length > 0 ? existingLogs[0] : null;
      if (existing) {
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.entries && d.entries.length > 0) {
          setEntries(d.entries);
          if (existing.cp_signature) setCpSignature(existing.cp_signature);
          if (existing.cp_name) setCpName(existing.cp_name);
          return;
        }
      }

      // Build from checkins + their cert data
      const checkinList = Array.isArray(checkins) ? checkins : [];
      const autoEntries = [];
      for (const c of checkinList) {
        // One row per certification per worker
        const certs = c.certifications || [];
        if (certs.length > 0) {
          for (const cert of certs) {
            autoEntries.push({
              worker_id: c.worker_id,
              worker_name: c.worker_name || '',
              company: c.company || '',
              certification_type: cert.name || '',
              card_number: cert.card_number || c.osha_number || '',
              expiration: cert.expiry || '',
              signed: false,
              date: date,
            });
          }
        } else {
          // Add worker with osha_number if available
          autoEntries.push({
            worker_id: c.worker_id,
            worker_name: c.worker_name || '',
            company: c.company || '',
            certification_type: c.osha_number ? 'OSHA 40hr' : '',
            card_number: c.osha_number || '',
            expiration: '',
            signed: false,
            date: date,
          });
        }
      }
      setEntries(autoEntries.length > 0 ? autoEntries : [EMPTY_ENTRY()]);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const updateEntry = (index, field, value) => {
    setEntries(prev => prev.map((e, i) => i === index ? { ...e, [field]: value } : e));
  };

  const addEntry = () => {
    setEntries(prev => [...prev, EMPTY_ENTRY()]);
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    try {
      const payload = {
        project_id: projectId,
        log_type: 'osha_log',
        date, // Use today's date for upsert key
        data: { entries },
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
      toast.success(submitStatus === 'submitted' ? 'Submitted' : 'Saved', 'OSHA Log saved');
      if (submitStatus === 'submitted') router.back();
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
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <View>
              <Text style={styles.headerTitle}>OSHA Log Book</Text>
              <Text style={styles.headerSub}>Worker Certifications Register</Text>
            </View>
          </View>
          <View style={styles.countBadge}>
            <CreditCard size={14} strokeWidth={1.5} color="#06b6d4" />
            <Text style={styles.countText}>{entries.length}</Text>
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

          {/* Entries */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionTitle}>Certification Entries</Text>
            <Text style={styles.sectionSubtitle}>
              Auto-populated from checked-in workers. Edit or add entries as needed.
            </Text>

            {/* Table Header */}
            <View style={styles.tableHeader}>
              <Text style={[styles.colHeader, { flex: 2 }]}>Worker Name</Text>
              <Text style={[styles.colHeader, { flex: 2 }]}>Company</Text>
              <Text style={[styles.colHeader, { flex: 2 }]}>Cert. Type</Text>
              <Text style={[styles.colHeader, { flex: 2 }]}>Card / # / Date</Text>
            </View>

            {entries.map((entry, index) => (
              <View key={index} style={styles.entryBlock}>
                <View style={styles.entryRow}>
                  <TextInput
                    style={[styles.entryInput, { flex: 2 }]}
                    value={entry.worker_name}
                    onChangeText={(v) => updateEntry(index, 'worker_name', v)}
                    placeholder="Name"
                    placeholderTextColor={colors.text.subtle}
                  />
                  <TextInput
                    style={[styles.entryInput, { flex: 2 }]}
                    value={entry.company}
                    onChangeText={(v) => updateEntry(index, 'company', v)}
                    placeholder="Company"
                    placeholderTextColor={colors.text.subtle}
                  />
                </View>
                <View style={styles.entryRow}>
                  {/* Cert type selector */}
                  <Pressable
                    onPress={() => setShowCertPicker(showCertPicker === index ? null : index)}
                    style={[styles.entryInput, { flex: 2, justifyContent: 'center' }]}
                  >
                    <Text style={entry.certification_type ? styles.entryInputText : styles.entryPlaceholder}>
                      {entry.certification_type || 'Select cert...'}
                    </Text>
                  </Pressable>
                  <TextInput
                    style={[styles.entryInput, { flex: 1 }]}
                    value={entry.card_number}
                    onChangeText={(v) => updateEntry(index, 'card_number', v)}
                    placeholder="Card #"
                    placeholderTextColor={colors.text.subtle}
                  />
                  <TextInput
                    style={[styles.entryInput, { flex: 1 }]}
                    value={entry.expiration}
                    onChangeText={(v) => updateEntry(index, 'expiration', v)}
                    placeholder="Exp."
                    placeholderTextColor={colors.text.subtle}
                  />
                </View>

                {/* Cert picker dropdown */}
                {showCertPicker === index && (
                  <View style={styles.certPicker}>
                    {CERT_TYPES.map((ct) => (
                      <Pressable
                        key={ct}
                        onPress={() => {
                          updateEntry(index, 'certification_type', ct);
                          setShowCertPicker(null);
                        }}
                        style={[styles.certOption, entry.certification_type === ct && styles.certOptionActive]}
                      >
                        <Text style={[styles.certOptionText, entry.certification_type === ct && styles.certOptionTextActive]}>
                          {ct}
                        </Text>
                      </Pressable>
                    ))}
                  </View>
                )}

                {/* Signed toggle */}
                <Pressable
                  onPress={() => updateEntry(index, 'signed', !entry.signed)}
                  style={styles.signedRow}
                >
                  <View style={[styles.signedBox, entry.signed && styles.signedBoxActive]}>
                    {entry.signed && <CheckCircle size={14} strokeWidth={2} color="#4ade80" />}
                  </View>
                  <Text style={styles.signedLabel}>
                    {entry.signed ? 'Signature on file' : 'Mark signature on file'}
                  </Text>
                </Pressable>

                {index < entries.length - 1 && <View style={styles.entryDivider} />}
              </View>
            ))}

            <GlassButton
              title="+ Add Entry"
              icon={<Plus size={14} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={addEntry}
              style={styles.addBtn}
            />
          </GlassCard>

          {/* CP Signature */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <ClipboardList size={16} strokeWidth={1.5} color="#06b6d4" />
              <Text style={styles.sectionTitle}>CP Signature</Text>
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
              disabled={!cpSignature || entries.length === 0}
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
    backgroundColor: 'rgba(6,182,212,0.15)',
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.md,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: 'rgba(6,182,212,0.3)',
  },
  countText: { fontSize: 14, fontWeight: '600', color: '#22d3ee' },
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
  tableHeader: {
    flexDirection: 'row',
    paddingBottom: spacing.sm,
    marginBottom: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.08)',
  },
  colHeader: {
    fontSize: 10,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  entryBlock: { marginBottom: spacing.sm },
  entryRow: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.xs },
  entryInput: {
    fontSize: 13,
    color: colors.text.primary,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.08)',
  },
  entryInputText: { fontSize: 13, color: colors.text.primary },
  entryPlaceholder: { fontSize: 13, color: colors.text.subtle },
  certPicker: {
    backgroundColor: 'rgba(0,0,0,0.6)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    marginBottom: spacing.xs,
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
    padding: spacing.sm,
  },
  certOption: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  certOptionActive: { backgroundColor: 'rgba(6,182,212,0.2)', borderColor: '#06b6d4' },
  certOptionText: { fontSize: 12, color: colors.text.muted },
  certOptionTextActive: { color: '#22d3ee', fontWeight: '600' },
  signedRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  signedBox: {
    width: 22,
    height: 22,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.04)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  signedBoxActive: { backgroundColor: 'rgba(74,222,128,0.1)', borderColor: '#4ade80' },
  signedLabel: { fontSize: 12, color: colors.text.muted },
  entryDivider: {
    height: 1,
    backgroundColor: 'rgba(255,255,255,0.05)',
    marginTop: spacing.sm,
  },
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
  submitBtn: { flex: 2, backgroundColor: 'rgba(6,182,212,0.15)', borderColor: 'rgba(6,182,212,0.3)' },
});
