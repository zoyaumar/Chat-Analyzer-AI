import { createContext } from "react";

export interface AuthContextValue {
  isAuthenticated: boolean;
  sessionExpired: boolean;
  token: string | null;
  userId: number | null;
  signIn: (token: string) => void;
  signOut: () => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
