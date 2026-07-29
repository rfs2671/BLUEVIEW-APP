import { Platform, useWindowDimensions } from 'react-native';

/**
 * Desktop breakpoint for the RN-Web presentation layer.
 *
 * The app is a mobile single-column stack that also renders on the web via
 * RN-Web. `useIsDesktop()` is the single switch the desktop shell branches on.
 *
 * Why a hook and not a CSS media query: RN-Web does not give us media queries
 * natively — styles are JS objects, not stylesheets we can attach `@media` to.
 * `useWindowDimensions()` subscribes to dimension changes, so a browser resize
 * across the boundary re-renders the tree and the layout switches live.
 *
 * Native is always false: `Platform.OS === 'web'` gates it, so iOS/Android
 * render exactly what they render today regardless of tablet width.
 */
export const DESKTOP_BREAKPOINT = 1024;

export function useIsDesktop() {
  // Called unconditionally — rules of hooks. On native the width is read but
  // the Platform check short-circuits the result to false.
  const { width } = useWindowDimensions();
  return Platform.OS === 'web' && width >= DESKTOP_BREAKPOINT;
}

/**
 * Same breakpoint, WITHOUT the web gate — for content layout rather than the
 * desktop shell.
 *
 * useIsDesktop() answers "should we render the admin chrome", and that is a web
 * question, so it is false on native by design. The jobsite site device is a
 * 10" tablet running the NATIVE app in landscape: 1280x800, no browser. A
 * layout hook gated on Platform.OS === 'web' would report `false` on the exact
 * device the wide layout exists for, so the site screens use this one.
 *
 * Deliberately shares DESKTOP_BREAKPOINT: one number, so a phone in landscape
 * (max ~930pt) never crosses it and a 10" tablet always does.
 */
export function useIsWide() {
  const { width } = useWindowDimensions();
  return width >= DESKTOP_BREAKPOINT;
}

export default useIsDesktop;
