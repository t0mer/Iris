import { useQuery } from '@tanstack/react-query'
import { Pencil, ShieldOff, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { api } from '../lib/api'
import { cn } from '../lib/cn'
import { dateTime } from '../lib/format'
import type { Message, MessageDetail } from '../lib/types'
import { QueryError } from './QueryError'
import { Badge } from './ui/badge'
import { Dialog, DialogContent, DialogTrigger } from './ui/dialog'
import { Skeleton } from './ui/skeleton'

type Flagged = Pick<Message, 'edited_at' | 'revoked_at'> & { id: number }

/**
 * "Deleted for everyone" and "Edited" markers. With `history` the edited marker is a button that
 * opens the edit history; inside a link it must stay plain, so the list rows leave it off.
 */
export function MessageFlags({ m, history = false }: { m: Flagged; history?: boolean }) {
  if (!m.revoked_at && !m.edited_at) return null
  return (
    <>
      {m.revoked_at && (
        <Badge tone="danger" title="The sender deleted this message for everyone. Iris kept it.">
          <Trash2 /> Deleted for everyone
        </Badge>
      )}
      {m.edited_at &&
        (history ? (
          <EditHistory m={m} />
        ) : (
          <Badge title="The sender edited this message.">
            <Pencil /> Edited
          </Badge>
        ))}
    </>
  )
}

function EditHistory({ m }: { m: Flagged }) {
  const [open, setOpen] = useState(false)
  const detail = useQuery({
    queryKey: ['message', String(m.id)],
    queryFn: () => api<MessageDetail>(`/api/messages/${m.id}`),
    enabled: open,
  })
  const d = detail.data
  const earlier = [...(d?.revisions ?? [])].reverse() // newest first; the last one is the original
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex min-h-6 items-center gap-1 rounded-sm bg-surface-2 px-2 py-0.5 text-xs font-medium text-muted-foreground',
            'hover:bg-border',
          )}
          aria-label="Edited, show the edit history"
        >
          <Pencil className="size-3" /> Edited
        </button>
      </DialogTrigger>
      <DialogContent
        title="Edit history"
        description="Every wording of this message Iris saw, newest first."
      >
        {detail.isError && (
          <QueryError what="the edit history" onRetry={() => void detail.refetch()} />
        )}
        {!d && !detail.isError && <Skeleton className="h-24" />}
        {d && (
          <ol className="flex flex-col gap-3">
            <li className="flex flex-col gap-1 rounded-md border bg-surface-2/50 p-3">
              <span className="text-sm font-medium">Current</span>
              <span className="text-xs text-muted-foreground">
                Edited {d.edited_at ? dateTime(d.edited_at) : ''}
              </span>
              <Wording text={d.text} redacted={d.redacted} />
            </li>
            {earlier.map((r, i) => {
              const original = i === earlier.length - 1
              return (
                <li key={r.replaced_at + i} className="flex flex-col gap-1 rounded-md border p-3">
                  <span className="text-sm font-medium">
                    {original ? 'Original' : 'Earlier version'}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {original ? `Sent ${dateTime(d.sent_at)}, ` : ''}replaced{' '}
                    {dateTime(r.replaced_at)}
                  </span>
                  <Wording text={r.text} />
                </li>
              )
            })}
            {earlier.length === 0 && (
              <li className="text-sm text-muted-foreground">
                {d.redacted
                  ? 'The content is withheld, so no earlier wording is kept.'
                  : 'No earlier wording was kept for this message.'}
              </li>
            )}
          </ol>
        )}
      </DialogContent>
    </Dialog>
  )
}

function Wording({ text, redacted }: { text: string | null; redacted?: boolean }) {
  if (redacted)
    return (
      <span className="inline-flex items-center gap-1.5 italic text-muted-foreground">
        <ShieldOff className="size-4" /> Content withheld.
      </span>
    )
  return (
    <span dir="auto" className="whitespace-pre-wrap break-words text-[15px]">
      {text}
    </span>
  )
}
