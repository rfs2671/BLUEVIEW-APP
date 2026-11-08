import React, { useState, useEffect } from 'react';
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
  KeyboardAvoidingView,
  useWindowDimensions,
} from 'react-native';
import Svg, { Path } from 'react-native-svg';
import Animated, {
  useSharedValue,
  useAnimatedProps,
  useAnimatedStyle,
  withSpring,
} from 'react-native-reanimated';
import { useRouter, usePathname } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
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
import { colors, spacing } from '../styles/theme';
import { useAuth, isCompanyAdmin, isAccountAdmin } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { useIsDesktop } from '../hooks/useIsDesktop';
import { authAPI } from '../utils/api';
import { semantic, withAlpha } from '../styles/semanticColors';

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/projects', icon: FolderKanban, label: 'Projects' },
  { path: '/workers', icon: Users, label: 'Workers' },
  { path: '/reports', icon: FileText, label: 'Reports' },
];

// The bar is a solid, full-width strip flush to the bottom of the screen. Its
// bottom padding is `insets.bottom + NAV_BOTTOM_PADDING`, applied inline at
// render (see FloatingNav) because a StyleSheet is built before any inset
// exists. The inset clears the system navigation bar; this constant is the
// small breathing room under the labels on top of it.
export const NAV_BOTTOM_PADDING = 8;

// Notch geometry. The bar's top edge is scooped out under the active tab and a
// raised circle holding the active icon sits in the scoop; both slide to the
// tapped tab on a spring. TOP is the bar's top edge inside the container (the
// headroom above it is where the circle rises).
const BAR_H = 52;          // tab row height, excluding the bottom inset
const CIRCLE = 46;         // active bubble diameter
const NOTCH_DEPTH = 26;    // how far the scoop dips below the bar's top edge
const TOP = CIRCLE / 2 + 4; // headroom above the bar line
const SPRING = { damping: 16, stiffness: 190, mass: 0.8 };

const AnimatedPath = Animated.createAnimatedComponent(Path);

/**
 * SettingsModal
 * - Name change (all users)
 * - Password change (admin / owner only)
 * - Light / Dark mode toggle — wired to ThemeContext
 */
