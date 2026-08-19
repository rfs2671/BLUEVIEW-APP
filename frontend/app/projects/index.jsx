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
import { GlassCard, StatCard, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import RiskScoreCircle from '../../src/components/RiskScoreCircle';
import GlassInput from '../../src/components/GlassInput';
import { ProjectCardSkeleton } from '../../src/components/GlassSkeleton';
import FloatingNav from '../../src/components/FloatingNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { projectsAPI } from '../../src/utils/api';
import { cacheProjectList, readCachedProjectList } from '../../src/utils/projectCache';
import OfflineNotice from '../../src/components/OfflineNotice';
import { isOfflineError, failureDetail } from '../../src/utils/offlineState';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { semantic, withAlpha } from '../../src/styles/semanticColors';
import { useIsDesktop } from '../../src/hooks/useIsDesktop';
import ProjectsTable from '../../src/components/ProjectsTable';
import { useTheme } from '../../src/context/ThemeContext';
// ── FIX #3: Import AddressAutocomplete ──
import AddressAutocomplete from '../../src/components/AddressAutocomplete';
import HeaderBrand from '../../src/components/HeaderBrand';
import BuildMarker from '../../src/components/BuildMarker';
// Phase 1 Week 11-12 PR-B — Defcon dot color mapping (NORMAL hidden).
import { tierToTheme } from '../../src/utils/defconHelpers';
// PR #52 — shared text-overflow helpers (no mid-word breaks).
import { clampLines, textOverflowDefaults } from '../../src/utils/textHelpers';

export default function ProjectsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();
  // Desktop (RN-Web >=1024) swaps the card list for a sortable table.
  // Below the breakpoint, and on native, the card list below is unchanged.
  const isDesktop = useIsDesktop();

  const [searchQuery, setSearchQuery] = useState('');
  const [showAddModal, setShowAddModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [projects, setProjects] = useState([]);
  // OFFLINE vs EMPTY — 'ok' | 'offline' | 'error' for the last list refresh.
  // The cache keeps rows on screen, but the screen still has to SAY the list is
  // a saved copy; and with an empty cache it must not fall through to
  // "No projects found", which claims the account has none.
  const [fetchState, setFetchState] = useState('ok');
  // ── FIX #3: Single address field instead of name + location ──
  const [newProject, setNewProject] = useState({
    address: '',
    // UNSET, NOT 'regular'. server.py:9282 treats ANY client-supplied
    // project_class as an ADMIN OVERRIDE and stamps
    // classification_source = "admin" — so this default recorded a human
    // decision about §3310 on every project created here, when nobody had
    // measured anything or chosen anything.
    //
    // That is why so few projects ever reached the fail-closed path: the
    // server computes a suggested class and marks it "measured" or
    // "unassessed", and this field overrode that on the way in.
    //
    // Sending NOTHING lets the server's own classification run.
    project_class: null,
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
    // Cache-first: show the cached list immediately so the selection screen is
    // never empty offline. (The old catch did setProjects([]), which BLANKED the
    // list on any offline load — the CP's live "no projects" bug.)
    const _cached = await readCachedProjectList();
    if (_cached.length > 0) { setProjects(_cached); setLoading(false); }
    else setLoading(true);
    try {
      const data = await projectsAPI.getAll();
      cacheProjectList(data);
      setProjects(Array.isArray(data) ? data : []);
      setFetchState('ok');
    } catch (error) {
      console.error('Failed to fetch projects:', error);
      // KEEP the already-loaded cached list — the offline refresh failure must
      // NEVER clear or overwrite it. Re-set the SAME `_cached` we already
      // rendered (no re-read, no [] path); cacheProjectList only runs on success
      // above, so the stored cache is never overwritten with empty either.
      setProjects(_cached);
      // A 4xx/5xx is NOT "Offline" — the server answered. isOfflineError() is
      // the discriminator; the banner below renders from the same state.
      const offline = isOfflineError(error);
      setFetchState(offline ? 'offline' : 'error');
      if (_cached.length > 0) {
        toast.success(
          offline ? 'Offline' : 'Showing saved copy',
          `Loaded ${_cached.length} cached project${_cached.length === 1 ? '' : 's'}`,
        );
      } else {
        // The offline copy stays as-is: it says something failureDetail
        // cannot know — that no cached copy exists on THIS VERSION. The error
        // branch gives up its fixed sentence, which was identical for a 500,
        // a 403 and a 404.
        toast.error(
          offline ? 'Offline' : 'Could not load',
          offline
            ? 'No cached projects — open once online on this version first'
            : failureDetail('error', error, 'your projects'),
        );
      }
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
        // OMITTED unless he picked one. A key present with any value is an
        // override; the absence is what lets the server classify.
        ...(newProject.project_class ? { project_class: newProject.project_class } : {}),
      });

      setProjects([...projects, createdProject]);
      setNewProject({ address: '', project_class: null });
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

          {/* The last refresh failed. Say so ABOVE the list, whether the list is
              a cached copy (cachedCount) or nothing at all. */}
          {!loading && fetchState !== 'ok' && (
            <OfflineNotice mode={fetchState} cachedCount={projects.length} />
          )}

          {/* Projects List */}
          <View style={s.projectsList}>
            {loading ? (
              <>
                <ProjectCardSkeleton />
                <ProjectCardSkeleton />
                <ProjectCardSkeleton />
              </>
            ) : filteredProjects.length > 0 ? (
              isDesktop ? (
                <ProjectsTable
                  projects={filteredProjects}
                  onRowPress={(project) => router.push(`/project/${getProjectId(project)}`)}
                  onDelete={(project) => handleDeleteProject(getProjectId(project))}
                />
              ) : filteredProjects.map((project) => (
                <GlassListItem
                  key={getProjectId(project)}
                  onPress={() => router.push(`/project/${getProjectId(project)}`)}
                  style={s.projectCard}
                >
                  {/* Card redesign: Building2 logo removed. Left zone
                      takes all remaining width (flex:1 + minWidth:0) so
                      the address can never be starved into a per-char
                      wrap; badges sit BELOW the text instead of competing
                      for horizontal room. */}
                  <View style={s.cardMain}>
                    <View style={s.titleRow}>
                      {/* Defcon urgency marker — leading dot, top-left of
                          the card. Real tier signal (not decoration);
                          bordered so it stays legible. NORMAL/null hide. */}
                      {project.defcon_tier && project.defcon_tier !== 'NORMAL' && (
                        <View
                          style={[s.defconDot, { backgroundColor: tierToTheme(project.defcon_tier).fg }]}
                          accessibilityLabel={`Defcon ${project.defcon_tier.toLowerCase()}`}
                        />
                      )}
                      <Text
                        style={[s.projectName, { color: colors.text.primary }]}
                        {...clampLines(2)}
                      >
                        {project.name}
                      </Text>
                    </View>

                    <View style={s.projectLocation}>
                      <MapPin size={13} strokeWidth={1.5} color={colors.text.muted} />
                      {/* Address first, location fallback. Single-line
                          ellipsis (textOverflowDefaults) — never wraps. */}
                      <Text
                        style={[s.projectLocationText, { color: colors.text.muted }]}
                        {...textOverflowDefaults}
                      >
                        {project.address || project.location || 'No location'}
                      </Text>
                    </View>

                    {/* Badge strip below the text — frees the address
                        column's width (was the starvation root cause). */}
                    {(project.nfc_tags?.length > 0
                      || (project.project_class && project.project_class !== 'regular')
                      || project.status) && (
                      <View style={s.badgeStrip}>
                        {project.nfc_tags?.length > 0 && (
                          <View style={s.nfcBadge}>
                            <Wifi size={12} strokeWidth={1.5} color={colors.text.muted} />
                            <Text style={s.nfcText}>{project.nfc_tags.length} NFC</Text>
                          </View>
                        )}
                        {project.project_class && project.project_class !== 'regular' && (
                          <View style={[s.classificationBadge, {
                            backgroundColor: project.project_class === 'major_b' ? semantic.neutralBg : semantic.attentionBg,
                          }]}>
                            <Text style={[s.classificationText, {
                              color: project.project_class === 'major_b' ? semantic.neutralStrong : semantic.neutralStrong,
                            }]}>
                              {project.project_class === 'major_b' ? 'MAJOR B' : 'MAJOR A'}
                            </Text>
                          </View>
                        )}
                        {project.status && (
                          <View style={[s.statusBadge, project.status === 'active' && s.statusActive]}>
                            <Text style={[s.statusText, project.status === 'active' && s.statusTextActive]}>
                              {project.status.toUpperCase()}
                            </Text>
                          </View>
                        )}
                      </View>
                    )}
                  </View>

                  {/* Right zone — risk ring only now (no badge
                      competitors). flexShrink:0 keeps its width fixed so
                      the left text column absorbs the rest. */}
                  <View style={s.cardRight}>
                    <RiskScoreCircle
                      projectId={getProjectId(project)}
                      isAdmin={false}
                      size={52}
                    />
                  </View>

                  {/* Delete — small, pinned to the card's top-right
                      corner (out of the badge row), sitting in the empty
                      corner above the ring's arc. */}
                  <Pressable
                    onPress={() => handleDeleteProject(getProjectId(project))}
                    style={({ hovered }) => [s.trashCorner, hovered && { backgroundColor: semantic.criticalBg }]}
                    hitSlop={10}
                  >
                    {({ hovered }) => (
                      <Trash2 size={15} strokeWidth={1.5} color={hovered ? semantic.neutral : colors.text.muted} />
                    )}
                  </Pressable>
                </GlassListItem>
              ))
            ) : projects.length === 0 && fetchState !== 'ok' ? (
              /* Nothing loaded AND nothing cached. "No projects found" would
                 assert the account has none — it doesn't; we just couldn't
                 read them. (A search that matches nothing is still honest.) */
              <View style={s.emptyState}>
                <Building2 size={48} strokeWidth={1} color={colors.text.subtle} />
                <Text style={s.emptyText}>
                  {fetchState === 'offline'
                    ? 'Your projects could not be loaded and none are saved on this device.'
                    : 'Your projects could not be read from the server.'}
                </Text>
              </View>
            ) : (
              <View style={s.emptyState}>
                <Building2 size={48} strokeWidth={1} color={colors.text.subtle} />
                <Text style={s.emptyText}>
                  {searchQuery ? 'No projects match your search' : 'No projects found'}
                </Text>
              </View>
            )}
          </View>

          {/* Running-bundle self-report — proves which JS is live. */}
          <BuildMarker />
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
                        // FIRST, AND SELECTED UNTIL HE CHOOSES. "Not assessed"
                        // is a real answer here: the server measures stories,
                        // height and footprint and classifies from them, and it
                        // can only do that if this screen does not assert one.
                        { key: null, label: 'Not assessed — set later',
                          desc: 'The server classifies from the measurements; pick one only to override it' },
                        { key: 'regular', label: 'Regular', desc: 'Under 10 stories, no SSC/SSM required' },
                        { key: 'major_a', label: 'Major A — SSC', desc: '10+ stories or 125+ ft — Site Safety Coordinator required' },
                        { key: 'major_b', label: 'Major B — SSM', desc: '15+ stories, 200+ ft, or 100K+ sqft — Site Safety Manager required' },
                      ].map((opt) => (
                        <Pressable
                          key={String(opt.key)}
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
  // Card redesign — left text zone owns the remaining width so the
  // address can never be starved into a per-character wrap.
  // (GlassCard.listItemContent has no `gap`, so marginRight provides the
  // separation from the risk ring.)
  cardMain: {
    flex: 1,
    minWidth: 0,
    marginRight: spacing.md,
    gap: spacing.xs,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  // Defcon urgency dot — leading marker on the title row (top-left).
  // Bordered in the card bg so it stays legible against any tier color.
  defconDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    borderWidth: 2,
    borderColor: colors.background.middle,
    flexShrink: 0,
  },
  projectName: {
    flex: 1,
    minWidth: 0,
    fontSize: 17,
    fontWeight: '500',
  },
  projectLocation: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    minWidth: 0,
  },
  projectLocationText: {
    flex: 1,
    minWidth: 0,
    fontSize: 14,
    flexShrink: 1,
  },
  // Badge strip below the text (NFC · MAJOR · ACTIVE). Wraps instead of
  // squeezing the address column.
  badgeStrip: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: spacing.xs,
    marginTop: 2,
  },
  // Right zone holds only the risk ring now; fixed width.
  cardRight: {
    flexShrink: 0,
    alignItems: 'center',
    justifyContent: 'center',
  },
  // Delete pinned to the card's top-right corner.
  trashCorner: {
    position: 'absolute',
    top: spacing.sm,
    right: spacing.sm,
    padding: spacing.xs,
    borderRadius: borderRadius.md,
    zIndex: 2,
  },
  // PR #52 L3 — the right-side cluster (badges + risk donut + delete)
  // keeps intrinsic width (flexShrink:0) so it never squeezes the title
  // column, which is what forced the mid-word wraps.
  nfcBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
    flexShrink: 0,
  },
  nfcText: {
    fontSize: 12,
    color: colors.text.muted,
  },
  statusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    backgroundColor: withAlpha('#ffffff', 0.05),
    flexShrink: 0,
  },
  statusActive: {
    backgroundColor: semantic.verifiedBg,
  },
  statusText: {
    fontSize: 10,
    fontWeight: '600',
    color: colors.text.muted,
  },
  statusTextActive: {
    color: semantic.verified,
  },
  deleteButton: {
    padding: spacing.sm,
    borderRadius: borderRadius.md,
    backgroundColor: semantic.criticalBg,
    flexShrink: 0,
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
    backgroundColor: withAlpha('#000000', 0.75),
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
    borderColor: withAlpha('#ffffff', 0.1),
    backgroundColor: withAlpha('#ffffff', 0.03),
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
    borderColor: withAlpha('#ffffff', 0.15),
    backgroundColor: withAlpha('#ffffff', 0.04),
    alignItems: 'center',
    justifyContent: 'center',
  },
  toggleBoxActive: {
    backgroundColor: semantic.verifiedBg,
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
    flexShrink: 0,
  },
  classificationMajor: {
    backgroundColor: withAlpha('#94a3b8', 0.15),
  },
  classificationText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#60a5fa',
  },
  classificationTextMajor: {
    color: semantic.neutralStrong,
  },
  });
}
