import { useState } from "react";
import { registerUser } from "../api";
import { isApiError } from "../apiClient";
import { useNavigate } from "react-router-dom";

export default function Register() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      await registerUser({ username, password });
      navigate("/login");
    } catch (err: unknown) {
      if (isApiError(err) && err.detail) {
        setError(err.detail);
      } else if (isApiError(err) && (err.status === 400 || err.status === 422)) {
        setError("Invalid registration details. Please check your username and password.");
      } else {
        setError("Registration failed. Please try again later.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-center mt-20">
      <h1 className="text-2xl mb-4">Register</h1>

      <form onSubmit={handleRegister} className="flex flex-col gap-3 w-64">
        <input
          aria-label="Username"
          className="border p-2"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          aria-label="Password"
          type="password"
          className="border p-2"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button
          type="submit"
          disabled={loading || !username.trim() || !password}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Registering..." : "Register"}
        </button>
      </form>

      {error && (
        <p role="alert" className="text-red-500 mt-2 max-w-xs text-center text-sm">
          {error}
        </p>
      )}
    </div>
  );
}
