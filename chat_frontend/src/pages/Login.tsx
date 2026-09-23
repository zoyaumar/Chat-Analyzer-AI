import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { loginUser } from "../api";
import { useAuth } from "../auth/useAuth";

interface LoginState {
  expired?: boolean;
}

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const { sessionExpired, signIn } = useAuth();
  const wasExpired =
    sessionExpired || Boolean((location.state as LoginState | null)?.expired);

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      const response = await loginUser({ username, password });
      signIn(response.data.access_token);
      navigate("/chat");
    } catch {
      setError("Invalid username or password");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-center mt-20">
      <h1 className="text-2xl mb-4">Login</h1>

      <form onSubmit={handleLogin} className="flex flex-col gap-3 w-64">
        <input
          aria-label="Username"
          className="border p-2"
          placeholder="Username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
        />
        <input
          aria-label="Password"
          type="password"
          className="border p-2"
          placeholder="Password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <button
          type="submit"
          disabled={loading}
          className="bg-green-600 text-white px-4 py-2 rounded hover:bg-green-700 disabled:opacity-50"
        >
          {loading ? "Logging in..." : "Login"}
        </button>
      </form>

      {wasExpired && (
        <p role="status" className="text-amber-600 mt-2">
          Your session expired. Please sign in again.
        </p>
      )}
      {error && (
        <p role="alert" className="text-red-500 mt-2">
          {error}
        </p>
      )}
    </div>
  );
}
