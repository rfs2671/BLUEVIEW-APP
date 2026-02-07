import React, { useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import { RefreshCw } from 'lucide-react-native';
import GlassButton from './GlassButton';
import { useDatabase } from '../context/DatabaseContext';
import { useNetworkStatus } from '../hooks/useNetworkStatus';
import { useToast } from './Toast';
import { colors, spacing, typography } from '../styles/theme';

export default function SyncButton({ showLabel = true, size = 'md' }) {
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
      <GlassButton
        variant="secondary"
        icon={
          isSyncing ? (
            <ActivityIndicator size="small" color={colors.text.primary} />
          ) : (
            <RefreshCw 
              size={18} 
              strokeWidth={1.5} 
              color={isOnline ? colors.text.primary : colors.text.secondary}
            />
          )
        }
        onPress={handleSync}
        disabled={!isOnline || isSyncing}
      >
        {isSyncing ? 'Syncing...' : 'Sync Now'}
      </GlassButton>
      
      <View style={styles.info}>
        <Text style={styles.infoText}>
          Last sync: {getLastSyncText()}
        </Text>
        {queueStatus.size > 0 && (
          <Text style={styles.queueText}>
            {queueStatus.size} pending change{queueStatus.size !== 1 ? 's' : ''}
          </Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: spacing.sm,
  },
  info: {
    gap: spacing.xs,
  },
  infoText: {
    fontSize: typography.sizes.sm,
    color: colors.text.secondary,
  },
  queueText: {
    fontSize: typography.sizes.xs,
    color: colors.warning,
    fontWeight: '600',
  },
});
