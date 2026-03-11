import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  Modal,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ClipboardList,
  Plus,
  Edit2,
  Trash2,
  Users,
  X,
  Check,
  Send,
  Eye,
  CheckCircle,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, IconPod, GlassListItem } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import GlassInput from '../../../src/components/GlassInput';
import { GlassSkeleton } from '../../../src/components/GlassSkeleton';
import FloatingNav from '../../../src/components/FloatingNav';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { checklistsAPI, projectsAPI, adminUsersAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';

export default function AdminChecklistsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [checklists, setChecklists] = useState([]);
  const [projects, setProjects] = useState([]);
  const [users, setUsers] = useState([]);

  // Modals
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [showViewModal, setShowViewModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  // Selected data
  const [selectedChecklist, setSelectedChecklist] = useState(null);
  const [assignments, setAssignments] = useState([]);

  // Form states
  const [formData, setFormData] = useState({
    title: '',
    description: '',
    items: [{ text: '', order: 0 }],
  });

  const [assignData, setAssignData] = useState({
    selectedProjects: [],
    selectedUsers: [],
  });

  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!authLoading) {
      if (!isAuthenticated) {
        router.replace('/login');
      } else if (user?.role !== 'admin' && user?.role !== 'owner') {
        router.replace('/');
      }
    }
  }, [isAuthenticated, authLoading, user]);

  useEffect(() => {
    if (isAuthenticated && (user?.role === 'admin' || user?.role === 'owner')) {
      fetchData();
    }
  }, [isAuthenticated, user]);

  const fetchData = async () => {
    setLoading(true);
    try {
      const [checklistsData, projectsData, usersData] = await Promise.all([
        checklistsAPI.getAll(),
        projectsAPI.getAll(),
        adminUsersAPI.getAll(),
      ]);
      setChecklists(checklistsData);
      setProjects(projectsData);
      setUsers(usersData.filter(u => u.role !== 'owner'));
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Error', 'Could not load checklists');
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setFormData({
      title: '',
      description: '',
      items: [{ text: '', order: 0 }],
    });
  };

  const handleCreateChecklist = () => {
    resetForm();
    setShowCreateModal(true);
  };

  const handleEditChecklist = (checklist) => {
    setSelectedChecklist(checklist);
    setFormData({
      title: checklist.title,
      description: checklist.description || '',
      items: checklist.items.length > 0 ? checklist.items : [{ text: '', order: 0 }],
    });
    setShowEditModal(true);
  };

  const handleDeleteChecklist = (checklist) => {
    setSelectedChecklist(checklist);
    setShowDeleteModal(true);
  };

  const handleAssignChecklist = (checklist) => {
    setSelectedChecklist(checklist);
    setAssignData({ selectedProjects: [], selectedUsers: [] });
    setShowAssignModal(true);
  };

  const handleViewAssignments = async (checklist) => {
    setSelectedChecklist(checklist);
    try {
      const data = await checklistsAPI.getAssignments(checklist.id);
      setAssignments(data);
      setShowViewModal(true);
    } catch (error) {
      console.error('Failed to fetch assignments:', error);
      toast.error('Error', 'Could not load assignments');
    }
  };

  const addItem = () => {
    setFormData({
      ...formData,
      items: [...formData.items, { text: '', order: formData.items.length }],
    });
  };

  const removeItem = (index) => {
    const newItems = formData.items.filter((_, i) => i !== index);
    setFormData({ ...formData, items: newItems });
  };

  const updateItem = (index, text) => {
    const newItems = [...formData.items];
    newItems[index] = { ...newItems[index], text };
    setFormData({ ...formData, items: newItems });
  };

  const handleSubmitCreate = async () => {
    if (!formData.title.trim()) {
      toast.error('Error', 'Title is required');
      return;
    }

    const validItems = formData.items.filter(item => item.text.trim());
    if (validItems.length === 0) {
      toast.error('Error', 'At least one item is required');
      return;
    }

    setSaving(true);
    try {
      await checklistsAPI.create({
        title: formData.title,
        description: formData.description,
        items: validItems.map((item, idx) => ({ text: item.text, order: idx })),
      });
      toast.success('Created', 'Checklist created successfully');
      setShowCreateModal(false);
      resetForm();
      fetchData();
    } catch (error) {
      console.error('Failed to create:', error);
      toast.error('Error', 'Could not create checklist');
    } finally {
      setSaving(false);
    }
  };

  const handleSubmitEdit = async () => {
    if (!formData.title.trim()) {
      toast.error('Error', 'Title is required');
      return;
    }

    const validItems = formData.items.filter(item => item.text.trim());
    if (validItems.length === 0) {
      toast.error('Error', 'At least one item is required');
      return;
    }

    setSaving(true);
    try {
      await checklistsAPI.update(selectedChecklist.id, {
        title: formData.title,
        description: formData.description,
        items: validItems.map((item, idx) => ({
          id: item.id,
          text: item.text,
          order: idx,
        })),
      });
      toast.success('Updated', 'Checklist updated successfully');
      setShowEditModal(false);
      resetForm();
      fetchData();
    } catch (error) {
      console.error('Failed to update:', error);
      toast.error('Error', 'Could not update checklist');
    } finally {
      setSaving(false);
    }
  };

  const handleSubmitAssign = async () => {
    if (assignData.selectedProjects.length === 0) {
      toast.error('Error', 'Select at least one project');
      return;
    }

    if (assignData.selectedUsers.length === 0) {
      toast.error('Error', 'Select at least one user');
      return;
    }

    setSaving(true);
    try {
      await checklistsAPI.assign(selectedChecklist.id, {
        checklist_id: selectedChecklist.id,
        project_ids: assignData.selectedProjects,
        user_ids: assignData.selectedUsers,
      });
      toast.success('Assigned', 'Checklist assigned successfully');
      setShowAssignModal(false);
      fetchData();
    } catch (error) {
      console.error('Failed to assign:', error);
      toast.error('Error', 'Could not assign checklist');
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = async () => {
    setSaving(true);
    try {
      await checklistsAPI.delete(selectedChecklist.id);
      toast.success('Deleted', 'Checklist deleted successfully');
      setShowDeleteModal(false);
      fetchData();
    } catch (error) {
      console.error('Failed to delete:', error);
      toast.error('Error', 'Could not delete checklist');
    } finally {
      setSaving(false);
    }
  };

  const toggleProject = (projectId) => {
    setAssignData(prev => ({
      ...prev,
      selectedProjects: prev.selectedProjects.includes(projectId)
        ? prev.selectedProjects.filter(id => id !== projectId)
        : [...prev.selectedProjects, projectId],
    }));
  };

  const toggleUser = (userId) => {
    setAssignData(prev => ({
      ...prev,
      selectedUsers: prev.selectedUsers.includes(userId)
        ? prev.selectedUsers.filter(id => id !== userId)
        : [...prev.selectedUsers, userId],
    }));
  };

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        <ScrollView style={s.scrollView} contentContainerStyle={s.scrollContent} showsVerticalScrollIndicator={false}>
          <View style={s.header}>
            <View style={s.headerLeft}>
              <IconPod size={48}>
                <ClipboardList size={24} strokeWidth={1.5} color="#4ade80" />
              </IconPod>
              <View>
                <Text style={s.headerLabel}>ADMIN</Text>
                <Text style={s.headerTitle}>Checklists</Text>
              </View>
            </View>
            <GlassButton
              variant="primary"
              icon={<Plus size={20} strokeWidth={1.5} color="#fff" />}
              title="Create"
              onPress={handleCreateChecklist}
            />
          </View>

          {loading ? (
            <>
              <GlassSkeleton width="100%" height={100} borderRadiusValue={borderRadius.xl} style={s.mb16} />
              <GlassSkeleton width="100%" height={100} borderRadiusValue={borderRadius.xl} style={s.mb16} />
              <GlassSkeleton width="100%" height={100} borderRadiusValue={borderRadius.xl} />
            </>
          ) : checklists.length === 0 ? (
            <GlassCard style={s.emptyCard}>
              <ClipboardList size={48} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.emptyTitle}>No Checklists</Text>
              <Text style={s.emptyText}>Create your first checklist to get started</Text>
            </GlassCard>
          ) : (
            <View style={s.checklistsList}>
              {checklists.map((checklist) => (
                <GlassCard key={checklist.id} style={s.checklistCard}>
                  <View style={s.checklistHeader}>
                    <View style={s.checklistInfo}>
                      <Text style={s.checklistTitle}>{checklist.title}</Text>
                      {checklist.description && (
                        <Text style={s.checklistDescription} numberOfLines={2}>
                          {checklist.description}
                        </Text>
                      )}
                      <View style={s.checklistMeta}>
                        <Text style={s.metaText}>
                          {checklist.items?.length || 0} items
                        </Text>
                        <Text style={s.metaDot}>•</Text>
                        <Text style={s.metaText}>
                          {checklist.assignment_count || 0} assignments
                        </Text>
                      </View>
                    </View>
                  </View>

                  <View style={s.checklistActions}>
                    <Pressable
                      onPress={() => handleViewAssignments(checklist)}
                      style={s.actionButton}
                    >
                      <Eye size={18} strokeWidth={1.5} color={colors.text.secondary} />
                    </Pressable>
                    <Pressable
                      onPress={() => handleAssignChecklist(checklist)}
                      style={s.actionButton}
                    >
                      <Send size={18} strokeWidth={1.5} color="#4ade80" />
                    </Pressable>
                    <Pressable
                      onPress={() => handleEditChecklist(checklist)}
                      style={s.actionButton}
                    >
                      <Edit2 size={18} strokeWidth={1.5} color="#60a5fa" />
                    </Pressable>
                    <Pressable
                      onPress={() => handleDeleteChecklist(checklist)}
                      style={s.actionButton}
                    >
                      <Trash2 size={18} strokeWidth={1.5} color="#ef4444" />
                    </Pressable>
                  </View>
                </GlassCard>
              ))}
            </View>
          )}
        </ScrollView>

        <FloatingNav activeRoute="/admin/checklists" />

        {/* Create/Edit Modal */}
        <Modal
          visible={showCreateModal || showEditModal}
          animationType="slide"
          transparent
          onRequestClose={() => {
            setShowCreateModal(false);
            setShowEditModal(false);
            resetForm();
          }}
        >
          <View style={s.modalOverlay}>
            <View style={s.modalContent}>
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>
                  {showCreateModal ? 'Create Checklist' : 'Edit Checklist'}
                </Text>
                <Pressable
                  onPress={() => {
                    setShowCreateModal(false);
                    setShowEditModal(false);
                    resetForm();
                  }}
                >
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>

              <ScrollView style={s.modalScroll} showsVerticalScrollIndicator={false}>
                <GlassInput
                  label="Title"
                  value={formData.title}
                  onChangeText={(text) => setFormData({ ...formData, title: text })}
                  placeholder="Safety Inspection"
                  style={s.input}
                />

                <GlassInput
                  label="Description (Optional)"
                  value={formData.description}
                  onChangeText={(text) => setFormData({ ...formData, description: text })}
                  placeholder="Describe the checklist..."
                  multiline
                  numberOfLines={2}
                  style={s.input}
                />

                <Text style={s.sectionLabel}>ITEMS</Text>
                {formData.items.map((item, index) => (
                  <View key={index} style={s.itemRow}>
                    <TextInput
                      style={s.itemInput}
                      value={item.text}
                      onChangeText={(text) => updateItem(index, text)}
                      placeholder={`Item ${index + 1}`}
                      placeholderTextColor={colors.text.subtle}
                    />
                    {formData.items.length > 1 && (
                      <Pressable onPress={() => removeItem(index)} style={s.removeBtn}>
                        <X size={18} strokeWidth={1.5} color="#ef4444" />
                      </Pressable>
                    )}
                  </View>
                ))}

                <GlassButton
                  variant="secondary"
                  title="Add Item"
                  icon={<Plus size={20} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={addItem}
                  style={s.addItemBtn}
                />
              </ScrollView>

              <View style={s.modalActions}>
                <GlassButton
                  variant="secondary"
                  title="Cancel"
                  onPress={() => {
                    setShowCreateModal(false);
                    setShowEditModal(false);
                    resetForm();
                  }}
                  style={s.modalBtn}
                />
                <GlassButton
                  variant="primary"
                  title={saving ? 'Saving...' : showCreateModal ? 'Create' : 'Update'}
                  onPress={showCreateModal ? handleSubmitCreate : handleSubmitEdit}
                  loading={saving}
                  style={s.modalBtn}
                />
              </View>
            </View>
          </View>
        </Modal>

        {/* Assign Modal */}
        <Modal
          visible={showAssignModal}
          animationType="slide"
          transparent
          onRequestClose={() => setShowAssignModal(false)}
        >
          <View style={s.modalOverlay}>
            <View style={s.modalContent}>
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>Assign Checklist</Text>
                <Pressable onPress={() => setShowAssignModal(false)}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>

              <ScrollView style={s.modalScroll} showsVerticalScrollIndicator={false}>
                <Text style={s.sectionLabel}>SELECT PROJECTS</Text>
                {projects.map((project) => (
                  <Pressable
                    key={project.id}
                    onPress={() => toggleProject(project.id)}
                    style={s.selectItem}
                  >
                    <View
                      style={[
                        s.checkbox,
                        assignData.selectedProjects.includes(project.id) && s.checkboxChecked,
                      ]}
                    >
                      {assignData.selectedProjects.includes(project.id) && (
                        <Check size={14} strokeWidth={2} color="#fff" />
                      )}
                    </View>
                    <Text style={s.selectText}>{project.name}</Text>
                  </Pressable>
                ))}

                <Text style={[s.sectionLabel, s.mt24]}>SELECT USERS</Text>
                {users.map((user) => (
                  <Pressable
                    key={user.id}
                    onPress={() => toggleUser(user.id)}
                    style={s.selectItem}
                  >
                    <View
                      style={[
                        s.checkbox,
                        assignData.selectedUsers.includes(user.id) && s.checkboxChecked,
                      ]}
                    >
                      {assignData.selectedUsers.includes(user.id) && (
                        <Check size={14} strokeWidth={2} color="#fff" />
                      )}
                    </View>
                    <View>
                      <Text style={s.selectText}>{user.name}</Text>
                      <Text style={s.selectSubtext}>{user.email}</Text>
                    </View>
                  </Pressable>
                ))}
              </ScrollView>

              <View style={s.modalActions}>
                <GlassButton
                  variant="secondary"
                  title="Cancel"
                  onPress={() => setShowAssignModal(false)}
                  style={s.modalBtn}
                />
                <GlassButton
                  variant="primary"
                  title={saving ? 'Assigning...' : 'Assign'}
                  onPress={handleSubmitAssign}
                  loading={saving}
                  style={s.modalBtn}
                />
              </View>
            </View>
          </View>
        </Modal>

        {/* View Assignments Modal */}
        <Modal
          visible={showViewModal}
          animationType="slide"
          transparent
          onRequestClose={() => setShowViewModal(false)}
        >
          <View style={s.modalOverlay}>
            <View style={s.modalContent}>
              <View style={s.modalHeader}>
                <Text style={s.modalTitle}>Assignments</Text>
                <Pressable onPress={() => setShowViewModal(false)}>
                  <X size={24} strokeWidth={1.5} color={colors.text.muted} />
                </Pressable>
              </View>

              <ScrollView style={s.modalScroll} showsVerticalScrollIndicator={false}>
                {assignments.length === 0 ? (
                  <Text style={s.emptyText}>No assignments yet</Text>
                ) : (
                  assignments.map((assignment) => (
                    <GlassCard key={assignment.id} style={s.assignmentCard}>
                      <Text style={s.assignmentProject}>{assignment.project_name}</Text>
                      <View style={s.assignmentUsers}>
                        {assignment.assigned_users?.map((user) => {
                          const completion = assignment.completions?.find(c => c.user_id === user.id);
                          const isComplete = completion?.progress?.completed === completion?.progress?.total;

                          return (
                            <View key={user.id} style={s.userRow}>
                              <View style={s.userInfo}>
                                <Text style={s.userName}>{user.name}</Text>
                                {completion && (
                                  <Text style={s.userProgress}>
                                    {completion.progress.completed}/{completion.progress.total}
                                  </Text>
                                )}
                              </View>
                              {isComplete && (
                                <CheckCircle size={16} strokeWidth={1.5} color="#4ade80" />
                              )}
                            </View>
                          );
                        })}
                      </View>
                    </GlassCard>
                  ))
                )}
              </ScrollView>

              <GlassButton
                variant="secondary"
                title="Close"
                onPress={() => setShowViewModal(false)}
                style={s.closeBtn}
              />
            </View>
          </View>
        </Modal>

        {/* Delete Confirmation Modal */}
        <Modal
          visible={showDeleteModal}
          animationType="fade"
          transparent
          onRequestClose={() => setShowDeleteModal(false)}
        >
          <View style={s.modalOverlay}>
            <View style={s.deleteModal}>
              <View style={s.deleteIcon}>
                <Trash2 size={32} strokeWidth={1.5} color="#ef4444" />
              </View>
              <Text style={s.deleteTitle}>Delete Checklist?</Text>
              <Text style={s.deleteText}>
                This will delete the checklist and all its assignments. This cannot be undone.
              </Text>
              <View style={s.deleteActions}>
                <GlassButton
                  variant="secondary"
                  title="Cancel"
                  onPress={() => setShowDeleteModal(false)}
                  style={s.deleteBtn}
                />
                <Pressable
                  onPress={confirmDelete}
                  style={s.deleteConfirmBtn}
                  disabled={saving}
                >
                  <Text style={s.deleteConfirmText}>
                    {saving ? 'Deleting...' : 'Delete'}
                  </Text>
                </Pressable>
              </View>
            </View>
          </View>
        </Modal>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: { flex: 1 },
  scrollView: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 120 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.xl },
  headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  headerLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.xs },
  headerTitle: { fontSize: 28, fontWeight: '200', color: colors.text.primary, letterSpacing: -0.5 },
  mb16: { marginBottom: spacing.md },
  emptyCard: { alignItems: 'center', paddingVertical: spacing.xxl },
  emptyTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary, marginTop: spacing.md },
  emptyText: { fontSize: 14, color: colors.text.muted, marginTop: spacing.xs },
  checklistsList: { gap: spacing.md },
  checklistCard: { padding: spacing.lg },
  checklistHeader: { marginBottom: spacing.md },
  checklistInfo: { flex: 1 },
  checklistTitle: { fontSize: 18, fontWeight: '500', color: colors.text.primary, marginBottom: spacing.xs },
  checklistDescription: { fontSize: 14, color: colors.text.secondary, marginBottom: spacing.sm },
  checklistMeta: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  metaText: { fontSize: 12, color: colors.text.muted },
  metaDot: { fontSize: 12, color: colors.text.subtle },
  checklistActions: { flexDirection: 'row', gap: spacing.sm },
  actionButton: { padding: spacing.sm, backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: borderRadius.md },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'center', alignItems: 'center', padding: spacing.lg },
  modalContent: { backgroundColor: '#1a1a2e', borderRadius: borderRadius.xxl, width: '100%', maxWidth: 500, maxHeight: '80%', borderWidth: 1, borderColor: colors.glass.border },
  modalHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.glass.border },
  modalTitle: { fontSize: 20, fontWeight: '500', color: colors.text.primary },
  modalScroll: { padding: spacing.lg },
  input: { marginBottom: spacing.md },
  sectionLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.sm },
  itemRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  itemInput: { flex: 1, backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: borderRadius.lg, borderWidth: 1, borderColor: colors.glass.border, padding: spacing.md, color: colors.text.primary, fontSize: 14 },
  removeBtn: { padding: spacing.sm },
  addItemBtn: { marginTop: spacing.sm },
  modalActions: { flexDirection: 'row', gap: spacing.md, padding: spacing.lg, borderTopWidth: 1, borderTopColor: colors.glass.border },
  modalBtn: { flex: 1 },
  selectItem: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.glass.border },
  checkbox: { width: 20, height: 20, borderRadius: 4, borderWidth: 1, borderColor: colors.glass.border, backgroundColor: 'rgba(255,255,255,0.05)', alignItems: 'center', justifyContent: 'center' },
  checkboxChecked: { backgroundColor: '#4ade80', borderColor: '#4ade80' },
  selectText: { fontSize: 14, color: colors.text.primary },
  selectSubtext: { fontSize: 12, color: colors.text.muted, marginTop: 2 },
  mt24: { marginTop: spacing.lg },
  assignmentCard: { marginBottom: spacing.md, padding: spacing.md },
  assignmentProject: { fontSize: 16, fontWeight: '500', color: colors.text.primary, marginBottom: spacing.sm },
  assignmentUsers: { gap: spacing.sm },
  userRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: spacing.xs },
  userInfo: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  userName: { fontSize: 14, color: colors.text.secondary },
  userProgress: { fontSize: 12, color: colors.text.muted },
  closeBtn: { margin: spacing.lg },
  deleteModal: { backgroundColor: '#1a1a2e', borderRadius: borderRadius.xxl, padding: spacing.xl, width: '90%', maxWidth: 400, borderWidth: 1, borderColor: colors.glass.border, alignItems: 'center' },
  deleteIcon: { width: 64, height: 64, borderRadius: 32, backgroundColor: 'rgba(239,68,68,0.1)', alignItems: 'center', justifyContent: 'center', marginBottom: spacing.lg },
  deleteTitle: { fontSize: 20, fontWeight: '600', color: colors.text.primary, marginBottom: spacing.sm },
  deleteText: { fontSize: 14, color: colors.text.secondary, textAlign: 'center', marginBottom: spacing.xl },
  deleteActions: { flexDirection: 'row', gap: spacing.md, width: '100%' },
  deleteBtn: { flex: 1 },
  deleteConfirmBtn: { flex: 1, backgroundColor: '#ef4444', borderRadius: borderRadius.lg, padding: spacing.md, alignItems: 'center', justifyContent: 'center' },
  deleteConfirmText: { fontSize: 16, fontWeight: '500', color: '#fff' },
});
}
