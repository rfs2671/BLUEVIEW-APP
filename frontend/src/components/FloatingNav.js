import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, ScrollView } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { BlurView } from 'expo-blur';
import {
  LayoutDashboard,
  FolderKanban,
  Users,
  FileText,
  FolderOpen,
} from 'lucide-react-native';
import { colors, borderRadius, spacing } from '../styles/theme';

const navItems = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/projects', icon: FolderKanban, label: 'Projects' },
  { path: '/workers', icon: Users, label: 'Workers' },
  { path: '/documents', icon: FolderOpen, label: 'Documents' },
  { path: '/reports', icon: FileText, label: 'Reports' },
];

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

/**
 * FloatingNav - Bottom navigation with glassmorphism and hover effects
 */
const FloatingNav = () => {
  const router = useRouter();
  const pathname = usePathname();

  return (
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
              </View>
            </ScrollView>
          </View>
        </BlurView>
        <View style={styles.border} />
      </View>
    </View>
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
    width: '100%'
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
