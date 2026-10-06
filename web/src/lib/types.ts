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
  classifications: Classification[]
  revisions: Revision[]
}

export interface Instance {
  id: number
  kid_name: string
  phone_number: string | null
  openwa_base_url: string
  openwa_instance_id: string
  api_key_set: boolean
  enabled: boolean
  webhook_url: string
  last_webhook_at: string | null
  created_at: string
}

export interface Alert {
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
}

export interface AlertPage {
  items: Alert[]
  total: number
  page: number
  page_size: number
}

export interface AlertDetail extends Alert {
  message_type: string
  sent_at: string
  classifications: Classification[]
}

export interface ReviewItem {
  message: Message
  classifications: Classification[]
}

export interface ReviewPage {
  items: ReviewItem[]
  total: number
  page: number
  page_size: number
}

export interface Stats {
  messages_today: number
  messages_7d: number
  alerts_by_status: Record<string, number>
  alerts_by_delivery: Record<string, number>
  review_queue: number
  jobs_by_status: Record<string, number>
  queue_depth: number
  failed_jobs: number
  delivery_configured: boolean
  instances: number
  silent_instances: number
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
