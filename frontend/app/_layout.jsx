import React from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View, StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AuthProvider } from '../src/context/AuthContext';
import { DatabaseProvider } from '../src/context/DatabaseContext';
import { ThemeProvider, useTheme } from '../src/context/ThemeContext';
import { ToastProvider } from '../src/components/Toast';
import { colors } from '../src/styles/theme';

function AppShell() {
  const { isDark } = useTheme();
  return (
    <View style={[styles.container, { backgroundColor: colors.background.start }]}>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.background.start },
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
  container: { flex: 1, overflow: 'hidden' },
});
