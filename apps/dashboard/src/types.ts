export interface FileRead {
  content: string;
  sha256: string;
  exists: boolean;
}

export interface SearchResult {
  path: string;
  line: number;
  excerpt: string;
  score: number;
  semantic_score: number | null;
  lexical_score: number | null;
  learned_boost?: number;
  sources: string[];
}

export interface Citation {
  path: string;
  line: number;
  score?: number;
  sources?: string[];
  redactions?: number;
  injection_risk?: string;
}

export interface Safety {
  secrets: number;
  injection: number;
  risk: string;
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
  safety?: Safety;
  retrieval: { used_chars: number; results: number };
}

export interface IndexStats {
  model: string;
  dimensions: number;
  indexed_files: number;
  vectors: number;
  df_terms: number;
  last_indexed_at: number | null;
  backend: string;
  feedback?: { positive: number; negative: number; paths: number; weight: number };
  safety_screening?: string;
}

export interface IndexReport {
  embedded_files: number;
  unchanged_files: number;
  vectors: number;
  elapsed_seconds: number;
  dimensions: number;
}

export interface AgentStep {
  id: string;
  seq: number;
  role: string;
  instruction: string;
  status: string;
  output: string;
  truncated: boolean;
  error: string;
  started_at: number;
  finished_at: number;
}

export interface AgentRun {
  id: string;
  project: string;
  goal: string;
  mode: string;
  status: string;
  created_at: number;
  updated_at: number;
  steps: AgentStep[];
  progress: { completed: number; total: number };
}

export interface AuditEntry {
  created_at: number;
  event: string;
  actor: string;
  detail: string;
  request_id: string;
}

export interface SecurityPosture {
  token_configured: boolean;
  token_fingerprint: string | null;
  token_strength: string;
  mfa_enabled: boolean;
  mfa_algorithm: string;
  mfa_header: string;
  max_auth_failures: number;
  failure_window_seconds: number;
  lockout_base_seconds: number;
  lockout_cap_seconds: number;
  general_rate_limit_per_minute: number;
  max_body_bytes: number;
  locked_addresses: number;
  recent_audit: AuditEntry[];
  client?: string;
  request_id?: string;
}

export interface ChatSeed {
  id: number;
  text: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface HistoryResponse {
  messages: ChatMessage[];
}
