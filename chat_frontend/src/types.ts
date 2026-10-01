export interface User {
  id: number;
  username: string;
}

/** `GET /users/{user_id}` — the public profile, used to name message authors (F10). */
export interface UserProfile {
  id: number;
  username: string;
  created_at: string;
}

export interface Message {
  id: number;
  text: string;
  user_id: number;
  timestamp: string;
}

export interface MessagePageParams {
  limit?: number;
  before?: string;
  beforeId?: number;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface SentimentResult {
  label: string;
  score: number;
}

export interface SummaryResult {
  date: string;
  summary: string;
}

/**
 * `GET /analytics/sentiment/timeline` — one entry per UTC day that had
 * activity. Days without messages are omitted rather than zero-filled, so a
 * gap in the data is a gap in the chart (gap A3/P12).
 */
export interface SentimentTimelineEntry {
  date: string;
  messages: number;
  positive: number;
  negative: number;
  avg_score: number;
}

export interface SentimentTimeline {
  days: number;
  timeline: SentimentTimelineEntry[];
}
