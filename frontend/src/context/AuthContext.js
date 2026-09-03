import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import {
  authAPI, getToken, getStoredUser, setStoredUser, clearAuth,
  registerAuthRejectedHandler,
} from '../utils/api';
import { isTokenExpired } from '../utils/sessionSurvival';
import { setSentryUser, clearSentryUser } from '../lib/sentry';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [siteMode, setSiteMode] = useState(false);
  const [siteProject, setSiteProject] = useState(null);
  // READ-ONLY CACHED MODE. True when the token on disk has run out and the
  // device is running off what it already downloaded. Authenticated against
  // its own cache and nothing else — a screen that wants to refuse a WRITE
  // has to be able to tell that from a live session.
  const [isSessionExpired, setIsSessionExpired] = useState(false);

  // Guard: when true, the 401 interceptor should NOT wipe auth
  const isValidatingRef = useRef(false);

  useEffect(() => {
    validateSession();
  }, []);

  // A GENUINE 401 NOW ARRIVES HERE INSTEAD OF WAITING FOR A RESTART. api.js
  // has always said "Navigation will be handled by AuthContext" on its 401
  // arm; it was not, because this provider re-validates on mount and never
  // again. The token came off the disk mid-session and the screen carried on
  // looking fine until the next cold boot. This is that missing wire.
  useEffect(() => {
    registerAuthRejectedHandler(() => {
      setUser(null);
      setIsAuthenticated(false);
      setSiteMode(false);
      setSiteProject(null);
      setIsSessionExpired(false);
      clearSentryUser();
    });
    return () => registerAuthRejectedHandler(null);
  }, []);

  /**
   * Adopt the principal already on disk. Used by both offline paths: the
   * network-error fallback that has always existed, and the expired-token
   * path below that could never reach it.
   */
  const adoptStoredUser = (storedUser) => {
    const normalizedUser = {
      ...storedUser,
      full_name: storedUser.full_name || storedUser.name,
    };
    setUser(normalizedUser);
    setIsAuthenticated(true);

    if (storedUser?.site_mode) {
      setSiteMode(true);
      setSiteProject({
        id: storedUser.project_id,
        name: storedUser.project_name,
      });
    }
  };

  const validateSession = async () => {
    isValidatingRef.current = true;
    try {
      const token = await getToken();
      const storedUser = await getStoredUser();

      if (!token || token.split('.').length !== 3) {
        throw new Error('Invalid or missing token format');
      }

      // ── AN EXPIRY IS A REASON TO STOP FETCHING, NOT TO STOP READING ─────
      //
      // This check runs BEFORE any network call, so being offline never
      // protected it. It used to `throw new Error('Token expired')`, the
      // throw reached the outer catch, and the outer catch calls clearAuth().
      // A gate tablet 30 days offline therefore deleted its own credentials
      // — the password lives in an admin's head, not on the jobsite — and
      // then could not reach a single one of the submitted logbooks, plans
      // and documents still sitting on its disk. That is the moment a DOB
      // inspector walks in.
      //
      // The content was approved and downloaded long ago; the session running
      // out does not unapprove it. So the device stays authenticated against
      // its cache, keeps its site mode and its project, and every /site/*
      // screen — each of which redirects on `!isAuthenticated` — renders what
      // it has. `isSessionExpired` names the state so nothing mistakes it for
      // a live session.
      //
      // NO REQUEST IS MADE. A token we already know is dead can only earn a
      // 401, and a 401 is one more thing that used to end with clearAuth().
      if (isTokenExpired(token)) {
        if (!storedUser) {
          // Nothing cached: nothing to preserve and nothing to render. This
          // one really does belong at the login screen.
          throw new Error('Session expired with nothing cached');
        }
        console.log('Session expired - serving the device cache read-only');
        adoptStoredUser(storedUser);
        setIsSessionExpired(true);
        return;
      }

      if (token && storedUser) {
        try {
          const userData = await authAPI.getMe();
          const normalizedUser = {
            ...userData,
            full_name: userData.full_name || userData.name,
          };

          setUser(normalizedUser);
          await setStoredUser(normalizedUser);
          setIsAuthenticated(true);
          // The server answered, so this is a live session however it got
          // here — including a device that woke up in cached mode and then
          // found signal.
          setIsSessionExpired(false);
          // Phase C1: tag Sentry events with user_email + company.
          // No-op when Sentry isn't initialized (no DSN) — safe in dev.
          setSentryUser({
            email: normalizedUser.email,
            company_name: normalizedUser.company_name,
            role: normalizedUser.role,
          });

          if (userData.site_mode) {
            setSiteMode(true);
            setSiteProject({
              id: userData.project_id || storedUser?.project_id,
              name: userData.project_name || storedUser?.project_name,
              ...userData.project,
            });
          } else if (storedUser?.site_mode) {
            setSiteMode(true);
            setSiteProject({
              id: storedUser.project_id,
              name: storedUser.project_name,
            });
          } else {
            setSiteMode(false);
            setSiteProject(null);
          }
        } catch (apiError) {
          // 401 = token genuinely invalid → wipe and go to login
          if (apiError?.response?.status === 401) {
            throw new Error('Token rejected by server');
          }

          // Network / 500 / timeout → trust stored user for offline use.
          // OFFLINE IS NOT EXPIRED: the token here is live by its own clock,
          // so the device is not put into read-only cached mode for it.
          console.log('Network error during validation, using stored user:', apiError.message);
          adoptStoredUser(storedUser);
          setIsSessionExpired(false);
        }
      } else {
        throw new Error('No stored session');
      }
    } catch (error) {
      // ONLY THREE THINGS REACH HERE NOW, and all three are cases where the
      // device has nothing it could show: no token, a token that is not a
      // token, and an expired token with an empty cache behind it. A local
      // expiry on a device that HAS a cache no longer throws, which is the
      // whole point — that throw is what deleted the credentials.
      console.error('Auth cleanup triggered:', error.message);
      await clearAuth();
      setUser(null);
      setIsAuthenticated(false);
      setSiteMode(false);
      setSiteProject(null);
      setIsSessionExpired(false);
    } finally {
      isValidatingRef.current = false;
      setIsLoading(false);
    }
  };

  const login = async (email, password) => {
    await authAPI.login(email, password);

    const userData = await authAPI.getMe();
    const normalizedUser = {
      ...userData,
      full_name: userData.full_name || userData.name,
    };

    setUser(normalizedUser);
    await setStoredUser(normalizedUser);
    setIsAuthenticated(true);
    setIsSessionExpired(false);
    // Phase C1: tag Sentry on explicit login too (validateSession
    // covers re-loads, login covers fresh sign-ins).
    setSentryUser({
      email: normalizedUser.email,
      company_name: normalizedUser.company_name,
      role: normalizedUser.role,
    });

    if (userData.site_mode) {
      setSiteMode(true);
      setSiteProject({
        id: userData.project_id,
        name: userData.project_name,
        ...userData.project,
      });
    } else {
      setSiteMode(false);
      setSiteProject(null);
    }

    return normalizedUser;
  };

  const logout = async () => {
    try {
      await authAPI.logout();
    } catch (e) {
      console.error('Logout API call failed, clearing local state anyway');
    } finally {
      await clearAuth();
      setUser(null);
      setIsAuthenticated(false);
      setSiteMode(false);
      setSiteProject(null);
      setIsSessionExpired(false);
      // Phase C1: clear Sentry user tagging on logout so events
      // captured before the next login aren't attributed to the
      // previous user.
      clearSentryUser();
    }
  };

  // Account activation gating: pending accounts get the read-only demo. The
  // server is authoritative (cost-bearing endpoints 403 with account_pending);
  // this flag just routes the UI. Site-mode devices are never "pending".
  const isPending =
    isAuthenticated && !siteMode && user?.account_status === 'pending';

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated,
        isPending,
        // Authenticated against the device cache only: the token has run out
        // and nothing on screen came from the server this session.
        isSessionExpired,
        siteMode,
        siteProject,
        login,
        logout,
        validateSession,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export default AuthContext;
