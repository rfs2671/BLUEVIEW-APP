import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Linking } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Building2,
  FileText,
  File,
  Image,
  FileSpreadsheet,
  FileCode,
  ExternalLink,
  FolderOpen,
  LogOut,
  RefreshCw,
  Cloud,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import SiteNav from '../../src/components/SiteNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { dropboxAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

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

export default function SiteDocumentsScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [files, setFiles] = useState([]);
  const [loadingFile, setLoadingFile] = useState(null);

  // Redirect if not authenticated or not in site mode
  useEffect(() => {
    if (!authLoading) {
      if (!isAuthenticated) {
        router.replace('/login');
      } else if (!siteMode) {
        router.replace('/');
      }
    }
  }, [isAuthenticated, authLoading, siteMode]);

  // Fetch data
  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchFiles();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  const fetchFiles = async () => {
    if (!siteProject?.id) return;
    
    setLoading(true);
    try {
      const response = await dropboxAPI.getProjectFiles(siteProject.id);
      setFiles(response.files || []);
      
      if (response.message && response.files?.length === 0) {
        if (response.message.includes('not connected')) {
          toast.info('Dropbox', 'Dropbox is not connected for this project.');
        }
      }
    } catch (error) {
      console.error('Failed to fetch files:', error);
      toast.error('Load Error', 'Could not load documents');
      setFiles([]);
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchFiles();
    setRefreshing(false);
    toast.success('Refreshed', 'Documents updated');
  };

  const handleOpenFile = async (file) => {
    if (!siteProject?.id) return;
    
    setLoadingFile(file.path);
    try {
      const response = await dropboxAPI.getFileUrl(siteProject.id, file.path);
      
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

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <View style={styles.siteBadge}>
              <Building2 size={14} strokeWidth={1.5} color="#4ade80" />
              <Text style={styles.siteBadgeText}>SITE MODE</Text>
            </View>
            <Text style={styles.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
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
            <View style={styles.titleRow}>
              <Text style={styles.titleLabel}>PROJECT</Text>
              <GlassButton
                variant="icon"
                icon={<RefreshCw size={16} strokeWidth={1.5} color={colors.text.muted} />}
                onPress={handleRefresh}
                style={styles.refreshBtn}
              />
            </View>
            <Text style={styles.titleText}>Documents</Text>
          </View>

          {/* Files Count */}
          {!loading && (
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

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={styles.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={styles.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
            </>
          ) : files.length > 0 ? (
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
          ) : (
            <GlassCard style={styles.emptyCard}>
              <IconPod size={64} style={styles.emptyIcon}>
                <Cloud size={28} strokeWidth={1.5} color={colors.text.muted} />
              </IconPod>
              <Text style={styles.emptyTitle}>No Documents</Text>
              <Text style={styles.emptyText}>
                No documents have been uploaded to this project's folder yet.
                {'\n\n'}
                Contact your administrator if you need document access.
              </Text>
            </GlassCard>
          )}
        </ScrollView>

        <SiteNav />
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
    flex: 1,
  },
  siteBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(74, 222, 128, 0.3)',
  },
  siteBadgeText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#4ade80',
    letterSpacing: 0.5,
  },
  projectName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    flex: 1,
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
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  refreshBtn: {
    padding: spacing.xs,
  },
  titleText: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
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
  mb12: {
    marginBottom: spacing.sm + 4,
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
    fontSize: 18,
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
