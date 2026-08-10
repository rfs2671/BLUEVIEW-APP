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
import LogbookLockBar from '../../src/components/LogbookLockBar';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { recordSignatureEvent } from '../../src/utils/signatureAudit';
import { draftKey, readDraft, writeDraft, setDraftBackendId, markPending, clearPending, markFinalized } from '../../src/utils/logbookDrafts';
import { freezeIfImmediate } from '../../src/utils/logbookTiming';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { easternToday } from '../../src/utils/dates';

const CERT_TYPES = ['OSHA 10', 'OSHA 30', 'OSHA 40hr', 'OSHA 62hr', 'SST', 'Flagman', 'Forklift', 'Scaffold', 'Other'];

const EMPTY_ENTRY = () => ({
  worker_id: null,
  worker_name: '',
  company: '',
  certification_type: '',
  card_number: '',
  expiration: '',
  signed: false,
  // TIER 1 — this date is FILED onto the OSHA/SST row, not used for a lookup.
  // toISOString() is UTC, so an entry added after 20:00 EDT (19:00 EST) was
  // stamped with TOMORROW's date. That persists and an inspector reads it.
  date: easternToday(),
});

export default function OshaLogBook() {
  // Theme read at RENDER time. A module-scope StyleSheet snapshots colors.*
  // at import (the DARK palette), so on the light theme this screen rendered
  // near-white text on a pale background. Same tokens, live values.
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
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

  const [entries, setEntries] = useState([]);
  const [showCertPicker, setShowCertPicker] = useState(null); // index of row being edited

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  // Task 5 (offline): debounced autosave to the local draft on any change.
  // `status` deliberately omitted so autosave never downgrades a submitted log.
  useEffect(() => {
    if (loading) return undefined;
    const key = draftKey({ projectId, logType: 'osha_log', date });
    const t = setTimeout(() => {
      writeDraft(key, { data: { entries }, cp_signature: cpSignature, cp_name: cpName });
    }, 800);
    return () => clearTimeout(t);
  }, [loading, projectId, date, entries, cpSignature, cpName]);

  const fetchData = async () => {
    setLoading(true);
    const key = draftKey({ projectId, logType: 'osha_log', date });
    try {
      // Task 5 (offline): a local draft wins — paint it immediately and skip the
      // server read + check-in auto-populate so unsynced edits are never clobbered.
      const draft = await readDraft(key);
      if (draft) {
        // Tier 1 (1)b: a draft marked finalized locks the form read-only.
        if (draft.finalized) {
          setLocked(true);
          markFinalized(key);
        }
        if (draft.backend_id) setExistingLogId(draft.backend_id);
        const dd = draft.data || {};
        if (Array.isArray(dd.entries)) setEntries(dd.entries);
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        setLoading(false);
        return;
      }
      const [checkins, existingLogs] = await Promise.all([
        logbooksAPI.getCheckinsForDate(projectId, date).catch(() => []),
        // Date-scoped (Task H/I): the OSHA log is per-DAY like every other
        // logbook. Fetching with no date returned the most-recent prior-day doc,
        // so on day 2+ the early-return below loaded old entries (skipping today's
        // check-in auto-populate — Task H) AND submit finalized that old-dated doc
        // while the dashboard reads only today's (showing "pending" — Task I).
        // Passing `date` makes `existing` today's doc or null → auto-populate runs
        // on a fresh day, and submit lands on the doc the dashboard queries.
        logbooksAPI.getByProject(projectId, 'osha_log', date).catch(() => []),
      ]);
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
        // Task 9: a worker turned away for missing OSHA (surfaced by the
        // checkins-today endpoint from a CERT_BLOCK alert) — badge it, read-only.
        if (c.blocked) {
          autoEntries.push({
            worker_id: c.worker_id,
            worker_name: c.worker_name || '',
            company: c.company || '',
            certification_type: 'MISSING OSHA',
            card_number: '',
            expiration: '',
            signed: false,
            blocked: true,
            blocks: c.blocks || [],
            date: date,
          });
          continue;
        }
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

      const key = draftKey({ projectId, logType: 'osha_log', date });
      // Task 5 (offline): write the local draft FIRST, then best-effort push so a
      // failed/absent network keeps the CP's entries instead of losing them.
      await writeDraft(key, { data: payload.data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus });

      let created = null;
      let savedId = existingLogId;
      let pushOk = true;
      try {
        if (existingLogId) {
          await logbooksAPI.update(existingLogId, {
            data: payload.data,
            cp_signature: cpSignature,
            cp_name: cpName,
            status: submitStatus,
          });
        } else {
          created = await logbooksAPI.create(payload);
          savedId = created.id || created._id;
          setExistingLogId(savedId);
        }
        if (savedId) setDraftBackendId(key, savedId);
        clearPending(key);
      } catch (pushErr) {
        pushOk = false;
        markPending(key);
        console.warn('OSHA log deferred push (kept local draft):', pushErr?.message);
      }

      // FREEZE ON SIGN — osha_log is an IMMEDIATE log: the SIGNATURE IS THE
      // FREEZE. "Submit & Sign" finalizes the register in one action (there is
      // no separate Finalize step, and it is never reopened). This runs after
      // the local writeDraft above — so the frozen draft holds the SIGNED
      // content — and after the push attempt on BOTH paths, because the register
      // is signed at the gate with no signal: the freeze must not need the
      // server. Corrections from here go through Amend (a linked child).
      if (submitStatus === 'submitted') {
        await freezeIfImmediate(key, 'osha_log');
        setLocked(true);
      }

      await autoSave(cpName, cpSignature).catch(() => {});  // guarded: a CP-PROFILE save failure must never report "Could not save log" on a log that was already saved (and, for immediate types, already FROZEN)
      if (submitStatus === 'submitted' && cpSignature) {
        const docId = existingLogId || created?.id || created?._id;
        if (docId) {
          recordSignatureEvent({
            documentType: 'logbook', documentId: docId, eventType: 'cp_sign',
            signerName: cpName, signerRole: user?.role || 'cp',
            signatureData: cpSignature,
            contentSnapshot: { log_type: 'osha_log', date, project_id: projectId, data: { entries }, status: submitStatus },
            user,
          }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
        }
      }
      toast.success(
        submitStatus === 'submitted' ? 'Signed & Locked' : 'Draft saved',
        submitStatus !== 'submitted'
          ? 'Saved'
          : pushOk
            ? 'Signed — this log is now locked. Corrections require an amendment.'
            : 'Signed — locked on this device and will sync when you are back online.'
      );
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
              onPress={() => router.push('/logbooks')}
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

          {/* Tier 1 (1)b: a finalized log renders read-only. pointerEvents 'none'
              makes EVERY field below non-interactive (no per-field editable flags
              to miss). Scrolling still works; the LockBar stays interactive. */}
          <View pointerEvents={locked ? 'none' : 'auto'}>

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
                {entry.blocked && (
                  <View style={styles.deniedBadge}>
                    <Text style={styles.deniedText}>
                      ⛔ DENIED — MISSING OSHA (turned away at gate, not admitted)
                    </Text>
                  </View>
                )}
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
                    {entry.signed && <CheckCircle size={14} strokeWidth={2} color={semantic.verified} />}
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
          </View>

          {/* Actions — hidden when finalized; the LockBar handles finalize/amend. */}
          {!locked && (
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
          )}

          {/* logType drives the FREEZE MODEL: osha_log is IMMEDIATE, so the bar
              hides Finalize (the signature already froze the log) and offers
              only Amend once locked. canFinalize stays false for that reason. */}
          <LogbookLockBar
            locked={locked}
            logId={existingLogId}
            logType="osha_log"
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
    borderBottomColor: withAlpha('#ffffff', 0.08),
  },
  colHeader: {
    fontSize: 10,
    fontWeight: '600',
    color: colors.text.muted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  entryBlock: { marginBottom: spacing.sm },
  // Task 9: badge for a worker turned away at the gate for missing OSHA.
  deniedBadge: {
    backgroundColor: withAlpha('#ef4444', 0.15),
    borderColor: withAlpha('#ef4444', 0.4),
    borderWidth: 1,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    marginBottom: 4,
  },
  deniedText: { color: '#ef4444', fontSize: 12, fontWeight: '700' },
  entryRow: { flexDirection: 'row', gap: spacing.xs, marginBottom: spacing.xs },
  entryInput: {
    fontSize: 13,
    color: colors.text.primary,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    backgroundColor: withAlpha('#ffffff', 0.05),
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.08),
  },
  entryInputText: { fontSize: 13, color: colors.text.primary },
  entryPlaceholder: { fontSize: 13, color: colors.text.subtle },
  certPicker: {
    backgroundColor: withAlpha('#000000', 0.6),
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.1),
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
    borderColor: withAlpha('#ffffff', 0.1),
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
    borderColor: withAlpha('#ffffff', 0.15),
    backgroundColor: withAlpha('#ffffff', 0.04),
    alignItems: 'center',
    justifyContent: 'center',
  },
  signedBoxActive: { backgroundColor: semantic.verifiedBg, borderColor: semantic.verified },
  signedLabel: { fontSize: 12, color: colors.text.muted },
  entryDivider: {
    height: 1,
    backgroundColor: withAlpha('#ffffff', 0.05),
    marginTop: spacing.sm,
  },
  addBtn: { marginTop: spacing.md },
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
  submitBtn: { flex: 2, backgroundColor: 'rgba(6,182,212,0.15)', borderColor: 'rgba(6,182,212,0.3)' },
  });
}
