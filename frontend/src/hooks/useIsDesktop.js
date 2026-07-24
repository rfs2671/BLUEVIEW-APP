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

export default useIsDesktop;
