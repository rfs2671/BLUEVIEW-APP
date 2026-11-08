import React, { createContext, useContext, useState, useEffect, useMemo, useRef } from 'react';
import { Dimensions, StyleSheet } from 'react-native';
import Svg, { Defs, RadialGradient, Stop, Circle } from 'react-native-svg';
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
  // itself cannot be animated in place. Instead a flood of the TARGET theme's
  // background grows out of the tapped button until it covers the screen, the
  // switch happens underneath it, and the flood then fades away to reveal the
  // new theme. Site-device (forced) accounts have no toggle at all.
  const toggleRef = useRef(toggleTheme);
  toggleRef.current = toggleTheme;
  const expand = useSharedValue(0);
  const fade = useSharedValue(0);
  const [flood, setFlood] = useState(null);

  const commitSwitch = () => { toggleRef.current(); };
  const clearFlood = () => setFlood(null);

  const toggleThemeAnimated = (origin) => {
    if (forced || flood) return;
    const { width, height } = Dimensions.get('window');
    const o = origin || { x: width - 40, y: height - 40 };
    const R = Math.hypot(Math.max(o.x, width - o.x), Math.max(o.y, height - o.y));
    setFlood({ x: o.x, y: o.y, R, color: userIsDark ? '#ECEDE9' : '#1C2B38', ring: userIsDark ? '#1C2B38' : '#ECEDE9' });
    expand.value = 0;
    fade.value = 1;
    expand.value = withTiming(1, { duration: 520, easing: Easing.bezier(0.22, 0.7, 0.2, 1) }, (done) => {
      if (!done) return;
      runOnJS(commitSwitch)();
      fade.value = withTiming(0, { duration: 640, easing: Easing.bezier(0.4, 0, 0.2, 1) }, (fin) => {
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

// A soft wave, not a disc: the flood is a radial gradient whose opaque core is
// just big enough to cover the screen at full scale and whose edge feathers to
// nothing, so there is no hard line sweeping across the UI.
const CORE = 0.55;
const ThemeFlood = ({ flood, expand, fade }) => {
  const wrap = useAnimatedStyle(() => ({ opacity: fade.value }));
  const disc = useAnimatedStyle(() => ({ transform: [{ scale: 0.04 + 0.96 * expand.value }] }));
  const D = flood.R / CORE;
  return (
    <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, { zIndex: 9999, elevation: 9999 }, wrap]}>
      <Animated.View style={[{ position: 'absolute', left: flood.x - D, top: flood.y - D, width: D * 2, height: D * 2 }, disc]}>
        <Svg width={D * 2} height={D * 2}>
          <Defs>
            <RadialGradient id="themeFlood" cx="50%" cy="50%" r="50%">
              <Stop offset="0" stopColor={flood.color} stopOpacity="1" />
              <Stop offset={String(CORE)} stopColor={flood.color} stopOpacity="1" />
              <Stop offset="1" stopColor={flood.color} stopOpacity="0" />
            </RadialGradient>
          </Defs>
          <Circle cx={D} cy={D} r={D} fill="url(#themeFlood)" />
        </Svg>
      </Animated.View>
    </Animated.View>
  );
};

export const useTheme = () => {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
};

export default ThemeContext;
