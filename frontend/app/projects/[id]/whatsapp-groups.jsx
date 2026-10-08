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
  Trash2,
  X,
  Copy,
  CheckCircle,
  RotateCw,
  ChevronDown,
  ChevronRight,
} from 'lucide-react-native';
import * as Clipboard from 'expo-clipboard';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { useToast } from '../../../src/components/Toast';
import { useAuth, isCompanyAdmin } from '../../../src/context/AuthContext';
import { whatsappAPI, projectsAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';
import GroupConfigPanel from '../../../src/components/whatsapp/GroupConfigPanel';
import LevelogAssistantCard from '../../../src/components/whatsapp/LevelogAssistantCard';
import { groupLabel, headerTitle, messageCountLabel } from '../../../src/utils/whatsappSettings';
import { withAlpha } from '../../../src/styles/semanticColors';
import OfflineNotice from '../../../src/components/OfflineNotice';
import { readCachedProject } from '../../../src/utils/projectCache';
import { settleFetch } from '../../../src/utils/offlineState';

const WHATSAPP_GREEN = '#25D366';
const COUNTDOWN_SECONDS = 300; // 5 minutes

export default function WhatsAppGroupsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  // Admins see the Levelog Assistant settings and the per-group settings.
  // Owner / admin / CP may link and unlink a group (the server's rule).
  const isAdmin = isCompanyAdmin(user);
  const canLink = ['owner', 'admin', 'cp'].includes(String(user?.role || '').toLowerCase());
  const [confirmUnlink, setConfirmUnlink] = useState(null);
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [project, setProject] = useState(null);
  const [groups, setGroups] = useState([]);
  const [whatsappStatus, setWhatsappStatus] = useState(null);
  const [unlinking, setUnlinking] = useState(null);
  const [configOpenId, setConfigOpenId] = useState(null);  // groupId whose config panel is expanded
  // 'ok' | 'offline' | 'error'. Every fetch here used to .catch(() => null/[]),
  // so a dead zone rendered "No groups linked yet" — a false claim.
  const [fetchState, setFetchState] = useState('ok');
  const readOnly = fetchState !== 'ok';

  // Modal state
  const [showLinkModal, setShowLinkModal] = useState(false);
  // The six-digit code flow is kept (see the quiet link under the groups):
  // it is the only path when the person linking cannot add the number to
  // the group themselves.

  const [linkStep, setLinkStep] = useState(1);
  const [verifyCode, setVerifyCode] = useState('');
  const [verifying, setVerifying] = useState(false);
  const [initiating, setInitiating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [generatedCode, setGeneratedCode] = useState('');  // 6-digit code from initiate
  const [codeCopied, setCodeCopied] = useState(false);

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
      const [projectRes, groupsRes, waStatus] = await Promise.all([
        settleFetch(() => projectsAPI.getById(projectId)),
        settleFetch(() => whatsappAPI.getGroups(projectId)),
        whatsappAPI.getStatus().catch(() => null),
      ]);

      // Offline fallback for the project name/header — cacheProject() already
      // stored it from the project list/detail screens.
      let projectData = projectRes.data;
      if (projectRes.status !== 'ok') {
        console.warn('Project fetch failed, using device cache:', projectRes.error?.message);
        projectData = await readCachedProject(projectId);
      }

      // The GROUP list itself is server-only (no cache): the honest offline
      // answer is "unknown", never an empty roster.
      const netState =
        groupsRes.status !== 'ok'
          ? groupsRes.status
          : projectRes.status !== 'ok'
            ? projectRes.status
            : 'ok';
      setFetchState(netState);

      setProject(projectData);
      setGroups(Array.isArray(groupsRes.data) ? groupsRes.data : []);
      setWhatsappStatus(waStatus);
    } catch (error) {
      console.error('Failed to fetch data:', error);
      setFetchState('error');
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
    setGeneratedCode('');
    setCodeCopied(false);
    if (timerRef.current) clearInterval(timerRef.current);
  };

  const handleInitiateLink = async () => {
    setInitiating(true);
    try {
      const result = await whatsappAPI.initiateLink(projectId);
      setGeneratedCode(result?.code || '');
      setVerifyCode(result?.code || '');  // pre-fill input so user just hits Verify
      setLinkStep(2);
    } catch (error) {
      console.error('Failed to initiate link:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not initiate group link');
    } finally {
      setInitiating(false);
    }
  };

  const handleCopyCode = async () => {
    if (!generatedCode) return;
    try {
      await Clipboard.setStringAsync(generatedCode);
      setCodeCopied(true);
      setTimeout(() => setCodeCopied(false), 2000);
    } catch (e) {
      toast.error('Error', 'Could not copy code');
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
    // Two taps: the first asks, the second unlinks. (A dialog would not
    // show on the web build.)
    if (confirmUnlink !== groupDocId) {
      setConfirmUnlink(groupDocId);
      return;
    }
    setConfirmUnlink(null);
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
            <Text style={s.titleLabel}>
              {project?.address || project?.location || project?.name || 'PROJECT'}
            </Text>
            <Text style={s.titleText}>{headerTitle(readOnly ? 0 : groups.length)}</Text>
          </View>

          {loading ? (
            <View style={s.loadingContainer}>
              <ActivityIndicator size="large" color={colors.text.primary} />
              <Text style={s.loadingText}>Loading...</Text>
            </View>
          ) : (
            <>
              {readOnly && (
                <>
                  <OfflineNotice
                    mode={fetchState}
                    detail={
                      fetchState === 'error'
                        ? 'Could not load the linked groups. This is NOT a statement that no groups are linked.'
                        : 'Offline — the linked groups for this project could not be read, and linking a group needs a live connection to WhatsApp. This is NOT a statement that no groups are linked.'
                    }
                  />
                  <GlassButton
                    title="Retry"
                    icon={<RotateCw size={16} strokeWidth={1.5} color={colors.text.primary} />}
                    onPress={fetchData}
                    style={s.retryBtn}
                  />
                </>
              )}

              {/* ── GROUPS ─────────────────────────────────────────────────
                  Real names and message counts. Linking a new group lives
                  in Integrations ("Link new groups"), not here. */}
              <Text style={s.sectionHeading}>Groups</Text>
              {groups.length > 0 ? (
                <View style={s.groupsList}>
                  {groups.map((group) => {
                    const groupId = group._id || group.id;
                    const asking = confirmUnlink === groupId;
                    return (
                      <GlassCard key={groupId} style={s.groupItem}>
                        <View style={s.groupRow}>
                          <View style={s.groupIconWrap}>
                            <MessageCircle size={22} strokeWidth={1.5} color={WHATSAPP_GREEN} />
                          </View>
                          <View style={s.groupInfo}>
                            <Text style={s.groupName} numberOfLines={1}>
                              {groupLabel(group.group_name)}
                            </Text>
                            <Text style={s.groupMeta}>{messageCountLabel(group.message_count)}</Text>
                          </View>
                          {canLink ? (
                            <Pressable
                              onPress={() => handleUnlinkGroup(groupId)}
                              disabled={unlinking === groupId || readOnly}
                              accessibilityLabel={asking ? 'Tap again to unlink' : 'Unlink group'}
                              style={({ pressed }) => [s.iconBtn, pressed && { opacity: 0.7 }]}
                            >
                              {unlinking === groupId ? (
                                <ActivityIndicator size="small" color={colors.status.error} />
                              ) : asking ? (
                                <Text style={s.unlinkConfirm}>Unlink?</Text>
                              ) : (
                                <Trash2 size={18} strokeWidth={1.5} color={colors.status.error} />
                              )}
                            </Pressable>
                          ) : null}
                        </View>
                      </GlassCard>
                    );
                  })}
                </View>
              ) : readOnly ? (
                <GlassCard style={s.emptyCard}>
                  <MessageCircle size={48} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyTitle}>Groups unavailable</Text>
                  <Text style={s.emptyDesc}>
                    Reconnect to see which WhatsApp groups are linked to this project.
                  </Text>
                </GlassCard>
              ) : (
                <GlassCard style={s.emptyCard}>
                  <MessageCircle size={48} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={s.emptyTitle}>No groups linked yet</Text>
                  <Text style={s.emptyDesc}>
                    Add the Levelog number to the job's WhatsApp group, then link it in
                    Integrations → Link new groups.
                  </Text>
                </GlassCard>
              )}

              {/* The six-digit flow, kept for the case where the number
                  can't be added by the person linking. Quiet, and only for
                  those who may link. */}
              {canLink ? (
                <Pressable
                  onPress={handleOpenLinkModal}
                  disabled={readOnly}
                  style={({ pressed }) => [s.quietLink, pressed && { opacity: 0.7 }]}
                >
                  <Text style={s.quietLinkText}>
                    {readOnly ? 'Linking needs a connection' : 'Link a group with a code instead'}
                  </Text>
                </Pressable>
              ) : null}

              {/* ── LEVELOG ASSISTANT (admins) ──────────────────────────── */}
              {isAdmin && !readOnly ? (
                <LevelogAssistantCard projectId={projectId} />
              ) : null}

              {/* ── WHAT THE BOT DOES IN GROUPS (admins) ─────────────────── */}
              {isAdmin && !readOnly && groups.length > 0 ? (
                <>
                  <Text style={s.sectionHeading}>What the bot does in groups</Text>
                  {groups.map((group) => {
                    const groupId = group._id || group.id;
                    const open = configOpenId === groupId;
                    return (
                      <View key={`cfg-${groupId}`}>
                        <Pressable
                          onPress={() => setConfigOpenId(open ? null : groupId)}
                          style={({ pressed }) => [pressed && { opacity: 0.8 }]}
                          accessibilityRole="button"
                        >
                          <GlassCard style={s.groupItem}>
                            <View style={s.groupRow}>
                              <Text style={[s.groupName, { flex: 1 }]} numberOfLines={1}>
                                {groupLabel(group.group_name)}
                              </Text>
                              {open
                                ? <ChevronDown size={18} color={colors.text.muted} />
                                : <ChevronRight size={18} color={colors.text.muted} />}
                            </View>
                          </GlassCard>
                        </Pressable>
                        {open ? (
                          <GroupConfigPanel
                            group={group}
                            onSaved={(updated) => {
                              setGroups((prev) => prev.map((g) => (
                                (g._id || g.id) === groupId
                                  ? { ...g, bot_config: updated.bot_config || g.bot_config }
                                  : g)));
                            }}
                            onClose={() => setConfigOpenId(null)}
                          />
                        ) : null}
                      </View>
                    );
                  })}
                </>
              ) : null}

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
                    1. Copy this code   2. Paste it as a message in your WhatsApp group   3. Tap Verify
                  </Text>

                  {/* Generated code display + copy button */}
                  <View style={s.phoneDisplay}>
                    <Text style={[s.phoneNumber, { letterSpacing: 6 }]}>
                      {generatedCode || '------'}
                    </Text>
                    <Pressable onPress={handleCopyCode} style={s.copyBtn}>
                      {codeCopied ? (
                        <CheckCircle size={20} strokeWidth={1.5} color={WHATSAPP_GREEN} />
                      ) : (
                        <Copy size={20} strokeWidth={1.5} color={colors.text.muted} />
                      )}
                      <Text style={[s.copyText, codeCopied && { color: WHATSAPP_GREEN }]}>
                        {codeCopied ? 'Copied!' : 'Copy'}
                      </Text>
                    </Pressable>
                  </View>

                  {/* Countdown */}
                  <View style={s.countdownWrap}>
                    <Text style={[s.countdownText, countdown === 0 && { color: colors.status.error }, { fontSize: 14 }]}>
                      {countdown > 0 ? `Code expires in ${formatCountdown(countdown)}` : 'Code expired — close and try again'}
                    </Text>
                  </View>

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
    sectionHeading: {
      fontSize: 13,
      fontWeight: '600',
      color: colors.text.muted,
      letterSpacing: 0.6,
      textTransform: 'uppercase',
      marginTop: spacing.lg,
      marginBottom: spacing.sm,
    },
    groupMeta: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
    unlinkConfirm: { fontSize: 12, fontWeight: '600', color: colors.status.error },
    quietLink: { paddingVertical: spacing.sm, marginTop: spacing.xs },
    quietLinkText: { fontSize: 13, color: colors.text.muted },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: withAlpha('#ffffff', 0.08),
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
    retryBtn: {
      alignSelf: 'flex-start',
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
      backgroundColor: 'rgba(37, 211, 102, 0.1)', /* brand: WhatsApp - intentional, not a token */
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
    iconBtn: {
      width: 36,
      height: 36,
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
      backgroundColor: withAlpha('#000000', 0.6),
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
