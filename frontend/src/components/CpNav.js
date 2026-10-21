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
import { View, StyleSheet, Pressable, Text } from 'react-native';
import { useRouter, usePathname } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { LayoutDashboard, QrCode, Settings } from 'lucide-react-native';
import { spacing } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
import CheckinQrModal from './CheckinQrModal';

// ─── The bar's geometry, and the clearance every CP screen owes it ──────────
//
// DERIVED, NOT MEASURED-AND-WRITTEN-DOWN. Every term below is the same token
// the styles at the bottom of this file are built from, so changing
// `spacing.sm` moves the bar and the clearance together. A number copied off
// a screenshot would not.
//
// WHAT THE SCREENS DID BEFORE. /logbooks and /documents hardcoded
// `paddingBottom: 120`, /settings `140`. None of the three was a measurement
// against this nav: 120 is the app's house-wide bottom scroll padding (it
// appears on ~34 screens, most of which have no nav at all), and settings was
// 110 until an unrelated react-native-web scroll fix bumped it to 140. So the
// clearance was a coincidence that happened to be roughly right on gesture
// navigation and WRONG on 3-button, where the inset is ~48 rather than ~24
// and the nav covered the last row of every list.
//
// `numberOfLines={1}` ON navLabel IS WHAT KEEPS THIS TRUE. The height below
// assumes each item is ONE label line tall. This nav's items are equal-width
// `flex: 1` columns, so a squeezed label wraps: two lines, a taller item, a
// taller bar, and this constant silently understating the clearance on
// exactly the narrow phones where it is tightest. Removing that prop without
// changing this number is the visible error; they are one mechanism in two
// places. (`lineHeight` is explicit for the same reason: the label's height
// is a token here, not whatever the platform's default line box happens to be.)

const NAV_ICON_SIZE = 18;

// One tab, top to bottom: the 3pt rule that lights up on the active tab, the
// padding under it, the icon, the gap, ONE label line, the padding under that.
const NAV_ITEM_RULE = 3;
const NAV_ITEM_PAD_TOP = 6;
const NAV_ITEM_GAP = 3;
const NAV_LABEL_LINE_HEIGHT = 14;
const NAV_ITEM_PAD_BOTTOM = 5;
const NAV_ITEM_HEIGHT =
  NAV_ITEM_RULE + NAV_ITEM_PAD_TOP + NAV_ICON_SIZE + NAV_ITEM_GAP
  + NAV_LABEL_LINE_HEIGHT + NAV_ITEM_PAD_BOTTOM;

// The bar's constant bottom padding, UNDER the labels and ABOVE the system
// navigation bar. Applied inline at render as
// `insets.bottom + CP_NAV_BOTTOM_OFFSET` (see `container`), because a
// StyleSheet is built before any inset exists. It equals the bar's top
// padding (`spacing.sm`), which is why the height below counts `spacing.sm`
// twice; CpNav.clearance.test.cjs pins the two together.
export const CP_NAV_BOTTOM_OFFSET = spacing.sm;

// The bar's height WITHOUT the safe-area inset: its top and bottom padding
// (spacing.sm each) plus one item. The item is the icon AND the label line
// stacked, so unlike the old pill the label counts toward the height.
export const CP_NAV_PILL_HEIGHT =
  spacing.sm * 2 + NAV_ITEM_HEIGHT;

// The gap left between the top of the bar and the last row of content. Not
// styling slack: this is a gloved thumb outdoors reaching for the last item in
// a list, and a row that is merely visible behind the bar is not tappable.
const CP_NAV_BREATHING_ROOM = spacing.lg;

/**
 * What a screen carrying CpNav must leave at the bottom of its scroll content.
 *
 * Spread it as `{ paddingBottom: insets.bottom + CP_NAV_CLEARANCE }` — the
 * inset is added by the SCREEN, not baked in here, because this module cannot
 * see it and the value differs between gesture and 3-button navigation. The
 * bar is flush to the bottom edge and grows upward by that same inset, so the
 * clearance is the bar's own height plus breathing room.
 */
export const CP_NAV_CLEARANCE =
  CP_NAV_PILL_HEIGHT + CP_NAV_BREATHING_ROOM;


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

// ── WHY THERE IS NO SUPERINTENDENT SLOT ─────────────────────────────────────
//
// One was built here and REMOVED. It replaced Check-In whenever the signed-in
// principal was the registered construction superintendent.
//
// It was the wrong trade. The QR is reached at a gate with a worker standing in
// front of him; Settings is where he signs out. Both earn a slot on a bar with
// three. A once-a-day log he reaches from a list does not — it already appears
// among the other logbooks, which is where a man looks for a log.
//
// THE LOG IS NOT LESS REACHABLE FOR THIS. It is required per project once
// `superintendent_log_active` is on, so it renders in the CP's logbook list and
// routes by log type to app/logbooks/site_superintendent_log.jsx. That path is
// executed by requiredLogbooksWiring.test.cjs, toggle on and toggle off.
//
// AND A FOURTH ITEM IS NOT THE ALTERNATIVE. CP_NAV_PILL_HEIGHT cannot move —
// it carries no item-count term — so four was structurally safe and NOT
// legible: items share the width equally, and at 320pt "Dashboard" already has
// ONE POINT of headroom at three. numberOfLines turns that into an ellipsis
// rather than a wrap, which protects this constant and not the reading.

