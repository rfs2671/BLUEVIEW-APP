import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Nfc, CheckCircle, MapPin, User } from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import GlassInput from '../../src/components/GlassInput';
import OfflineIndicator from '../../src/components/OfflineIndicator';
import { useToast } from '../../src/components/Toast';
import { useCheckIns } from '../../src/hooks/useCheckIns';
import { useProjects } from '../../src/hooks/useProjects';
import { colors, spacing, typography } from '../../src/styles/theme';

export default function NfcCheckInScreen() {
  const router = useRouter();
  const { tag: tagId, projectId } = useLocalSearchParams();
  const toast = useToast();
  
  const { createCheckIn } = useCheckIns();
  const { getProjectById } = useProjects();
  
  const [status, setStatus] = useState('loading');
  const [project, setProject] = useState(null);
  const [workerName, setWorkerName] = useState('');
  const [workerPhone, setWorkerPhone] = useState('');
  const [workerCompany, setWorkerCompany] = useState('');
  const [workerTrade, setWorkerTrade] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    initializeCheckIn();
  }, [tagId, projectId]);

  const initializeCheckIn = async () => {
    try {
      if (!tagId || !projectId) {
        setStatus('error');
        return;
      }

      const proj = await getProjectById(projectId);
      setProject(proj);
      setStatus('ready');
    } catch (error) {
      console.error('Failed to initialize:', error);
      setStatus('error');
    }
  };

  const handleCheckIn = async () => {
    if (!workerName.trim() || !workerPhone.trim() || !workerCompany.trim() || !workerTrade.trim()) {
      toast.warning('Required', 'Please fill all fields');
      return;
    }

    setSubmitting(true);
    try {
      await createCheckIn({
        project_id: projectId,
        worker_name: workerName,
        worker_phone: workerPhone,
        worker_company: workerCompany,
        worker_trade: workerTrade,
        nfc_tag_id: tagId,
        project_name: project?.name || '',
      });

      setStatus('success');
      toast.success('Success', 'Checked in successfully');
      
      setTimeout(() => {
        setWorkerName('');
        setWorkerPhone('');
        setWorkerCompany('');
        setWorkerTrade('');
        setStatus('ready');
      }, 2000);
    } catch (error) {
      console.error('Check-in failed:', error);
      toast.error('Error', 'Check-in failed');
    } finally {
      setSubmitting(false);
    }
  };

  if (status === 'loading') {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={styles.loadingText}>Loading...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  if (status === 'error') {
    return (
      <AnimatedBackground>
        <SafeAreaView style={styles.container}>
          <View style={styles.errorContainer}>
            <Text style={styles.errorText}>Invalid check-in link</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <OfflineIndicator />
        </View>

        <View style={styles.content}>
          <GlassCard style={styles.card}>
            <IconPod size={64} style={styles.icon}>
              {status === 'success' ? (
                <CheckCircle size={32} strokeWidth={1.5} color={colors.success} />
              ) : (
                <Nfc size={32} strokeWidth={1.5} color={colors.primary} />
              )}
            </IconPod>

            <Text style={styles.title}>
              {status === 'success' ? 'Checked In!' : 'NFC Check-In'}
            </Text>

            {status === 'ready' && (
              <>
                <View style={styles.projectInfo}>
                  <MapPin size={16} color={colors.text.muted} />
                  <Text style={styles.projectText}>{project?.name}</Text>
                </View>

                <View style={styles.form}>
                  <GlassInput
                    value={workerName}
                    onChangeText={setWorkerName}
                    placeholder="Full Name"
                    leftIcon={<User size={18} color={colors.text.subtle} />}
                  />
                  <GlassInput
                    value={workerPhone}
                    onChangeText={setWorkerPhone}
                    placeholder="Phone"
                    keyboardType="phone-pad"
                    style={styles.inputSpacing}
                  />
                  <GlassInput
                    value={workerCompany}
                    onChangeText={setWorkerCompany}
                    placeholder="Company"
                    style={styles.inputSpacing}
                  />
                  <GlassInput
                    value={workerTrade}
                    onChangeText={setWorkerTrade}
                    placeholder="Trade"
                    style={styles.inputSpacing}
                  />

                  <GlassButton
                    title="Check In"
                    onPress={handleCheckIn}
                    loading={submitting}
                    style={styles.submitBtn}
                  />
                </View>
              </>
            )}
          </GlassCard>
        </View>
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  header: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  content: { flex: 1, justifyContent: 'center', paddingHorizontal: spacing.lg },
  loadingContainer: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  loadingText: { marginTop: spacing.md, fontSize: typography.sizes.sm, color: colors.text.secondary },
  errorContainer: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  errorText: { fontSize: typography.sizes.md, color: colors.error },
  card: { alignItems: 'center', padding: spacing.xl },
  icon: { marginBottom: spacing.lg },
  title: { fontSize: 24, fontWeight: '700', color: colors.text.primary, marginBottom: spacing.md },
  projectInfo: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.xl },
  projectText: { fontSize: 14, color: colors.text.muted },
  form: { width: '100%' },
  inputSpacing: { marginTop: spacing.sm },
  submitBtn: { marginTop: spacing.lg },
});
