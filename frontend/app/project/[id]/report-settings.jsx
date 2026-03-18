import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Alert,
  Platform,
  RefreshControl,
} from 'react-native';
import { useRouter, useLocalSearchParams, useFocusEffect } from 'expo-router';
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
  RotateCw,
} from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../../src/components/GlassCard';
import GlassButton from '../../../src/components/GlassButton';
import GlassInput from '../../../src/components/GlassInput';
import { useToast } from '../../../src/components/Toast';
import { useAuth } from '../../../src/context/AuthContext';
import { projectsAPI } from '../../../src/utils/api';
import { spacing, borderRadius, typography } from '../../../src/styles/theme';
import { useTheme } from '../../../src/context/ThemeContext';

export default function ReportSettingsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  // NEW: Track saved state for UI feedback
  const lastSavedRef = useRef(null);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [project, setProject] = useState(null);
  const [emailList, setEmailList] = useState([]);
  const [newEmail, setNewEmail] = useState('');
  const [sendTime, setSendTime] = useState('18:00');
  
  // NEW: Track if there are unsaved changes
  const [hasChanges, setHasChanges] = useState(false);

  const isAdmin = user?.role === 'admin';

  // NEW: Refetch whenever screen comes into focus to catch any backend updates
  useFocusEffect(
    React.useCallback(() => {
      if (isAuthenticated && projectId) {
        fetchProject();
      }
    }, [isAuthenticated, projectId])
  );

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  const fetchProject = async () => {
    if (!projectId) {
      console.warn('fetchProject called with no projectId, skipping');
      return;
    }
    setLoading(true);
    try {
      const projectData = await projectsAPI.getById(projectId);
      if (!projectData) {
        throw new Error('Project not found on server');
      
      setProject(projectData);
      // CRITICAL: Use the backend data as source of truth
      const backendEmailList = projectData.report_email_list || [];
      const backendSendTime = projectData.report_send_time || '18:00';
      
      console.log('✅ Report settings loaded from backend:', {
        emailCount: backendEmailList.length,
        emails: backendEmailList,
        sendTime: backendSendTime,
        projectId: projectData.id,
      });
      
      setEmailList(backendEmailList);
      setSendTime(backendSendTime);
      };
    } catch (error) {
      console.error('Failed to fetch project:', error);
      toast.error('Error', 'Could not load project settings');
    } finally {
      setLoading(false);
    }
  };

  // NEW: Refresh handler for pull-to-refresh
  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetchProject();
      toast.success('Refreshed', 'Report settings reloaded');
    } catch (error) {
      toast.error('Refresh Failed', 'Could not reload settings');
    } finally {
      setRefreshing(false);
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

    const newList = [...emailList, trimmedEmail];
    setEmailList(newList);
    setNewEmail('');
    setHasChanges(true);
    toast.success('Added', 'Email added to list');
  };

  const handleRemoveEmail = (emailToRemove) => {
    const confirmRemove = () => {
      const newList = emailList.filter(email => email !== emailToRemove);
      setEmailList(newList);
      setHasChanges(true);
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
    if (!hasChanges) {
      toast.info('No Changes', 'Settings are already saved');
      return;
    }

    setSaving(true);
    try {

      const response = await projectsAPI.updateReportSettings(projectId, {
        report_email_list: emailList,
        report_send_time: sendTime,
      });

      if (!response) {
        throw new Error('No response from server');
      }

      // CRITICAL: Update saved reference ONLY on successful response
      lastSavedRef.current = {
        emailList: emailList,
        sendTime: sendTime,
      };
      
      setHasChanges(false);
      toast.success('Saved', 'Report settings updated successfully');
      
      // CRITICAL: Refetch to confirm backend persisted the data
      await fetchProject();
    } catch (error) {
      console.error('Failed to save settings:', error);
      const errorMsg = error.response?.data?.detail || error.message || 'Could not save settings';
      toast.error('Save Failed', errorMsg);
      
      // NEW: Don't clear hasChanges on failure; user can retry
    } finally {
      setSaving(false);
    }
  };

  const handleSendTimeChange = (newTime) => {
    setSendTime(newTime);
    setHasChanges(true);
  };

  const handleLogout = async () => {
    if (hasChanges) {
      return Alert.alert(
        'Unsaved Changes',
        'You have unsaved changes. Save before logging out?',
        [
          { text: 'Discard', onPress: () => logoutUser() },
          { text: 'Save & Logout', onPress: async () => {
            await handleSave();
            await logoutUser();
          }},
          { text: 'Cancel', style: 'cancel' },
        ]
      );
    }
    await logoutUser();
  };

  const logoutUser = async () => {
    await logout();
    router.replace('/login');
  };

  if (!isAdmin) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.accessDenied}>
            <AlertCircle size={56} strokeWidth={1} color={colors.status.error} />
            <Text style={s.accessDeniedTitle}>Admin Access Required</Text>
            <Text style={s.accessDeniedDesc}>
              Only administrators can modify report settings.
            </Text>
            <GlassButton
              title="Go Back"
              onPress={() => router.back()}
              style={s.returnBtn}
            />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={s.loadingText}>Loading settings...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

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
          <View style={s.headerRight}>
            <GlassButton
              variant="icon"
              icon={<RotateCw size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleRefresh}
              loading={refreshing}
            />
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
          </View>
        </View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>PROJECT SETTINGS</Text>
            <Text style={s.titleText}>Report Email List</Text>
            {project && (
              <View style={s.projectBadge}>
                <Building2 size={14} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.projectName}>{project.name}</Text>
              </View>
            )}
          </View>

          {/* Unsaved Changes Warning */}
          {hasChanges && (
            <GlassCard style={[s.warningCard, { borderColor: '#f59e0b', borderWidth: 1 }]}>
              <Text style={s.warningText}>⚠ You have unsaved changes</Text>
            </GlassCard>
          )}

          {/* Description */}
          <GlassCard style={s.infoCard}>
            <IconPod size={44}>
              <Mail size={18} strokeWidth={1.5} color="#3b82f6" />
            </IconPod>
            <Text style={s.infoTitle}>Auto-Send Reports</Text>
            <Text style={s.infoText}>
              Daily reports for this project will be automatically sent to all email addresses in this list at the scheduled time.
            </Text>
          </GlassCard>

          {/* Add Email Input */}
          <GlassCard style={s.addEmailCard}>
            <Text style={s.sectionTitle}>Add Email Address</Text>
            <View style={s.addEmailRow}>
              <GlassInput
                value={newEmail}
                onChangeText={setNewEmail}
                placeholder="email@example.com"
                keyboardType="email-address"
                autoCapitalize="none"
                style={s.emailInput}
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
          <Text style={s.sectionLabel}>
            EMAIL LIST ({emailList.length})
          </Text>

          {emailList.length > 0 ? (
            <View style={s.emailList}>
              {emailList.map((email, index) => (
                <GlassCard key={index} style={s.emailCard}>
                  <View style={s.emailRow}>
                    <Mail size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.emailText}>{email}</Text>
                    <Pressable
                      onPress={() => handleRemoveEmail(email)}
                      style={s.deleteBtn}
                    >
                      <Trash2 size={16} color={colors.status.error} />
                    </Pressable>
                  </View>
                </GlassCard>
              ))}
            </View>
          ) : (
            <GlassCard style={s.emptyCard}>
              <Mail size={40} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyTitle}>No Email Addresses</Text>
              <Text style={s.emptyText}>
                Add email addresses to receive automatic daily reports for this project.
              </Text>
            </GlassCard>
          )}

          {/* Send Time */}
          <Text style={s.sectionLabel}>SEND TIME (EST)</Text>
          <GlassCard style={s.addEmailCard}>
            <Text style={s.sectionTitle}>Daily Report Time</Text>
            <View style={s.timeRow}>
              {['06:00', '12:00', '15:00', '17:00', '18:00', '19:00', '20:00', '21:00'].map((time) => (
                <Pressable
                  key={time}
                  onPress={() => handleSendTimeChange(time)}
                  style={[
                    s.timeOption,
                    sendTime === time && s.timeOptionActive,
                  ]}
                >
                  <Text style={[
                    s.timeOptionText,
                    sendTime === time && s.timeOptionTextActive,
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
            disabled={!hasChanges || saving}
            style={s.saveButton}
          />
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
    warningCard: {
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      marginBottom: spacing.lg,
      backgroundColor: 'rgba(245, 158, 11, 0.1)',
    },
    warningText: {
      fontSize: 14,
      color: '#f59e0b',
      fontWeight: '500',
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
}
