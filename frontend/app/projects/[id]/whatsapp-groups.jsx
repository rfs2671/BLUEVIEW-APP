import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Modal,
  TextInput,
  Platform,
  Image,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  MessageCircle,
  Plus,
  Trash2,
  X,
  Copy,
  CheckCircle,
} from 'lucide-react-native';
import * as Clipboard from 'expo-clipboard';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { whatsappAPI, projectsAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

const WHATSAPP_GREEN = '#25D366';
const COUNTDOWN_SECONDS = 300; // 5 minutes

export default function WhatsAppGroupsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [project, setProject] = useState(null);
  const [groups, setGroups] = useState([]);
  const [whatsappStatus, setWhatsappStatus] = useState(null);
  const [unlinking, setUnlinking] = useState(null);

  // Modal state
  const [showLinkModal, setShowLinkModal] = useState(false);
  const [linkStep, setLinkStep] = useState(1);
  const [verifyCode, setVerifyCode] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [initiating, setInitiating] = useState(false);
  const [copied, setCopied] = useState(false);

  // Countdown timer
  const [countdown, setCountdown] = useState(COUNTDOWN_SECONDS);
  const timerRef = useRef(null);

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  // Fetch data
  useEffect(() => {
    if (isAuthenticated && projectId) {
      fetchData();
    }
  }, [isAuthenticated, projectId]);

  // Countdown effect
  useEffect(() => {
    if (linkStep === 2 && showLinkModal) {
      setCountdown(COUNTDOWN_SECONDS);
      timerRef.current = setInterval(() => {
        setCountdown((prev) => {
          if (prev <= 1) {
            clearInterval(timerRef.current);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [linkStep, showLinkModal]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [projectData, groupsData, waStatus] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        whatsappAPI.getGroups(projectId).catch(() => []),
        whatsappAPI.getStatus().catch(() => null),
      ]);
      setProject(projectData);
      setGroups(Array.isArray(groupsData) ? groupsData : []);
      setWhatsappStatus(waStatus);
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Load Error', 'Could not load WhatsApp groups');
    } finally {
      setLoading(false);
    }
  };

  const formatPhoneNumber = (number) => {
    if (!number) return '';
    const cleaned = number.replace(/\D/g, '');
    if (cleaned.length === 11 && cleaned.startsWith('1')) {
      return `+1 (${cleaned.slice(1, 4)}) ${cleaned.slice(4, 7)}-${cleaned.slice(7)}`;
    }
    return `+${cleaned}`;
  };

  const handleCopyNumber = async () => {
    try {
      await Clipboard.setStringAsync(whatsappStatus?.whatsapp_number || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      toast.error('Error', 'Could not copy to clipboard');
    }
  };

  const handleOpenLinkModal = () => {
    setShowLinkModal(true);
    setLinkStep(1);
    setVerifyCode('');
    setCopied(false);
  };

  const handleCloseLinkModal = () => {
    setShowLinkModal(false);
    setLinkStep(1);
    setVerifyCode('');
    setCopied(false);
    if (timerRef.current) clearInterval(timerRef.current);
  };

  const handleInitiateLink = async () => {
    setInitiating(true);
    try {
      await whatsappAPI.initiateLink(projectId);
      setLinkStep(2);
    } catch (error) {
      console.error('Failed to initiate link:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not initiate group link');
    } finally {
      setInitiating(false);
    }
  };

  const handleVerifyLink = async () => {
    if (verifyCode.length !== 6) {
      toast.error('Error', 'Please enter the full 6-digit code');
      return;
    }
    setVerifying(true);
    try {
      await whatsappAPI.verifyLink(verifyCode, projectId);
      handleCloseLinkModal();
      await fetchData();
      toast.success('Group Linked!', 'WhatsApp group has been linked to this project');
    } catch (error) {
      console.error('Failed to verify link:', error);
      toast.error('Invalid or expired code', error.response?.data?.detail || 'Please try again');
    } finally {
      setVerifying(false);
    }
  };

  const handleUnlinkGroup = async (groupDocId) => {
    setUnlinking(groupDocId);
    try {
      await whatsappAPI.unlinkGroup(groupDocId);
      setGroups((prev) => prev.filter((g) => (g._id || g.id) !== groupDocId));
      toast.success('Unlinked', 'Group has been removed');
    } catch (error) {
      console.error('Failed to unlink group:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not unlink group');
    } finally {
      setUnlinking(null);
    }
  };

  const formatCountdown = (seconds) => {
    const m = Math.floor(seconds / 60);
    const sec = seconds % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <HeaderBrand />
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>{project?.name || 'PROJECT'}</Text>
            <Text style={s.titleText}>WhatsApp Groups</Text>
          </View>

          {loading ? (
            <View style={s.loadingContainer}>
              <ActivityIndicator size="large" color={colors.text.primary} />
              <Text style={s.loadingText}>Loading...</Text>
            </View>
          ) : (
            <>
              {/* Link a Group Button */}
              <GlassButton
                title="+ Link a Group"
                icon={<Plus size={18} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={handleOpenLinkModal}
                style={s.linkButton}
              />

              {/* Groups List */}
              {groups.length > 0 ? (
                <View style={s.groupsList}>
                  {groups.map((group) => {
                    const groupId = group._id || group.id;
                    return (
                      <GlassCard key={groupId} style={s.groupItem}>
                        <View style={s.groupRow}>
                          <View style={s.groupIconWrap}>
                            <MessageCircle size={22} strokeWidth={1.5} color={WHATSAPP_GREEN} />
                          </View>
                          <View style={s.groupInfo}>
                            <Text style={s.groupName} numberOfLines={1}>
                              {group.group_name || group.name || 'WhatsApp Group'}
                            </Text>
                            {group.message_count != null && (
                              <View style={s.messageBadge}>
                                <Text style={s.messageBadgeText}>
                                  {group.message_count} messages
                                </Text>
                              </View>
                            )}
                          </View>
                          <Pressable
                            onPress={() => handleUnlinkGroup(groupId)}
                            disabled={unlinking === groupId}
                            style={({ pressed }) => [
                              s.unlinkBtn,
                              pressed && { opacity: 0.7 },
                            ]}
                          >
                            {unlinking === groupId ? (
                              <ActivityIndicator size="small" color={colors.status.error} />
                            ) : (
                              <Trash2 size={18} strokeWidth={1.5} color={colors.status.error} />
                            )}
                          </Pressable>
                        </View>
                      </GlassCard>
                    );
                  })}
                </View>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <MessageCircle size={48} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyTitle}>No groups linked yet</Text>
                  <Text style={s.emptyDesc}>
                    Link a WhatsApp group to this project to enable messaging, site queries, and
                    daily summaries for your team.
                  </Text>
                </GlassCard>
              )}
            </>
          )}
        </ScrollView>

        {/* Link Group Modal */}
        <Modal
          visible={showLinkModal}
          transparent
          animationType="fade"
          onRequestClose={handleCloseLinkModal}
        >
          <View style={s.modalOverlay}>
            <GlassCard variant="modal" style={s.modalCard}>
              {/* Modal Header */}
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>
                  {linkStep === 1 ? 'Add LeveLog to your group' : 'Enter the code from your group'}
                </Text>
                <GlassButton
                  variant="icon"
                  icon={<X size={20} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={handleCloseLinkModal}
                />
              </View>

              {linkStep === 1 ? (
                <View style={s.modalBody}>
                  <Text style={s.modalDesc}>
                    Add this number to the WhatsApp group you want to link:
                  </Text>

                  {/* Phone Number Display */}
                  <View style={s.phoneDisplay}>
                    <Text style={s.phoneNumber}>
                      {formatPhoneNumber(whatsappStatus?.whatsapp_number)}
                    </Text>
                    <Pressable onPress={handleCopyNumber} style={s.copyBtn}>
                      {copied ? (
                        <CheckCircle size={20} strokeWidth={1.5} color={WHATSAPP_GREEN} />
                      ) : (
                        <Copy size={20} strokeWidth={1.5} color={colors.text.muted} />
                      )}
                      <Text style={[s.copyText, copied && { color: WHATSAPP_GREEN }]}>
                        {copied ? 'Copied!' : 'Copy'}
                      </Text>
                    </Pressable>
                  </View>

                  <Pressable
                    onPress={handleInitiateLink}
                    disabled={initiating}
                    style={({ pressed }) => [
                      s.whatsappActionBtn,
                      pressed && { opacity: 0.9, transform: [{ scale: 0.98 }] },
                      initiating && { opacity: 0.6 },
                    ]}
                  >
                    {initiating ? (
                      <ActivityIndicator size="small" color="#fff" />
                    ) : (
                      <Text style={s.whatsappActionBtnText}>I've added the number</Text>
                    )}
                  </Pressable>
                </View>
              ) : (
                <View style={s.modalBody}>
                  <Text style={s.modalDesc}>
                    Look for a 6-digit code in the group chat
                  </Text>

                  {/* Countdown */}
                  <View style={s.countdownWrap}>
                    <Text style={[s.countdownText, countdown === 0 && { color: colors.status.error }]}>
                      {countdown > 0 ? formatCountdown(countdown) : 'Code expired'}
                    </Text>
                  </View>

                  {/* Code Input */}
                  <TextInput
                    style={s.codeInput}
                    value={verifyCode}
                    onChangeText={(t) => setVerifyCode(t.replace(/\D/g, '').slice(0, 6))}
                    placeholder="000000"
                    placeholderTextColor={colors.text.subtle}
                    keyboardType="number-pad"
                    maxLength={6}
                    textAlign="center"
                  />

                  <Pressable
                    onPress={handleVerifyLink}
                    disabled={verifying || verifyCode.length !== 6 || countdown === 0}
                    style={({ pressed }) => [
                      s.whatsappActionBtn,
                      pressed && { opacity: 0.9, transform: [{ scale: 0.98 }] },
                      (verifying || verifyCode.length !== 6 || countdown === 0) && { opacity: 0.6 },
                    ]}
                  >
                    {verifying ? (
                      <ActivityIndicator size="small" color="#fff" />
                    ) : (
                      <Text style={s.whatsappActionBtnText}>Verify</Text>
                    )}
                  </Pressable>
                </View>
              )}
            </GlassCard>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: {
      flex: 1,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: 'rgba(255, 255, 255, 0.08)',
    },
    headerLeft: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    logoText: {
      ...typography.label,
      color: colors.text.muted,
    },
    scrollView: {
      flex: 1,
    },
    scrollContent: {
      padding: spacing.lg,
      paddingBottom: 120,
    },
    titleSection: {
      marginBottom: spacing.lg,
    },
    titleLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
    },
    titleText: {
      fontSize: 36,
      fontWeight: '200',
      color: colors.text.primary,
      letterSpacing: -0.5,
    },
    loadingContainer: {
      alignItems: 'center',
      paddingVertical: spacing.xxl * 2,
      gap: spacing.md,
    },
    loadingText: {
      color: colors.text.muted,
      fontSize: 14,
    },
    linkButton: {
      marginBottom: spacing.lg,
    },
    groupsList: {
      gap: spacing.sm,
    },
    groupItem: {
      padding: 0,
    },
    groupRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.md,
    },
    groupIconWrap: {
      width: 44,
      height: 44,
      borderRadius: borderRadius.full,
      backgroundColor: 'rgba(37, 211, 102, 0.1)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    groupInfo: {
      flex: 1,
    },
    groupName: {
      fontSize: 16,
      fontWeight: '500',
      color: colors.text.primary,
      marginBottom: 4,
    },
    messageBadge: {
      alignSelf: 'flex-start',
      paddingHorizontal: spacing.sm,
      paddingVertical: 2,
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.full,
      borderWidth: 1,
      borderColor: colors.glass.border,
    },
    messageBadgeText: {
      fontSize: 12,
      color: colors.text.muted,
    },
    unlinkBtn: {
      width: 40,
      height: 40,
      borderRadius: borderRadius.full,
      alignItems: 'center',
      justifyContent: 'center',
    },
    emptyCard: {
      alignItems: 'center',
      paddingVertical: spacing.xxl,
      gap: spacing.md,
    },
    emptyTitle: {
      fontSize: 20,
      fontWeight: '500',
      color: colors.text.primary,
    },
    emptyDesc: {
      fontSize: 14,
      color: colors.text.muted,
      textAlign: 'center',
      maxWidth: 300,
      lineHeight: 22,
    },

    // Modal styles
    modalOverlay: {
      flex: 1,
      backgroundColor: 'rgba(0, 0, 0, 0.6)',
      justifyContent: 'center',
      alignItems: 'center',
      padding: spacing.lg,
    },
    modalCard: {
      width: '100%',
      maxWidth: 420,
    },
    modalHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      marginBottom: spacing.lg,
    },
    modalTitle: {
      fontSize: 20,
      fontWeight: '600',
      color: colors.text.primary,
      flex: 1,
    },
    modalBody: {
      gap: spacing.lg,
    },
    modalDesc: {
      fontSize: 14,
      color: colors.text.secondary,
      lineHeight: 22,
    },
    phoneDisplay: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      backgroundColor: colors.glass.background,
      borderRadius: borderRadius.lg,
      borderWidth: 1,
      borderColor: colors.glass.border,
      padding: spacing.lg,
    },
    phoneNumber: {
      fontSize: 22,
      fontWeight: '600',
      color: colors.text.primary,
      letterSpacing: 1,
    },
    copyBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: spacing.xs,
      paddingHorizontal: spacing.sm,
      paddingVertical: spacing.xs,
    },
    copyText: {
      fontSize: 13,
      fontWeight: '500',
      color: colors.text.muted,
    },
    whatsappActionBtn: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: spacing.sm,
      backgroundColor: WHATSAPP_GREEN,
      borderRadius: borderRadius.lg,
      paddingVertical: spacing.md + 4,
      paddingHorizontal: spacing.xl,
    },
    whatsappActionBtnText: {
      fontSize: 16,
      fontWeight: '600',
      color: '#fff',
    },
    countdownWrap: {
      alignItems: 'center',
    },
    countdownText: {
      fontSize: 28,
      fontWeight: '300',
      color: colors.text.primary,
      letterSpacing: 2,
    },
    codeInput: {
      backgroundColor: colors.glass.background,
      borderWidth: 1,
      borderColor: colors.glass.border,
      borderRadius: borderRadius.lg,
      paddingHorizontal: spacing.xl,
      paddingVertical: spacing.lg,
      color: colors.text.primary,
      fontSize: 32,
      fontWeight: '600',
      letterSpacing: 8,
      textAlign: 'center',
    },
  });
}
