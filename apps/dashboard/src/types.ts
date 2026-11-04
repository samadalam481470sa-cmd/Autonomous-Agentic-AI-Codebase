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
  learned_score?: number;
  sources: string[];
}

export interface RagPacket {
  text: string;
  citations: Citation[];
  used_chars: number;
  results: number;
  safety: Safety;
}

export interface SearchResponse {
  query: string;
  mode: string;
  results: SearchResult[];
  retrieval?: { results: number; learned_rerank: boolean; sources: string[] };
  rag?: RagPacket;
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
  interaction_id?: string | null;
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
  lifelong?: {
    interactions: number;
    positive: number;
    negative: number;
    model: { id: string; metrics: Record<string, unknown>; created_at: number } | null;
    capture?: boolean;
  };
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

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface HistoryResponse {
  messages: ChatMessage[];
}

export interface ThermalSensor {
  label: string;
  celsius: number;
}

export interface ThermalEvent {
  at: number;
  from: string;
  to: string;
  celsius: number | null;
}

export interface ThermalStatus {
  state: string;
  max_c: number | null;
  ewma_c: number | null;
  slope_c_per_min: number;
  predicted_c: number | null;
  sensors: ThermalSensor[];
  thresholds: { warn: number; hot: number; critical: number; resume: number };
  cooldown_remaining: number;
  duty_cycle: number;
  sensors_available: boolean;
  note: string;
  history: { t: number; c: number }[];
  events: ThermalEvent[];
  sample_seconds: number;
  admission: { allowed: boolean; reason: string; retry_after: number; mode: string };
}

export interface LearningInteraction {
  id: string;
  kind: string;
  prompt: string;
  response: string;
  citations: Citation[];
  rating: string;
  redactions: number;
  created_at: number;
}

export interface LearningStatus {
  runtime: {
    thread_running: boolean;
    enabled: boolean;
    paused: boolean;
    interval_seconds: number;
    started_at: number | null;
    last_tick: Record<string, unknown> | null;
    capture: boolean;
  };
  gpu: {
    detected: boolean;
    vendor: string | null;
    device_count: number;
    max_utilization_percent: number | null;
    max_temperature_c: number | null;
    metrics_available: boolean;
    note: string;
  };
  power: { on_ac: boolean | null; battery_percent: number | null; source: string };
  projects: string[];
  project?: {
    interactions: number;
    positive: number;
    negative: number;
    capture: boolean;
    model: { id: string; metrics: Record<string, unknown>; created_at: number } | null;
    models: {
      active: { id: string; metrics: Record<string, unknown>; created_at: number } | null;
      latest: ({
        id: string;
        metrics: Record<string, unknown>;
        created_at: number;
        active: boolean;
        notes: string;
      }) | null;
    };
    interactions_recent: LearningInteraction[];
    feedback: { positive: number; negative: number; paths: number; weight: number };
    recent_cycles: { status: string; detail: string; created_at: number }[];
    privacy: string;
  };
  privacy: string;
}

export interface DeviceStatus {
  platform: {
    system: string;
    release: string;
    machine: string;
    python: string;
    hostname: string;
    apple_silicon: boolean;
    container: boolean;
  };
  cpu: {
    model: string;
    logical_cores: number | null;
    physical_cores: number | null;
    max_frequency_mhz: number | null;
    architecture: string;
  };
  memory: {
    total_mb: number | null;
    available_mb: number | null;
    used_percent: number | null;
    source: string;
  };
  disk: { total_gb: number; free_gb: number; used_percent: number } | null;
  gpus: {
    vendor: string;
    name: string;
    vram_mb: number | null;
    used_mb: number | null;
    temp_c: number | null;
    utilization_pct: number | null;
    driver: string | null;
    unified_memory?: boolean;
  }[];
  battery: {
    present: boolean;
    percent: number | null;
    plugged: boolean | null;
    status: string;
  } | null;
  thermal: ThermalStatus;
  keep_awake: {
    active: boolean;
    backend: string | null;
    pid: number | null;
    started_at: number | null;
    expires_at: number | null;
    ttl_remaining_seconds: number | null;
    note: string;
    supported: boolean;
  };
  session: {
    started_at: number;
    uptime_seconds: number;
    keep_awake_seconds: number;
    max_hours: number;
  };
  recommendation: {
    name: string;
    runtime: string;
    context_tokens: number;
    gpu_layers: number;
    estimated_vram_gb: number | null;
    reason: string;
    pull_command: string;
    env: Record<string, string>;
  };
  backends: {
    name: string;
    url: string;
    status: string;
    models: string[];
  }[];
  limits: Record<string, number>;
  privacy: string;
}
