import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, Switch,
  ActivityIndicator, Pressable,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ArrowLeft, User, Lock, Moon, Sun, Save, Shield, LogOut } from 'lucide-react-native';
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
import { colors, spacing, borderRadius, typography } from '../src/styles/theme';

export default function SettingsScreen() {
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const { isDark, toggleTheme } = useTheme();
  const toast = useToast();

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';
  const isCp    = user?.role === 'cp';

  const [name,       setName]       = useState('');
  const [email,      setEmail]      = useState('');
  const [savingName, setSavingName] = useState(false);

  const [currentPw,  setCurrentPw]  = useState('');
  const [newPw,      setNewPw]      = useState('');
  const [confirmPw,  setConfirmPw]  = useState('');
  const [savingPw,   setSavingPw]   = useState(false);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.replace('/login');
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (user) {
      setName(user.name || user.full_name || '');
      setEmail(user.email || '');
    }
  }, [user]);

  const handleSaveName = async () => {
    if (!name.trim()) { toast.error('Error', 'Name cannot be empty'); return; }
    setSavingName(true);
    try {
      await authAPI.updateProfile({ name: name.trim() });
      toast.success('Saved', 'Your name has been updated');
    } catch (e) {
      toast.error('Error', e?.response?.data?.detail || 'Could not update name');
    } finally { setSavingName(false); }
  };

  const handleChangePassword = async () => {
    if (!currentPw || !newPw || !confirmPw) {
      toast.error('Error', 'Please fill in all password fields'); return;
    }
    if (newPw !== confirmPw) { toast.error('Error', 'New passwords do not match'); return; }
    if (newPw.length < 8)   { toast.error('Error', 'Password must be at least 8 characters'); return; }
    setSavingPw(true);
    try {
      await authAPI.changePassword({ current_password: currentPw, new_password: newPw });
      toast.success('Updated', 'Password changed successfully');
      setCurrentPw(''); setNewPw(''); setConfirmPw('');
    } catch (e) {
      toast.error('Error', e?.response?.data?.detail || 'Could not change password');
    } finally { setSavingPw(false); }
  };

  const handleLogout = async () => { await logout(); router.replace('/login'); };

  const roleLabel = { admin: 'Administrator', owner: 'Owner', cp: 'Competent Person', worker: 'Worker' }[user?.role] || 'User';

  if (authLoading) {
    return (
      <AnimatedBackground>
        <View style={styles.loadingCenter}>
          <ActivityIndicator size="large" color={colors.text.primary} />
        </View>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top']}>

        {/* Header */}
        <View style={[styles.header, { borderBottomColor: colors.glass.border }]}>
          <Pressable onPress={() => router.back()} style={styles.iconBtn}>
            <ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />
          </Pressable>
          <Text style={[styles.headerTitle, { color: colors.text.primary }]}>Settings</Text>
          <Pressable onPress={handleLogout} style={styles.iconBtn}>
            <LogOut size={20} strokeWidth={1.5} color={colors.text.muted} />
          </Pressable>
        </View>

        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Account card */}
          <GlassCard style={styles.accountCard}>
            <View style={styles.avatarRow}>
              <View style={[styles.avatar, { backgroundColor: colors.primary }]}>
                <Text style={styles.avatarLetter}>
                  {(name || email || 'U')[0].toUpperCase()}
                </Text>
              </View>
              <View style={styles.accountInfo}>
                <Text style={[styles.accountName, { color: colors.text.primary }]}>{name || 'No name set'}</Text>
                <Text style={[styles.accountEmail, { color: colors.text.muted }]}>{email}</Text>
                <View style={[styles.roleBadge, { backgroundColor: `${colors.primary}18`, borderColor: `${colors.primary}35` }]}>
                  <Shield size={11} strokeWidth={1.5} color={colors.primary} />
                  <Text style={[styles.roleText, { color: colors.primary }]}>{roleLabel}</Text>
                </View>
              </View>
            </View>
          </GlassCard>

          {/* Appearance */}
          <Text style={[styles.sectionLabel, { color: colors.text.muted }]}>APPEARANCE</Text>
          <GlassCard style={styles.card}>
            <View style={styles.settingRow}>
              <View style={styles.settingLeft}>
                {isDark
                  ? <Moon size={20} strokeWidth={1.5} color={colors.text.secondary} />
                  : <Sun  size={20} strokeWidth={1.5} color={colors.text.secondary} />
                }
                <View>
                  <Text style={[styles.settingTitle, { color: colors.text.primary }]}>
                    {isDark ? 'Dark Mode' : 'Light Mode'}
                  </Text>
                  <Text style={[styles.settingSubtitle, { color: colors.text.muted }]}>
                    {isDark ? 'Tap to switch to light' : 'Tap to switch to dark'}
                  </Text>
                </View>
              </View>
              <Switch
                value={isDark}
                onValueChange={toggleTheme}
                trackColor={{ false: '#767577', true: colors.primary }}
                thumbColor="#ffffff"
              />
            </View>
          </GlassCard>

          {/* Personal details */}
          <Text style={[styles.sectionLabel, { color: colors.text.muted }]}>PERSONAL DETAILS</Text>
          <GlassCard style={styles.card}>
            <View style={styles.fieldIconRow}>
              <User size={14} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={[styles.fieldLabel, { color: colors.text.muted }]}>Display Name</Text>
            </View>
            <GlassInput
              value={name}
              onChangeText={setName}
              placeholder="Your full name"
              autoCapitalize="words"
            />

            <View style={[styles.fieldIconRow, { marginTop: spacing.md }]}>
              <Text style={[styles.fieldLabel, { color: colors.text.muted }]}>Email</Text>
            </View>
            <GlassInput
              value={email}
              editable={false}
              placeholder="Email address"
              style={{ opacity: 0.5 }}
            />
            <Text style={[styles.hintText, { color: colors.text.subtle }]}>
              Email cannot be changed here. Contact your administrator.
            </Text>

            <GlassButton
              title={savingName ? 'Saving...' : 'Save Name'}
              onPress={handleSaveName}
              loading={savingName}
              icon={<Save size={16} strokeWidth={1.5} color={colors.text.primary} />}
              style={styles.saveBtn}
            />
          </GlassCard>

          {/* Password — admin only */}
          {isAdmin && (
            <>
              <Text style={[styles.sectionLabel, { color: colors.text.muted }]}>SECURITY</Text>
              <GlassCard style={styles.card}>
                <View style={styles.fieldIconRow}>
                  <Lock size={14} strokeWidth={1.5} color={colors.text.muted} />
                  <Text style={[styles.fieldLabel, { color: colors.text.muted }]}>Change Password</Text>
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
                <GlassButton
                  title={savingPw ? 'Updating...' : 'Change Password'}
                  onPress={handleChangePassword}
                  loading={savingPw}
                  icon={<Lock size={16} strokeWidth={1.5} color={colors.text.primary} />}
                  style={styles.saveBtn}
                />
              </GlassCard>
            </>
          )}

          {/* Sign out */}
          <Text style={[styles.sectionLabel, { color: colors.text.muted }]}>ACCOUNT</Text>
          <GlassCard style={styles.card}>
            <GlassButton
              title="Sign Out"
              onPress={handleLogout}
              icon={<LogOut size={16} strokeWidth={1.5} color="#f87171" />}
            />
          </GlassCard>

        </ScrollView>

        {isCp ? <CpNav /> : <FloatingNav />}
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  container:    { flex: 1 },
  loadingCenter:{ flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: 1,
  },
  iconBtn:     { padding: spacing.xs },
  headerTitle: { fontSize: 17, fontWeight: '600' },
  scroll:      { flex: 1 },
  scrollContent: {
    padding: spacing.lg, paddingBottom: 110,
    maxWidth: 720, width: '100%', alignSelf: 'center',
  },
  accountCard: { padding: spacing.lg, marginBottom: spacing.lg },
  avatarRow:   { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  avatar: {
    width: 56, height: 56, borderRadius: 28,
    alignItems: 'center', justifyContent: 'center',
  },
  avatarLetter: { fontSize: 22, fontWeight: '600', color: '#fff' },
  accountInfo:  { flex: 1 },
  accountName:  { fontSize: 17, fontWeight: '600', marginBottom: 2 },
  accountEmail: { fontSize: 13, marginBottom: spacing.xs },
  roleBadge: {
    flexDirection: 'row', alignItems: 'center', gap: 4,
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.sm, paddingVertical: 3,
    borderRadius: borderRadius.full, borderWidth: 1,
  },
  roleText: { fontSize: 11, fontWeight: '600' },
  sectionLabel: {
    ...typography.label,
    marginBottom: spacing.sm, marginTop: spacing.sm,
  },
  card:         { padding: spacing.lg, marginBottom: spacing.md },
  settingRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
  },
  settingLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flex: 1 },
  settingTitle:    { fontSize: 15, fontWeight: '500' },
  settingSubtitle: { fontSize: 12, marginTop: 1 },
  fieldIconRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.sm },
  fieldLabel:   { fontSize: 11, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 1 },
  hintText:     { fontSize: 11, marginTop: spacing.xs },
  saveBtn:      { marginTop: spacing.md },
});
