import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft, HardHat, CheckCircle, XCircle, MinusCircle,
  Save, Download, Calendar,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import SignaturePad from '../../src/components/SignaturePad';
import LogbookLockBar from '../../src/components/LogbookLockBar';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI } from '../../src/utils/api';
import { draftKey, readDraft, writeDraft, setDraftBackendId, markPending, clearPending, markFinalized } from '../../src/utils/logbookDrafts';
import { freezeIfImmediate } from '../../src/utils/logbookTiming';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
import { semantic, withAlpha } from '../../src/styles/semanticColors';

// All maintenance questions exactly as per NYC DOB form
const GENERAL_INFO_FIELDS = [
  { key: 'scaffold_erector', label: 'Name of Scaffold Erector' },
  { key: 'renters_name', label: 'Renters Name' },
  { key: 'permit_number', label: 'Permit #' },
  { key: 'installation_date', label: 'Installation Date' },
  { key: 'expiration_date', label: 'Expiration' },
  { key: 'phone', label: 'Phone #' },
  { key: 'scaffold_height', label: 'Scaffold Height' },
  { key: 'num_platforms', label: 'Number of Platforms Decked' },
];

const SHED_TYPES = ['Light', 'Med.', 'Heavy', 'Duty'];

const MAINTENANCE_QUESTIONS = [
  { key: 'signs_on_parapets', label: 'Are the signs on the parapets?' },
  { key: 'base_plates_mudsills', label: 'Are the base plates and mudsills secured?' },
  { key: 'scaffold_pins_bolts', label: 'Are the scaffold pins and bolts installed?' },
  { key: 'legs_poles_plumb', label: 'Are the legs and poles plumb, braced and not displaced?' },
  { key: 'tie_ins_spaced', label: 'Are tie-ins correctly spaced, properly secured and the correct amount?' },
  { key: 'cross_braces', label: 'Are cross braces fully attached, not bent, and not missing?' },
  { key: 'pipe_clamps_tight', label: 'Are pipe clamps tight?' },
  { key: 'window_jacks_tight', label: 'Are window jacks tight?' },
  { key: 'planks_secured', label: 'Are all the planks secured?' },
  { key: 'decking_planks_condition', label: 'Are decking and planks in good condition?' },
  { key: 'deck_fully_planked', label: 'Is deck fully planked?' },
  { key: 'gaps_open_spaces', label: 'Are there gaps or open spaces on decking?' },
  { key: 'guardrails_toe_boards', label: 'Are the guardrails and toe boards secured at all places where required?' },
  { key: 'netting_extension', label: 'Is the netting extension of full length and height?' },
  { key: 'netting_secured', label: 'Is the netting secured?' },
  { key: 'parapet_height', label: 'Is the parapet the proper height and secured?' },
  { key: 'lights_working', label: 'Are the lights working?' },
  { key: 'deck_clean', label: 'Is the deck clean and free of debris?' },
  { key: 'drawings_on_site', label: 'Drawings on site for inspection?' },
];

const ANSWER_OPTIONS = ['YES', 'NO', 'N/A'];

