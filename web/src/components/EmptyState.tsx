import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

/** An empty list is an invitation: say what belongs here and what to do next. */
export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <span className="grid size-12 place-items-center rounded-full bg-primary-soft text-primary">
        <Icon className="size-6" />
      </span>
      <p className="font-medium">{title}</p>
      {children && <p className="max-w-sm text-sm text-muted-foreground">{children}</p>}
      {action}
    </div>
  )
}
