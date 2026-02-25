import React, { createContext, useContext, useState, useEffect } from 'react';
import { authAPI, getToken, getStoredUser, setStoredUser, clearAuth } from '../utils/api';

const AuthContext = createContext(null);

// Helper to decode JWT payload in React Native
const decodeToken = (token) => {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    // Using global.atob for RN compatibility
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

  // Check for stored auth on mount
  useEffect(() => {
    validateSession();
  }, []);

  const validateSession = async () => {
    try {
      const token = await getToken();
      const storedUser = await getStoredUser();

      // 1. Check if token exists and has valid JWT structure (3 parts)
      if (!token || token.split('.').length !== 3) {
        throw new Error('Invalid or missing token format');
      }

      // 2. Check Expiration (Auto-Cleanup)
      const payload = decodeToken(token);
      if (payload && payload.exp && payload.exp * 1000 < Date.now()) {
        console.log('Session expired - performing auto-cleanup');
        throw new Error('Token expired');
      }

      if (token && storedUser) {
        // 3. Validate with Backend
        const userData = await authAPI.getMe();
        const normalizedUser = {
          ...userData,
          full_name: userData.full_name || userData.name,
        };
        
        setUser(normalizedUser);
        await setStoredUser(normalizedUser);
        setIsAuthenticated(true);
        
        // Check site mode
        if (userData.site_mode) {
          setSiteMode(true);
          setSiteProject({
            id: userData.project_id || storedUser?.project_id,
            name: userData.project_name || storedUser?.project_name,
            ...userData.project
          });
        } else if (storedUser?.site_mode) {
          setSiteMode(true);
          setSiteProject({
            id: storedUser.project_id,
            name: storedUser.project_name,
          });
        }
    } catch (error) {
      console.error('Auth cleanup triggered:', error.message);
      await clearAuth(); // Removes token and user from storage via api utility
      setUser(null);
      setIsAuthenticated(false);
      setSiteMode(false);
      setSiteProject(null);
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (email, password) => {
    // Login returns token, utility handles storage
    await authAPI.login(email, password);
    
    // Fetch fresh user data using the new token
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
        ...userData.project
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
