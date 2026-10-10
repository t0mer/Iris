import { Eye, EyeOff } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from './ui/button'

/** The eye: shows or hides the content it belongs to. */
export function RevealButton({
  revealed,
  onToggle,
  label = 'content',
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
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      title={revealed ? `Hide ${label}` : `Show ${label}`}
      aria-label={context ? `${revealed ? 'Hide' : 'Show'} ${label}, ${context}` : undefined}
      onClick={onToggle}
      className={className}
    >
      <Icon /> {revealed ? `Hide ${label}` : `Show ${label}`}
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
      <span className="sr-only">Content hidden</span>
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
