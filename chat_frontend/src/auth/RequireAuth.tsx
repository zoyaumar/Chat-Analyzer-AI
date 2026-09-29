import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./useAuth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, initialised, sessionExpired } = useAuth();
  const location = useLocation();

  // The refresh cookie is still being checked (gap S9): a blank moment beats
  // bouncing a signed-in user through the login page on every reload.
  if (!initialised) {
    return null;
  }

  if (!isAuthenticated) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname, expired: sessionExpired }}
      />
    );
  }
  return children;
}
