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
  Building2,
  Plus,
  Trash2,
  Mail,
  Phone,
  Users,
  Briefcase,
  ShieldAlert,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { adminSubcontractorsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

export default function AdminSubcontractorsScreen() {
  const router = useRouter();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [subcontractors, setSubcontractors] = useState([]);
  
  // Modal state
  const [showAddModal, setShowAddModal] = useState(false);
  
  // Form fields
  const [formCompanyName, setFormCompanyName] = useState('');
  const [formContactName, setFormContactName] = useState('');
  const [formEmail, setFormEmail] = useState('');
  const [formPhone, setFormPhone] = useState('');
  const [formTrade, setFormTrade] = useState('');
  const [formPassword, setFormPassword] = useState('');

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
      const subsData = await adminSubcontractorsAPI.getAll().catch(() => []);
      setSubcontractors(Array.isArray(subsData) ? subsData.map(sub => ({
        id: sub.id || sub._id,
        company_name: sub.company_name,
        contact_name: sub.contact_name,
        email: sub.email,
        phone: sub.phone,
        trade: sub.trade,
        worker_count: sub.workers_count || 0,
        project_count: sub.assigned_projects?.length || 0,
      })) : []);
    } catch (error) {
      console.error('Failed to fetch data:', error);
      toast.error('Error', 'Could not load subcontractors');
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

  const handleAddSubcontractor = async () => {
    if (!formCompanyName.trim() || !formContactName.trim() || !formEmail.trim()) {
      toast.error('Error', 'Please fill in all required fields');
      return;
    }

    try {
      const newSub = await adminSubcontractorsAPI.create({
        company_name: formCompanyName,
        contact_name: formContactName,
        email: formEmail,
        phone: formPhone,
        trade: formTrade,
        password: formPassword,
      });

      setSubcontractors([...subcontractors, {
        id: newSub.id || newSub._id,
        company_name: formCompanyName,
        contact_name: formContactName,
        email: formEmail,
        phone: formPhone,
        trade: formTrade,
        worker_count: 0,
        project_count: 0,
      }]);
      resetForm();
      setShowAddModal(false);
      toast.success('Added', 'Subcontractor created successfully');
    } catch (error) {
      console.error('Failed to create subcontractor:', error);
      toast.error('Error', 'Backend does not support subcontractor creation yet');
    }
  };

  const handleDeleteSubcontractor = (subId) => {
    const confirmDelete = async () => {
      try {
        await adminSubcontractorsAPI.delete(subId);
        setSubcontractors(subcontractors.filter(s => s.id !== subId));
        toast.success('Deleted', 'Subcontractor removed');
      } catch (error) {
        console.error('Failed to delete subcontractor:', error);
        toast.error('Error', 'Backend does not support deletion yet');
      }
    };

    if (Platform.OS === 'web') {
      if (window.confirm('Delete this subcontractor?')) {
        confirmDelete();
      }
    } else {
      Alert.alert('Delete Subcontractor', 'Are you sure you want to delete this subcontractor?', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: confirmDelete },
      ]);
    }
  };

  const resetForm = () => {
    setFormCompanyName('');
    setFormContactName('');
    setFormEmail('');
    setFormPhone('');
    setFormTrade('');
    setFormPassword('');
  };

  if (!isAdmin) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.accessDenied}>
            <ShieldAlert size={56} strokeWidth={1} color={colors.status.error} />
            <Text style={styles.accessDeniedTitle}>Admin Access Required</Text>
            <Text style={styles.accessDeniedDesc}>
              Only administrators can manage subcontractors.
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
              <Text style={styles.titleText}>Subcontractors</Text>
              <View style={styles.countBadge}>
                <Text style={styles.countText}>{subcontractors.length}</Text>
              </View>
            </View>
          </View>

          {loading ? (
            <View style={styles.loadingContainer}>
              <ActivityIndicator size="large" color={colors.text.primary} />
            </View>
          ) : (
            <View style={styles.subList}>
              {subcontractors.map((sub) => (
                <GlassCard key={sub.id} style={styles.subCard}>
                  <View style={styles.subHeader}>
                    <IconPod size={48}>
                      <Building2 size={22} strokeWidth={1.5} color="#f59e0b" />
                    </IconPod>
                    <View style={styles.subInfo}>
                      <Text style={styles.companyName}>{sub.company_name}</Text>
                      <Text style={styles.contactName}>{sub.contact_name}</Text>
                    </View>
                    <Pressable 
                      onPress={() => handleDeleteSubcontractor(sub.id)}
                      style={styles.deleteBtn}
                    >
                      <Trash2 size={18} color={colors.status.error} />
                    </Pressable>
                  </View>

                  <View style={styles.subDetails}>
                    <View style={styles.detailRow}>
                      <Mail size={14} color={colors.text.muted} />
                      <Text style={styles.detailText}>{sub.email}</Text>
                    </View>
                    {sub.phone && (
                      <View style={styles.detailRow}>
                        <Phone size={14} color={colors.text.muted} />
                        <Text style={styles.detailText}>{sub.phone}</Text>
                      </View>
                    )}
                    {sub.trade && (
                      <View style={styles.detailRow}>
                        <Briefcase size={14} color={colors.text.muted} />
                        <Text style={styles.detailText}>{sub.trade}</Text>
                      </View>
                    )}
                  </View>

                  <View style={styles.statsRow}>
                    <View style={styles.statItem}>
                      <Users size={14} color={colors.text.muted} />
                      <Text style={styles.statText}>{sub.worker_count} workers</Text>
                    </View>
                    <View style={styles.statItem}>
                      <Building2 size={14} color={colors.text.muted} />
                      <Text style={styles.statText}>{sub.project_count} projects</Text>
                    </View>
                  </View>
                </GlassCard>
              ))}

              {subcontractors.length === 0 && (
                <GlassCard style={styles.emptyCard}>
                  <Building2 size={48} strokeWidth={1} color={colors.text.subtle} />
                  <Text style={styles.emptyText}>No subcontractors</Text>
                  <GlassButton
                    title="Add Subcontractor"
                    icon={<Plus size={16} color={colors.text.primary} />}
                    onPress={() => setShowAddModal(true)}
                  />
                </GlassCard>
              )}
            </View>
          )}

          {/* Add Modal */}
          {showAddModal && (
            <GlassCard style={styles.modal}>
              <Text style={styles.modalTitle}>Add Subcontractor</Text>
              
              <GlassInput
                value={formCompanyName}
                onChangeText={setFormCompanyName}
                placeholder="Company Name *"
                leftIcon={<Building2 size={18} color={colors.text.subtle} />}
              />
              <GlassInput
                value={formContactName}
                onChangeText={setFormContactName}
                placeholder="Contact Name *"
                style={styles.inputSpacing}
              />
              <GlassInput
                value={formEmail}
                onChangeText={setFormEmail}
                placeholder="Email *"
                keyboardType="email-address"
                leftIcon={<Mail size={18} color={colors.text.subtle} />}
                style={styles.inputSpacing}
              />
              <GlassInput
                value={formPassword}
                onChangeText={setFormPassword}
                placeholder="Password *"
                secureTextEntry
                style={styles.inputSpacing}
              />
              <GlassInput
                value={formPhone}
                onChangeText={setFormPhone}
                placeholder="Phone"
                keyboardType="phone-pad"
                leftIcon={<Phone size={18} color={colors.text.subtle} />}
                style={styles.inputSpacing}
              />
              <GlassInput
                value={formTrade}
                onChangeText={setFormTrade}
                placeholder="Trade/Specialty"
                leftIcon={<Briefcase size={18} color={colors.text.subtle} />}
                style={styles.inputSpacing}
              />

              <View style={styles.modalActions}>
                <GlassButton
                  title="Cancel"
                  onPress={() => { setShowAddModal(false); resetForm(); }}
                />
                <GlassButton
                  title="Add"
                  onPress={handleAddSubcontractor}
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
  subList: {
    gap: spacing.md,
  },
  subCard: {
    marginBottom: 0,
  },
  subHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  subInfo: {
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
  deleteBtn: {
    padding: spacing.sm,
  },
  subDetails: {
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
  statsRow: {
    flexDirection: 'row',
    gap: spacing.lg,
  },
  statItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  statText: {
    fontSize: 12,
    color: colors.text.muted,
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
