import { useQuery } from '@tanstack/react-query'
import { Search, SearchX } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState } from '../components/EmptyState'
import { Chips, FilterBar } from '../components/FilterBar'
import { Highlight } from '../components/Highlight'
import { KidStack } from '../components/KidAvatar'
import { Failure, MessageBody, VerdictBadge } from '../components/MessageBody'
import { PageHeader } from '../components/PageHeader'
import { Pagination } from '../components/Pagination'
import { TypeIcon } from '../components/TypeIcon'
import { Button } from '../components/ui/button'
import { Field, Input, Select } from '../components/ui/field'
import { Skeleton } from '../components/ui/skeleton'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import { useUrlState } from '../lib/urlState'
import type { Instance, MessagePage } from '../lib/types'

const TYPES = ['text', 'image', 'audio', 'voice', 'video', 'sticker', 'document', 'other']
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
const PAGE_SIZE = 25

function since(when: string): string | null {
  const now = new Date()
  if (when === 'today')
    return new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString()
  const days = when === '7d' ? 7 : when === '30d' ? 30 : 0
  return days ? new Date(now.getTime() - days * 86_400_000).toISOString() : null
}

export function Messages() {
  const { get, page, update, clear } = useUrlState()

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

  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) })
  for (const k of ['q', 'instance_id', 'type', 'verdict', 'sender'])
    if (get(k)) params.set(k, get(k))
  if (get('chat')) params.set('chat_id', get('chat'))
  if (from) params.set('from', from)

  const { data: instances } = useQuery({
    queryKey: ['instances'],
    queryFn: () => api<Instance[]>('/api/instances'),
  })
  const { data, isLoading, isError } = useQuery({
    queryKey: ['messages', params.toString()],
    queryFn: () => api<MessagePage>(`/api/messages?${params}`),
  })
  const active =
    ['instance_id', 'type', 'verdict', 'sender', 'chat', 'when'].filter((k) => get(k)).length +
    (get('q') ? 1 : 0)

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Messages"
        description="Everything Iris has seen. Search covers messages and voice-note transcripts, in Hebrew and English."
      />

      <div className="relative">
        <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          type="search"
          dir="auto"
          aria-label="Search messages"
          placeholder="Search words, names or transcripts"
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
            label="When"
            value={get('when')}
            options={WHEN}
            onChange={(v) => update({ when: v })}
          />
        }
      >
        <Field label="Phone" className="md:w-40">
          <Select
            value={get('instance_id')}
            onChange={(e) => update({ instance_id: e.target.value })}
          >
            <option value="">All phones</option>
            {instances?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.kid_name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Type" className="md:w-36">
          <Select value={get('type')} onChange={(e) => update({ type: e.target.value })}>
            <option value="">All types</option>
            {TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </Select>
        </Field>
        <Field label="Verdict" className="md:w-40">
          <Select value={get('verdict')} onChange={(e) => update({ verdict: e.target.value })}>
            <option value="">Any verdict</option>
            {VERDICTS.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Sender" className="md:w-40">
          <Input
            dir="auto"
            value={get('sender')}
            onChange={(e) => update({ sender: e.target.value })}
          />
        </Field>
      </FilterBar>

      <ul className="divide-y overflow-hidden rounded-lg border bg-surface" aria-busy={isLoading}>
        {isLoading &&
          Array.from({ length: 5 }, (_, i) => (
            <li key={i} className="p-4">
              <Skeleton className="h-12" />
            </li>
          ))}
        {isError && (
          <li role="alert" className="p-4 text-sm text-danger">
            Could not load messages. Reload the page; if it keeps failing, check the Jobs page.
          </li>
        )}
        {data?.items.map((m) => (
          <li key={m.id}>
            <Link
              to={`/messages/${m.id}`}
              className="flex flex-col gap-1.5 px-4 py-3.5 hover:bg-surface-2/60"
            >
              <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <KidStack names={m.kids.map((k) => k.kid_name)} />
                <span className="font-medium">{m.kids.map((k) => k.kid_name).join(' and ')}</span>
                <span className="text-sm text-muted-foreground">
                  {m.chat_name ?? (m.is_group ? 'a group' : 'a chat')}
                  {m.sender_name ? `, ${m.sender_name}` : ''}
                </span>
                <span className="ms-auto text-xs text-muted-foreground">{dateTime(m.sent_at)}</span>
              </span>
              <span className="flex items-start gap-2">
                <span className="mt-1 text-muted-foreground">
                  <TypeIcon type={m.type} />
                </span>
                <span className="line-clamp-2 min-w-0 flex-1 break-words text-[15px]" dir="auto">
                  {m.snippet ? <Highlight snippet={m.snippet} /> : <MessageBody m={m} />}
                </span>
                <VerdictBadge m={m} />
              </span>
              <Failure m={m} />
            </Link>
          </li>
        ))}
        {data && data.items.length === 0 && (
          <li>
            <EmptyState
              icon={SearchX}
              title={active > 0 ? 'No messages match' : 'No messages yet'}
              action={
                active > 0 ? (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setQ('')
                      clear()
                    }}
                  >
                    Clear search and filters
                  </Button>
                ) : undefined
              }
            >
              {active > 0
                ? 'Try fewer words or remove a filter.'
                : 'Messages appear here a few seconds after a phone receives or sends them.'}
            </EmptyState>
          </li>
        )}
      </ul>
      {data && (
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={data.total}
          noun={['message', 'messages']}
          onPage={(p) => update({ page: String(p) })}
        />
      )}
    </div>
  )
}
