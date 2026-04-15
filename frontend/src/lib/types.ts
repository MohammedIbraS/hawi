export type Language = "ar" | "en";

export interface Source {
  index: number;
  entity: string;
  title_ar: string;
  title_en: string;
  url: string;
  page_number: number | null;
  section_heading: string | null;
  content?: string;
  publication_date: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  timestamp: Date;
}

export interface EntityInfo {
  entity: string;
  name_ar: string;
  name_en: string;
  doc_count: number;
  last_updated: string | null;
  failed_count: number;
  pending_count: number;
}

export interface DocumentSummary {
  id: string;
  entity: string;
  title_ar: string | null;
  title_en: string | null;
  doc_type: string;
  original_url: string;
  publication_date: string | null;
  last_fetched_at: string | null;
  ingest_status: string;
}

export interface DocumentsResponse {
  total: number;
  page: number;
  page_size: number;
  items: DocumentSummary[];
}

export interface ChatSessionSummary {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatSessionDetail {
  id: string;
  title: string | null;
  messages: {
    id: string;
    role: "user" | "assistant";
    content: string;
    sources?: Source[];
    created_at: string;
  }[];
}

export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}