const SettingsModal = ({ visible, onClose, user, onToast }) => {
  const { isDark, toggleTheme, themeForced } = useTheme();

  const [name, setName] = useState(user?.full_name || user?.name || '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);

  const isAdmin = isCompanyAdmin(user);

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
    // Password min-length check removed (temporary regression — see backend).
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
        behavior="padding"
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
                    : <Sun size={18} strokeWidth={1.5} color={semantic.neutral} />}
                  <Text style={[modalStyles.rowText, { color: colors.text.primary }]}>
                    {isDark ? 'Dark Mode' : 'Light Mode'}
                  </Text>
                </View>
                <Switch
                  value={isDark}
                  onValueChange={toggleTheme}
                  disabled={themeForced}
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

              {/* ── Password (admin only: the server's admin-seat route,
                  which a full-access PM does not hold) ───────────── */}
              {isAccountAdmin(user) && (
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
  backdrop:  { ...StyleSheet.absoluteFillObject, backgroundColor: withAlpha('#000000', 0.5) },
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

// One tab: icon stacked above a one-line label. Inactive tabs sit at 72%
// opacity. The active tab's icon is drawn in the raised circle instead (see
// FloatingNav), so here it is hidden and only the label remains under the notch.
const NavTab = ({ icon: Icon, label, isActive, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);

  return (
    <Pressable
      onPress={onPress}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={[
        styles.navItem,
        isActive && styles.navItemActive,
        isHovered && !isActive && styles.navItemHover,
      ]}
    >
      <View style={{ opacity: isActive ? 0 : 1 }}>
        <Icon size={18} strokeWidth={1.8} color={colors.onBar} />
      </View>
      {/* numberOfLines IS LOAD-BEARING: five equal columns share the width, and
          a squeezed label must ellipsize rather than wrap into a taller bar. */}
      <Text style={styles.navLabel} numberOfLines={1}>
        {label}
      </Text>
    </Pressable>
  );
};

const NavItem = ({ item, isActive, onPress }) => (
  <NavTab icon={item.icon} label={item.label} isActive={isActive} onPress={onPress} />
);

// ─── SettingsNavItem ──────────────────────────────────────────────────────────

const SettingsNavItem = ({ onPress, isActive }) => (
  <NavTab icon={Settings} label="Settings" isActive={isActive} onPress={onPress} />
);

// Path of the bar with a scoop centred on cx. depth 0 = flat top (no tab active).
function buildBarPath(width, height, cx, depth) {
  'worklet';
  const d = NOTCH_DEPTH * depth;
  const half = 36; // half-width of the scoop's shoulders
  const k = 22;    // curve tension
  return (
    `M0,${TOP} L${cx - half},${TOP} ` +
    `C${cx - half + k},${TOP} ${cx - k},${TOP + d} ${cx},${TOP + d} ` +
    `C${cx + k},${TOP + d} ${cx + half - k},${TOP} ${cx + half},${TOP} ` +
    `L${width},${TOP} L${width},${height} L0,${height} Z`
  );
}

// ─── FloatingNav ──────────────────────────────────────────────────────────────

/**
 * Nav bar spec:
 *   solid colors.bar strip, full width, flush to the bottom edge
 *   scooped notch in the top edge under the active tab, with a raised
 *   colors.barActive circle carrying the active icon; both spring-slide
 *   between tabs. Inactive tabs: icon over a one-line 11pt label at 72%.
 */
const FloatingNav = () => {
  const router = useRouter();
  const pathname = usePathname();
  const insets = useSafeAreaInsets();
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  const isDesktop = useIsDesktop();
  const { width } = useWindowDimensions();

  const tabs = [...navItems, { path: '/settings', icon: Settings, label: 'Settings' }];
  const activeIndex = tabs.findIndex((t) => t.path === pathname);
  const hasActive = activeIndex >= 0;

  const padX = spacing.sm;
  const tabW = (width - padX * 2) / tabs.length;
  const centerOf = (i) => padX + tabW * (i + 0.5);
  const barBottom = insets.bottom + NAV_BOTTOM_PADDING;
  const height = TOP + BAR_H + barBottom;

  const cx = useSharedValue(centerOf(Math.max(activeIndex, 0)));
  const depth = useSharedValue(hasActive ? 1 : 0);
  const pop = useSharedValue(1);
  const [shownIndex, setShownIndex] = useState(Math.max(activeIndex, 0));

  useEffect(() => {
    if (hasActive) {
      cx.value = withSpring(centerOf(activeIndex), SPRING);
      depth.value = withSpring(1, SPRING);
      setShownIndex(activeIndex);
      pop.value = 0.82;
      pop.value = withSpring(1, SPRING);
    } else {
      depth.value = withSpring(0, SPRING);
    }
    // centerOf depends on width; re-snap on resize/rotation as well.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex, width]);

  const pathProps = useAnimatedProps(() => ({
    d: buildBarPath(width, height, cx.value, depth.value),
  }));

  const circleStyle = useAnimatedStyle(() => ({
    opacity: depth.value,
    transform: [
      { translateX: cx.value - CIRCLE / 2 },
      { scale: pop.value * (0.4 + 0.6 * depth.value) },
    ],
  }));

  // Desktop (RN-Web >= 1024) navigates via DesktopShell's left rail, so the
  // floating tab bar must not render. Suppressed here rather than in each
  // screen: FloatingNav is mounted by 19 separate screens, and this PR is
  // additive — no screen component is modified. All hooks above run first, so
  // this early return is hook-order safe. Native/web <1024 are unaffected.
  if (isDesktop) return null;

  const ActiveIcon = tabs[shownIndex].icon;

  return (
    <View style={[styles.container, { height }]} pointerEvents="box-none">
      <Svg width={width} height={height} style={StyleSheet.absoluteFill} pointerEvents="none">
        <AnimatedPath animatedProps={pathProps} fill={colors.bar} />
      </Svg>

      {/* Raised active bubble, nested in the scoop */}
      <Animated.View pointerEvents="none" style={[styles.circle, circleStyle]}>
        <ActiveIcon size={20} strokeWidth={1.9} color={colors.bar} />
      </Animated.View>

      <View style={[styles.row, { top: TOP, paddingBottom: barBottom, paddingHorizontal: padX }]}>
        {tabs.map((item, i) => (
          <NavItem
            key={item.path}
            item={item}
            isActive={i === activeIndex}
            onPress={() => router.push(item.path)}
          />
        ))}
      </View>
    </View>
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  // Height and bottom inset are applied inline at render (a StyleSheet is built
  // before any inset exists). Absolute positioning puts the bar outside the
  // inset flow, so the inset is added to the tab row's padding there; the bar
  // stays flush to the bottom edge and its fill runs under the system bar.
  container: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
  },
  row: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: 'row',
  },
  circle: {
    position: 'absolute',
    top: TOP + NOTCH_DEPTH - CIRCLE - 4,
    left: 0,
    width: CIRCLE,
    height: CIRCLE,
    borderRadius: CIRCLE / 2,
    backgroundColor: colors.barActive,
    alignItems: 'center',
    justifyContent: 'center',
  },
  // Equal-width columns. minWidth: 0 lets a flex child shrink below its
  // content so the label ellipsizes instead of widening its column.
  navItem: {
    flex: 1,
    minWidth: 0,
    alignItems: 'center',
    gap: 3,
    paddingTop: 8,
    opacity: 0.72,
  },
  navItemActive: {
    opacity: 1,
  },
  navItemHover: {
    opacity: 1,
  },
  navLabel: {
    fontSize: 11,
    lineHeight: 14,
    fontWeight: '600',
    color: colors.onBar,
  },
  });
}
export default FloatingNav;
