import React, { useState, useEffect, useRef } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Image, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Mail, Lock, Eye, EyeOff, ArrowRight } from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard } from '../src/components/GlassCard';
import GlassInput from '../src/components/GlassInput';
import GlassButton from '../src/components/GlassButton';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { semantic } from '../src/styles/semanticColors';
import { useTheme } from '../src/context/ThemeContext';

// WHERE A ROLE LANDS AFTER LOGIN.
//
// A `superintendent` fell through to '/' — the admin dashboard — because only
// site_mode and cp were named. Nothing then routed him to the CP logbook list,
// and the CP nav is not rendered on that screen, so he reached neither the list
// nor the nav: the two places his own statutory log is reachable from.
//
// He belongs on /logbooks for the same reason a CP does. That is where the
// thirteen log types are listed, including the Construction Superintendent Log
// he is the one person required to file. _layout.jsx's path constraint is
// widened to match, or he would be bounced straight back off it.
const LOGBOOK_LIST_ROLES = ['cp', 'superintendent'];

function getRedirectPath(userData) {
  if (userData.site_mode) return '/site';
  if (LOGBOOK_LIST_ROLES.includes(userData.role)) return '/logbooks';
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

  const pwdRef = useRef(null);

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
          <Image
            source={require('../assets/logo-header.png')}
            style={{ width: '100%', maxWidth: 440, height: 200, resizeMode: 'contain' }}
          />
          <ActivityIndicator size="large" color={colors.primary} style={{ marginTop: spacing.lg }} />
        </View>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      {/* BOTTOM EDGE IS LOAD-BEARING HERE, unlike the other screens that take
          edges={['top']}. This layout is CENTRED and its last element is a
          link; dropping the bottom inset puts that link on the home
          indicator. See 02649d3, which fixed the same symptom, and 0e87696,
          which undid it.

          AND IT IS A JSX COMMENT, not //. In JSX child position `//` is not
          a comment, it is text: f486caf shipped these four lines as visible
          copy above the logo on both auth screens, and the `['top']` inside
          them parsed as an expression container and rendered as `top`.
          React 19 throws on bare text in a <View>, and AnimatedBackground
          renders its children inside one. */}
      <SafeAreaView style={s.container} edges={['top', 'bottom']}>
        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.scrollContent}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
        <View style={s.content}>
          {/* Logo */}
          <View style={s.logoContainer}>
            <Image
              source={require('../assets/logo-header.png')}
              style={s.logoImage}
              resizeMode="contain"
            />
          </View>

          <GlassCard style={s.card}>
            <View style={s.welcomeSection}>
              <Text style={s.welcomeLabel}>WELCOME TO</Text>
              <Text style={s.welcomeTitle}>LeveLog</Text>
            </View>

            {(() => {
              const formContent = (
                <View style={s.form}>
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>EMAIL</Text>
                    <GlassInput
                      value={email}
                      onChangeText={setEmail}
                      placeholder="Enter your email"
                      keyboardType="email-address"
                      autoCapitalize="none"
                      returnKeyType="next"
                      onSubmitEditing={() => pwdRef.current?.focus()}
                      leftIcon={<Mail size={20} strokeWidth={1.5} color={colors.text.subtle} />}
                    />
                  </View>

                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>PASSWORD</Text>
                    <GlassInput
                      ref={pwdRef}
                      value={password}
                      onChangeText={setPassword}
                      placeholder="Enter password"
                      secureTextEntry={!showPassword}
                      returnKeyType="go"
                      onSubmitEditing={handleSubmit}
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
              );
              return Platform.OS === 'web' ? (
                <form
                  style={{ display: 'contents' }}
                  onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}
                >
                  {formContent}
                </form>
              ) : formContent;
            })()}
          </GlassCard>

          {/* Signup affordance — a first-time, unauthenticated visitor must be
              able to reach registration on first paint (App Store reviewers
              self-register here). Reachable directly at /register too. */}
          <Pressable
            onPress={() => router.push('/register')}
            style={s.signupRow}
            accessibilityRole="link"
            accessibilityLabel="Create an account"
          >
            <Text style={s.signupText}>
              Don't have an account? <Text style={s.signupLink}>Sign up</Text>
            </Text>
          </Pressable>
        </View>
        </ScrollView>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
  scroll: { flex: 1 },
  // flexGrow lets the stack vertically center when the viewport is tall
  // enough, and SCROLL when it's taller than the viewport — so the signup
  // link is always reachable (~768px screens included), not just full-screen.
  scrollContent: {
    flexGrow: 1,
    justifyContent: 'center',
    // Trailing scroll extent so the signup link below the card can be
    // scrolled CLEAR of a raised keyboard, not merely up against it.
    paddingBottom: spacing.xxl,
  },
  content: {
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
    marginBottom: -spacing.md,
    marginTop: spacing.xl,
  },
  logoImage: {
    width: '100%',
    height: 200,
    alignSelf: 'center',
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
    color: colors.error || semantic.criticalText,
    textAlign: 'center',
  },
  submitBtn: {
    marginTop: spacing.sm,
  },
  signupRow: {
    marginTop: spacing.lg,
    alignItems: 'center',
  },
  signupText: {
    fontSize: 14,
    color: colors.text.muted,
  },
  signupLink: {
    color: colors.primary,
    fontWeight: '600',
  },
});
}
