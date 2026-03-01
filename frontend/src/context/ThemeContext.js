import React, { createContext, useContext, useState, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { applyTheme } from '../styles/theme';

const THEME_KEY = 'blueview_theme';
const ThemeContext = createContext(null);

export const ThemeProvider = ({ children }) => {
  const [isDark, setIsDark]       = useState(true);
  // themeKey changes on every toggle — _layout passes it as key={themeKey}
  // to the Stack, which forces ALL screens to fully remount and re-execute
  // their module-level StyleSheet.create() with the newly mutated colors.
  const [themeKey, setThemeKey]   = useState('dark-0');

  // Load saved preference on mount
  useEffect(() => {
    AsyncStorage.getItem(THEME_KEY)
      .then(val => {
        if (val !== null) {
          const dark = val === 'dark';
          applyTheme(dark ? 'dark' : 'light');
          setIsDark(dark);
          setThemeKey(`${dark ? 'dark' : 'light'}-0`);
        }
      })
      .catch(() => {});
  }, []);

  const toggleTheme = async () => {
    const next = !isDark;
    // 1. Mutate the shared colors object so new StyleSheet.create calls
    //    see the correct palette when screens remount
    applyTheme(next ? 'dark' : 'light');
    // 2. Update state — triggers re-render
    setIsDark(next);
    // 3. Change the key — forces Stack (and all screens) to fully remount
    setThemeKey(`${next ? 'dark' : 'light'}-${Date.now()}`);
    // 4. Persist
    try { await AsyncStorage.setItem(THEME_KEY, next ? 'dark' : 'light'); } catch (_) {}
  };

  return (
    <ThemeContext.Provider value={{ isDark, themeKey, toggleTheme }}>
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
