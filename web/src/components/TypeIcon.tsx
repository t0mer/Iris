import {
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
import { strings } from '../lib/i18n'

const ICONS: Record<string, LucideIcon> = {
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
  const label = (strings.messageTypes as Record<string, string>)[type] ?? type
  return (
    <>
      <Icon aria-hidden className={className ?? 'size-4'} />
      <span className="sr-only">{label}</span>
    </>
  )
}
