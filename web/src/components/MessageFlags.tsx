import { t } from '../lib/i18n'
import { useQuery } from '@tanstack/react-query'
import { Pencil, ShieldOff, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { api } from '../lib/api'
import { cn } from '../lib/cn'
import { dateTime } from '../lib/format'
import type { Message, MessageDetail } from '../lib/types'
import { useReveal } from '../lib/useReveal'
import { QueryError } from './QueryError'
import { Concealed, RevealButton } from './Reveal'
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
        <Badge
          tone="danger"
          title={t('The sender deleted this message for everyone. Iris kept it.')}
        >
          <Trash2 /> {t('Deleted for everyone')}
        </Badge>
      )}
      {m.edited_at &&
        (history ? (
          <EditHistory m={m} />
        ) : (
          <Badge title={t('The sender edited this message.')}>
            <Pencil /> {t('Edited')}{' '}
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
          aria-label={t('Edited, show the edit history')}
        >
          <Pencil className="size-3" /> {t('Edited')}{' '}
        </button>
      </DialogTrigger>
      <DialogContent
        title={t('Edit history')}
        description={t('Every wording of this message Iris saw, newest first.')}
      >
        {detail.isError && (
          <QueryError what="the edit history" onRetry={() => void detail.refetch()} />
        )}
        {!d && !detail.isError && <Skeleton className="h-24" />}
        {d && <HistoryBody d={d} earlier={earlier} />}
      </DialogContent>
    </Dialog>
  )
}

/** Lives inside the dialog, so it starts hidden again every time the dialog is opened. */
function HistoryBody({ d, earlier }: { d: MessageDetail; earlier: MessageDetail['revisions'] }) {
  const { revealed, toggle } = useReveal()
  return (
    <>
      {!d.redacted && <RevealButton revealed={revealed} onToggle={toggle} className="w-fit" />}
      <ol className="flex flex-col gap-3">
        <li className="flex flex-col gap-1 rounded-md border bg-surface-2/50 p-3">
          <span className="text-sm font-medium">{t('Current')}</span>
          <span className="text-xs text-muted-foreground">
            {' '}
            {t('Edited')} {d.edited_at ? dateTime(d.edited_at) : ''}
          </span>
          <Wording text={d.text} redacted={d.redacted} revealed={revealed} />
        </li>
        {earlier.map((r, i) => {
          const original = i === earlier.length - 1
          return (
            <li key={r.replaced_at + i} className="flex flex-col gap-1 rounded-md border p-3">
              <span className="text-sm font-medium">
                {original ? t('Original') : t('Earlier version')}
              </span>
              <span className="text-xs text-muted-foreground">
                {original ? t('Sent {value0}, ', { value0: dateTime(d.sent_at) }) : ''}
                {t('replaced')} {dateTime(r.replaced_at)}
              </span>
              <Wording text={r.text} revealed={revealed} />
            </li>
          )
        })}
        {earlier.length === 0 && (
          <li className="text-sm text-muted-foreground">
            {d.redacted
              ? t('The content is withheld, so no earlier wording is kept.')
              : t('No earlier wording was kept for this message.')}
          </li>
        )}
      </ol>
    </>
  )
}

function Wording({
  text,
  redacted,
  revealed,
}: {
  text: string | null
  redacted?: boolean
  revealed: boolean
}) {
  if (redacted)
    return (
      <span className="inline-flex items-center gap-1.5 italic text-muted-foreground">
        <ShieldOff className="size-4" /> {t('Content withheld.')}
      </span>
    )
  return (
    <span dir="auto" className="whitespace-pre-wrap break-words text-[15px]">
      <Concealed revealed={revealed} length={text?.length}>
        {text}
      </Concealed>
    </span>
  )
}
