import { Eye, EyeOff } from 'lucide-react'
import type { ReactNode } from 'react'
import { t } from '../lib/i18n'
import { Button } from './ui/button'

/** The eye: shows or hides the content it belongs to. */
export function RevealButton({
  revealed,
  onToggle,
  label,
  context,
  className,
}: {
  revealed: boolean
  onToggle: () => void
  label?: string
  /** Tells screen-reader users which item the button belongs to, e.g. "message from Dan". */
  context?: string
  className?: string
}) {
  const Icon = revealed ? EyeOff : Eye
  const word = label ?? t('ui.contentLabel')
  const verb = revealed ? t('ui.hide', word) : t('ui.show', word)
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-label={context ? `${verb}, ${context}` : undefined}
      onClick={onToggle}
      className={className}
    >
      <Icon /> {verb}
    </Button>
  )
}

/** Same-length placeholder for hidden text. It carries none of the real characters. */
export function Masked({ length = 24 }: { length?: number }) {
  // Three sizes only, so a glance cannot tell a word from a sentence by the length of the mask.
  const n = length <= 30 ? 20 : length <= 120 ? 50 : 80
  const mask = Array.from({ length: Math.ceil(n / 5) }, () => '•••••').join(' ')
  return (
    <>
      <span aria-hidden className="select-none blur-[3px]">
        {mask}
      </span>
      <span className="sr-only">{t('ui.contentHidden')}</span>
    </>
  )
}

/** Shows `children` only when revealed; otherwise a mask of the same length (children not rendered). */
export function Concealed({
  revealed,
  length,
  children,
}: {
  revealed: boolean
  length?: number
  children: ReactNode
}) {
  return revealed ? <>{children}</> : <Masked length={length} />
}
