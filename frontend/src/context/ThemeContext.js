/**
 * ThemeContext.js
 * Place at: frontend/src/context/ThemeContext.js
 *
 * FIX: The original exposed the same mutable `colors` reference on every
 * render. Components using useTheme().colors never got a new reference after
 * toggleTheme(), so styles weren't re-evaluated.
 *
 * Now useMemo keyed to themeKey returns a shallow copy → new identity → re-render.
 */

import React, { createContext, useContext, useState, useEffect, useMemo } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { applyTheme, colors as themeColors } from '../styles/theme';

const THEME_KEY = 'blueview_theme';
const ThemeContext = createContext(null);

export const ThemeProvider = ({ children }) => {
  const [isDark, setIsDark]     = useState(true);
  const [themeKey, setThemeKey] = useState(0);

  useEffect(() => {
    AsyncStorage.getItem(THEME_KEY)
      .then(val => {
        if (val !== null) {
          const dark = val === 'dark';
          applyTheme(dark ? 'dark' : 'light');
          setIsDark(dark);
          setThemeKey(k => k + 1);
        }
      })
      .catch(() => {});
  }, []);

  const toggleTheme = async () => {
    const next = !isDark;
    applyTheme(next ? 'dark' : 'light');
    setIsDark(next);
    setThemeKey(k => k + 1);
    try { await AsyncStorage.setItem(THEME_KEY, next ? 'dark' : 'light'); } catch (_) {}
  };

  // Shallow copy: new identity on each toggle → triggers downstream re-renders
  const colors = useMemo(() => ({ ...themeColors }), [themeKey]);

  return (
    <ThemeContext.Provider value={{ isDark, themeKey, colors, toggleTheme }}>
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
