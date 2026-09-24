export interface User {
  id: number;
  username: string;
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
