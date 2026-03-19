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
import { useTheme } from '../context/ThemeContext';
import { authAPI } from '../utils/api';

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/projects', icon: FolderKanban, label: 'Projects' },
  { path: '/workers', icon: Users, label: 'Workers' },
  { path: '/documents', icon: FolderOpen, label: 'Documents' },
  { path: '/reports', icon: FileText, label: 'Reports' },
];

/**
 * SettingsModal
 * - Name change (all users)
 * - Password change (admin / owner only)
 * - Light / Dark mode toggle — wired to ThemeContext
 */
const SettingsModal = ({ visible, onClose, user, onToast }) => {
  const { isDark, toggleTheme } = useTheme();

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

  // Theme-aware input style
  const inputStyle = {
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: colors.text.primary,
    fontSize: 15,
    marginBottom: 10,
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

        <View style={[modalStyles.sheet, { backgroundColor: colors.glass.card }]}>
          <BlurView intensity={60} tint={isDark ? 'dark' : 'light'} style={modalStyles.blurFill}>
            <View style={[modalStyles.handle, { backgroundColor: colors.border.medium }]} />

            {/* Header */}
            <View style={modalStyles.header}>
              <Text style={[modalStyles.title, { color: colors.text.primary }]}>Settings</Text>
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
              <Text style={[modalStyles.sectionLabel, { color: colors.text.muted }]}>APPEARANCE</Text>
              <View style={modalStyles.row}>
                <View style={modalStyles.rowLeft}>
                  {isDark
                    ? <Moon size={18} strokeWidth={1.5} color={colors.text.secondary} />
                    : <Sun size={18} strokeWidth={1.5} color="#f59e0b" />}
                  <Text style={[modalStyles.rowText, { color: colors.text.primary }]}>
                    {isDark ? 'Dark Mode' : 'Light Mode'}
                  </Text>
                </View>
                <Switch
                  value={isDark}
                  onValueChange={toggleTheme}
                  trackColor={{ false: colors.glass.border, true: colors.primary }}
                  thumbColor={colors.white}
                />
              </View>

              {/* ── Personal Details ───────────────────────────────── */}
              <Text style={[modalStyles.sectionLabel, { marginTop: spacing.lg, color: colors.text.muted }]}>
                PERSONAL DETAILS
              </Text>
              <View style={modalStyles.iconRow}>
                <User size={16} strokeWidth={1.5} color={colors.text.muted} />
                <Text style={[modalStyles.fieldLabel, { color: colors.text.muted }]}>Display Name</Text>
              </View>
              <TextInput
                style={inputStyle}
                value={name}
                onChangeText={setName}
                placeholder="Your full name"
                placeholderTextColor={colors.text.subtle}
                autoCapitalize="words"
                autoCorrect={false}
              />

              <Pressable
                onPress={handleSaveName}
                style={[
                  modalStyles.saveBtn,
                  { backgroundColor: `${colors.primary}40`, borderColor: `${colors.primary}66` },
                  saving && { opacity: 0.6 },
                ]}
                disabled={saving}
              >
                {saving
                  ? <ActivityIndicator size="small" color={colors.text.primary} />
                  : <>
                      <Check size={15} strokeWidth={2} color={colors.primary} />
                      <Text style={[modalStyles.saveBtnText, { color: colors.primary }]}>Save Name</Text>
                    </>}
              </Pressable>

              {/* ── Password (admin / owner only) ─────────────────── */}
              {isAdmin && (
                <>
                  <Text style={[modalStyles.sectionLabel, { marginTop: spacing.lg, color: colors.text.muted }]}>
                    CHANGE PASSWORD
                  </Text>
                  <View style={modalStyles.iconRow}>
                    <Lock size={16} strokeWidth={1.5} color={colors.text.muted} />
                    <Text style={[modalStyles.fieldLabel, { color: colors.text.muted }]}>Current Password</Text>
                  </View>
                  <TextInput
                    style={inputStyle}
                    value={currentPassword}
                    onChangeText={setCurrentPassword}
                    placeholder="Enter current password"
                    placeholderTextColor={colors.text.subtle}
                    secureTextEntry
                    autoCorrect={false}
                  />
                  <TextInput
                    style={inputStyle}
                    value={newPassword}
                    onChangeText={setNewPassword}
                    placeholder="New password"
                    placeholderTextColor={colors.text.subtle}
                    secureTextEntry
                    autoCorrect={false}
                  />
                  <TextInput
                    style={inputStyle}
                    value={confirmPassword}
                    onChangeText={setConfirmPassword}
                    placeholder="Confirm new password"
                    placeholderTextColor={colors.text.subtle}
                    secureTextEntry
                    autoCorrect={false}
                  />
                  <Pressable
                    onPress={handleSavePassword}
                    style={[
                      modalStyles.saveBtn,
                      { backgroundColor: `${colors.primary}40`, borderColor: `${colors.primary}66` },
                      savingPassword && { opacity: 0.6 },
                    ]}
                    disabled={savingPassword}
                  >
                    {savingPassword
                      ? <ActivityIndicator size="small" color={colors.text.primary} />
                      : <>
                          <Check size={15} strokeWidth={2} color={colors.primary} />
                          <Text style={[modalStyles.saveBtnText, { color: colors.primary }]}>
                            Update Password
                          </Text>
                        </>}
                  </Pressable>
                </>
              )}

              <View style={{ height: 40 }} />
            </ScrollView>
          </BlurView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const modalStyles = StyleSheet.create({
  overlay:   { flex: 1, justifyContent: 'flex-end' },
  backdrop:  { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.5)' },
  sheet:     { maxHeight: '80%', borderTopLeftRadius: 24, borderTopRightRadius: 24, overflow: 'hidden' },
  blurFill:  { padding: spacing.lg },
  handle:    { width: 36, height: 4, borderRadius: 2, alignSelf: 'center', marginBottom: spacing.md },
  header:    { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.lg },
  title:     { fontSize: 20, fontWeight: '600' },
  closeBtn:  { padding: 4 },
  scroll:    {},
  sectionLabel: { fontSize: 11, fontWeight: '600', letterSpacing: 1.5, marginBottom: spacing.sm },
  row:       { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.lg },
  rowLeft:   { flexDirection: 'row', alignItems: 'center', gap: 10 },
  rowText:   { fontSize: 15, fontWeight: '500' },
  iconRow:   { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 },
  fieldLabel:{ fontSize: 12 },
  saveBtn:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, borderWidth: 1, borderRadius: 12, paddingVertical: 11, marginTop: 4 },
  saveBtnText: { fontSize: 14, fontWeight: '600' },
});

// ─── NavItem ─────────────────────────────────────────────────────────────────

const NavItem = ({ item, isActive, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();
  const Icon = item.icon;

  // active: bg-blue-50 (#EFF6FF) in light, rgba(255,255,255,0.15) in dark
  const activeBg = isDark ? 'rgba(255, 255, 255, 0.15)' : '#EFF6FF';
  const hoverBg  = isDark ? 'rgba(255, 255, 255, 0.10)' : 'rgba(191, 219, 254, 0.30)';

  return (
    <Pressable
      onPress={onPress}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={[
        styles.navItem,
        isActive && { backgroundColor: activeBg },
        isHovered && !isActive && { backgroundColor: hoverBg },
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
          { color: (isActive || isHovered) ? colors.text.primary : colors.text.muted },
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
  const { isDark } = useTheme();

  const activeBg = isDark ? 'rgba(255, 255, 255, 0.15)' : '#EFF6FF';
  const hoverBg  = isDark ? 'rgba(255, 255, 255, 0.10)' : 'rgba(191, 219, 254, 0.30)';

  return (
    <Pressable
      onPress={onPress}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={[
        styles.navItem,
        isActive && { backgroundColor: activeBg },
        isHovered && !isActive && { backgroundColor: hoverBg },
      ]}
    >
      <Settings
        size={18}
        strokeWidth={1.5}
        color={isActive || isHovered ? colors.text.primary : colors.text.muted}
      />
      <Text
        style={[styles.navLabel, { color: (isActive || isHovered) ? colors.text.primary : colors.text.muted }]}
        numberOfLines={1}
      >
        Settings
      </Text>
    </Pressable>
  );
};

// ─── FloatingNav ──────────────────────────────────────────────────────────────

/**
 * Nav bar spec (light):
 *   bg-white/90  backdrop-blur-2xl  rounded-[28px]
 *   border border-blue-200/60
 *   shadow-xl shadow-blue-900/10
 */
const FloatingNav = () => {
  const router = useRouter();
  const pathname = usePathname();
  const { user } = useAuth();
  const { isDark } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const handleToast = (type, message) => {
    if (Platform.OS === 'web') {
      console[type === 'error' ? 'error' : 'log'](`[${type.toUpperCase()}] ${message}`);
    }
  };

  // bg-white/90 in light, glass.background in dark
  const navBg = isDark
    ? colors.glass.background
    : 'rgba(255, 255, 255, 0.90)';

  return (
    <>
      <View style={styles.container}>
        <View style={[styles.innerContainer, !isDark && {
          // shadow-xl shadow-blue-900/10
          shadowColor: 'rgba(30, 58, 138, 0.10)',
          shadowOffset: { width: 0, height: 8 },
          shadowOpacity: 0.1,
          shadowRadius: 24,
          elevation: 8,
        }]}>
          <BlurView intensity={40} tint={isDark ? 'dark' : 'light'} style={styles.blur}>
            <View style={[styles.blurContent, { backgroundColor: navBg }]}>
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
                  <View style={[styles.separator, { backgroundColor: colors.border.subtle }]} />

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
  blurContent: {},
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
    marginHorizontal: 4,
  },
  border: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.15)',
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
  navLabel: {
    fontSize: 13,
    fontWeight: '500',
    color: 'rgba(255, 255, 255, 0.4)',
    transition: 'color 0.2s ease',
  },
  navLabelActive: {
    color: colors.text.primary,
  },
});

export default FloatingNav;
