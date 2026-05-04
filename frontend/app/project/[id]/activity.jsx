/**
 * MR.14 commit 3 — Activity feed route.
 *
 * /project/{id}/activity — surfaces the v1 monitoring product's
 * signal stream for the project. Reads from the backend's
 * server-side rendered dob-logs endpoint (title/body/severity_kind/
 * action_text per row, populated via lib.dob_signal_templates).
 *
 * The legacy /project/{id}/dob-logs route remains untouched as the
 * "raw record detail" fallback view; this route is the v1
 * monitoring product surface.
 */

import React, { useEffect, useState } from 'react';
import { View, StyleSheet, Pressable, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useLocalSearchParams } from 'expo-router';
import { ArrowLeft } from 'lucide-react-native';
import ActivityFeed from '../../../src/components/ActivityFeed';
import { useAuth } from '../../../src/context/AuthContext';
import HeaderBrand from '../../../src/components/HeaderBrand';
import FloatingNav from '../../../src/components/FloatingNav';
import { useTheme } from '../../../src/context/ThemeContext';

export default function ActivityScreen() {
  const router = useRouter();
  const { id: projectId } = useLocalSearchParams();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { colors } = useTheme();
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
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <View style={styles.headerBar}>
        <Pressable
          onPress={() => router.back()}
          style={styles.backBtn}
          accessibilityLabel="Go back"
          accessibilityRole="button"
        >
          <ArrowLeft size={20} color={colors?.text?.primary || '#0f172a'} />
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
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  headerBar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#e2e8f0',
  },
  backBtn: {
    padding: 8,
    borderRadius: 6,
    marginRight: 8,
  },
  feedWrap: {
    flex: 1,
  },
});
