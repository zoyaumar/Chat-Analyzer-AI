import axios, { type AxiosError } from "axios";
import type { TokenResponse, Message, SentimentResult, SummaryResult } from "./types";

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

// Same-origin: dev traffic goes through the Vite proxy; production through nginx.
const API = axios.create({ baseURL: "/" });

API.interceptors.request.use((request) => {
  const token = localStorage.getItem("token");
  if (token) {
    request.headers.Authorization = `Bearer ${token}`;
  }
  return request;
});

API.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const isLoginRequest = error.config?.url === "/users/login";
    if (error.response?.status === 401 && !isLoginRequest) {
      unauthorizedHandler?.();
    }
    return Promise.reject(error);
  }
);

// --- Auth ---
export const registerUser = (data: { username: string; password: string }) =>
  API.post("/users/register", data);

export const loginUser = (data: { username: string; password: string }) =>
  API.post<TokenResponse>("/users/login", new URLSearchParams(data), {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });

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
    `${location.origin.replace(/^http/, "ws")}/ws/chat?token=${encodeURIComponent(token)}`
  );

  ws.onmessage = (event) => {
    let data: unknown;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }

    const message = data as Partial<Message>;
    if (typeof message.id === "number" && typeof message.text === "string") {
      onMessage(message as Message);
    }
  };

  return ws;
}

