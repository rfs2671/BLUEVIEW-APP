import React from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View, StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AuthProvider } from '../src/context/AuthContext';
import { DatabaseProvider } from '../src/context/DatabaseContext';
import { ThemeProvider, useTheme } from '../src/context/ThemeContext';
import { ToastProvider } from '../src/components/Toast';

/**
 * AppShell reads ThemeContext so it re-renders on toggle.
 * The `key={themeKey}` on the Stack forces a full remount of all
 * screens whenever the theme changes — this is the only reliable
 * way to make module-level StyleSheet.create() calls pick up new
 * colors without modifying every screen file.
 */
function AppShell() {
  const { isDark, themeKey } = useTheme();

  return (
    <View style={styles.container}>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <Stack
        key={themeKey}
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: isDark ? '#050a12' : '#e8f0fb' },
          animation: 'fade',
        }}
      />
    </View>
  );
}

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <DatabaseProvider>
          <AuthProvider>
            <ToastProvider>
              <AppShell />
            </ToastProvider>
          </AuthProvider>
        </DatabaseProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    overflow: 'hidden',
  },
});
