import React, { useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { RefreshCw } from 'lucide-react-native';
import GlassButton from './GlassButton';
import { useDatabaseContext as useDatabase } from '../context/DatabaseContext';
import { useNetworkStatus } from '../hooks/useNetworkStatus';
import { useToast } from './Toast';
import { colors, spacing, typography, borderRadius } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';

export default function SyncButton({ showLabel = true, size = 'md' }) {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  const { performSync, isSyncing, lastSyncTime, queueStatus } = useDatabase();
  const { isOnline } = useNetworkStatus();
  const toast = useToast();
  const [isRotating, setIsRotating] = useState(false);

  const handleSync = async () => {
    if (!isOnline) {
      toast.error('Offline', 'Cannot sync while offline');
      return;
    }

    if (isSyncing) {
      return;
    }

    setIsRotating(true);
    
    const result = await performSync();
    
    setTimeout(() => setIsRotating(false), 500);

    if (result.success) {
      toast.success('Synced', 'All data synchronized');
    } else {
      toast.error('Sync Failed', result.error || 'Could not sync data');
    }
  };

  const getLastSyncText = () => {
    if (!lastSyncTime) return 'Never synced';
    
    const now = new Date();
    const diff = now - lastSyncTime;
    const minutes = Math.floor(diff / 60000);
    
    if (minutes < 1) return 'Just now';
    if (minutes === 1) return '1 min ago';
    if (minutes < 60) return `${minutes} mins ago`;
    
    const hours = Math.floor(minutes / 60);
    if (hours === 1) return '1 hour ago';
    if (hours < 24) return `${hours} hours ago`;
    
    return 'Over a day ago';
  };

  if (!showLabel) {
    // Icon-only button
    return (
      <GlassButton
        variant="icon"
        icon={
          isSyncing ? (
            <ActivityIndicator size="small" color={colors.text.primary} />
          ) : (
            <RefreshCw 
              size={20} 
              strokeWidth={1.5} 
              color={isOnline ? colors.text.primary : colors.text.secondary}
              style={isRotating ? { transform: [{ rotate: '360deg' }] } : {}}
            />
          )
        }
        onPress={handleSync}
        disabled={!isOnline || isSyncing}
      />
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.info}>
        <Text style={[styles.infoText, { color: colors.text.secondary }]}>
          Last sync: {getLastSyncText()}
        </Text>
        {queueStatus.size > 0 && (
          <Text style={styles.queueText}>
            {queueStatus.size} pending change{queueStatus.size !== 1 ? 's' : ''}
          </Text>
        )}
      </View>

      {/* title=, NOT children. GlassButton renders {title} in its own <Text>
          and never reads children, so the label was discarded and this
          rendered as an icon beside an EMPTY text slot - not an icon-only
          control, just a default-variant button missing its title.
          The variant here is a filled action (GlassButton special-cases "icon" and the filled variants).

          It matters most when disabled: the button greys out offline, and
          with no label there was nothing telling anyone why it would not
          respond. */}
      <GlassButton
        variant="filled"
        title={isSyncing ? 'Syncing...' : 'Sync Now'}
        icon={
          isSyncing ? (
            <ActivityIndicator size="small" color={colors.onPrimary} />
          ) : (
            <RefreshCw 
              size={18} 
              strokeWidth={1.5} 
              color={colors.onPrimary}
            />
          )
        }
        onPress={handleSync}
        disabled={!isOnline || isSyncing}
      />
    </View>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  // The concept draws the sync line as one card: the status on the left, the action on the right.
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    paddingVertical: spacing.sm + 2,
    paddingHorizontal: spacing.md - 4,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.glass.border,
    backgroundColor: colors.glass.background,
  },
  info: {
    flex: 1,
    flexShrink: 1,
    gap: spacing.xs,
  },
  infoText: {
    fontSize: typography.sizes.sm,
  },
  queueText: {
    fontSize: typography.sizes.xs,
    color: colors.warning,
    fontWeight: '600',
  },
  });
}