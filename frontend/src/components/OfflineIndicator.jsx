import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { WifiOff, Wifi } from 'lucide-react-native';
import { useNetworkStatus } from '../hooks/useNetworkStatus';
import { useDatabaseContext as useDatabase } from '../context/DatabaseContext';
import { colors, spacing, typography } from '../styles/theme';
import { semantic } from '../styles/semanticColors';

export default function OfflineIndicator() {
  const { isOnline } = useNetworkStatus();
  const { queueStatus } = useDatabase();

  // Don't show anything if online and queue is empty
  if (isOnline && queueStatus.size === 0) {
    return null;
  }

  return (
    <View style={[
      styles.container,
      isOnline ? styles.containerOnline : styles.containerOffline
    ]}>
      {isOnline ? (
        <Wifi size={16} color={colors.success} strokeWidth={2} />
      ) : (
        <WifiOff size={16} color={colors.warning} strokeWidth={2} />
      )}
      
      <Text style={[
        styles.text,
        isOnline ? styles.textOnline : styles.textOffline
      ]}>
        {isOnline 
          ? queueStatus.size > 0 
            ? `Syncing ${queueStatus.size} changes...`
            : 'Online'
          : 'Working Offline'
        }
      </Text>
      
      {queueStatus.size > 0 && (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{queueStatus.size}</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: 20,
    gap: spacing.sm,
  },
  containerOffline: {
    backgroundColor: semantic.attentionBg,
    borderWidth: 1,
    borderColor: semantic.attentionBorder,
  },
  containerOnline: {
    backgroundColor: semantic.verifiedBg,
    borderWidth: 1,
    borderColor: semantic.verifiedBorder,
  },
  text: {
    fontSize: typography.small.fontSize,
    fontWeight: '600',
  },
  textOffline: {
    color: colors.status.warning,
  },
  textOnline: {
    color: colors.status.success,
  },
  badge: {
    backgroundColor: colors.warning,
    borderRadius: 10,
    minWidth: 20,
    height: 20,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 6,
  },
  badgeText: {
    color: '#000',
    fontSize: 11,
    fontWeight: '700',
  },
});
