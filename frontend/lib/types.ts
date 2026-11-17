export type ChatRole = "user" | "assistant";

export interface Citation {
  index?: number;
  chunk_id: string;
  document_id: string;
  document_filename: string;
  chunk_index: number;
  text_snippet: string;
  page_number?: number | null;
  /** The page number printed on the page, when the file exposes one. */
  page_label?: string | null;
  relevance_score?: number;
}

export interface ChatMessage {
  role: ChatRole;
  content: string;
  citations?: Citation[];
}

export interface DocumentInfo {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: "pending" | "processing" | "completed" | "failed" | string;
  chunks_count: number;
  error_message?: string | null;
  created_at: string;
}

export interface DocumentListResponse {
  items: DocumentInfo[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface DonePayload {
  answer: string;
  confidence: number;
  query_id: string;
  latency_ms: number;
  /** "user", "server" or "none"; optional so older backends still work. */
  llm_source?: "user" | "server" | "none" | string;
}
