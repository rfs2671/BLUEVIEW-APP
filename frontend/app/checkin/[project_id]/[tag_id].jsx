import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  Pressable,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Modal,
} from 'react-native';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Building2,
  MapPin,
  User,
  Phone,
  Briefcase,
  HardHat,
  CheckCircle,
  ChevronDown,
  Check,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import apiClient from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';

/**
 * PUBLIC CHECK-IN PAGE
 * Workers access this by tapping NFC tag
 * URL: /checkin/{project_id}/{tag_id}
 * No authentication required
 */

export default function PublicCheckInScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const { project_id, tag_id } = useLocalSearchParams();
  const router = useRouter();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [projectInfo, setProjectInfo] = useState(null);

  // Form state
  const [workerName, setWorkerName] = useState('');
  const [workerPhone, setWorkerPhone] = useState('');
  const [workerCompany, setWorkerCompany] = useState('');
  const [workerTrade, setWorkerTrade] = useState('');
  // Dropdown state — the check-in page enforces a strict list of trades
  // set by the project admin. No free-text input.
  const [showTradePicker, setShowTradePicker] = useState(false);

  useEffect(() => {
    fetchProjectInfo();
  }, [project_id, tag_id]);

  const fetchProjectInfo = async () => {
    setLoading(true);
    try {
      // Call public endpoint to get project info
      const response = await apiClient.get(`/api/checkin/${project_id}/${tag_id}/info`);
      setProjectInfo(response.data);
    } catch (error) {
      console.error('Failed to fetch project info:', error);
      toast.error('Error', 'Invalid check-in link. Please contact your supervisor.');
    } finally {
      setLoading(false);
    }
  };

  const handleCheckIn = async () => {
    // Validation
    if (!workerName.trim()) {
      toast.warning('Required', 'Please enter your name');
      return;
    }
    if (!workerPhone.trim()) {
      toast.warning('Required', 'Please enter your phone number');
      return;
    }
    if (!workerCompany.trim()) {
      toast.warning('Required', 'Please enter your company name');
      return;
    }
    if (!workerTrade.trim() || !workerCompany.trim()) {
      toast.warning('Required', 'Please select your trade & company');
      return;
    }
    // Defense-in-depth: server re-validates against the project roster.
    const assignments = projectInfo?.trade_assignments || [];
    const match = assignments.some(
      (a) =>
        (a.trade || '').toLowerCase() === workerTrade.trim().toLowerCase() &&
        (a.company || '').toLowerCase() === workerCompany.trim().toLowerCase()
    );
    if (!match) {
      toast.warning('Invalid Selection', 'Please pick from the dropdown');
      return;
    }

    // Phone validation (basic)
    const phoneRegex = /^[0-9]{10,15}$/;
    const cleanPhone = workerPhone.replace(/[^0-9]/g, '');
    if (!phoneRegex.test(cleanPhone)) {
      toast.warning('Invalid Phone', 'Please enter a valid phone number (10-15 digits)');
      return;
    }

    setSubmitting(true);
    try {
      // Submit check-in (worker will be auto-registered if doesn't exist)
      const response = await apiClient.post('/api/checkin/submit', {
        project_id,
        tag_id,
        name: workerName.trim(),
        phone: cleanPhone,
        company: workerCompany.trim(),
        trade: workerTrade.trim(),
      });

      setSuccess(true);
      toast.success('Success!', 'Check-in recorded successfully');

      // Clear form
      setWorkerName('');
      setWorkerPhone('');
      setWorkerCompany('');
      setWorkerTrade('');

      // Show success for 3 seconds then reset
      setTimeout(() => {
        setSuccess(false);
      }, 3000);
    } catch (error) {
      console.error('Check-in failed:', error);
      toast.error('Error', error.response?.data?.detail || 'Check-in failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={s.loadingText}>Loading check-in...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  if (!projectInfo) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.errorContainer}>
            <Text style={s.errorTitle}>Invalid Check-In Link</Text>
            <Text style={s.errorText}>
              This check-in link is not valid. Please contact your supervisor for assistance.
            </Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container}>
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={s.keyboardView}
        >
          <ScrollView
            style={s.scrollView}
            contentContainerStyle={s.scrollContent}
            showsVerticalScrollIndicator={false}
            keyboardShouldPersistTaps="handled"
          >
            {/* Header */}
            <View style={s.header}>
              <Text style={s.headerLabel}>WORKER CHECK-IN</Text>
              <Text style={s.headerTitle}>LeveLog</Text>
            </View>

            {/* Project Info Card */}
            <GlassCard style={s.projectCard}>
              <View style={s.projectHeader}>
                <Building2 size={24} strokeWidth={1.5} color="#3b82f6" />
                <Text style={s.projectName}>{projectInfo.project_name}</Text>
              </View>
              <View style={s.projectLocation}>
                <MapPin size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.locationText}>
                  {projectInfo.location || 'Check-In Point'}
                </Text>
              </View>
            </GlassCard>

            {success ? (
              /* Success State */
              <GlassCard style={s.successCard}>
                <CheckCircle size={64} strokeWidth={1.5} color="#4ade80" />
                <Text style={s.successTitle}>Check-In Successful!</Text>
                <Text style={s.successText}>
                  You are now checked in to {projectInfo.project_name}
                </Text>
              </GlassCard>
            ) : (
              /* Check-In Form */
              <GlassCard style={s.formCard}>
                <Text style={s.formTitle}>Enter Your Information</Text>
                <Text style={s.formSubtitle}>
                  Fill in your details to check in to this project
                </Text>

                {/* Name Input */}
                <View style={s.inputGroup}>
                  <View style={s.inputHeader}>
                    <User size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.inputLabel}>FULL NAME *</Text>
                  </View>
                  <TextInput
                    style={s.input}
                    value={workerName}
                    onChangeText={setWorkerName}
                    placeholder="John Smith"
                    placeholderTextColor={colors.text.subtle}
                    autoCapitalize="words"
                  />
                </View>

                {/* Phone Input */}
                <View style={s.inputGroup}>
                  <View style={s.inputHeader}>
                    <Phone size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.inputLabel}>PHONE NUMBER *</Text>
                  </View>
                  <TextInput
                    style={s.input}
                    value={workerPhone}
                    onChangeText={setWorkerPhone}
                    placeholder="(555) 123-4567"
                    placeholderTextColor={colors.text.subtle}
                    keyboardType="phone-pad"
                  />
                </View>

                {/* Combined Trade + Company dropdown — strict roster
                    set by the project admin. Both fields get filled
                    from the one pick. */}
                <View style={s.inputGroup}>
                  <View style={s.inputHeader}>
                    <HardHat size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.inputLabel}>TRADE &amp; COMPANY *</Text>
                  </View>
                  <Pressable
                    style={s.input}
                    onPress={() => setShowTradePicker(true)}
                  >
                    <View style={s.dropdownRow}>
                      <View style={{ flex: 1 }}>
                        {workerTrade && workerCompany ? (
                          <>
                            <Text style={s.dropdownText}>{workerTrade}</Text>
                            <Text style={s.dropdownSub}>{workerCompany}</Text>
                          </>
                        ) : (
                          <Text
                            style={[s.dropdownText, { color: colors.text.subtle }]}
                          >
                            Select your trade & company
                          </Text>
                        )}
                      </View>
                      <ChevronDown size={18} strokeWidth={1.5} color={colors.text.muted} />
                    </View>
                  </Pressable>
                </View>

                {/* Trade + Company picker modal */}
                <Modal
                  visible={showTradePicker}
                  transparent
                  animationType="fade"
                  onRequestClose={() => setShowTradePicker(false)}
                >
                  <Pressable
                    style={s.modalOverlay}
                    onPress={() => setShowTradePicker(false)}
                  >
                    <Pressable style={s.modalCard} onPress={() => {}}>
                      <Text style={s.modalTitle}>Select Your Trade & Company</Text>
                      <ScrollView
                        style={s.modalScroll}
                        showsVerticalScrollIndicator={false}
                      >
                        {(projectInfo?.trade_assignments || []).length === 0 ? (
                          <View style={s.emptyAssignments}>
                            <Text style={s.emptyAssignmentsText}>
                              This project has no subcontractors configured yet.
                              Please ask your project admin to set up the
                              check-in list.
                            </Text>
                          </View>
                        ) : (
                          (projectInfo?.trade_assignments || []).map((a, idx) => {
                            const selected =
                              workerTrade.toLowerCase() === (a.trade || '').toLowerCase() &&
                              workerCompany.toLowerCase() === (a.company || '').toLowerCase();
                            return (
                              <Pressable
                                key={`${a.trade}|${a.company}|${idx}`}
                                style={({ pressed }) => [
                                  s.tradeOption,
                                  selected && s.tradeOptionSelected,
                                  pressed && { opacity: 0.7 },
                                ]}
                                onPress={() => {
                                  setWorkerTrade(a.trade);
                                  setWorkerCompany(a.company);
                                  setShowTradePicker(false);
                                }}
                              >
                                <View style={{ flex: 1 }}>
                                  <Text
                                    style={[
                                      s.tradeOptionText,
                                      selected && s.tradeOptionTextSelected,
                                    ]}
                                  >
                                    {a.trade}
                                  </Text>
                                  <Text style={s.tradeOptionSub}>
                                    {a.company}
                                  </Text>
                                </View>
                                {selected && (
                                  <Check size={18} strokeWidth={2} color="#4ade80" />
                                )}
                              </Pressable>
                            );
                          })
                        )}
                      </ScrollView>
                    </Pressable>
                  </Pressable>
                </Modal>

                {/* Submit Button */}
                <GlassButton
                  title={submitting ? 'Checking In...' : 'Check In'}
                  onPress={handleCheckIn}
                  loading={submitting}
                  style={s.submitButton}
                />

                {/* Info Text */}
                <Text style={s.infoText}>
                  By checking in, you confirm your presence at this job site.
                </Text>
              </GlassCard>
            )}
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: {
    flex: 1,
  },
  keyboardView: {
    flex: 1,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
  },
  loadingText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  errorContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  errorTitle: {
    fontSize: 24,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.md,
  },
  errorText: {
    fontSize: 16,
    color: colors.text.muted,
    textAlign: 'center',
    lineHeight: 24,
  },
  header: {
    marginBottom: spacing.xl,
    alignItems: 'center',
  },
  headerLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  headerTitle: {
    fontSize: 42,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
  },
  projectCard: {
    marginBottom: spacing.lg,
    padding: spacing.lg,
  },
  projectHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  projectName: {
    flex: 1,
    fontSize: 22,
    fontWeight: '500',
    color: colors.text.primary,
  },
  projectLocation: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  locationText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  formCard: {
    padding: spacing.lg,
  },
  formTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  formSubtitle: {
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.lg,
  },
  inputGroup: {
    marginBottom: spacing.lg,
  },
  inputHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.sm,
  },
  inputLabel: {
    ...typography.label,
    fontSize: 11,
    color: colors.text.muted,
  },
  input: {
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    color: colors.text.primary,
    fontSize: 16,
  },
  dropdownRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  dropdownText: {
    fontSize: 16,
    color: colors.text.primary,
    flex: 1,
  },
  dropdownSub: {
    fontSize: 13,
    color: colors.text.muted,
    marginTop: 2,
  },
  emptyAssignments: {
    padding: spacing.lg,
    alignItems: 'center',
  },
  emptyAssignmentsText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    lineHeight: 20,
  },
  tradeOptionSub: {
    fontSize: 13,
    color: colors.text.muted,
    marginTop: 2,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.6)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.lg,
  },
  modalCard: {
    width: '100%',
    maxWidth: 420,
    maxHeight: '80%',
    backgroundColor: isDark ? '#1a1f2e' : '#ffffff',
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: spacing.md,
    textAlign: 'center',
  },
  modalScroll: {
    maxHeight: 400,
  },
  tradeOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  tradeOptionSelected: {
    backgroundColor: 'rgba(74, 222, 128, 0.1)',
  },
  tradeOptionText: {
    fontSize: 15,
    color: colors.text.primary,
    flex: 1,
  },
  tradeOptionTextSelected: {
    color: '#4ade80',
    fontWeight: '500',
  },
  submitButton: {
    marginTop: spacing.md,
    marginBottom: spacing.lg,
  },
  infoText: {
    fontSize: 12,
    color: colors.text.subtle,
    textAlign: 'center',
    lineHeight: 18,
  },
  successCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  successTitle: {
    fontSize: 24,
    fontWeight: '500',
    color: '#4ade80',
    marginTop: spacing.md,
  },
  successText: {
    fontSize: 16,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 280,
  },
});
}
