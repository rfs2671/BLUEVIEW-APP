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
import OfflineIndicator from '../src/components/OfflineIndicator';
import { useToast } from '../src/components/Toast';
import { useAuth } from '../src/context/AuthContext';
import { useWorkers } from '../src/hooks/useWorkers';
import { useProjects } from '../src/hooks/useProjects';
import { useCheckIns } from '../src/hooks/useCheckIns';
import { colors, spacing, borderRadius, typography } from '../src/styles/theme';

export default function WorkersScreen() {
  const router = useRouter();
  const { logout, isAuthenticated, isLoading: authLoading } = useAuth();
  const toast = useToast();

  const [selectedDate, setSelectedDate] = useState(new Date());
  
  // Use hooks for data
  const { workers, loading: workersLoading } = useWorkers();
  const { projects, loading: projectsLoading } = useProjects();
  const { checkIns, loading: checkInsLoading, getTodayCheckIns } = useCheckIns();
  
  const [todayCheckIns, setTodayCheckIns] = useState([]);

  const formatTime = (timestamp) => {
    if (!timestamp) return '--:--';
    const date = typeof timestamp === 'number' ? new Date(timestamp) : new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
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
    const fetchTodayCheckIns = async () => {
      if (isAuthenticated) {
        const checkIns = await getTodayCheckIns();
        setTodayCheckIns(checkIns);
      }
    };
    fetchTodayCheckIns();
  }, [isAuthenticated, selectedDate, checkIns]);

  const handleLogout = async () => {
    await logout();
    router.replace('/login');
  };

  const loading = workersLoading || projectsLoading || checkInsLoading;

  const uniqueProjects = new Set(todayCheckIns.map((c) => c.projectName || c.projectId)).size;
  const uniqueCompanies = new Set(todayCheckIns.map((c) => c.workerCompany)).size;

  const getWorkerInfo = (checkin) => ({
    name: checkin.workerName || 'Unknown Worker',
    trade: checkin.workerTrade || 'General',
    company: checkin.workerCompany || 'Unknown Company',
    project: checkin.projectName || 'Unknown Project',
    checkInTime: checkin.checkInTime,
    checkOutTime: checkin.checkOutTime,
  });

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
          <GlassButton
            variant="icon"
            icon={<ArrowLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={() => router.back()}
          />
          <Text style={styles.headerTitle}>Workers</Text>
          <View style={styles.headerRight}>
            <OfflineIndicator />
            <GlassButton
              variant="icon"
              icon={<LogOut size={20} strokeWidth={1.5} color={colors.text.primary} />}
              onPress={handleLogout}
            />
          </View>
        </View>

        {/* Date Selector */}
        <View style={styles.dateSelector}>
          <GlassButton
            variant="icon"
            icon={<ChevronLeft size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={goToPreviousDay}
          />
          <View style={styles.dateDisplay}>
            <Calendar size={18} strokeWidth={1.5} color={colors.text.secondary} />
            <Text style={styles.dateText}>{formatDate(selectedDate)}</Text>
            {isToday && <View style={styles.todayBadge}><Text style={styles.todayText}>TODAY</Text></View>}
          </View>
          <GlassButton
            variant="icon"
            icon={<ChevronRight size={20} strokeWidth={1.5} color={colors.text.primary} />}
            onPress={goToNextDay}
            disabled={isToday}
          />
        </View>

        <ScrollView
          style={styles.scrollView}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
        >
          {/* Stats */}
          <View style={styles.statsGrid}>
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
            ) : todayCheckIns.length > 0 ? (
              todayCheckIns.map((checkin) => {
                const info = getWorkerInfo(checkin);
                const isCheckedOut = !!info.checkOutTime;

                return (
                  <GlassListItem
                    key={checkin.id}
                    title={info.name}
                    subtitle={`${info.trade} • ${info.company}`}
                    leftIcon={
                      <IconPod size={44}>
                        <Users size={18} strokeWidth={1.5} color={colors.text.secondary} />
                      </IconPod>
                    }
                    rightContent={
                      <View style={styles.timeContainer}>
                        <View style={styles.timeRow}>
                          <Clock size={14} strokeWidth={1.5} color={colors.success} />
                          <Text style={styles.timeText}>{formatTime(info.checkInTime)}</Text>
                        </View>
                        {isCheckedOut && (
                          <View style={styles.timeRow}>
                            <Clock size={14} strokeWidth={1.5} color={colors.error} />
                            <Text style={styles.timeText}>{formatTime(info.checkOutTime)}</Text>
                          </View>
                        )}
                        {!isCheckedOut && (
                          <View style={styles.activeBadge}>
                            <View style={styles.activeDot} />
                            <Text style={styles.activeText}>ACTIVE</Text>
                          </View>
                        )}
                      </View>
                    }
                    description={
                      <View style={styles.projectRow}>
                        <MapPin size={12} strokeWidth={1.5} color={colors.text.subtle} />
                        <Text style={styles.projectText}>{info.project}</Text>
                      </View>
                    }
                    onPress={() => router.push(`/workers/${checkin.workerId}`)}
                    showBorder={true}
                  />
                );
              })
            ) : (
              <View style={styles.emptyState}>
                <Users size={48} strokeWidth={1.5} color={colors.text.subtle} />
                <Text style={styles.emptyText}>No check-ins for {formatDate(selectedDate)}</Text>
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
  },
  headerTitle: {
    fontSize: typography.sizes.lg,
    fontWeight: '700',
    color: colors.text.primary,
  },
  headerRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  dateSelector: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  dateDisplay: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    backgroundColor: 'rgba(255, 255, 255, 0.05)',
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
  },
  dateText: {
    fontSize: typography.sizes.sm,
    fontWeight: '600',
    color: colors.text.primary,
  },
  todayBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    backgroundColor: colors.primary,
    borderRadius: 4,
  },
  todayText: {
    fontSize: 10,
    fontWeight: '700',
    color: '#000',
    letterSpacing: 0.5,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: spacing.lg,
    paddingBottom: 100,
  },
  statsGrid: {
    flexDirection: 'row',
    gap: spacing.md,
    marginBottom: spacing.xl,
  },
  statCard: {
    flex: 1,
  },
  statIcon: {
    marginBottom: spacing.sm,
  },
  statValue: {
    fontSize: 28,
    fontWeight: '700',
    color: colors.text.primary,
    marginBottom: 2,
  },
  statLabel: {
    fontSize: typography.sizes.xs,
    fontWeight: '600',
    color: colors.text.secondary,
    letterSpacing: 1,
  },
  checkinsList: {
    gap: spacing.md,
  },
  timeContainer: {
    alignItems: 'flex-end',
    gap: spacing.xs,
  },
  timeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  timeText: {
    fontSize: typography.sizes.xs,
    fontWeight: '600',
    color: colors.text.secondary,
  },
  activeBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 6,
    paddingVertical: 2,
    backgroundColor: 'rgba(34, 197, 94, 0.1)',
    borderRadius: 4,
  },
  activeDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.success,
  },
  activeText: {
    fontSize: 10,
    fontWeight: '700',
    color: colors.success,
    letterSpacing: 0.5,
  },
  projectRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    marginTop: spacing.xs,
  },
  projectText: {
    fontSize: typography.sizes.xs,
    color: colors.text.subtle,
  },
  emptyState: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.xl * 2,
    gap: spacing.md,
  },
  emptyText: {
    fontSize: typography.sizes.sm,
    color: colors.text.subtle,
    textAlign: 'center',
  },
});
