import { t } from '../lib/i18n'
import { Download, FileX, Film, Image as ImageIcon, Mic } from 'lucide-react'
import { useState } from 'react'
import { fileSize } from '../lib/format'
import type { KeptMedia } from '../lib/types'
import { Badge } from './ui/badge'
import { Button } from './ui/button'

const ICON = { image: ImageIcon, audio: Mic, video: Film } as const
const LABEL = { image: 'Photo', audio: 'Voice note', video: 'Video' } as const

/** A small "media kept" marker for lists. It is plain text: rows are links, so no nested link. */
export function MediaBadge({ media }: { media: KeptMedia }) {
  const Icon = ICON[media.kind]
  return (
    <Badge
      tone="info"
      title={t('{value0} kept, {value1}', {
        value0: t(LABEL[media.kind]),
        value1: fileSize(media.size_bytes),
      })}
    >
      <Icon /> {t(LABEL[media.kind])} {t('kept')}
    </Badge>
  )
}

/**
 * Shows kept media from Iris itself (the file is only served to a signed-in owner). Hidden
 * unless `revealed`: nothing is requested until then.
 */
export function MediaPlayer({
  media,
  revealed = false,
  className,
}: {
  media: KeptMedia
  revealed?: boolean
  className?: string
}) {
  const src = `/api/media/${media.id}`
  const [failed, setFailed] = useState(false)
  if (!revealed) {
    const Icon = ICON[media.kind]
    return (
      <div className="flex min-h-32 w-full max-w-md items-center justify-center gap-2 rounded-lg border bg-surface-2 p-6 text-sm text-muted-foreground">
        <Icon className="size-5" aria-hidden /> {t(LABEL[media.kind])} {t('hidden')}
      </div>
    )
  }
  if (failed)
    return (
      <p role="alert" className="flex items-center gap-2 text-sm text-muted-foreground">
        <FileX className="size-4" />{' '}
        {t('This file could not be loaded. It may have been deleted from the storage.')}
      </p>
    )
  if (!media.inline)
    return (
      <Button asChild variant="outline" className="w-fit">
        <a href={src} download>
          <Download /> {t('Download the')} {t(LABEL[media.kind].toLowerCase())} (
          {fileSize(media.size_bytes)})
        </a>
      </Button>
    )
  if (media.kind === 'image')
    return (
      <img
        src={src}
        alt="The photo kept from this message"
        onError={() => setFailed(true)}
        className={
          className ?? 'max-h-[70dvh] max-w-full rounded-lg border bg-surface-2 object-contain'
        }
      />
    )
  if (media.kind === 'audio')
    return (
      // eslint-disable-next-line jsx-a11y/media-has-caption -- a voice note has no captions to offer
      <audio
        controls
        preload="metadata"
        src={src}
        className="w-full max-w-md"
        onError={() => setFailed(true)}
      />
    )
  return (
    // eslint-disable-next-line jsx-a11y/media-has-caption -- the transcript is on the message
    <video
      controls
      playsInline
      preload="metadata"
      src={src}
      onError={() => setFailed(true)}
      className={className ?? 'max-h-[70dvh] max-w-full rounded-lg border bg-black'}
    />
  )
}
