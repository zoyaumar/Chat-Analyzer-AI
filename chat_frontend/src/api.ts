import axios from "axios";
import type { TokenResponse, Message, SentimentResult, SummaryResult } from "./types";

// Same-origin: dev traffic goes through the Vite proxy, production through nginx
// or the static mount (docs/DESIGN_DECISIONS.md Q34).
const API = axios.create({ baseURL: "/" });

// Attach JWT if available
API.interceptors.request.use((req) => {
  const token = localStorage.getItem("token");
  if (token && req.headers) {
    req.headers.Authorization = `Bearer ${token}`;
  }
  return req;
});

// --- Auth ---
export const registerUser = (data: { username: string; password: string }) =>
  API.post("/users/register", data);

export const loginUser = (data: { username: string; password: string }) =>
  API.post<TokenResponse>(
    "/users/login",
    new URLSearchParams(data),
    { headers: { "Content-Type": "application/x-www-form-urlencoded" } }
  );

// --- Messages ---
export const getMessages = () => API.get<Message[]>("/messages/");
export const sendMessage = (data: { text: string }) =>
  API.post<Message>("/messages/", data);

// --- Analytics ---
export const analyzeSentiment = (text: string) =>
  API.post<SentimentResult>("/analytics/sentiment", { text });

export const getDailySummary = () => API.get<SummaryResult>("/analytics/daily");

export function connectWebSocket(
  onMessage: (msg: Message) => void,
  token: string
): WebSocket {
  const ws = new WebSocket(
    `${location.origin.replace(/^http/, "ws")}/ws/chat?token=${token}`
  );

  ws.onmessage = (event) => {
    let data: unknown;
    try {
      data = JSON.parse(event.data);
    } catch {
      return; // ignore malformed frames
    }
    // Only accept frames shaped like a Message; ignore echoes/prototyping frames.
    const m = data as Partial<Message>;
    if (typeof m.id === "number" && typeof m.text === "string") {
      onMessage(m as Message);
    }
  };

  return ws;
}



