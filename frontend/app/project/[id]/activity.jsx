/**
 * MR.14 commit 3 / Phase B0.1 — Activity feed route.
 *
 * /project/{id}/activity — surfaces the v1 monitoring product's
 * signal stream for the project. Reads from the backend's
 * server-side rendered dob-logs endpoint (title/body/severity_kind/
 * action_text per row, populated via lib.dob_signal_templates).
 *
 * Phase B0.1: integrated into the LeveLog design system —
 * AnimatedBackground gradient + glass header bar + theme-aware
 * colors. The legacy /project/{id}/dob-logs route remains untouched
 * as the "raw record detail" fallback view.
 */

import React, { useEffect, useState, useMemo } from 'react';
import { View, StyleSheet, Pressable, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { ArrowLeft } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import ActivityFeed from '../../../src/components/ActivityFeed';
import { useAuth } from '../../../src/context/AuthContext';
import HeaderBrand from '../../../src/components/HeaderBrand';
import FloatingNav from '../../../src/components/FloatingNav';
import { useTheme } from '../../../src/context/ThemeContext';
import { spacing } from '../../../src/styles/theme';

export default function ActivityScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { colors } = useTheme();
  const styles = useMemo(() => buildStyles(colors), [colors]);
  const [unreadCount, setUnreadCount] = useState(0);

  useEffect(() => {
    if (authLoading) return;
    if (isAuthenticated === false) {
      const t = setTimeout(() => router.replace('/login'), 0);
      return () => clearTimeout(t);
    }
  }, [isAuthenticated, authLoading]);

  if (authLoading || !isAuthenticated) return null;

  return (
    <AnimatedBackground>
      <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
        <View style={styles.headerBar}>
          <Pressable
            onPress={() => router.back()}
            style={({ pressed }) => [
              styles.backBtn,
              pressed && { opacity: 0.65 },
            ]}
            accessibilityLabel="Go back"
            accessibilityRole="button"
          >
            <ArrowLeft size={20} color={colors.text.primary} />
          </Pressable>
          <HeaderBrand />
        </View>

        <View style={styles.feedWrap}>
          <ActivityFeed
            projectId={projectId}
            onUnreadCountChange={setUnreadCount}
          />
        </View>

        <FloatingNav unreadActivityCount={unreadCount} />
      </SafeAreaView>
    </AnimatedBackground>
  );
}

function buildStyles(colors) {
  return StyleSheet.create({
    safe: {
      flex: 1,
      // AnimatedBackground supplies the page gradient — keep this
      // transparent so the gradient bleeds through.
      backgroundColor: 'transparent',
    },
    headerBar: {
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: spacing.md,
      paddingVertical: spacing.sm,
      // Subtle glass treatment matches the rest of the app's chrome.
      backgroundColor: colors.glass.background,
      borderBottomWidth: 1,
      borderBottomColor: colors.glass.border,
    },
    backBtn: {
      width: 36,
      height: 36,
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 18,
      marginRight: spacing.sm,
    },
    feedWrap: {
      flex: 1,
    },
  });
}
