import { Home } from 'lucide-react-native';
import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  Users,
  Building2,
  Clock,
  MapPin,
  LogOut,
  RefreshCw,
} from 'lucide-react-native';
import AnimatedBackground from '../../src/components/AnimatedBackground';
import { GlassCard, StatCard, IconPod, GlassListItem } from '../../src/components/GlassCard';
import GlassButton from '../../src/components/GlassButton';
import { GlassSkeleton, StatCardSkeleton } from '../../src/components/GlassSkeleton';
import { useToast } from '../../src/components/Toast';
import { useAuth } from '../../src/context/AuthContext';
import { checkinsAPI } from '../../src/utils/api';
import { spacing, borderRadius, typography } from '../../src/styles/theme';
import { useTheme } from '../../src/context/ThemeContext';

export default function SiteCheckInsScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { user, logout, isAuthenticated, isLoading: authLoading, siteMode, siteProject } = useAuth();
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [checkins, setCheckins] = useState([]);
  const [stats, setStats] = useState({ total: 0, active: 0 });

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      router.replace('/login');
    } else if (!siteMode) {
      router.replace('/');
    }
  }, [isAuthenticated, authLoading, siteMode]);

  // Fetch data
  useEffect(() => {
    if (isAuthenticated && siteMode && siteProject?.id) {
      fetchData();
    }
  }, [isAuthenticated, siteMode, siteProject]);

  const fetchData = async () => {
    if (!siteProject?.id) return;
    
    setLoading(true);
    try {
      const todayCheckins = await checkinsAPI.getTodayByProject(siteProject.id);
      const checkinList = Array.isArray(todayCheckins) ? todayCheckins : [];
      setCheckins(checkinList);
      
      const activeCount = checkinList.filter(c => !c.check_out_time).length;
      setStats({
        total: checkinList.length,
        active: activeCount,
      });
    } catch (error) {
      console.error('Failed to fetch check-ins:', error);
      toast.error('Load Error', 'Could not load check-in data');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchData();
    setRefreshing(false);
    toast.success('Refreshed', 'Check-in data updated');
  };

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const formatTime = (dateStr) => {
    if (!dateStr) return '--:--';
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '--:--';
    return d.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'America/New_York',
    });
  };

  const getWorkerInfo = (checkin) => ({
    name: checkin.worker_name || checkin.workerName || checkin.name || 'Unknown Worker',
    trade: checkin.worker_trade || checkin.workerTrade || checkin.trade || 'General',
    company: checkin.worker_company || checkin.workerCompany || checkin.company || 'Unknown Company',
    project: checkin.project_name || checkin.projectName || 'Unknown Project',
    checkInTime: checkin.check_in_time || checkin.checkInTime || checkin.checkin_time,
    checkOutTime: checkin.check_out_time || checkin.checkOutTime || checkin.checkout_time,
  });

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
  <View style={s.headerLeft}>
    <GlassButton
      variant="icon"
      icon={<Home size={20} strokeWidth={1.5} color={colors.text.primary} />}
      onPress={() => router.push('/site')}
    />
    <View style={s.siteBadge}>
      <Building2 size={14} strokeWidth={1.5} color="#4ade80" />
      <Text style={s.siteBadgeText}>SITE DEVICE</Text>
    </View>
    <Text style={s.projectName} numberOfLines={1}>
      {siteProject?.name || 'Project'}
    </Text>
  </View>
  <GlassButton
    variant="icon"
    icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
    onPress={handleLogout}
  />
