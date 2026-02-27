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
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { logbooksAPI } from '../../src/utils/api';
import { useCpProfile } from '../../src/hooks/useCpProfile';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

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
  const router = useRouter();
  const { projectId, date } = useLocalSearchParams();
  const { user } = useAuth();
  const toast = useToast();
  const { cpName, setCpName, cpSignature, setCpSignature, autoSave } = useCpProfile();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [existingLogId, setExistingLogId] = useState(null);

  const [generalInfo, setGeneralInfo] = useState({
    scaffold_erector: '', renters_name: '', permit_number: '',
    installation_date: '', expiration_date: '', phone: '',
    scaffold_height: '', num_platforms: '', shed_type: 'Heavy',
    drawings_on_site: 'YES',
  });

  const [answers, setAnswers] = useState({});

  useEffect(() => {
    fetchData();
  }, [projectId, date]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [scaffoldInfo, profile, existingLogs] = await Promise.all([
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

      // Pre-fill CP signature
      if (profile) {
        setCpProfile(profile);
        setCpName(profile.cp_name || '');
        if (profile.cp_signature) {
          setCpSignature(profile.cp_signature);
        }
      }

      // Load existing log for this date
      const existing = Array.isArray(existingLogs) && existingLogs.length > 0 ? existingLogs[0] : null;
      if (existing) {
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
    try {
      // Save scaffold info to project memory
      await logbooksAPI.saveScaffoldInfo(projectId, generalInfo).catch(() => {});

      const payload = {
        project_id: projectId,
        log_type: 'scaffold_maintenance',
        date: date,
        data: { general_info: generalInfo, answers },
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
      toast.success(submitStatus === 'submitted' ? 'Submitted' : 'Saved', 'Scaffold log saved');
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
            {opt === 'YES' && <CheckCircle size={14} strokeWidth={2} color={current === 'YES' ? '#4ade80' : colors.text.muted} />}
            {opt === 'NO' && <XCircle size={14} strokeWidth={2} color={current === 'NO' ? '#ef4444' : colors.text.muted} />}
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
    if (opt === 'YES') return { color: '#4ade80' };
    if (opt === 'NO') return { color: '#ef4444' };
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
              disabled={!cpSignature || answeredCount === 0}
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
    borderBottomColor: 'rgba(255,255,255,0.05)',
    gap: spacing.md,
  },
  fieldLabel: { flex: 1, fontSize: 13, color: colors.text.secondary },
  fieldInput: {
    flex: 1,
    fontSize: 14,
    color: colors.text.primary,
    textAlign: 'right',
    padding: spacing.xs,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: borderRadius.sm,
  },
  shedTypeRow: { flexDirection: 'row', gap: spacing.xs },
  shedTypeBtn: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
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
    borderBottomColor: 'rgba(255,255,255,0.05)',
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
    borderColor: 'rgba(255,255,255,0.1)',
    backgroundColor: 'rgba(255,255,255,0.04)',
  },
  answerBtnYes: { backgroundColor: 'rgba(74,222,128,0.1)', borderColor: 'rgba(74,222,128,0.3)' },
  answerBtnNo: { backgroundColor: 'rgba(239,68,68,0.1)', borderColor: 'rgba(239,68,68,0.3)' },
  answerBtnNA: { backgroundColor: 'rgba(148,163,184,0.1)', borderColor: 'rgba(148,163,184,0.3)' },
  answerBtnText: { fontSize: 12, color: colors.text.muted, fontWeight: '500' },
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
