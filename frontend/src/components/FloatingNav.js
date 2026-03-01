import React, { useState } from 'react';
import {
  View,
  StyleSheet,
  Pressable,
  Text,
  ScrollView,
  Switch,
  TextInput,
  Modal,
  ActivityIndicator,
  Platform,
  KeyboardAvoidingView,
} from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { BlurView } from 'expo-blur';
import {
  LayoutDashboard,
  FolderKanban,
  Users,
  FileText,
  FolderOpen,
  Settings,
  X,
  Sun,
  Moon,
  User,
  Lock,
  Check,
} from 'lucide-react-native';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useAuth } from '../context/AuthContext';
import { authAPI } from '../utils/api';

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/projects', icon: FolderKanban, label: 'Projects' },
  { path: '/workers', icon: Users, label: 'Workers' },
  { path: '/documents', icon: FolderOpen, label: 'Documents' },
  { path: '/reports', icon: FileText, label: 'Reports' },
];

// ─── Shared input style used inside the settings modal ───────────────────────
const INPUT_STYLE = {
  backgroundColor: 'rgba(255, 255, 255, 0.08)',
  borderWidth: 1,
  borderColor: 'rgba(255, 255, 255, 0.12)',
  borderRadius: 12,
  paddingHorizontal: 14,
  paddingVertical: 12,
  color: '#ffffff',
  fontSize: 15,
  marginBottom: 10,
};

/**
 * SettingsModal
 * - Name change (all users)
 * - Password change (admin / owner only)
 * - Light / Dark mode toggle (UI preference stored in component state; extend
 *   with a real ThemeContext once one is added to the project)
 */
