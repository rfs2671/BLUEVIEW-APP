import React, { useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { RefreshCw } from 'lucide-react-native';
import GlassButton from './GlassButton';
import { useDatabaseContext as useDatabase } from '../context/DatabaseContext';
import { useNetworkStatus } from '../hooks/useNetworkStatus';
import { useToast } from './Toast';
import { colors, spacing, typography, borderRadius } from '../styles/theme';
import { useTheme } from '../context/ThemeContext';
import { auraRim, auraShadow } from '../styles/aura';

export default function SyncButton({ showLabel = true, size = 'md' }) {
  const { colors, isDark } = useTheme();
  const styles = buildStyles(colors, isDark);
  const { performSync, isSyncing, queueStatus } = useDatabase();
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
    // The action sits alone in the middle of its card. The last-sync time is not shown here (the owner asked for the
    // button alone); a count of changes still waiting to upload IS shown, under the button, because it is the one thing
    // that tells someone a sync is needed.
    <View style={[styles.container, auraRim(colors), auraShadow(colors, undefined, { translucent: true })]}>

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
      {queueStatus.size > 0 && (
        <Text style={styles.queueText}>
          {queueStatus.size} pending change{queueStatus.size !== 1 ? 's' : ''}
        </Text>
      )}
    </View>
  );
}

function buildStyles(colors, isDark) {
  return StyleSheet.create({
  container: {
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    paddingVertical: spacing.md - 4,
    paddingHorizontal: spacing.md - 4,
    borderRadius: borderRadius.lg,
    backgroundColor: colors.glass.background,
  },
  queueText: {
    fontSize: typography.sizes.xs,
    color: colors.warning,
    fontWeight: '600',
  },
  });
}