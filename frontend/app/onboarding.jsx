/**
 * Phase B3 — customer onboarding flow.
 *
 * Surfaces a 4-step progressive form to a newly-registered GC user
 * (onboarding_step ∈ {1,2,3,4} on the user doc). On every step the
 * user can either submit and advance, or skip. Skipping at step 1
 * sets onboarding_step="skipped" and drops the user on the dashboard
 * empty-state. Submitting step 4 sets onboarding_step="completed"
 * and redirects to the project they just created (or the dashboard
 * if they skipped step 2).
 *
 * Backend endpoints touched:
 *   GET  /api/users/me/onboarding-status     (entry — resume from
 *                                             saved step on reload)
 *   POST /api/onboarding/company             (step 1 submit)
 *   POST /api/onboarding/project             (step 2 submit)
 *   POST /api/onboarding/filing-reps         (step 3 submit)
 *   PATCH /api/users/me/notification-preferences  (step 4 submit;
 *                                             existing B1a/B1b endpoint)
 *   PATCH /api/users/me/onboarding-step      (every advance/skip)
 *
 * Backward-compat: pre-B3 users (no onboarding_step on their doc)
 * get show_onboarding=false from the GET endpoint and the RouteGuard
 * never redirects them here. Existing 622 production users + 3
 * active projects don't see the flow.
 *
 * Design system: AnimatedBackground page wrapper, GlassCard for the
 * step card, GlassInput / GlassButton for form controls,
 * typography.label for section headers, colors.* tokens for every
 * color reference. Mobile-first: forms stack on screens <768; use
 * row layout above. Theme-aware via useTheme().
 */

import React, { useState, useEffect, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Dimensions,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Building2,
  Briefcase,
  Users,
  Bell,
  ArrowRight,
  Plus,
  Trash2,
  Check,
  CheckCircle2,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard } from '../src/components/GlassCard';
import GlassInput from '../src/components/GlassInput';
import GlassButton from '../src/components/GlassButton';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { useTheme } from '../src/context/ThemeContext';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import apiClient, { onboardingAPI } from '../src/utils/api';
import InfoTooltip from '../src/components/InfoTooltip';
import {
  PRESETS,
  PRESET_ORDER,
  buildPresetPrefs,
} from '../src/utils/notificationPresets';

const TOTAL_STEPS = 4;

// Mobile breakpoint matches activity feed (B0.1). <768 stacks form
// fields, ≥768 keeps a comfortable two-column where helpful.
const MOBILE_BREAKPOINT = 768;

// Steps emit a numeric string — mirrors the backend VALID_ONBOARDING_STEPS.
const STEP_KEYS = ['1', '2', '3', '4'];

const STEP_META = {
  1: {
    title: 'Tell us about your company',
    subtitle:
      'We\'ll create your company workspace. You can update these details anytime in Settings.',
    Icon: Building2,
  },
  2: {
    title: 'Add your first project',
    subtitle:
      'We\'ll start monitoring DOB activity for this project right away. Initial scan completes within 15 minutes.',
    Icon: Briefcase,
  },
  3: {
    title: 'Add filing reps (optional)',
    subtitle:
      'Filing reps are licensed individuals who file paperwork on your behalf. Add them so we know who\'s the applicant when permits need renewal. You can do this later in Settings.',
    Icon: Users,
  },
  4: {
    title: 'How should we notify you?',
    subtitle:
      'Choose how you\'d like to be notified about DOB activity on your projects. You can change this anytime in Settings.',
    Icon: Bell,
  },
};

