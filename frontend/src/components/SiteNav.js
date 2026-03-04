import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, ScrollView } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { BlurView } from 'expo-blur';
import { LayoutDashboard, Users, FileText } from 'lucide-react-native';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

const siteNavItems = [
  { path: '/site', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/site/workers', icon: Users, label: 'Workers' },
  { path: '/site/documents', icon: FileText, label: 'Documents' },
];

const SiteNavItem = ({ item, isActive, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { isDark } = useTheme();
  const Icon = item.icon;

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
          (isActive || isHovered) && styles.navLabelActive,
        ]}
        numberOfLines={1}
      >
        {item.label}
      </Text>
    </Pressable>
  );
};

/**
 * SiteNav - Bottom navigation for site mode
 */
const SiteNav = () => {
  const router = useRouter();
  const pathname = usePathname();
  const { isDark } = useTheme();

  const navBg = isDark ? colors.glass.background : 'rgba(255, 255, 255, 0.90)';

  return (
    <View style={styles.container}>
      <BlurView intensity={40} tint={isDark ? 'dark' : 'light'} style={styles.blur}>
        <View style={[styles.nav, { backgroundColor: navBg }]}>
          {siteNavItems.map((item) => {
            const isActive = pathname === item.path || pathname.startsWith(item.path);
            return (
              <SiteNavItem
                key={item.path}
                item={item}
                isActive={isActive}
                onPress={() => router.push(item.path)}
              />
            );
          })}
        </View>
      </BlurView>
      <View style={styles.border} />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    bottom: 24,
    left: '50%',
    transform: [{ translateX: -180 }],
    width: 360,
    borderRadius: borderRadius.full,
    overflow: 'hidden',
  },
  blur: {
    borderRadius: borderRadius.full,
  },
  nav: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
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
    paddingHorizontal: spacing.lg,
    borderRadius: borderRadius.lg,
    transition: 'all 0.2s ease',
  },
  navLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.muted,
    transition: 'color 0.2s ease',
  },
  navLabelActive: {
    color: colors.text.primary,
  },
});

export default SiteNav;
