import React, { useState, useRef, useEffect } from 'react';
import SyncIconButton from './SyncIconButton';
import { useDatabaseContext as useDatabase } from '../context/DatabaseContext';
import { useNetworkStatus } from '../hooks/useNetworkStatus';
import { useToast } from './Toast';

/**
 * The dashboard's sync control: a small icon button. It spins while the sync
 * runs and turns green when it is done, so success needs no message. Failures
 * still get a toast, because those have to say what went wrong.
 */
export default function SyncButton({ onSyncComplete, style }) {
  const { performSync, isSyncing, queueStatus } = useDatabase();
  const { isOnline } = useNetworkStatus();
  const toast = useToast();
  const [status, setStatus] = useState('idle');
  const timer = useRef(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const settle = (next) => {
    setStatus(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setStatus('idle'), 2200);
  };

  const handleSync = async () => {
    if (!isOnline) {
      toast.error('Offline', 'Cannot sync while offline');
      settle('error');
      return;
    }
    if (isSyncing) return;

    setStatus('syncing');
    let result;
    try {
      result = await performSync();
    } catch (e) {
      result = { success: false, error: e && e.message };
    }

    if (result && result.success) {
      settle('success');
      if (typeof onSyncComplete === 'function') {
        try { onSyncComplete(); } catch (_e) { /* the sync itself succeeded */ }
      }
    } else {
      settle('error');
      toast.error('Sync Failed', (result && result.error) || 'Could not sync data');
    }
  };

  return (
    <SyncIconButton
      status={isSyncing && status === 'idle' ? 'syncing' : status}
      onPress={handleSync}
      disabled={!isOnline}
      size={44}
      badge={queueStatus ? queueStatus.size : 0}
      accessibilityLabel="Sync now"
      style={style}
    />
  );
}
