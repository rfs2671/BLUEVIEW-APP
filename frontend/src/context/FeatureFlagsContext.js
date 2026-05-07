/**
 * Phase E1 — feature-flags context + provider.
 *
 * Single GET /api/feature-flags/me round-trip on app boot (and
 * again on login / logout) hydrates a per-session map of
 * {flag: bool}. Components read flags via the useFeatureFlag hook
 * (see ../hooks/useFeatureFlag.js).
 *
 * Hard rule: until the GET resolves, every flag returns false.
 * This is "fail closed during loading" — without it, v1 customers
 * would briefly see v2 surfaces flicker into view on every
 * navigation while flags are loading. False-default avoids the
 * flicker.
 *
 * Refresh triggers:
 *   • Mount (when AuthContext reports authenticated).
 *   • validateSession() / login() / logout() — re-fetch so the
 *     map reflects the new identity. Logged-out users get an
 *     empty map (every flag → false).
 */

import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useCallback,
  useRef,
} from 'react';
import apiClient from '../utils/api';
import { useAuth } from './AuthContext';

const FeatureFlagsContext = createContext({
  flags: {},
  loaded: false,
  refresh: async () => {},
});

export const FeatureFlagsProvider = ({ children }) => {
  const { isAuthenticated, isLoading: authLoading, user } = useAuth();
  const [flags, setFlags] = useState({});
  const [loaded, setLoaded] = useState(false);
  // Tracks the last user identity we fetched flags for — refetch
  // when it changes so a logout/login swap doesn't keep stale
  // per-user flag overrides.
  const lastFetchedUserIdRef = useRef(null);

  const refresh = useCallback(async () => {
    if (!isAuthenticated) {
      // Logged-out: every flag is false. Mark as loaded so
      // the hook stops returning the loading-default, but the
      // map is empty.
      setFlags({});
      setLoaded(true);
      lastFetchedUserIdRef.current = null;
      return;
    }
    try {
      const resp = await apiClient.get('/api/feature-flags/me');
      const incoming = (resp && resp.data && resp.data.flags) || {};
      setFlags(incoming);
      setLoaded(true);
      lastFetchedUserIdRef.current = (user && (user.id || user._id)) || null;
    } catch (_e) {
      // Fail closed on error — empty map. We mark loaded=true
      // so the loading-default state ends; otherwise a 500 from
      // the flags endpoint would leave the whole UI in a perpetual
      // "false" state (which is fine, but loaded=true is more
      // honest about the state).
      setFlags({});
      setLoaded(true);
    }
  }, [isAuthenticated, user]);

  useEffect(() => {
    // Wait for auth resolution before fetching — prevents a
    // burn-an-API-call race on app boot before AuthContext has
    // figured out whether the user is logged in.
    if (authLoading) return;

    const currentUserId = (user && (user.id || user._id)) || null;
    if (lastFetchedUserIdRef.current !== currentUserId) {
      // Identity changed (or first mount). Refetch.
      refresh();
    }
  }, [authLoading, isAuthenticated, user, refresh]);

  const value = useMemo(
    () => ({ flags, loaded, refresh }),
    [flags, loaded, refresh],
  );

  return (
    <FeatureFlagsContext.Provider value={value}>
      {children}
    </FeatureFlagsContext.Provider>
  );
};

/** Internal accessor — components should use the
 *  useFeatureFlag hook for per-flag boolean reads, or this for
 *  the full map (rare; mostly used by debug tooling). */
export const useFeatureFlagsContext = () => useContext(FeatureFlagsContext);

export default FeatureFlagsContext;
