import { useState } from "react";
import { loginUser } from "../api";
import { useNavigate } from "react-router-dom";

export default function Login() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const navigate = useNavigate();

    const handleLogin = async () => {
        try {
            const res = await loginUser({ username, password });
            console.log(res);
            localStorage.setItem("token", res.data.access_token);
            navigate("/chat");
        } catch (err) {
            console.error("Login failed", err);
        }
    };

    return (
        <div className="flex flex-col items-center mt-20">
            <h1 className="text-2xl mb-4">Login</h1>
            <input
                className="border p-2 mb-2"
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
            />
            <input
                type="password"
                className="border p-2 mb-2"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
            />
            <button
                onClick={handleLogin}
                className="bg-green-600 text-white px-4 py-2"
            >
                Login
            </button>
        </div>
    );
}
