import axios from "axios";
import type { TokenResponse, Message, SentimentResult, SummaryResult } from "./types";

const API = axios.create({ baseURL: import.meta.env.VITE_API_URL  });

// Attach JWT if available
API.interceptors.request.use((req) => {
  const token = localStorage.getItem("token");
  if (token && req.headers) {
    req.headers.Authorization = `Bearer ${token}`;
  }
  return req;
});

// --- Auth ---
export const registerUser = (data: { username: string; password_hash: string }) =>
  API.post("/users/register", data);

export const loginUser = (data: { username: string; password: string }) =>
  API.post<TokenResponse>(
    "/users/login",
    new URLSearchParams(data),
    { headers: { "Content-Type": "application/x-www-form-urlencoded" } }
  );

// --- Messages ---
export const getMessages = () => API.get<Message[]>("/messages/");
export const sendMessage = (data: { text: string; user_id: number }) =>
  API.post<Message>("/messages/", data);

// --- Analytics ---
export const analyzeSentiment = (text: string) =>
  API.post<SentimentResult>("/analytics/sentiment", null, { params: { text } });

export const getDailySummary = () => API.get<SummaryResult>("/analytics/daily");
