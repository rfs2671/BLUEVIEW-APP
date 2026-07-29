import React from 'react';
import { View, Text, Pressable, StyleSheet } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import {
  LayoutDashboard,
  FolderKanban,
  Users,
  FileText,
  Settings,
  Shield,
} from 'lucide-react-native';
import { chrome, border, surface, text } from '../styles/semanticColors';
import { spacing, borderRadius, typography } from '../styles/theme';

/**
 * DesktopShell — the RN-Web desktop presentation layer.
 *
 * Rendered only when useIsDesktop() is true (web AND width >= 1024). Provides
 * a persistent left rail plus a centered, max-width content column; the
 * current screen renders inside it untouched as `children`.
 *
 * Scope note: this PR adds the shell only. The screens inside it are still
 * mobile single-column stacks and will look narrow in a 1280 container —
 * that is expected and is fixed in the follow-up PRs (projects table,
 * dashboard rollup, project detail, quick actions).
 *
 * Rail destinations mirror the mobile tab bar exactly (see
 * components/FloatingNav.js `navItems` + its Settings button), so there is one
 * navigation model, not two. Active state uses `chrome.brand` (primary blue)
 * per the color taxonomy — deliberately NOT `semantic.verified`, which means
 * "confirmed clear", not "selected".
 */

const RAIL_ITEMS = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/projects', icon: FolderKanban, label: 'Projects' },
  { path: '/workers', icon: Users, label: 'Workers' },
  { path: '/reports', icon: FileText, label: 'Reports' },
  { path: '/settings', icon: Settings, label: 'Settings' },
  // Admin points at /admin/users, not /admin — there is no app/admin/index.jsx
  // and this PR deliberately does not create one. /admin/users is the natural
  // landing screen for the admin group.
  { path: '/admin/users', icon: Shield, label: 'Admin' },
];

export const CONTENT_MAX_WIDTH = 1280;
const RAIL_WIDTH = 240;

/**
 * Routes that must render WITHOUT the shell even on desktop.
 *
 * Three groups:
 *  • Pre-auth / onboarding — a nav rail on the login screen would offer
 *    destinations the visitor cannot reach.
 *  • Worker field-capture flows (`/nfc`, `/checkin/*`) — desktop is
 *    admin/oversight only; these are phone/tablet flows reached by tapping an
 *    NFC tag or a deep link, so wrapping them in an admin rail misrepresents
 *    them. They stay reachable by URL (this does not block or redirect — that
 *    would be a RouteGuard change, deliberately out of scope); they simply
 *    render standalone. Read-only equivalents for admins already exist:
 *    site/checkins (check-in log) and the ON SITE tile on project/[id].
 *  • SITE MODE (`/site/*`) — the jobsite tablet. It is 1280x800, so it clears
 *    DESKTOP_BREAKPOINT and was getting the full admin rail: 240px of
 *    Dashboard / Projects / Workers / Reports / Settings / Admin on a device
 *    whose primary user is a DOB inspector. Every one of those destinations
 *    bounced straight back to /site — the RouteGuard in app/_layout.jsx
 *    confines a site device to `/site/*` and `/login` — so the rail was six
 *    dead ends occupying a fifth of the screen. Site mode has its own
 *    navigation (SiteNav); it must not inherit the admin one.
 *
 * Prefix-matched, so '/checkin' also covers '/checkin/{project_id}/{tag_id}'
 * and '/site' covers '/site/documents'.
 */
const BARE_ROUTES = [
  '/login',
  '/register',
  '/demo',
  '/onboarding',
  '/nfc',
  '/checkin',
  '/site',
];

function isBareRoute(pathname) {
  if (!pathname) return false;
  return BARE_ROUTES.some((r) => pathname === r || pathname.startsWith(`${r}/`));
}

export default function DesktopShell({ children }) {
  const router = useRouter();
  const pathname = usePathname();

  if (isBareRoute(pathname)) return children;

  return (
    <View style={styles.root}>
      <View
        style={[
          styles.rail,
          { borderRightColor: border.subtle, backgroundColor: surface.glass },
        ]}
      >
        {RAIL_ITEMS.map((item) => {
          // Exact-match active state, mirroring FloatingNav so the rail and
          // the tab bar agree. Detail routes (e.g. /projects/123) highlight
          // nothing, same as mobile today.
          const active = pathname === item.path;
          const Icon = item.icon;
          return (
            <Pressable
              key={item.path}
              onPress={() => router.push(item.path)}
              accessibilityRole="link"
              accessibilityLabel={item.label}
              style={({ hovered, pressed }) => [
                styles.railItem,
                active && { backgroundColor: surface.glassHover },
                !active && hovered && { backgroundColor: surface.card },
                pressed && { opacity: 0.8 },
              ]}
            >
              <Icon
                size={20}
                strokeWidth={1.5}
                color={active ? chrome.brand : text.muted}
              />
              <Text
                style={[
                  styles.railLabel,
                  { color: active ? chrome.brand : text.secondary },
                  active && styles.railLabelActive,
                ]}
                numberOfLines={1}
              >
                {item.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      <View style={styles.contentOuter}>
        <View style={styles.contentInner}>{children}</View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    flexDirection: 'row',
  },
  rail: {
    width: RAIL_WIDTH,
    flexShrink: 0,
    borderRightWidth: 1,
    paddingTop: spacing.lg,
    paddingHorizontal: spacing.sm,
    gap: spacing.xs,
  },
  railItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.md,
  },
  railLabel: {
    fontSize: typography.sizes.sm,
    fontWeight: '500',
  },
  railLabelActive: {
    fontWeight: '600',
  },
  // Centering wrapper: fills the space beside the rail, centers the column.
  contentOuter: {
    flex: 1,
    alignItems: 'center',
  },
  // The constrained column the screen renders into.
  contentInner: {
    flex: 1,
    width: '100%',
    maxWidth: CONTENT_MAX_WIDTH,
  },
});
