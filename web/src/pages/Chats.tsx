import { t } from '../lib/i18n'
import { useQuery } from '@tanstack/react-query'
import { MessagesSquare, Search, User, Users } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Chips, FilterBar } from '../components/FilterBar'
import { Field, Input, Select } from '../components/ui/field'
import { Button } from '../components/ui/button'
import { useUrlState } from '../lib/urlState'
import { useMe } from '../lib/auth'
import { Link } from 'react-router-dom'
import { EmptyState } from '../components/EmptyState'
import { KidStack } from '../components/KidAvatar'
import { PageHeader } from '../components/PageHeader'
import { Badge } from '../components/ui/badge'
import { Skeleton } from '../components/ui/skeleton'
import { api } from '../lib/api'
import { relativeTime } from '../lib/format'
import type { Chat, Instance } from '../lib/types'
import { QueryError } from '../components/QueryError'

const TYPES = ['text', 'image', 'audio', 'voice', 'video', 'sticker', 'document', 'poll', 'other']
const VERDICTS = [
  { value: 'harmful', label: 'Harmful' },
  { value: 'review', label: 'Needs review' },
  { value: 'safe', label: 'Safe' },
  { value: 'none', label: 'Not checked' },
]
const WHEN = [
  { value: '', label: 'Any time' },
  { value: 'today', label: 'Today' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
]

function since(when: string): string | null {
  const now = new Date()
  if (when === 'today')
    return new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString()
  const days = when === '7d' ? 7 : when === '30d' ? 30 : 0
  return days ? new Date(now.getTime() - days * 86_400_000).toISOString() : null
}

export function Chats() {
  const { data: me } = useMe()
  const { get, update, clear } = useUrlState()

  // The search box edits locally and reaches the address (and the server) after a short pause.
  // `pushed` is what we last wrote, so an outside change (a link, back) re-syncs the box without
  // fighting the user's typing.
  const [q, setQ] = useState(get('q'))
  const pushed = useRef(get('q'))
  useEffect(() => {
    const t = setTimeout(() => {
      if (pushed.current !== q) {
        pushed.current = q
        update({ q })
      }
    }, 300)
    return () => clearTimeout(t)
  }, [q, update])
  const urlQ = get('q')
  useEffect(() => {
    if (urlQ !== pushed.current) {
      pushed.current = urlQ
      setQ(urlQ)
    }
  }, [urlQ])

  // Computed once per choice, not per render: a changing timestamp would change the query key and
  // refetch forever.
  const when = get('when')
  const from = useMemo(() => since(when), [when])

  const params = new URLSearchParams()
  for (const k of ['q', 'instance_id', 'type', 'verdict', 'sender'])
    if (get(k)) params.set(k, get(k))
  if (from) params.set('from', from)

  const { data: instances } = useQuery({
    queryKey: ['auth-phones', me?.id],
    queryFn: () => api<Instance[]>('/api/auth/phones'),
  })
  const active = ['q', 'instance_id', 'type', 'verdict', 'sender', 'when'].filter((k) =>
    get(k),
  ).length
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['chats', me?.id, params.toString()],
    queryFn: () => api<Chat[]>(`/api/chats?${params}`),
    refetchInterval: 60_000,
  })
  return (
    <div className="flex max-w-4xl flex-col gap-5">
      <PageHeader
        title={t('Chats')}
        description={t(
          'Filter conversations by their messages. Counts show all messages and alerts in each chat.',
        )}
      />
      <div className="relative">
        <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          dir="auto"
          aria-label={t('Search chat messages')}
          placeholder={t('Search messages or transcripts within chats')}
          className="min-h-11 ps-9"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <FilterBar
        active={active}
        onClear={() => {
          setQ('')
          clear()
        }}
        leading={
          <Chips
            label={t('When')}
            value={get('when')}
            options={WHEN}
            onChange={(v) => update({ when: v })}
          />
        }
      >
        <Field label={t('Phone')} className="md:w-40">
          <Select
            value={get('instance_id')}
            onChange={(e) => update({ instance_id: e.target.value })}
          >
            <option value="">{t('All phones')}</option>
            {instances?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.kid_name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('Type')} className="md:w-36">
          <Select value={get('type')} onChange={(e) => update({ type: e.target.value })}>
            <option value="">{t('All types')}</option>
            {TYPES.map((type) => (
              <option key={type} value={type}>
                {t(type)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('Verdict')} className="md:w-40">
          <Select value={get('verdict')} onChange={(e) => update({ verdict: e.target.value })}>
            <option value="">{t('Any verdict')}</option>
            {VERDICTS.map((v) => (
              <option key={v.value} value={v.value}>
                {t(v.label)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('Sender')} className="md:w-40">
          <Input
            dir="auto"
            value={get('sender')}
            onChange={(e) => update({ sender: e.target.value })}
          />
        </Field>
      </FilterBar>

      {isLoading && <Skeleton className="h-48" />}
      {isError && <QueryError what="your chats" onRetry={() => void refetch()} />}
      <ul className="divide-y overflow-hidden rounded-lg border bg-surface">
        {data?.map((c) => (
          <li key={c.id}>
            <Link
              to={`/messages?${new URLSearchParams({ ...Object.fromEntries(params), ...(get('when') ? { when: get('when') } : {}), chat: String(c.id) })}`}
              className="flex items-center gap-4 px-4 py-3.5 hover:bg-surface-2/60"
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary-soft text-primary">
                {c.is_group ? <Users className="size-5" /> : <User className="size-5" />}
                <span className="sr-only">{c.is_group ? t('Group') : t('Direct chat')}</span>
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="truncate font-medium" dir="auto">
                  {c.name ?? (c.is_group ? t('Unnamed group') : t('Direct chat'))}
                </span>
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                  <KidStack names={c.kids.map((k) => k.kid_name)} />
                  <span>{c.kids.map((k) => k.kid_name).join(' and ') || 'No phone linked'}</span>
                </span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1 text-sm">
                <span className="tabular">
                  {c.message_count} {c.message_count === 1 ? t('message') : t('messages')}
                </span>
                {c.alert_count > 0 && (
                  <Badge tone="danger">
                    {c.alert_count} {c.alert_count === 1 ? t('alert') : t('alerts')}
                  </Badge>
                )}
                {c.last_message_at && (
                  <span className="text-xs text-muted-foreground">
                    {relativeTime(c.last_message_at)}
                  </span>
                )}
              </span>
            </Link>
          </li>
        ))}
        {data?.length === 0 && (
          <li>
            <EmptyState
              icon={MessagesSquare}
              title={active ? t('No chats match') : t('No chats yet')}
              action={
                active ? (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setQ('')
                      clear()
                    }}
                  >
                    {t('Clear search and filters')}
                  </Button>
                ) : undefined
              }
            >
              {t('Chats show up here once a connected phone receives or sends a message.')}
            </EmptyState>
          </li>
        )}
      </ul>
    </div>
  )
}
