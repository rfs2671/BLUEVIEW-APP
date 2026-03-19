import React, { useState, useEffect } from 'react';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Mail, Lock, Eye, EyeOff, ArrowRight } from 'lucide-react-native';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Image } from 'react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard } from '../src/components/GlassCard';
import GlassInput from '../src/components/GlassInput';
import GlassButton from '../src/components/GlassButton';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { useTheme } from '../src/context/ThemeContext';

function getRedirectPath(userData) {
  if (userData.site_mode) return '/site';
  if (userData.role === 'cp') return '/logbooks';
  return '/';
}

export default function LoginScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { login, isAuthenticated, isLoading: authLoading, siteMode, user } = useAuth();
  const toast = useToast();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

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

  // FIX: branded splash instead of bare white View
  if (authLoading) {
    return (
      <AnimatedBackground>
        <View style={s.loadingContainer}>
          <View style={s.logoIcon}>
            <Image
              source={require('../assets/icon.png')}
              style={{ width: 28, height: 28, resizeMode: 'contain' }}
            />
          </View>
          <Text style={s.logoTextLoading}>BLUEVIEW</Text>
          <ActivityIndicator size="large" color={colors.primary} style={{ marginTop: spacing.lg }} />
        </View>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container}>
        <View style={s.content}>
          {/* Logo */}
          <View style={s.logoContainer}>
            <View style={s.logoIcon}>
              <Image
                source={require('../assets/icon.png')}
                style={{ width: 28, height: 28, resizeMode: 'contain' }}
              />
            </View>
            <Text style={s.logoText}>BLUEVIEW</Text>
          </View>

          <GlassCard style={s.card}>
            <View style={s.welcomeSection}>
              <Text style={s.welcomeLabel}>WELCOME TO</Text>
              <Text style={s.welcomeTitle}>Blueview</Text>
            </View>

            <View style={s.form}>
              <View style={s.inputGroup}>
                <Text style={s.inputLabel}>EMAIL</Text>
                <GlassInput
                  value={email}
                  onChangeText={setEmail}
                  placeholder="Enter your email"
                  keyboardType="email-address"
                  autoCapitalize="none"
                  leftIcon={<Mail size={20} strokeWidth={1.5} color={colors.text.subtle} />}
                />
              </View>

              <View style={s.inputGroup}>
                <Text style={s.inputLabel}>PASSWORD</Text>
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
                <Text style={s.errorText}>{error}</Text>
              ) : null}

              <GlassButton
                title={loading ? 'Signing in...' : 'Sign In'}
                icon={!loading ? <ArrowRight size={18} strokeWidth={1.5} color={colors.text.primary} /> : null}
                onPress={handleSubmit}
                loading={loading}
                style={s.submitBtn}
              />
            </View>
          </GlassCard>
        </View>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
  content: {
    flex: 1,
    justifyContent: 'center',
    padding: spacing.lg,
    maxWidth: 440,
    width: '100%',
    alignSelf: 'center',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  logoContainer: {
    alignItems: 'center',
    marginBottom: spacing.xl,
  },
  logoIcon: {
    width: 48,
    height: 48,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.sm,
  },
  logoText: {
    ...typography.label,
    fontSize: 18,
    color: colors.text.primary,
    letterSpacing: 6,
  },
  logoTextLoading: {
    ...typography.label,
    fontSize: 18,
    color: colors.text.primary,
    letterSpacing: 6,
    marginTop: spacing.sm,
  },
  card: { padding: spacing.xl },
  welcomeSection: { marginBottom: spacing.xl },
  welcomeLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  welcomeTitle: {
    fontSize: 32,
    fontWeight: '200',
    color: colors.text.primary,
  },
  form: { gap: spacing.md },
  inputGroup: { gap: spacing.xs },
  inputLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  errorText: {
    fontSize: 13,
    color: colors.error || '#f87171',
    textAlign: 'center',
  },
  submitBtn: {
    marginTop: spacing.sm,
  },
});
}
