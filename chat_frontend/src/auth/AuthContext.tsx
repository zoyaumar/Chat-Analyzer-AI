import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { setUnauthorizedHandler } from "../api";
import { AuthContext } from "./context";
import {
  clearStoredToken,
  getTokenExpiration,
  getTokenUserId,
  getValidStoredToken,
  setStoredToken,
} from "./token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [token, setToken] = useState(getValidStoredToken);
  const [sessionExpired, setSessionExpired] = useState(false);

  const endSession = useCallback(
    (expired: boolean) => {
      clearStoredToken();
      setToken(null);
      setSessionExpired(expired);
      navigate("/login", { replace: true });
    },
    [navigate]
  );

  const signIn = useCallback((newToken: string) => {
    setStoredToken(newToken);
    setSessionExpired(false);
    setToken(newToken);
  }, []);

  const signOut = useCallback(() => endSession(false), [endSession]);

  useEffect(() => {
    if (!token) {
      setUnauthorizedHandler(null);
      return;
    }

    const handleUnauthorized = () => endSession(true);
    const expiresAt = getTokenExpiration(token);
    if (expiresAt === null || expiresAt <= Date.now()) {
      endSession(true);
      return;
    }

    setUnauthorizedHandler(handleUnauthorized);
    const timer = window.setTimeout(handleUnauthorized, expiresAt - Date.now());
    return () => {
      window.clearTimeout(timer);
      setUnauthorizedHandler(null);
    };
  }, [endSession, token]);

  const value = useMemo(
    () => ({
      isAuthenticated: token !== null,
      sessionExpired,
      token,
      userId: getTokenUserId(token),
      signIn,
      signOut,
    }),
    [sessionExpired, signIn, signOut, token]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