export default function OnboardingScreen() {
  const router = useRouter();
  const toast = useToast();
  const { user, isAuthenticated, isLoading: authLoading, validateSession } = useAuth();
  const { colors, isDark } = useTheme();
  const styles = useMemo(() => buildStyles(colors, isDark), [colors, isDark]);

  // ── State ────────────────────────────────────────────────────────
  const [currentStep, setCurrentStep] = useState('1');
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [createdProjectId, setCreatedProjectId] = useState(null);

  // Per-step form data.
  const [companyForm, setCompanyForm] = useState({
    name: '',
    license_number: '',
    office_address: '',
  });
  const [projectForm, setProjectForm] = useState({
    name: '',
    address: '',
    expected_start_date: '',
    expected_completion_date: '',
  });
  const [filingReps, setFilingReps] = useState([
    { name: '', license_number: '', email: '', phone: '' },
  ]);
  const [selectedPreset, setSelectedPreset] = useState('critical_only');

  const screenWidth = Dimensions.get('window').width;
  const isMobile = screenWidth < MOBILE_BREAKPOINT;

  // ── Auth + status bootstrap ──────────────────────────────────────
  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      router.replace('/login');
      return;
    }
    // Resume from the saved step on reload.
    onboardingAPI
      .getStatus()
      .then((status) => {
        if (!status.show_onboarding) {
          // Already completed/skipped (or pre-B3 user) — bounce home.
          router.replace('/');
          return;
        }
        const step = String(status.step || '1');
        if (STEP_KEYS.includes(step)) setCurrentStep(step);
        setStatusLoaded(true);
      })
      .catch(() => {
        // Soft-fail: assume step 1 if the read errors. Better than
        // hanging the screen on a transient network blip.
        setStatusLoaded(true);
      });
  }, [authLoading, isAuthenticated]);

  if (authLoading || !statusLoaded) {
    return (
      <AnimatedBackground>
        <View style={styles.loading}>
          <ActivityIndicator size="large" color={colors.text.primary} />
        </View>
      </AnimatedBackground>
    );
  }

  // ── Helpers ──────────────────────────────────────────────────────
  const advanceStep = async (next) => {
    try {
      await onboardingAPI.patchStep(next);
    } catch (e) {
      // Soft-fail: still let the user advance the local UI, but
      // surface a toast.
      toast.error('Sync issue', 'We saved your progress locally. Continue.');
    }
  };

  const finalizeAndExit = async () => {
    try {
      await onboardingAPI.patchStep('completed');
    } catch (_e) {
      // Even if the PATCH fails, fall through and route the user out
      // — the next login will resume them at the saved step.
    }
    // Refresh /auth/me so AuthContext picks up the new
    // company_id / company_name / onboarding_completed_at.
    try {
      await validateSession();
    } catch (_e) { /* noop */ }

    if (createdProjectId) {
      router.replace(`/project/${createdProjectId}`);
    } else {
      router.replace('/');
    }
  };

  const skipFromCurrentStep = async () => {
    if (currentStep === '1') {
      // Skipping the entire flow at step 1 marks the user as skipped.
      try {
        await onboardingAPI.patchStep('skipped');
      } catch (_e) { /* noop */ }
      try { await validateSession(); } catch (_e) { /* noop */ }
      router.replace('/');
      return;
    }
    // Skipping mid-flow advances to the next step.
    const next = String(parseInt(currentStep, 10) + 1);
    if (parseInt(currentStep, 10) >= 4) {
      // No "skip" on step 4 — the only step-4 dismissal is "keep
      // Critical only" (which is identical to no-op on the prefs
      // doc since the synthesized defaults already match).
      await finalizeAndExit();
      return;
    }
    setCurrentStep(next);
    await advanceStep(next);
  };

  // ── Step submit handlers ─────────────────────────────────────────

  const submitStep1 = async () => {
    const name = (companyForm.name || '').trim();
    if (!name) {
      toast.error('Required', 'Please enter your company name.');
      return;
    }
    setSubmitting(true);
    try {
      await apiClient.post('/api/onboarding/company', {
        name,
        license_number: (companyForm.license_number || '').trim() || null,
        office_address: (companyForm.office_address || '').trim() || null,
      });
      try { await validateSession(); } catch (_e) { /* noop */ }
      setCurrentStep('2');
      await advanceStep('2');
    } catch (err) {
      const msg = err.response?.data?.detail || 'Could not save your company.';
      toast.error('Error', msg);
    } finally {
      setSubmitting(false);
    }
  };

  const submitStep2 = async () => {
    const name = (projectForm.name || '').trim();
    if (!name) {
      toast.error('Required', 'Please enter the project name.');
      return;
    }
    setSubmitting(true);
    try {
      const resp = await apiClient.post('/api/onboarding/project', {
        name,
        address: (projectForm.address || '').trim() || null,
        expected_start_date: projectForm.expected_start_date || null,
        expected_completion_date: projectForm.expected_completion_date || null,
      });
      const pid = resp.data?.id || resp.data?.project_id;
      if (pid) setCreatedProjectId(pid);
      setCurrentStep('3');
      await advanceStep('3');
    } catch (err) {
      const msg = err.response?.data?.detail || 'Could not save your project.';
      toast.error('Error', msg);
    } finally {
      setSubmitting(false);
    }
  };

  const submitStep3 = async () => {
    // Drop empty rows on the wire.
    const cleaned = (filingReps || [])
      .map((r) => ({
        name: (r.name || '').trim(),
        license_number: (r.license_number || '').trim() || null,
        email: (r.email || '').trim() || null,
        phone: (r.phone || '').trim() || null,
      }))
      .filter((r) => !!r.name);

    setSubmitting(true);
    try {
      if (cleaned.length > 0) {
        await apiClient.post('/api/onboarding/filing-reps', {
          filing_reps: cleaned,
        });
      }
      setCurrentStep('4');
      await advanceStep('4');
    } catch (err) {
      const msg = err.response?.data?.detail || 'Could not save filing reps.';
      toast.error('Error', msg);
    } finally {
      setSubmitting(false);
    }
  };

  const submitStep4 = async () => {
    setSubmitting(true);
    try {
      // If the user kept the "Critical only" default, we skip the
      // PATCH — the synthesized backend defaults already match this
      // shape, so writing a record would be functionally identical
      // but creates a per-user prefs row prematurely. Other presets
      // get written explicitly.
      if (selectedPreset !== 'critical_only') {
        const built = buildPresetPrefs(selectedPreset, {});
        await apiClient.put('/api/users/me/notification-preferences', {
          signal_kind_overrides: built.signal_kind_overrides,
          channel_routes_default: built.channel_routes_default,
        });
      }
      await finalizeAndExit();
    } catch (err) {
      const msg =
        err.response?.data?.detail ||
        'Could not save notification preferences.';
      toast.error('Error', msg);
    } finally {
      setSubmitting(false);
    }
  };

  // ── Render helpers ───────────────────────────────────────────────

  const renderProgress = () => {
    const stepNum = parseInt(currentStep, 10);
    return (
      <View style={styles.progress}>
        <Text style={styles.progressText}>
          STEP {stepNum} OF {TOTAL_STEPS}
        </Text>
        <View style={styles.progressTrack}>
          {STEP_KEYS.map((k) => {
            const idx = parseInt(k, 10);
            const isActive = idx === stepNum;
            const isDone = idx < stepNum;
            return (
              <View
                key={k}
                style={[
                  styles.progressDot,
                  isActive && styles.progressDotActive,
                  isDone && styles.progressDotDone,
                ]}
              />
            );
          })}
        </View>
      </View>
    );
  };

  const renderStepHeader = () => {
    const meta = STEP_META[currentStep];
    if (!meta) return null;
    const Icon = meta.Icon;
    return (
      <View style={styles.stepHeader}>
        <View style={styles.stepIconCircle}>
          <Icon size={24} strokeWidth={1.5} color={colors.text.primary} />
        </View>
        <Text style={styles.stepTitle}>{meta.title}</Text>
        <Text style={styles.stepSubtitle}>{meta.subtitle}</Text>
      </View>
    );
  };

  const renderStep1 = () => (
    <View style={styles.form}>
      <View style={styles.field}>
        <Text style={styles.fieldLabel}>COMPANY NAME</Text>
        <GlassInput
          value={companyForm.name}
          onChangeText={(t) => setCompanyForm((s) => ({ ...s, name: t }))}
          placeholder="e.g. ACME Construction Inc"
        />
      </View>
      <View style={styles.field}>
        <Text style={styles.fieldLabel}>NYC GC LICENSE NUMBER</Text>
        <GlassInput
          value={companyForm.license_number}
          onChangeText={(t) =>
            setCompanyForm((s) => ({ ...s, license_number: t }))
          }
          placeholder="e.g. 0123456"
          keyboardType="numeric"
        />
      </View>
      <View style={styles.field}>
        <Text style={styles.fieldLabel}>PRIMARY OFFICE ADDRESS</Text>
        <GlassInput
          value={companyForm.office_address}
          onChangeText={(t) =>
            setCompanyForm((s) => ({ ...s, office_address: t }))
          }
          placeholder="123 Main St, Brooklyn, NY 11201"
        />
      </View>
    </View>
  );

  const renderStep2 = () => (
    <View style={styles.form}>
      <View style={styles.field}>
        <Text style={styles.fieldLabel}>PROJECT NAME</Text>
        <GlassInput
          value={projectForm.name}
          onChangeText={(t) => setProjectForm((s) => ({ ...s, name: t }))}
          placeholder="e.g. 123 Front Street Renovation"
        />
      </View>
      <View style={styles.field}>
        <Text style={styles.fieldLabel}>PROJECT ADDRESS</Text>
        <GlassInput
          value={projectForm.address}
          onChangeText={(t) => setProjectForm((s) => ({ ...s, address: t }))}
          placeholder="123 Front St, Brooklyn, NY 11201"
        />
        <Text style={styles.fieldHint}>
          We'll auto-resolve the BIN from this address to pull DOB filings,
          permits, violations, and inspections.
        </Text>
      </View>
      <View style={isMobile ? styles.dateRowMobile : styles.dateRowDesktop}>
        <View style={styles.dateField}>
          <Text style={styles.fieldLabel}>EXPECTED START</Text>
          <GlassInput
            value={projectForm.expected_start_date}
            onChangeText={(t) =>
              setProjectForm((s) => ({ ...s, expected_start_date: t }))
            }
            placeholder="YYYY-MM-DD"
          />
        </View>
        <View style={styles.dateField}>
          <Text style={styles.fieldLabel}>EXPECTED COMPLETION</Text>
          <GlassInput
            value={projectForm.expected_completion_date}
            onChangeText={(t) =>
              setProjectForm((s) => ({ ...s, expected_completion_date: t }))
            }
            placeholder="YYYY-MM-DD"
          />
        </View>
      </View>
    </View>
  );

  const renderStep3 = () => (
    <View style={styles.form}>
      {filingReps.map((rep, idx) => (
        <View key={idx} style={styles.repCard}>
          <View style={styles.repCardHeader}>
            <Text style={styles.repCardTitle}>FILING REP #{idx + 1}</Text>
            {filingReps.length > 1 ? (
              <Pressable
                onPress={() =>
                  setFilingReps((arr) => arr.filter((_, i) => i !== idx))
                }
                accessibilityLabel="Remove this filing rep"
              >
                <Trash2 size={16} color={colors.text.muted} />
              </Pressable>
            ) : null}
          </View>
          <View style={styles.field}>
            <Text style={styles.fieldLabel}>NAME</Text>
            <GlassInput
              value={rep.name}
              onChangeText={(t) =>
                setFilingReps((arr) =>
                  arr.map((r, i) => (i === idx ? { ...r, name: t } : r))
                )
              }
              placeholder="Jane Doe"
            />
          </View>
          <View style={isMobile ? styles.dateRowMobile : styles.dateRowDesktop}>
            <View style={styles.dateField}>
              <Text style={styles.fieldLabel}>LICENSE NUMBER</Text>
              <GlassInput
                value={rep.license_number}
                onChangeText={(t) =>
                  setFilingReps((arr) =>
                    arr.map((r, i) =>
                      i === idx ? { ...r, license_number: t } : r
                    )
                  )
                }
                placeholder="0123456"
              />
            </View>
            <View style={styles.dateField}>
              <Text style={styles.fieldLabel}>PHONE</Text>
              <GlassInput
                value={rep.phone}
                onChangeText={(t) =>
                  setFilingReps((arr) =>
                    arr.map((r, i) => (i === idx ? { ...r, phone: t } : r))
                  )
                }
                placeholder="(555) 555-5555"
              />
            </View>
          </View>
          <View style={styles.field}>
            <Text style={styles.fieldLabel}>EMAIL</Text>
            <GlassInput
              value={rep.email}
              onChangeText={(t) =>
                setFilingReps((arr) =>
                  arr.map((r, i) => (i === idx ? { ...r, email: t } : r))
                )
              }
              placeholder="jane@example.com"
              keyboardType="email-address"
            />
          </View>
        </View>
      ))}
      <Pressable
        onPress={() =>
          setFilingReps((arr) => [
            ...arr,
            { name: '', license_number: '', email: '', phone: '' },
          ])
        }
        style={styles.addRepBtn}
      >
        <Plus size={16} color={colors.text.primary} />
        <Text style={styles.addRepBtnText}>Add another rep</Text>
      </Pressable>
    </View>
  );

  const renderStep4 = () => (
    <View style={styles.form}>
      <Text style={styles.step4Lead}>
        We've selected{' '}
        <Text style={styles.step4LeadBold}>Critical only</Text> by default —
        only urgent items get an email. You'll see all activity in the feed
        regardless.
      </Text>
      {PRESET_ORDER.map((key) => {
        const preset = PRESETS[key];
        const isActive = selectedPreset === key;
        return (
          <Pressable
            key={key}
            onPress={() => setSelectedPreset(key)}
            style={[
              styles.presetCard,
              isActive && styles.presetCardActive,
            ]}
            accessibilityRole="radio"
            accessibilityState={{ selected: isActive }}
          >
            <View style={styles.presetCardHeader}>
              <View style={styles.presetCheck}>
                {isActive ? (
                  <CheckCircle2
                    size={20}
                    color={colors.primary}
                    strokeWidth={2}
                  />
                ) : (
                  <View style={styles.presetCheckEmpty} />
                )}
              </View>
              <View style={styles.presetCardTextWrap}>
                <View style={styles.presetCardLabelRow}>
                  <Text style={styles.presetCardLabel}>{preset.label}</Text>
                  {preset.badge ? (
                    <View style={styles.presetBadge}>
                      <Text style={styles.presetBadgeText}>{preset.badge}</Text>
                    </View>
                  ) : null}
                  {/* Phase B4: tooltip on each preset radio in
                      onboarding step 4. preset.bodyHelp is the
                      detailed 1-2 sentence behavior description from
                      the B1b.1 PRESETS object. */}
                  {preset.bodyHelp ? (
                    <InfoTooltip text={preset.bodyHelp} size={14} />
                  ) : null}
                </View>
                <Text style={styles.presetCardSubtitle}>{preset.subtitle}</Text>
              </View>
            </View>
          </Pressable>
        );
      })}
    </View>
  );

  // ── Footer (CTA + skip) ──────────────────────────────────────────
  const renderFooter = () => {
    const handlers = {
      1: submitStep1,
      2: submitStep2,
      3: submitStep3,
      4: submitStep4,
    };
    const ctaLabels = {
      1: 'Continue',
      2: 'Continue',
      3: 'Continue',
      4: 'Finish setup',
    };
    const skipLabels = {
      1: "I'll do this later",
      2: 'Skip this step',
      3: 'Skip this step',
      4: 'Use Critical only',
    };
    return (
      <View style={styles.footer}>
        <GlassButton
          title={submitting ? 'Saving...' : ctaLabels[currentStep]}
          icon={
            !submitting ? (
              <ArrowRight
                size={18}
                strokeWidth={1.5}
                color={colors.text.primary}
              />
            ) : null
          }
          iconRight
          onPress={handlers[currentStep]}
          loading={submitting}
          style={styles.cta}
        />
        <Pressable
          onPress={
            currentStep === '4' ? finalizeAndExit : skipFromCurrentStep
          }
          disabled={submitting}
          style={styles.skipBtn}
          accessibilityRole="button"
        >
          <Text style={styles.skipBtnText}>{skipLabels[currentStep]}</Text>
        </Pressable>
      </View>
    );
  };

  const renderStepBody = () => {
    if (currentStep === '1') return renderStep1();
    if (currentStep === '2') return renderStep2();
    if (currentStep === '3') return renderStep3();
    if (currentStep === '4') return renderStep4();
    return null;
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.safe} edges={['top']}>
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          {renderProgress()}
          <GlassCard style={styles.card}>
            {renderStepHeader()}
            {renderStepBody()}
            {renderFooter()}
          </GlassCard>
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    safe: { flex: 1, backgroundColor: 'transparent' },
    scroll: { flex: 1 },
    scrollContent: {
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.lg,
      paddingBottom: 80,
      maxWidth: 720,
      width: '100%',
      alignSelf: 'center',
    },
    loading: {
      flex: 1,
      justifyContent: 'center',
      alignItems: 'center',
    },

    // Progress indicator at top.
    progress: {
      marginBottom: spacing.lg,
    },
    progressText: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
      textAlign: 'center',
    },
    progressTrack: {
      flexDirection: 'row',
      gap: spacing.sm,
      justifyContent: 'center',
    },
    progressDot: {
      width: 32,
      height: 4,
      borderRadius: 2,
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    progressDotActive: {
      backgroundColor: colors.primary,
      borderColor: colors.primary,
    },
    progressDotDone: {
      backgroundColor: colors.success || colors.primary,
      borderColor: colors.success || colors.primary,
    },

    // Step card.
    card: {
      padding: spacing.xl,
    },

    // Step header.
    stepHeader: {
      alignItems: 'center',
      marginBottom: spacing.xl,
    },
    stepIconCircle: {
      width: 56,
      height: 56,
      borderRadius: 28,
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      alignItems: 'center',
      justifyContent: 'center',
      marginBottom: spacing.md,
    },
    stepTitle: {
      fontSize: 22,
      fontWeight: '600',
      color: colors.text.primary,
      marginBottom: spacing.sm,
      textAlign: 'center',
    },
    stepSubtitle: {
      fontSize: 14,
      lineHeight: 20,
      color: colors.text.secondary,
      textAlign: 'center',
      maxWidth: 480,
    },

    // Forms.
    form: { gap: spacing.md },
    field: { gap: spacing.xs },
    fieldLabel: {
      ...typography.label,
      color: colors.text.muted,
    },
    fieldHint: {
      fontSize: 12,
      color: colors.text.muted,
      lineHeight: 16,
      marginTop: spacing.xs,
    },
    dateRowMobile: { gap: spacing.md },
    dateRowDesktop: {
      flexDirection: 'row',
      gap: spacing.md,
    },
    dateField: {
      flex: 1,
      gap: spacing.xs,
    },

    // Filing rep card.
    repCard: {
      padding: spacing.md,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
      gap: spacing.md,
    },
    repCardHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    repCardTitle: {
      ...typography.label,
      color: colors.text.muted,
    },
    addRepBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      alignSelf: 'flex-start',
      borderRadius: borderRadius.md,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
    },
    addRepBtnText: {
      fontSize: 13,
      color: colors.text.primary,
    },

    // Step 4 — preset cards.
    step4Lead: {
      fontSize: 13,
      lineHeight: 19,
      color: colors.text.secondary,
      marginBottom: spacing.sm,
    },
    step4LeadBold: {
      color: colors.text.primary,
      fontWeight: '600',
    },
    presetCard: {
      padding: spacing.md,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      backgroundColor: colors.glass.background,
    },
    presetCardActive: {
      borderColor: colors.primary,
      backgroundColor: colors.glass.backgroundHover,
    },
    presetCardHeader: {
      flexDirection: 'row',
      gap: spacing.md,
      alignItems: 'flex-start',
    },
    presetCheck: { paddingTop: 2 },
    presetCheckEmpty: {
      width: 20,
      height: 20,
      borderRadius: 10,
      borderWidth: 2,
      borderColor: colors.glass.border,
    },
    presetCardTextWrap: { flex: 1 },
    presetCardLabelRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.sm,
      marginBottom: spacing.xs,
    },
    presetCardLabel: {
      fontSize: 15,
      fontWeight: '600',
      color: colors.text.primary,
    },
    presetBadge: {
      paddingHorizontal: spacing.sm,
      paddingVertical: 2,
      borderRadius: borderRadius.sm,
      backgroundColor: colors.primary,
    },
    presetBadgeText: {
      fontSize: 10,
      fontWeight: '700',
      color: colors.text.inverse || '#fff',
      letterSpacing: 0.5,
    },
    presetCardSubtitle: {
      fontSize: 13,
      lineHeight: 18,
      color: colors.text.secondary,
    },

    // Footer.
    footer: {
      marginTop: spacing.xl,
      gap: spacing.md,
    },
    cta: { width: '100%' },
    skipBtn: {
      alignSelf: 'center',
      paddingVertical: spacing.sm,
      paddingHorizontal: spacing.md,
    },
    skipBtnText: {
      fontSize: 13,
      color: colors.text.muted,
      textDecorationLine: 'underline',
    },
  });
}
