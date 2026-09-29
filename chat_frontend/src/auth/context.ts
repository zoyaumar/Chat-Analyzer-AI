import { createContext } from "react";

export interface AuthContextValue {
  isAuthenticated: boolean;
  /**
   * False while the boot refresh is still proving whether a session exists
   * (gap S9): `RequireAuth` holds the gate closed instead of flashing the
   * login page at a visitor whose refresh cookie is perfectly valid.
   */
  initialised: boolean;
  sessionExpired: boolean;
  token: string | null;
  userId: number | null;
  signIn: (token: string) => void;
  signOut: () => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