const SettingsModal = ({ visible, onClose, user, onToast }) => {
  const [isDark, setIsDark] = useState(true); // default dark – matches current theme
  const [name, setName] = useState(user?.full_name || user?.name || '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);

  const isAdmin = user?.role === 'admin' || user?.role === 'owner';

  const handleSaveName = async () => {
    if (!name.trim()) {
      onToast && onToast('error', 'Name is required');
      return;
    }
    setSaving(true);
    try {
      await authAPI.updateProfile({ name: name.trim() });
      onToast && onToast('success', 'Name updated successfully');
    } catch (err) {
      console.error('Failed to update name:', err);
      onToast && onToast('error', err?.response?.data?.detail || 'Could not update name');
    } finally {
      setSaving(false);
    }
  };

  const handleSavePassword = async () => {
    if (!currentPassword || !newPassword || !confirmPassword) {
      onToast && onToast('error', 'Please fill in all password fields');
      return;
    }
    if (newPassword !== confirmPassword) {
      onToast && onToast('error', 'New passwords do not match');
      return;
    }
    if (newPassword.length < 6) {
      onToast && onToast('error', 'Password must be at least 6 characters');
      return;
    }
    setSavingPassword(true);
    try {
      await authAPI.updatePassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      onToast && onToast('success', 'Password updated successfully');
    } catch (err) {
      console.error('Failed to update password:', err);
      onToast && onToast('error', err?.response?.data?.detail || 'Could not update password');
    } finally {
      setSavingPassword(false);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={modalStyles.overlay}
      >
        <Pressable style={modalStyles.backdrop} onPress={onClose} />

        <View style={modalStyles.sheet}>
          <BlurView intensity={60} tint="dark" style={modalStyles.blurFill}>
            <View style={modalStyles.handle} />

            {/* Header */}
            <View style={modalStyles.header}>
              <Text style={modalStyles.title}>Settings</Text>
              <Pressable onPress={onClose} style={modalStyles.closeBtn}>
                <X size={20} strokeWidth={1.5} color={colors.text.muted} />
              </Pressable>
            </View>

            <ScrollView
              style={modalStyles.scroll}
              showsVerticalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
            >
              {/* ── Appearance ─────────────────────────────────────── */}
              <Text style={modalStyles.sectionLabel}>APPEARANCE</Text>
              <View style={modalStyles.row}>
                <View style={modalStyles.rowLeft}>
                  {isDark
                    ? <Moon size={18} strokeWidth={1.5} color={colors.text.secondary} />
                    : <Sun size={18} strokeWidth={1.5} color="#f59e0b" />}
                  <Text style={modalStyles.rowText}>{isDark ? 'Dark Mode' : 'Light Mode'}</Text>
                </View>
                <Switch
                  value={isDark}
                  onValueChange={setIsDark}
                  trackColor={{ false: 'rgba(255,255,255,0.2)', true: 'rgba(96,165,250,0.5)' }}
                  thumbColor={isDark ? '#60a5fa' : '#ffffff'}
                />
              </View>

              {/* ── Personal Details ───────────────────────────────── */}
              <Text style={[modalStyles.sectionLabel, { marginTop: spacing.lg }]}>PERSONAL DETAILS</Text>
              <View style={modalStyles.iconRow}>
                <User size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={modalStyles.fieldLabel}>Display Name</Text>
              </View>
              <TextInput
                style={INPUT_STYLE}
                value={name}
                onChangeText={setName}
                placeholder="Your full name"
                placeholderTextColor={colors.text.subtle}
                autoCapitalize="words"
                autoCorrect={false}
              />

              <Pressable
                onPress={handleSaveName}
                style={[modalStyles.saveBtn, saving && { opacity: 0.6 }]}
                disabled={saving}
              >
                {saving
                  ? <ActivityIndicator size="small" color="#fff" />
                  : <><Check size={15} strokeWidth={2} color="#fff" /><Text style={modalStyles.saveBtnText}>Save Name</Text></>}
              </Pressable>

              {/* ── Password (admin / owner only) ─────────────────── */}
              {isAdmin && (
                <>
                  <Text style={[modalStyles.sectionLabel, { marginTop: spacing.lg }]}>CHANGE PASSWORD</Text>
                  <View style={modalStyles.iconRow}>
                    <Lock size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={modalStyles.fieldLabel}>Current Password</Text>
                  </View>
                  <TextInput
                    style={INPUT_STYLE}
                    value={currentPassword}
                    onChangeText={setCurrentPassword}
                    placeholder="Enter current password"
                    placeholderTextColor={colors.text.subtle}
                    secureTextEntry
                    autoCorrect={false}
                  />
                  <TextInput
                    style={INPUT_STYLE}
                    value={newPassword}
                    onChangeText={setNewPassword}
                    placeholder="New password"
                    placeholderTextColor={colors.text.subtle}
                    secureTextEntry
                    autoCorrect={false}
                  />
                  <TextInput
                    style={INPUT_STYLE}
                    value={confirmPassword}
                    onChangeText={setConfirmPassword}
                    placeholder="Confirm new password"
                    placeholderTextColor={colors.text.subtle}
                    secureTextEntry
                    autoCorrect={false}
                  />
                  <Pressable
                    onPress={handleSavePassword}
                    style={[modalStyles.saveBtn, savingPassword && { opacity: 0.6 }]}
                    disabled={savingPassword}
                  >
                    {savingPassword
                      ? <ActivityIndicator size="small" color="#fff" />
                      : <><Check size={15} strokeWidth={2} color="#fff" /><Text style={modalStyles.saveBtnText}>Update Password</Text></>}
                  </Pressable>
                </>
              )}

              {/* Bottom safe-space */}
              <View style={{ height: spacing.xl }} />
            </ScrollView>
          </BlurView>
          <View style={modalStyles.border} />
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const modalStyles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.55)',
  },
  sheet: {
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    overflow: 'hidden',
    maxHeight: '85%',
  },
  blurFill: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xl,
    backgroundColor: 'rgba(10,14,23,0.85)',
  },
  handle: {
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignSelf: 'center',
    marginTop: 10,
    marginBottom: 4,
  },
  border: {
    ...StyleSheet.absoluteFillObject,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    pointerEvents: 'none',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.08)',
    marginBottom: spacing.md,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.text.primary,
  },
  closeBtn: {
    padding: 6,
  },
  scroll: {
    flexGrow: 0,
  },
  sectionLabel: {
    fontSize: 10,
    fontWeight: '600',
    color: colors.text.muted,
    letterSpacing: 1.5,
    marginBottom: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
  },
  rowLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  rowText: {
    fontSize: 15,
    color: colors.text.primary,
  },
  iconRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 6,
  },
  fieldLabel: {
    fontSize: 12,
    color: colors.text.muted,
  },
  saveBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
    backgroundColor: 'rgba(96,165,250,0.25)',
    borderWidth: 1,
    borderColor: 'rgba(96,165,250,0.4)',
    borderRadius: 12,
    paddingVertical: 11,
    marginTop: 4,
  },
  saveBtnText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#60a5fa',
  },
});

// ─── NavItem ─────────────────────────────────────────────────────────────────

