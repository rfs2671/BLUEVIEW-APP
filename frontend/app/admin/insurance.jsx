import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  RefreshControl,
  Image,
} from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  LogOut,
  Shield,
  ShieldCheck,
  ShieldAlert,
  Building2,
  RefreshCw,
  AlertTriangle,
  CheckCircle,
  Clock,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, IconPod } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import FloatingNav from '../../src/components/FloatingNav';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import apiClient from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

const INSURANCE_LABELS = {
  general_liability: 'General Liability',
  workers_comp: "Workers' Compensation",
  disability: 'Disability Benefits',
};

const getExpirationColor = (dateStr) => {
  if (!dateStr) return '#6b7280';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return '#6b7280';
  const daysLeft = Math.ceil((d - new Date()) / (1000 * 60 * 60 * 24));
  if (daysLeft < 0) return '#ef4444';
  if (daysLeft <= 60) return '#f59e0b';
  return '#22c55e';
};

const formatDate = (dateStr) => {
  if (!dateStr) return '--';
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return typeof dateStr === 'string' ? dateStr : '--';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

export default function AdminInsuranceScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { logout, isAuthenticated, isLoading: authLoading, user } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  useEffect(() => {
    if (isAuthenticated) fetchInsurance();
  }, [isAuthenticated]);

  const fetchInsurance = async () => {
    if (!loading) setRefreshing(true);
    try {
      const resp = await apiClient.get('/api/admin/company/insurance');
      setData(resp.data);
    } catch (error) {
      console.error('Failed to fetch insurance:', error);
      toast.error('Error', error.response?.data?.detail || 'Could not load insurance data');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const resp = await apiClient.post('/api/admin/company/insurance/refresh');
      setData((prev) => ({
        ...prev,
        gc_insurance_records: resp.data.gc_insurance_records,
        gc_license_status: resp.data.gc_license_status || prev?.gc_license_status,
        gc_license_expiration: resp.data.gc_license_expiration || prev?.gc_license_expiration,
        gc_last_verified: resp.data.gc_last_verified,
      }));
      if (resp.data.warning) {
        toast.warning('Warning', resp.data.warning);
      } else {
        toast.success('Refreshed', 'Insurance data updated from DOB');
      }
    } catch (error) {
      toast.error('Error', error.response?.data?.detail || 'Could not refresh from DOB');
    } finally {
      setRefreshing(false);
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  if (authLoading || loading) {
    return (
      <AnimatedBackground>
        <SafeAreaView style={s.container}>
          <View style={s.loadingContainer}>
            <ActivityIndicator size="large" color={colors.text.primary} />
            <Text style={s.loadingText}>Loading insurance data...</Text>
          </View>
        </SafeAreaView>
      </AnimatedBackground>
    );
  }

  const gcResolved = data?.gc_resolved;
  const records = data?.gc_insurance_records || [];
  const licenseStatus = (data?.gc_license_status || '').toUpperCase();
  const licenseActive = licenseStatus === 'ACTIVE';

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.back()}
            />
            <Image
              source={require('../../assets/logo-header.png')}
              style={{ width: 180, height: 48, resizeMode: 'contain' }}
            />
          </View>
          <GlassButton
            variant="icon"
            icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={handleLogout}
          />
        </View>

        <ScrollView
          style={s.scroll}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={fetchInsurance} tintColor={colors.text.muted} />
          }
        >
          <Text style={s.pageTitle}>Insurance & License</Text>
          <Text style={s.pageSubtitle}>{data?.company_name || ''}</Text>

          {/* Not linked to DOB */}
          {!gcResolved && (
            <GlassCard style={s.warningCard}>
              <View style={s.warningRow}>
                <AlertTriangle size={18} color="#f59e0b" />
                <Text style={s.warningText}>
                  Company not linked to a DOB license. Contact your administrator.
                </Text>
              </View>
            </GlassCard>
          )}

          {/* GC License card */}
          {gcResolved && (
            <GlassCard style={s.licenseCard}>
              <View style={s.licenseHeader}>
                <IconPod size={44}>
                  <Building2 size={20} strokeWidth={1.5} color={licenseActive ? '#22c55e' : '#ef4444'} />
                </IconPod>
                <View style={{ flex: 1 }}>
                  <Text style={s.licenseNumber}>GC-{data?.gc_license_number || '--'}</Text>
                  <Text style={[s.licenseStatus, { color: licenseActive ? '#22c55e' : '#ef4444' }]}>
                    {licenseStatus || 'Unknown'}
                  </Text>
                </View>
                {licenseActive ? (
                  <CheckCircle size={20} color="#22c55e" />
                ) : (
                  <ShieldAlert size={20} color="#ef4444" />
                )}
              </View>
              {data?.gc_business_name && (
                <Text style={s.licenseDetail}>{data.gc_business_name}</Text>
              )}
              {data?.gc_license_expiration && (
                <Text style={s.licenseDetail}>
                  License expires: {formatDate(data.gc_license_expiration)}
                </Text>
              )}
            </GlassCard>
          )}

          {/* Insurance Records */}
          {gcResolved && (
            <View style={s.sectionHeader}>
              <Text style={s.sectionTitle}>Insurance Coverage</Text>
            </View>
          )}

          {gcResolved && records.length === 0 && (
            <GlassCard style={s.emptyCard}>
              <Shield size={36} strokeWidth={1} color={colors.text.subtle} />
              <Text style={s.emptyText}>No Insurance Records</Text>
              <Text style={s.emptySubtext}>
                Tap "Refresh from DOB" to pull insurance data from the DOB Licensing Portal.
              </Text>
            </GlassCard>
          )}

          {gcResolved && records.map((rec, idx) => {
            const expColor = getExpirationColor(rec.expiration_date);
            const label = INSURANCE_LABELS[rec.insurance_type] || rec.insurance_type;
            const isCurrent = rec.is_current;
            return (
              <GlassCard key={`ins-${idx}`} style={s.insuranceCard}>
                <View style={s.insuranceHeader}>
                  <View style={[s.insuranceDot, { backgroundColor: expColor }]} />
                  <Text style={s.insuranceType}>{label}</Text>
                  {isCurrent ? (
                    <View style={s.currentBadge}>
                      <Text style={s.currentBadgeText}>Current</Text>
                    </View>
                  ) : (
                    <View style={[s.currentBadge, { borderColor: '#ef444440', backgroundColor: '#ef444410' }]}>
                      <Text style={[s.currentBadgeText, { color: '#ef4444' }]}>Expired</Text>
                    </View>
                  )}
                </View>
                <View style={s.insuranceDetails}>
                  <View style={s.insuranceRow}>
                    <Text style={s.insuranceLabel}>Effective</Text>
                    <Text style={s.insuranceValue}>{formatDate(rec.effective_date)}</Text>
                  </View>
                  <View style={s.insuranceRow}>
                    <Text style={s.insuranceLabel}>Expiration</Text>
                    <Text style={[s.insuranceValue, { color: expColor, fontWeight: '600' }]}>
                      {formatDate(rec.expiration_date)}
                    </Text>
                  </View>
                </View>
              </GlassCard>
            );
          })}

          {/* Refresh button */}
          {gcResolved && (
            <GlassButton
              title={refreshing ? 'Refreshing...' : 'Refresh from DOB'}
              icon={refreshing
                ? <ActivityIndicator size={16} color={colors.text.primary} />
                : <RefreshCw size={16} strokeWidth={1.5} color={colors.text.primary} />
              }
              onPress={handleRefresh}
              disabled={refreshing}
              style={s.refreshBtn}
            />
          )}

          {/* Last verified */}
          {gcResolved && data?.gc_last_verified && (
            <View style={s.verifiedRow}>
              <Clock size={12} color={colors.text.subtle} />
              <Text style={s.verifiedText}>
                Last verified: {formatDate(data.gc_last_verified)}
              </Text>
            </View>
          )}

          <View style={{ height: 100 }} />
        </ScrollView>

        <FloatingNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
    container: { flex: 1 },
    loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center', gap: spacing.md },
    loadingText: { fontSize: 13, color: colors.text.muted },
    header: {
      flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
      paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
      borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.08)',
    },
    headerLeft: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    scroll: { flex: 1 },
    scrollContent: { padding: spacing.lg, paddingBottom: 120 },
    pageTitle: { fontSize: 24, fontWeight: '200', color: colors.text.primary, letterSpacing: -0.5 },
    pageSubtitle: { fontSize: 14, color: colors.text.muted, marginBottom: spacing.lg },

    warningCard: { backgroundColor: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.25)', marginBottom: spacing.lg },
    warningRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
    warningText: { fontSize: 14, color: '#f59e0b', flex: 1, lineHeight: 20 },

    licenseCard: { marginBottom: spacing.lg },
    licenseHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
    licenseNumber: { fontSize: 18, fontWeight: '600', color: colors.text.primary },
    licenseStatus: { fontSize: 13, fontWeight: '500', marginTop: 2 },
    licenseDetail: { fontSize: 13, color: colors.text.muted, marginTop: 6 },

    sectionHeader: { marginBottom: spacing.md },
    sectionTitle: { fontSize: 12, fontWeight: '600', color: colors.text.muted, textTransform: 'uppercase', letterSpacing: 1 },

    emptyCard: { alignItems: 'center', paddingVertical: spacing.xl, gap: spacing.sm, marginBottom: spacing.lg },
    emptyText: { fontSize: 16, fontWeight: '500', color: colors.text.primary },
    emptySubtext: { fontSize: 13, color: colors.text.muted, textAlign: 'center', maxWidth: 280 },

    insuranceCard: { marginBottom: spacing.md },
    insuranceHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
    insuranceDot: { width: 10, height: 10, borderRadius: 5 },
    insuranceType: { fontSize: 15, fontWeight: '500', color: colors.text.primary, flex: 1 },
    currentBadge: {
      paddingHorizontal: 8, paddingVertical: 2, borderRadius: borderRadius.full,
      borderWidth: 1, borderColor: '#22c55e40', backgroundColor: '#22c55e10',
    },
    currentBadgeText: { fontSize: 10, fontWeight: '600', color: '#22c55e', textTransform: 'uppercase' },
    insuranceDetails: { gap: 6 },
    insuranceRow: { flexDirection: 'row', justifyContent: 'space-between' },
    insuranceLabel: { fontSize: 13, color: colors.text.muted },
    insuranceValue: { fontSize: 13, color: colors.text.primary },

    refreshBtn: { marginTop: spacing.md },
    verifiedRow: { flexDirection: 'row', alignItems: 'center', gap: 6, justifyContent: 'center', marginTop: spacing.md },
    verifiedText: { fontSize: 11, color: colors.text.subtle },
  });
}
