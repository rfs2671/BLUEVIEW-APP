import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Alert,
  Platform,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  Users,
  Plus,
  Edit3,
  Trash2,
  Mail,
  Shield,
  ShieldAlert,
  FolderOpen,
  CheckCircle,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { adminUsersAPI, projectsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

export default function AdminUsersScreen() {
  const router = useRouter();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [users, setUsers] = useState([]);
  const [projects, setProjects] = useState([]);
  
  // Modal states
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showAssignModal, setShowAssignModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState(null);
  
  // Form fields
  const [formName, setFormName] = useState('');
  const [formEmail, setFormEmail] = useState('');
  const [formRole, setFormRole] = useState('cp');
  const [formPassword, setFormPassword] = useState('');
  const [assignedProjects, setAssignedProjects] = useState([]);

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    }
  }, [isAuthenticated]);

  const fetchData = async () => {
    try {
      // Fetch real data from API
      const [usersData, projectsData] = await Promise.all([
        adminUsersAPI.getAll().catch(() => []),
        projectsAPI.getAll().catch(() => []),
      ]);
      
      setUsers(Array.isArray(usersData) ? usersData : []);
      setProjects(Array.isArray(projectsData) ? projectsData.map(p => ({
        id: p.id || p._id,
        name: p.name,
      })) : []);
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Error', 'Could not load users');
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

  const handleAddUser = () => {
    if (!formName.trim() || !formEmail.trim() || !formPassword.trim()) {
      toast.error('Error', 'Please fill in all required fields');
      return;
    }

    const newUser = {
      id: Date.now().toString(),
      name: formName,
      email: formEmail,
      role: formRole,
      assigned_projects: [],
    };

    setUsers([...users, newUser]);
    resetForm();
    setShowAddModal(false);
    toast.success('Added', 'User created successfully');
  };

  const handleEditUser = () => {
    if (!selectedUser) return;
    
    const updated = users.map(u => 
      u.id === selectedUser.id 
        ? { ...u, name: formName, email: formEmail, role: formRole }
        : u
    );
    
    setUsers(updated);
    resetForm();
    setShowEditModal(false);
    toast.success('Updated', 'User updated successfully');
  };

  const handleDeleteUser = (userId) => {
    const confirmDelete = () => {
      setUsers(users.filter(u => u.id !== userId));
      toast.success('Deleted', 'User removed');
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Delete this user?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Delete User', 'Are you sure you want to delete this user?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const handleAssignProjects = () => {
    if (!selectedUser) return;
    
    const updated = users.map(u => 
      u.id === selectedUser.id 
        ? { ...u, assigned_projects: assignedProjects }
        : u
    );
    
    setUsers(updated);
    setShowAssignModal(false);
    toast.success('Updated', 'Projects assigned');
  };

  const toggleProjectAssignment = (projectId) => {
    setAssignedProjects(prev => 
      prev.includes(projectId)
        ? prev.filter(id => id !== projectId)
        : [...prev, projectId]
    );
  };

  const openEditModal = (userItem) => {
    setSelectedUser(userItem);
    setFormName(userItem.name);
    setFormEmail(userItem.email);
    setFormRole(userItem.role);
    setShowEditModal(true);
  };

  const openAssignModal = (userItem) => {
    setSelectedUser(userItem);
    setAssignedProjects(userItem.assigned_projects || []);
    setShowAssignModal(true);
  };

  const resetForm = () => {
    setFormName('');
    setFormEmail('');
    setFormRole('cp');
    setFormPassword('');
    setSelectedUser(null);
  };

  const getRoleBadgeStyle = (role) => {
    switch (role) {
      case 'admin': return { bg: 'rgba(239, 68, 68, 0.2)', color: '#f87171' };
      case 'cp': return { bg: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa' };
      default: return { bg: 'rgba(156, 163, 175, 0.2)', color: '#9ca3af' };
    }
  };

  if (!isAdmin) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.accessDenied}>
            <ShieldAlert size={56} strokeWidth={1} color={colors.status.error} />
            <Text style={styles.accessDeniedTitle}>Admin Access Required</Text>
            <Text style={styles.accessDeniedDesc}>
              Only administrators can access user management.
            </Text>
            <GlassButton
              title="Return to Dashboard"
              onPress={() => router.push('/')}
              style={styles.returnBtn}
            />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

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
          <View style={styles.headerRight}>
            <GlassButton
              variant="icon"
              icon={<Plus size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => setShowAddModal(true)}
            />
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
          </View>
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.text.primary} />
          }
        >
          {/* Title */}
          <View style={styles.titleSection}>
            <Text style={styles.titleLabel}>ADMIN</Text>
            <View style={styles.titleRow}>
              <Text style={styles.titleText}>User Management</Text>
              <View style={styles.countBadge}>
                <Text style={styles.countText}>{users.length}</Text>
              </View>
            </View>
          </View>

          {loading ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color={colors.text.primary} />
            </View>
          ) : (
            <View style={styles.usersList}>
              {users.map((userItem) => {
                const roleStyle = getRoleBadgeStyle(userItem.role);
                return (
                  <GlassCard key={userItem.id} style={styles.userCard}>
                    <View style={styles.userHeader}>
                      <View style={styles.userAvatar}>
                        <Text style={styles.userInitial}>{userItem.name?.charAt(0) || 'U'}</Text>
                      </View>
                      <View style={styles.userInfo}>
                        <Text style={styles.userName}>{userItem.name}</Text>
                        <Text style={styles.userEmail}>{userItem.email}</Text>
                      </View>
                      <View style={[styles.roleBadge, { backgroundColor: roleStyle.bg }]}>
                        <Text style={[styles.roleText, { color: roleStyle.color }]}>
                          {userItem.role.toUpperCase()}
                        </Text>
                      </View>
                    </View>

                    {userItem.assigned_projects?.length > 0 && (
                      <View style={styles.projectsRow}>
                        <FolderOpen size={14} color={colors.text.muted} />
                        <Text style={styles.projectsText}>
                          {userItem.assigned_projects.length} project(s) assigned
                        </Text>
                      </View>
                    )}

                    <View style={styles.userActions}>
                      <GlassButton
                        title="Assign"
                        icon={<FolderOpen size={14} color={colors.text.primary} />}
                        onPress={() => openAssignModal(userItem)}
                        style={styles.actionBtn}
                      />
                      <GlassButton
                        title="Edit"
                        icon={<Edit3 size={14} color={colors.text.primary} />}
                        onPress={() => openEditModal(userItem)}
                        style={styles.actionBtn}
                      />
                      <Pressable 
                        onPress={() => handleDeleteUser(userItem.id)}
                        style={styles.deleteBtn}
                      >
                        <Trash2 size={16} color={colors.status.error} />
                      </Pressable>
                    </View>
                  </GlassCard>
                );
              })}

              {users.length === 0 && (
                <GlassCard style={styles.emptyCard}>
                  <Users size={48} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={styles.emptyText}>No users found</Text>
                  <GlassButton
                    title="Add User"
                    icon={<Plus size={16} color={colors.text.primary} />}
                    onPress={() => setShowAddModal(true)}
                  />
                </GlassCard>
              )}
            </View>
          )}

          {/* Add User Modal */}
          {showAddModal && (
            <GlassCard style={styles.modal}>
              <Text style={styles.modalTitle}>Add New User</Text>
              <GlassInput
                value={formName}
                onChangeText={setFormName}
                placeholder="Full Name"
              />
              <GlassInput
                value={formEmail}
                onChangeText={setFormEmail}
                placeholder="Email"
                keyboardType="email-address"
                leftIcon={<Mail size={18} color={colors.text.subtle} />}
                style={styles.inputSpacing}
              />
              <GlassInput
                value={formPassword}
                onChangeText={setFormPassword}
                placeholder="Password"
                secureTextEntry
                style={styles.inputSpacing}
              />
              <View style={styles.roleSelector}>
                <Text style={styles.roleSelectorLabel}>Role:</Text>
                <Pressable
                  onPress={() => setFormRole('cp')}
                  style={[styles.roleOption, formRole === 'cp' && styles.roleOptionActive]}
                >
                  <Text style={[styles.roleOptionText, formRole === 'cp' && styles.roleOptionTextActive]}>
                    CP Manager
                  </Text>
                </Pressable>
                <Pressable
                  onPress={() => setFormRole('worker')}
                  style={[styles.roleOption, formRole === 'worker' && styles.roleOptionActive]}
                >
                  <Text style={[styles.roleOptionText, formRole === 'worker' && styles.roleOptionTextActive]}>
                    Worker
                  </Text>
                </Pressable>
              </View>
              <View style={styles.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => { setShowAddModal(false); resetForm(); }}
                />
                <GlassButton
                  title="Add User"
                  onPress={handleAddUser}
                />
              </View>
            </GlassCard>
          )}

          {/* Edit User Modal */}
          {showEditModal && (
            <GlassCard style={styles.modal}>
              <Text style={styles.modalTitle}>Edit User</Text>
              <GlassInput
                value={formName}
                onChangeText={setFormName}
                placeholder="Full Name"
              />
              <GlassInput
                value={formEmail}
                onChangeText={setFormEmail}
                placeholder="Email"
                keyboardType="email-address"
                style={styles.inputSpacing}
              />
              <View style={styles.roleSelector}>
                <Text style={styles.roleSelectorLabel}>Role:</Text>
                <Pressable
                  onPress={() => setFormRole('cp')}
                  style={[styles.roleOption, formRole === 'cp' && styles.roleOptionActive]}
                >
                  <Text style={[styles.roleOptionText, formRole === 'cp' && styles.roleOptionTextActive]}>
                    CP Manager
                  </Text>
                </Pressable>
                <Pressable
                  onPress={() => setFormRole('worker')}
                  style={[styles.roleOption, formRole === 'worker' && styles.roleOptionActive]}
                >
                  <Text style={[styles.roleOptionText, formRole === 'worker' && styles.roleOptionTextActive]}>
                    Worker
                  </Text>
                </Pressable>
              </View>
              <View style={styles.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => { setShowEditModal(false); resetForm(); }}
                />
                <GlassButton
                  title="Save"
                  onPress={handleEditUser}
                />
              </View>
            </GlassCard>
          )}

          {/* Assign Projects Modal */}
          {showAssignModal && (
            <GlassCard style={styles.modal}>
              <Text style={styles.modalTitle}>Assign Projects</Text>
              <Text style={styles.modalSubtitle}>Select projects for {selectedUser?.name}</Text>
              <View style={styles.projectsList}>
                {projects.map((proj) => (
                  <Pressable
                    key={proj.id}
                    onPress={() => toggleProjectAssignment(proj.id)}
                    style={[
                      styles.projectItem,
                      assignedProjects.includes(proj.id) && styles.projectItemSelected,
                    ]}
                  >
                    <Text style={styles.projectItemName}>{proj.name}</Text>
                    {assignedProjects.includes(proj.id) && (
                      <CheckCircle size={18} color="#10b981" />
                    )}
                  </Pressable>
                ))}
              </View>
              <View style={styles.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => setShowAssignModal(false)}
                />
                <GlassButton
                  title="Save"
                  onPress={handleAssignProjects}
                />
              </View>
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
  accessDenied: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
    gap: spacing.md,
  },
  accessDeniedTitle: {
    fontSize: 22,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.md,
  },
  accessDeniedDesc: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
  },
  returnBtn: {
    marginTop: spacing.lg,
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
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
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
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  titleText: {
    fontSize: 32,
    fontWeight: '200',
    color: colors.text.primary,
  },
  countBadge: {
    backgroundColor: colors.glass.background,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  countText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text.primary,
  },
  loadingContainer: {
    paddingVertical: spacing.xxl,
    alignItems: 'center',
  },
  usersList: {
    gap: spacing.md,
  },
  userCard: {
    marginBottom: 0,
  },
  userHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  userAvatar: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#3b82f6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  userInitial: {
    fontSize: 20,
    fontWeight: '500',
    color: '#fff',
  },
  userInfo: {
    flex: 1,
  },
  userName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  userEmail: {
    fontSize: 13,
    color: colors.text.muted,
  },
  roleBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
  },
  roleText: {
    fontSize: 10,
    fontWeight: '600',
  },
  projectsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    marginBottom: spacing.md,
  },
  projectsText: {
    fontSize: 12,
    color: colors.text.muted,
  },
  userActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.glass.border,
    paddingTop: spacing.md,
  },
  actionBtn: {
    flex: 1,
  },
  deleteBtn: {
    padding: spacing.md,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 16,
    color: colors.text.muted,
  },
  modal: {
    marginTop: spacing.xl,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.lg,
  },
  modalSubtitle: {
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  inputSpacing: {
    marginTop: spacing.sm,
  },
  roleSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  roleSelectorLabel: {
    fontSize: 14,
    color: colors.text.muted,
  },
  roleOption: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  roleOptionActive: {
    backgroundColor: 'rgba(59, 130, 246, 0.2)',
    borderColor: '#3b82f6',
  },
  roleOptionText: {
    fontSize: 13,
    color: colors.text.muted,
  },
  roleOptionTextActive: {
    color: '#60a5fa',
    fontWeight: '500',
  },
  modalActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
  projectsList: {
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  projectItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: spacing.md,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  projectItemSelected: {
    backgroundColor: 'rgba(16, 185, 129, 0.1)',
    borderColor: 'rgba(16, 185, 129, 0.3)',
  },
  projectItemName: {
    fontSize: 14,
    color: colors.text.primary,
  },
});
