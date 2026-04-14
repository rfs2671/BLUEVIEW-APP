import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Image } from 'react-native';
import { useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  ArrowLeft,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Users,
  Building2,
  Briefcase,
  Clock,
  MapPin,
  LogOut,
} from 'lucide-react-native';
import AnimatedBackground from '../src/components/AnimatedBackground';
import { StatCard, IconPod, GlassListItem } from '../src/components/GlassCard';
import GlassButton from '../src/components/GlassButton';
import { WorkerCardSkeleton, StatCardSkeleton } from '../src/components/GlassSkeleton';
import FloatingNav from '../src/components/FloatingNav';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { useWorkers } from '../src/hooks/useWorkers';
import { useProjects } from '../src/hooks/useProjects';
import { useCheckIns } from '../src/hooks/useCheckIns';
import OfflineIndicator from '../src/components/OfflineIndicator';
import { spacing, borderRadius, typography } from '../src/styles/theme';
import { useTheme } from '../src/context/ThemeContext';

export default function WorkersScreen() {
  const { colors, isDark } = useTheme();
  const s = buildStyles(colors, isDark);
  const router = useRouter();
  const { logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [selectedDate, setSelectedDate] = useState(() => new Date());

// Use hooks for data
  const [checkInsLoading, setCheckInsLoading] = useState(true);
  const loading = checkInsLoading;
  const { projects, loading: projectsLoading } = useProjects();
  const { getTodayCheckIns } = useCheckIns();
  const [todayCheckIns, setTodayCheckIns] = useState([]);

  const formatTime = (isoString) => {
    if (!isoString) return '--:--';
    return new Date(isoString).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'America/New_York',
    });
  };

  const formatDate = (date) => {
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
  };

  const isToday = selectedDate.toDateString() === new Date().toDateString();

  const goToPreviousDay = () => {
    const newDate = new Date(selectedDate);
    newDate.setDate(newDate.getDate() - 1);
    setSelectedDate(newDate);
  };

  const goToNextDay = () => {
    const newDate = new Date(selectedDate);
    newDate.setDate(newDate.getDate() + 1);
    if (newDate <= new Date()) setSelectedDate(newDate);
  };

  // Redirect if not authenticated
  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isAuthenticated, authLoading]);

  // Fetch today's check-ins
  useEffect(() => {
  const fetchCheckIns = async () => {
    if (isAuthenticated) {
      setCheckInsLoading(true);
      const checkIns = await getTodayCheckIns(null, selectedDate);
      setTodayCheckIns(Array.isArray(checkIns) ? checkIns : []);
      setCheckInsLoading(false);
    }
  };
  fetchCheckIns();
}, [isAuthenticated, selectedDate]);

  const uniqueProjects = new Set(todayCheckIns.map((c) => c.projectName || c.projectId)).size;
  const uniqueCompanies = new Set(todayCheckIns.map((c) => c.workerCompany)).size;

  const getWorkerInfo = (checkin) => ({
    name: checkin.worker_name || checkin.workerName || checkin.name || 'Unknown Worker',
    trade: checkin.worker_trade || checkin.workerTrade || checkin.trade || 'General',
    company: checkin.worker_company || checkin.workerCompany || checkin.company || 'Unknown Company',
    project: checkin.project_name || checkin.projectName || 'Unknown Project',
    checkInTime: checkin.check_in_time || checkin.checkInTime || checkin.checkin_time,
    checkOutTime: checkin.check_out_time || checkin.checkOutTime || checkin.checkout_time,
  });

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const statItems = [
    { icon: Users, value: todayCheckIns.length, label: 'Workers' },
    { icon: Building2, value: uniqueProjects, label: 'Projects' },
    { icon: Briefcase, value: uniqueCompanies, label: 'Companies' },
  ];

  return (
    <AnimatedBackground>
      <SafeAreaView style={s.container} edges={['top']}>
        {/* Header */}
        <View style={s.header}>
          <View style={s.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            <Image source={require('../assets/logo-header.png')} style={{ width: 360, height: 96, resizeMode: 'contain' }} />
          </View>
          <View style={s.headerRight}>
            <OfflineIndicator />
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
          </View>
        </View>
          
        <ScrollView
          style={s.scrollView}
          contentContainerStyle={s.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={s.titleSection}>
            <Text style={s.titleLabel}>DAILY</Text>
            <Text style={s.titleText}>Sign-In Log</Text>
          </View>

          {/* Date Selector */}
          <View style={s.dateSelector}>
            <GlassButton
              variant="icon"
              icon={<ChevronLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={goToPreviousDay}
            />
            <View style={s.dateDisplay}>
              <Calendar size={20} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={s.dateText}>{formatDate(selectedDate)}</Text>
              {isToday && (
                <View style={s.todayBadge}>
                  <Text style={s.todayText}>TODAY</Text>
                </View>
              )}
            </View>
            <GlassButton
              variant="icon"
              icon={<ChevronRight size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={goToNextDay}
              disabled={isToday}
              style={isToday && s.disabledButton}
            />
          </View>

          {/* Stats */}
          <View style={s.statsRow}>
            {loading ? (
              <>
                <StatCardSkeleton />
                <StatCardSkeleton />
                <StatCardSkeleton />
              </>
            ) : (
              statItems.map((stat) => {
                const Icon = stat.icon;
                return (
                  <StatCard key={stat.label} style={s.statCard}>
                    <IconPod size={36} style={s.statIcon}>
                      <Icon size={16} strokeWidth={1.5} color={colors.text.secondary} />
                    </IconPod>
                    <Text style={s.statValue}>{stat.value}</Text>
                    <Text style={s.statLabel} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8}>{stat.label.toUpperCase()}</Text>
                  </StatCard>
                );
              })
            )}
          </View>

          {/* Checkins List */}
          <View style={s.checkinsList}>
            {loading ? (
              <>
                <WorkerCardSkeleton />
                <WorkerCardSkeleton />
                <WorkerCardSkeleton />
              </>
            ) : todayCheckIns.length > 0 ? (
              Object.entries(
                todayCheckIns.reduce((acc, checkin) => {
                  const info = getWorkerInfo(checkin);
                  if (!acc[info.company]) acc[info.company] = [];
                  acc[info.company].push(checkin);
                  return acc;
                }, {})
              ).map(([company, companyCheckins]) => (
                <View key={company}>
                  <Text style={s.companyHeader}>{company}</Text>
                  {companyCheckins.map((checkin, index) => {
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
                        onPress={() => {
                          const workerId = checkin.worker_id;
                          if (workerId) {
                            router.push(`/workers/${workerId}`);
                          }
                        }}
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
                              <MapPin size={12} strokeWidth={1.5} color={colors.text.subtle} />
                              <Text style={s.metaText}>{workerInfo.project}</Text>
                            </View>
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
              ))
            ) : (
              <View style={s.emptyState}>
                <Users size={48} strokeWidth={1} color={colors.text.subtle} />
                <Text style={s.emptyText}>No check-ins recorded for this date</Text>
              </View>
            )}
          </View>
        </ScrollView>

        <FloatingNav />
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
  },
  logoText: {
    ...typography.label,
    color: colors.text.muted,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.lg,
    paddingBottom: 120,
  },
  titleSection: {
    marginBottom: spacing.xl,
  },
  titleLabel: {
    ...typography.label,
    color: colors.text.muted,
    marginBottom: spacing.sm,
  },
  titleText: {
    fontSize: 48,
    fontWeight: '200',
    color: colors.text.primary,
    letterSpacing: -1,
  },
  dateSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  dateDisplay: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  dateText: {
    fontSize: 16,
    fontWeight: '500',
    color: colors.text.primary,
  },
  todayBadge: {
    backgroundColor: colors.glass.background,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    borderRadius: borderRadius.full,
  },
  todayText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  disabledButton: {
    opacity: 0.3,
  },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.lg,
  },
  statCard: {
    flex: 1,
    alignItems: 'center',
  },
  statIcon: {
    marginBottom: spacing.md,
  },
  statValue: {
    fontSize: 28,
    fontWeight: '200',
    color: colors.text.primary,
    marginBottom: spacing.xs,
  },
  statLabel: {
    ...typography.label,
    color: colors.text.muted,
    fontSize: 9,
    letterSpacing: 0.8,
  },
  checkinsList: {
    gap: spacing.sm,
  },
  companyHeader: {
    color: colors.text.muted,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 1.5,
    textTransform: 'uppercase',
    paddingVertical: 8,
    paddingHorizontal: 4,
    marginTop: 8,
  },
  checkinCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
  },
  timeSection: {
    width: 70,
    alignItems: 'center',
  },
  timeText: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.secondary,
  },
  timeOutText: {
    fontSize: 11,
    color: colors.text.subtle,
    marginTop: spacing.xs,
  },
  divider: {
    width: 1,
    height: 48,
    backgroundColor: colors.glass.border,
    marginHorizontal: spacing.md,
  },
  workerInfo: {
    flex: 1,
  },
  workerHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: borderRadius.full,
    backgroundColor: colors.glass.background,
    borderWidth: 1,
    borderColor: colors.glass.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.text.secondary,
  },
  workerDetails: {
    flex: 1,
  },
  workerName: {
    fontSize: 15,
    fontWeight: '500',
    color: colors.text.primary,
  },
  workerTrade: {
    fontSize: 13,
    color: colors.text.muted,
  },
  workerMeta: {
    flexDirection: 'row',
    gap: spacing.md,
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
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    borderColor: colors.glass.border,
  },
  statusActive: {
    backgroundColor: 'rgba(255, 255, 255, 0.1)',
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.text.secondary,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.text.muted,
  },
  statusDone: {
    color: colors.text.subtle,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: spacing.xxl * 2,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: 16,
    color: colors.text.muted,
  },
  });
}
