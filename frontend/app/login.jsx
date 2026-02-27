import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Mail, Lock, Eye, EyeOff, ArrowRight, LayoutGrid } from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard } from '../src/components/GlassCard';
import GlassInput from '../src/components/GlassInput';
import GlassButton from '../src/components/GlassButton';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { colors, spacing, borderRadius, typography } from '../src/styles/theme';

/**
 * Routing logic after login:
 *   site_mode  → /site
 *   role=cp    → /logbooks   (CP's entire app is logbooks)
 *   everyone else → /        (admin dashboard)
 */
function getRedirectPath(userData) {
  if (userData.site_mode) return '/site';
  if (userData.role === 'cp') return '/logbooks';
  return '/';
}

export default function LoginScreen() {
  const router = useRouter();
  const { login, isAuthenticated, isLoading: authLoading, siteMode, user } = useAuth();
  const toast = useToast();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Redirect if already authenticated (e.g. app restart with valid session)
  useEffect(() => {
    if (isAuthenticated && !authLoading) {
      if (siteMode) {
        router.replace('/site');
      } else if (user?.role === 'cp') {
        router.replace('/logbooks');
      } else {
        router.replace('/');
      }
    }
  }, [isAuthenticated, authLoading, siteMode, user]);

  const handleSubmit = async () => {
    if (!email.trim() || !password.trim()) {
      setError('Please enter email and password');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const userData = await login(email, password);
      const dest = getRedirectPath(userData);

      if (userData.site_mode) {
        toast.success('Site Mode', `Connected to ${userData.project_name || 'project'}`);
      } else {
        toast.success('Welcome back!', `Logged in as ${userData.full_name || userData.name || userData.email}`);
      }

      router.replace(dest);
    } catch (err) {
      const errorMessage = err.response?.data?.detail || err.message || 'Invalid credentials';
      setError(errorMessage);
      toast.error('Login Failed', errorMessage);
    } finally {
      setLoading(false);
    }
  };

  if (authLoading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.text.primary} />
        <Text style={styles.loadingText}>LOADING</Text>
      </View>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container}>
        <View style={styles.content}>
          {/* Logo */}
          <View style={styles.logoContainer}>
            <View style={styles.logoIcon}>
              <LayoutGrid size={20} strokeWidth={1.5} color={colors.text.primary} />
            </View>
            <Text style={styles.logoText}>BLUEVIEW</Text>
          </View>

          <GlassCard style={styles.card}>
            <View style={styles.welcomeSection}>
              <Text style={styles.welcomeLabel}>WELCOME TO</Text>
              <Text style={styles.welcomeTitle}>Blueview</Text>
            </View>

            <View style={styles.form}>
              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>EMAIL</Text>
                <GlassInput
                  value={email}
                  onChangeText={setEmail}
                  placeholder="Enter your email"
                  keyboardType="email-address"
                  autoCapitalize="none"
                  leftIcon={<Mail size={20} strokeWidth={1.5} color={colors.text.subtle} />}
                />
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>PASSWORD</Text>
                <GlassInput
                  value={password}
                  onChangeText={setPassword}
                  placeholder="Enter password"
                  secureTextEntry={!showPassword}
                  leftIcon={<Lock size={20} strokeWidth={1.5} color={colors.text.subtle} />}
                  rightIcon={
                    <Pressable onPress={() => setShowPassword(!showPassword)}>
                      {showPassword ? (
                        <EyeOff size={20} strokeWidth={1.5} color={colors.text.subtle} />
                      ) : (
                        <Eye size={20} strokeWidth={1.5} color={colors.text.subtle} />
                      )}
                    </Pressable>
                  }
                />
              </View>

              {error ? (
                <Text style={styles.errorText}>{error}</Text>
              ) : null}

              <GlassButton
                title={loading ? 'Signing in...' : 'Sign In'}
                icon={!loading ? <ArrowRight size={18} strokeWidth={1.5} color="#fff" /> : null}
                onPress={handleSubmit}
                loading={loading}
                disabled={loading}
                style={styles.loginBtn}
              />
            </View>
          </GlassCard>
        </View>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background?.start || '#0a0a0a',
    gap: spacing.md,
  },
  loadingText: {
    color: colors.text.muted,
    fontSize: 12,
    letterSpacing: 2,
    fontWeight: '600',
  },
  container: { flex: 1 },
  content: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.lg,
  },
  logoContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xxl,
  },
  logoIcon: {
    width: 36,
    height: 36,
    borderRadius: 8,
    backgroundColor: 'rgba(255,255,255,0.1)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoText: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.text.primary,
    letterSpacing: 3,
  },
  card: {
    width: '100%',
    maxWidth: 400,
    padding: spacing.xl,
  },
  welcomeSection: { marginBottom: spacing.xl },
  welcomeLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
    letterSpacing: 2,
    marginBottom: spacing.xs,
  },
  welcomeTitle: {
    fontSize: 32,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -0.5,
  },
  form: { gap: spacing.md },
  inputGroup: { gap: spacing.xs },
  inputLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
    letterSpacing: 1,
  },
  errorText: {
    fontSize: 13,
    color: '#f87171',
    textAlign: 'center',
  },
  loginBtn: {
    marginTop: spacing.sm,
  },
});
