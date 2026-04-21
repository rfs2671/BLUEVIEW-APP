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
  Alert,
  Image,
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
  CheckCircle,
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
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';
// ── FIX #3: Import AddressAutocomplete ──
import AddressAutocomplete from '../../src/components/AddressAutocomplete';
import HeaderBrand from '../../src/components/HeaderBrand';

export default function ProjectsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [searchQuery, setSearchQuery] = useState('');
  const [showAddModal, setShowAddModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [projects, setProjects] = useState([]);
  // ── FIX #3: Single address field instead of name + location ──
  const [newProject, setNewProject] = useState({
    address: '',
    project_class: 'regular',
  });

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

  // ── FIX #3: Search also matches against address field ──
  const filteredProjects = projects.filter(
    (p) =>
      (p.name?.toLowerCase() || '').includes(searchQuery.toLowerCase()) ||
      (p.address?.toLowerCase() || '').includes(searchQuery.toLowerCase()) ||
      (p.location?.toLowerCase() || '').includes(searchQuery.toLowerCase())
  );

  // ── FIX #3: Send address as name + address + location ──
  const handleAddProject = async () => {
    if (!newProject.address.trim()) {
      toast.warning('Validation Error', 'Please enter a project address');
      return;
    }

    setCreating(true);
    try {
      const createdProject = await projectsAPI.create({
        name: newProject.address,
        address: newProject.address,
        location: newProject.address,
        project_class: newProject.project_class,
      });

      setProjects([...projects, createdProject]);
      setNewProject({ address: '', project_class: 'regular' });
      setShowAddModal(false);
      toast.success('Project Created', 'New project added');
    } catch (error) {
      console.error('Failed to create project:', error);
      toast.error('Create Error', error.response?.data?.detail || 'Could not create project');
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteProject = async (projectId) => {
    const projectToDelete = projects.find(p => (p._id || p.id) === projectId);
    const projectName = projectToDelete?.name || projectToDelete?.address || 'this project';

    const doDelete = async () => {
      try {
        await projectsAPI.delete(projectId);
        setProjects(projects.filter((p) => (p._id || p.id) !== projectId));
        toast.success('Deleted', 'Project and all DOB logs removed');
      } catch (error) {
        console.error('Failed to delete project:', error);
        toast.error('Delete Error', error.response?.data?.detail || 'Could not delete project');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm(`Delete "${projectName}"?\n\nThis will permanently remove the project and all its DOB compliance data. This cannot be undone.`)) {
        doDelete();
      }
    } else {
      Alert.alert(
        'Delete Project?',
        `This will permanently remove "${projectName}" and all its DOB compliance data. This cannot be undone.`,
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Delete', style: 'destructive', onPress: doDelete },
        ]
      );
    }
  };

  const getProjectId = (project) => project._id || project.id;

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
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
            <Text style={s.titleLabel}>MANAGE</Text>
            <Text style={s.titleText}>Projects</Text>
          </View>

          {/* Search & Add */}
          <View style={s.searchRow}>
            <View style={s.searchContainer}>
              <GlassInput
                value={searchQuery}
                onChangeText={setSearchQuery}
                placeholder="Search"
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
          <View style={s.projectsList}>
            {loading ? (
              <>
                <ProjectCardSkeleton />
                <ProjectCardSkeleton />
                <ProjectCardSkeleton />
              </>
            ) : filteredProjects.length > 0 ? (
              filteredProjects.map((project) => (
                <GlassListItem
                  key={getProjectId(project)}
                  onPress={() => router.push(`/project/${getProjectId(project)}`)}
                  style={s.projectCard}
                >
                  <IconPod>
                    <Building2 size={20} strokeWidth={1.5} color={colors.text.secondary} />
                  </IconPod>

                  <View style={s.projectInfo}>
                    <Text style={[s.projectName, { color: colors.text.primary }]}>{project.name}</Text>
                    <View style={s.projectLocation}>
                      <MapPin size={14} strokeWidth={1.5} color={colors.text.muted} />
                      {/* ── FIX #3: Show address first, fall back to location ── */}
                      <Text style={[s.projectLocationText, { color: colors.text.muted }]}>
                        {project.address || project.location || 'No location'}
                      </Text>
                    </View>
                  </View>

                  {project.nfc_tags?.length > 0 && (
                    <View style={s.nfcBadge}>
                      <Wifi size={14} strokeWidth={1.5} color={colors.text.muted} />
                      <Text style={s.nfcText}>{project.nfc_tags.length} NFC</Text>
                    </View>
                  )}

                  {project.project_class && project.project_class !== 'regular' && (
                    <View style={[s.classificationBadge, {
                      backgroundColor: project.project_class === 'major_b' ? 'rgba(239,68,68,0.2)' : 'rgba(245,158,11,0.2)',
                    }]}>
                      <Text style={[s.classificationText, {
                        color: project.project_class === 'major_b' ? '#ef4444' : '#f59e0b',
                      }]}>
                        {project.project_class === 'major_b' ? 'MAJOR B' : 'MAJOR A'}
                      </Text>
                    </View>
                  )}

                  {project.status && (
                    <View
                      style={[
                        s.statusBadge,
                        project.status === 'active' && s.statusActive,
                      ]}
                    >
                      <Text
                        style={[
                          s.statusText,
                          project.status === 'active' && s.statusTextActive,
                        ]}
                      >
                        {project.status.toUpperCase()}
                      </Text>
                    </View>
                  )}

                  <Pressable
                    onPress={() => handleDeleteProject(getProjectId(project))}
                    onHoverIn={(e) => { e.currentTarget._trashHover = true; e.currentTarget.setNativeProps && e.currentTarget.setNativeProps({}); }}
                    onHoverOut={(e) => { e.currentTarget._trashHover = false; e.currentTarget.setNativeProps && e.currentTarget.setNativeProps({}); }}
                    style={({ hovered }) => [s.deleteButton, hovered && { backgroundColor: 'rgba(239,68,68,0.1)', borderRadius: 20 }]}
                    hitSlop={10}
                  >
                    {({ hovered }) => (
                      <Trash2 size={16} strokeWidth={1.5} color={hovered ? '#ef4444' : colors.text.muted} />
                    )}
                  </Pressable>
                </GlassListItem>
              ))
            ) : (
              <View style={s.emptyState}>
                <Building2 size={48} strokeWidth={1} color={colors.text.subtle} />
                <Text style={s.emptyText}>
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
            style={s.modalOverlay}
          >
            <Pressable style={s.modalBackdrop} onPress={() => setShowAddModal(false)} />
            <View style={[s.modalContent, { overflow: 'visible' }]}>
              <GlassCard variant="modal" style={[s.modalCard, { overflow: 'visible' }]}>
                <View style={s.modalHeader}>
                  <Text style={s.modalTitle}>New Project</Text>
                  <GlassButton
                    variant="icon"
                    icon={<X size={20} strokeWidth={1.5} color={colors.text.primary} />}
                    onPress={() => setShowAddModal(false)}
                  />
                </View>

                {/* ── FIX #3: Single address autocomplete replaces name + location ── */}
                <View style={s.modalForm}>
                  <View style={[s.inputGroup, { zIndex: 100 }]}>
                    <Text style={s.inputLabel}>PROJECT ADDRESS</Text>
                    <AddressAutocomplete
                      value={newProject.address}
                      onChangeText={(text) => setNewProject({ ...newProject, address: text })}
                      onSelect={({ address }) => setNewProject({ ...newProject, address })}
                      placeholder="Start typing an address..."
                    />
                  </View>

                  {/* Classification fields */}
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>PROJECT TYPE</Text>
                    <View style={s.classPickerCol}>
                      {[
                        { key: 'regular', label: 'Regular', desc: 'Under 10 stories, no SSC/SSM required' },
                        { key: 'major_a', label: 'Major A — SSC', desc: '10+ stories or 125+ ft — Site Safety Coordinator required' },
                        { key: 'major_b', label: 'Major B — SSM', desc: '15+ stories, 200+ ft, or 100K+ sqft — Site Safety Manager required' },
                      ].map((opt) => (
                        <Pressable
                          key={opt.key}
                          style={[
                            s.classPickerOption,
                            newProject.project_class === opt.key && s.classPickerActive,
                          ]}
                          onPress={() => setNewProject({ ...newProject, project_class: opt.key })}
                        >
                          <Text style={[
                            s.classPickerText,
                            newProject.project_class === opt.key && s.classPickerTextActive,
                          ]}>
                            {opt.label}
                          </Text>
                          <Text style={s.classPickerDesc}>{opt.desc}</Text>
                        </Pressable>
                      ))}
                    </View>
                  </View>

                  <GlassButton
                    title="Create Project"
                    onPress={handleAddProject}
                    loading={creating}
                    style={s.createButton}
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
    fontSize: 48,
    fontWeight: '200',
    letterSpacing: -1,
    color: colors.text.primary,
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
    gap: spacing.md,
  },
  projectInfo: {
    flex: 1,
  },
  projectName: {
    fontSize: 17,
    fontWeight: '500',
    marginBottom: spacing.xs,
  },
  projectLocation: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  projectLocationText: {
    fontSize: 14,
  },
  nfcBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
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
    borderRadius: borderRadius.full,
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
  },
  statusActive: {
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
  },
  statusText: {
    fontSize: 10,
    fontWeight: '600',
    color: colors.text.muted,
  },
  statusTextActive: {
    color: '#4ade80',
  },
  deleteButton: {
    padding: spacing.sm,
    borderRadius: borderRadius.md,
    backgroundColor: 'rgba(239, 68, 68, 0.1)',
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 15,
    color: colors.text.muted,
    textAlign: 'center',
  },
  // Modal
  modalOverlay: {
    flex: 1,
  },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    // Darker scrim so background content reads as clearly "behind" the
    // modal rather than bleeding through it.
    backgroundColor: 'rgba(0, 0, 0, 0.75)',
  },
  modalContent: {
    flex: 1,
    justifyContent: 'flex-end',
    padding: spacing.lg,
  },
  modalCard: {
    padding: spacing.xl,
    // GlassCard variant="modal" has no gradient layer — just blur — so
    // on mobile you can still read the page behind it. Add a solid
    // theme-aware fill so the card is fully opaque.
    backgroundColor: isDark ? '#121826' : '#ffffff',
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.xl,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  modalForm: {
    gap: spacing.lg,
  },
  inputGroup: {
    gap: spacing.sm,
  },
  inputLabel: {
    ...typography.label,
  },
  createButton: {
    marginTop: spacing.md,
  },
  classPickerCol: {
    gap: spacing.xs,
  },
  classPickerOption: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    backgroundColor: 'rgba(255,255,255,0.03)',
  },
  classPickerActive: {
    borderColor: colors.primary || '#3b82f6',
    backgroundColor: (colors.primary || '#3b82f6') + '15',
  },
  classPickerText: {
    color: colors.text.muted,
    fontSize: 14,
    fontWeight: '600',
  },
  classPickerTextActive: {
    color: colors.primary || '#3b82f6',
  },
  classPickerDesc: {
    color: colors.text.subtle,
    fontSize: 11,
    marginTop: 2,
  },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  toggleBox: {
    width: 22,
    height: 22,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.15)',
    backgroundColor: 'rgba(255,255,255,0.04)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  toggleBoxActive: {
    backgroundColor: 'rgba(74,222,128,0.1)',
    borderColor: '#4ade80',
  },
  toggleLabel: {
    fontSize: 14,
    color: colors.text.secondary,
  },
  classificationBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    backgroundColor: 'rgba(59,130,246,0.15)',
  },
  classificationMajor: {
    backgroundColor: 'rgba(245,158,11,0.15)',
  },
  classificationText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#60a5fa',
  },
  classificationTextMajor: {
    color: '#f59e0b',
  },
  });
}
