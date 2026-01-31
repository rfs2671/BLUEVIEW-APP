import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Animated,
  ActivityIndicator,
  Platform,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  Nfc,
  CheckCircle,
  XCircle,
  MapPin,
  User,
  AlertCircle,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import { useToast } from '../../src/components/Toast';
import { nfcAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

const WORKER_PROFILE_KEY = 'blueview_worker_profile';
const WORKER_ID_KEY = 'blueview_worker_id';

export default function NfcCheckInScreen() {
  const router = useRouter();
  const { tag: tagId, projectId } = useLocalSearchParams();
  const toast = useToast();

  // States for the check-in flow
  const [status, setStatus] = useState('loading'); // loading, register, checking_in, success, error
  const [tagInfo, setTagInfo] = useState(null);
  const [workerProfile, setWorkerProfile] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [pulseAnim] = useState(new Animated.Value(1));

  // Registration form fields
  const [formPhone, setFormPhone] = useState('');
  const [formName, setFormName] = useState('');
  const [formTrade, setFormTrade] = useState('');
  const [formCompany, setFormCompany] = useState('');
  const [registering, setRegistering] = useState(false);

  // Check-in result
  const [checkInResult, setCheckInResult] = useState(null);

  useEffect(() => {
    initializeCheckIn();
  }, [tagId]);

  useEffect(() => {
    if (status === 'checking_in') {
      startPulseAnimation();
    }
  }, [status]);

  const startPulseAnimation = () => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 1.2,
          duration: 600,
          useNativeDriver: true,
        }),
        Animated.timing(pulseAnim, {
          toValue: 1,
          duration: 600,
          useNativeDriver: true,
        }),
      ])
    ).start();
  };

  const initializeCheckIn = async () => {
    try {
      // If no tag ID provided, show error
      if (!tagId) {
        setStatus('error');
        setErrorMessage('No NFC tag detected. Please tap an NFC tag to check in.');
        return;
      }

      // Fetch tag info from backend
      const info = await nfcAPI.getTagInfo(tagId);
      setTagInfo(info);

      // Check if worker profile exists in local storage
      const storedProfile = await AsyncStorage.getItem(WORKER_PROFILE_KEY);
      const storedWorkerId = await AsyncStorage.getItem(WORKER_ID_KEY);

      if (storedProfile && storedWorkerId) {
        // Returning worker - auto check-in
        const profile = JSON.parse(storedProfile);
        setWorkerProfile(profile);
        await performCheckIn(storedWorkerId, profile.phone);
      } else {
        // New worker - show registration form
        setStatus('register');
      }
    } catch (error) {
      console.error('Failed to initialize check-in:', error);
      setStatus('error');
      setErrorMessage(error.response?.data?.detail || 'Could not find this NFC tag. Contact site admin.');
    }
  };

  const performCheckIn = async (workerId, phone) => {
    setStatus('checking_in');
    
    try {
      const result = await nfcAPI.checkIn({
        worker_id: workerId,
        tag_id: tagId,
        phone: phone,
      });

      setCheckInResult(result);
      setStatus('success');

      // Auto-close after 3 seconds
      setTimeout(() => {
        if (Platform.OS === 'web') {
          window.close();
        }
      }, 3000);
    } catch (error) {
      console.error('Check-in failed:', error);
      setStatus('error');
      setErrorMessage(error.response?.data?.detail || 'Check-in failed. Please try again.');
    }
  };

  const handleRegister = async () => {
    if (!formPhone.trim() || !formName.trim() || !formTrade.trim() || !formCompany.trim()) {
      toast.error('Error', 'Please fill in all fields');
      return;
    }

    setRegistering(true);

    try {
      // Generate device fingerprint
      const deviceId = `WEB_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

      // Register worker with backend
      const result = await nfcAPI.registerWorker({
        phone: formPhone,
        name: formName,
        trade: formTrade,
        company: formCompany,
        device_id: deviceId,
      });

      // Save profile to local storage
      const profile = {
        phone: formPhone,
        name: formName,
        trade: formTrade,
        company: formCompany,
        deviceId: deviceId,
        registeredAt: new Date().toISOString(),
      };

      await AsyncStorage.setItem(WORKER_PROFILE_KEY, JSON.stringify(profile));
      await AsyncStorage.setItem(WORKER_ID_KEY, result.worker_id);

      setWorkerProfile(profile);

      // Auto check-in after registration
      await performCheckIn(result.worker_id, formPhone);
    } catch (error) {
      console.error('Registration failed:', error);
      toast.error('Error', error.response?.data?.detail || 'Registration failed. Please try again.');
      setRegistering(false);
    }
  };

  // Loading state
  if (status === 'loading') {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.centerContent}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={styles.loadingText}>Detecting site...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  // Error state
  if (status === 'error') {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.centerContent}>
            <View style={styles.errorIcon}>
              <XCircle size={80} strokeWidth={1.5} color={colors.status.error} />
            </View>
            <Text style={styles.errorTitle}>Check-In Failed</Text>
            <Text style={styles.errorMessage}>{errorMessage}</Text>
            <GlassButton
              title="Try Again"
              onPress={() => router.back()}
              style={styles.actionBtn}
            />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  // Registration form
  if (status === 'register') {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
          <View style={styles.registerContent}>
            {/* Site Info */}
            {tagInfo && (
              <GlassCard style={styles.siteCard}>
                <View style={styles.siteIcon}>
                  <MapPin size={24} strokeWidth={1.5} color="#10b981" />
                </View>
                <Text style={styles.siteName}>{tagInfo.project_name || 'Job Site'}</Text>
                <Text style={styles.siteLocation}>{tagInfo.location_description || 'Check-In Point'}</Text>
              </GlassCard>
            )}

            {/* Registration Form */}
            <GlassCard style={styles.formCard}>
              <View style={styles.formHeader}>
                <User size={24} strokeWidth={1.5} color={colors.text.primary} />
                <Text style={styles.formTitle}>Worker Registration</Text>
              </View>
              <Text style={styles.formDesc}>
                First time here? Register to check in automatically next time.
              </Text>

              <GlassInput
                value={formPhone}
                onChangeText={setFormPhone}
                placeholder="Phone Number"
                keyboardType="phone-pad"
                style={styles.input}
              />
              <GlassInput
                value={formName}
                onChangeText={setFormName}
                placeholder="Full Name"
                style={styles.input}
              />
              <GlassInput
                value={formTrade}
                onChangeText={setFormTrade}
                placeholder="Trade (e.g., Electrician, Carpenter)"
                style={styles.input}
              />
              <GlassInput
                value={formCompany}
                onChangeText={setFormCompany}
                placeholder="Company Name"
                style={styles.input}
              />

              <GlassButton
                title={registering ? 'Registering...' : 'Register & Check In'}
                onPress={handleRegister}
                loading={registering}
                disabled={registering}
                style={styles.registerBtn}
              />
            </GlassCard>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  // Checking in state
  if (status === 'checking_in') {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.centerContent}>
            <Animated.View style={[styles.checkingIcon, { transform: [{ scale: pulseAnim }] }]}>
              <Nfc size={60} strokeWidth={1} color="#3b82f6" />
            </Animated.View>
            <Text style={styles.checkingTitle}>Checking you in...</Text>
            <Text style={styles.checkingName}>{workerProfile?.name || 'Worker'}</Text>
            <ActivityIndicator size="large" color="#3b82f6" style={styles.spinner} />
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  // Success state
  if (status === 'success') {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.centerContent}>
            <View style={styles.successIcon}>
              <CheckCircle size={100} strokeWidth={1.5} color="#10b981" />
            </View>
            <Text style={styles.successTitle}>Checked In!</Text>
            <Text style={styles.successMessage}>All books signed.</Text>
            
            {checkInResult && (
              <GlassCard style={styles.resultCard}>
                <Text style={styles.resultName}>{checkInResult.worker_name || workerProfile?.name}</Text>
                <Text style={styles.resultProject}>{checkInResult.project_name || tagInfo?.project_name}</Text>
                <Text style={styles.resultTime}>
                  {new Date(checkInResult.timestamp || Date.now()).toLocaleTimeString('en-US', {
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </Text>
              </GlassCard>
            )}

            <Text style={styles.autoCloseText}>This page will close automatically...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return null;
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  centerContent: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  loadingText: {
    color: colors.text.muted,
    fontSize: 16,
    marginTop: spacing.lg,
  },
  // Error styles
  errorIcon: {
    marginBottom: spacing.xl,
  },
  errorTitle: {
    fontSize: 28,
    fontWeight: '300',
    color: colors.status.error,
    marginBottom: spacing.sm,
  },
  errorMessage: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 300,
    marginBottom: spacing.xl,
    lineHeight: 22,
  },
  actionBtn: {
    minWidth: 160,
  },
  // Register styles
  registerContent: {
    flex: 1,
    padding: spacing.lg,
    justifyContent: 'center',
  },
  siteCard: {
    alignItems: 'center',
    marginBottom: spacing.xl,
  },
  siteIcon: {
    width: 56,
    height: 56,
    borderRadius: borderRadius.full,
    backgroundColor: 'rgba(16, 185, 129, 0.2)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.md,
  },
  siteName: {
    fontSize: 24,
    fontWeight: '400',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  siteLocation: {
    fontSize: 14,
    color: colors.text.muted,
  },
  formCard: {
    padding: spacing.lg,
  },
  formHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.sm,
  },
  formTitle: {
    fontSize: 20,
    fontWeight: '500',
    color: colors.text.primary,
  },
  formDesc: {
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.lg,
  },
  input: {
    marginBottom: spacing.md,
  },
  registerBtn: {
    marginTop: spacing.md,
    backgroundColor: '#10b981',
    borderColor: '#10b981',
  },
  // Checking in styles
  checkingIcon: {
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderWidth: 2,
    borderColor: 'rgba(59, 130, 246, 0.3)',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.xl,
  },
  checkingTitle: {
    fontSize: 24,
    fontWeight: '300',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  checkingName: {
    fontSize: 18,
    color: '#3b82f6',
    fontWeight: '500',
    marginBottom: spacing.lg,
  },
  spinner: {
    marginTop: spacing.md,
  },
  // Success styles
  successIcon: {
    marginBottom: spacing.xl,
  },
  successTitle: {
    fontSize: 42,
    fontWeight: '200',
    color: '#10b981',
    marginBottom: spacing.xs,
  },
  successMessage: {
    fontSize: 18,
    color: colors.text.muted,
    marginBottom: spacing.xl,
  },
  resultCard: {
    alignItems: 'center',
    minWidth: 280,
    marginBottom: spacing.xl,
  },
  resultName: {
    fontSize: 22,
    fontWeight: '400',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  resultProject: {
    fontSize: 14,
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  resultTime: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
  },
  autoCloseText: {
    fontSize: 12,
    color: colors.text.subtle,
    fontStyle: 'italic',
  },
});
