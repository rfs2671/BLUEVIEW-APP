import React, { createContext, useContext, useState, useEffect, useMemo, useRef } from 'react';
import { Dimensions, StyleSheet } from 'react-native';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
    runOnJS,
  Easing,
} from 'react-native-reanimated';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { applyTheme, getActiveMode, colors as themeColors } from '../styles/theme';
import { effectiveIsDark } from '../utils/themeMode';

const THEME_KEY = 'blueview_theme';
const ThemeContext = createContext(null);

export const ThemeProvider = ({ children }) => {
  // THE PERSON'S OWN CHOICE, and the mode a screen is actually drawn in. They are two things because a site device
  // account is held to the light theme on every page (see `forceTheme` below): its tablet is wall-mounted or handed
  // to an inspector, and the person using it never chose a theme. Their stored choice is left alone, so the same
  // browser or phone goes back to it the moment a normal account signs in.
  const [userIsDark, setUserIsDark] = useState(true);
  const [forced, setForced]         = useState(null);   // null | 'light' | 'dark'
  const isDark = effectiveIsDark(userIsDark, forced);
  // The palette `colors` currently holds (it starts dark) and how many times it has changed. The palette is switched
  // DURING RENDER, before any child reads it, so a frame can never be drawn with isDark and `colors` disagreeing;
  // the guard makes it idempotent, so a repeated render (StrictMode) does nothing the second time.
  const appliedRef = useRef(getActiveMode());
  const keyRef = useRef(0);
  const mode = isDark ? 'dark' : 'light';
  if (appliedRef.current !== mode) {
    appliedRef.current = mode;
    applyTheme(mode);
    keyRef.current += 1;
  }
  const themeKey = keyRef.current;

  useEffect(() => {
    AsyncStorage.getItem(THEME_KEY)
      .then(val => {
        if (val !== null) setUserIsDark(val === 'dark');
      })
      .catch(() => {});
    // A site device is recognised from the stored principal as well, as early as it can be read, so a tablet that
    // restarts goes light before the session has been validated rather than after.
    AsyncStorage.getItem('blueview_user')
      .then(raw => {
        try { if (raw && JSON.parse(raw)?.site_mode) setForced(f => f || 'light'); } catch (_) {}
      })
      .catch(() => {});
  }, []);

  const toggleTheme = async () => {
    // A forced theme has no toggle: it must not flip, and must not overwrite what the person chose elsewhere.
    if (forced) return;
    const next = !userIsDark;
    setUserIsDark(next);
    try { await AsyncStorage.setItem(THEME_KEY, next ? 'dark' : 'light'); } catch (_) {}
  };

  // ── Animated switch ──────────────────────────────────────────────────────
  // The whole app is keyed on themeKey and remounts on a switch, so the change
  // itself cannot be animated in place. Instead the screen blurs and washes to
  // the TARGET theme's background (fast), the switch happens underneath, and the
  // wash clears to reveal the new theme sharp. About 0.45s end to end.
  // Site-device (forced) accounts have no toggle at all.
  const toggleRef = useRef(toggleTheme);
  toggleRef.current = toggleTheme;
  const expand = useSharedValue(0);
  const fade = useSharedValue(0);
  const [flood, setFlood] = useState(null);

  const commitSwitch = () => { toggleRef.current(); };
  const clearFlood = () => setFlood(null);

  const toggleThemeAnimated = (origin) => {
    if (forced || flood) return;
    const goingDark = !userIsDark;
    const { width, height } = Dimensions.get('window');
    const o = origin || { x: width / 2, y: height / 2 };
    const R = Math.hypot(Math.max(o.x, width - o.x), Math.max(o.y, height - o.y));
    setFlood({ x: o.x, y: o.y, R, color: goingDark ? '#1C2B38' : '#ECEDE9' });
    expand.value = 0;
    fade.value = 1;
    // Fast: the new theme's colour spreads out of the control in a lumpy, liquid
    // edge, the switch happens underneath once it covers the screen, and it
    // clears. About half a second in all.
    expand.value = withTiming(1, { duration: 340, easing: Easing.bezier(0.2, 0.75, 0.25, 1) }, (done) => {
      if (!done) return;
      runOnJS(commitSwitch)();
      fade.value = withTiming(0, { duration: 230, easing: Easing.out(Easing.quad) }, (fin) => {
        if (fin) runOnJS(clearFlood)();
      });
    });
  };

  // Deep copy: new identity on each toggle → triggers downstream re-renders
  const colors = useMemo(() => JSON.parse(JSON.stringify(themeColors)), [themeKey]);

  return (
    <ThemeContext.Provider value={{ isDark, themeKey, colors, toggleTheme, toggleThemeAnimated, forceTheme: setForced, themeForced: !!forced }}>
      {children}
      {flood && <ThemeFlood flood={flood} expand={expand} fade={fade} />}
    </ThemeContext.Provider>
  );
};

// THE LIQUID EDGE. Several plain circles of the new colour spread from the same
// point, each a little off-centre and at its own pace, so the outline of their
// union is lumpy and alive instead of a perfect ring. Circles are cheap (no
// bitmaps, no gradients) and crisp at any size. The first one alone is big
// enough to cover the whole screen at the end.
const BLOBS = [
  { dx: 0,     dy: 0,     r: 1.06, k: 1 },
  { dx: -0.16, dy: -0.10, r: 0.88, k: 1.28 },
  { dx: 0.14,  dy: -0.15, r: 0.84, k: 1.4 },
  { dx: 0.13,  dy: 0.16,  r: 0.86, k: 1.22 },
  { dx: -0.15, dy: 0.12,  r: 0.82, k: 1.45 },
  { dx: 0.02,  dy: -0.2,  r: 0.8,  k: 1.34 },
];

const Blob = ({ b, flood, expand }) => {
  const style = useAnimatedStyle(
    () => ({ transform: [{ scale: Math.max(0.001, Math.min(1, expand.value * b.k)) }] }),
    [expand],
  );
  const r = b.r * flood.R;
  return (
    <Animated.View
      style={[
        {
          position: 'absolute',
          left: flood.x + b.dx * flood.R - r,
          top: flood.y + b.dy * flood.R - r,
          width: r * 2,
          height: r * 2,
          borderRadius: r,
          backgroundColor: flood.color,
        },
        style,
      ]}
    />
  );
};

const ThemeFlood = ({ flood, expand, fade }) => {
  const wrap = useAnimatedStyle(() => ({ opacity: fade.value }), [fade]);
  return (
    <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, { zIndex: 9999, elevation: 24, overflow: 'hidden' }, wrap]}>
      {BLOBS.map((b, i) => <Blob key={i} b={b} flood={flood} expand={expand} />)}
    </Animated.View>
  );
};

export const useTheme = () => {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
};

export default ThemeContext;
