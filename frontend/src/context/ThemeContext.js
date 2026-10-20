import React, { createContext, useContext, useState, useEffect, useMemo, useRef } from 'react';
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

  // Deep copy: new identity on each toggle → triggers downstream re-renders
  const colors = useMemo(() => JSON.parse(JSON.stringify(themeColors)), [themeKey]);

  return (
    <ThemeContext.Provider value={{ isDark, themeKey, colors, toggleTheme, forceTheme: setForced, themeForced: !!forced }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside ThemeProvider');
  return ctx;
};

export default ThemeContext;
