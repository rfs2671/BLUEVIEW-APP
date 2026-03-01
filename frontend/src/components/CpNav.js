import React from 'react';
import { View, StyleSheet, Pressable, Text } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { BlurView } from 'expo-blur';
import { LayoutDashboard, BookOpen, FolderOpen, Settings } from 'lucide-react-native';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

const CP_NAV_ITEMS = [
  { path: '/logbooks',       icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/logbooks/books', icon: BookOpen,        label: 'Log Books' },
  { path: '/documents',      icon: FolderOpen,      label: 'Documents' },
  { path: '/settings',       icon: Settings,        label: 'Settings'  },
];

const NavItem = ({ item, isActive, onPress }) => {
  const Icon = item.icon;
  return (
    <Pressable
      onPress={onPress}
      style={[styles.navItem, isActive && styles.navItemActive]}
    >
      <Icon size={18} strokeWidth={1.5} color={isActive ? colors.text.primary : colors.text.muted} />
      <Text style={[styles.navLabel, { color: isActive ? colors.text.primary : colors.text.muted }]}>
        {item.label}
      </Text>
    </Pressable>
  );
};

const CpNav = () => {
  const router   = useRouter();
  const pathname = usePathname();
  const { isDark } = useTheme();

  return (
    <View style={styles.container}>
      <View style={styles.innerContainer}>
        <BlurView intensity={40} tint={isDark ? 'dark' : 'light'} style={styles.blur}>
          <View style={[styles.blurContent, { backgroundColor: colors.glass.background }]}>
            <View style={styles.nav}>
              {CP_NAV_ITEMS.map((item) => {
                const isActive =
                  pathname === item.path ||
                  (item.path === '/logbooks/books' &&
                   pathname.startsWith('/logbooks/') &&
                   pathname !== '/logbooks');
                return (
                  <NavItem
                    key={item.path}
                    item={item}
                    isActive={isActive}
                    onPress={() => router.push(item.path)}
                  />
                );
              })}
            </View>
          </View>
        </BlurView>
        <View style={[styles.border, { borderColor: colors.glass.border }]} />
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
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
  navItemActive: { backgroundColor: 'rgba(128,128,128,0.20)' },
  navLabel: { fontSize: 11, fontWeight: '500' },
  border: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: borderRadius.full, borderWidth: 1, pointerEvents: 'none',
  },
});

export default CpNav;
