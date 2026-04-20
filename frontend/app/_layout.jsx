import React, { useEffect, useState } from 'react';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useRouter, usePathname } from 'expo-router';
import { AuthProvider, useAuth } from '../src/context/AuthContext';
import { DatabaseProvider } from '../src/context/DatabaseContext';
import { ThemeProvider, useTheme } from '../src/context/ThemeContext';
import { ToastProvider, useToast } from '../src/components/Toast';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('App crash caught by ErrorBoundary:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <View style={errorStyles.container}>
          <Text style={errorStyles.title}>Something went wrong</Text>
          <Text style={errorStyles.message}>
            The app encountered an unexpected error. Please restart.
          </Text>
          <Pressable
            style={errorStyles.button}
            onPress={() => this.setState({ hasError: false, error: null })}
          >
            <Text style={errorStyles.buttonText}>Try Again</Text>
          </Pressable>
        </View>
      );
    }
    return this.props.children;
  }
}

const errorStyles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#050a12',
    padding: 32,
  },
  title: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '700',
    marginBottom: 12,
  },
  message: {
    color: '#94a3b8',
    fontSize: 15,
    textAlign: 'center',
    marginBottom: 24,
    lineHeight: 22,
  },
  button: {
    backgroundColor: '#3b82f6',
    paddingHorizontal: 28,
    paddingVertical: 12,
    borderRadius: 8,
  },
  buttonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '600',
  },
});

function RouteGuard() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, siteMode, isAuthenticated, isLoading } = useAuth();
  const toast = useToast();
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || isLoading || !isAuthenticated) return;

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

    // CP user exists but has no company assignment — authenticated but every
    // company-gated API endpoint will 403. Contain them to safe paths and surface
    // a clear action instead of a cascade of silent errors.
    if (user?.role === 'cp' && !user?.company_id) {
      const safePaths = ['/logbooks', '/login', '/settings'];
      const currentPath = pathname || '';
      const isOnSafePath = safePaths.some(p => currentPath.startsWith(p));
      if (!isOnSafePath) {
        router.replace('/logbooks');
        setTimeout(() => {
          toast.error(
            'Account Setup Incomplete',
            'Ask your admin to assign you to a company in Settings → Team.'
          );
        }, 400);
      }
    }
  }, [isMounted, isLoading, isAuthenticated, user, siteMode, pathname]);

  return null;
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
      <ErrorBoundary>
        <ThemeProvider>
          <DatabaseProvider>
            <AuthProvider>
              <ToastProvider>
                <AppShell />
              </ToastProvider>
            </AuthProvider>
          </DatabaseProvider>
        </ThemeProvider>
      </ErrorBoundary>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, overflow: 'hidden' },
});
