import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Linking, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
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
  Building2,
  ChevronDown,
  LogOut,
  RefreshCw,
  Cloud,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod, GlassListItem } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import { GlassSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import CpNav from '../src/components/CpNav';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { projectsAPI, dropboxAPI } from '../src/utils/api';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { useTheme } from '../src/context/ThemeContext';

// Conditional PDF viewer import
const PDFViewer = Platform.OS === 'web'
  ? require('../src/components/PDFViewerWeb').default
  : require('../src/components/PDFViewer').default;

// File type icon mapping
const getFileIcon = (fileName) => {
  const ext = fileName?.split('.').pop()?.toLowerCase();

  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'heic'].includes(ext)) {
    return { Icon: Image, color: '#f472b6' };
  }
  if (['pdf'].includes(ext)) {
    return { Icon: FileText, color: '#ef4444' };
  }
  if (['xls', 'xlsx', 'csv'].includes(ext)) {
    return { Icon: FileSpreadsheet, color: '#22c55e' };
  }
  if (['doc', 'docx', 'txt', 'rtf'].includes(ext)) {
    return { Icon: FileText, color: '#3b82f6' };
  }
  if (['dwg', 'dxf', 'skp'].includes(ext)) {
    return { Icon: FileCode, color: '#f59e0b' };
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
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const isCp = user?.role === 'cp';

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [files, setFiles] = useState([]);
  const [loadingFile, setLoadingFile] = useState(null);
  const [pdfViewerVisible, setPdfViewerVisible] = useState(false);
  const [selectedPdfFile, setSelectedPdfFile] = useState(null);

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

  const fetchProjects = async () => {
    setLoading(true);
    try {
      const projectsData = await projectsAPI.getAll();
      const projectList = Array.isArray(projectsData) ? projectsData : [];

      // Filter to projects with Dropbox enabled
      const dropboxProjects = projectList.filter(
        (p) => p.dropbox_enabled && p.dropbox_folder
      );
      setProjects(dropboxProjects);

      // Auto-select first project
      if (dropboxProjects.length > 0) {
        setSelectedProject(dropboxProjects[0]);
        await fetchFiles(dropboxProjects[0]._id || dropboxProjects[0].id);
      }
    } catch (error) {
      console.error('Failed to fetch projects:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchFiles = async (projectId) => {
    if (!projectId) return;
    setRefreshing(true);
    try {
      const response = await dropboxAPI.getProjectFiles(projectId);
      setFiles(Array.isArray(response?.files) ? response.files : Array.isArray(response) ? response : []);
    } catch (error) {
      console.error('Failed to fetch files:', error);
      if (error.response?.status === 404) {
        setFiles([]);
        if (!selectedProject?.dropbox_folder) {
          toast.warning('Not Connected', 'This project does not have a Dropbox folder linked. Ask your admin to connect it.');
        }
      }
    } finally {
      setRefreshing(false);
    }
  };

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

    const ext = file.name?.split('.').pop()?.toLowerCase();
    if (ext === 'pdf') {
      setSelectedPdfFile(file);
      setPdfViewerVisible(true);
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

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
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
            <Text style={s.logoText}>BLUEVIEW</Text>
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

              {/* Refresh button */}
              {selectedProject && (
                <View style={s.refreshRow}>
                  <Text style={s.fileCount}>
                    {files.length} file{files.length !== 1 ? 's' : ''}
                  </Text>
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
              )}

              {/* File List */}
              {files.length > 0 ? (
                files.map((file, index) => {
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
                      </View>
                      <ExternalLink size={16} strokeWidth={1.5} color={colors.text.muted} />
                    </Pressable>
                  );
                })
              ) : selectedProject ? (
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
  scrollView: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 120 },
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
    borderBottomColor: 'rgba(255,255,255,0.05)',
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
