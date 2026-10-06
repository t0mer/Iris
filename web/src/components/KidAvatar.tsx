import { cn } from '../lib/cn'

// Soft tints, assigned by name so a kid keeps the same colour everywhere.
const TINTS = [
  'bg-primary-soft text-primary',
  'bg-success-soft text-success',
  'bg-warning-soft text-warning',
  'bg-danger-soft text-danger',
  'bg-surface-2 text-foreground',
]

function tint(name: string) {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)!) >>> 0
  return TINTS[h % TINTS.length]
}

export function KidAvatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold',
        tint(name),
        className,
      )}
    >
      {[...name.trim()][0]?.toUpperCase() ?? '?'}
    </span>
  )
}

/** Overlapping avatars for the kids on one message or alert. */
export function KidStack({ names }: { names: string[] }) {
  return (
    <span className="flex shrink-0 -space-x-2 rtl:space-x-reverse">
      {names.slice(0, 3).map((n) => (
        <KidAvatar key={n} name={n} className="ring-2 ring-surface" />
      ))}
    </span>
  )
}
