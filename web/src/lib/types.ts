export interface Kid {
  id: number
  kid_name: string
}

export interface Message {
  id: number
  chat_id: number
  chat_name: string | null
  is_group: boolean
  sender_name: string | null
  from_me: boolean
  type: string
  text: string | null
  transcript: string | null
  snippet: string | null
  sent_at: string
  status: string
  verdict: string | null
  review_reason?: string | null
  skip_reason?: string | null
  raw_type?: string | null
  diagnostics?: Record<string, boolean | string> | null
  redacted: boolean
  edited_at: string | null
  revoked_at: string | null
  kids: Kid[]
  failure: string | null
}

export interface MessagePage {
  items: Message[]
  total: number
  page: number
  page_size: number
}

export interface Classification {
  id: number
  stage: string
  input_kind: string
  model: string
  scores: Record<string, unknown>
  flagged_categories: string[]
  band: string
  context_message_ids: number[] | null
  latency_ms: number | null
}

export interface Revision {
  text: string
  replaced_at: string
}

export interface MessageDetail extends Message {
  media?: KeptMedia | null
  classifications: Classification[]
  revisions: Revision[]
}

export interface Instance {
  connection_status?: string
  connection_checked_at?: string | null
  session_name?: string | null
  role?: 'child' | 'parent'
  id: number
  kid_name: string
  phone_number: string | null
  openwa_base_url: string
  openwa_instance_id: string
  api_key_set: boolean
  enabled: boolean
  monitoring_status?: string
  monitoring_error?: string | null
  webhook_url: string
  last_webhook_at: string | null
  created_at: string
}

export interface KeptMedia {
  id: number
  kind: 'image' | 'audio' | 'video'
  content_type: string
  size_bytes: number
  inline: boolean
}

export interface MediaInfo extends KeptMedia {
  message_id: number
  alert_id: number | null
}

export interface Alert {
  seen_at?: string | null
  verdict?: string | null
  review_reason?: string | null
  id: number
  message_id: number
  chat_id: number
  categories: string[]
  max_score: number
  kid_names: string[]
  chat_name: string | null
  sender_name: string | null
  quote: string | null
  redacted: boolean
  status: string
  delivery_status: string
  delivery_error: string | null
  notified_at: string | null
  created_at: string
  edited_at: string | null
  revoked_at: string | null
  media?: KeptMedia | null
}

export interface AlertPage {
  items: Alert[]
  total: number
  page: number
  page_size: number
}

export interface ResponseNote {
  actor: string
  choice: string
  applied: boolean
  note: string
  created_at: string
}

export interface AlertDetail extends Alert {
  response_notes?: ResponseNote[]
  sending_server?: string
  recipient_delivery?: { recipient: string; status: string }[]
  message_type: string
  sent_at: string
  classifications: Classification[]
}

export interface ReviewItem {
  human_feedback?: {
    verdict: string
    categories: string[] | null
    explanation: string | null
    details_current: boolean
  } | null
  response_notes?: ResponseNote[]
  missing_data?: boolean
  message: Message
  classifications: Classification[]
}

export interface ReviewPage {
  reviewed_total?: number
  items: ReviewItem[]
  total: number
  page: number
  page_size: number
}

export interface Stats {
  monitoring_issues?: {
    instance_id: number
    kid_name: string
    issues: string[]
    refresh_attempts?: number
    refresh_limit?: number
    refresh_error?: string | null
    notify_after?: string | null
  }[]
  schedule_failures?: { key: string; error: string }[]
  alert_delivery_issues?: string[]
  eligible_alert_recipients?: number
  invalid_alert_recipients?: number
  messages_today: number
  messages_7d: number
  alerts_by_status: Record<string, number>
  alerts_by_delivery: Record<string, number>
  review_queue: number
  iris_review_queue?: number
  jobs_by_status: Record<string, number>
  queue_depth: number
  failed_jobs: number
  delivery_configured: boolean
  instances: number
  children?: number
  parent_recipients?: number
  alert_phones?: number
  alert_sender_configured?: boolean
  silent_instances: number
  sender_is_recipient?: boolean
  unavailable_instances?: number
  monitoring_window_minutes?: number
  media_policy?: string
  media_files?: number
  alert_media_not_saved?: number
  alert_media_warning_count?: number
  alert_media_warning_latest_id?: number
  alert_channel?: string
  media_bytes?: number
}

export interface AlertReadiness {
  channel: string
  ready: boolean
  provider_ready: boolean
  provider_error: string | null
  eligible_count: number
  invalid_count: number
  error: string | null
  issues: string[]
  recipients: {
    target: string
    user_id: number | null
    name: string
    eligible: boolean
    reason: string | null
    legacy: boolean
  }[]
  users: {
    id: number
    username: string
    selected: boolean
    eligible: boolean
    reason: string | null
  }[]
}

export interface Chat {
  id: number
  wa_chat_id: string
  name: string | null
  is_group: boolean
  kids: Kid[]
  message_count: number
  alert_count: number
  last_message_at: string | null
}

export interface Job {
  run_after?: string
  id: number
  type: string
  status: string
  attempts: number
  max_attempts: number
  last_error: string | null
  message_id: number | null
  created_at: string
}

export interface ThresholdRow {
  category: string
  low: number
  high: number
  default_low: number
  default_high: number
}

export interface DayActivity {
  date: string
  safe: number
  review: number
  harmful: number
  other: number
  alerts: number
}

export interface Timeline {
  timezone: string
  days: DayActivity[]
}

export interface DbConfigInfo {
  kind: 'sqlite' | 'postgresql' | 'mysql'
  host: string
  port: number | null
  name: string
  user: string
  tls: boolean
  password_set: boolean
}

export interface CopyState {
  state: 'idle' | 'running' | 'done' | 'failed'
  table: string
  copied: Record<string, number>
  error: string | null
}

export interface DatabaseStatus {
  config_error?: string | null
  running: DbConfigInfo
  running_source: 'env' | 'file' | 'default'
  saved: DbConfigInfo
  restart_required: boolean
  env_override: boolean
  copy_job: CopyState
}

export interface DatabaseProbe {
  ok: boolean
  detail: string
  version: string | null
  empty: boolean | null
  warning: string | null
}
