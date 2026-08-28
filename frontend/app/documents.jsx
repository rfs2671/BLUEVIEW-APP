import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Linking, Platform, Image as RNImage } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  FileText,
  File,
  Image,
  FileSpreadsheet,
  FileCode,
  Download,
  ExternalLink,
  FolderOpen,
  Folder,
  Building2,
  ChevronDown,
  RefreshCw,
  Cloud,
  Upload,
} from 'lucide-react-native';
import * as DocumentPicker from 'expo-document-picker';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod, GlassListItem } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import { GlassSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import CpNav from '../src/components/CpNav';
import { CP_NAV_CLEARANCE } from '../src/components/CpNav';
import OfflineNotice from '../src/components/OfflineNotice';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { projectsAPI, dropboxAPI } from '../src/utils/api';
import { settleFetch } from '../src/utils/offlineState';
import { cacheProjectList, readCachedProjectList } from '../src/utils/projectCache';
import {
  cacheDocList,
  readCachedDocList,
  ensureCachedDocFile,
  warmDocCache,
} from '../src/utils/docCache';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import {
  UNFILED, folderLabel, groupByFolder, collidingNames, isColliding,
  treeHeadline, COLLISION_NOTE,
} from '../src/utils/dropboxTree';
import { semantic, withAlpha } from '../src/styles/semanticColors';
import { useTheme } from '../src/context/ThemeContext';

// PDFViewer auto-resolves: .native.jsx on native, .jsx (web fallback) on web
import PDFViewer from '../src/components/PDFViewer';
import HeaderBrand from '../src/components/HeaderBrand';

const extOf = (fileName) => String(fileName || '').split('.').pop()?.toLowerCase() || '';
// PDFs are the only type with an offline story — everything else opens via
// Linking against a REMOTE url and cannot work without a connection.
const isPdf = (fileName) => extOf(fileName) === 'pdf';

// File type icon mapping
const getFileIcon = (fileName) => {
  const ext = fileName?.split('.').pop()?.toLowerCase();

  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'heic'].includes(ext)) {
    return { Icon: Image, color: '#f472b6' };
  }
  if (['pdf'].includes(ext)) {
    return { Icon: FileText, color: semantic.neutral };
  }
  if (['xls', 'xlsx', 'csv'].includes(ext)) {
    return { Icon: FileSpreadsheet, color: semantic.neutral };
  }
  if (['doc', 'docx', 'txt', 'rtf'].includes(ext)) {
    return { Icon: FileText, color: '#3b82f6' };
  }
  if (['dwg', 'dxf', 'skp'].includes(ext)) {
    return { Icon: FileCode, color: semantic.neutral };
  }
  return { Icon: File, color: '#94a3b8' };
};

