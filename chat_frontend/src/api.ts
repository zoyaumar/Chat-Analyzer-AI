import { apiDelete, apiGet, apiPost } from "./apiClient";
import type {
  Message,
  MessagePageParams,
  SentimentResult,
  SentimentTimeline,
  SummaryResult,
  TokenResponse,
  User,
  UserProfile,
} from "./types";

// --- Auth ---
export const registerUser = (data: { username: string; password: string }) =>
  apiPost<User>("/users/register", data);

export const loginUser = (data: { username: string; password: string }) =>
  apiPost<TokenResponse>("/users/login", new URLSearchParams(data), {
    skipUnauthorizedHandler: true,
    // A wrong password must not "rescue" itself by renewing — and must never
    // log a signed-in user out of the app over a typo on the login form.
    skipRefresh: true,
  });

/**
 * Trade the refresh cookie for a new access token (gaps S7/S9, Q9). The
 * cookie is `HttpOnly`, so only the browser carries it — this call is the
 * *only* thing that can spend it, and it never triggers its own refresh.
 */
export const refreshSession = () =>
  apiPost<TokenResponse>("/users/refresh", undefined, {
    skipUnauthorizedHandler: true,
    skipRefresh: true,
  });

/** Revoke the session's refresh token server-side and retire the cookie (S7). */
export const logoutUser = () =>
  apiPost<{ detail: string }>("/users/logout", undefined, {
    skipUnauthorizedHandler: true,
    skipRefresh: true,
  });

/** A message author's name, for attribution in the feed (gap F10). */
export const getUserProfile = (userId: number) =>
  apiGet<UserProfile>(`/users/${userId}`);

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

/**
 * A pure SQL aggregate over stored scores, so the dashboard it feeds runs no
 * inference and stays fast regardless of how heavy the models are (gap A3/P12).
 */
export const getSentimentTimeline = (days: number) =>
  apiGet<SentimentTimeline>("/analytics/sentiment/timeline", { days });

