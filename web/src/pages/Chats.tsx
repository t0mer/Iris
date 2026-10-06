import { useQuery } from '@tanstack/react-query'
import { MessagesSquare, User, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState } from '../components/EmptyState'
import { KidStack } from '../components/KidAvatar'
import { PageHeader } from '../components/PageHeader'
import { Badge } from '../components/ui/badge'
import { Skeleton } from '../components/ui/skeleton'
import { api } from '../lib/api'
import { relativeTime } from '../lib/format'
import type { Chat } from '../lib/types'

export function Chats() {
  const { data, isLoading } = useQuery({
    queryKey: ['chats'],
    queryFn: () => api<Chat[]>('/api/chats'),
    refetchInterval: 60_000,
  })
  return (
    <div className="flex max-w-4xl flex-col gap-5">
      <PageHeader
        title="Chats"
        description="Every conversation and group Iris has seen, and which phones are in them."
      />
      {isLoading && <Skeleton className="h-48" />}
      <ul className="divide-y overflow-hidden rounded-lg border bg-surface">
        {data?.map((c) => (
          <li key={c.id}>
            <Link
              to={`/messages?chat=${c.id}`}
              className="flex items-center gap-4 px-4 py-3.5 hover:bg-surface-2/60"
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary-soft text-primary">
                {c.is_group ? <Users className="size-5" /> : <User className="size-5" />}
                <span className="sr-only">{c.is_group ? 'Group' : 'Direct chat'}</span>
              </span>
              <span className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="truncate font-medium" dir="auto">
                  {c.name ?? c.wa_chat_id}
                </span>
                <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
                  <KidStack names={c.kids.map((k) => k.kid_name)} />
                  <span>{c.kids.map((k) => k.kid_name).join(' and ') || 'No phone linked'}</span>
                </span>
              </span>
              <span className="flex shrink-0 flex-col items-end gap-1 text-sm">
                <span className="tabular">
                  {c.message_count} {c.message_count === 1 ? 'message' : 'messages'}
                </span>
                {c.alert_count > 0 && (
                  <Badge tone="danger">
                    {c.alert_count} {c.alert_count === 1 ? 'alert' : 'alerts'}
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
            <EmptyState icon={MessagesSquare} title="No chats yet">
              Chats show up here once a connected phone receives or sends a message.
            </EmptyState>
          </li>
        )}
      </ul>
    </div>
  )
}
