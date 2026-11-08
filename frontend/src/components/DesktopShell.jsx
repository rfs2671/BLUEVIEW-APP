import React, { useRef, useState, useEffect } from 'react';
import { View, Text, Pressable, StyleSheet, Platform } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import Animated, { useSharedValue, useAnimatedStyle, withTiming, Easing, interpolateColor } from 'react-native-reanimated';
import {
  LayoutDashboard,
  FolderKanban,
  Users,
  FileText,
  Settings,
  Shield,
} from 'lucide-react-native';
import { withAlpha } from '../styles/semanticColors';
import { useTheme } from '../context/ThemeContext';
import ThemeSwitch from './ThemeSwitch';
import { useAuth } from '../context/AuthContext';
import { brandLabel } from '../utils/brandLabel';
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
 * navigation model, not two. Active state is a brass tick and the bar's
 * active ink (theme.js `barActive`/`onBar`) — deliberately NOT `semantic.verified`, which means
 * "confirmed clear", not "selected".
 */

const RAIL_ITEMS = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/projects', icon: FolderKanban, label: 'Projects' },
  { path: '/workers', icon: Users, label: 'Workers' },
  { path: '/reports', icon: FileText, label: 'Reports' },
  // Admin points at /admin/users, not /admin — there is no app/admin/index.jsx
  // and this PR deliberately does not create one. /admin/users is the natural
  // landing screen for the admin group.
  { path: '/admin/users', icon: Shield, label: 'Admin' },
];

export const CONTENT_MAX_WIDTH = 1280;
const RAIL_WIDTH = 240;
// The rail rests as a narrow strip of icons. When the cursor reaches it the full
// rail opens OVER the page (the page does not move), and it closes shortly after
// the cursor leaves.
const RAIL_COLLAPSED = 72;
const RAIL_PAD = 12;
const RAIL_CLOSE_DELAY_MS = 80;

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
 *  • OWNER PORTAL (`/owner/*`) — the platform operator's portal has its own
 *    nav (OwnerNav: Companies · Deleted items · Pending deletion, and Back to
 *    app). The company app's rail beside it offered a second, unrelated
 *    navigation.
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
  '/owner',
];

function isBareRoute(pathname) {
  if (!pathname) return false;
  return BARE_ROUTES.some((r) => pathname === r || pathname.startsWith(`${r}/`));
}

// ── Who is signed in ────────────────────────────────────────────────────────
// First letter of the first and last name; the first two letters of a single
// name. Never empty.
export function initialsOf(name) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '–';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

const ROLE_LABEL = {
  admin: 'Admin',
  owner: 'Owner',
  pm: 'Project manager',
  superintendent: 'Superintendent',
  cp: 'Competent person',
};
function roleLabel(role) {
  const r = String(role || '').trim().toLowerCase();
  if (!r) return '';
  return ROLE_LABEL[r] || r.charAt(0).toUpperCase() + r.slice(1);
}

const ID_CLOSED = 48;                                   // the seal
const ID_OPEN_W = RAIL_WIDTH - RAIL_PAD * 2;            // the title block
const ID_OPEN_H = 64;
const ID_NAME_H = 36;

/**
 * The signed-in person, at the top of the rail. At rest it is a round brass-ringed
 * seal with their initials. As the rail opens the seal grows into a drawing-sheet
 * title block (name in the top cell; role and company in the cells below): the
 * ring squares off, the initials fade out and the name fades in on the same
 * piece of surface, so the initials read as turning into the name.
 */
