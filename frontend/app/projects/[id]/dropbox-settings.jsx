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
  Smartphone,
  Check,
  Square,
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
import { semantic, withAlpha } from '../../../src/styles/semanticColors';
import OfflineNotice from '../../../src/components/OfflineNotice';
import { readCachedProject } from '../../../src/utils/projectCache';
import { settleFetch } from '../../../src/utils/offlineState';

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

  // Site device visibility — list top-level subfolders under the
  // project's linked Dropbox folder, let admin pick which ones the
  // kiosk role can see. Empty selection = kiosk sees nothing.
  const [siteDeviceSubfolders, setSiteDeviceSubfolders] = useState([]);
  const [siteDeviceSelected, setSiteDeviceSelected] = useState([]);
  const [loadingSiteVisibility, setLoadingSiteVisibility] = useState(false);
  const [savingSiteVisibility, setSavingSiteVisibility] = useState(false);

  // 'ok' | 'offline' | 'error'. Critical here: offline, dropboxAPI.getStatus()
  // fails and `{connected:false}` used to render "Dropbox Not Connected" —
  // a flat lie about the company's integration.
  const [fetchState, setFetchState] = useState('ok');

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
      const [projectRes, statusRes] = await Promise.all([
        settleFetch(() => projectsAPI.getById(projectId)),
        settleFetch(() => dropboxAPI.getStatus()),
      ]);

      // Offline fallback for the project — cacheProject() already stored it.
      let projectData = projectRes.data;
      if (projectRes.status !== 'ok') {
        console.warn('Project fetch failed, using device cache:', projectRes.error?.message);
        projectData = await readCachedProject(projectId);
      }
      const status =
        statusRes.status === 'ok' && statusRes.data
          ? statusRes.data
          : { connected: false };

      // Worst status of the two wins — a reachable server is required before
      // ANY of this screen's claims (connected / not connected) are honest.
      const netState =
        projectRes.status !== 'ok'
          ? projectRes.status
          : statusRes.status !== 'ok'
            ? statusRes.status
            : 'ok';
      setFetchState(netState);

      setProject(projectData);
      setDropboxStatus(status);

      if (netState === 'ok' && projectData?.dropbox_folder_path) {
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

        // Load site-device visibility settings (admin-only endpoint —
        // non-admins get 403 which we swallow silently).
        if (user?.role === 'admin' || user?.role === 'owner') {
          fetchSiteDeviceVisibility();
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

  const fetchSiteDeviceVisibility = async () => {
    if (!projectId) return;
    setLoadingSiteVisibility(true);
    try {
      const data = await dropboxAPI.getSiteDeviceSubfolders(projectId);
      setSiteDeviceSubfolders(Array.isArray(data?.subfolders) ? data.subfolders : []);
      setSiteDeviceSelected(Array.isArray(data?.selected) ? data.selected : []);
    } catch (e) {
      console.warn('Site device visibility load failed:', e?.message);
      setSiteDeviceSubfolders([]);
      setSiteDeviceSelected([]);
    } finally {
      setLoadingSiteVisibility(false);
    }
  };

  const toggleSiteSubfolder = (name) => {
    if (!isAdmin) return;
    setSiteDeviceSelected((prev) => {
      const low = (name || '').toLowerCase();
      const has = prev.some((s) => s.toLowerCase() === low);
      return has
        ? prev.filter((s) => s.toLowerCase() !== low)
        : [...prev, name];
    });
  };

  const handleSaveSiteVisibility = async () => {
    if (!isAdmin) return;
    setSavingSiteVisibility(true);
    try {
      await dropboxAPI.setSiteDeviceSubfolders(projectId, siteDeviceSelected);
      toast.success(
        'Saved',
        siteDeviceSelected.length === 0
          ? 'Site device will see no files'
          : `Site device visibility updated (${siteDeviceSelected.length} folder(s))`
      );
    } catch (e) {
      console.error('Save site visibility failed:', e);
      toast.error('Error', e.response?.data?.detail || 'Could not save');
    } finally {
      setSavingSiteVisibility(false);
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
    // THE CLASS, not the one control. '' and '/' both mean "the whole Dropbox"
    // to the server; refusing them here means a new call site cannot
    // reintroduce a root link by passing a falsy path.
    const target = (folderPath || '').trim();
    if (!target || target === '/') {
      toast.error('Pick a folder', 'A project cannot be linked to all of Dropbox.');
      return;
    }
    try {
      await dropboxAPI.linkToProject(projectId, target);
      setSelectedFolder(target);
      setShowFolderPicker(false);
      toast.success('Linked', 'Dropbox folder linked successfully');

      // Trigger initial sync
      handleSync();
      // Refresh available subfolders so the site-device card updates.
      if (isAdmin) fetchSiteDeviceVisibility();
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
            {/* Don't sit on "Loading..." forever once the load has finished */}
            <Text style={s.titleText}>
              {project?.name || (loading ? 'Loading...' : 'Project unavailable')}
            </Text>
          </View>

          {loading ? (
            <View style={s.loadingContainer}>
              <GlassSkeleton width="100%" height={200} borderRadiusValue={borderRadius.xxl} />
            </View>
          ) : fetchState !== 'ok' ? (
            // NEVER fall through to "Dropbox Not Connected" here: getStatus()
            // failing is not the same as the company having no Dropbox.
            <>
              <OfflineNotice
                mode={fetchState}
                cachedCount={project ? 1 : 0}
                detail={
                  fetchState === 'error'
                    ? 'Could not read Dropbox settings. This is NOT a statement that Dropbox is disconnected.'
                    : 'Offline — Dropbox settings cannot be read or changed. This is NOT a statement that Dropbox is disconnected; linking, syncing and visibility changes all need a connection.'
                }
              />

              {/* What the device already knows about this project, read-only. */}
              {project?.dropbox_folder_path ? (
                <GlassCard style={s.folderCard}>
                  <Text style={s.cardLabel}>LINKED FOLDER (SAVED COPY)</Text>
                  <View style={s.selectedFolder}>
                    <IconPod size={44}>
                      <FolderOpen size={20} strokeWidth={1.5} color={DROPBOX_BLUE} />
                    </IconPod>
                    <View style={s.folderInfo}>
                      <Text style={s.folderPath}>{project.dropbox_folder_path}</Text>
                      <Text style={s.folderMeta}>
                        {project.dropbox_last_synced
                          ? `Last synced ${new Date(project.dropbox_last_synced).toLocaleString()}`
                          : 'Sync time unknown'}
                      </Text>
                    </View>
                  </View>
                </GlassCard>
              ) : null}

              <GlassButton
                title="Retry"
                icon={<RefreshCw size={16} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={fetchData}
                style={s.retryBtn}
              />
            </>
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

                  {/* Site Device Visibility — admin-only, per-project allowlist */}
                  {selectedFolder && isAdmin && (
                    <GlassCard style={s.siteVizCard}>
                      <View style={s.siteVizHeader}>
                        <Smartphone size={16} strokeWidth={1.5} color={colors.text.muted} />
                        <Text style={s.cardLabel}>SITE DEVICE VISIBILITY</Text>
                      </View>
                      <Text style={s.siteVizDesc}>
                        Pick which subfolders the on-site kiosk can see. Admins and
                        CPs always see the full project folder. Leave empty to block
                        the kiosk from all files.
                      </Text>

                      {loadingSiteVisibility ? (
                        <ActivityIndicator
                          size="small"
                          color={colors.text.primary}
                          style={s.foldersLoading}
                        />
                      ) : siteDeviceSubfolders.length === 0 ? (
                        <Text style={s.noFolders}>
                          No subfolders found directly under the linked folder.
                          Create subfolders in Dropbox (e.g. "Approved Plans",
                          "Access Agreements"), then reload this page.
                        </Text>
                      ) : (
                        <View style={s.siteVizList}>
                          {siteDeviceSubfolders.map((name) => {
                            const checked = siteDeviceSelected.some(
                              (s) => s.toLowerCase() === name.toLowerCase()
                            );
                            return (
                              <Pressable
                                key={name}
                                onPress={() => toggleSiteSubfolder(name)}
                                style={({ pressed }) => [
                                  s.siteVizRow,
                                  pressed && s.siteVizRowPressed,
                                ]}
                              >
                                {checked ? (
                                  <View style={s.checkboxChecked}>
                                    <Check size={14} strokeWidth={2} color="#fff" />
                                  </View>
                                ) : (
                                  <View style={s.checkboxEmpty}>
                                    <Square size={14} strokeWidth={1.5} color={colors.text.muted} />
                                  </View>
                                )}
                                <Folder size={16} strokeWidth={1.5} color={DROPBOX_BLUE} />
                                <Text style={s.siteVizName}>{name}</Text>
                              </Pressable>
                            );
                          })}
                        </View>
                      )}

                      <View style={s.siteVizActions}>
                        <GlassButton
                          title={
                            savingSiteVisibility
                              ? 'Saving...'
                              : siteDeviceSelected.length === 0
                                ? 'Save (kiosk sees nothing)'
                                : `Save (${siteDeviceSelected.length} selected)`
                          }
                          onPress={handleSaveSiteVisibility}
                          loading={savingSiteVisibility}
                          disabled={loadingSiteVisibility}
                        />
                      </View>
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

                  {/* Select Current Folder.

                      ROOT IS NOT A PROJECT FOLDER. At depth 0 currentPath is
                      '', and the server reads both '' and '/' as "link to the
                      root of the Dropbox scope". The sync lists RECURSIVELY, so
                      a root link copies every file the company owns into this
                      one project's files and onto R2. Open a folder first. */}
                  {currentPath ? (
                    <Pressable
                      onPress={() => handleSelectFolder(currentPath)}
                      style={({ pressed }) => [
                        s.selectCurrentBtn,
                        pressed && s.selectCurrentBtnPressed,
                      ]}
                    >
                      <CheckCircle size={18} strokeWidth={1.5} color="#4ade80" />
                      <Text style={s.selectCurrentText}>Select This Folder</Text>
                    </Pressable>
                  ) : (
                    <View style={s.selectRootBlocked}>
                      <Text style={s.selectRootBlockedText}>
                        Open a folder to link it. A project cannot be linked to
                        all of Dropbox — every file your company stores would be
                        copied into this project.
                      </Text>
                    </View>
                  )}

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
  retryBtn: {
    alignSelf: 'flex-start',
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
    backgroundColor: 'rgba(0, 97, 255, 0.1)', /* brand: Dropbox - intentional, not a token */
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
    backgroundColor: withAlpha('#ffffff', 0.12),
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
  siteVizCard: {
    marginTop: spacing.md,
    padding: spacing.lg,
  },
  siteVizHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  siteVizDesc: {
    fontSize: 13,
    color: colors.text.muted,
    lineHeight: 18,
    marginBottom: spacing.md,
  },
  siteVizList: {
    gap: spacing.xs,
    marginBottom: spacing.md,
  },
  siteVizRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.sm,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  siteVizRowPressed: {
    opacity: 0.7,
  },
  siteVizName: {
    fontSize: 14,
    color: colors.text.primary,
    flex: 1,
  },
  checkboxChecked: {
    width: 20,
    height: 20,
    borderRadius: 4,
    backgroundColor: '#4ade80',
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxEmpty: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: colors.glass.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  siteVizActions: {
    marginTop: spacing.xs,
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
  selectRootBlocked: {
    padding: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    marginBottom: spacing.md,
  },
  selectRootBlockedText: {
    fontSize: typography.sizes.sm,
    color: colors.text.muted,
    lineHeight: 18,
  },
  selectCurrentBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    padding: spacing.md,
    backgroundColor: semantic.verifiedBg,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: semantic.verifiedBorder,
    marginBottom: spacing.md,
    transition: 'all 0.2s ease',
  },
  selectCurrentBtnPressed: {
    backgroundColor: semantic.verifiedBg,
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
    backgroundColor: withAlpha('#ffffff', 0.12),
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
