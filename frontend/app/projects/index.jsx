import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Modal,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Plus,
  Building2,
  MapPin,
  Wifi,
  Trash2,
  X,
  Search,
  LogOut,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { ProjectCardSkeleton } from '../../src/components/GlassSkeleton';
import FloatingNav from '../../src/components/FloatingNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { projectsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

export default function ProjectsScreen() {
  const router = useRouter();
  const { logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [searchQuery, setSearchQuery] = useState('');
  const [showAddModal, setShowAddModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [projects, setProjects] = useState([]);
  const [newProject, setNewProject] = useState({ name: '', location: '' });

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  // Fetch projects
  useEffect(() => {
    if (isAuthenticated) {
      fetchProjects();
    }
  }, [isAuthenticated]);

  const fetchProjects = async () => {
    setLoading(true);
    try {
      const data = await projectsAPI.getAll();
      setProjects(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error('Failed to fetch projects:', error);
      toast.error('Load Error', 'Could not load projects');
      setProjects([]);
    } finally {
      setLoading(false);
    }
  };

  const filteredProjects = projects.filter(
    (p) =>
      (p.name?.toLowerCase() || '').includes(searchQuery.toLowerCase()) ||
      (p.location?.toLowerCase() || '').includes(searchQuery.toLowerCase())
  );

  const handleAddProject = async () => {
    if (!newProject.name.trim() || !newProject.location.trim()) {
      toast.warning('Validation Error', 'Please fill in all fields');
      return;
    }

    setCreating(true);
    try {
      const createdProject = await projectsAPI.create({
        name: newProject.name,
        location: newProject.location,
      });

      setProjects([...projects, createdProject]);
      setNewProject({ name: '', location: '' });
      setShowAddModal(false);
      toast.success('Success', 'Project created successfully');
    } catch (error) {
      console.error('Failed to create project:', error);
      toast.error('Create Error', error.response?.data?.detail || 'Could not create project');
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteProject = async (projectId) => {
    try {
      await projectsAPI.delete(projectId);
      setProjects(projects.filter((p) => (p._id || p.id) !== projectId));
      toast.success('Deleted', 'Project removed successfully');
    } catch (error) {
      console.error('Failed to delete project:', error);
      toast.error('Delete Error', error.response?.data?.detail || 'Could not delete project');
    }
  };

  const getProjectId = (project) => project._id || project.id;

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
            <Text style={styles.titleLabel}>MANAGE</Text>
            <Text style={styles.titleText}>Projects</Text>
          </View>

          {/* Search & Add */}
          <View style={styles.searchRow}>
            <View style={styles.searchContainer}>
              <GlassInput
                value={searchQuery}
                onChangeText={setSearchQuery}
                placeholder="Search projects..."
                leftIcon={<Search size={20} strokeWidth={1.5} color={colors.text.subtle} />}
              />
            </View>
            <GlassButton
              title="New Project"
              icon={<Plus size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => setShowAddModal(true)}
            />
          </View>

          {/* Projects List */}
          <View style={styles.projectsList}>
            {loading ? (
              <>
                <ProjectCardSkeleton />
                <ProjectCardSkeleton />
                <ProjectCardSkeleton />
              </>
            ) : filteredProjects.length > 0 ? (
              filteredProjects.map((project) => (
                <Pressable
                  key={getProjectId(project)}
                  onPress={() => router.push(`/project/${getProjectId(project)}`)}
                  style={({ pressed }) => [
                    styles.projectCard,
                    pressed && styles.projectCardPressed,
                  ]}
                >
                  <IconPod>
                    <Building2 size={20} strokeWidth={1.5} color={colors.text.secondary} />
                  </IconPod>

                  <View style={styles.projectInfo}>
                    <Text style={styles.projectName}>{project.name}</Text>
                    <View style={styles.projectLocation}>
                      <MapPin size={14} strokeWidth={1.5} color={colors.text.muted} />
                      <Text style={styles.projectLocationText}>
                        {project.location || 'No location'}
                      </Text>
                    </View>
                  </View>

                  {project.nfc_tags?.length > 0 && (
                    <View style={styles.nfcBadge}>
                      <Wifi size={14} strokeWidth={1.5} color={colors.text.muted} />
                      <Text style={styles.nfcText}>{project.nfc_tags.length} NFC</Text>
                    </View>
                  )}

                  {project.status && (
                    <View
                      style={[
                        styles.statusBadge,
                        project.status === 'active' && styles.statusActive,
                      ]}
                    >
                      <Text
                        style={[
                          styles.statusText,
                          project.status === 'active' && styles.statusTextActive,
                        ]}
                      >
                        {project.status.toUpperCase()}
                      </Text>
                    </View>
                  )}

                  <Pressable
                    onPress={() => handleDeleteProject(getProjectId(project))}
                    style={styles.deleteButton}
                    hitSlop={10}
                  >
                    <Trash2 size={16} strokeWidth={1.5} color={colors.text.muted} />
                  </Pressable>
                </Pressable>
              ))
            ) : (
              <View style={styles.emptyState}>
                <Building2 size={48} strokeWidth={1} color={colors.text.subtle} />
                <Text style={styles.emptyText}>
                  {searchQuery ? 'No projects match your search' : 'No projects found'}
                </Text>
              </View>
            )}
          </View>
        </ScrollView>

        <FloatingNav />

        {/* Add Modal */}
        <Modal
          visible={showAddModal}
          transparent
          animationType="slide"
          onRequestClose={() => setShowAddModal(false)}
        >
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
            style={styles.modalOverlay}
          >
            <Pressable style={styles.modalBackdrop} onPress={() => setShowAddModal(false)} />
            <View style={styles.modalContent}>
              <GlassCard style={styles.modalCard}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>New Project</Text>
                  <GlassButton
                    variant="icon"
                    icon={<X size={20} strokeWidth={1.5} color={colors.text.primary} />}
                    onPress={() => setShowAddModal(false)}
                  />
                </View>

                <View style={styles.modalForm}>
                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>PROJECT NAME</Text>
                    <GlassInput
                      value={newProject.name}
                      onChangeText={(text) => setNewProject({ ...newProject, name: text })}
                      placeholder="Downtown Tower Phase 2"
                    />
                  </View>

                  <View style={styles.inputGroup}>
                    <Text style={styles.inputLabel}>LOCATION</Text>
                    <GlassInput
                      value={newProject.location}
                      onChangeText={(text) => setNewProject({ ...newProject, location: text })}
                      placeholder="New York, NY"
                    />
                  </View>

                  <GlassButton
                    title="Create Project"
                    onPress={handleAddProject}
                    loading={creating}
                    style={styles.createButton}
                  />
                </View>
              </GlassCard>
            </View>
          </KeyboardAvoidingView>
        </Modal>
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
  searchRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.lg,
  },
  searchContainer: {
    flex: 1,
  },
  projectsList: {
    gap: spacing.md,
  },
  projectCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  projectCardPressed: {
    opacity: 0.8,
  },
  projectInfo: {
    flex: 1,
  },
  projectName: {
    fontSize: 17,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  projectLocation: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  projectLocationText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  nfcBadge: {
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
  nfcText: {
    fontSize: 12,
    color: colors.text.muted,
  },
  statusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  statusActive: {
    backgroundColor: 'rgba(74, 222, 128, 0.2)',
    borderColor: 'rgba(74, 222, 128, 0.3)',
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
  },
  statusTextActive: {
    color: '#4ade80',
  },
  deleteButton: {
    padding: spacing.sm,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: spacing.xxl * 2,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 16,
    color: colors.text.muted,
  },
  modalOverlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0, 0, 0, 0.6)',
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
    marginBottom: spacing.lg,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '300',
    color: colors.text.primary,
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
  createButton: {
    marginTop: spacing.sm,
  },
});