function RailIdentity({ open, name, role, company, colors }) {
  const box = useAnimatedStyle(() => ({
    width: ID_CLOSED + (ID_OPEN_W - ID_CLOSED) * open.value,
    height: ID_CLOSED + (ID_OPEN_H - ID_CLOSED) * open.value,
    borderRadius: 24 - 20 * open.value,
    borderColor: interpolateColor(open.value, [0, 1], ['rgba(227,194,122,0.6)', 'rgba(236,237,233,0.28)']),
    backgroundColor: interpolateColor(open.value, [0, 1], ['rgba(236,237,233,0.10)', 'rgba(236,237,233,0.04)']),
  }), [open]);
  const initialsStyle = useAnimatedStyle(() => ({
    opacity: Math.max(0, 1 - open.value * 2.4),
    transform: [{ scale: 1 - 0.3 * open.value }],
  }), [open]);
  const cellsStyle = useAnimatedStyle(() => ({
    opacity: Math.max(0, (open.value - 0.45) / 0.55),
    transform: [{ translateY: 5 * (1 - open.value) }],
  }), [open]);
  const edgeStyle = useAnimatedStyle(() => ({ opacity: Math.max(0, (open.value - 0.3) / 0.7) }), [open]);

  return (
    <Animated.View style={[styles.idBox, box]} accessible accessibilityLabel={`Signed in as ${name}`}>
      <Animated.View style={[styles.idEdge, { backgroundColor: colors.barActive }, edgeStyle]} />
      <Animated.View style={[styles.idInitials, initialsStyle]} pointerEvents="none">
        <Text style={[styles.idInitialsText, { color: colors.onBar }]}>{initialsOf(name)}</Text>
      </Animated.View>
      <Animated.View style={[styles.idCells, cellsStyle]} pointerEvents="none">
        <View style={[styles.idNameCell, { borderBottomColor: withAlpha(colors.onBar, 0.2) }]}>
          <Text style={[styles.idName, { color: colors.onBar }]} numberOfLines={1}>{name}</Text>
        </View>
        <View style={styles.idSubRow}>
          {role ? (
            <Text style={[styles.idSub, { color: withAlpha(colors.onBar, 0.62) }]} numberOfLines={1}>{role}</Text>
          ) : null}
          {role && company ? <View style={[styles.idDivider, { backgroundColor: withAlpha(colors.onBar, 0.2) }]} /> : null}
          {company ? (
            <Text style={[styles.idSub, styles.idSubCompany, { color: withAlpha(colors.onBar, 0.62) }]} numberOfLines={1}>{company}</Text>
          ) : null}
        </View>
      </Animated.View>
    </Animated.View>
  );
}

