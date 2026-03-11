import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Linking,
  TextInput,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Cloud,
  FileText,
  Image,
  File,
  Download,
  Eye,
  RefreshCw,
  Search,
  Filter,
  Clock,
  HardDrive,
  FolderOpen,
  LogOut,
  CheckCircle,
  AlertCircle,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import GlassInput from '../../../src/components/GlassInput';
import { GlassSkeleton } from '../../../src/components/GlassSkeleton';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { dropboxAPI, projectsAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';
import { useTheme } from '../../../src/context/ThemeContext';


const DROPBOX_BLUE = '#0061FF';

// File type icons and colors
const getFileTypeInfo = (filename) => {
  const ext = filename.split('.').pop()?.toLowerCase();
  
  const typeMap = {
    pdf: { icon: FileText, color: '#ef4444', label: 'PDF' },
    doc: { icon: FileText, color: '#3b82f6', label: 'DOC' },
    docx: { icon: FileText, color: '#3b82f6', label: 'DOCX' },
    xls: { icon: FileText, color: '#22c55e', label: 'XLS' },
    xlsx: { icon: FileText, color: '#22c55e', label: 'XLSX' },
    png: { icon: Image, color: '#8b5cf6', label: 'PNG' },
    jpg: { icon: Image, color: '#8b5cf6', label: 'JPG' },
    jpeg: { icon: Image, color: '#8b5cf6', label: 'JPEG' },
    gif: { icon: Image, color: '#8b5cf6', label: 'GIF' },
    dwg: { icon: File, color: '#f59e0b', label: 'DWG' },
    dxf: { icon: File, color: '#f59e0b', label: 'DXF' },
  };

  return typeMap[ext] || { icon: File, color: colors.text.muted, label: ext?.toUpperCase() || 'FILE' };
};

// Format file size
const formatFileSize = (bytes) => {
  if (!bytes) return 'Unknown size';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

export default function ConstructionPlansScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [project, setProject] = useState(null);
  const [files, setFiles] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState('all'); // all, pdf, image, document
  const [lastSynced, setLastSynced] = useState(null);
  const [syncStatus, setSyncStatus] = useState('idle'); // idle, syncing, success, error

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
      const [projectData, filesData] = await Promise.all([
        projectsAPI.getById(projectId).catch(() => null),
        dropboxAPI.getProjectFiles(projectId).catch(() => []),
      ]);

      setProject(projectData);
      setFiles(Array.isArray(filesData) ? filesData : []);
      setLastSynced(projectData?.dropbox_last_synced);
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Load Error', 'Could not load files');
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setSyncStatus('syncing');
    try {
      await dropboxAPI.syncProject(projectId);
      const filesData = await dropboxAPI.getProjectFiles(projectId);
      setFiles(Array.isArray(filesData) ? filesData : []);
      setLastSynced(new Date().toISOString());
      setSyncStatus('success');
      toast.success('Synced', 'Files synchronized from Dropbox');
    } catch (error) {
      console.error('Failed to sync:', error);
      setSyncStatus('error');
      toast.error('Sync Error', error.response?.data?.detail || 'Could not sync files');
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncStatus('idle'), 3000);
    }
  };

  const handleViewFile = async (file) => {
    try {
      const { url } = await dropboxAPI.getFileUrl(projectId, file.path);
      if (url) {
        await Linking.openURL(url);
      } else {
        toast.error('Error', 'Could not get file URL');
      }
    } catch (error) {
      console.error('Failed to get file URL:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not open file');
    }
  };

  const handleDownloadFile = async (file) => {
    try {
      const { url } = await dropboxAPI.getFileUrl(projectId, file.path);
      if (url) {
        await Linking.openURL(url);
        toast.success('Download', 'File download started');
      }
    } catch (error) {
      console.error('Failed to download:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not download file');
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  // Filter files
  const filteredFiles = files.filter((file) => {
    // Search filter
    if (searchQuery && !file.name?.toLowerCase().includes(searchQuery.toLowerCase())) {
      return false;
    }

    // Type filter
    if (filterType !== 'all') {
      const ext = file.name?.split('.').pop()?.toLowerCase();
      if (filterType === 'pdf' && ext !== 'pdf') return false;
      if (filterType === 'image' && !['png', 'jpg', 'jpeg', 'gif'].includes(ext)) return false;
      if (filterType === 'document' && !['doc', 'docx', 'xls', 'xlsx'].includes(ext)) return false;
    }

    return true;
  });

  const filterOptions = [
    { key: 'all', label: 'All Files' },
    { key: 'pdf', label: 'PDFs' },
    { key: 'image', label: 'Images' },
    { key: 'document', label: 'Documents' },
  ];

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
            <Text style={s.titleLabel}>{project?.name || 'PROJECT'}</Text>
            <Text style={s.titleText}>Construction Plans</Text>
          </View>

          {loading ? (
            <View style={s.loadingContainer}>
              <GlassSkeleton width="100%" height={60} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} />
            </View>
          ) : !project?.dropbox_folder_path ? (
            <GlassCard style={s.notLinkedCard}>
              <Cloud size={48} strokeWidth={1} color={colors.text.muted} />
              <Text style={s.notLinkedTitle}>No Dropbox Folder Linked</Text>
              <Text style={s.notLinkedDesc}>
                Link a Dropbox folder to this project to view construction plans.
              </Text>
              <GlassButton
                title="Configure Dropbox"
                onPress={() => router.push(`/projects/${projectId}/dropbox-settings`)}
                style={s.configureBtn}
              />
            </GlassCard>
          ) : (
            <>
              {/* Sync Status Bar */}
              <View style={s.syncBar}>
                <View style={s.syncInfo}>
                  <View
                    style={[
                      s.syncIndicator,
                      syncStatus === 'syncing' && s.syncIndicatorSyncing,
                      syncStatus === 'success' && s.syncIndicatorSuccess,
                      syncStatus === 'error' && s.syncIndicatorError,
                    ]}
                  >
                    {syncStatus === 'syncing' ? (
                      <ActivityIndicator size="small" color={DROPBOX_BLUE} />
                    ) : syncStatus === 'success' ? (
                      <CheckCircle size={16} strokeWidth={2} color="#4ade80" />
                    ) : syncStatus === 'error' ? (
                      <AlertCircle size={16} strokeWidth={2} color="#f87171" />
                    ) : (
                      <Cloud size={16} strokeWidth={1.5} color={DROPBOX_BLUE} />
                    )}
                  </View>
                  <View>
                    <Text style={s.syncLabel}>
                      {syncStatus === 'syncing'
                        ? 'Syncing...'
                        : syncStatus === 'success'
                        ? 'Synced!'
                        : syncStatus === 'error'
                        ? 'Sync failed'
                        : 'Dropbox Connected'}
                    </Text>
                    <Text style={s.syncTime}>
                      {lastSynced
                        ? `Last synced ${new Date(lastSynced).toLocaleString()}`
                        : 'Never synced'}
                    </Text>
                  </View>
                </View>
                <GlassButton
                  variant="icon"
                  icon={
                    <RefreshCw
                      size={18}
                      strokeWidth={1.5}
                      color={colors.text.primary}
                    />
                  }
                  onPress={handleSync}
                  disabled={syncing}
                />
              </View>

              {/* Search and Filter */}
              <View style={s.searchRow}>
                <View style={s.searchContainer}>
                  <GlassInput
                    value={searchQuery}
                    onChangeText={setSearchQuery}
                    placeholder="Search files..."
                    leftIcon={<Search size={18} strokeWidth={1.5} color={colors.text.subtle} />}
                  />
                </View>
              </View>

              {/* Filter Tabs */}
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                style={s.filterScroll}
                contentContainerStyle={s.filterContainer}
              >
                {filterOptions.map((option) => (
                  <Pressable
                    key={option.key}
                    onPress={() => setFilterType(option.key)}
                    style={[
                      s.filterTab,
                      filterType === option.key && s.filterTabActive,
                    ]}
                  >
                    <Text
                      style={[
                        s.filterTabText,
                        filterType === option.key && s.filterTabTextActive,
                      ]}
                    >
                      {option.label}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>

              {/* Files Count */}
              <Text style={s.filesCount}>
                {filteredFiles.length} file{filteredFiles.length !== 1 ? 's' : ''}
              </Text>

              {/* Files List */}
              <View style={s.filesList}>
                {filteredFiles.length > 0 ? (
                  filteredFiles.map((file, index) => {
                    const typeInfo = getFileTypeInfo(file.name || '');
                    const FileIcon = typeInfo.icon;

                    return (
                      <Pressable
                        key={file.path || index}
                        style={({ pressed }) => [
                          s.fileItem,
                          pressed && s.fileItemPressed,
                        ]}
                        onPress={() => handleViewFile(file)}
                      >
                        {/* File Icon */}
                        <View
                          style={[
                            s.fileIconContainer,
                            { backgroundColor: `${typeInfo.color}15` },
                          ]}
                        >
                          <FileIcon size={22} strokeWidth={1.5} color={typeInfo.color} />
                          <Text style={[s.fileTypeLabel, { color: typeInfo.color }]}>
                            {typeInfo.label}
                          </Text>
                        </View>

                        {/* File Info */}
                        <View style={s.fileInfo}>
                          <Text style={s.fileName} numberOfLines={1}>
                            {file.name}
                          </Text>
                          <View style={s.fileMeta}>
                            <Text style={s.fileMetaText}>
                              {formatFileSize(file.size)}
                            </Text>
                            {file.modified && (
                              <>
                                <Text style={s.fileMetaDot}>•</Text>
                                <Text style={s.fileMetaText}>
                                  {new Date(file.modified).toLocaleDateString()}
                                </Text>
                              </>
                            )}
                          </View>
                        </View>

                        {/* Actions */}
                        <View style={s.fileActions}>
                          <Pressable
                            onPress={(e) => {
                              e.stopPropagation();
                              handleViewFile(file);
                            }}
                            style={s.fileActionBtn}
                          >
                            <Eye size={18} strokeWidth={1.5} color={colors.text.muted} />
                          </Pressable>
                          <Pressable
                            onPress={(e) => {
                              e.stopPropagation();
                              handleDownloadFile(file);
                            }}
                            style={s.fileActionBtn}
                          >
                            <Download size={18} strokeWidth={1.5} color={colors.text.muted} />
                          </Pressable>
                        </View>
                      </Pressable>
                    );
                  })
                ) : (
                  <View style={s.emptyFiles}>
                    <FolderOpen size={48} strokeWidth={1} color={colors.text.subtle} />
                    <Text style={s.emptyText}>
                      {searchQuery || filterType !== 'all'
                        ? 'No files match your search'
                        : 'No files in this folder'}
                    </Text>
                    <GlassButton
                      title="Sync from Dropbox"
                      icon={<RefreshCw size={16} strokeWidth={1.5} color={colors.text.primary} />}
                      onPress={handleSync}
                      loading={syncing}
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
    paddingVertical: spacing.md,
  },
  mb12: {
    marginBottom: spacing.sm,
  },
  notLinkedCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  notLinkedTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  notLinkedDesc: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 280,
  },
  configureBtn: {
    marginTop: spacing.md,
  },
  syncBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  syncInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  syncIndicator: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.full,
    backgroundColor: 'rgba(0, 97, 255, 0.1)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  syncIndicatorSyncing: {
    backgroundColor: 'rgba(0, 97, 255, 0.2)',
  },
  syncIndicatorSuccess: {
    backgroundColor: 'rgba(74, 222, 128, 0.2)',
  },
  syncIndicatorError: {
    backgroundColor: 'rgba(248, 113, 113, 0.2)',
  },
  syncLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  syncTime: {
    fontSize: 12,
    color: colors.text.muted,
  },
  searchRow: {
    marginBottom: spacing.md,
  },
  searchContainer: {
    flex: 1,
  },
  filterScroll: {
    marginBottom: spacing.md,
  },
  filterContainer: {
    gap: spacing.sm,
    paddingRight: spacing.lg,
  },
  filterTab: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  filterTabActive: {
    backgroundColor: 'rgba(255, 255, 255, 0.15)',
    borderColor: 'rgba(255, 255, 255, 0.3)',
  },
  filterTabText: {
    fontSize: 13,
    fontWeight: '500',
    color: colors.text.muted,
  },
  filterTabTextActive: {
    color: colors.text.primary,
  },
  filesCount: {
    fontSize: 13,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  filesList: {
    gap: spacing.sm,
  },
  fileItem: {
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
  fileItemPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.12)',
  },
  fileIconContainer: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  fileTypeLabel: {
    fontSize: 9,
    fontWeight: '700',
    marginTop: 2,
  },
  fileInfo: {
    flex: 1,
  },
  fileName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: 4,
  },
  fileMeta: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  fileMetaText: {
    fontSize: 12,
    color: colors.text.muted,
  },
  fileMetaDot: {
    marginHorizontal: spacing.xs,
    color: colors.text.subtle,
  },
  fileActions: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  fileActionBtn: {
    width: 36,
    height: 36,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyFiles: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 15,
    color: colors.text.muted,
    textAlign: 'center',
  },
});
}
