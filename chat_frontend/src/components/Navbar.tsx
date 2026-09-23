import { Link } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

export default function Navbar() {
  const { signOut } = useAuth();

  return (
    <nav className="bg-blue-600 text-white p-4 flex justify-between">
      <div className="flex space-x-4">
        <Link to="/chat">Chat</Link>
        <Link to="/analytics">Analytics</Link>
      </div>
      <button
        onClick={signOut}
        className="bg-red-500 px-3 py-1 rounded"
      >
        Logout
      </button>
    </nav>
  );
}
