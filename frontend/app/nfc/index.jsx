import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
  Animated,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Nfc,
  CheckCircle,
  XCircle,
  MapPin,
  Wifi,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { useToast } from '../../src/components/Toast';
import { projectsAPI } from '../../src/utils/api';
import { colors, spacing, borderRadius, typography } from '../../src/styles/theme';

export default function NfcCheckInScreen() {
  const router = useRouter();
  const { tag, projectId } = useLocalSearchParams();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [status, setStatus] = useState('ready'); // ready, scanning, success, error
  const [project, setProject] = useState(null);
  const [pulseAnim] = useState(new Animated.Value(1));

  useEffect(() => {
    fetchProject();
  }, [tag, projectId]);

  useEffect(() => {
    if (scanning) {
      startPulseAnimation();
    }
  }, [scanning]);

  const fetchProject = async () => {
    try {
      if (projectId) {
        const proj = await projectsAPI.getById(projectId);
        setProject(proj);
      } else if (tag) {
        // In real app, would look up project by NFC tag
        setProject({ name: 'Site from NFC', location: 'Auto-detected location' });
      }
    } catch (error) {
      console.error('Failed to fetch project:', error);
    } finally {
      setLoading(false);
    }
  };

  const startPulseAnimation = () => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 1.2,
          duration: 800,
          useNativeDriver: true,
        }),
        Animated.timing(pulseAnim, {
          toValue: 1,
          duration: 800,
          useNativeDriver: true,
        }),
      ])
    ).start();
  };

  const handleScan = () => {
    setScanning(true);
    setStatus('scanning');
    
    // Simulate NFC scan (in real app, would use NFC manager)
    setTimeout(() => {
      setScanning(false);
      setStatus('success');
      toast.success('Checked In', 'You have been checked in successfully');
    }, 3000);
  };

  const handleRetry = () => {
    setStatus('ready');
    setScanning(false);
  };

  if (loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={styles.loadingText}>Detecting site...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
        <View style={styles.content}>
          {/* Site Info */}
          {project && (
            <GlassCard style={styles.siteCard}>
              <View style={styles.siteIcon}>
                <MapPin size={24} strokeWidth={1.5} color="#10b981" />
              </View>
              <Text style={styles.siteName}>{project.name}</Text>
              <Text style={styles.siteLocation}>{project.location || project.address}</Text>
            </GlassCard>
          )}

          {/* NFC Status */}
          <View style={styles.nfcSection}>
            {status === 'ready' && (
              <>
                <View style={styles.nfcIconContainer}>
                  <Animated.View style={[styles.pulseRing, { transform: [{ scale: pulseAnim }] }]} />
                  <View style={styles.nfcIcon}>
                    <Nfc size={60} strokeWidth={1} color={colors.text.primary} />
                  </View>
                </View>
                <Text style={styles.nfcTitle}>NFC Check-In</Text>
                <Text style={styles.nfcDesc}>
                  Hold your device near the NFC tag to check in
                </Text>
                <GlassButton
                  title="Start Scanning"
                  icon={<Wifi size={20} strokeWidth={1.5} color={colors.text.primary} />}
                  onPress={handleScan}
                  style={styles.scanBtn}
                />
              </>
            )}

            {status === 'scanning' && (
              <>
                <View style={styles.nfcIconContainer}>
                  <Animated.View 
                    style={[
                      styles.pulseRing, 
                      styles.pulseRingActive,
                      { transform: [{ scale: pulseAnim }] }
                    ]} 
                  />
                  <View style={[styles.nfcIcon, styles.nfcIconScanning]}>
                    <Nfc size={60} strokeWidth={1} color="#3b82f6" />
                  </View>
                </View>
                <Text style={styles.nfcTitle}>Scanning...</Text>
                <Text style={styles.nfcDesc}>
                  Hold your device steady near the NFC tag
                </Text>
                <ActivityIndicator size="large" color="#3b82f6" style={styles.scanningIndicator} />
              </>
            )}

            {status === 'success' && (
              <>
                <View style={styles.successIcon}>
                  <CheckCircle size={80} strokeWidth={1.5} color="#10b981" />
                </View>
                <Text style={styles.successTitle}>Checked In!</Text>
                <Text style={styles.successDesc}>
                  You have been successfully checked in to {project?.name}
                </Text>
                <Text style={styles.successTime}>
                  {new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
                </Text>
                <GlassButton
                  title="Done"
                  onPress={() => router.back()}
                  style={styles.doneBtn}
                />
              </>
            )}

            {status === 'error' && (
              <>
                <View style={styles.errorIcon}>
                  <XCircle size={80} strokeWidth={1.5} color={colors.status.error} />
                </View>
                <Text style={styles.errorTitle}>Check-In Failed</Text>
                <Text style={styles.errorDesc}>
                  Could not read the NFC tag. Please try again.
                </Text>
                <GlassButton
                  title="Try Again"
                  onPress={handleRetry}
                  style={styles.retryBtn}
                />
              </>
            )}
          </View>

          {/* Info */}
          <GlassCard style={styles.infoCard}>
            <Text style={styles.infoTitle}>How it works</Text>
            <View style={styles.infoItem}>
              <View style={styles.infoBullet}><Text style={styles.infoBulletText}>1</Text></View>
              <Text style={styles.infoText}>Tap "Start Scanning" to activate NFC</Text>
            </View>
            <View style={styles.infoItem}>
              <View style={styles.infoBullet}><Text style={styles.infoBulletText}>2</Text></View>
              <Text style={styles.infoText}>Hold your phone near the NFC tag</Text>
            </View>
            <View style={styles.infoItem}>
              <View style={styles.infoBullet}><Text style={styles.infoBulletText}>3</Text></View>
              <Text style={styles.infoText}>Wait for confirmation</Text>
            </View>
          </GlassCard>
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
    gap: spacing.md,
  },
  loadingText: {
    color: colors.text.muted,
    fontSize: 14,
  },
  content: {
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
  nfcSection: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  nfcIconContainer: {
    position: 'relative',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing.xl,
  },
  pulseRing: {
    position: 'absolute',
    width: 160,
    height: 160,
    borderRadius: 80,
    borderWidth: 2,
    borderColor: 'rgba(255, 255, 255, 0.1)',
  },
  pulseRingActive: {
    borderColor: 'rgba(59, 130, 246, 0.3)',
  },
  nfcIcon: {
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  nfcIconScanning: {
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderColor: 'rgba(59, 130, 246, 0.3)',
  },
  nfcTitle: {
    fontSize: 28,
    fontWeight: '300',
    color: colors.text.primary,
    marginBottom: spacing.sm,
  },
  nfcDesc: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 280,
    marginBottom: spacing.xl,
  },
  scanBtn: {
    minWidth: 200,
  },
  scanningIndicator: {
    marginTop: spacing.lg,
  },
  successIcon: {
    marginBottom: spacing.xl,
  },
  successTitle: {
    fontSize: 32,
    fontWeight: '300',
    color: '#10b981',
    marginBottom: spacing.sm,
  },
  successDesc: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 280,
    marginBottom: spacing.md,
  },
  successTime: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    marginBottom: spacing.xl,
  },
  doneBtn: {
    minWidth: 160,
    backgroundColor: '#10b981',
    borderColor: '#10b981',
  },
  errorIcon: {
    marginBottom: spacing.xl,
  },
  errorTitle: {
    fontSize: 28,
    fontWeight: '300',
    color: colors.status.error,
    marginBottom: spacing.sm,
  },
  errorDesc: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 280,
    marginBottom: spacing.xl,
  },
  retryBtn: {
    minWidth: 160,
  },
  infoCard: {
    marginTop: spacing.xl,
  },
  infoTitle: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.muted,
    marginBottom: spacing.md,
  },
  infoItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.sm,
  },
  infoBullet: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  infoBulletText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.muted,
  },
  infoText: {
    fontSize: 13,
    color: colors.text.secondary,
    flex: 1,
  },
});
