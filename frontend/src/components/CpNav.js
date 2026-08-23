/**
 * CpNav.js
 * Place at: frontend/src/components/CpNav.js
 *
 * FIX #2: Removed the "Log Books" tab (/logbooks/books) because /logbooks
 * IS the dashboard. Having both "Dashboard" and "Log Books" point to the
 * same content was confusing. Now: Dashboard, Documents, Settings.
 */

import React from 'react';
import { View, StyleSheet, Pressable, Text, Platform } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BlurView } from 'expo-blur';
import { LayoutDashboard, FolderOpen, Settings } from 'lucide-react-native';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
import { withAlpha } from '../styles/semanticColors';

const CP_NAV_ITEMS = [
  { path: '/logbooks',  icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/settings',  icon: Settings,        label: 'Settings'  },
];

const NavItem = ({ item, isActive, onPress, colors: c }) => {
  const Icon = item.icon;
  return (
    <Pressable
      onPress={onPress}
      style={[styles.navItem, isActive && styles.navItemActive]}
    >
      <Icon size={18} strokeWidth={1.5} color={isActive ? c.text.primary : c.text.muted} />
      <Text style={[styles.navLabel, { color: isActive ? c.text.primary : c.text.muted }]}>
        {item.label}
      </Text>
    </Pressable>
  );
};

const CpNav = () => {
  const router   = useRouter();
  const pathname = usePathname();
  const insets   = useSafeAreaInsets();
  const { isDark, colors: c } = useTheme();

  // blurContent already carries a near-opaque background, so the nav
  // reads fine without the blur layer.
  const navInner = (
    <View style={[styles.blurContent, { backgroundColor: isDark ? colors.glass.background : withAlpha('#ffffff', 0.9) }]}>
      <View style={styles.nav}>
        {CP_NAV_ITEMS.map((item) => {
          const isActive =
            pathname === item.path ||
            (item.path === '/logbooks' &&
             pathname.startsWith('/logbooks/'));
          return (
            <NavItem
              key={item.path}
              item={item}
              isActive={isActive}
              onPress={() => router.push(item.path)}
              colors={c}
            />
          );
        })}
      </View>
    </View>
  );

  return (
    <View style={[styles.container, { bottom: insets.bottom + 24 }]}>
      <View style={styles.innerContainer}>
        {/* Web keeps expo-blur; native falls back to a plain View —
            the native BlurView was throwing a render exception on
            device, and blurContent's near-opaque fill already covers
            the look. Reversible. */}
        {Platform.OS === 'web' ? (
          <BlurView intensity={40} tint={isDark ? 'dark' : 'light'} style={styles.blur}>
            {navInner}
          </BlurView>
        ) : (
          <View style={styles.blur}>{navInner}</View>
        )}
        <View style={[styles.border, { borderColor: colors.glass.border }]} />
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    // OVERRIDDEN AT RENDER. The component passes
    // { bottom: insets.bottom + 24 } inline, which REPLACES this value — it
    // does not add to it. The 24 below is therefore a fallback that only
    // applies if these styles are used without the component.
    //
    // It has to be done inline: a StyleSheet is built once at module load,
    // before any inset exists. And it has to be done at all because
    // absolute positioning puts this outside the inset flow — neither the
    // screen's SafeAreaView nor its paddingBottom: 120 reaches it, so a
    // hardcoded 24 leaves the nav under the buttons on 3-button navigation.
    position: 'absolute',
    bottom: 24, left: 0, right: 0,
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
  },
  innerContainer: {
    width: '100%', maxWidth: 520,
    borderRadius: borderRadius.full, overflow: 'hidden',
  },
  blur:        { borderRadius: borderRadius.full },
  blurContent: { paddingVertical: spacing.sm, paddingHorizontal: spacing.sm },
  nav: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-around',
  },
  navItem: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: spacing.xs, paddingVertical: spacing.sm + 4, paddingHorizontal: spacing.xs,
    borderRadius: borderRadius.lg,
  },
  navItemActive: { backgroundColor: withAlpha('#808080', 0.2) },
  navLabel: { fontSize: 11, fontWeight: '500' },
  border: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: borderRadius.full, borderWidth: 1, pointerEvents: 'none',
  },
});

export default CpNav;
