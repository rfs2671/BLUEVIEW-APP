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
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { dropboxAPI, projectsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

// Dropbox brand color
const DROPBOX_BLUE = '#0061FF';

export default function AdminIntegrationsScreen() {
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
      const [status, projectsData] = await Promise.all([
        dropboxAPI.getStatus().catch(() => ({ connected: false })),
        projectsAPI.getAll().catch(() => []),
      ]);
      setDropboxStatus(status);
      setProjects(Array.isArray(projectsData) ? projectsData : []);
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
      const { authorize_url } = await dropboxAPI.getAuthUrl();
      
      // Open Dropbox OAuth in browser
      const supported = await Linking.canOpenURL(authorize_url);
      if (supported) {
        await Linking.openURL(authorize_url);
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

  const projectsWithDropbox = projects.filter((p) => p.dropbox_folder_path);

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            <Text style={styles.logoText}>BLUEVIEW</Text>
          </View>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={styles.titleSection}>
            <Text style={styles.titleLabel}>ADMIN</Text>
            <Text style={styles.titleText}>Integrations</Text>
          </View>

          {!isAdmin ? (
            <GlassCard style={styles.accessDeniedCard}>
              <ShieldAlert size={56} strokeWidth={1} color={colors.status.error} />
              <Text style={styles.accessDeniedTitle}>Admin Access Required</Text>
              <Text style={styles.accessDeniedDesc}>
                Only administrators can manage integrations and connect external services.
              </Text>
              <GlassButton
                title="Return to Dashboard"
                onPress={() => router.push('/')}
                style={styles.returnBtn}
              />
            </GlassCard>
          ) : loading ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color={colors.text.primary} />
              <Text style={styles.loadingText}>Loading...</Text>
            </View>
          ) : (
            <>
              {/* Dropbox Integration Card */}
              <GlassCard style={styles.integrationCard}>
                {/* Dropbox Header */}
                <View style={styles.integrationHeader}>
                  <View style={styles.integrationIcon}>
                    <Cloud size={28} strokeWidth={1.5} color={DROPBOX_BLUE} />
                  </View>
                  <View style={styles.integrationInfo}>
                    <Text style={styles.integrationName}>Dropbox</Text>
                    <Text style={styles.integrationDesc}>
                      Sync construction plans and documents
                    </Text>
                  </View>
                  <View
                    style={[
                      styles.statusBadge,
                      dropboxStatus.connected && styles.statusConnected,
                    ]}
                  >
                    {dropboxStatus.connected ? (
                      <CheckCircle size={14} strokeWidth={2} color="#4ade80" />
                    ) : (
                      <XCircle size={14} strokeWidth={2} color={colors.text.muted} />
                    )}
                    <Text
                      style={[
                        styles.statusText,
                        dropboxStatus.connected && styles.statusTextConnected,
                      ]}
                    >
                      {dropboxStatus.connected ? 'Connected' : 'Not Connected'}
                    </Text>
                  </View>
                </View>

                {/* Connection Status Details */}
                {dropboxStatus.connected ? (
                  <View style={styles.connectedSection}>
                    {/* Account Info */}
                    {dropboxStatus.account_email && (
                      <View style={styles.accountInfo}>
                        <Text style={styles.accountLabel}>CONNECTED ACCOUNT</Text>
                        <Text style={styles.accountEmail}>{dropboxStatus.account_email}</Text>
                      </View>
                    )}

                    {/* Connected At */}
                    {dropboxStatus.connected_at && (
                      <View style={styles.accountInfo}>
                        <Text style={styles.accountLabel}>CONNECTED SINCE</Text>
                        <Text style={styles.accountEmail}>
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
                      style={styles.disconnectButton}
                      textStyle={styles.disconnectText}
                    />
                  </View>
                ) : (
                  <View style={styles.connectSection}>
                    <Text style={styles.connectDesc}>
                      Connect your Dropbox account to sync construction plans, blueprints, and
                      documents directly to your projects.
                    </Text>

                    {!showCodeInput ? (
                      <Pressable
                        onPress={handleConnectDropbox}
                        disabled={connecting}
                        style={({ pressed }) => [
                          styles.dropboxButton,
                          pressed && styles.dropboxButtonPressed,
                          connecting && styles.dropboxButtonDisabled,
                        ]}
                      >
                        {connecting ? (
                          <ActivityIndicator size="small" color="#fff" />
                        ) : (
                          <>
                            <Cloud size={22} strokeWidth={2} color="#fff" />
                            <Text style={styles.dropboxButtonText}>Connect to Dropbox</Text>
                            <ExternalLink size={16} strokeWidth={2} color="rgba(255,255,255,0.7)" />
                          </>
                        )}
                      </Pressable>
                    ) : (
                      <View style={styles.codeInputSection}>
                        <Text style={styles.codeInputLabel}>
                          After authorizing in Dropbox, paste the code below:
                        </Text>
                        <View style={styles.codeInputRow}>
                          <TextInput
                            style={styles.codeInput}
                            value={authCode}
                            onChangeText={setAuthCode}
                            placeholder="Paste authorization code"
                            placeholderTextColor={colors.text.subtle}
                            autoCapitalize="none"
                            autoCorrect={false}
                          />
                        </View>
                        <View style={styles.codeButtonRow}>
                          <GlassButton
                            title="Cancel"
                            onPress={() => {
                              setShowCodeInput(false);
                              setAuthCode('');
                            }}
                            style={styles.cancelCodeBtn}
                          />
                          <Pressable
                            onPress={handleCompleteAuth}
                            disabled={completingAuth || !authCode.trim()}
                            style={({ pressed }) => [
                              styles.completeAuthButton,
                              pressed && styles.dropboxButtonPressed,
                              (completingAuth || !authCode.trim()) && styles.dropboxButtonDisabled,
                            ]}
                          >
                            {completingAuth ? (
                              <ActivityIndicator size="small" color="#fff" />
                            ) : (
                              <>
                                <Key size={18} strokeWidth={2} color="#fff" />
                                <Text style={styles.dropboxButtonText}>Complete Connection</Text>
                              </>
                            )}
                          </Pressable>
                        </View>
                      </View>
                    )}
                  </View>
                )}
              </GlassCard>

              {/* Projects with Dropbox */}
              {dropboxStatus.connected && (
                <View style={styles.projectsSection}>
                  <View style={styles.sectionHeader}>
                    <Text style={styles.sectionTitle}>Projects with Dropbox</Text>
                    <GlassButton
                      variant="icon"
                      icon={<RefreshCw size={18} strokeWidth={1.5} color={colors.text.primary} />}
                      onPress={fetchData}
                    />
                  </View>

                  {projectsWithDropbox.length > 0 ? (
                    <View style={styles.projectsList}>
                      {projectsWithDropbox.map((project) => (
                        <Pressable
                          key={project._id || project.id}
                          onPress={() =>
                            router.push(`/projects/${project._id || project.id}/dropbox-settings`)
                          }
                          style={({ pressed }) => [
                            styles.projectItem,
                            pressed && styles.projectItemPressed,
                          ]}
                        >
                          <IconPod size={40}>
                            <FolderOpen size={18} strokeWidth={1.5} color={DROPBOX_BLUE} />
                          </IconPod>
                          <View style={styles.projectInfo}>
                            <Text style={styles.projectName}>{project.name}</Text>
                            <Text style={styles.projectFolder} numberOfLines={1}>
                              {project.dropbox_folder_path}
                            </Text>
                          </View>
                          <CheckCircle size={18} strokeWidth={1.5} color="#4ade80" />
                        </Pressable>
                      ))}
                    </View>
                  ) : (
                    <View style={styles.emptyProjects}>
                      <FolderOpen size={40} strokeWidth={1} color={colors.text.subtle} />
                      <Text style={styles.emptyText}>
                        No projects linked to Dropbox yet
                      </Text>
                      <Text style={styles.emptySubtext}>
                        Go to a project's settings to enable Dropbox sync
                      </Text>
                    </View>
                  )}
                </View>
              )}

              {/* All Projects */}
              <View style={styles.projectsSection}>
                <Text style={styles.sectionTitle}>All Projects</Text>
                {projects.length > 0 ? (
                  <View style={styles.projectsList}>
                    {projects.map((project) => (
                      <Pressable
                        key={project._id || project.id}
                        onPress={() =>
                          router.push(`/projects/${project._id || project.id}/dropbox-settings`)
                        }
                        style={({ pressed }) => [
                          styles.projectItem,
                          pressed && styles.projectItemPressed,
                        ]}
                      >
                        <IconPod size={40}>
                          <FolderOpen
                            size={18}
                            strokeWidth={1.5}
                            color={project.dropbox_folder_path ? DROPBOX_BLUE : colors.text.muted}
                          />
                        </IconPod>
                        <View style={styles.projectInfo}>
                          <Text style={styles.projectName}>{project.name}</Text>
                          <Text style={styles.projectFolder}>
                            {project.dropbox_folder_path || 'No Dropbox folder linked'}
                          </Text>
                        </View>
                        {project.dropbox_folder_path && (
                          <CheckCircle size={18} strokeWidth={1.5} color="#4ade80" />
                        )}
                      </Pressable>
                    ))}
                  </View>
                ) : (
                  <View style={styles.emptyProjects}>
                    <Text style={styles.emptyText}>No projects found</Text>
                    <GlassButton
                      title="Create Project"
                      onPress={() => router.push('/projects')}
                      style={styles.createProjectBtn}
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

const styles = StyleSheet.create({
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
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    transition: 'all 0.2s ease',
  },
  projectItemPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.12)',
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
});
