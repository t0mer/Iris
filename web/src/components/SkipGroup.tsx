import { t } from '../lib/i18n'
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '../lib/notify'
import { CircleSlash } from 'lucide-react'
import { api } from '../lib/api'
import { useMe } from '../lib/auth'
import type { Message } from '../lib/types'
import { Button } from './ui/button'
import { ConfirmDialog, Dialog, DialogContent, DialogTrigger } from './ui/dialog'

type Child = { id: number; kid_name: string; skipped: boolean }

export function SkipGroup({
  messageId,
  isGroup,
  disabled = false,
}: {
  messageId: number
  isGroup?: boolean
  disabled?: boolean
}) {
  const { data: me } = useMe()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const qc = useQueryClient()
  const { data: message } = useQuery({
    queryKey: ['skip-group-message', messageId],
    queryFn: () => api<Message>(`/api/messages/${messageId}`),
    enabled: open,
  })
  const { data: children, isError } = useQuery({
    queryKey: ['group-children', message?.chat_id],
    queryFn: () =>
      api<Child[]>(
        `/api/messages/${message?.is_group ? 'groups' : 'chats'}/${message!.chat_id}/children`,
      ),
    enabled: open && !!message,
  })
  if (!['admin', 'parent'].includes(me?.role || '')) return null
  const kind = (message?.is_group ?? isGroup) ? 'group' : 'chat'
  async function act(child: Child, removeHistory = false) {
    setBusy(true)
    try {
      const base = `/api/messages/${message?.is_group ? 'groups' : 'chats'}/${message!.chat_id}/children/${child.id}`
      await api(removeHistory ? `${base}/history` : base, {
        method: removeHistory ? 'DELETE' : 'PUT',
        ...(removeHistory ? {} : { body: JSON.stringify({ skipped: !child.skipped }) }),
      })
      toast.success(
        removeHistory
          ? 'History deleted for this child.'
          : child.skipped
            ? t('{value0} monitoring resumed.', { value0: kind === 'group' ? 'Group' : 'Chat' })
            : t('{value0} skipped. You can now delete its history below.', {
                value0: kind === 'group' ? 'Group' : 'Chat',
              }),
      )
      if (removeHistory) setOpen(false)
      await qc.invalidateQueries()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not update group.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          aria-label={t('Skip {value0}', {
            value0:
              message?.is_group === undefined && isGroup === undefined ? 'chat / group' : kind,
          })}
          title={t('Choose which child should stop monitoring this chat or group')}
        >
          <CircleSlash /> {t('Skip')}{' '}
        </Button>
      </DialogTrigger>
      <DialogContent
        title={t('{value0} monitoring per child', {
          value0: kind === 'group' ? t('Group') : t('Chat'),
        })}
        description={t(
          "Skip future messages from this WhatsApp {value0} for a child. After skipping, you can delete that child's message history, alerts, and reviews. History shared with other children is retained for them.",
          { value0: kind },
        )}
      >
        {!message && <p>{t('Loading group…')}</p>}
        {isError && <p role="alert">{t('Could not load children. Close and try again.')}</p>}
        {children?.map((child) => (
          <div key={child.id} className="flex flex-wrap items-center gap-2 rounded-md border p-3">
            <span className="flex-1">
              {child.kid_name} · {child.skipped ? t('Skipped') : t('Monitoring')}
            </span>
            {child.skipped ? (
              <Button variant="outline" size="sm" disabled={busy} onClick={() => void act(child)}>
                {t('Resume monitoring')}
              </Button>
            ) : (
              <ConfirmDialog
                trigger={
                  <Button variant="outline" size="sm" disabled={busy}>
                    {' '}
                    {t('Skip')} {kind}
                  </Button>
                }
                title={t('Are you sure you want to skip this {value0} for {value1}?', {
                  value0: kind,
                  value1: child.kid_name,
                })}
                description={t(
                  'Iris will stop checking new messages from this {value0} for {value1}. Other children keep their own monitoring settings. You can resume later.',
                  { value0: kind, value1: child.kid_name },
                )}
                confirmLabel={t('Skip {value0}', { value0: kind })}
                onConfirm={() => act(child)}
              />
            )}
            {child.skipped && (
              <ConfirmDialog
                trigger={
                  <Button variant="danger" size="sm" disabled={busy}>
                    {t('Delete history')}
                  </Button>
                }
                title={t('Delete {value0} history for {value1}?', {
                  value0: kind,
                  value1: child.kid_name,
                })}
                description={t(
                  "Permanently delete this child's message history, alerts, and reviews for this {value0}. Shared records remain for other children. Saved media from deleted messages will also be removed.",
                  { value0: kind },
                )}
                confirmLabel={t('Delete history')}
                onConfirm={() => act(child, true)}
              />
            )}
          </div>
        ))}
      </DialogContent>
    </Dialog>
  )
}
