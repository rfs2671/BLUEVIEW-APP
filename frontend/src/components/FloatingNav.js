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
  withTiming,
  withSequence,
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
  Moon as MoonIcon,
  Sun as SunIcon,
  X,
  Sun,
  Moon,
  User,
  Lock,
  Check,
} from 'lucide-react-native';
import { colors, spacing } from '../styles/theme';
import { registerNavChrome } from '../utils/navChromeStore';
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
const BAR_H = 54;          // tab row height, excluding the bottom inset
const CIRCLE = 44;         // active bubble diameter
const GAP = 6;             // even clearance between bubble and the bar edge around it
const NOTCH_R = CIRCLE / 2 + GAP; // radius of the scoop (concentric with the bubble)
const BUBBLE_CY = 1;       // bubble centre, px below the bar's top edge
const TOP = CIRCLE / 2 + 14; // headroom above the bar line (room for the lift)
const SPRING = { damping: 13, stiffness: 150, mass: 0.9 };

// Every screen mounts its own FloatingNav, so component state is lost on each
// navigation and a new instance would start AT the destination (no slide). This
// module-level value carries the previously active tab across remounts so the
// new instance can start there and visibly glide to its own tab.
let lastNavIndex = -1;

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
                  trackColor={{ false: colors.glass.border, true: colors.switchOn }}
                  thumbColor={colors.switchThumb}
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

// ─── ThemeToggle ──────────────────────────────────────────────────────────────

// Sits after a divider at the end of the bar. Tapping floods the screen with the
// other theme from this button (see ThemeContext.toggleThemeAnimated). The app
// remounts on a switch, so the icon turns in on mount when the mode changed.
let lastShownDark = null;
const TOGGLE_W = 54;

