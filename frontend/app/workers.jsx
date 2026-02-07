import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable } from 'react-native';
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
import { colors, spacing, borderRadius, typography } from '../src/styles/theme';

export default function WorkersScreen() {
  const router = useRouter();
  const { logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [selectedDate, setSelectedDate] = useState(new Date());

// Use hooks for data
  const { workers, loading: workersLoading } = useWorkers();
  const { projects, loading: projectsLoading } = useProjects();
  const { getTodayCheckIns } = useCheckIns();
  const [todayCheckIns, setTodayCheckIns] = useState([]);
  const loading = workersLoading || projectsLoading;

  const formatTime = (isoString) => {
    if (!isoString) return '--:--';
    return new Date(isoString).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
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
      const checkIns = await getTodayCheckIns();
      setTodayCheckIns(checkIns);
    }
  };
  fetchCheckIns();
}, [isAuthenticated, selectedDate]);

  const uniqueProjects = new Set(todayCheckIns.map((c) => c.projectName || c.projectId)).size;
  const uniqueCompanies = new Set(todayCheckIns.map((c) => c.workerCompany)).size;

  const getWorkerInfo = (checkin) => ({
    name: checkin.worker_name || checkin.name || 'Unknown Worker',
    trade: checkin.worker_trade || checkin.trade || 'General',
    company: checkin.worker_company || checkin.company || 'Unknown Company',
    project: checkin.project_name || 'Unknown Project',
    checkInTime: checkin.check_in_time || checkin.checkin_time,
    checkOutTime: checkin.check_out_time || checkin.checkout_time,
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
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.headerLeft}>
            <GlassButton
              variant="icon"
              icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={() => router.push('/')}
            />
            <Text style={styles.logoText}>BLUEVIEW</Text>
          </View>
          <View style={styles.headerRight}>
            <OfflineIndicator />
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
          </View>
        </View>
          
        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Title */}
          <View style={styles.titleSection}>
            <Text style={styles.titleLabel}>DAILY</Text>
            <Text style={styles.titleText}>Sign-In Log</Text>
          </View>

          {/* Date Selector */}
          <View style={styles.dateSelector}>
            <GlassButton
              variant="icon"
              icon={<ChevronLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={goToPreviousDay}
            />
            <View style={styles.dateDisplay}>
              <Calendar size={20} strokeWidth={1.5} color={colors.text.muted} />
              <Text style={styles.dateText}>{formatDate(selectedDate)}</Text>
              {isToday && (
                <View style={styles.todayBadge}>
                  <Text style={styles.todayText}>TODAY</Text>
                </View>
              )}
            </View>
            <GlassButton
              variant="icon"
              icon={<ChevronRight size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={goToNextDay}
              disabled={isToday}
              style={isToday && styles.disabledButton}
            />
          </View>

          {/* Stats */}
          <View style={styles.statsRow}>
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
                  <StatCard key={stat.label} style={styles.statCard}>
                    <IconPod size={44} style={styles.statIcon}>
                      <Icon size={18} strokeWidth={1.5} color={colors.text.secondary} />
                    </IconPod>
                    <Text style={styles.statValue}>{stat.value}</Text>
                    <Text style={styles.statLabel}>{stat.label.toUpperCase()}</Text>
                  </StatCard>
                );
              })
            )}
          </View>

          {/* Checkins List */}
          <View style={styles.checkinsList}>
            {loading ? (
              <>
                <WorkerCardSkeleton />
                <WorkerCardSkeleton />
                <WorkerCardSkeleton />
              </>
            ) : todaycheckins.length > 0 ? (
              todayCheckins.map((checkin, index) => {
                const workerInfo = getWorkerInfo(checkin);
                const initials = workerInfo.name
                  .split(' ')
                  .map((n) => n[0])
                  .join('')
                  .toUpperCase();

                return (
                  <GlassListItem 
                    key={checkin._id || checkin.id || index} 
                    style={styles.checkinCard}
                    onPress={() => router.push(`/workers/${checkin.worker_id || checkin._id || checkin.id}`)}
                  >
                    {/* Time */}
                    <View style={styles.timeSection}>
                      <Text style={styles.timeText}>{formatTime(workerInfo.checkInTime)}</Text>
                      {workerInfo.checkOutTime && (
                        <Text style={styles.timeOutText}>Out: {formatTime(workerInfo.checkOutTime)}</Text>
                      )}
                    </View>

                    <View style={styles.divider} />

                    {/* Worker Info */}
                    <View style={styles.workerInfo}>
                      <View style={styles.workerHeader}>
                        <View style={styles.avatar}>
                          <Text style={styles.avatarText}>{initials}</Text>
                        </View>
                        <View style={styles.workerDetails}>
                          <Text style={styles.workerName}>{workerInfo.name}</Text>
                          <Text style={styles.workerTrade}>{workerInfo.trade}</Text>
                        </View>
                      </View>
                      <View style={styles.workerMeta}>
                        <View style={styles.metaItem}>
                          <MapPin size={12} strokeWidth={1.5} color={colors.text.subtle} />
                          <Text style={styles.metaText}>{workerInfo.project}</Text>
                        </View>
                        <View style={styles.metaItem}>
                          <Building2 size={12} strokeWidth={1.5} color={colors.text.subtle} />
                          <Text style={styles.metaText}>{workerInfo.company}</Text>
                        </View>
                      </View>
                    </View>

                    {/* Status */}
                    <View
                      style={[
                        styles.statusBadge,
                        !workerInfo.checkOutTime && styles.statusActive,
                      ]}
                    >
                      {!workerInfo.checkOutTime ? (
                        <>
                          <View style={styles.statusDot} />
                          <Text style={styles.statusText}>ON-SITE</Text>
                        </>
                      ) : (
                        <>
                          <Clock size={12} strokeWidth={1.5} color={colors.text.subtle} />
                          <Text style={[styles.statusText, styles.statusDone]}>DONE</Text>
                        </>
                      )}
                    </View>
                  </GlassListItem>
                );
              })
            ) : (
              <View style={styles.emptyState}>
                <Users size={48} strokeWidth={1} color={colors.text.subtle} />
                <Text style={styles.emptyText}>No check-ins recorded for this date</Text>
              </View>
            )}
          </View>
        </ScrollView>

        <FloatingNav />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

const styles = StyleSheet.create({
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
    fontSize: 10,
  },
  checkinsList: {
    gap: spacing.sm,
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
