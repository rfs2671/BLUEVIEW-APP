import React, { createContext, useContext, useState, useEffect } from 'react';
import { authAPI, getToken, getStoredUser, setStoredUser, clearAuth } from '../utils/api';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Check for stored auth on mount
  useEffect(() => {
    validateSession();
  }, []);

  const validateSession = async () => {
    try {
      const token = await getToken();
      const storedUser = await getStoredUser();

      if (token && storedUser) {
        // Validate token by fetching current user
        const userData = await authAPI.getMe();
        const normalizedUser = {
          ...userData,
          full_name: userData.full_name || userData.name,
        };
        setUser(normalizedUser);
        await setStoredUser(normalizedUser);
        setIsAuthenticated(true);
      }
    } catch (error) {
      console.error('Session validation failed:', error);
      await clearAuth();
      setUser(null);
      setIsAuthenticated(false);
    } finally {
      setIsLoading(false);
    }
  };

  const login = async (email, password) => {
    // Login returns only token, so we need to fetch user data separately
    await authAPI.login(email, password);
    
    // Fetch user data using the token
    const userData = await authAPI.getMe();
    const normalizedUser = {
      ...userData,
      full_name: userData.full_name || userData.name,
    };
    
    setUser(normalizedUser);
    await setStoredUser(normalizedUser);
    setIsAuthenticated(true);
    
    return normalizedUser;
  };

  const logout = async () => {
    await authAPI.logout();
    setUser(null);
    setIsAuthenticated(false);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated,
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
