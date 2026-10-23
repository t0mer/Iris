import {
  BarChart3,
  FileText,
  Headphones,
  Image,
  Mic,
  Smile,
  MessageSquare,
  Video,
  CircleHelp,
  type LucideIcon,
} from 'lucide-react'

const ICONS: Record<string, LucideIcon> = {
  poll: BarChart3,
  text: MessageSquare,
  image: Image,
  audio: Headphones,
  voice: Mic,
  video: Video,
  sticker: Smile,
  document: FileText,
}

/** An icon for a message type, with its name for screen readers. */
export function TypeIcon({ type, className }: { type: string; className?: string }) {
  const Icon = ICONS[type] ?? CircleHelp
  return (
    <>
      <Icon aria-hidden className={className ?? 'size-4'} />
      <span className="sr-only">{t(type)}</span>
    </>
  )
}
import { t } from '../lib/i18n'
