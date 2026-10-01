import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { logoutUser, refreshSession } from "../api";
import { setSessionRefresher, setUnauthorizedHandler } from "../apiClient";
import { AuthContext } from "./context";
import {
  clearAccessToken,
  getAccessToken,
  getValidAccessToken,
  getTokenExpiration,
  getTokenUserId,
  setAccessToken,
  takeLegacyToken,
} from "./token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  // A valid in-memory token (a test seed, a hot reload) is a session from the
  // first paint; anything else must be *proven* by the boot refresh, so
  // `initialised` stays false until it answers — no login flash for a visitor
  // whose refresh cookie is perfectly valid.
  const [token, setToken] = useState<string | null>(() => getValidAccessToken());
  const [initialised, setInitialised] = useState<boolean>(
    () => getValidAccessToken() !== null
  );
  const [sessionExpired, setSessionExpired] = useState(false);
  // Single-flight: the boot refresh, the expiry timer and any mid-request 401
  // share one promise — rotating the refresh cookie twice in parallel would
  // strand one of them on a spent token.
  const refreshInFlight = useRef<Promise<boolean> | null>(null);

  const endSession = useCallback(
    (expired: boolean) => {
      clearAccessToken();
      setToken(null);
      setInitialised(true);
      setSessionExpired(expired);
      navigate("/login", { replace: true });
    },
    [navigate]
  );

  /**
   * Spend the refresh cookie for a new access token — once at a time, for any
   * caller. Resolves `true` only when a new token is in memory; `false` never
   * logs anyone out by itself, because *who* asked decides that (boot failure
   * is "not signed in", a mid-session failure is an expiry).
   */
  const renewSession = useCallback((): Promise<boolean> => {
    if (refreshInFlight.current) return refreshInFlight.current;
    const before = getAccessToken();
    refreshInFlight.current = (async () => {
      try {
        const { access_token: fresh } = await refreshSession();
        setAccessToken(fresh);
        setToken(fresh);
        setInitialised(true);
        setSessionExpired(false);
        return true;
      } catch {
        setInitialised(true);
        // A refresh that lost the race with a fresh login must not clear the
        // session the login just created — only the session it started with.
        if (getAccessToken() === before) {
          clearAccessToken();
          setToken(null);
          if (before !== null) endSession(true);
        }
        return false;
      } finally {
        refreshInFlight.current = null;
      }
    })();
    return refreshInFlight.current;
  }, [endSession]);

  const signIn = useCallback((newToken: string) => {
    setAccessToken(newToken);
    setSessionExpired(false);
    setToken(newToken);
  }, []);

  const signOut = useCallback(() => {
    // Server first: revoking the stored refresh token is the whole point of
    // logout now. The local session ends regardless of the answer —
    // a failed revoke simply ages out with the cookie.
    void logoutUser().catch(() => undefined);
    endSession(false);
  }, [endSession]);

  // Register the renewal seams while a session is live: the API client's 401
  // rescue and its expiry handler.
  useEffect(() => {
    if (!token) {
      setSessionRefresher(null);
      setUnauthorizedHandler(null);
      return;
    }

    const handleUnauthorized = () => endSession(true);
    setSessionRefresher(renewSession);
    setUnauthorizedHandler(handleUnauthorized);

    const expiresAt = getTokenExpiration(token);
    if (expiresAt === null) {
      endSession(true);
      return;
    }
    // Renew *at* expiry instead of ending the session: the refresh cookie, not
    // this token, is the session now. A renewal that fails is a real
    // expiry — the cookie is gone with it — and lands exactly where the old
    // hard timeout did: login, with the expiry notice.
    const timer = window.setTimeout(() => {
      void renewSession().then((renewed) => {
        if (!renewed) endSession(true);
      });
    }, Math.max(0, expiresAt - Date.now()));

    return () => {
      window.clearTimeout(timer);
      setSessionRefresher(null);
      setUnauthorizedHandler(null);
    };
  }, [endSession, renewSession, token]);

  // Boot: no token in memory, so the only way in is the cookie.
  // The legacy `localStorage` copy — if any — is adopted once and deleted,
  // which migrates already-signed-in browsers off the XSS-readable storage.
  useEffect(() => {
    if (getValidAccessToken() !== null) return;
    const legacy = takeLegacyToken();
    if (legacy) {
      setToken(legacy);
      setInitialised(true);
      return;
    }
    void renewSession();
  }, [renewSession]);

  const value = useMemo(
    () => ({
      isAuthenticated: token !== null,
      initialised,
      sessionExpired,
      token,
      userId: getTokenUserId(token),
      signIn,
      signOut,
    }),
    [initialised, sessionExpired, signIn, signOut, token]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
