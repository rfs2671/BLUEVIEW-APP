import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Linking } from 'react-native';
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
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { projectsAPI, dropboxAPI } from '../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../src/styles/theme';

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
  return { Icon: File, color: colors.text.muted };
};

// Format file size
const formatFileSize = (bytes) => {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
};

// Format date
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
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  const [showProjectPicker, setShowProjectPicker] = useState(false);
  const [files, setFiles] = useState([]);
  const [loadingFile, setLoadingFile] = useState(null);

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  // Fetch projects on mount
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
      
      // Filter projects that have Dropbox enabled
      const dropboxProjects = projectList.filter(p => p.dropbox_enabled || p.dropbox_folder);
      setProjects(dropboxProjects);

      // Auto-select first project with Dropbox or user's assigned project
      if (dropboxProjects.length > 0) {
        // Check if user has assigned projects
        const userProjectIds = user?.assigned_projects || [];
        const assignedProject = dropboxProjects.find(p => 
          userProjectIds.includes(p._id || p.id)
        );
        
        const projectToSelect = assignedProject || dropboxProjects[0];
        setSelectedProject(projectToSelect);
        await fetchFiles(projectToSelect._id || projectToSelect.id);
      }
    } catch (error) {
      console.error('Failed to fetch projects:', error);
      toast.error('Load Error', 'Could not load projects');
    } finally {
      setLoading(false);
    }
  };

  const fetchFiles = async (projectId) => {
    if (!projectId) return;
    
    setRefreshing(true);
    try {
      const response = await dropboxAPI.getProjectFiles(projectId);
      setFiles(response.files || []);
      
      if (response.message && response.files?.length === 0) {
        // Show info message if there's a reason for no files
        if (response.message.includes('not connected')) {
          toast.info('Dropbox', 'Dropbox is not connected. Ask your admin to connect it.');
        }
      }
    } catch (error) {
      console.error('Failed to fetch files:', error);
      toast.error('Load Error', 'Could not load documents');
      setFiles([]);
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
    
    setLoadingFile(file.path);
    try {
      const response = await dropboxAPI.getFileUrl(
        selectedProject._id || selectedProject.id,
        file.path
      );
      
      if (response.url) {
        // Open in new tab/browser
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

  const getProjectId = (project) => project?._id || project?.id;

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
            <Text style={styles.titleLabel}>PROJECT</Text>
            <Text style={styles.titleText}>Documents</Text>
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={70} borderRadiusValue={borderRadius.xl} style={styles.mb16} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={styles.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={styles.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
            </>
          ) : projects.length === 0 ? (
            /* No Projects with Dropbox */
            <GlassCard style={styles.emptyCard}>
              <IconPod size={80} style={styles.emptyIcon}>
                <Cloud size={32} strokeWidth={1.5} color={colors.text.muted} />
              </IconPod>
              <Text style={styles.emptyTitle}>No Documents Available</Text>
              <Text style={styles.emptyText}>
                No projects have Dropbox folders linked yet.{'\n'}
                Contact your administrator to set up document access.
              </Text>
            </GlassCard>
          ) : (
            <>
              {/* Project Selector */}
              <Pressable
                style={styles.selectorCard}
                onPress={() => setShowProjectPicker(!showProjectPicker)}
              >
                <View style={styles.selectorContent}>
                  <IconPod size={44}>
                    <Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />
                  </IconPod>
                  <View>
                    <Text style={styles.selectorLabel}>SELECT PROJECT</Text>
                    <Text style={styles.selectorText}>
                      {selectedProject?.name || 'Choose a project'}
                    </Text>
                  </View>
                </View>
                <View style={styles.selectorRight}>
                  <GlassButton
                    variant="icon"
                    icon={<RefreshCw size={16} strokeWidth={1.5} color={colors.text.muted} />}
                    onPress={handleRefresh}
                    style={styles.refreshBtn}
                  />
                  <ChevronDown
                    size={20}
                    strokeWidth={1.5}
                    color={colors.text.muted}
                    style={showProjectPicker && styles.iconRotated}
                  />
                </View>
              </Pressable>

              {showProjectPicker && (
                <View style={styles.dropdown}>
                  {projects.map((p) => (
                    <Pressable
                      key={getProjectId(p)}
                      onPress={() => handleProjectChange(p)}
                      style={[
                        styles.dropdownItem,
                        getProjectId(selectedProject) === getProjectId(p) && styles.dropdownItemActive,
                      ]}
                    >
                      <FolderOpen size={16} strokeWidth={1.5} color={colors.text.muted} />
                      <Text
                        style={[
                          styles.dropdownText,
                          getProjectId(selectedProject) === getProjectId(p) && styles.dropdownTextActive,
                        ]}
                      >
                        {p.name}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              )}

              {/* Files Count */}
              {selectedProject && (
                <View style={styles.filesHeader}>
                  <View style={styles.filesCount}>
                    <FolderOpen size={14} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={styles.filesCountText}>
                      {files.length} document{files.length !== 1 ? 's' : ''}
                    </Text>
                  </View>
                  {refreshing && (
                    <Text style={styles.refreshingText}>Refreshing...</Text>
                  )}
                </View>
              )}

              {/* Files List */}
              {files.length > 0 ? (
                <View style={styles.filesList}>
                  {files.map((file, index) => {
                    const { Icon, color } = getFileIcon(file.name);
                    const isLoading = loadingFile === file.path;
                    
                    return (
                      <GlassListItem
                        key={file.id || file.path || index}
                        style={styles.fileItem}
                        onPress={() => handleOpenFile(file)}
                        disabled={isLoading}
                      >
                        <IconPod size={44} style={{ borderColor: color }}>
                          <Icon size={18} strokeWidth={1.5} color={color} />
                        </IconPod>
                        
                        <View style={styles.fileInfo}>
                          <Text style={styles.fileName} numberOfLines={1}>
                            {file.name}
                          </Text>
                          <View style={styles.fileMeta}>
                            <Text style={styles.fileSize}>
                              {formatFileSize(file.size)}
                            </Text>
                            <Text style={styles.fileDot}>•</Text>
                            <Text style={styles.fileDate}>
                              {formatDate(file.modified)}
                            </Text>
                          </View>
                        </View>

                        <View style={styles.fileActions}>
                          {isLoading ? (
                            <View style={styles.loadingIndicator}>
                              <Text style={styles.loadingText}>Opening...</Text>
                            </View>
                          ) : (
                            <View style={styles.actionButton}>
                              <ExternalLink size={18} strokeWidth={1.5} color={colors.text.primary} />
                            </View>
                          )}
                        </View>
                      </GlassListItem>
                    );
                  })}
                </View>
              ) : selectedProject && !refreshing ? (
                /* No Documents for Selected Project */
                <GlassCard style={styles.emptyCard}>
                  <IconPod size={64} style={styles.emptyIcon}>
                    <FolderOpen size={28} strokeWidth={1.5} color={colors.text.muted} />
                  </IconPod>
                  <Text style={styles.emptyTitle}>No Documents</Text>
                  <Text style={styles.emptyText}>
                    No documents have been uploaded to this project's Dropbox folder yet.
                  </Text>
                </GlassCard>
              ) : null}
            </>
          )}
        </ScrollView>

        <FloatingNav />
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
  mb16: {
    marginBottom: spacing.md,
  },
  mb12: {
    marginBottom: spacing.sm + 4,
  },
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
  selectorContent: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    flex: 1,
  },
  selectorRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  refreshBtn: {
    padding: spacing.sm,
  },
  selectorLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: 2,
  },
  selectorText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  iconRotated: {
    transform: [{ rotate: '180deg' }],
  },
  dropdown: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    marginBottom: spacing.md,
    overflow: 'hidden',
  },
  dropdownItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.md,
  },
  dropdownItemActive: {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
  },
  dropdownText: {
    fontSize: 15,
    color: colors.text.muted,
  },
  dropdownTextActive: {
    color: colors.text.primary,
  },
  filesHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  filesCount: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  filesCountText: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  refreshingText: {
    fontSize: 13,
    color: colors.text.muted,
    fontStyle: 'italic',
  },
  filesList: {
    gap: spacing.sm,
  },
  fileItem: {
    gap: spacing.md,
  },
  fileInfo: {
    flex: 1,
    gap: 4,
  },
  fileName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  fileMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  fileSize: {
    fontSize: 12,
    color: colors.text.muted,
  },
  fileDot: {
    fontSize: 12,
    color: colors.text.subtle,
  },
  fileDate: {
    fontSize: 12,
    color: colors.text.muted,
  },
  fileActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  actionButton: {
    padding: spacing.sm,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    borderRadius: borderRadius.md,
  },
  loadingIndicator: {
    padding: spacing.sm,
  },
  loadingText: {
    fontSize: 12,
    color: colors.text.muted,
    fontStyle: 'italic',
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  emptyIcon: {
    marginBottom: spacing.lg,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    lineHeight: 22,
    maxWidth: 280,
  },
});
