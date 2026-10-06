import { cn } from '../lib/cn'

/** The Iris mark: a ring around an eye. Used as the logo and echoed by the dashboard status ring. */
export function IrisMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn('size-7', className)}>
      <circle cx="16" cy="16" r="12.5" fill="none" stroke="currentColor" strokeWidth="3" />
      <circle cx="16" cy="16" r="5.2" fill="currentColor" />
      <circle cx="18.2" cy="13.8" r="1.6" className="fill-background" />
    </svg>
  )
}