export default function ScaffoldMaintenanceLog() {
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

  const [generalInfo, setGeneralInfo] = useState({
    scaffold_erector: '', renters_name: '', permit_number: '',
    installation_date: '', expiration_date: '', phone: '',
    scaffold_height: '', num_platforms: '', shed_type: 'Heavy',
    // `drawings_on_site` is NOT seeded here any more, and is not a general_info
    // key at all. It was initialised to 'YES' with no control anywhere on the
    // screen that could change it — the app asserting, on every scaffold log,
    // that drawings were on site for inspection when nobody had said so.
    //
    // The same name is ALSO one of the 19 inspection questions, which is where
    // it belongs and where the CP actually answers it. Both PDF renderers
    // already read only that one and say so
    // (backend/server.py:13369 and :18801, "a dead duplicate of the answers
    // question of the same key"), so nothing printed changes — an unanswered
    // question renders "Not recorded", never a silent YES.
  });

  const [answers, setAnswers] = useState({});

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  // Phase A — autosave every field change to the LOCAL draft (AsyncStorage).
  // Debounced so typing doesn't thrash storage; makes no server call. This is
  // what lets the CP fill with zero network and reopen to the same draft.
  // `status` is intentionally omitted so an autosave never downgrades a
  // submitted log back to draft.
  useEffect(() => {
    if (loading) return undefined;
    const t = setTimeout(() => {
      writeDraft(
        draftKey({ projectId, logType: 'scaffold_maintenance', date }),
        {
          data: { general_info: generalInfo, answers },
          cp_signature: cpSignature,
          cp_name: cpName,
        },
      ).catch(() => {});
    }, 800);
    return () => clearTimeout(t);
  }, [loading, projectId, date, generalInfo, answers, cpSignature, cpName]);

  const fetchData = async () => {
    setLoading(true);
    try {
      // Phase A — local-first: read the on-device draft first. A local draft
      // wins over both the project-memory prefill and the server copy, so an
      // offline CP reopens to exactly what they filled.
      const key = draftKey({ projectId, logType: 'scaffold_maintenance', date });
      const draft = await readDraft(key);
      if (draft) {
        // Tier 1 (1)b: a draft marked finalized locks the form read-only.
        if (draft.finalized) {
          setLocked(true);
          markFinalized(key);  // lock the offline draft too (mirrors the backend 423)
        }
        setExistingLogId(draft.backend_id);
        const d = draft.data || {};
        if (d.general_info) setGeneralInfo(d.general_info);
        if (d.answers) setAnswers(d.answers);
        if (draft.cp_signature) setCpSignature(draft.cp_signature);
        if (draft.cp_name) setCpName(draft.cp_name);
        setLoading(false);
        return;
      }

      const [scaffoldInfo, existingLogs] = await Promise.all([
        logbooksAPI.getScaffoldInfo(projectId).catch(() => ({})),
        logbooksAPI.getByProject(projectId, 'scaffold_maintenance', date).catch(() => []),
      ]);

      // Pre-fill scaffold info from project memory
      if (scaffoldInfo) {
        setGeneralInfo(prev => ({
          ...prev,
          scaffold_erector: scaffoldInfo.scaffold_erector || '',
          renters_name: scaffoldInfo.renters_name || '',
          permit_number: scaffoldInfo.permit_number || '',
          installation_date: scaffoldInfo.installation_date || '',
          expiration_date: scaffoldInfo.expiration_date || '',
          phone: scaffoldInfo.phone || '',
          scaffold_height: scaffoldInfo.scaffold_height || '',
          num_platforms: scaffoldInfo.num_platforms || '',
          shed_type: scaffoldInfo.shed_type || 'Heavy',
        }));
      }

      // CP profile is auto-loaded by useCpProfile hook — no manual fetch needed

      // Load existing log for this date. Prefer the EDITABLE (non-locked) doc —
      // an amendment child — over a locked original that shares (project, type, date).
      const arr = Array.isArray(existingLogs) ? existingLogs : [];
      const existing = arr.find(l => !l.is_locked) || arr[0] || null;
      if (existing) {
        // Tier 1 (1)b: a server doc's is_locked locks the form read-only.
        if (existing.is_locked) {
          setLocked(true);
          markFinalized(key);  // lock the offline draft too (mirrors the backend 423)
        }
        setExistingLogId(existing.id || existing._id);
        const d = existing.data || {};
        if (d.general_info) setGeneralInfo(d.general_info);
        if (d.answers) setAnswers(d.answers);
        if (existing.cp_signature) setCpSignature(existing.cp_signature);
        if (existing.cp_name) setCpName(existing.cp_name);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const setAnswer = (key, value) => {
    setAnswers(prev => ({ ...prev, [key]: value }));
  };

  const handleSave = async (submitStatus = 'draft') => {
    setSaving(true);
    const key = draftKey({ projectId, logType: 'scaffold_maintenance', date });
    const data = { general_info: generalInfo, answers };
    try {
      // Save scaffold info to project memory
      // Only the keys this screen actually holds. update_scaffold_info writes
      // every key it is given, so an ABSENT drawings_on_site would be sent as
      // undefined and stored as null — replacing whatever the project already
      // had with nothing. Dropping it from the payload leaves it untouched.
      await logbooksAPI.saveScaffoldInfo(
        projectId,
        Object.fromEntries(
          Object.entries(generalInfo).filter(([, v]) => v !== undefined),
        ),
      ).catch(() => {});

      // Phase A — write the LOCAL draft first. Source of truth, needs no network,
      // so an offline CP completes the log without the "could not save" failure.
      await writeDraft(key, { data, cp_signature: cpSignature, cp_name: cpName, status: submitStatus });

      const payload = {
        project_id: projectId,
        log_type: 'scaffold_maintenance',
        date: date,
        data,
        cp_signature: cpSignature,
        cp_name: cpName,
        status: submitStatus,
      };

      // FIX (PR F): `created` MUST be declared OUTSIDE the else. Referencing it
      // at `docId = existingLogId || created?.id` below (a different block)
      // threw ReferenceError on the FIRST submit of a new log — the record was
      // written but the client errored, so recordSignatureEvent never fired and
      // the CP was trained to press Submit twice. Hoisting fixes both.
      let created = null;
      let pushOk = true;
      // Best-effort server push. Offline this throws and is swallowed — the key
      // is recorded in the pending-push list for the Phase B reconnect flush.
      try {
        if (existingLogId) {
          await logbooksAPI.update(existingLogId, {
            data: payload.data,
            cp_signature: cpSignature,
            cp_name: cpName,
            status: submitStatus,
          });
          await setDraftBackendId(key, existingLogId);
        } else {
          created = await logbooksAPI.create(payload);
          setExistingLogId(created.id || created._id);
          await setDraftBackendId(key, created.id || created._id);
        }
        await clearPending(key);
      } catch (pushErr) {
        pushOk = false;
        await markPending(key);
        console.warn('Logbook server push deferred (will sync on reconnect):', pushErr?.message);
      }

      // FREEZE MODEL — scaffold_maintenance is an IMMEDIATE log: THE SIGNATURE IS
      // THE FREEZE. Submitting finalizes the inspection in one action; there is no
      // separate Finalize step and it is never reopened (a post-alteration
      // re-inspection is a NEW log; corrections go through the amendment-as-child
      // path). This runs AFTER the local writeDraft (so the frozen draft holds the
      // signed content) and AFTER the server push attempt — on SUCCESS OR FAILURE,
      // so a sidewalk-shed inspection signed with no signal still freezes. It sits
      // ahead of the autoSave below on purpose: that call is unguarded, and a CP
      // profile hiccup must not be what leaves a signed inspection unfrozen.
      if (submitStatus === 'submitted') {
        await freezeIfImmediate(key, 'scaffold_maintenance');
        setLocked(true);
      }

      await autoSave(cpName, cpSignature).catch(() => {});  // guarded: a CP-PROFILE save failure must never report "Could not save log" on a log that was already saved (and, for immediate types, already FROZEN)

      if (submitStatus === 'submitted' && cpSignature) {
        const docId = existingLogId || created?.id || created?._id;
        if (docId) {
          const { recordSignatureEvent } = require('../../src/utils/signatureAudit');
          recordSignatureEvent({
            documentType: 'logbook', documentId: docId, eventType: 'cp_sign',
            signerName: cpName, signerRole: user?.role || 'cp',
            signatureData: cpSignature,
            contentSnapshot: { log_type: 'scaffold_maintenance', date, project_id: projectId, data: payload.data, status: submitStatus },
            user,
          }).catch(e => console.warn('Signature audit failed (non-blocking):', e?.message));
        }
      }

      toast.success(
        submitStatus === 'submitted' ? 'Signed & Locked' : 'Saved',
        submitStatus === 'submitted'
          ? (pushOk
            ? 'Scaffold inspection signed and locked. Corrections require an amendment.'
            : 'Scaffold inspection signed and locked on this device. It will sync when you reconnect.')
          : 'Scaffold log saved'
      );
      if (submitStatus === 'submitted') router.back();
    } catch (e) {
      console.error(e);
      toast.error('Error', 'Could not save log');
    } finally {
      setSaving(false);
    }
  };

  const AnswerToggle = ({ questionKey }) => {
    const current = answers[questionKey];
    return (
      <View style={styles.answerRow}>
        {ANSWER_OPTIONS.map((opt) => (
          <Pressable
            key={opt}
            onPress={() => setAnswer(questionKey, opt)}
            style={[styles.answerBtn, current === opt && getAnswerActive(opt)]}
          >
            {opt === 'YES' && <CheckCircle size={14} strokeWidth={2} color={current === 'YES' ? semantic.verified : colors.text.muted} />}
            {opt === 'NO' && <XCircle size={14} strokeWidth={2} color={current === 'NO' ? semantic.attention : colors.text.muted} />}
            {opt === 'N/A' && <MinusCircle size={14} strokeWidth={2} color={current === 'N/A' ? '#94a3b8' : colors.text.muted} />}
            <Text style={[styles.answerBtnText, current === opt && getAnswerTextStyle(opt)]}>{opt}</Text>
          </Pressable>
        ))}
      </View>
    );
  };

  const getAnswerActive = (opt) => {
    if (opt === 'YES') return styles.answerBtnYes;
    if (opt === 'NO') return styles.answerBtnNo;
    return styles.answerBtnNA;
  };
  const getAnswerTextStyle = (opt) => {
    if (opt === 'YES') return { color: semantic.verified };
    if (opt === 'NO') return { color: semantic.attention };
    return { color: '#94a3b8' };
  };

  const answeredCount = Object.keys(answers).length;
  const totalQuestions = MAINTENANCE_QUESTIONS.length;

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
              <Text style={styles.headerTitle}>Scaffold Maintenance Log</Text>
              <Text style={styles.headerSub}>NYC DOB — Daily Inspection</Text>
            </View>
          </View>
          <View style={styles.progressBadge}>
            <Text style={styles.progressText}>{answeredCount}/{totalQuestions}</Text>
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

          {/* General Information */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionHeader}>General Information</Text>
            {GENERAL_INFO_FIELDS.map((field) => (
              <View key={field.key} style={styles.fieldRow}>
                <Text style={styles.fieldLabel}>{field.label}</Text>
                <TextInput
                  style={styles.fieldInput}
                  value={generalInfo[field.key] || ''}
                  onChangeText={(v) => setGeneralInfo(prev => ({ ...prev, [field.key]: v }))}
                  placeholder="—"
                  placeholderTextColor={colors.text.subtle}
                />
              </View>
            ))}

            {/* Shed Type */}
            <View style={styles.fieldRow}>
              <Text style={styles.fieldLabel}>Shed Type</Text>
              <View style={styles.shedTypeRow}>
                {SHED_TYPES.map((type) => (
                  <Pressable
                    key={type}
                    onPress={() => setGeneralInfo(prev => ({ ...prev, shed_type: type }))}
                    style={[styles.shedTypeBtn, generalInfo.shed_type === type && styles.shedTypeBtnActive]}
                  >
                    <Text style={[styles.shedTypeBtnText, generalInfo.shed_type === type && styles.shedTypeBtnTextActive]}>
                      {type}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </GlassCard>

          {/* Specific & Maintenance Information */}
          <GlassCard style={styles.section}>
            <Text style={styles.sectionHeader}>Specific & Maintenance Information</Text>
            <Text style={styles.sectionSubtitle}>Answer YES, NO, or N/A for each item</Text>
            {MAINTENANCE_QUESTIONS.map((q, i) => (
              <View key={q.key} style={[styles.questionRow, i < MAINTENANCE_QUESTIONS.length - 1 && styles.questionBorder]}>
                <Text style={styles.questionText}>{q.label}</Text>
                <AnswerToggle questionKey={q.key} />
              </View>
            ))}
          </GlassCard>

          {/* CP Signature */}
          <GlassCard style={styles.section}>
            <View style={styles.sectionHeaderRow}>
              <HardHat size={18} strokeWidth={1.5} color="#3b82f6" />
              <Text style={styles.sectionHeader}>Competent Person Sign-Off</Text>
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
              disabled={!cpSignature || answeredCount === 0}
              style={styles.submitBtn}
            />
          </View>
          )}

          {/* logType drives the freeze model: for an IMMEDIATE log the LockBar
              hides Finalize (the signature already froze it) and offers only the
              Amend path. No canFinalize prop — it would contradict that. */}
          <LogbookLockBar
            locked={locked}
            logId={existingLogId}
            logType="scaffold_maintenance"
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
  progressBadge: {
    backgroundColor: 'rgba(59,130,246,0.15)',
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderWidth: 1,
    borderColor: 'rgba(59,130,246,0.3)',
  },
  progressText: { fontSize: 13, color: '#60a5fa', fontWeight: '600' },
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
    flex: 1,
    fontSize: 14,
    color: colors.text.primary,
    textAlign: 'right',
    padding: spacing.xs,
    backgroundColor: withAlpha('#ffffff', 0.04),
    borderRadius: borderRadius.sm,
  },
  shedTypeRow: { flexDirection: 'row', gap: spacing.xs },
  shedTypeBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.1),
  },
  shedTypeBtnActive: { backgroundColor: 'rgba(59,130,246,0.2)', borderColor: '#3b82f6' },
  shedTypeBtnText: { fontSize: 12, color: colors.text.muted },
  shedTypeBtnTextActive: { color: '#60a5fa', fontWeight: '600' },
  questionRow: {
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  questionBorder: {
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.05),
  },
  questionText: { fontSize: 13, color: colors.text.secondary, lineHeight: 18 },
  answerRow: { flexDirection: 'row', gap: spacing.xs },
  answerBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: withAlpha('#ffffff', 0.1),
    backgroundColor: withAlpha('#ffffff', 0.04),
  },
  answerBtnYes: { backgroundColor: semantic.verifiedBg, borderColor: semantic.verifiedBorder },
  answerBtnNo: { backgroundColor: semantic.criticalBg, borderColor: semantic.criticalBorder },
  answerBtnNA: { backgroundColor: withAlpha('#94a3b8', 0.1), borderColor: withAlpha('#94a3b8', 0.3) },
  answerBtnText: { fontSize: 12, color: colors.text.muted, fontWeight: '500' },
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