const formatFileSize = (bytes) => {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

const formatDate = (dateStr) => {
  if (!dateStr) return 'Unknown';
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
};

export default function DocumentsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const isCp = user?.role === 'cp';

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [projects, setProjects] = useState([]);
  const insets = useSafeAreaInsets();
  const [selectedProject, setSelectedProject] = useState(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [files, setFiles] = useState([]);
  const [loadingFile, setLoadingFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [pdfViewerVisible, setPdfViewerVisible] = useState(false);
  const [selectedPdfFile, setSelectedPdfFile] = useState(null);
  // 'ok' | 'offline' | 'error', tracked separately for the project list and the
  // file list so a failure in either one never renders as "nothing exists".
  const [projectsState, setProjectsState] = useState('ok');
  const [filesState, setFilesState] = useState('ok');
  const offline = projectsState === 'offline' || filesState === 'offline';

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchProjects();
    }
  }, [isAuthenticated]);

  /**
   * Projects with a linked Dropbox folder — the only ones this screen can list
   * files for.
   *
   * THIS FILTER EMPTIED THE WHOLE SCREEN. It read `dropbox_enabled &&
   * dropbox_folder`, two fields create_project writes once (false and null)
   * and nothing has written since. So it matched NOTHING, for every user, and
   * the screen rendered "No projects have Dropbox folders linked yet" —
   * a sentence about the operator's configuration, produced by a bug.
   *
   * Linked-ness is `bool(dropbox_folder_path)`. One field, the one the linker
   * actually writes and the one ProjectResponse actually serves.
   */
  const dropboxOnly = (list) =>
    (Array.isArray(list) ? list : []).filter((p) => Boolean(p.dropbox_folder_path));

  const fetchProjects = async () => {
    setLoading(true);

    // Cache-first, so an offline user still gets a project to select instead of
    // "No projects have Dropbox folders linked yet" — which reads as a config
    // problem rather than a network one.
    const cached = dropboxOnly(await readCachedProjectList());
    let picked = null;
    if (cached.length) {
      setProjects(cached);
      picked = cached[0];
      setSelectedProject(picked);
    }

    const r = await settleFetch(() => projectsAPI.getAll());
    if (r.status === 'ok') {
      const projectList = Array.isArray(r.data) ? r.data : [];
      cacheProjectList(projectList);
      const dropboxProjects = dropboxOnly(projectList);
      setProjects(dropboxProjects);
      setProjectsState('ok');

      // Auto-select first project
      if (dropboxProjects.length > 0) {
        picked = dropboxProjects[0];
        setSelectedProject(picked);
      } else {
        picked = null;
        setSelectedProject(null);
      }
    } else {
      // Keep whatever the cache gave us — never fall back to an empty list.
      console.error('Failed to fetch projects:', r.error);
      setProjectsState(r.status);
    }

    if (picked) await fetchFiles(picked._id || picked.id);
    setLoading(false);
  };

  const fetchFiles = async (projectId) => {
    if (!projectId) return;
    const scopeKey = `docs:${projectId}`;
    setRefreshing(true);

    const cached = await readCachedDocList(scopeKey);
    if (cached.length) setFiles(cached);

    const r = await settleFetch(() => dropboxAPI.getProjectFiles(projectId));
    if (r.status === 'ok') {
      const list = Array.isArray(r.data?.files)
        ? r.data.files
        : Array.isArray(r.data) ? r.data : [];
      setFiles(list);
      setFilesState('ok');
      cacheDocList(scopeKey, list);
      // Fire-and-forget byte warm so these PDFs survive the next dead zone.
      warmDocCache(list.filter((f) => isPdf(f?.name)), { limit: 15 }).catch(() => {});
    } else if (r.error?.response?.status === 404) {
      // A real server answer — the empty state here is honest.
      setFiles([]);
      setFilesState('ok');
      cacheDocList(scopeKey, []);
      if (!selectedProject?.dropbox_folder_path) {
        toast.warning('Not Connected', 'This project does not have a Dropbox folder linked. Ask your admin to connect it.');
      }
    } else {
      // Any other failure KEEPS the cached list.
      console.error('Failed to fetch files:', r.error);
      setFilesState(r.status);
    }
    setRefreshing(false);
  };

  // Both numbers from THIS list. The sync response's recursive file_count is
  // about Dropbox, not about the rows below, and half a sentence from each
  // source is a sentence true of neither.
  const fileGroups = groupByFolder(files);
  const collisions = collidingNames(files);
  const headline = treeHeadline(files, selectedProject?.dropbox_last_synced);

  const handleProjectChange = (project) => {
    setSelectedProject(project);
    setShowProjectPicker(false);
    fetchFiles(project._id || project.id);
  };

  const handleRefresh = () => {
    if (selectedProject) {
      fetchFiles(selectedProject._id || selectedProject.id);
    }
  };

  const handleOpenFile = async (file) => {
    if (!selectedProject) return;

    const ext = extOf(file.name);
    if (ext === 'pdf') {
      // Prefer the copy already on disk. PDFViewer prefers `directUrl`, so
      // pointing that at the cached uri is the whole integration — and iOS'
      // WKWebView renders a local file:// through PDFKit with no network.
      const local = await ensureCachedDocFile({
        fileId: file?.id || file?._id,
        cacheVersion: file?.cache_version ?? 0,
        remoteUrl: file?.r2_url || file?.directUrl,
      });

      // Android can now render a cached file too — PDFViewer stages a local
      // pdf.js copy for `file://` sources. Android still takes the REMOTE
      // viewer while online, so the online path is byte-for-byte what it was;
      // drop the `|| offline` to prefer the cached copy there as well.
      if (local && (Platform.OS === 'ios' || offline)) {
        setSelectedPdfFile({ ...file, directUrl: local });
        setPdfViewerVisible(true);
        return;
      }

      if (offline) {
        toast.info(
          'Not saved on this device',
          'No saved copy of this document is on this device yet. Reconnect to load it.',
        );
        return;
      }

      // If file has r2_url, pass it directly instead of calling getFileUrl
      setSelectedPdfFile(file.r2_url ? { ...file, directUrl: file.r2_url } : file);
      setPdfViewerVisible(true);
      return;
    }

    // ⚠️ NON-PDF LIMIT: .docx/.xlsx hand a REMOTE url to another app. There is
    // no offline path for these, so don't let the tap fail silently.
    if (offline) {
      toast.info(
        'Not available offline',
        `${(ext || 'This file type').toUpperCase()} files open in another app over the network. Reconnect to open ${file.name}.`,
      );
      return;
    }

    setLoadingFile(file.path);
    try {
      const response = await dropboxAPI.getFileUrl(
        selectedProject._id || selectedProject.id,
        file.path
      );

      if (response.url) {
        const canOpen = await Linking.canOpenURL(response.url);
        if (canOpen) {
          await Linking.openURL(response.url);
          toast.success('Opening', `Opening ${file.name}`);
        } else {
          toast.error('Error', 'Could not open file');
        }
      }
    } catch (error) {
      console.error('Failed to get file URL:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not get file URL');
    } finally {
      setLoadingFile(null);
    }
  };

  const handleUploadFile = async () => {
    if (!selectedProject) {
      toast.warning('Select Project', 'Please select a project first');
      return;
    }
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: 'application/pdf',
        copyToCacheDirectory: true,
      });
      if (result.canceled) return;
      const file = result.assets?.[0];
      if (!file) return;

      setUploading(true);
      toast.info('Uploading', `Uploading ${file.name}...`);

      const formData = new FormData();
      if (Platform.OS === 'web') {
        const response = await fetch(file.uri);
        const blob = await response.blob();
        formData.append('file', blob, file.name);
      } else {
        formData.append('file', { uri: file.uri, name: file.name, type: 'application/pdf' });
      }

      const pid = selectedProject._id || selectedProject.id;
      await dropboxAPI.uploadFile(pid, formData);
      toast.success('Uploaded', `${file.name} uploaded`);
      handleRefresh();
    } catch (error) {
      console.error('Upload failed:', error);
      toast.error('Upload Error', error.response?.data?.detail || 'Could not upload file');
    } finally {
      setUploading(false);
    }
  };

  // CP goes back to /logbooks, admin goes to /
  const handleBack = () => {
    router.push(isCp ? '/logbooks' : '/');
  };

  const getProjectId = (project) => project?._id || project?.id;

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleBack}
            />
            <HeaderBrand />
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          // The clearance this nav actually needs, derived from its own
          // styles rather than a literal sized by hand. The INSET is added
          // here because CpNav cannot see it, and it is the term that was
          // missing: on 3-button navigation it is ~48 rather than ~24, which
          // is where the old hardcoded number went negative and the pill
          // covered the last row.
          contentContainerStyle={[
            s.scrollContent,
            { paddingBottom: insets.bottom + CP_NAV_CLEARANCE },
          ]}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>PROJECT</Text>
            <Text style={s.titleText}>Documents</Text>
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={70} borderRadiusValue={borderRadius.xl} style={s.mb16} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
            </>
          ) : projects.length === 0 ? (
            projectsState !== 'ok' ? (
              /* A failed load is NOT "nobody has linked a folder" — saying so
                 sends the user to their admin over a dead cell tower. */
              <OfflineNotice mode={projectsState} cachedCount={0} />
            ) : (
              /* No Projects with Dropbox */
              <GlassCard style={s.emptyCard}>
                <IconPod size={80} style={s.emptyIcon}>
                  <Cloud size={32} strokeWidth={1.5} color={colors.text.muted} />
                </IconPod>
                <Text style={s.emptyTitle}>No Documents Available</Text>
                <Text style={s.emptyText}>
                  No projects have Dropbox folders linked yet.{'\n'}
                  Contact your administrator to set up document access.
                </Text>
              </GlassCard>
            )
          ) : (
            <>
              {/* Project Selector */}
              <Pressable
                style={s.selectorCard}
                onPress={() => setShowProjectPicker(!showProjectPicker)}
              >
                <View style={s.selectorLeft}>
                  <Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />
                  <View>
                    <Text style={s.selectorLabel}>PROJECT</Text>
                    <Text style={s.selectorValue}>
                      {selectedProject?.name || 'Select project'}
                    </Text>
                  </View>
                </View>
                <ChevronDown
                  size={16}
                  strokeWidth={1.5}
                  color={colors.text.muted}
                  style={{ transform: [{ rotate: showProjectPicker ? '180deg' : '0deg' }] }}
                />
              </Pressable>

              {showProjectPicker && (
                <GlassCard style={s.dropdownCard}>
                  {projects.map((p) => (
                    <Pressable
                      key={getProjectId(p)}
                      style={[
                        s.dropdownItem,
                        getProjectId(p) === getProjectId(selectedProject) &&
                          s.dropdownItemActive,
                      ]}
                      onPress={() => handleProjectChange(p)}
                    >
                      <Text style={s.dropdownItemText}>{p.name}</Text>
                    </Pressable>
                  ))}
                </GlassCard>
              )}

              {/* Actions row */}
              {selectedProject && (
                <View style={s.refreshRow}>
                  {/* Never a bare count under an ambiguous label. */}
                  <Text style={s.fileCount}>{headline}</Text>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
                    {(user?.role === 'admin' || user?.role === 'owner') && (
                      <Pressable
                        style={[s.refreshBtn, { backgroundColor: 'rgba(59,130,246,0.15)', borderColor: 'rgba(59,130,246,0.3)', borderWidth: 1 }]}
                        onPress={handleUploadFile}
                        disabled={uploading}
                      >
                        <Upload size={14} strokeWidth={1.5} color="#3b82f6" />
                        <Text style={[s.refreshText, { color: '#3b82f6' }]}>
                          {uploading ? 'Uploading...' : 'Upload PDF'}
                        </Text>
                      </Pressable>
                    )}
                    <Pressable style={s.refreshBtn} onPress={handleRefresh}>
                      <RefreshCw
                        size={14}
                        strokeWidth={1.5}
                        color={colors.text.muted}
                        style={refreshing ? { opacity: 0.5 } : {}}
                      />
                      <Text style={s.refreshText}>
                        {refreshing ? 'Refreshing...' : 'Refresh'}
                      </Text>
                    </Pressable>
                  </View>
                </View>
              )}

              {/* Cached-vs-live disclosure, above the list it describes. */}
              {(filesState !== 'ok' || projectsState !== 'ok') && (
                <OfflineNotice
                  mode={filesState !== 'ok' ? filesState : projectsState}
                  cachedCount={files.length}
                  style={s.mb12}
                />
              )}

              {/* File List */}
              {files.length > 0 ? (
                fileGroups.map(([folderPath, groupFiles]) => (
                <View key={folderPath} style={s.folderGroup}>
                  <View style={s.folderGroupHeader}>
                    {/* A TOKEN, NOT THE DROPBOX BRAND HEX. This screen is one
                        of the 17 under tokens.test.cjs's palette discipline, and
                        the icon is a folder rather than a Dropbox mark -- the
                        brand blue was borrowed from files.jsx, which is not in
                        that scanned set. */}
                    <Folder size={14} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.folderGroupName} numberOfLines={1}>
                      {folderLabel(folderPath)}
                    </Text>
                    <Text style={s.folderGroupCount}>
                      {groupFiles.length} file{groupFiles.length === 1 ? '' : 's'}
                    </Text>
                  </View>
                  {folderPath !== UNFILED && folderLabel(folderPath) !== folderPath && (
                    <Text style={s.folderGroupPath} numberOfLines={1}>{folderPath}</Text>
                  )}
                {groupFiles.map((file, index) => {
                  const { Icon: FileIcon, color: iconColor } = getFileIcon(file.name);
                  const isLoading = loadingFile === file.path;

                  return (
                    <Pressable
                      key={file.path || index}
                      style={({ pressed }) => [
                        s.fileCard,
                        pressed && s.fileCardPressed,
                      ]}
                      onPress={() => handleOpenFile(file)}
                      disabled={isLoading}
                    >
                      <View style={[s.fileIcon, { backgroundColor: `${iconColor}15` }]}>
                        <FileIcon size={20} strokeWidth={1.5} color={iconColor} />
                      </View>
                      <View style={s.fileInfo}>
                        <Text style={s.fileName} numberOfLines={1}>
                          {file.name}
                        </Text>
                        <Text style={s.fileMeta}>
                          {formatFileSize(file.size)}
                          {file.modified ? ` • ${formatDate(file.modified)}` : ''}
                        </Text>
                        {/* Two rows sharing a filename are ONE object in R2 —
                            the sync key omits the folder. The tree renders them
                            in two places, so it must not also claim they are
                            two documents. */}
                        {isColliding(file, collisions) && (
                          <Text style={s.collisionNote}>{COLLISION_NOTE}</Text>
                        )}
                      </View>
                      <ExternalLink size={16} strokeWidth={1.5} color={colors.text.muted} />
                    </Pressable>
                  );
                })}
                </View>
                ))
              ) : selectedProject && filesState === 'ok' ? (
                /* "No Documents" ONLY when the server actually returned none. */
                <GlassCard style={s.emptyCard}>
                  <IconPod size={64} style={s.emptyIcon}>
                    <FolderOpen size={28} strokeWidth={1.5} color={colors.text.muted} />
                  </IconPod>
                  <Text style={s.emptyTitle}>No Documents</Text>
                  <Text style={s.emptyText}>
                    No documents have been uploaded to this project's Dropbox folder yet.
                  </Text>
                </GlassCard>
              ) : null}
            </>
          )}
        </ScrollView>

        {/* CP gets CpNav, everyone else gets FloatingNav */}
        {isCp ? <CpNav /> : <FloatingNav />}

        <PDFViewer
          visible={pdfViewerVisible}
          file={selectedPdfFile}
          projectId={selectedProject?._id || selectedProject?.id}
          onClose={() => { setPdfViewerVisible(false); setSelectedPdfFile(null); }}
        />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: { flex: 1 },
  folderGroup: {
    marginBottom: spacing.lg,
  },
  folderGroupHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
  folderGroupName: {
    flex: 1,
    ...typography.label,
    color: colors.text.secondary,
  },
  folderGroupCount: {
    fontSize: 12,
    color: colors.text.subtle,
  },
  folderGroupPath: {
    fontSize: 11,
    color: colors.text.subtle,
    marginBottom: spacing.sm,
  },
  collisionNote: {
    fontSize: 12,
    lineHeight: 16,
    color: colors.text.muted,
    marginTop: 4,
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
  scrollView: { flex: 1 },
  // paddingBottom is set INLINE at the ScrollView, from
  // insets.bottom + CP_NAV_CLEARANCE.
  scrollContent: { padding: spacing.lg },
  titleSection: { marginBottom: spacing.xl },
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
  mb16: { marginBottom: spacing.md },
  mb12: { marginBottom: spacing.sm + 4 },
  selectorCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  selectorLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  selectorLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: 2,
  },
  selectorValue: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  dropdownCard: { marginBottom: spacing.md, padding: 0, overflow: 'hidden' },
  dropdownItem: {
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: withAlpha('#ffffff', 0.05),
  },
  dropdownItemActive: { backgroundColor: 'rgba(59, 130, 246, 0.1)' },
  dropdownItemText: { fontSize: 15, color: colors.text.primary },
  refreshRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  fileCount: { fontSize: 13, color: colors.text.muted },
  refreshBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  refreshText: { fontSize: 13, color: colors.text.muted },
  fileCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  fileCardPressed: { opacity: 0.8 },
  fileIcon: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  fileInfo: { flex: 1 },
  fileName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 2,
  },
  fileMeta: { fontSize: 12, color: colors.text.muted },
  emptyCard: {
    alignItems: 'center',
    padding: spacing.xxl,
    gap: spacing.md,
  },
  emptyIcon: { marginBottom: spacing.sm },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    lineHeight: 22,
  },
});
}
