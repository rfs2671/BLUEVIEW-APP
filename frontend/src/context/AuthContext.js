import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import { authAPI, getToken, getStoredUser, setStoredUser, clearAuth } from '../utils/api';

const AuthContext = createContext(null);

const decodeToken = (token) => {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join('')
    );
    return JSON.parse(jsonPayload);
  } catch (e) {
    return null;
  }
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [siteMode, setSiteMode] = useState(false);
  const [siteProject, setSiteProject] = useState(null);

  // Guard: when true, the 401 interceptor should NOT wipe auth
  const isValidatingRef = useRef(false);

  useEffect(() => {
    validateSession();
  }, []);

  const validateSession = async () => {
    isValidatingRef.current = true;
    try {
      const token = await getToken();
      const storedUser = await getStoredUser();

      if (!token || token.split('.').length !== 3) {
        throw new Error('Invalid or missing token format');
      }

      const payload = decodeToken(token);
      if (payload && payload.exp && payload.exp * 1000 < Date.now()) {
        console.log('Session expired - performing auto-cleanup');
        throw new Error('Token expired');
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

          // Network / 500 / timeout → trust stored user for offline use
          console.log('Network error during validation, using stored user:', apiError.message);
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
        }
      } else {
        throw new Error('No stored session');
      }
    } catch (error) {
      console.error('Auth cleanup triggered:', error.message);
      await clearAuth();
      setUser(null);
      setIsAuthenticated(false);
      setSiteMode(false);
      setSiteProject(null);
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
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated,
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
