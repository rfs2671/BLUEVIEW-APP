import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Switch,
  ActivityIndicator,
  Image,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Cloud,
  FolderOpen,
  Folder,
  ChevronRight,
  ChevronLeft,
  RefreshCw,
  CheckCircle,
  Clock,
  FileText,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import { GlassSkeleton } from '../../../src/components/GlassSkeleton';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { dropboxAPI, projectsAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import HeaderBrand from '../../../src/components/HeaderBrand';

const DROPBOX_BLUE = '#0061FF';

export default function ProjectDropboxSettingsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [project, setProject] = useState(null);
  const [dropboxStatus, setDropboxStatus] = useState({ connected: false });
  const [dropboxEnabled, setDropboxEnabled] = useState(false);
  const [selectedFolder, setSelectedFolder] = useState(null);
  const [lastSynced, setLastSynced] = useState(null);
  const [fileCount, setFileCount] = useState(0);

  // Folder browser state
  const [showFolderPicker, setShowFolderPicker] = useState(false);
  const [folders, setFolders] = useState([]);
  const [currentPath, setCurrentPath] = useState('');
  const [loadingFolders, setLoadingFolders] = useState(false);

  // Check if user is admin
  const isAdmin = user?.role === 'admin';

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

  const fetchData = async () => {
    setLoading(true);
    try {
      const [projectData, status] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        dropboxAPI.getStatus().catch(() => ({ connected: false })),
      ]);

      setProject(projectData);
      setDropboxStatus(status);

      if (projectData?.dropbox_folder_path) {
        setDropboxEnabled(true);
        setSelectedFolder(projectData.dropbox_folder_path);
        setLastSynced(projectData.dropbox_last_synced);

        // Get file count
        try {
          const files = await dropboxAPI.getProjectFiles(projectId);
          setFileCount(Array.isArray(files) ? files.length : 0);
        } catch (e) {
          setFileCount(0);
        }
      }
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Load Error', 'Could not load project settings');
    } finally {
      setLoading(false);
    }
  };

  const fetchFolders = async (path = '') => {
    setLoadingFolders(true);
    try {
      const foldersData = await dropboxAPI.getFolders(path);
      setFolders(Array.isArray(foldersData) ? foldersData : []);
      setCurrentPath(path);
    } catch (error) {
      console.error('Failed to fetch folders:', error);
      toast.error('Error', 'Could not load Dropbox folders');
      setFolders([]);
    } finally {
      setLoadingFolders(false);
    }
  };

  const handleToggleDropbox = async (enabled) => {
    setDropboxEnabled(enabled);
    if (enabled && !selectedFolder) {
      setShowFolderPicker(true);
      fetchFolders('');
    } else if (!enabled) {
      // Disable dropbox for this project
      try {
        await dropboxAPI.linkToProject(projectId, null);
        setSelectedFolder(null);
        toast.success('Disabled', 'Dropbox sync disabled for this project');
      } catch (error) {
        toast.error('Error', 'Could not disable Dropbox sync');
        setDropboxEnabled(true);
      }
    }
  };

  const handleSelectFolder = async (folderPath) => {
    try {
      await dropboxAPI.linkToProject(projectId, folderPath);
      setSelectedFolder(folderPath);
      setShowFolderPicker(false);
      toast.success('Linked', 'Dropbox folder linked successfully');
      
      // Trigger initial sync
      handleSync();
    } catch (error) {
      console.error('Failed to link folder:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not link folder');
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      await dropboxAPI.syncProject(projectId);
      setLastSynced(new Date().toISOString());
      
      // Refresh file count
      const files = await dropboxAPI.getProjectFiles(projectId);
      setFileCount(Array.isArray(files) ? files.length : 0);
      
      toast.success('Synced', 'Files synchronized from Dropbox');
    } catch (error) {
      console.error('Failed to sync:', error);
      toast.error('Sync Error', error.response?.data?.detail || 'Could not sync files');
    } finally {
      setSyncing(false);
    }
  };

  const navigateToFolder = (path) => {
    fetchFolders(path);
  };

  const navigateUp = () => {
    const parentPath = currentPath.split('/').slice(0, -1).join('/');
    fetchFolders(parentPath);
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
            <Text style={s.titleLabel}>PROJECT SETTINGS</Text>
            <Text style={s.titleText}>{project?.name || 'Loading...'}</Text>
          </View>

          {loading ? (
            <View style={s.loadingContainer}>
              <GlassSkeleton width="100%" height={200} borderRadiusValue={borderRadius.xxl} />
            </View>
          ) : !dropboxStatus.connected ? (
            <GlassCard style={s.notConnectedCard}>
              <Cloud size={48} strokeWidth={1} color={colors.text.muted} />
              <Text style={s.notConnectedTitle}>Dropbox Not Connected</Text>
              <Text style={s.notConnectedDesc}>
                Connect your Dropbox account in Admin Settings to enable file sync.
              </Text>
              <GlassButton
                title="Go to Admin Settings"
                onPress={() => router.push('/admin/integrations')}
                style={s.goToAdminBtn}
              />
            </GlassCard>
          ) : (
            <>
              {/* Enable Toggle */}
              <GlassCard style={s.toggleCard}>
                <View style={s.toggleRow}>
                  <View style={s.toggleInfo}>
                    <View style={s.toggleIcon}>
                      <Cloud size={24} strokeWidth={1.5} color={DROPBOX_BLUE} />
                    </View>
                    <View>
                      <Text style={s.toggleTitle}>Enable Dropbox</Text>
                      <Text style={s.toggleDesc}>Sync files for this project</Text>
                    </View>
                  </View>
                  <Switch
                    value={dropboxEnabled}
                    onValueChange={isAdmin ? handleToggleDropbox : undefined}
                    disabled={!isAdmin}
                    trackColor={{ false: colors.glass.background, true: DROPBOX_BLUE }}
                    thumbColor="#fff"
                  />
                </View>
                {!isAdmin && (
                  <Text style={s.adminOnlyHint}>Admin access required to modify settings</Text>
                )}
              </GlassCard>

              {/* Folder Selection */}
              {dropboxEnabled && (
                <>
                  <GlassCard style={s.folderCard}>
                    <Text style={s.cardLabel}>LINKED FOLDER</Text>
                    
                    {selectedFolder ? (
                      <Pressable
                        onPress={isAdmin ? () => {
                          setShowFolderPicker(true);
                          fetchFolders(selectedFolder);
                        } : undefined}
                        disabled={!isAdmin}
                        style={({ pressed }) => [
                          s.selectedFolder,
                          pressed && isAdmin && s.selectedFolderPressed,
                        ]}
                      >
                        <IconPod size={44}>
                          <FolderOpen size={20} strokeWidth={1.5} color={DROPBOX_BLUE} />
                        </IconPod>
                        <View style={s.folderInfo}>
                          <Text style={s.folderPath}>{selectedFolder}</Text>
                          <Text style={s.folderMeta}>{fileCount} files synced</Text>
                        </View>
                        {isAdmin && <ChevronRight size={20} strokeWidth={1.5} color={colors.text.muted} />}
                      </Pressable>
                    ) : isAdmin ? (
                      <GlassButton
                        title="Select Folder"
                        icon={<Folder size={18} strokeWidth={1.5} color={colors.text.primary} />}
                        onPress={() => {
                          setShowFolderPicker(true);
                          fetchFolders('');
                        }}
                      />
                    ) : (
                      <Text style={s.noFolderText}>No folder linked yet</Text>
                    )}
                  </GlassCard>

                  {/* Sync Status */}
                  {selectedFolder && (
                    <GlassCard style={s.syncCard}>
                      <View style={s.syncHeader}>
                        <Text style={s.cardLabel}>SYNC STATUS</Text>
                        <GlassButton
                          title={syncing ? 'Syncing...' : 'Sync Now'}
                          icon={
                            <RefreshCw
                              size={16}
                              strokeWidth={1.5}
                              color={colors.text.primary}
                              style={syncing && s.spinningIcon}
                            />
                          }
                          onPress={handleSync}
                          loading={syncing}
                          disabled={syncing}
                        />
                      </View>

                      <View style={s.syncStats}>
                        <View style={s.syncStat}>
                          <Clock size={18} strokeWidth={1.5} color={colors.text.muted} />
                          <View>
                            <Text style={s.syncStatLabel}>Last Synced</Text>
                            <Text style={s.syncStatValue}>
                              {lastSynced
                                ? new Date(lastSynced).toLocaleString()
                                : 'Never'}
                            </Text>
                          </View>
                        </View>
                        <View style={s.syncStat}>
                          <FileText size={18} strokeWidth={1.5} color={colors.text.muted} />
                          <View>
                            <Text style={s.syncStatLabel}>Files</Text>
                            <Text style={s.syncStatValue}>{fileCount}</Text>
                          </View>
                        </View>
                      </View>

                      {/* View Files Button */}
                      <GlassButton
                        title="View Construction Plans"
                        icon={<FileText size={18} strokeWidth={1.5} color={colors.text.primary} />}
                        onPress={() => router.push(`/projects/${projectId}/construction-plans`)}
                        style={s.viewFilesBtn}
                      />
                    </GlassCard>
                  )}
                </>
              )}

              {/* Folder Picker Modal - Admin only */}
              {showFolderPicker && isAdmin && (
                <GlassCard style={s.folderPicker}>
                  <View style={s.folderPickerHeader}>
                    <Text style={s.folderPickerTitle}>Select Folder</Text>
                    <GlassButton
                      variant="icon"
                      icon={<ChevronLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
                      onPress={() => setShowFolderPicker(false)}
                    />
                  </View>

                  {/* Current Path */}
                  <View style={s.currentPathRow}>
                    {currentPath && (
                      <Pressable onPress={navigateUp} style={s.backBtn}>
                        <ChevronLeft size={18} strokeWidth={1.5} color={colors.text.muted} />
                        <Text style={s.backText}>Back</Text>
                      </Pressable>
                    )}
                    <Text style={s.currentPathText}>
                      {currentPath || '/ (Root)'}
                    </Text>
                  </View>

                  {/* Select Current Folder */}
                  <Pressable
                    onPress={() => handleSelectFolder(currentPath || '/')}
                    style={({ pressed }) => [
                      s.selectCurrentBtn,
                      pressed && s.selectCurrentBtnPressed,
                    ]}
                  >
                    <CheckCircle size={18} strokeWidth={1.5} color="#4ade80" />
                    <Text style={s.selectCurrentText}>Select This Folder</Text>
                  </Pressable>

                  {/* Folder List */}
                  {loadingFolders ? (
                    <ActivityIndicator
                      size="small"
                      color={colors.text.primary}
                      style={s.foldersLoading}
                    />
                  ) : (
                    <View style={s.foldersList}>
                      {folders.map((folder, index) => (
                        <Pressable
                          key={folder.path || index}
                          onPress={() => navigateToFolder(folder.path)}
                          style={({ pressed }) => [
                            s.folderItem,
                            pressed && s.folderItemPressed,
                          ]}
                        >
                          <Folder size={18} strokeWidth={1.5} color={DROPBOX_BLUE} />
                          <Text style={s.folderName}>{folder.name}</Text>
                          <ChevronRight size={16} strokeWidth={1.5} color={colors.text.subtle} />
                        </Pressable>
                      ))}
                      {folders.length === 0 && (
                        <Text style={s.noFolders}>No subfolders</Text>
                      )}
                    </View>
                  )}
                </GlassCard>
              )}
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
    fontSize: 36,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -0.5,
  },
  loadingContainer: {
    paddingVertical: spacing.xl,
  },
  notConnectedCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  notConnectedTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  notConnectedDesc: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 280,
  },
  goToAdminBtn: {
    marginTop: spacing.md,
  },
  toggleCard: {
    marginBottom: spacing.md,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  toggleInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  toggleIcon: {
    width: 48,
    height: 48,
    borderRadius: borderRadius.lg,
    backgroundColor: 'rgba(0, 97, 255, 0.1)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  toggleTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  toggleDesc: {
    fontSize: 13,
    color: colors.text.muted,
  },
  adminOnlyHint: {
    fontSize: 12,
    color: colors.text.subtle,
    fontStyle: 'italic',
    marginTop: spacing.sm,
  },
  noFolderText: {
    fontSize: 14,
    color: colors.text.muted,
    fontStyle: 'italic',
  },
  folderCard: {
    marginBottom: spacing.md,
  },
  cardLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  selectedFolder: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    transition: 'all 0.2s ease',
  },
  selectedFolderPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.12)',
  },
  folderInfo: {
    flex: 1,
  },
  folderPath: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 2,
  },
  folderMeta: {
    fontSize: 13,
    color: colors.text.muted,
  },
  syncCard: {
    marginBottom: spacing.md,
  },
  syncHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  spinningIcon: {
    // Animation would go here
  },
  syncStats: {
    flexDirection: 'row',
    gap: spacing.lg,
    marginBottom: spacing.lg,
  },
  syncStat: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    flex: 1,
  },
  syncStatLabel: {
    fontSize: 12,
    color: colors.text.muted,
  },
  syncStatValue: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  viewFilesBtn: {
    marginTop: spacing.sm,
  },
  folderPicker: {
    marginTop: spacing.md,
  },
  folderPickerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  folderPickerTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
  },
  currentPathRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  backBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
  },
  backText: {
    fontSize: 13,
    color: colors.text.muted,
  },
  currentPathText: {
    fontSize: 13,
    color: colors.text.secondary,
    flex: 1,
  },
  selectCurrentBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    padding: spacing.md,
    backgroundColor: 'rgba(74, 222, 128, 0.1)',
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: 'rgba(74, 222, 128, 0.3)',
    marginBottom: spacing.md,
    transition: 'all 0.2s ease',
  },
  selectCurrentBtnPressed: {
    backgroundColor: 'rgba(74, 222, 128, 0.2)',
  },
  selectCurrentText: {
    fontSize: 14,
    fontWeight: '500',
    color: '#4ade80',
  },
  foldersLoading: {
    paddingVertical: spacing.xl,
  },
  foldersList: {
    gap: spacing.xs,
  },
  folderItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.md,
    transition: 'all 0.2s ease',
  },
  folderItemPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.12)',
  },
  folderName: {
    flex: 1,
    fontSize: 14,
    color: colors.text.primary,
  },
  noFolders: {
    textAlign: 'center',
    color: colors.text.muted,
    paddingVertical: spacing.lg,
  },
});
}
