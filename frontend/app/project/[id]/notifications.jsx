/**
 * V2.3 Commit 7 — Notifications inbox standalone route.
 *
 * /project/{id}/notifications — full paginated view of the project's
 * in-app notifications. Operators arrive here via the "See all →"
 * link on the inline preview embedded in the project page.
 *
 * Mirrors the chrome of /project/{id}/activity (Phase B0.1 design
 * system) — AnimatedBackground + glass header bar + back button +
 * HeaderBrand + FloatingNav. The NotificationsList component in
 * mode="full" supplies the body: unread-only toggle, mark-all-read
 * button, pull-to-refresh, and per-item mark-read on click.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { View, StyleSheet, Pressable } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { ArrowLeft } from 'lucide-react-native';
import AnimatedBackground from '../../../src/components/AnimatedBackground';
import NotificationsList from '../../../src/components/NotificationsList';
import { useAuth } from '../../../src/context/AuthContext';
import HeaderBrand from '../../../src/components/HeaderBrand';
import FloatingNav from '../../../src/components/FloatingNav';
import { useTheme } from '../../../src/context/ThemeContext';
import { spacing } from '../../../src/styles/theme';

export default function NotificationsScreen() {
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

        <View style={styles.listWrap}>
          <NotificationsList
            projectId={projectId}
            mode="full"
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
    listWrap: {
      flex: 1,
      padding: spacing.md,
    },
  });
}
