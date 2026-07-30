import React, { createContext, useContext, useState, useEffect } from 'react';
import { getToken, getUser, setAuthSession, clearAuthSession, isTokenExpired } from '../utils/auth';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => getToken());
  const [user, setUser] = useState(() => getUser());

  const login = (data, usernameStr) => {
    setAuthSession(data, usernameStr);
    setToken(data.access_token);
    setUser(usernameStr || data.user_id || 'Admin');
  };

  const logout = () => {
    clearAuthSession();
    setToken(null);
    setUser(null);
    window.location.href = '/login';
  };

  // Periodic automatic JWT expiration & token presence check (every 10 seconds)
  useEffect(() => {
    const checkTokenStatus = () => {
      const currentToken = getToken();
      if (!currentToken || isTokenExpired(currentToken)) {
        if (token) {
          console.warn('JWT token expired or missing from storage. Logging out user immediately...');
          logout();
        }
      }
    };

    checkTokenStatus();
    const interval = setInterval(checkTokenStatus, 10000);

    return () => clearInterval(interval);
  }, [token]);

  const isAuthenticated = !!token && !isTokenExpired(token);

  return (
    <AuthContext.Provider value={{ token, user, login, logout, isAuthenticated }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
