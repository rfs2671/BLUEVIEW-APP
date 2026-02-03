import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Modal,
  Alert,
  Platform,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  MapPin,
  Users,
  Building2,
  QrCode,
  ClipboardList,
  FileText,
  Settings,
  Nfc,
  ChevronRight,
  HardHat,
  Plus,
  Trash2,
  X,
  Wifi,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { projectsAPI, checkinsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

export default function ProjectDetailScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [project, setProject] = useState(null);
  const [stats, setStats] = useState({
    onSiteWorkers: 0,
    subcontractors: 0,
    subcontractorCount: 0,
  });
  const [workersByCompany, setWorkersByCompany] = useState([]);
  
  // NFC management
  const [showAddNfcModal, setShowAddNfcModal] = useState(false);
  const [nfcTagId, setNfcTagId] = useState('');
  const [nfcLocation, setNfcLocation] = useState('');
  const [addingNfc, setAddingNfc] = useState(false);

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) {
      fetchData();
    }
  }, [isAuthenticated, projectId]);

  const fetchData = async () => {
    try {
      const projectData = await projectsAPI.getById(projectId);
      setProject(projectData);

      // Fetch active check-ins for this project
      try {
        const activeCheckins = await checkinsAPI.getActiveByProject(projectId);
        const workers = Array.isArray(activeCheckins) ? activeCheckins : [];
        
        // Group workers by company
        const grouped = workers.reduce((acc, worker) => {
          const company = worker.company || 'Unassigned';
          if (!acc[company]) {
            acc[company] = [];
          }
          acc[company].push(worker);
          return acc;
        }, {});

        const companiesArray = Object.entries(grouped).map(([name, workers]) => ({
          name,
          workers,
        }));

        setWorkersByCompany(companiesArray);
        setStats({
          onSiteWorkers: workers.length,
          subcontractors: companiesArray.length,
          subcontractorCount: companiesArray.length,
        });
      } catch (e) {
        setStats({ onSiteWorkers: 0, subcontractors: 0, subcontractorCount: 0 });
        setWorkersByCompany([]);
      }
    } catch (error) {
      console.error('Failed to fetch project:', error);
      toast.error('Error', 'Could not load project details');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const onRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const handleAddNfcTag = async () => {
    if (!nfcTagId.trim() || !nfcLocation.trim()) {
      toast.error('Error', 'Please enter tag ID and location');
      return;
    }

    setAddingNfc(true);
    try {
      await projectsAPI.addNfcTag(projectId, {
        tag_id: nfcTagId,
        location_description: nfcLocation,
      });

      toast.success('Added', 'NFC tag registered successfully');
      setNfcTagId('');
      setNfcLocation('');
      setShowAddNfcModal(false);
      await fetchData(); // Refresh to show new tag
    } catch (error) {
      console.error('Failed to add NFC tag:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not add NFC tag');
    } finally {
      setAddingNfc(false);
    }
  };

  const handleDeleteNfcTag = (tagId) => {
    const confirmDelete = async () => {
      try {
        await projectsAPI.deleteNfcTag(projectId, tagId);
        toast.success('Deleted', 'NFC tag removed');
        await fetchData();
      } catch (error) {
        console.error('Failed to delete NFC tag:', error);
        toast.error('Error', 'Could not delete NFC tag');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Remove this NFC tag?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Remove NFC Tag', 'Are you sure?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const quickActions = [
    { title: 'Check-In', icon: QrCode, path: `/checkin?projectId=${projectId}`, color: '#3b82f6' },
    { title: 'Daily Log', icon: ClipboardList, path: `/daily-log?projectId=${projectId}`, color: '#8b5cf6' },
    { title: 'Report Settings', icon: Settings, path: `/project/${projectId}/report-settings`, color: '#f59e0b' },
  ];

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={styles.loadingText}>Loading project...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  const nfcTags = project?.nfc_tags || [];

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
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
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text.primary} />
          }
        >
          {/* Project Header */}
          <GlassCard style={styles.projectHeader}>
            <View style={styles.projectTitleRow}>
              <View style={styles.projectInfo}>
                <Text style={styles.projectName}>{project?.name || 'Project'}</Text>
                <View style={styles.locationRow}>
                  <MapPin size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={styles.locationText}>{project?.location || project?.address || 'No location'}</Text>
                </View>
              </View>
              <View style={styles.qrBadge}>
                <QrCode size={20} strokeWidth={1.5} color={colors.text.primary} />
              </View>
            </View>
          </GlassCard>

          {/* Stats Row */}
          <View style={styles.statsRow}>
            <StatCard style={styles.statCard}>
              <IconPod style={styles.statIcon}>
                <Users size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={styles.statValue}>{stats.onSiteWorkers}</Text>
              <Text style={styles.statLabel}>ON SITE</Text>
            </StatCard>
            <StatCard style={styles.statCard}>
              <IconPod style={styles.statIcon}>
                <Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={styles.statValue}>{stats.subcontractors}</Text>
              <Text style={styles.statLabel}>COMPANIES</Text>
            </StatCard>
            <StatCard style={styles.statCard}>
              <IconPod style={styles.statIcon}>
                <Wifi size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={styles.statValue}>{nfcTags.length}</Text>
              <Text style={styles.statLabel}>NFC TAGS</Text>
            </StatCard>
          </View>

          {/* Quick Actions */}
          <Text style={styles.sectionLabel}>QUICK ACTIONS</Text>
          <View style={styles.actionsGrid}>
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <Pressable
                  key={action.title}
                  onPress={() => router.push(action.path)}
                  style={({ pressed }) => [
                    styles.actionCard,
                    pressed && styles.actionCardPressed,
                  ]}
                >
                  <View style={[styles.actionIcon, { backgroundColor: `${action.color}20` }]}>
                    <Icon size={24} strokeWidth={1.5} color={action.color} />
                  </View>
                  <Text style={styles.actionTitle}>{action.title}</Text>
                </Pressable>
              );
            })}
          </View>

          {/* NFC Tags Section - Admin Only */}
          {isAdmin && (
            <>
              <View style={styles.sectionHeader}>
                <Text style={styles.sectionLabel}>NFC CHECK-IN TAGS</Text>
                <GlassButton
                  title="Add Tag"
                  icon={<Plus size={16} color={colors.text.primary} />}
                  onPress={() => setShowAddNfcModal(true)}
                />
              </View>
              
              {nfcTags.length > 0 ? (
                <View style={styles.nfcTagsList}>
                  {nfcTags.map((tag) => (
                    <GlassCard key={tag.tag_id} style={styles.nfcTagCard}>
                      <View style={styles.nfcTagHeader}>
                        <Wifi size={20} strokeWidth={1.5} color="#10b981" />
                        <View style={styles.nfcTagInfo}>
                          <Text style={styles.nfcTagId}>{tag.tag_id}</Text>
                          <Text style={styles.nfcTagLocation}>{tag.location || 'Check-In Point'}</Text>
                        </View>
                        <Pressable
                          onPress={() => handleDeleteNfcTag(tag.tag_id)}
                          style={styles.deleteBtn}
                        >
                          <Trash2 size={16} color={colors.status.error} />
                        </Pressable>
                      </View>
                    </GlassCard>
                  ))}
                </View>
              ) : (
                <GlassCard style={styles.emptyNfcCard}>
                  <Nfc size={40} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={styles.emptyNfcText}>No NFC tags registered</Text>
                  <Text style={styles.emptyNfcSubtext}>Add NFC tags for worker check-in</Text>
                </GlassCard>
              )}
            </>
          )}

          {/* On-Site Workers */}
          <Text style={styles.sectionLabel}>ON-SITE WORKERS</Text>
          {workersByCompany.length > 0 ? (
            workersByCompany.map((company) => (
              <GlassCard key={company.name} style={styles.companyCard}>
                <View style={styles.companyHeader}>
                  <Building2 size={18} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={styles.companyName}>{company.name}</Text>
                  <View style={styles.workerCount}>
                    <Text style={styles.workerCountText}>{company.workers.length}</Text>
                  </View>
                </View>
                <View style={styles.workerTags}>
                  {company.workers.map((worker, idx) => (
                    <View key={idx} style={styles.workerTag}>
                      <Text style={styles.workerTagName}>{worker.name || worker.worker_name}</Text>
                      <Text style={styles.workerTagTrade}>{worker.trade || 'Worker'}</Text>
                    </View>
                  ))}
                </View>
              </GlassCard>
            ))
          ) : (
            <GlassCard style={styles.emptyCard}>
              <Users size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={styles.emptyText}>No workers on site</Text>
              <Text style={styles.emptySubtext}>Workers will appear here when they check in</Text>
            </GlassCard>
          )}
        </ScrollView>

        {/* Add NFC Tag Modal */}
        <Modal
          visible={showAddNfcModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowAddNfcModal(false)}
        >
          <View style={styles.modalOverlay}>
            <Pressable style={styles.modalBackdrop} onPress={() => setShowAddNfcModal(false)} />
            <View style={styles.modalContent}>
              <GlassCard variant="modal" style={styles.modalCard}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>Add NFC Tag</Text>
                  <Pressable onPress={() => setShowAddNfcModal(false)}>
                    <X size={24} color={colors.text.primary} />
                  </Pressable>
                </View>

                <Text style={styles.modalDesc}>
                  Tap an NFC tag or enter its ID manually to register it for check-ins.
                </Text>

                <View style={styles.modalForm}>
                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>TAG ID</Text>
                    <GlassInput
                      value={nfcTagId}
                      onChangeText={setNfcTagId}
                      placeholder="Enter or scan NFC tag ID"
                    />
                  </View>

                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>LOCATION</Text>
                    <GlassInput
                      value={nfcLocation}
                      onChangeText={setNfcLocation}
                      placeholder="e.g., Main Entrance, Building A"
                    />
                  </View>

                  <GlassButton
                    title={addingNfc ? 'Adding...' : 'Add NFC Tag'}
                    onPress={handleAddNfcTag}
                    loading={addingNfc}
                    style={styles.addButton}
                  />
                </View>
              </GlassCard>
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.md,
  },
  loadingText: {
    color: colors.text.muted,
    fontSize: 14,
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
  projectHeader: {
    marginBottom: spacing.lg,
  },
  projectTitleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
  },
  projectInfo: {
    flex: 1,
  },
  projectName: {
    fontSize: 28,
    fontWeight: '300',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  locationRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  locationText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  qrBadge: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
  },
  statIcon: {
    marginBottom: spacing.sm,
  },
  statValue: {
    fontSize: 28,
    fontWeight: '200',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  statLabel: {
    ...typography.label,
    fontSize: 9,
    color: colors.text.muted,
  },
  sectionLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.xs,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
    paddingHorizontal: spacing.xs,
  },
  actionsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  actionCard: {
    width: '47%',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
    alignItems: 'center',
    gap: spacing.sm,
  },
  actionCardPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.98 }],
  },
  actionIcon: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.lg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  nfcTagsList: {
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  nfcTagCard: {
    padding: spacing.md,
  },
  nfcTagHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  nfcTagInfo: {
    flex: 1,
  },
  nfcTagId: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  nfcTagLocation: {
    fontSize: 13,
    color: colors.text.muted,
  },
  deleteBtn: {
    padding: spacing.sm,
  },
  emptyNfcCard: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  emptyNfcText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.muted,
  },
  emptyNfcSubtext: {
    fontSize: 13,
    color: colors.text.subtle,
  },
  companyCard: {
    marginBottom: spacing.md,
  },
  companyHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  companyName: {
    flex: 1,
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerCount: {
    backgroundColor: colors.glass.background,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
  },
  workerCountText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.primary,
  },
  workerTags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  workerTag: {
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  workerTagName: {
    fontSize: 13,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerTagTrade: {
    fontSize: 11,
    color: colors.text.muted,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.sm,
  },
  emptyText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.muted,
  },
  emptySubtext: {
    fontSize: 13,
    color: colors.text.subtle,
    textAlign: 'center',
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0, 0, 0, 0.85)',
  },
  modalContent: {
    padding: spacing.lg,
  },
  modalCard: {
    maxWidth: 500,
    alignSelf: 'center',
    width: '100%',
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  modalDesc: {
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.lg,
  },
  modalForm: {
    gap: spacing.md,
  },
  inputGroup: {
    gap: spacing.sm,
  },
  inputLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  addButton: {
    marginTop: spacing.sm,
  },
});
