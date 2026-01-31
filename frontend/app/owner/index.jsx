import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Alert,
  Platform,
  TextInput,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Lock,
  LogOut,
  Building2,
  Plus,
  Edit3,
  Trash2,
  Mail,
  Calendar,
  CheckCircle,
  XCircle,
  Share2,
  Eye,
  EyeOff,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { adminUsersAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

const OWNER_PASSWORD = 'blueview2024'; // In real app, would be server-validated

export default function OwnerPortalScreen() {
  const router = useRouter();
  const toast = useToast();

  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  
  // Admin management
  const [admins, setAdmins] = useState([]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [selectedAdmin, setSelectedAdmin] = useState(null);
  
  // Form fields
  const [formCompanyName, setFormCompanyName] = useState('');
  const [formContactName, setFormContactName] = useState('');
  const [formEmail, setFormEmail] = useState('');
  const [formPassword, setFormPassword] = useState('');

  useEffect(() => {
    if (isAuthenticated) {
      fetchAdmins();
    }
  }, [isAuthenticated]);

  const handleLogin = () => {
    if (password === OWNER_PASSWORD) {
      setIsAuthenticated(true);
      setPassword('');
      toast.success('Welcome', 'Owner portal access granted');
    } else {
      toast.error('Access Denied', 'Invalid password');
    }
  };

  const handleLogout = () => {
    setIsAuthenticated(false);
    setPassword('');
  };

  const fetchAdmins = async () => {
    setLoading(true);
    try {
      // Fetch admin users from API
      const usersData = await adminUsersAPI.getAll().catch(() => []);
      // Filter to only show admin role users
      const adminUsers = Array.isArray(usersData) 
        ? usersData.filter(u => u.role === 'admin').map(u => ({
            id: u.id || u._id,
            company_name: u.company_name || 'Individual Admin',
            contact_name: u.name,
            email: u.email,
            created_at: u.created_at ? new Date(u.created_at).toISOString().split('T')[0] : 'N/A',
            status: 'active',
          }))
        : [];
      setAdmins(adminUsers);
    } catch (error) {
      console.error('Failed to fetch admins:', error);
      toast.error('Error', 'Could not load admin accounts');
    } finally {
      setLoading(false);
    }
  };

  const handleAddAdmin = async () => {
    if (!formCompanyName.trim() || !formContactName.trim() || !formEmail.trim() || !formPassword.trim()) {
      toast.error('Error', 'Please fill in all fields');
      return;
    }

    try {
      const newAdmin = await adminUsersAPI.create({
        name: formContactName,
        company_name: formCompanyName,
        email: formEmail,
        password: formPassword,
        role: 'admin',
      });
      
      setAdmins([...admins, {
        id: newAdmin.id || newAdmin._id,
        company_name: formCompanyName,
        contact_name: formContactName,
        email: formEmail,
        created_at: new Date().toISOString().split('T')[0],
        status: 'active',
      }]);
      resetForm();
      setShowAddModal(false);
      toast.success('Created', 'Admin account created successfully');
    } catch (error) {
      console.error('Failed to create admin:', error);
      toast.error('Error', 'Backend does not support admin creation yet');
    }
  };

  const handleEditAdmin = async () => {
    if (!selectedAdmin) return;
    
    try {
      await adminUsersAPI.update(selectedAdmin.id, {
        name: formContactName,
        company_name: formCompanyName,
        email: formEmail,
      });
      
      const updated = admins.map(a => 
        a.id === selectedAdmin.id 
          ? { ...a, company_name: formCompanyName, contact_name: formContactName, email: formEmail }
          : a
      );
      
      setAdmins(updated);
      resetForm();
      setShowEditModal(false);
      toast.success('Updated', 'Admin account updated');
    } catch (error) {
      console.error('Failed to update admin:', error);
      toast.error('Error', 'Backend does not support admin updates yet');
    }
  };

  const handleDeleteAdmin = (adminId) => {
    const admin = admins.find(a => a.id === adminId);
    const confirmDelete = async () => {
      try {
        await adminUsersAPI.delete(adminId);
        setAdmins(admins.filter(a => a.id !== adminId));
        toast.success('Deleted', 'Admin account removed');
      } catch (error) {
        console.error('Failed to delete admin:', error);
        toast.error('Error', 'Backend does not support admin deletion yet');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm(`Delete ${admin?.company_name}? This will remove all associated data.`)) {
        confirmDelete();
      }
    } else {
      Alert.alert(
        'Delete Admin',
        `Delete ${admin?.company_name}? This will remove all associated data.`,
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Delete', style: 'destructive', onPress: confirmDelete },
        ]
      );
    }
  };

  const handleShareCredentials = (admin) => {
    const credentials = `Company: ${admin.company_name}\nEmail: ${admin.email}\nLogin URL: https://blueview.app/login`;
    
    if (Platform.OS === 'web') {
      navigator.clipboard?.writeText(credentials);
      toast.success('Copied', 'Credentials copied to clipboard');
    } else {
      toast.info('Credentials', `Email: ${admin.email}`);
    }
  };

  const openEditModal = (admin) => {
    setSelectedAdmin(admin);
    setFormCompanyName(admin.company_name);
    setFormContactName(admin.contact_name);
    setFormEmail(admin.email);
    setShowEditModal(true);
  };

  const resetForm = () => {
    setFormCompanyName('');
    setFormContactName('');
    setFormEmail('');
    setFormPassword('');
    setSelectedAdmin(null);
  };

  const activeCount = admins.filter(a => a.status === 'active').length;

  // Login Screen
  if (!isAuthenticated) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.loginContent}>
            <View style={styles.lockIcon}>
              <Lock size={48} strokeWidth={1} color={colors.text.primary} />
            </View>
            
            <Text style={styles.loginTitle}>Owner Portal</Text>
            <Text style={styles.loginSubtitle}>
              Master administration for Blueview platform
            </Text>

            <GlassCard style={styles.loginCard}>
              <GlassInput
                value={password}
                onChangeText={setPassword}
                placeholder="Enter owner password"
                secureTextEntry={!showPassword}
                rightIcon={
                  <Pressable onPress={() => setShowPassword(!showPassword)}>
                    {showPassword ? (
                      <EyeOff size={20} color={colors.text.muted} />
                    ) : (
                      <Eye size={20} color={colors.text.muted} />
                    )}
                  </Pressable>
                }
              />
              
              <GlassButton
                title="Access Portal"
                icon={<Lock size={18} color={colors.text.primary} />}
                onPress={handleLogin}
                style={styles.loginBtn}
              />
            </GlassCard>

            <Pressable onPress={() => router.back()} style={styles.backLink}>
              <Text style={styles.backLinkText}>← Return to app</Text>
            </Pressable>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  // Owner Dashboard
  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <IconPod size={44}>
              <Lock size={20} strokeWidth={1.5} color={colors.text.primary} />
            </IconPod>
            <Text style={styles.logoText}>OWNER PORTAL</Text>
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
          {/* Stats */}
          <View style={styles.statsRow}>
            <StatCard style={styles.statCard}>
              <IconPod size={40}>
                <Building2 size={18} strokeWidth={1.5} color={colors.text.secondary} />
              </IconPod>
              <Text style={styles.statValue}>{admins.length}</Text>
              <Text style={styles.statLabel}>COMPANIES</Text>
            </StatCard>
            <StatCard style={styles.statCard}>
              <IconPod size={40}>
                <CheckCircle size={18} strokeWidth={1.5} color="#10b981" />
              </IconPod>
              <Text style={styles.statValue}>{activeCount}</Text>
              <Text style={styles.statLabel}>ACTIVE</Text>
            </StatCard>
          </View>

          {/* Admin List Header */}
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Admin Accounts</Text>
            <GlassButton
              title="Create Admin"
              icon={<Plus size={16} color={colors.text.primary} />}
              onPress={() => setShowAddModal(true)}
            />
          </View>

          {/* Admin List */}
          {loading ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color={colors.text.primary} />
            </View>
          ) : (
            <View style={styles.adminList}>
              {admins.map((admin) => (
                <GlassCard key={admin.id} style={styles.adminCard}>
                  <View style={styles.adminHeader}>
                    <View style={styles.adminInfo}>
                      <Text style={styles.companyName}>{admin.company_name}</Text>
                      <Text style={styles.contactName}>{admin.contact_name}</Text>
                    </View>
                    <View style={[
                      styles.statusBadge,
                      admin.status === 'active' ? styles.statusActive : styles.statusInactive
                    ]}>
                      <Text style={[
                        styles.statusText,
                        admin.status === 'active' ? styles.statusTextActive : styles.statusTextInactive
                      ]}>
                        {admin.status.toUpperCase()}
                      </Text>
                    </View>
                  </View>

                  <View style={styles.adminDetails}>
                    <View style={styles.detailRow}>
                      <Mail size={14} color={colors.text.muted} />
                      <Text style={styles.detailText}>{admin.email}</Text>
                    </View>
                    <View style={styles.detailRow}>
                      <Calendar size={14} color={colors.text.muted} />
                      <Text style={styles.detailText}>Created: {admin.created_at}</Text>
                    </View>
                  </View>

                  <View style={styles.adminActions}>
                    <GlassButton
                      title="Share"
                      icon={<Share2 size={14} color={colors.text.primary} />}
                      onPress={() => handleShareCredentials(admin)}
                      style={styles.actionBtn}
                    />
                    <GlassButton
                      title="Edit"
                      icon={<Edit3 size={14} color={colors.text.primary} />}
                      onPress={() => openEditModal(admin)}
                      style={styles.actionBtn}
                    />
                    <Pressable 
                      onPress={() => handleDeleteAdmin(admin.id)}
                      style={styles.deleteBtn}
                    >
                      <Trash2 size={16} color={colors.status.error} />
                    </Pressable>
                  </View>
                </GlassCard>
              ))}
            </View>
          )}

          {/* Add Modal */}
          {showAddModal && (
            <GlassCard style={styles.modal}>
              <Text style={styles.modalTitle}>Create Admin Account</Text>
              
              <GlassInput
                value={formCompanyName}
                onChangeText={setFormCompanyName}
                placeholder="Company Name"
                leftIcon={<Building2 size={18} color={colors.text.subtle} />}
              />
              <GlassInput
                value={formContactName}
                onChangeText={setFormContactName}
                placeholder="Contact Name"
                style={styles.inputSpacing}
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

              <View style={styles.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => { setShowAddModal(false); resetForm(); }}
                />
                <GlassButton
                  title="Create"
                  onPress={handleAddAdmin}
                />
              </View>
            </GlassCard>
          )}

          {/* Edit Modal */}
          {showEditModal && (
            <GlassCard style={styles.modal}>
              <Text style={styles.modalTitle}>Edit Admin Account</Text>
              
              <GlassInput
                value={formCompanyName}
                onChangeText={setFormCompanyName}
                placeholder="Company Name"
                leftIcon={<Building2 size={18} color={colors.text.subtle} />}
              />
              <GlassInput
                value={formContactName}
                onChangeText={setFormContactName}
                placeholder="Contact Name"
                style={styles.inputSpacing}
              />
              <GlassInput
                value={formEmail}
                onChangeText={setFormEmail}
                placeholder="Email"
                keyboardType="email-address"
                leftIcon={<Mail size={18} color={colors.text.subtle} />}
                style={styles.inputSpacing}
              />

              <View style={styles.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => { setShowEditModal(false); resetForm(); }}
                />
                <GlassButton
                  title="Save"
                  onPress={handleEditAdmin}
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
  loginContent: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  lockIcon: {
    width: 100,
    height: 100,
    borderRadius: 50,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.xl,
  },
  loginTitle: {
    fontSize: 32,
    fontWeight: '200',
    color: colors.text.primary,
    marginBottom: spacing.sm,
  },
  loginSubtitle: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    marginBottom: spacing.xl,
  },
  loginCard: {
    width: '100%',
    maxWidth: 400,
  },
  loginBtn: {
    marginTop: spacing.lg,
  },
  backLink: {
    marginTop: spacing.xl,
  },
  backLinkText: {
    fontSize: 14,
    color: colors.text.muted,
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
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
  },
  statValue: {
    fontSize: 32,
    fontWeight: '200',
    color: colors.text.primary,
    marginTop: spacing.sm,
  },
  statLabel: {
    ...typography.label,
    fontSize: 9,
    color: colors.text.muted,
    marginTop: spacing.xs,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  sectionTitle: {
    fontSize: 20,
    fontWeight: '400',
    color: colors.text.primary,
  },
  loadingContainer: {
    paddingVertical: spacing.xxl,
    alignItems: 'center',
  },
  adminList: {
    gap: spacing.md,
  },
  adminCard: {
    marginBottom: 0,
  },
  adminHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: spacing.md,
  },
  adminInfo: {
    flex: 1,
  },
  companyName: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
  },
  contactName: {
    fontSize: 14,
    color: colors.text.muted,
  },
  statusBadge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.sm,
  },
  statusActive: {
    backgroundColor: 'rgba(16, 185, 129, 0.2)',
  },
  statusInactive: {
    backgroundColor: 'rgba(156, 163, 175, 0.2)',
  },
  statusText: {
    fontSize: 10,
    fontWeight: '600',
  },
  statusTextActive: {
    color: '#10b981',
  },
  statusTextInactive: {
    color: '#9ca3af',
  },
  adminDetails: {
    gap: spacing.sm,
    marginBottom: spacing.md,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.glass.border,
  },
  detailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  detailText: {
    fontSize: 13,
    color: colors.text.secondary,
  },
  adminActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  actionBtn: {
    flex: 1,
  },
  deleteBtn: {
    padding: spacing.md,
    borderRadius: borderRadius.md,
    backgroundColor: colors.glass.background,
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
  inputSpacing: {
    marginTop: spacing.sm,
  },
  modalActions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: spacing.sm,
    marginTop: spacing.lg,
  },
});
