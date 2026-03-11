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
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  Mail,
  Plus,
  Trash2,
  Save,
  Building2,
  AlertCircle,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import GlassInput from '../../../src/components/GlassInput';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { projectsAPI } from '../../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../../src/styles/theme';

export default function ReportSettingsScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [project, setProject] = useState(null);
  const [emailList, setEmailList] = useState([]);
  const [newEmail, setNewEmail] = useState('');
  const [sendTime, setSendTime] = useState('18:00');

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated && projectId) {
      fetchProject();
    }
  }, [isAuthenticated, projectId]);

  const fetchProject = async () => {
    setLoading(true);
    try {
      const projectData = await projectsAPI.getById(projectId);
      setProject(projectData);
      setEmailList(projectData.report_email_list || []);
      setSendTime(projectData.report_send_time || '18:00');
    } catch (error) {
      console.error('Failed to fetch project:', error);
      toast.error('Error', 'Could not load project settings');
    } finally {
      setLoading(false);
    }
  };

  const handleAddEmail = () => {
    const trimmedEmail = newEmail.trim().toLowerCase();
    
    if (!trimmedEmail) {
      toast.warning('Empty Email', 'Please enter an email address');
      return;
    }

    // Basic email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(trimmedEmail)) {
      toast.error('Invalid Email', 'Please enter a valid email address');
      return;
    }

    if (emailList.includes(trimmedEmail)) {
      toast.warning('Duplicate', 'This email is already in the list');
      return;
    }

    setEmailList([...emailList, trimmedEmail]);
    setNewEmail('');
    toast.success('Added', 'Email added to list');
  };

  const handleRemoveEmail = (emailToRemove) => {
    const confirmRemove = () => {
      setEmailList(emailList.filter(email => email !== emailToRemove));
      toast.success('Removed', 'Email removed from list');
    };

    if (Platform.OS === 'web') {
      if (window.confirm(`Remove ${emailToRemove}?`)) {
        confirmRemove();
      }
    } else {
      Alert.alert('Remove Email', `Remove ${emailToRemove} from the list?`, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Remove', style: 'destructive', onPress: confirmRemove },
      ]);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await projectsAPI.update(projectId, {
        report_email_list: emailList,
        report_send_time: sendTime,
      });
      toast.success('Saved', 'Report settings updated successfully');
    } catch (error) {
      console.error('Failed to save settings:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  if (!isAdmin) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.accessDenied}>
            <AlertCircle size={56} strokeWidth={1} color={colors.status.error} />
            <Text style={styles.accessDeniedTitle}>Admin Access Required</Text>
            <Text style={styles.accessDeniedDesc}>
              Only administrators can modify report settings.
            </Text>
            <GlassButton
              title="Go Back"
              onPress={() => router.back()}
              style={styles.returnBtn}
            />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={styles.loadingText}>Loading settings...</Text>
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
            <Text style={styles.titleLabel}>PROJECT SETTINGS</Text>
            <Text style={styles.titleText}>Report Email List</Text>
            {project && (
              <View style={styles.projectBadge}>
                <Building2 size={14} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={styles.projectName}>{project.name}</Text>
              </View>
            )}
          </View>

          {/* Description */}
          <GlassCard style={styles.infoCard}>
            <IconPod size={44}>
              <Mail size={18} strokeWidth={1.5} color="#3b82f6" />
            </IconPod>
            <Text style={styles.infoTitle}>Auto-Send Reports</Text>
            <Text style={styles.infoText}>
              Daily reports for this project will be automatically sent to all email addresses in this list at the scheduled time.
            </Text>
          </GlassCard>

          {/* Add Email Input */}
          <GlassCard style={styles.addEmailCard}>
            <Text style={styles.sectionTitle}>Add Email Address</Text>
            <View style={styles.addEmailRow}>
              <GlassInput
                value={newEmail}
                onChangeText={setNewEmail}
                placeholder="email@example.com"
                keyboardType="email-address"
                autoCapitalize="none"
                style={styles.emailInput}
                onSubmitEditing={handleAddEmail}
              />
              <GlassButton
                variant="icon"
                icon={<Plus size={20} strokeWidth={1.5} color={colors.text.primary} />}
                onPress={handleAddEmail}
              />
            </View>
          </GlassCard>

          {/* Email List */}
          <Text style={styles.sectionLabel}>
            EMAIL LIST ({emailList.length})
          </Text>

          {emailList.length > 0 ? (
            <View style={styles.emailList}>
              {emailList.map((email, index) => (
                <GlassCard key={index} style={styles.emailCard}>
                  <View style={styles.emailRow}>
                    <Mail size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={styles.emailText}>{email}</Text>
                    <Pressable
                      onPress={() => handleRemoveEmail(email)}
                      style={styles.deleteBtn}
                    >
                      <Trash2 size={16} color={colors.status.error} />
                    </Pressable>
                  </View>
                </GlassCard>
              ))}
            </View>
          ) : (
            <GlassCard style={styles.emptyCard}>
              <Mail size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={styles.emptyTitle}>No Email Addresses</Text>
              <Text style={styles.emptyText}>
                Add email addresses to receive automatic daily reports for this project.
              </Text>
            </GlassCard>
          )}
           {/* Send Time */}
          <Text style={styles.sectionLabel}>SEND TIME (EST)</Text>
          <GlassCard style={styles.addEmailCard}>
            <Text style={styles.sectionTitle}>Daily Report Time</Text>
            <View style={styles.timeRow}>
              {['06:00', '12:00', '15:00', '17:00', '18:00', '19:00', '20:00', '21:00'].map((time) => (
                <Pressable
                  key={time}
                  onPress={() => setSendTime(time)}
                  style={[
                    styles.timeOption,
                    sendTime === time && styles.timeOptionActive,
                  ]}
                >
                  <Text style={[
                    styles.timeOptionText,
                    sendTime === time && styles.timeOptionTextActive,
                  ]}>
                    {parseInt(time) > 12 ? `${parseInt(time) - 12}:${time.split(':')[1]} PM` : parseInt(time) === 12 ? '12:00 PM' : `${parseInt(time)}:${time.split(':')[1]} AM`}
                  </Text>
                </Pressable>
              ))}
            </View>
          </GlassCard>

          {/* Save Button */}
          <GlassButton
            title={saving ? 'Saving...' : 'Save Settings'}
            icon={<Save size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleSave}
            loading={saving}
            style={styles.saveButton}
          />
        </ScrollView>
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
    marginBottom: spacing.md,
  },
  projectBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  projectName: {
    fontSize: 14,
    color: colors.text.primary,
  },
  infoCard: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
    marginBottom: spacing.lg,
  },
  infoTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  infoText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 320,
    lineHeight: 20,
  },
  addEmailCard: {
    marginBottom: spacing.lg,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    marginBottom: spacing.md,
  },
  addEmailRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    alignItems: 'flex-end',
  },
  emailInput: {
    flex: 1,
  },
  sectionLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.md,
    paddingHorizontal: spacing.xs,
  },
  emailList: {
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  emailCard: {
    padding: spacing.md,
  },
  emailRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  emailText: {
    flex: 1,
    fontSize: 15,
    color: colors.text.primary,
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
  },
  deleteBtn: {
    padding: spacing.sm,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
    gap: spacing.sm,
    marginBottom: spacing.xl,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.md,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 280,
    lineHeight: 20,
  },
  timeRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  timeOption: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
    backgroundColor: colors.glass.background,
  },
  timeOptionActive: {
    backgroundColor: 'rgba(59, 130, 246, 0.2)',
    borderColor: '#3b82f6',
  },
  timeOptionText: {
    fontSize: 13,
    color: colors.text.muted,
  },
  timeOptionTextActive: {
    color: '#3b82f6',
    fontWeight: '600',
  },
  saveButton: {
    marginTop: spacing.md,
  },
});
