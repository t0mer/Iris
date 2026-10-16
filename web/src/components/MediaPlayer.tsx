import { Download, FileX, Film, Image as ImageIcon, Mic } from 'lucide-react'
import { useState } from 'react'
import { fileSize } from '../lib/format'
import { strings, t } from '../lib/i18n'
import type { KeptMedia } from '../lib/types'
import { Badge } from './ui/badge'
import { Button } from './ui/button'

const ICON = { image: ImageIcon, audio: Mic, video: Film } as const
const LABEL = {
  image: strings.media.photo,
  audio: strings.media.voiceNote,
  video: strings.media.video,
} as const

/** A small "media kept" marker for lists. It is plain text: rows are links, so no nested link. */
export function MediaBadge({ media }: { media: KeptMedia }) {
  const Icon = ICON[media.kind]
  return (
    <Badge
      tone="info"
      title={t('media.keptWithSize', LABEL[media.kind], fileSize(media.size_bytes))}
    >
      <Icon /> {t('media.kept', LABEL[media.kind])}
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
        <Icon className="size-5" aria-hidden /> {t('media.hidden', LABEL[media.kind])}
      </div>
    )
  }
  if (failed)
    return (
      <p role="alert" className="flex items-center gap-2 text-sm text-muted-foreground">
        <FileX className="size-4" /> {t('media.loadFailed')}
      </p>
    )
  if (!media.inline)
    return (
      <Button asChild variant="outline" className="w-fit">
        <a href={src} download>
          <Download /> {t('media.download', LABEL[media.kind], fileSize(media.size_bytes))}
        </a>
      </Button>
    )
  if (media.kind === 'image')
    return (
      <img
        src={src}
        alt={t('media.photoAlt')}
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
