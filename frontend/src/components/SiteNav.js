import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { LayoutDashboard, Users, FileText } from 'lucide-react-native';
import { spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
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

// The bar is a solid, full-width strip. Its bottom padding is
// `insets.bottom + SITE_NAV_BOTTOM_PADDING`, applied inline at render because
// a StyleSheet is built before any inset exists. The screens that mount this
// inset only the top edge, so the bar clears the system navigation bar itself.
export const SITE_NAV_BOTTOM_PADDING = 8;

const SiteNavItem = ({ item, isActive, onPress }) => {
  const [isHovered, setIsHovered] = useState(false);
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  const Icon = item.icon;

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
      <Icon size={18} strokeWidth={1.8} color={colors.onBar} />
      <Text style={styles.navLabel} numberOfLines={1}>
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
  const insets = useSafeAreaInsets();
  const { colors, isDark } = useTheme();
  const isWide = useIsWide();
  const styles = buildStyles(colors, isDark);

  // DOCKED ON A TABLET, absolute on a phone. Overlaid on a 1280px document the
  // bar sat squarely on the WORKERS and DESCRIPTION cells of the activity
  // table on /site/logbooks. Docked, it takes its own strip and obscures
  // nothing. Either way it is a solid, full-width bar flush to the bottom.
  return (
    <View
      style={[
        styles.container,
        isWide && styles.containerDocked,
        { paddingBottom: insets.bottom + SITE_NAV_BOTTOM_PADDING },
      ]}
    >
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
  );
};

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  // A solid colors.bar strip, full width, flush to the bottom edge, three
  // equal-width columns (icon over a one-line label). The bottom padding is
  // OVERRIDDEN AT RENDER with `insets.bottom + SITE_NAV_BOTTOM_PADDING`; the
  // value here is only the fallback when the styles are used without the
  // component.
  container: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    paddingTop: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingBottom: SITE_NAV_BOTTOM_PADDING,
    backgroundColor: colors.bar,
  },
  containerDocked: {
    position: 'relative',
  },
  // minWidth: 0 lets a flex child shrink below its content so the label
  // ellipsizes instead of widening its column. 6 + 18 + 3 + 14 + 5 + the 3pt
  // rule = 49pt tall, over the 44 minimum for a device operated with gloves.
  navItem: {
    flex: 1,
    minWidth: 0,
    alignItems: 'center',
    gap: 3,
    paddingTop: 6,
    paddingBottom: 5,
    borderTopWidth: 3,
    borderTopColor: 'transparent',
    opacity: 0.72,
  },
  navItemActive: {
    opacity: 1,
    borderTopColor: colors.barActive,
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
export default SiteNav;
