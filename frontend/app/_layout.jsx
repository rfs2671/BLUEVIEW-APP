import React, { useEffect } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View, StyleSheet } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useRouter, usePathname } from 'expo-router';
import { AuthProvider, useAuth } from '../src/context/AuthContext';
import { DatabaseProvider } from '../src/context/DatabaseContext';
import { ThemeProvider, useTheme } from '../src/context/ThemeContext';
import { ToastProvider } from '../src/components/Toast';

function RouteGuard() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, siteMode, isAuthenticated, isLoading } = useAuth();

  useEffect(() => {
    if (isLoading || !isAuthenticated) return;

    const isSiteDevice = siteMode || user?.role === 'site_device';
    const isCp = user?.role === 'cp';

    // Site device: can ONLY be on /site/*, /login
    if (isSiteDevice) {
      const allowed = pathname.startsWith('/site') || pathname === '/login';
      if (!allowed) {
        router.replace('/site');
      }
    }

    // CP: can be on /logbooks/*, /documents, /settings, /login — NOT admin routes
    if (isCp) {
      const allowed =
        pathname.startsWith('/logbooks') ||
        pathname === '/documents' ||
        pathname === '/settings' ||
        pathname === '/login';
      if (!allowed) {
        router.replace('/logbooks');
      }
    }
  }, [isLoading, isAuthenticated, user, siteMode, pathname]);

  return null; // renders nothing — just a side-effect hook
}

function AppShell() {
  const { isDark, themeKey } = useTheme();
  const bg = isDark ? '#050a12' : '#D6E4F7';

  return (
    <View key={themeKey} style={[styles.container, { backgroundColor: bg }]}>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <RouteGuard />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: bg },
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