export default function DesktopShell({ children }) {
  const router = useRouter();
  const pathname = usePathname();
  const { colors, isDark } = useTheme();
  const { user } = useAuth();
  const open = useSharedValue(0);
  const [isOpen, setIsOpen] = useState(false);
  const closeTimer = useRef(null);

  useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current); }, []);

  // Is the rail open? A ref, because the mouse handler below runs on every move.
  const expandedRef = useRef(false);
  const bareRef = useRef(false);

  const openRail = () => {
    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
    if (expandedRef.current) return;
    expandedRef.current = true;
    setIsOpen(true);
    open.value = withTiming(1, { duration: 200, easing: Easing.out(Easing.cubic) });
  };
  const closeRail = () => {
    if (!expandedRef.current || closeTimer.current) return;
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null;
      expandedRef.current = false;
      setIsOpen(false);
      open.value = withTiming(0, { duration: 150, easing: Easing.out(Easing.quad) });
    }, RAIL_CLOSE_DELAY_MS);
  };

  // WHERE THE CURSOR IS, NOT WHAT IT IS OVER. The rail opens when the cursor is in
  // its strip and stays open while the cursor is within its opened width, judged
  // by the cursor's x position on the screen. Asking the browser which element is
  // under the cursor (mouseenter/leave, hover events) breaks whenever something on
  // the page sits above the opened rail: the cursor then "leaves" the rail while
  // still visibly inside it, the rail closes, reopens, and flickers.
  useEffect(() => {
    if (Platform.OS !== 'web' || typeof document === 'undefined') return undefined;
    const onMove = (e) => {
      if (bareRef.current) return;
      const edge = expandedRef.current ? RAIL_WIDTH + 2 : RAIL_COLLAPSED;
      if (e.clientX <= edge) openRail(); else closeRail();
    };
    const onLeaveWindow = (e) => { if (!e.relatedTarget) closeRail(); };
    document.addEventListener('mousemove', onMove, { passive: true });
    document.addEventListener('mouseout', onLeaveWindow);
    return () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseout', onLeaveWindow);
    };
    // openRail / closeRail only touch refs and a shared value
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const railStyle = useAnimatedStyle(() => ({
    width: RAIL_COLLAPSED + (RAIL_WIDTH - RAIL_COLLAPSED) * open.value,
    shadowOpacity: 0.28 * open.value,
  }), [open]);
  const footStyle = useAnimatedStyle(() => ({
    opacity: Math.max(0, (open.value - 0.5) / 0.5),
  }), [open]);
  const labelStyle = useAnimatedStyle(() => ({
    opacity: Math.max(0, (open.value - 0.35) / 0.65),
  }), [open]);

  bareRef.current = isBareRoute(pathname);
  if (bareRef.current) return children;

  // The rail is its own plane, anchored apart from the page: the bar navy of the phone's bottom bar in both themes
  // (theme.js `bar`), with the active destination marked by a brass tick. Its text is the bar's own ink.
  const personName = (user && (user.full_name || user.name || user.display_name))
    || (user && user.email ? String(user.email).split('@')[0] : '') || 'Account';
  const personRole = roleLabel(user && user.role);
  const personCompany = user && (user.gc_business_name || user.company_name) ? brandLabel(user) : '';
  const railIdle = withAlpha(colors.onBar, 0.78);
  const railActive = isDark ? colors.barActive : colors.onBar;

  return (
    <View style={styles.root}>
      {/* A fixed-width slot keeps the page where it is; the rail itself grows over it. */}
      <View style={styles.railSlot}>
      <Animated.View style={[styles.rail, { backgroundColor: colors.bar }, railStyle]}>
        <View style={styles.idWrap}>
          <RailIdentity open={open} name={personName} role={personRole} company={personCompany} colors={colors} />
        </View>
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
              onFocus={openRail}
              onBlur={closeRail}
              accessibilityRole="link"
              accessibilityLabel={item.label}
              style={({ hovered, pressed, focused }) => [
                styles.railItem,
                active && { backgroundColor: withAlpha(colors.onBar, 0.10) },
                !active && hovered && { backgroundColor: withAlpha(colors.onBar, 0.06) },
                // The browser's own focus ring is a separate box that stays after a
                // click and lags behind the rail as it widens. Keyboard focus is shown
                // as a highlight on the item itself instead.
                focused && { backgroundColor: withAlpha(colors.onBar, 0.14) },
                pressed && { opacity: 0.8 },
              ]}
            >
              {active ? <View style={[styles.railTick, { backgroundColor: colors.barActive }]} /> : null}
              {/* flexShrink 0: in the narrow resting rail the label's fixed width
                  would otherwise squeeze the icon down to nothing. */}
              <View style={styles.railIcon}>
                <Icon
                  size={20}
                  strokeWidth={1.5}
                  color={active ? railActive : railIdle}
                />
              </View>
              <Animated.View style={[styles.railLabelWrap, labelStyle]} pointerEvents="none">
                <Text
                  style={[
                    styles.railLabel,
                    { color: active ? railActive : railIdle },
                    active && styles.railLabelActive,
                  ]}
                  numberOfLines={1}
                >
                  {item.label}
                </Text>
              </Animated.View>
            </Pressable>
          );
        })}

        {/* Bottom of the rail. The switch and Settings only exist while the rail is
            open: they fade in with the labels and cannot be hit while it rests. */}
        <Animated.View
          style={[styles.railFoot, { borderTopColor: withAlpha(colors.onBar, 0.14) }, footStyle]}
          pointerEvents={isOpen ? 'auto' : 'none'}
          accessibilityElementsHidden={!isOpen}
          importantForAccessibility={isOpen ? 'auto' : 'no-hide-descendants'}
        >
          <View style={styles.footRow}>
            <View style={styles.switchSlot}><ThemeSwitch /></View>
            <Text style={[styles.footLabel, { color: railIdle }]} numberOfLines={1}>{isDark ? 'Dark mode' : 'Light mode'}</Text>
          </View>
          <Pressable
            onPress={() => router.push('/settings')}
            onFocus={openRail}
            onBlur={closeRail}
            accessibilityRole="link"
            accessibilityLabel="Settings"
            style={({ hovered, pressed, focused }) => [
              styles.railItem,
              pathname === '/settings' && { backgroundColor: withAlpha(colors.onBar, 0.10) },
              pathname !== '/settings' && hovered && { backgroundColor: withAlpha(colors.onBar, 0.06) },
              focused && { backgroundColor: withAlpha(colors.onBar, 0.14) },
              pressed && { opacity: 0.8 },
            ]}
          >
            <View style={styles.railIcon}>
              <Settings size={20} strokeWidth={1.5} color={pathname === '/settings' ? railActive : railIdle} />
            </View>
            <Text style={[styles.railLabel, { color: pathname === '/settings' ? railActive : railIdle }]} numberOfLines={1}>Settings</Text>
          </Pressable>
        </Animated.View>
      </Animated.View>
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
  // Holds the collapsed width in the layout so the page never shifts.
  railSlot: {
    width: RAIL_COLLAPSED,
    flexShrink: 0,
    // Above anything a page lays over its left edge.
    zIndex: 1000,
  },
  // ONE AXIS. At rest the rail is 72 wide with 12 of padding, leaving 48 for every
  // control; each is 48 wide with its icon dead centre, so icons, the switch and
  // the settings gear all sit on the same vertical line (x = 36). Opening the
  // rail only adds room on the right, so nothing moves sideways as it opens.
  rail: {
    position: 'absolute',
    left: 0,
    top: 0,
    bottom: 0,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 6, height: 0 },
    shadowRadius: 18,
    paddingTop: spacing.lg,
    paddingHorizontal: RAIL_PAD,
    gap: 4,
  },
  railItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    height: 44,
    paddingHorizontal: 14,
    borderRadius: 12,
    ...(Platform.OS === 'web' ? { outlineStyle: 'none' } : null),
  },
  // The active destination's tick: a short brass bar flush with the rail's left
  // edge (the item sits RAIL_PAD in from it).
  railTick: { position: 'absolute', left: -RAIL_PAD, top: 12, bottom: 12, width: 3, borderTopRightRadius: 2, borderBottomRightRadius: 2 },
  // Footer: the switch and settings, set apart from the destinations by a hairline.
  idWrap: { marginBottom: 14, minHeight: ID_OPEN_H },
  idBox: { overflow: 'hidden', borderWidth: 1 },
  idEdge: { position: 'absolute', top: 0, left: 0, right: 0, height: 3 },
  idInitials: { position: 'absolute', top: 0, left: 0, width: ID_CLOSED - 2, height: ID_CLOSED - 2, alignItems: 'center', justifyContent: 'center' },
  idInitialsText: { fontSize: 15, fontWeight: '600', letterSpacing: 0.6 },
  idCells: { position: 'absolute', top: 0, left: 0, width: ID_OPEN_W - 2 },
  idNameCell: { height: ID_NAME_H, paddingHorizontal: 12, justifyContent: 'center', borderBottomWidth: StyleSheet.hairlineWidth },
  idName: { fontSize: 14.5, fontWeight: '600', letterSpacing: -0.1 },
  idSubRow: { flexDirection: 'row', alignItems: 'center', height: ID_OPEN_H - ID_NAME_H - 2, paddingHorizontal: 12, gap: 10 },
  idSub: { fontSize: 11.5, flexShrink: 0 },
  idSubCompany: { flexShrink: 1 },
  idDivider: { width: 1, height: 12 },
  railFoot: {
    marginTop: 'auto',
    marginBottom: spacing.lg,
    paddingTop: 14,
    gap: 6,
    alignItems: 'stretch',
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  footRow: { flexDirection: 'row', alignItems: 'center', gap: 12, height: 40 },
  footLabel: { fontSize: typography.sizes.sm, fontWeight: '500', flexShrink: 1 },
  footIcon: {
    width: 48,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    ...(Platform.OS === 'web' ? { outlineStyle: 'none' } : null),
  },
  switchSlot: {
    width: 48,
    height: 30,
    alignItems: 'center',
    justifyContent: 'center',
  },
  railIcon: {
    width: 20,
    height: 20,
    flexShrink: 0,
  },
  railLabelWrap: {
    flexShrink: 0,
    width: RAIL_WIDTH - RAIL_PAD * 2 - 14 * 2 - 20 - spacing.sm,
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
