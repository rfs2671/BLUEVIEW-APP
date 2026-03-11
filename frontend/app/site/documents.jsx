import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Home,
  Building2,
  LogOut,
  FileText,
  File,
  FolderOpen,
  Download,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { GlassSkeleton } from '../../src/components/GlassSkeleton';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import apiClient from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

const dropboxAPI = {
  getProjectFiles: async (projectId) => {
    const response = await apiClient.get(`/api/projects/${projectId}/dropbox-files`);
    return response.data;
  },
};

const getFileIcon = (filename) => {
  const ext = filename.split('.').pop()?.toLowerCase();
  if (['pdf'].includes(ext)) return { Icon: FileText, color: '#ef4444' };
  if (['doc', 'docx'].includes(ext)) return { Icon: FileText, color: '#3b82f6' };
  if (['xls', 'xlsx'].includes(ext)) return { Icon: FileText, color: '#22c55e' };
  return { Icon: File, color: '#94a3b8' };
};

const formatFileSize = (bytes) => {
  if (!bytes) return 'Unknown';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export default function SiteDocumentsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [files, setFiles] = useState([]);

  useEffect(() => {
  if (!authLoading && isAuthenticated !== undefined) {
    if (!isAuthenticated) {
      router.replace('/login');
    } else if (isAuthenticated && !siteMode && siteProject === null) {
      // Only redirect if we're sure siteMode resolved
      router.replace('/');
    }
  }
}, [isAuthenticated, authLoading, siteMode, siteProject]);
  
  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchDocuments();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  const fetchDocuments = async () => {
    if (!siteProject?.id) return;

    setLoading(true);
    try {
      const result = await dropboxAPI.getProjectFiles(siteProject.id);
      setFiles(result.files || []);
    } catch (error) {
      console.error('Failed to fetch documents:', error);
      toast.error('Error', 'Could not load documents');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<Home size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/site')}
            />
            <View style={s.siteBadge}>
              <Building2 size={14} strokeWidth={1.5} color="#4ade80" />
              <Text style={s.siteBadgeText}>SITE DEVICE</Text>
            </View>
            <Text style={s.projectName} numberOfLines={1}>
              {siteProject?.name || 'Project'}
            </Text>
          </View>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
        </View>

        {/* Title */}
        <View style={s.titleSection}>
          <Text style={s.titleLabel}>PROJECT</Text>
          <Text style={s.titleText}>Documents</Text>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {loading ? (
            <View style={s.loadingContainer}>
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
            </View>
          ) : files.length > 0 ? (
            <View style={s.filesList}>
              {files.map((file, index) => {
                const { Icon, color } = getFileIcon(file.name);
                return (
                  <GlassCard key={index} style={s.fileCard}>
                    <View style={s.fileIcon}>
                      <Icon size={24} strokeWidth={1.5} color={color} />
                    </View>
                    <View style={s.fileInfo}>
                      <Text style={s.fileName} numberOfLines={1}>
                        {file.name}
                      </Text>
                      <Text style={s.fileSize}>{formatFileSize(file.size)}</Text>
                    </View>
                    <Download size={20} strokeWidth={1.5} color={colors.text.muted} />
                  </GlassCard>
                );
              })}
            </View>
          ) : (
            <GlassCard style={s.emptyCard}>
              <FolderOpen size={48} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyText}>No Documents</Text>
              <Text style={s.emptySubtext}>Documents will appear here when added</Text>
            </GlassCard>
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
  },
  headerLeft: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  siteBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(74, 222, 128, 0.3)',
  },
  siteBadgeText: {
    ...typography.label,
    fontSize: 9,
    color: '#4ade80',
    letterSpacing: 1,
  },
  projectName: {
    fontSize: 16,
    fontWeight: '400',
    color: colors.text.primary,
    flex: 1,
  },
  titleSection: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  titleText: {
    fontSize: 32,
    fontWeight: '200',
    color: colors.text.primary,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
  },
  loadingContainer: {
    gap: spacing.md,
  },
  filesList: {
    gap: spacing.md,
  },
  fileCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    padding: spacing.lg,
  },
  fileIcon: {
    width: 48,
    height: 48,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.glass.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  fileInfo: {
    flex: 1,
  },
  fileName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  fileSize: {
    fontSize: 13,
    color: colors.text.muted,
    marginTop: spacing.xs,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl * 2,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.muted,
  },
  emptySubtext: {
    fontSize: 14,
    color: colors.text.subtle,
  },
});
}
