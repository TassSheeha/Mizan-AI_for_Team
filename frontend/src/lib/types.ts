export interface User {
  id: number
  email: string
  username: string
  role: 'user' | 'admin'
  is_active: boolean
  created_at: string
}

export interface Citation {
  article: string | number | null
  page: number | null
  section: string | null
  chapter: string | null
  document: string | null
  doc_id: string | null
  year: number | null
  text: string | null
}

export interface ChatMessage {
  id: number | string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  confidence?: number
  retrieval_time?: number
  generation_time?: number
  provider?: string
  answer_type?: string
  feedback?: 'like' | 'dislike' | null
  created_at?: string
  pending?: boolean
}

export interface ConversationSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
  last_message?: string
}

export interface LegalDocument {
  id: number
  doc_id: string
  title: string
  doc_type: string
  year: number
  specialization: string
  chunk_count: number
  status: 'indexed' | 'processing' | 'error'
  error_message: string | null
  is_builtin: boolean
  updated_at: string
}

export interface NotificationItem {
  id: number
  title: string
  body: string
  created_at: string
  is_read: boolean
}

export interface AdminStats {
  users: number
  active_users: number
  conversations: number
  messages: number
  messages_24h: number
  documents: number
  indexed_chunks: number
  ai_status: string
  feedback: { like: number; dislike: number; total: number; satisfaction: number | null }
  avg_confidence: number
}

export interface SystemHealth {
  status: string
  components: {
    database: { ok: boolean; latency_ms: number }
    ai_layer: { status: string; error: string | null }
    vector_index: { indexed_chunks: number; error?: string }
    groq_api: { ok: boolean | null; model: string }
  }
  uptime_seconds: number
  timestamp: string
}

export interface AdminUser {
  id: number
  email: string
  username: string
  role: 'user' | 'admin'
  is_active: boolean
  created_at: string
  last_login_at: string | null
  conversation_count: number
}
