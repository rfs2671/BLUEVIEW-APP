import React, { useState, useRef, useEffect } from 'react';
import { View, Text, StyleSheet, Pressable, ActivityIndicator, Image, Platform } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Mail, Lock, Eye, EyeOff, User, Building2, ArrowRight } from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { GlassCard } from '../src/components/GlassCard';
import GlassInput from '../src/components/GlassInput';
import GlassButton from '../src/components/GlassButton';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { authAPI } from '../src/utils/api';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { useTheme } from '../src/context/ThemeContext';

export default function RegisterScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { login, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [name, setName] = useState('');
  const [company, setCompany] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const companyRef = useRef(null);
  const emailRef = useRef(null);
  const pwdRef = useRef(null);

  // Already signed in → leave the auth screens.
  useEffect(() => {
    if (isAuthenticated && !authLoading) router.replace('/');
  }, [isAuthenticated, authLoading]);

  const handleSubmit = async () => {
    if (!name.trim() || !email.trim() || !password.trim()) {
      setError('Please enter your name, email, and password');
      return;
    }
    setLoading(true);
    setError('');
    try {
      // role "owner" so a self-serve signup doesn't require a pre-existing
      // company_id (the backend requires a company for non-owner/admin roles).
      await authAPI.register({
        name: name.trim(),
        email: email.trim(),
        password,
        company_name: company.trim() || null,
        role: 'owner',
      });
      // Register returns no token; sign in to establish the session.
      await login(email.trim(), password);
      toast.success('Account created', 'Welcome to LeveLog');
      router.replace('/');
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Could not create account';
      setError(typeof msg === 'string' ? msg : 'Could not create account');
      toast.error('Sign up failed', typeof msg === 'string' ? msg : 'Could not create account');
    } finally {
      setLoading(false);
    }
  };

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
      <SafeAreaView style={s.container}>
        <View style={s.content}>
          <View style={s.logoContainer}>
            <Image source={require('../assets/logo-header.png')} style={s.logoImage} resizeMode="contain" />
          </View>

          <GlassCard style={s.card}>
            <View style={s.welcomeSection}>
              <Text style={s.welcomeLabel}>CREATE YOUR ACCOUNT</Text>
              <Text style={s.welcomeTitle}>Sign up</Text>
            </View>

            {(() => {
              const formContent = (
                <View style={s.form}>
                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>FULL NAME</Text>
                    <GlassInput
                      value={name}
                      onChangeText={setName}
                      placeholder="Your name"
                      returnKeyType="next"
                      onSubmitEditing={() => companyRef.current?.focus()}
                      leftIcon={<User size={20} strokeWidth={1.5} color={colors.text.subtle} />}
                    />
                  </View>

                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>COMPANY (OPTIONAL)</Text>
                    <GlassInput
                      ref={companyRef}
                      value={company}
                      onChangeText={setCompany}
                      placeholder="Your company"
                      returnKeyType="next"
                      onSubmitEditing={() => emailRef.current?.focus()}
                      leftIcon={<Building2 size={20} strokeWidth={1.5} color={colors.text.subtle} />}
                    />
                  </View>

                  <View style={s.inputGroup}>
                    <Text style={s.inputLabel}>EMAIL</Text>
                    <GlassInput
                      ref={emailRef}
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
                      placeholder="Create a password"
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

                  {error ? <Text style={s.errorText}>{error}</Text> : null}

                  <GlassButton
                    title={loading ? 'Creating account...' : 'Create account'}
                    icon={!loading ? <ArrowRight size={18} strokeWidth={1.5} color={colors.text.primary} /> : null}
                    onPress={handleSubmit}
                    loading={loading}
                    style={s.submitBtn}
                  />
                </View>
              );
              return Platform.OS === 'web' ? (
                <form style={{ display: 'contents' }} onSubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
                  {formContent}
                </form>
              ) : formContent;
            })()}
          </GlassCard>

          <Pressable
            onPress={() => router.push('/login')}
            style={s.signinRow}
            accessibilityRole="link"
            accessibilityLabel="Sign in"
          >
            <Text style={s.signinText}>
              Already have an account? <Text style={s.signinLink}>Sign in</Text>
            </Text>
          </Pressable>
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
    loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' },
    logoContainer: { alignItems: 'center', marginBottom: -spacing.md, marginTop: spacing.xl },
    logoImage: { width: '100%', height: 200, alignSelf: 'center' },
    card: { padding: spacing.xl },
    welcomeSection: { marginBottom: spacing.xl },
    welcomeLabel: { ...typography.label, color: colors.text.muted, marginBottom: spacing.xs },
    welcomeTitle: { fontSize: 32, fontWeight: '200', color: colors.text.primary },
    form: { gap: spacing.md },
    inputGroup: { gap: spacing.xs },
    inputLabel: { ...typography.label, color: colors.text.muted },
    errorText: { fontSize: 13, color: colors.error || '#f87171', textAlign: 'center' },
    submitBtn: { marginTop: spacing.sm },
    signinRow: { marginTop: spacing.lg, alignItems: 'center' },
    signinText: { fontSize: 14, color: colors.text.muted },
    signinLink: { color: colors.primary, fontWeight: '600' },
  });
}
