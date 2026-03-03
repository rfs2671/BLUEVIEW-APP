import React, { useEffect, useRef } from 'react';
import { View, StyleSheet, Animated } from 'react-native';
import { colors, borderRadius, spacing } from '../styles/theme';

/**
 * GlassSkeleton - Shimmer loading skeleton matching Base44 aesthetic
 */
export const GlassSkeleton = ({ width, height, style, borderRadiusValue = borderRadius.md }) => {
  const shimmerAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.loop(
      Animated.timing(shimmerAnim, {
        toValue: 1,
        duration: 1500,
        useNativeDriver: true,
      })
    ).start();
  }, []);

  const translateX = shimmerAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [-200, 200],
  });

  return (
    <View
      style={[
        { width, height, borderRadius: borderRadiusValue, backgroundColor: colors.glass.card, overflow: 'hidden' },
        style,
      ]}
    >
      <Animated.View
        style={[
          {
            ...StyleSheet.absoluteFillObject,
            backgroundColor: colors.glass.background,
            width: 100,
          },
          { transform: [{ translateX }] },
        ]}
      />
    </View>
  );
};

/**
 * StatCardSkeleton - Skeleton for stat cards
 */
export const StatCardSkeleton = () => (
  <View style={styles.statCard}>
    <GlassSkeleton width={52} height={52} borderRadiusValue={borderRadius.full} style={styles.mb24} />
    <GlassSkeleton width={60} height={36} style={styles.mb8} />
    <GlassSkeleton width={100} height={12} />
  </View>
);

/**
 * ProjectCardSkeleton - Skeleton for project cards
 */
export const ProjectCardSkeleton = () => (
  <View style={styles.projectCard}>
    <View style={styles.row}>
      <GlassSkeleton width={52} height={52} borderRadiusValue={borderRadius.full} />
      <View style={styles.projectInfo}>
        <GlassSkeleton width={160} height={18} style={styles.mb4} />
        <GlassSkeleton width={100} height={12} />
      </View>
    </View>
  </View>
);

/**
 * WorkerCardSkeleton - Skeleton for worker cards
 */
export const WorkerCardSkeleton = () => (
  <View style={styles.workerCard}>
    <View style={styles.row}>
      <GlassSkeleton width={40} height={40} borderRadiusValue={borderRadius.full} />
      <View style={styles.workerInfo}>
        <GlassSkeleton width={120} height={16} style={styles.mb4} />
        <GlassSkeleton width={80} height={12} />
      </View>
    </View>
  </View>
);

/**
 * DashboardSkeleton - Full dashboard loading skeleton
 */
export const DashboardSkeleton = () => (
  <View style={styles.dashboardSkeleton}>
    <View style={styles.statsRow}>
      <StatCardSkeleton />
      <View style={styles.divider} />
      <StatCardSkeleton />
    </View>
    <View style={styles.mb32} />
    <ProjectCardSkeleton />
    <ProjectCardSkeleton />
    <WorkerCardSkeleton />
    <WorkerCardSkeleton />
    <WorkerCardSkeleton />
  </View>
);

const styles = StyleSheet.create({
  statCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
    flex: 1,
  },
  projectCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.lg,
    marginBottom: spacing.md,
  },
  workerCard: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  dashboardSkeleton: {
    backgroundColor: colors.glass.background,
    borderRadius: borderRadius.xxl,
    borderWidth: 1,
    borderColor: colors.glass.border,
    padding: spacing.xl,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  projectInfo: {
    flex: 1,
    marginLeft: spacing.md,
  },
  workerInfo: {
    flex: 1,
    marginLeft: spacing.md,
  },
  divider: {
    width: 1,
    height: 48,
    backgroundColor: colors.glass.border,
  },
  statsRow: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  mb4: { marginBottom: 4 },
  mb8: { marginBottom: spacing.sm },
  mb24: { marginBottom: spacing.lg },
  mb32: { marginBottom: spacing.xl },
});

export default GlassSkeleton;
