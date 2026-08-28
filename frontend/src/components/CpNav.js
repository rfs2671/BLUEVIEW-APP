/**
 * CpNav.js
 * Place at: frontend/src/components/CpNav.js
 *
 * The nav on every CP screen: Dashboard, Check-In, Settings.
 *
 * "Log Books" (/logbooks/books) was removed because /logbooks IS the
 * dashboard, and having both point at the same content was confusing. The
 * header used to claim the result was "Dashboard, Documents, Settings" — it
 * was not; Documents was dropped from the array and only its now-deleted
 * FolderOpen import survived to suggest otherwise. Corrected here rather than
 * left to mislead the next reader of a three-line file.
 */

import React, { useState } from 'react';
import { View, StyleSheet, Pressable, Text, Platform } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BlurView } from 'expo-blur';
import { LayoutDashboard, QrCode, Settings } from 'lucide-react-native';
import { colors, borderRadius, spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
import { withAlpha } from '../styles/semanticColors';
import CheckinQrModal from './CheckinQrModal';

// CHECK-IN IS NOT A ROUTE. It opens a modal in place, because the CP reaches
// for it standing at a gate with a worker beside him — navigating away from
// whatever he was doing, and back again afterwards, is the wrong shape for a
// tool he uses for fifteen seconds. `path` is still the identity used for the
// active-state comparison below, so it is a sentinel that matches no pathname.
const CHECKIN_QR_ACTION = '#checkin-qr';

const CP_NAV_ITEMS = [
  { path: '/logbooks',        icon: LayoutDashboard, label: 'Dashboard' },
  // "Check-In", not "Check-In QR". The QR is how it happens to work today;
  // what the CP is reaching for is a way to check a man in. See the label
  // note on navLabel about why the length is not what keeps this safe.
  { path: CHECKIN_QR_ACTION,  icon: QrCode,          label: 'Check-In'  },
  { path: '/settings',        icon: Settings,        label: 'Settings'  },
];

const NavItem = ({ item, isActive, onPress, colors: c }) => {
  const Icon = item.icon;
  return (
    <Pressable
      onPress={onPress}
      style={[styles.navItem, isActive && styles.navItemActive]}
    >
      <Icon size={18} strokeWidth={1.5} color={isActive ? c.text.primary : c.text.muted} />
      {/* numberOfLines IS LOAD-BEARING. See the note on navLabel. */}
      <Text
        numberOfLines={1}
        style={[styles.navLabel, { color: isActive ? c.text.primary : c.text.muted }]}
      >
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
  const [showCheckinQr, setShowCheckinQr] = useState(false);

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
              onPress={() => (
                item.path === CHECKIN_QR_ACTION
                  ? setShowCheckinQr(true)
                  : router.push(item.path)
              )}
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

      {/* No `project` prop. The nav is on screens that have no project context
          at all (settings) and on one whose project list is filtered to
          Dropbox-enabled projects only (documents), so nothing here can supply
          one honestly. The modal resolves its own from the cached list. */}
      <CheckinQrModal
        visible={showCheckinQr}
        onClose={() => setShowCheckinQr(false)}
      />
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

  // THE PILL'S HEIGHT IS DECOUPLED FROM ITEM COUNT ON PURPOSE, and
  // `numberOfLines={1}` on this Text is the whole mechanism. Do not remove it
  // as noise, and do not "fix" a cramped label by shortening the word instead.
  //
  // WHY IT MATTERS. Three CP screens clear this nav with a hardcoded
  // paddingBottom (120 on /logbooks and /documents, 140 on /settings). Those
  // numbers were sized by hand against the pill as it was. If the pill grows,
  // it eats that clearance and starts covering the last row of content — the
  // class of defect this nav has already produced once, when absolute
  // positioning put it under the system buttons on 3-button navigation.
  //
  // WHY IT GROWS. Unlike FloatingNav — which sizes its pill to content and
  // scrolls the row horizontally — this nav is `width: '100%'` with
  // `navItem: flex: 1`, so items SHARE the width equally. Add an item and every
  // label gets less room. Without numberOfLines a squeezed label wraps to two
  // lines, the item gets taller, and the pill grows with it.
  //
  // MEASURED, on this component, at the third item:
  //
  //   375pt wide, label "Check-In QR"          pill 58   (12pt headroom)
  //   320pt wide, label "Check-In QR"          pill 70   <- wrapped
  //   320pt wide, label "Check-In"             pill 58   (12pt headroom)
  //   320pt wide, "Check-In QR" + this prop    pill 58   (ellipsis)
  //
  // The shorter label is NOT what makes it safe. At 320pt with three items,
  // "Dashboard" — an item that was already here — has ONE POINT of headroom,
  // so the nav is a single accessibility font step from growing no matter what
  // the new item is called. allowFontScaling is on by default on native, and
  // at 1.3x every label is ~1.3x wider.
  //
  // With numberOfLines the label ellipsizes instead of wrapping, and the height
  // stops depending on item count, label length and font scale together. That
  // is what makes a FOURTH item safe to add later without moving every screen's
  // clearance. Keep it.
  navLabel: { fontSize: 11, fontWeight: '500' },
  border: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: borderRadius.full, borderWidth: 1, pointerEvents: 'none',
  },
});

export default CpNav;
