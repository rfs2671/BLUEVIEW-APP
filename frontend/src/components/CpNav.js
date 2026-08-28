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

// ─── The pill's geometry, and the clearance every CP screen owes it ─────────
//
// DERIVED, NOT MEASURED-AND-WRITTEN-DOWN. Every term below is the same token
// the styles at the bottom of this file are built from, so changing
// `spacing.sm` moves the pill and the clearance together. A number copied off
// a screenshot would not.
//
// WHAT THE SCREENS DID BEFORE. /logbooks and /documents hardcoded
// `paddingBottom: 120`, /settings `140`. None of the three was a measurement
// against this nav: 120 is the app's house-wide bottom scroll padding (it
// appears on ~34 screens, most of which have no nav at all), and settings was
// 110 until an unrelated react-native-web scroll fix bumped it to 140. So the
// clearance was a coincidence that happened to be roughly right on gesture
// navigation and WRONG on 3-button, where the inset is ~48 rather than ~24
// and the pill covered the last row of every list.
//
// `numberOfLines={1}` ON navLabel IS WHAT KEEPS THIS TRUE. The height below
// assumes each item is ONE line tall. This nav is `width: '100%'` with
// `navItem: flex: 1`, so items share the width and a squeezed label wraps —
// two lines, a taller item, a taller pill, and this constant silently
// understating the clearance on exactly the narrow phones where it is
// tightest. Removing that prop without changing this number is the visible
// error; they are one mechanism in two places.
//   Measured, three items, 320pt wide: with the prop 58, without it 70.

const NAV_ICON_SIZE = 18;

// How far the pill floats above the safe-area inset. Applied inline at render
// (see `container`), because a StyleSheet is built before any inset exists.
export const CP_NAV_BOTTOM_OFFSET = 24;

// blurContent's padding, top and bottom  +  navItem's padding, top and bottom
//   + the tallest thing in the row, which is the icon, not the 11pt label.
export const CP_NAV_PILL_HEIGHT =
  spacing.sm * 2 + (spacing.sm + 4) * 2 + NAV_ICON_SIZE;

// The gap left between the top of the pill and the last row of content. Not
// styling slack: this is a gloved thumb outdoors reaching for the last item in
// a list, and a row that is merely visible behind the pill is not tappable.
const CP_NAV_BREATHING_ROOM = spacing.lg;

/**
 * What a screen carrying CpNav must leave at the bottom of its scroll content.
 *
 * Spread it as `{ paddingBottom: insets.bottom + CP_NAV_CLEARANCE }` — the
 * inset is added by the SCREEN, not baked in here, because this module cannot
 * see it and the value differs between gesture and 3-button navigation.
 */
export const CP_NAV_CLEARANCE =
  CP_NAV_BOTTOM_OFFSET + CP_NAV_PILL_HEIGHT + CP_NAV_BREATHING_ROOM;


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
      <Icon size={NAV_ICON_SIZE} strokeWidth={1.5} color={isActive ? c.text.primary : c.text.muted} />
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
    <View style={[styles.container, { bottom: insets.bottom + CP_NAV_BOTTOM_OFFSET }]}>
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
    // { bottom: insets.bottom + CP_NAV_BOTTOM_OFFSET } inline, which REPLACES
    // this value — it does not add to it. The one below is therefore a
    // fallback that only applies if these styles are used without the
    // component.
    //
    // It has to be done inline: a StyleSheet is built once at module load,
    // before any inset exists. And it has to be done at all because absolute
    // positioning puts this outside the inset flow — neither the screen's
    // SafeAreaView nor its scroll padding reaches it, so a hardcoded offset
    // leaves the nav under the buttons on 3-button navigation. The screens
    // add the same inset to their own clearance; see CP_NAV_CLEARANCE.
    position: 'absolute',
    bottom: CP_NAV_BOTTOM_OFFSET, left: 0, right: 0,
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
