import { useEffect, useState } from "react";
import { getMessages, sendMessage } from "../api";
import Navbar from "../components/Navbar";
import type { Message } from "../types";

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");

  useEffect(() => {
    fetchMessages();
  }, []);

  const fetchMessages = async () => {
    const res = await getMessages();
    setMessages(res.data);
  };

  const handleSend = async () => {
    await sendMessage({ text, user_id: 1 }); // later, derive from JWT
    setText("");
    fetchMessages();
  };

  return (
    <div>
      <Navbar />
      <div className="p-4">
        <h1 className="text-xl mb-4">Chat</h1>
        <div className="border p-2 h-64 overflow-y-scroll mb-4">
          {messages.map((m) => (
            <div key={m.id}>
              <b>User {m.user_id}:</b> {m.text}
            </div>
          ))}
        </div>
        <input
          className="border p-2 w-3/4"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <button
          onClick={handleSend}
          className="bg-blue-600 text-white px-4 py-2 ml-2"
        >
          Send
        </button>
      </div>
    </div>
  );
}
