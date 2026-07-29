import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, ScrollView } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { BlurView } from 'expo-blur';
import { LayoutDashboard, Users, FileText } from 'lucide-react-native';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
import { withAlpha } from '../styles/semanticColors';
import { useIsWide } from '../hooks/useIsDesktop';

/**
 * `/site/workers` HAS NO ROUTE FILE. app/site/ contains index, checkins,
 * daily-logs, documents and logbooks — nothing else. Tapping the third item
 * landed the jobsite tablet on Expo Router's developer "Unmatched Route" page,
 * complete with a Sitemap link.
 *
 * Retargeted rather than removed: /site/checkins IS the workers view (it is
 * what the "Worker Sign In" tile on /site opens), so the destination existed
 * all along and only the path was wrong. Removing the item would have left the
 * bar with two entries and taken a real screen out of the navigation. The label
 * follows the screen's own title — "Check-Ins" — so the bar and the page agree.
 */
const siteNavItems = [
  { path: '/site', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/site/logbooks', icon: FileText, label: 'Log Books' },
  { path: '/site/checkins', icon: Users, label: 'Check-Ins' },
];

const SiteNavItem = ({ item, isActive, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  const Icon = item.icon;

  const activeBg = isDark ? withAlpha('#ffffff', 0.15) : '#EFF6FF';
  const hoverBg  = isDark ? withAlpha('#ffffff', 0.1) : 'rgba(191, 219, 254, 0.30)';

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
  const { colors, isDark } = useTheme();
  const isWide = useIsWide();
  const styles = buildStyles(colors, isDark);

  const navBg = isDark ? colors.glass.background : withAlpha('#ffffff', 0.9);

  // DOCKED ON A TABLET, floating on a phone. Floating over a 390px column
  // covers a margin; floating over a 1280px document covers the middle of the
  // activity table — on /site/logbooks it sat squarely on the WORKERS and
  // DESCRIPTION cells. Docked, it takes its own strip and obscures nothing.
  return (
    <View
      style={[styles.container, isWide && styles.containerDocked]}
      pointerEvents="box-none"
    >
      <View style={styles.pill}>
      <BlurView intensity={40} tint={isDark ? 'dark' : 'light'} style={styles.blur}>
        <View style={[styles.nav, { backgroundColor: navBg }]}>
          {siteNavItems.map((item) => {
            // EXACT match for the dashboard. `startsWith` made '/site' true on
            // every child route, so "Dashboard" was permanently lit alongside
            // whichever item was actually active.
            const isActive = item.path === '/site'
              ? pathname === '/site'
              : pathname === item.path || pathname.startsWith(`${item.path}/`);
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
    </View>
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  // SIZES TO ITS CONTENT. This was `width: 360` centred by a hardcoded
  // `translateX(-180)`, which clipped the third label mid-word ("Worker…") at
  // every viewport — the bar could not fit its own three items. Now it spans
  // the parent and centres an intrinsically-sized pill, the same construction
  // FloatingNav uses, so the pill is as wide as its labels need and no wider.
  // pointerEvents box-none on the full-width container so it does not swallow
  // taps on the content either side of the pill.
  container: {
    position: 'absolute',
    bottom: 24,
    left: 0,
    right: 0,
    alignItems: 'center',
  },
  containerDocked: {
    position: 'relative',
    bottom: 0,
    paddingVertical: spacing.sm,
  },
  // The pill is what the border traces. Keeping the border a sibling of the
  // blur INSIDE this wrapper (rather than of the full-width container) is what
  // stops the outline stretching edge to edge.
  pill: {
    alignSelf: 'center',
    maxWidth: '96%',
    borderRadius: borderRadius.full,
    position: 'relative',
  },
  blur: {
    borderRadius: borderRadius.full,
    overflow: 'hidden',
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
  // 16 + 18 + 16 = 50pt tall. Was 42 — under the 44 minimum, on a device
  // operated with work gloves.
  navItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    minHeight: 44,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    borderRadius: borderRadius.lg,
    transition: 'all 0.2s ease',
  },
  navLabel: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.muted,
    transition: 'color 0.2s ease',
  },
  navLabelActive: {
    color: colors.text.primary,
  },
  });
}
export default SiteNav;
