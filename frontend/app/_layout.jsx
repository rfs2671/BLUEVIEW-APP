import React from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View, StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { AuthProvider } from '../src/context/AuthContext';
import { DatabaseProvider } from '../src/context/DatabaseContext';
import { ToastProvider } from '../src/components/Toast';
import { colors } from '../src/styles/theme';

/**
 * Root Layout - Wraps entire app with providers
 * Provider order matters:
 * 1. SafeAreaProvider - Device safe areas
 * 2. DatabaseProvider - Local database + sync
 * 3. AuthProvider - User authentication
 * 4. ToastProvider - Toast notifications
 */
export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <DatabaseProvider>
        <AuthProvider>
          <ToastProvider>
            <View style={styles.container}>
              <StatusBar style="light" />
              <Stack
                screenOptions={{
                  headerShown: false,
                  contentStyle: { backgroundColor: colors.background.start },
                  animation: 'fade',
                }}
              />
            </View>
          </ToastProvider>
        </AuthProvider>
      </DatabaseProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background.start,
    overflow: 'hidden',
  },
});
