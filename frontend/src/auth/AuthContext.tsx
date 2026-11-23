/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { logout, restoreSession, SESSION_ENDED } from '../api/authApi';
import type { AuthSuccessResponse, AuthUser } from '../types/auth';

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  establishSession: (payload: AuthSuccessResponse) => void;
  signOut: () => Promise<void>;
  reloadSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const reloadSession = useCallback(async () => {
    setLoading(true);
    try {
      const nextUser = await restoreSession();
      setUser(nextUser);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const clearSession = () => {
      setUser(null);
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'setup-status' });
    };
    window.addEventListener(SESSION_ENDED, clearSession);
    void reloadSession();
    return () => window.removeEventListener(SESSION_ENDED, clearSession);
  }, [queryClient, reloadSession]);

  const establishSession = useCallback((payload: AuthSuccessResponse) => {
    setUser(payload.user);
    setLoading(false);
  }, []);

  const signOut = useCallback(async () => {
    setLoading(true);
    try {
      await logout();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      establishSession,
      signOut,
      reloadSession,
    }),
    [establishSession, loading, reloadSession, signOut, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider.');
  }
  return context;
}
