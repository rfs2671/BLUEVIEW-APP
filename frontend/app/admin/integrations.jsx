import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Linking,
  ActivityIndicator,
  TextInput,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Cloud,
  CheckCircle,
  XCircle,
  ExternalLink,
  Unlink,
  LogOut,
  FolderOpen,
  RefreshCw,
  ShieldAlert,
  Key,
  MessageCircle,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { dropboxAPI, projectsAPI, whatsappAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

// Dropbox brand color
const DROPBOX_BLUE = '#0061FF';
// WhatsApp brand color
const WHATSAPP_GREEN = '#25D366';

export default function AdminIntegrationsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [completingAuth, setCompletingAuth] = useState(false);
  const [dropboxStatus, setDropboxStatus] = useState({ connected: false });
  const [projects, setProjects] = useState([]);
  const [showCodeInput, setShowCodeInput] = useState(false);
  const [authCode, setAuthCode] = useState('');
  const [whatsappStatus, setWhatsappStatus] = useState({ platform_configured: false, company_active: false });
  const [activatingWhatsapp, setActivatingWhatsapp] = useState(false);

  // Check if user is admin
  const isAdmin = user?.role === 'admin';

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  // Fetch data on mount
  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    }
  }, [isAuthenticated]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [status, projectsData, waStatus] = await Promise.all([
        dropboxAPI.getStatus().catch(() => ({ connected: false })),
        projectsAPI.getAll().catch(() => []),
        whatsappAPI.getStatus().catch(() => ({ platform_configured: false, company_active: false })),
      ]);
      setDropboxStatus(status);
      setProjects(Array.isArray(projectsData) ? projectsData : []);
      setWhatsappStatus(waStatus);
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Load Error', 'Could not load integration status');
    } finally {
      setLoading(false);
    }
  };

  const handleConnectDropbox = async () => {
    setConnecting(true);
    try {
      const { auth_url } = await dropboxAPI.getAuthUrl();
      
      // Open Dropbox OAuth in browser
      const supported = await Linking.canOpenURL(auth_url);
      if (supported) {
        await Linking.openURL(auth_url);
        // Show code input after opening auth URL
        setShowCodeInput(true);
        toast.info('Dropbox Login', 'Complete authorization in browser, then paste the code below');
      } else {
        toast.error('Error', 'Cannot open Dropbox authorization URL');
      }
    } catch (error) {
      console.error('Failed to get auth URL:', error);
      toast.error('Connection Error', error.response?.data?.detail || 'Could not start Dropbox connection');
    } finally {
      setConnecting(false);
    }
  };

  const handleCompleteAuth = async () => {
    if (!authCode.trim()) {
      toast.error('Error', 'Please enter the authorization code');
      return;
    }

    setCompletingAuth(true);
    try {
      const result = await dropboxAPI.completeAuth(authCode.trim());
      setDropboxStatus({
        connected: true,
        account_email: result.email,
        connected_at: new Date().toISOString(),
      });
      setShowCodeInput(false);
      setAuthCode('');
      toast.success('Connected!', result.email ? `Connected as ${result.email}` : 'Dropbox connected successfully');
    } catch (error) {
      console.error('Failed to complete auth:', error);
      toast.error('Connection Error', error.response?.data?.detail || 'Could not complete Dropbox connection');
    } finally {
      setCompletingAuth(false);
    }
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await dropboxAPI.disconnect();
      setDropboxStatus({ connected: false });
      toast.success('Disconnected', 'Dropbox has been disconnected');
    } catch (error) {
      console.error('Failed to disconnect:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not disconnect Dropbox');
    } finally {
      setDisconnecting(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const handleActivateWhatsapp = async () => {
    setActivatingWhatsapp(true);
    try {
      await whatsappAPI.activate();
      const waStatus = await whatsappAPI.getStatus();
      setWhatsappStatus(waStatus);
      toast.success('WhatsApp Activated', 'WhatsApp integration is now active');
    } catch (error) {
      console.error('Failed to activate WhatsApp:', error);
      toast.error('Activation Error', error.response?.data?.detail || 'Could not activate WhatsApp');
    } finally {
      setActivatingWhatsapp(false);
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

  const projectsWithDropbox = projects.filter((p) => p.dropbox_folder_path);

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            <Text style={s.logoText}>LEVELOG</Text>
          </View>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>ADMIN</Text>
            <Text style={s.titleText}>Integrations</Text>
          </View>

          {!isAdmin ? (
            <GlassCard style={s.accessDeniedCard}>
              <ShieldAlert size={56} strokeWidth={1} color={colors.status.error} />
              <Text style={s.accessDeniedTitle}>Admin Access Required</Text>
              <Text style={s.accessDeniedDesc}>
                Only administrators can manage integrations and connect external services.
              </Text>
              <GlassButton
                title="Return to Dashboard"
                onPress={() => router.push('/')}
                style={s.returnBtn}
              />
            </GlassCard>
          ) : loading ? (
            <View style={s.loadingContainer}>
              <ActivityIndicator size="large" color={colors.text.primary} />
              <Text style={s.loadingText}>Loading...</Text>
            </View>
          ) : (
            <>
              {/* Dropbox Integration Card */}
              <GlassCard style={s.integrationCard}>
                {/* Dropbox Header */}
                <View style={s.integrationHeader}>
                  <View style={s.integrationIcon}>
                    <Cloud size={28} strokeWidth={1.5} color={DROPBOX_BLUE} />
                  </View>
                  <View style={s.integrationInfo}>
                    <Text style={s.integrationName}>Dropbox</Text>
                    <Text style={s.integrationDesc}>
                      Sync construction plans and documents
                    </Text>
                  </View>
                  <View
                    style={[
                      s.statusBadge,
                      dropboxStatus.connected && s.statusConnected,
                    ]}
                  >
                    {dropboxStatus.connected ? (
                      <CheckCircle size={14} strokeWidth={2} color="#4ade80" />
                    ) : (
                      <XCircle size={14} strokeWidth={2} color={colors.text.muted} />
                    )}
                    <Text
                      style={[
                        s.statusText,
                        dropboxStatus.connected && s.statusTextConnected,
                      ]}
                    >
                      {dropboxStatus.connected ? 'Connected' : 'Not Connected'}
                    </Text>
                  </View>
                </View>

                {/* Connection Status Details */}
                {dropboxStatus.connected ? (
                  <View style={s.connectedSection}>
                    {/* Account Info */}
                    {dropboxStatus.account_email && (
                      <View style={s.accountInfo}>
                        <Text style={s.accountLabel}>CONNECTED ACCOUNT</Text>
                        <Text style={s.accountEmail}>{dropboxStatus.account_email}</Text>
                      </View>
                    )}

                    {/* Connected At */}
                    {dropboxStatus.connected_at && (
                      <View style={s.accountInfo}>
                        <Text style={s.accountLabel}>CONNECTED SINCE</Text>
                        <Text style={s.accountEmail}>
                          {new Date(dropboxStatus.connected_at).toLocaleDateString()}
                        </Text>
                      </View>
                    )}

                    {/* Disconnect Button */}
                    <GlassButton
                      title="Disconnect Dropbox"
                      icon={<Unlink size={18} strokeWidth={1.5} color={colors.status.error} />}
                      onPress={handleDisconnect}
                      loading={disconnecting}
                      style={s.disconnectButton}
                      textStyle={s.disconnectText}
                    />
                  </View>
                ) : (
                  <View style={s.connectSection}>
                    <Text style={s.connectDesc}>
                      Connect your Dropbox account to sync construction plans, blueprints, and
                      documents directly to your projects.
                    </Text>

                    {!showCodeInput ? (
                      <Pressable
                        onPress={handleConnectDropbox}
                        disabled={connecting}
                        style={({ pressed }) => [
                          s.dropboxButton,
                          pressed && s.dropboxButtonPressed,
                          connecting && s.dropboxButtonDisabled,
                        ]}
                      >
                        {connecting ? (
                          <ActivityIndicator size="small" color="#fff" />
                        ) : (
                          <>
                            <Cloud size={22} strokeWidth={2} color="#fff" />
                            <Text style={s.dropboxButtonText}>Connect to Dropbox</Text>
                            <ExternalLink size={16} strokeWidth={2} color="rgba(255,255,255,0.7)" />
                          </>
                        )}
                      </Pressable>
                    ) : (
                      <View style={s.codeInputSection}>
                        <Text style={s.codeInputLabel}>
                          After authorizing in Dropbox, paste the code below:
                        </Text>
                        <View style={s.codeInputRow}>
                          <TextInput
                            style={s.codeInput}
                            value={authCode}
                            onChangeText={setAuthCode}
                            placeholder="Paste authorization code"
                            placeholderTextColor={colors.text.subtle}
                            autoCapitalize="none"
                            autoCorrect={false}
                          />
                        </View>
                        <View style={s.codeButtonRow}>
                          <GlassButton
                            title="Cancel"
                            onPress={() => {
                              setShowCodeInput(false);
                              setAuthCode('');
                            }}
                            style={s.cancelCodeBtn}
                          />
                          <Pressable
                            onPress={handleCompleteAuth}
                            disabled={completingAuth || !authCode.trim()}
                            style={({ pressed }) => [
                              s.completeAuthButton,
                              pressed && s.dropboxButtonPressed,
                              (completingAuth || !authCode.trim()) && s.dropboxButtonDisabled,
                            ]}
                          >
                            {completingAuth ? (
                              <ActivityIndicator size="small" color="#fff" />
                            ) : (
                              <>
                                <Key size={18} strokeWidth={2} color="#fff" />
                                <Text style={s.dropboxButtonText}>Complete Connection</Text>
                              </>
                            )}
                          </Pressable>
                        </View>
                      </View>
                    )}
                  </View>
                )}
              </GlassCard>

              {/* WhatsApp Integration Card */}
              <GlassCard style={s.integrationCard}>
                <View style={s.integrationHeader}>
                  <View style={[s.integrationIcon, { backgroundColor: 'rgba(37, 211, 102, 0.1)' }]}>
                    <MessageCircle size={28} strokeWidth={1.5} color={WHATSAPP_GREEN} />
                  </View>
                  <View style={s.integrationInfo}>
                    <Text style={s.integrationName}>WhatsApp</Text>
                    <Text style={s.integrationDesc}>
                      {!whatsappStatus.platform_configured
                        ? 'WhatsApp integration is managed by Levelog. Contact support to enable.'
                        : !whatsappStatus.company_active
                        ? 'Connect WhatsApp to enable group messaging, site queries, and daily summaries.'
                        : 'Connected to WhatsApp Business'}
                    </Text>
                  </View>
                  <View
                    style={[
                      s.statusBadge,
                      whatsappStatus.company_active && s.statusConnected,
                    ]}
                  >
                    {whatsappStatus.company_active ? (
                      <CheckCircle size={14} strokeWidth={2} color="#4ade80" />
                    ) : (
                      <XCircle size={14} strokeWidth={2} color={colors.text.muted} />
                    )}
                    <Text
                      style={[
                        s.statusText,
                        whatsappStatus.company_active && s.statusTextConnected,
                      ]}
                    >
                      {whatsappStatus.company_active
                        ? 'Connected'
                        : whatsappStatus.platform_configured
                        ? 'Not Connected'
                        : 'Not Available'}
                    </Text>
                  </View>
                </View>

                {whatsappStatus.company_active ? (
                  <View style={s.connectedSection}>
                    <View style={s.accountInfo}>
                      <Text style={s.accountLabel}>YOUR LEVELOG ASSISTANT NUMBER</Text>
                      <Text style={s.whatsappNumber}>
                        {formatPhoneNumber(whatsappStatus.whatsapp_number)}
                      </Text>
                    </View>
                    <Text style={s.whatsappHint}>
                      Add this number to WhatsApp groups from each project page.
                    </Text>
                  </View>
                ) : whatsappStatus.platform_configured ? (
                  <View style={s.connectSection}>
                    <Text style={s.connectDesc}>
                      Activate WhatsApp to enable group messaging for your projects. Your team can
                      ask site questions and receive daily summaries directly in WhatsApp.
                    </Text>
                    <Pressable
                      onPress={handleActivateWhatsapp}
                      disabled={activatingWhatsapp}
                      style={({ pressed }) => [
                        s.whatsappButton,
                        pressed && s.dropboxButtonPressed,
                        activatingWhatsapp && s.dropboxButtonDisabled,
                      ]}
                    >
                      {activatingWhatsapp ? (
                        <ActivityIndicator size="small" color="#fff" />
                      ) : (
                        <>
                          <MessageCircle size={22} strokeWidth={2} color="#fff" />
                          <Text style={s.dropboxButtonText}>Activate WhatsApp</Text>
                        </>
                      )}
                    </Pressable>
                  </View>
                ) : null}
              </GlassCard>

              {/* Projects with Dropbox */}
              {dropboxStatus.connected && (
                <View style={s.projectsSection}>
                  <View style={s.sectionHeader}>
                    <Text style={s.sectionTitle}>Projects with Dropbox</Text>
                    <GlassButton
                      variant="icon"
                      icon={<RefreshCw size={18} strokeWidth={1.5} color={colors.text.primary} />}
                      onPress={fetchData}
                    />
                  </View>

                  {projectsWithDropbox.length > 0 ? (
                    <View style={s.projectsList}>
                      {projectsWithDropbox.map((project) => (
                        <GlassListItem
                          key={project._id || project.id}
                          onPress={() =>
                            router.push(`/projects/${project._id || project.id}/dropbox-settings`)
                          }
                          style={s.projectItem}
                        >
                          <IconPod size={40}>
                            <FolderOpen size={18} strokeWidth={1.5} color={DROPBOX_BLUE} />
                          </IconPod>
                          <View style={s.projectInfo}>
                            <Text style={s.projectName}>{project.name}</Text>
                            <Text style={s.projectFolder} numberOfLines={1}>
                              {project.dropbox_folder_path}
                            </Text>
                          </View>
                          <CheckCircle size={18} strokeWidth={1.5} color="#4ade80" />
                        </GlassListItem>
                      ))}
                    </View>
                  ) : (
                    <View style={s.emptyProjects}>
                      <FolderOpen size={40} strokeWidth={1} color={colors.text.subtle} />
                      <Text style={s.emptyText}>
                        No projects linked to Dropbox yet
                      </Text>
                      <Text style={s.emptySubtext}>
                        Go to a project's settings to enable Dropbox sync
                      </Text>
                    </View>
                  )}
                </View>
              )}

              {/* All Projects */}
              <View style={s.projectsSection}>
                <Text style={s.sectionTitle}>All Projects</Text>
                {projects.length > 0 ? (
                  <View style={s.projectsList}>
                    {projects.map((project) => (
                      <GlassListItem
                        key={project._id || project.id}
                        onPress={() =>
                          router.push(`/projects/${project._id || project.id}/dropbox-settings`)
                        }
                        style={s.projectItem}
                      >
                        <IconPod size={40}>
                          <FolderOpen
                            size={18}
                            strokeWidth={1.5}
                            color={project.dropbox_folder_path ? DROPBOX_BLUE : colors.text.muted}
                          />
                        </IconPod>
                        <View style={s.projectInfo}>
                          <Text style={s.projectName}>{project.name}</Text>
                          <Text style={s.projectFolder}>
                            {project.dropbox_folder_path || 'No Dropbox folder linked'}
                          </Text>
                        </View>
                        {project.dropbox_folder_path && (
                          <CheckCircle size={18} strokeWidth={1.5} color="#4ade80" />
                        )}
                      </GlassListItem>
                    ))}
                  </View>
                ) : (
                  <View style={s.emptyProjects}>
                    <Text style={s.emptyText}>No projects found</Text>
                    <GlassButton
                      title="Create Project"
                      onPress={() => router.push('/projects')}
                      style={s.createProjectBtn}
                    />
                  </View>
                )}
              </View>
            </>
          )}
        </ScrollView>
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
    marginBottom: spacing.xl,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  titleText: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
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
  accessDeniedCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  accessDeniedTitle: {
    fontSize: 22,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.md,
  },
  accessDeniedDesc: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 300,
    lineHeight: 22,
  },
  returnBtn: {
    marginTop: spacing.lg,
  },
  integrationCard: {
    marginBottom: spacing.xl,
  },
  integrationHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.lg,
  },
  integrationIcon: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.lg,
    backgroundColor: 'rgba(0, 97, 255, 0.1)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  integrationInfo: {
    flex: 1,
  },
  integrationName: {
    fontSize: 20,
    fontWeight: '600',
    color: colors.text.primary,
    marginBottom: 2,
  },
  integrationDesc: {
    fontSize: 14,
    color: colors.text.muted,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  statusConnected: {
    backgroundColor: 'rgba(74, 222, 128, 0.1)',
    borderColor: 'rgba(74, 222, 128, 0.3)',
  },
  statusText: {
    fontSize: 12,
    fontWeight: '500',
    color: colors.text.muted,
  },
  statusTextConnected: {
    color: '#4ade80',
  },
  connectedSection: {
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
    paddingTop: spacing.lg,
  },
  accountInfo: {
    marginBottom: spacing.md,
  },
  accountLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  accountEmail: {
    fontSize: 16,
    color: colors.text.primary,
  },
  disconnectButton: {
    marginTop: spacing.md,
    borderColor: 'rgba(248, 113, 113, 0.3)',
  },
  disconnectText: {
    color: colors.status.error,
  },
  connectSection: {
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
    paddingTop: spacing.lg,
  },
  connectDesc: {
    fontSize: 14,
    color: colors.text.secondary,
    lineHeight: 22,
    marginBottom: spacing.lg,
  },
  dropboxButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: DROPBOX_BLUE,
    borderRadius: borderRadius.lg,
    paddingVertical: spacing.md + 4,
    paddingHorizontal: spacing.xl,
    transition: 'all 0.2s ease',
  },
  dropboxButtonPressed: {
    opacity: 0.9,
    transform: [{ scale: 0.98 }],
  },
  dropboxButtonDisabled: {
    opacity: 0.6,
  },
  dropboxButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fff',
  },
  codeInputSection: {
    gap: spacing.md,
  },
  codeInputLabel: {
    fontSize: 14,
    color: colors.text.secondary,
    marginBottom: spacing.sm,
  },
  codeInputRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  codeInput: {
    flex: 1,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    borderRadius: borderRadius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    color: colors.text.primary,
    fontSize: 14,
    fontFamily: 'monospace',
  },
  codeButtonRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  cancelCodeBtn: {
    flex: 1,
    opacity: 0.7,
  },
  completeAuthButton: {
    flex: 2,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: '#4ade80',
    borderRadius: borderRadius.lg,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
  },
  projectsSection: {
    marginBottom: spacing.xl,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.md,
  },
  projectsList: {
    gap: spacing.sm,
  },
  projectItem: {
    gap: spacing.md,
    padding: spacing.md,
  },
  projectInfo: {
    flex: 1,
  },
  projectName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 2,
  },
  projectFolder: {
    fontSize: 13,
    color: colors.text.muted,
  },
  emptyProjects: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    gap: spacing.sm,
  },
  emptyText: {
    fontSize: 15,
    color: colors.text.muted,
  },
  emptySubtext: {
    fontSize: 13,
    color: colors.text.subtle,
    textAlign: 'center',
  },
  createProjectBtn: {
    marginTop: spacing.md,
  },
  whatsappButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    backgroundColor: WHATSAPP_GREEN,
    borderRadius: borderRadius.lg,
    paddingVertical: spacing.md + 4,
    paddingHorizontal: spacing.xl,
  },
  whatsappNumber: {
    fontSize: 24,
    fontWeight: '600',
    color: colors.text.primary,
    letterSpacing: 1,
  },
  whatsappHint: {
    fontSize: 13,
    color: colors.text.muted,
    marginTop: spacing.sm,
  },
});
}
