import type { Classification } from '../lib/types'
import { Scores } from './Scores'
import { Badge } from './ui/badge'

const STAGE: Record<string, string> = {
  moderation: 'First check',
  context: 'Second look, with the chat around it',
}
const BAND: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' }> = {
  safe: { label: 'Fine', tone: 'success' },
  inconclusive: { label: 'Unclear', tone: 'warning' },
  harmful: { label: 'Harmful', tone: 'danger' },
}

/** How Iris decided: one card per stage, with the score for every category that registered. */
export function ClassificationCards({ items }: { items: Classification[] }) {
  if (items.length === 0)
    return (
      <p className="rounded-lg border bg-surface p-4 text-sm text-muted-foreground">
        Not checked yet. Iris classifies new messages within a few seconds.
      </p>
    )
  return (
    <div className="flex flex-col gap-3">
      {items.map((c) => (
        <div key={c.id} className="flex flex-col gap-3 rounded-lg border bg-surface p-4">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium">{STAGE[c.stage] ?? c.stage}</p>
            <Badge tone={BAND[c.band]?.tone ?? 'neutral'}>{BAND[c.band]?.label ?? c.band}</Badge>
            <span className="ms-auto text-xs text-muted-foreground">
              {c.input_kind}, {c.model}
            </span>
          </div>
          <Scores scores={c.scores} />
        </div>
      ))}
    </div>
  )
}