const ThemeToggle = () => {
  const { colors, isDark, toggleThemeAnimated } = useTheme();
  const ref = React.useRef(null);
  const spin = useSharedValue(lastShownDark === null || lastShownDark === isDark ? 1 : 0);
  const squash = useSharedValue(0);   // 0 at rest, 1 fully pressed
  const ring = useSharedValue(1);     // 0 -> 1 one ripple, 1 = finished/invisible

  useEffect(() => {
    lastShownDark = isDark;
    spin.value = withSpring(1, { damping: 11, stiffness: 120 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDark]);

  const iconStyle = useAnimatedStyle(() => ({
    opacity: spin.value,
    transform: [
      { rotate: `${(1 - spin.value) * -140}deg` },
      { scaleX: (0.5 + 0.5 * spin.value) * (1 + 0.25 * squash.value) },
      { scaleY: (0.5 + 0.5 * spin.value) * (1 - 0.2 * squash.value) },
    ],
  }), [spin, squash]);
  const ringStyle = useAnimatedStyle(() => ({
    opacity: 0.55 * (1 - ring.value),
    transform: [{ scale: 1 + 1.4 * ring.value }],
  }), [ring]);

  const onPress = () => {
    // The ripple and squash play first; the spread of the new theme follows a
    // beat later so the button is seen to cause it.
    ring.value = 0;
    ring.value = withTiming(1, { duration: 380 });
    const go = (x, y) => setTimeout(() => toggleThemeAnimated({ x, y }), 90);
    if (ref.current && ref.current.measureInWindow) {
      ref.current.measureInWindow((x, y, w, h) => go(x + w / 2, y + h / 2));
    } else {
      go(undefined, undefined);
    }
  };

  const Icon = isDark ? MoonIcon : SunIcon;
  return (
    <View ref={ref} collapsable={false} style={{ width: TOGGLE_W, alignItems: 'center', justifyContent: 'flex-start', paddingTop: 11 }}>
      <View style={{ position: 'absolute', left: 0, top: 12, width: 1, height: 28, backgroundColor: withAlpha(colors.onBar, 0.22) }} />
      <Animated.View
        pointerEvents="none"
        style={[{ position: 'absolute', top: 11, width: 34, height: 34, borderRadius: 17, borderWidth: 1.5, borderColor: colors.onBar }, ringStyle]}
      />
      <Pressable
        onPress={onPress}
        onPressIn={() => { squash.value = withTiming(1, { duration: 80 }); }}
        onPressOut={() => { squash.value = withSpring(0, { damping: 8, stiffness: 220 }); }}
        accessibilityRole="button"
        accessibilityLabel={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        hitSlop={6}
        style={({ pressed }) => [{ width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' }, pressed && { backgroundColor: withAlpha(colors.onBar, 0.12) }]}
      >
        <Animated.View style={iconStyle}>
          <Icon size={18} strokeWidth={1.8} color={colors.onBar} />
        </Animated.View>
      </Pressable>
    </View>
  );
};

// Path of the bar with a scoop wrapped around the bubble. The scoop's bottom is a
// circular arc concentric with the bubble (so the gap is even all the way round),
// blended into the flat top edge with S-curve shoulders so the bar "bends" around
// it. depth 0 = flat top (no tab active); the arc slides up out of the bar.
function buildBarPath(width, height, cx, depth) {
  'worklet';
  if (depth < 0.04) {
    return `M0,${TOP} L${width},${TOP} L${width},${height} L0,${height} Z`;
  }
  const cy = TOP + BUBBLE_CY - (1 - depth) * (NOTCH_R + 14);
  const phi = 1.08;                       // arc half-span from straight down (rad)
  const sn = Math.sin(phi);
  const cs = Math.cos(phi);
  const lx = cx - NOTCH_R * sn;           // arc ends (left / right)
  const rx = cx + NOTCH_R * sn;
  const ly = cy + NOTCH_R * cs;
  const sh = 26;                          // shoulder run
  const k = 14;                           // shoulder tension
  return (
    `M0,${TOP} L${lx - sh},${TOP} ` +
    `C${lx - sh + k},${TOP} ${lx - cs * k},${ly - sn * k} ${lx},${ly} ` +
    `A${NOTCH_R},${NOTCH_R} 0 0 0 ${rx},${ly} ` +
    `C${rx + cs * k},${ly - sn * k} ${rx + sh - k},${TOP} ${rx + sh},${TOP} ` +
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
  const { themeForced } = useTheme();
  const toggleW = themeForced ? 0 : TOGGLE_W;

  const tabs = navItems;
  const activeIndex = tabs.findIndex((t) => t.path === pathname);
  const hasActive = activeIndex >= 0;

  const padX = spacing.sm;
  const tabW = (width - padX * 2 - toggleW) / tabs.length;
  const centerOf = (i) => padX + tabW * (i + 0.5);
  const barBottom = insets.bottom + NAV_BOTTOM_PADDING;
  const height = TOP + BAR_H + barBottom;

  // Where the bubble starts: the tab active before this screen mounted (so it
  // slides in), else straight at the current tab.
  const fromIndex = lastNavIndex >= 0 ? lastNavIndex : activeIndex;
  const cx = useSharedValue(centerOf(Math.max(fromIndex, 0)));
  const depth = useSharedValue(fromIndex >= 0 ? 1 : 0);
  const lift = useSharedValue(0);   // bubble rises mid-move, then settles
  const iconT = useSharedValue(1);  // 0 -> 1 crossfade outgoing -> incoming icon
  const shownRef = React.useRef(fromIndex);
  const [prevIdx, setPrevIdx] = useState(fromIndex);

  useEffect(() => {
    if (hasActive) {
      cx.value = withSpring(centerOf(activeIndex), SPRING);
      depth.value = withSpring(1, SPRING);
      if (shownRef.current !== activeIndex && shownRef.current >= 0) {
        setPrevIdx(shownRef.current);
        iconT.value = 0;
        iconT.value = withTiming(1, { duration: 300 });
        lift.value = withSequence(
          withTiming(1, { duration: 150 }),
          withSpring(0, { damping: 9, stiffness: 140 }),
        );
      }
      shownRef.current = activeIndex;
      lastNavIndex = activeIndex;
    } else {
      depth.value = withSpring(0, SPRING);
      lastNavIndex = -1;
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
      { translateY: -10 * lift.value },
      { scale: (0.4 + 0.6 * depth.value) * (1 + 0.1 * lift.value) },
    ],
  }));
  const inIconStyle = useAnimatedStyle(() => ({
    opacity: iconT.value,
    transform: [{ scale: 0.5 + 0.5 * iconT.value }],
  }));
  const outIconStyle = useAnimatedStyle(() => ({
    opacity: Math.max(0, 1 - iconT.value * 2.2),
    transform: [{ scale: 1 - 0.4 * iconT.value }],
  }));

  // Tell the app root the bar is on screen so the corner settings button shows.
  useEffect(() => {
    if (isDesktop) return undefined;
    return registerNavChrome();
  }, [isDesktop]);

  // Desktop (RN-Web >= 1024) navigates via DesktopShell's left rail, so the
  // floating tab bar must not render. Suppressed here rather than in each
  // screen: FloatingNav is mounted by 19 separate screens, and this PR is
  // additive — no screen component is modified. All hooks above run first, so
  // this early return is hook-order safe. Native/web <1024 are unaffected.
  if (isDesktop) return null;

  const ActiveIcon = tabs[Math.max(activeIndex, 0)].icon;
  const PrevIcon = tabs[Math.max(prevIdx, 0)].icon;

  return (
    <View style={[styles.container, { height }]} pointerEvents="box-none">
      <Svg width={width} height={height} style={StyleSheet.absoluteFill} pointerEvents="none">
        <AnimatedPath animatedProps={pathProps} fill={colors.bar} />
      </Svg>

      {/* Raised active bubble, nested in the scoop */}
      <Animated.View pointerEvents="none" style={[styles.circle, circleStyle]}>
        <Animated.View style={[styles.circleIcon, outIconStyle]}>
          <PrevIcon size={21} strokeWidth={1.9} color={colors.bar} />
        </Animated.View>
        <Animated.View style={[styles.circleIcon, inIconStyle]}>
          <ActiveIcon size={21} strokeWidth={1.9} color={colors.bar} />
        </Animated.View>
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
        {!themeForced && <ThemeToggle />}
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
    top: TOP + BUBBLE_CY - CIRCLE / 2,
    left: 0,
    width: CIRCLE,
    height: CIRCLE,
    borderRadius: CIRCLE / 2,
    backgroundColor: colors.barActive,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: colors.barActive,
    shadowOpacity: 0.5,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 0 },
    elevation: 6,
  },
  circleIcon: {
    ...StyleSheet.absoluteFillObject,
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
    paddingTop: 11,
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
