import React, { createContext, useContext, useState, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { applyTheme } from '../styles/theme';

const THEME_KEY = 'blueview_theme';

const ThemeContext = createContext(null);

export const ThemeProvider = ({ children }) => {
  const [isDark, setIsDark] = useState(true); // default dark

  // Load saved preference on mount and apply it immediately
  useEffect(() => {
    AsyncStorage.getItem(THEME_KEY)
      .then(val => {
        if (val !== null) {
          const dark = val === 'dark';
          applyTheme(dark ? 'dark' : 'light');
          setIsDark(dark);
        }
        // if val is null (first launch), keep dark default — already applied at module load
      })
      .catch(() => {});
  }, []);

  const toggleTheme = async () => {
    const next = !isDark;
    // 1. Mutate the shared colors object immediately so every screen sees new values
    applyTheme(next ? 'dark' : 'light');
    // 2. Trigger a full React re-render
    setIsDark(next);
    // 3. Persist preference
    try {
      await AsyncStorage.setItem(THEME_KEY, next ? 'dark' : 'light');
    } catch (_) {}
  };

  const theme = {
    isDark,
    toggleTheme,
  };

  return (
    <ThemeContext.Provider value={theme}>
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
