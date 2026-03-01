import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Switch,
  ActivityIndicator,
  Pressable,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  User,
  Lock,
  Moon,
  Sun,
  Save,
  Shield,
  LogOut,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import GlassInput from '../src/components/GlassInput';
import FloatingNav from '../src/components/FloatingNav';
import CpNav from '../src/components/CpNav';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { useTheme } from '../src/context/ThemeContext';
import { authAPI } from '../src/utils/api';
import { spacing, borderRadius, typography } from '../src/styles/theme';

export default function SettingsScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const { isDark, toggleTheme, colors } = useTheme();
  const toast = useToast();

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';
  const isCp    = user?.role === 'cp';

  // \u2500\u2500 Profile fields \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  const [name,        setName]        = useState('');
  const [email,       setEmail]       = useState('');
  const [savingName,  setSavingName]  = useState(false);

  // \u2500\u2500 Password fields (admin only) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  const [currentPw,   setCurrentPw]   = useState('');
  const [newPw,       setNewPw]       = useState('');
  const [confirmPw,   setConfirmPw]   = useState('');
  const [savingPw,    setSavingPw]    = useState(false);

  // \u2500\u2500 Auth guard \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [isAuthenticated, authLoading]);

  // Pre-fill from auth context
  useEffect(() => {
    if (user) {
      setName(user.name || user.full_name || '');
      setEmail(user.email || '');
    }
  }, [user]);

  // \u2500\u2500 Handlers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  const handleSaveName = async () => {
    if (!name.trim()) {
      toast.error('Error', 'Name cannot be empty');
      return;
    }
    setSavingName(true);
    try {
      await authAPI.updateProfile({ name: name.trim() });
      toast.success('Saved', 'Your name has been updated');
    } catch (e) {
      toast.error('Error', e?.response?.data?.detail || 'Could not update name');
    } finally {
      setSavingName(false);
    }
  };

  const handleChangePassword = async () => {
    if (!currentPw || !newPw || !confirmPw) {
      toast.error('Error', 'Please fill in all password fields');
      return;
    }
    if (newPw !== confirmPw) {
      toast.error('Error', 'New passwords do not match');
      return;
    }
    if (newPw.length < 8) {
      toast.error('Error', 'Password must be at least 8 characters');
      return;
    }
    setSavingPw(true);
    try {
      await authAPI.changePassword({ current_password: currentPw, new_password: newPw });
      toast.success('Updated', 'Password changed successfully');
      setCurrentPw('');
      setNewPw('');
      setConfirmPw('');
    } catch (e) {
      toast.error('Error', e?.response?.data?.detail || 'Could not change password');
    } finally {
      setSavingPw(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  // \u2500\u2500 Role badge label \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  const roleLabel = {
    admin:  'Administrator',
    owner:  'Owner',
    cp:     'Competent Person',
    worker: 'Worker',
  }[user?.role] || user?.role || 'User';

  // \u2500\u2500 Styles (theme-aware, built inline so colors update on toggle) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  const s = buildStyles(colors);

  if (authLoading) {
    return (
      <AnimatedBackground>
        <View style={s.loadingCenter}>
          <ActivityIndicator size="large" color={colors.text.primary} />
        </View>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>

        {/* Header */}
        <View style={s.header}>
          <Pressable onPress={() => router.back()} style={s.backBtn}>
            <ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />
          </Pressable>
          <Text style={s.headerTitle}>Settings</Text>
          <Pressable onPress={handleLogout} style={s.logoutBtn}>
            <LogOut size={20} strokeWidth={1.5} color={colors.text.muted} />
          </Pressable>
        </View>

        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* \u2500\u2500 Account info card \u2500\u2500 */}
          <GlassCard style={s.accountCard}>
            <View style={s.avatarRow}>
              <View style={s.avatar}>
                <Text style={s.avatarLetter}>
                  {(name || email || 'U')[0].toUpperCase()}
                </Text>
              </View>
              <View style={s.accountInfo}>
                <Text style={s.accountName}>{name || 'No name set'}</Text>
                <Text style={s.accountEmail}>{email}</Text>
                <View style={s.roleBadge}>
                  <Shield size={11} strokeWidth={1.5} color={colors.primary} />
                  <Text style={[s.roleText, { color: colors.primary }]}>{roleLabel}</Text>
                </View>
              </View>
            </View>
          </GlassCard>

          {/* \u2500\u2500 Appearance \u2500\u2500 */}
          <Text style={s.sectionLabel}>APPEARANCE</Text>
          <GlassCard style={s.card}>
            <View style={s.settingRow}>
              <View style={s.settingLeft}>
                {isDark
                  ? <Moon size={20} strokeWidth={1.5} color={colors.text.secondary} />
                  : <Sun  size={20} strokeWidth={1.5} color={colors.text.secondary} />
                }
                <View>
                  <Text style={s.settingTitle}>{isDark ? 'Dark Mode' : 'Light Mode'}</Text>
                  <Text style={s.settingSubtitle}>
                    {isDark ? 'Switch to light theme' : 'Switch to dark theme'}
                  </Text>
                </View>
              </View>
              <Switch
                value={isDark}
                onValueChange={toggleTheme}
                trackColor={{ false: colors.glass.border, true: colors.primary }}
                thumbColor={colors.white}
              />
            </View>
          </GlassCard>

          {/* \u2500\u2500 Personal details \u2500\u2500 */}
          <Text style={s.sectionLabel}>PERSONAL DETAILS</Text>
          <GlassCard style={s.card}>
            <View style={s.fieldGroup}>
              <View style={s.fieldIconRow}>
                <User size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={s.fieldLabel}>Display Name</Text>
              </View>
              <GlassInput
                value={name}
                onChangeText={setName}
                placeholder="Your full name"
                autoCapitalize="words"
              />
            </View>

            <View style={[s.fieldGroup, { marginTop: spacing.sm }]}>
              <View style={s.fieldIconRow}>
                <Text style={s.fieldLabel}>Email</Text>
              </View>
              <GlassInput
                value={email}
                editable={false}
                placeholder="Email address"
                style={s.disabledInput}
              />
              <Text style={s.hintText}>Email cannot be changed here. Contact your administrator.</Text>
            </View>

            <GlassButton
              title={savingName ? 'Saving...' : 'Save Name'}
              onPress={handleSaveName}
              loading={savingName}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              style={s.saveBtn}
            />
          </GlassCard>

          {/* \u2500\u2500 Password (admin only) \u2500\u2500 */}
          {isAdmin && (
            <>
              <Text style={s.sectionLabel}>SECURITY</Text>
              <GlassCard style={s.card}>
                <View style={s.fieldGroup}>
                  <View style={s.fieldIconRow}>
                    <Lock size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={s.fieldLabel}>Change Password</Text>
                  </View>
                  <GlassInput
                    value={currentPw}
                    onChangeText={setCurrentPw}
                    placeholder="Current password"
                    secureTextEntry
                  />
                  <GlassInput
                    value={newPw}
                    onChangeText={setNewPw}
                    placeholder="New password (min 8 chars)"
                    secureTextEntry
                    style={{ marginTop: spacing.sm }}
                  />
                  <GlassInput
                    value={confirmPw}
                    onChangeText={setConfirmPw}
                    placeholder="Confirm new password"
                    secureTextEntry
                    style={{ marginTop: spacing.sm }}
                  />
                </View>

                <GlassButton
                  title={savingPw ? 'Updating...' : 'Change Password'}
                  onPress={handleChangePassword}
                  loading={savingPw}
                  icon={<Lock size={16} strokeWidth={1.5} color={colors.text.primary} />}
                  style={s.saveBtn}
                />
              </GlassCard>
            </>
          )}

          {/* \u2500\u2500 Sign out \u2500\u2500 */}
          <Text style={s.sectionLabel}>ACCOUNT</Text>
          <GlassCard style={s.card}>
            <GlassButton
              title="Sign Out"
              onPress={handleLogout}
              icon={<LogOut size={16} strokeWidth={1.5} color="#f87171" />}
              style={s.signOutBtn}
            />
          </GlassCard>

        </ScrollView>

        {/* Bottom nav \u2014 CP gets CpNav, everyone else gets FloatingNav */}
        {isCp ? <CpNav /> : <FloatingNav />}

      </SafeAreaView>
    </AnimatedBackground>
  );
}

// Build styles using live theme colors so they re-render on toggle
function buildStyles(colors) {
  return StyleSheet.create({
    container:    { flex: 1 },
    loadingCenter:{ flex: 1, alignItems: 'center', justifyContent: 'center' },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      paddingHorizontal: spacing.lg,
      paddingVertical: spacing.md,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    backBtn:     { padding: spacing.xs },
    logoutBtn:   { padding: spacing.xs },
    headerTitle: {
      fontSize: 17,
      fontWeight: '600',
      color: colors.text.primary,
    },
    scroll:       { flex: 1 },
    scrollContent: {
      padding: spacing.lg,
      paddingBottom: 110,
      maxWidth: 720,
      width: '100%',
      alignSelf: 'center',
    },
    // Account card
    accountCard: { padding: spacing.lg, marginBottom: spacing.lg },
    avatarRow:   { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    avatar: {
      width: 56, height: 56, borderRadius: 28,
      backgroundColor: colors.primary,
      alignItems: 'center', justifyContent: 'center',
    },
    avatarLetter: { fontSize: 22, fontWeight: '600', color: '#fff' },
    accountInfo:  { flex: 1 },
    accountName:  { fontSize: 17, fontWeight: '600', color: colors.text.primary, marginBottom: 2 },
    accountEmail: { fontSize: 13, color: colors.text.muted, marginBottom: spacing.xs },
    roleBadge: {
      flexDirection: 'row', alignItems: 'center', gap: 4,
      alignSelf: 'flex-start',
      paddingHorizontal: spacing.sm, paddingVertical: 3,
      borderRadius: borderRadius.full,
      backgroundColor: `${colors.primary}18`,
      borderWidth: 1, borderColor: `${colors.primary}35`,
    },
    roleText: { fontSize: 11, fontWeight: '600' },
    // Section label
    sectionLabel: {
      ...typography.label,
      color: colors.text.muted,
      marginBottom: spacing.sm,
      marginTop: spacing.sm,
    },
    // Card
    card: { padding: spacing.lg, marginBottom: spacing.md },
    // Setting row (theme toggle)
    settingRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    settingLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
    settingTitle:    { fontSize: 15, fontWeight: '500', color: colors.text.primary },
    settingSubtitle: { fontSize: 12, color: colors.text.muted, marginTop: 1 },
    // Field group
    fieldGroup:   {},
    fieldIconRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.sm },
    fieldLabel:   { fontSize: 12, fontWeight: '500', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 1 },
    disabledInput:{ opacity: 0.5 },
    hintText:     { fontSize: 11, color: colors.text.subtle, marginTop: spacing.xs },
    // Buttons
    saveBtn:    { marginTop: spacing.md },
    signOutBtn: { borderColor: 'rgba(248,113,113,0.3)' },
  });
}
