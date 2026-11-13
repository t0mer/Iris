import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useMe } from '../lib/auth'
import { t } from '../lib/i18n'
import { toast } from '../lib/notify'
import { Button } from './ui/button'
import { Dialog, DialogContent, DialogTrigger } from './ui/dialog'

export function LearningSharing() {
  const { data: me } = useMe()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<boolean | null>(null)
  const qc = useQueryClient()
  const key = ['learning-sharing', me?.id]
  const consent = useQuery({
    queryKey: key,
    queryFn: () => api<{ enabled: boolean }>('/api/auth/learning-sharing'),
    enabled: open && !!me,
  })
  const save = useMutation({
    mutationFn: () =>
      api('/api/auth/learning-sharing', {
        method: 'PATCH',
        body: JSON.stringify({
          enabled: draft ?? consent.data?.enabled ?? false,
          acknowledged_policy: 'synthetic-only-v1',
        }),
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: key })
      setOpen(false)
      setDraft(null)
    },
    onError: (error) => toast.error(error.message),
  })
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setOpen(value)
        setDraft(null)
      }}
    >
      <DialogTrigger asChild>
        <Button variant="ghost">{t('Learning sharing consent')}</Button>
      </DialogTrigger>
      <DialogContent title={t('Learning sharing consent')}>
        <p className="text-sm text-muted-foreground">
          {t(
            'Sharing is off by default and requires your explicit approval. Only reviewed synthetic contributions may be shared. Messages, contacts and private reviews are excluded. This preference does not upload anything automatically.',
          )}
        </p>
        {consent.isError && <p role="alert">{t('Could not load sharing consent.')}</p>}
        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            disabled={!consent.data || save.isPending}
            checked={draft ?? consent.data?.enabled ?? false}
            onChange={(event) => setDraft(event.target.checked)}
            className="mt-1 size-4 shrink-0"
          />
          <span>
            {t(
              'I approve sharing reviewed synthetic learning contributions for my account. I can withdraw this approval at any time.',
            )}
          </span>
        </label>
        <Button
          disabled={!consent.data || draft === null || save.isPending}
          onClick={() => save.mutate()}
        >
          {t('Save')}
        </Button>
      </DialogContent>
    </Dialog>
  )
}
