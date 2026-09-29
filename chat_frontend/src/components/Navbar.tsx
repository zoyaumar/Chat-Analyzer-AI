import { Link } from "react-router-dom";
import { useAuth } from "../auth/useAuth";

export default function Navbar() {
  const { signOut } = useAuth();

  return (
    <nav aria-label="Main" className="bg-blue-600 text-white p-4 flex flex-wrap gap-3 justify-between">
      <div className="flex space-x-4">
        <Link className="focus-ring" to="/chat">
          Chat
        </Link>
        <Link className="focus-ring" to="/analytics">
          Analytics
        </Link>
      </div>
      <button
        onClick={signOut}
        className="focus-ring bg-red-500 px-3 py-1 rounded"
      >
        Logout
      </button>
    </nav>
  );
}
