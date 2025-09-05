export interface User {
  id: number;
  username: string;
}

export interface Message {
  id: number;
  text: string;
  user_id: number;
  created_at: string;
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
