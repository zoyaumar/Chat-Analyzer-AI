import { apiDelete, apiGet, apiPost } from "./apiClient";
import type {
  Message,
  MessagePageParams,
  SentimentResult,
  SummaryResult,
  TokenResponse,
  User,
} from "./types";

// --- Auth ---
export const registerUser = (data: { username: string; password: string }) =>
  apiPost<User>("/users/register", data);

export const loginUser = (data: { username: string; password: string }) =>
  apiPost<TokenResponse>("/users/login", new URLSearchParams(data), {
    skipUnauthorizedHandler: true,
  });

// --- Messages ---
export const getMessages = (params?: MessagePageParams) =>
  apiGet<Message[]>("/messages/", {
    limit: params?.limit,
    before: params?.before,
    before_id: params?.beforeId,
  });

export const sendMessage = (data: { text: string }) =>
  apiPost<Message>("/messages/", data);

export const deleteMessage = (messageId: number) =>
  apiDelete<{ detail: string }>(`/messages/${messageId}`);

// --- Analytics ---
export const analyzeSentiment = (text: string) =>
  apiPost<SentimentResult>("/analytics/sentiment", { text });

export const getDailySummary = () => apiGet<SummaryResult>("/analytics/daily");

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