/**
 * NavItem - Individual nav button with hover support
 */
const NavItem = ({ item, isActive, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const Icon = item.icon;

  return (
    <Pressable
      onPress={onPress}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={[
        styles.navItem,
        isActive && styles.navItemActive,
        isHovered && !isActive && styles.navItemHovered,
      ]}
    >
      <Icon
        size={18}
        strokeWidth={1.5}
        color={isActive || isHovered ? colors.text.primary : colors.text.muted}
      />
      <Text
        style={[
          styles.navLabel,
          (isActive || isHovered) && styles.navLabelActive,
        ]}
        numberOfLines={1}
      >
        {item.label}
      </Text>
    </Pressable>
  );
};

// ─── SettingsNavItem ──────────────────────────────────────────────────────────

const SettingsNavItem = ({ onPress, isActive }) => {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <Pressable
      onPress={onPress}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={[
        styles.navItem,
        isActive && styles.navItemActive,
        isHovered && !isActive && styles.navItemHovered,
      ]}
    >
      <Settings
        size={18}
        strokeWidth={1.5}
        color={isActive || isHovered ? colors.text.primary : colors.text.muted}
      />
      <Text
        style={[styles.navLabel, (isActive || isHovered) && styles.navLabelActive]}
        numberOfLines={1}
      >
        Settings
      </Text>
    </Pressable>
  );
};

// ─── FloatingNav ──────────────────────────────────────────────────────────────

/**
 * FloatingNav - Bottom navigation with glassmorphism, hover effects, and a
 * Settings button that opens an inline modal for profile & appearance changes.
 */
const FloatingNav = () => {
  const router = useRouter();
  const pathname = usePathname();
  const { user } = useAuth();
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Basic toast shim – FloatingNav doesn't have access to the ToastProvider's
  // imperative API directly; wire up a lightweight Alert fallback so the modal
  // can communicate results. Replace with `useToast()` if you lift this modal
  // into a screen that already sits under ToastProvider.
  const handleToast = (type, message) => {
    if (Platform.OS === 'web') {
      // Use the browser's native alert as a simple fallback
      // (replace with useToast from Toast.js when refactoring)
      console[type === 'error' ? 'error' : 'log'](`[${type.toUpperCase()}] ${message}`);
    }
  };

  return (
    <>
      <View style={styles.container}>
        <View style={styles.innerContainer}>
          <BlurView intensity={40} tint="dark" style={styles.blur}>
            <View style={styles.blurContent}>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.scrollContent}
                style={styles.scrollView}
              >
                <View style={styles.nav}>
                  {navItems.map((item) => {
                    const isActive = pathname === item.path;
                    return (
                      <NavItem
                        key={item.path}
                        item={item}
                        isActive={isActive}
                        onPress={() => router.push(item.path)}
                      />
                    );
                  })}

                  {/* Separator */}
                  <View style={styles.separator} />

                  {/* Settings button */}
                  <SettingsNavItem
                    isActive={settingsOpen}
                    onPress={() => setSettingsOpen(true)}
                  />
                </View>
              </ScrollView>
            </View>
          </BlurView>
          <View style={styles.border} />
        </View>
      </View>

      <SettingsModal
        visible={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        user={user}
        onToast={handleToast}
      />
    </>
  );
};

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    bottom: 24,
    left: 0,
    right: 0,
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
  },
  innerContainer: {
    width: '100%',
    maxWidth: 700,
    borderRadius: borderRadius.full,
    overflow: 'hidden',
  },
  blur: {
    borderRadius: borderRadius.full,
  },
  blurContent: {
    backgroundColor: colors.glass.background,
  },
  scrollView: {
    flexGrow: 0,
  },
  scrollContent: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
  },
  nav: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
  },
  separator: {
    width: 1,
    height: 20,
    backgroundColor: 'rgba(255,255,255,0.12)',
    marginHorizontal: 4,
  },
  border: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
    pointerEvents: 'none',
  },
  navItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm + 4,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.lg,
    transition: 'all 0.2s ease',
  },
  navItemActive: {
    backgroundColor: 'rgba(255, 255, 255, 0.15)',
  },
  navItemHovered: {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
  },
  navLabel: {
    fontSize: 13,
    fontWeight: '500',
    color: colors.text.muted,
    transition: 'color 0.2s ease',
  },
  navLabelActive: {
    color: colors.text.primary,
  },
});

export default FloatingNav;
