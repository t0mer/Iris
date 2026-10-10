import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

export type LiveStatus = 'live' | 'reconnecting' | 'unsupported'

/** Which query keys each server topic makes stale. The stream carries no content, only topics. */
const KEYS: Record<string, string[]> = {
  messages: ['messages', 'message', 'message-context', 'timeline'],
  alerts: ['alerts', 'alert'],
  review: ['review'],
  jobs: ['jobs'],
  stats: ['stats', 'alert-readiness', 'schedules', 'audit'],
  instances: ['instances', 'auth-phones'],
  chats: ['chats'],
}

export function invalidateTopics(qc: QueryClient, topics: string[]) {
  for (const t of topics) {
    for (const key of KEYS[t] ?? []) void qc.invalidateQueries({ queryKey: [key] })
  }
}

function parse(data: string): { topics?: unknown; id?: unknown } | null {
  try {
    const v: unknown = JSON.parse(data)
    return v && typeof v === 'object' ? v : null
  } catch {
    return null
  }
}

/**
 * Keeps the open page current: opens /api/events, refetches what the server says changed, and
 * catches up on everything after a (re)connect or when the tab comes back. Polling stays as the
 * fallback, so a blocked or buffered stream only costs freshness.
 */
export function useLiveUpdates(onAlert: (id: number | null) => void): LiveStatus {
  const qc = useQueryClient()
  const alertRef = useRef(onAlert)
  useEffect(() => {
    alertRef.current = onAlert
  })
  const [status, setStatus] = useState<LiveStatus>(
    typeof EventSource === 'undefined' ? 'unsupported' : 'reconnecting',
  )
  useEffect(() => {
    if (typeof EventSource === 'undefined') return
    let source: EventSource | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let delay = 5_000
    const everything = () => void qc.invalidateQueries()
    const connect = () => {
      const es = new EventSource('/api/events')
      source = es
      es.addEventListener('hello', () => {
        delay = 5_000
        setStatus('live')
        everything() // whatever happened while we were not listening
      })
      es.addEventListener('change', (e) => {
        const topics = parse((e as MessageEvent<string>).data)?.topics
        if (Array.isArray(topics)) {
          invalidateTopics(
            qc,
            topics.filter((t): t is string => typeof t === 'string'),
          )
        }
      })
      es.addEventListener('alert', (e) => {
        const id = parse((e as MessageEvent<string>).data)?.id
        alertRef.current(typeof id === 'number' ? id : null)
      })
      es.onerror = () => {
        setStatus('reconnecting')
        // A network drop is retried by the browser. A refusal (signed out, too many portals) closes
        // the stream for good, so open a new one ourselves, a little slower each time.
        if (es.readyState === 2 && source === es) {
          es.close()
          retry = setTimeout(connect, delay)
          delay = Math.min(delay * 2, 60_000)
        }
      }
    }
    connect()
    const onVisible = () => {
      if (document.visibilityState === 'visible') everything()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      clearTimeout(retry)
      source?.close()
      source = null
    }
  }, [qc])
  return status
}
