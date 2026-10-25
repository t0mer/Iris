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
export function ClassificationCards({
  items,
  emptyReason,
}: {
  items: Classification[]
  emptyReason?: string
}) {
  if (items.length === 0)
    return (
      <p className="rounded-lg border bg-surface p-4 text-sm text-muted-foreground">
        {emptyReason || t('Not checked yet. Iris classifies new messages within a few seconds.')}
      </p>
    )
  return (
    <div className="flex flex-col gap-3">
      {items.map((c) => (
        <div key={c.id} className="flex flex-col gap-3 rounded-lg border bg-surface p-4">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-medium">{t(STAGE[c.stage] ?? c.stage)}</p>
            <Badge tone={BAND[c.band]?.tone ?? 'neutral'}>{BAND[c.band]?.label ?? c.band}</Badge>
            <span className="ms-auto text-xs text-muted-foreground">
              {c.input_kind === 'video_frames'
                ? t('Sampled video frames')
                : c.input_kind === 'document_text'
                  ? t('Document text analysis')
                  : c.input_kind}
              , {c.model}
            </span>
          </div>
          {c.input_kind === 'video_frames' && (
            <p className="text-sm text-muted-foreground">
              {t(
                'Local AI checked sampled frames with the available caption and speech. Sampling does not inspect every frame.',
              )}
            </p>
          )}
          {c.input_kind === 'document_text' && (
            <p className="text-sm text-muted-foreground">
              {t(
                'Document text was checked. Unreadable or unchecked visual, embedded and dynamic content still requires review.',
              )}
            </p>
          )}
          <Scores scores={c.scores} />
        </div>
      ))}
    </div>
  )
}
import { t } from '../lib/i18n'