</View>

        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <View style={s.titleRow}>
              <Text style={s.titleLabel}>TODAY'S</Text>
              <GlassButton
                variant="icon"
                icon={<RefreshCw size={16} strokeWidth={1.5} color={colors.text.muted} />}
                onPress={handleRefresh}
                style={s.refreshBtn}
              />
            </View>
            <Text style={s.titleText}>Check-Ins</Text>
          </View>

          {/* Stats */}
          <View style={s.statsRow}>
            {loading ? (
              <>
                <StatCardSkeleton style={s.statCard} />
                <StatCardSkeleton style={s.statCard} />
              </>
            ) : (
              <>
                <StatCard style={s.statCard}>
                  <Text style={s.statLabel}>TOTAL TODAY</Text>
                  <Text style={s.statValue}>{stats.total}</Text>
                </StatCard>
                <StatCard style={s.statCard}>
                  <View style={s.activeIndicator}>
                    <View style={s.activeDot} />
                    <Text style={s.statLabel}>ON-SITE NOW</Text>
                  </View>
                  <Text style={[s.statValue, s.activeValue]}>{stats.active}</Text>
                </StatCard>
              </>
            )}
          </View>

          {/* Check-ins List */}
          {loading ? (
            <>
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} style={s.mb12} />
              <GlassSkeleton width="100%" height={80} borderRadiusValue={borderRadius.xl} />
            </>
          ) : checkins.length > 0 ? (
            <View style={s.checkinsList}>
              {checkins.map((checkin, index) => {
                const workerInfo = getWorkerInfo(checkin);
                const initials = workerInfo.name
                  .split(' ')
                  .map((n) => n[0])
                  .join('')
                  .toUpperCase();

                return (
                  <GlassListItem 
                    key={checkin._id || checkin.id || index} 
                    style={s.checkinCard}
                  >
                    {/* Time */}
                    <View style={s.timeSection}>
                      <Text style={s.timeText}>{formatTime(workerInfo.checkInTime)}</Text>
                      {workerInfo.checkOutTime && (
                        <Text style={s.timeOutText}>Out: {formatTime(workerInfo.checkOutTime)}</Text>
                      )}
                    </View>

                    <View style={s.divider} />

                    {/* Worker Info */}
                    <View style={s.workerInfo}>
                      <View style={s.workerHeader}>
                        <View style={s.avatar}>
                          <Text style={s.avatarText}>{initials}</Text>
                        </View>
                        <View style={s.workerDetails}>
                          <Text style={s.workerName}>{workerInfo.name}</Text>
                          <Text style={s.workerTrade}>{workerInfo.trade}</Text>
                        </View>
                      </View>
                      <View style={s.workerMeta}>
                        <View style={s.metaItem}>
                          <Building2 size={12} strokeWidth={1.5} color={colors.text.subtle} />
                          <Text style={s.metaText}>{workerInfo.company}</Text>
                        </View>
                      </View>
                    </View>

                    {/* Status */}
                    <View
                      style={[
                        s.statusBadge,
                        !workerInfo.checkOutTime && s.statusActive,
                      ]}
                    >
                      {!workerInfo.checkOutTime ? (
                        <>
                          <View style={s.statusDot} />
                          <Text style={s.statusText}>ON-SITE</Text>
                        </>
                      ) : (
                        <>
                          <Clock size={12} strokeWidth={1.5} color={colors.text.subtle} />
                          <Text style={[s.statusText, s.statusDone]}>DONE</Text>
                        </>
                      )}
                    </View>
                  </GlassListItem>
                );
              })}
            </View>
          ) : (
            <GlassCard style={s.emptyCard}>
              <IconPod size={64}>
                <Users size={28} strokeWidth={1.5} color={colors.text.muted} />
              </IconPod>
              <Text style={s.emptyTitle}>No Check-Ins Today</Text>
              <Text style={s.emptyText}>
                Workers will appear here when they check in to this project.
              </Text>
            </GlassCard>
          )}
        </ScrollView>

      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.08)',
  },
  headerLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    flex: 1,
  },
  siteBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: 'rgba(74, 222, 128, 0.3)',
  },
  siteBadgeText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#4ade80',
    letterSpacing: 0.5,
  },
  projectName: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
    flex: 1,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 120,
  },
  titleSection: {
    marginBottom: spacing.lg,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
  },
  refreshBtn: {
    padding: spacing.xs,
  },
  titleText: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
  },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
    padding: spacing.lg,
  },
  statLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.xs,
  },
  statValue: {
    fontSize: 36,
    fontWeight: '200',
    color: colors.text.primary,
  },
  activeIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  activeDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#4ade80',
  },
  activeValue: {
    color: '#4ade80',
  },
  mb12: {
    marginBottom: spacing.sm + 4,
  },
  checkinsList: {
    gap: spacing.sm,
  },
  checkinCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  timeSection: {
    minWidth: 60,
    alignItems: 'center',
  },
  timeText: {
    fontSize: 16,
    fontWeight: '600',
    color: colors.text.primary,
  },
  timeOutText: {
    fontSize: 11,
    color: colors.text.muted,
    marginTop: 2,
  },
  divider: {
    width: 1,
    height: 40,
    backgroundColor: colors.glass.border,
  },
  workerInfo: {
    flex: 1,
    gap: spacing.xs,
  },
  workerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.text.primary,
  },
  workerDetails: {
    flex: 1,
  },
  workerName: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerTrade: {
    fontSize: 12,
    color: colors.text.muted,
  },
  workerMeta: {
    flexDirection: 'row',
    gap: spacing.md,
    marginLeft: 44,
  },
  metaItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  metaText: {
    fontSize: 11,
    color: colors.text.subtle,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    backgroundColor: 'rgba(100, 116, 139, 0.2)',
    borderRadius: borderRadius.full,
  },
  statusActive: {
    backgroundColor: 'rgba(74, 222, 128, 0.15)',
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#4ade80',
  },
  statusText: {
    fontSize: 10,
    fontWeight: '600',
    color: '#4ade80',
    letterSpacing: 0.5,
  },
  statusDone: {
    color: colors.text.subtle,
  },
  emptyCard: {
    alignItems: 'center',
    paddingVertical: spacing.xxl,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '500',
    color: colors.text.primary,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
  },
  emptyText: {
    fontSize: 14,
    color: colors.text.muted,
    textAlign: 'center',
    maxWidth: 260,
  },
});
}
