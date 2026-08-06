import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useMemo,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * Tier 1 ③ — "Inspector Mode" device-local confinement toggle.
 *
 * A construction superintendent taps "Hand to Inspector (read-only)"
 * and hands the site_device over. While the toggle is on, the app is
 * confined to the read-only /site/logbooks tab (the route gate in
 * app/_layout.jsx enforces this). Tapping "Exit Inspector Mode" on the
 * logbooks screen restores normal navigation.
 *
 * NO PIN — deliberately. The tablet's own device lock (screen lock /
 * kiosk pinning) is the security control; this is purely a UI
 * confinement toggle, so there is no secret to store or verify.
 *
 * FRONTEND-ONLY / OTA — no native module. The single boolean flag is
 * persisted in AsyncStorage so the confinement survives an app restart
 * while the device is in the inspector's hands.
 */

const LOCKED_KEY = 'bv_inspector_locked';

const InspectorLockContext = createContext({
  isLocked: false,
  loading: true,
  lock: async () => {},
  unlock: async () => {},
});

export const InspectorLockProvider = ({ children }) => {
  const [isLocked, setIsLocked] = useState(false);
  const [loading, setLoading] = useState(true);

  // Hydrate persisted state on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const storedLocked = await AsyncStorage.getItem(LOCKED_KEY);
        if (cancelled) return;
        setIsLocked(storedLocked === '1');
      } catch (_e) {
        if (!cancelled) setIsLocked(false);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Engage the confinement.
  const lock = useCallback(async () => {
    setIsLocked(true);
    try {
      await AsyncStorage.setItem(LOCKED_KEY, '1');
    } catch (_e) {
      // Persistence is best-effort — the in-memory flag still confines
      // the current session.
    }
    return true;
  }, []);

  // Release the confinement.
  const unlock = useCallback(async () => {
    setIsLocked(false);
    try {
      await AsyncStorage.setItem(LOCKED_KEY, '0');
    } catch (_e) {
      // Best-effort — never strand the device on a storage failure.
    }
    return true;
  }, []);

  const value = useMemo(
    () => ({ isLocked, loading, lock, unlock }),
    [isLocked, loading, lock, unlock],
  );

  return (
    <InspectorLockContext.Provider value={value}>
      {children}
    </InspectorLockContext.Provider>
  );
};

export const useInspectorLock = () => useContext(InspectorLockContext);

export default InspectorLockContext;
