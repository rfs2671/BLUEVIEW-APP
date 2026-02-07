import { useState, useEffect } from 'react';
import NetInfo from '@react-native-community/netinfo';

export function useNetworkStatus() {
  const [isOnline, setIsOnline] = useState(true);
  const [connectionType, setConnectionType] = useState('unknown');

  useEffect(() => {
    // Get initial state
    NetInfo.fetch().then(state => {
      setIsOnline(state.isConnected && state.isInternetReachable !== false);
      setConnectionType(state.type);
    });

    // Subscribe to network state updates
    const unsubscribe = NetInfo.addEventListener(state => {
      setIsOnline(state.isConnected && state.isInternetReachable !== false);
      setConnectionType(state.type);
    });

    return () => unsubscribe();
  }, []);

  return {
    isOnline,
    connectionType,
    isWifi: connectionType === 'wifi',
    isCellular: connectionType === 'cellular',
  };
}
