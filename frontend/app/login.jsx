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

export default function LoginScreen() {
  const router = useRouter();
  const { login, isAuthenticated, isLoading: authLoading, siteMode } = useAuth();
  const toast = useToast();
  
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated && !authLoading) {
      // Check if site mode and redirect accordingly
      if (siteMode) {
        router.replace('/site/checkins');
      } else {
        router.replace('/');
      }
    }
  }, [isAuthenticated, authLoading, siteMode]);

  const handleSubmit = async () => {
    if (!email.trim() || !password.trim()) {
      setError('Please enter email and password');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const userData = await login(email, password);
      
      // Check if site mode login
      if (userData.site_mode) {
        toast.success('Site Mode', `Connected to ${userData.project_name || 'project'}`);
        router.replace('/site/checkins');
      } else {
        toast.success('Welcome back!', `Logged in as ${userData.full_name || userData.name || userData.email}`);
        router.replace('/');
      }
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

          {/* Main Glass Card */}
          <GlassCard style={styles.card}>
            {/* Welcome Text */}
            <View style={styles.welcomeSection}>
              <Text style={styles.welcomeLabel}>WELCOME TO</Text>
              <Text style={styles.welcomeTitle}>Blueview</Text>
            </View>

            {/* Form */}
            <View style={styles.form}>
              {/* Email */}
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

              {/* Password */}
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

              {/* Error */}
              {error ? (
                <View style={styles.errorContainer}>
                  <Text style={styles.errorText}>{error}</Text>
                </View>
              ) : null}

              {/* Submit */}
              <GlassButton
                title="Sign In"
                onPress={handleSubmit}
                loading={loading}
                iconRight={<ArrowRight size={20} strokeWidth={1.5} color={colors.text.primary} />}
                style={styles.submitButton}
              />
            </View>
          </GlassCard>

          {/* Help Text */}
          <Text style={styles.helpText}>Sign in with your Blueview account</Text>
        </View>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background.start,
    gap: spacing.md,
  },
  loadingText: {
    ...typography.label,
    color: colors.text.muted,
  },
  content: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  logoContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xxl,
  },
  logoIcon: {
    width: 44,
    height: 44,
    borderRadius: borderRadius.full,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  logoText: {
    ...typography.label,
    color: colors.text.muted,
  },
  card: {
    width: '100%',
    maxWidth: 400,
  },
  welcomeSection: {
    marginBottom: spacing.xl + spacing.md,
  },
  welcomeLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  welcomeTitle: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
  },
  form: {
    gap: spacing.md,
  },
  inputGroup: {
    gap: spacing.sm,
  },
  inputLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  errorContainer: {
    backgroundColor: colors.status.errorBg,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: 'rgba(248, 113, 113, 0.2)',
    padding: spacing.md,
  },
  errorText: {
    color: colors.status.error,
    fontSize: 14,
  },
  submitButton: {
    marginTop: spacing.sm,
  },
  helpText: {
    marginTop: spacing.xl,
    color: colors.text.subtle,
    fontSize: 14,
  },
});