const NavItem = ({ item, isActive, onPress, colors: c }) => {
  const [isHovered, setIsHovered] = useState(false);
  const Icon = item.icon;
  return (
    <Pressable
      onPress={onPress}
      onHoverIn={() => setIsHovered(true)}
      onHoverOut={() => setIsHovered(false)}
      style={[
        styles.navItem,
        isActive && { opacity: 1, borderTopColor: c.barActive },
        isHovered && !isActive && styles.navItemHover,
      ]}
    >
      <Icon size={NAV_ICON_SIZE} strokeWidth={1.8} color={c.onBar} />
      {/* numberOfLines IS LOAD-BEARING. See the note on navLabel. */}
      <Text
        numberOfLines={1}
        style={[styles.navLabel, { color: c.onBar }]}
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
  const { colors: c } = useTheme();
  const [showCheckinQr, setShowCheckinQr] = useState(false);

  return (
    <>
      <View
        style={[
          styles.container,
          { backgroundColor: c.bar, paddingBottom: insets.bottom + CP_NAV_BOTTOM_OFFSET },
        ]}
      >
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

      {/* No `project` prop. The nav is on screens that have no project context
          at all (settings) and on one whose project list is filtered to
          Dropbox-enabled projects only (documents), so nothing here can supply
          one honestly. The modal resolves its own from the cached list. */}
      <CheckinQrModal
        visible={showCheckinQr}
        onClose={() => setShowCheckinQr(false)}
      />
    </>
  );
};

const styles = StyleSheet.create({
  container: {
    // OVERRIDDEN AT RENDER. The component passes
    // { paddingBottom: insets.bottom + CP_NAV_BOTTOM_OFFSET } inline, which
    // REPLACES the fallback below — it does not add to it. The fallback only
    // applies if these styles are used without the component. The background
    // is inline too, from the theme's `bar` token, so it follows light/dark.
    //
    // It has to be done inline: a StyleSheet is built once at module load,
    // before any inset exists. And it has to be done at all because absolute
    // positioning puts this outside the inset flow — neither the screen's
    // SafeAreaView nor its scroll padding reaches it, so a hardcoded padding
    // leaves the labels under the buttons on 3-button navigation. The bar is
    // flush to the bottom edge (bottom: 0) and grows upward by the inset, so
    // its fill runs under the system bar. The screens add the same inset to
    // their own clearance; see CP_NAV_CLEARANCE.
    position: 'absolute',
    bottom: 0, left: 0, right: 0,
    flexDirection: 'row',
    paddingTop: spacing.sm,
    paddingHorizontal: spacing.sm,
    paddingBottom: CP_NAV_BOTTOM_OFFSET,
  },
  // Equal-width columns, icon stacked over the label. minWidth: 0 lets a flex
  // child shrink below its content so the label ellipsizes rather than
  // widening its column. Inactive at 72%; the active tab is full opacity with
  // a brass top rule (colour applied inline from the theme).
  navItem: {
    flex: 1, minWidth: 0, alignItems: 'center',
    gap: NAV_ITEM_GAP,
    paddingTop: NAV_ITEM_PAD_TOP, paddingBottom: NAV_ITEM_PAD_BOTTOM,
    borderTopWidth: NAV_ITEM_RULE, borderTopColor: 'transparent',
    opacity: 0.72,
  },
  navItemHover: { opacity: 1 },

  // THE BAR'S HEIGHT IS DECOUPLED FROM ITEM COUNT ON PURPOSE, and
  // `numberOfLines={1}` on this Text is the whole mechanism. Do not remove it
  // as noise, and do not "fix" a cramped label by shortening the word instead.
  //
  // WHY IT MATTERS. Three CP screens clear this nav with
  // `insets.bottom + CP_NAV_CLEARANCE`, which is derived from the bar's height
  // as it is. If the bar grows, it eats that clearance and starts covering the
  // last row of content — the class of defect this nav has already produced
  // once, when absolute positioning put it under the system buttons on
  // 3-button navigation.
  //
  // WHY IT GROWS. This nav's items are `flex: 1` columns, so they SHARE the
  // width equally. Add an item and every label gets less room. Without
  // numberOfLines a squeezed label wraps to two lines, the item gets taller,
  // and the bar grows with it.
  //
  // MEASURED, on the earlier floating-pill layout (the pill heights below are
  // that layout's, kept as the record of the wrap mechanism; the bar's own
  // derived height is CP_NAV_PILL_HEIGHT), at the third item:
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
  // stops depending on item count, label length and font scale together; the
  // explicit lineHeight fixes the one line to a token. That
  // is what makes a FOURTH item safe to add later without moving every screen's
  // clearance. Keep it.
  //
  // THE FOURTH ITEM ARRIVED (the superintendent log, label "Super"), and the
  // measurements above were NOT re-taken on a device for it — the bar height
  // is asserted to be unchanged by derivation instead, in
  // CpNav.clearance.test.cjs, which is sound because the derivation provably
  // contains no item-count or label-width term. What is NOT covered by that
  // argument is legibility: at 320pt and four items "Dashboard" and "Settings"
  // now ellipsize. That was accepted deliberately. If a FIFTH item is ever
  // added, re-measure rather than extending the same reasoning again — four
  // ~72pt columns is where icon + any label stops being readable at all, and
  // the failure then is not the pill growing, it is every label reading "Da…".
  navLabel: { fontSize: 11, lineHeight: NAV_LABEL_LINE_HEIGHT, fontWeight: '600' },
});

export default CpNav;
