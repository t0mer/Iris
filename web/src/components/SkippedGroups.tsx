import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Button } from './ui/button'

type Group = { chat_id: number; chat_name: string; instance_id: number; kid_name: string }

export function SkippedGroups() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['skipped-groups'],
    queryFn: () => api<Group[]>('/api/messages/chats/skipped/list'),
  })
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold">Skipped WhatsApp chats and groups</h2>
      {data?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No skipped chats or groups. Skip a chat or group from Messages, Alerts, or Review.
        </p>
      )}
      {data?.map((g) => (
        <div
          key={`${g.chat_id}-${g.instance_id}`}
          className="flex items-center gap-3 rounded-md border p-3"
        >
          <span className="flex-1">
            {g.kid_name} · {g.chat_name}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              try {
                await api(`/api/messages/chats/${g.chat_id}/children/${g.instance_id}`, {
                  method: 'PUT',
                  body: JSON.stringify({ skipped: false }),
                })
                await qc.invalidateQueries()
                toast.success('Group monitoring resumed.')
              } catch (error) {
                toast.error(error instanceof Error ? error.message : 'Could not resume monitoring.')
              }
            }}
          >
            Resume monitoring
          </Button>
        </div>
      ))}
    </section>
  )
}
