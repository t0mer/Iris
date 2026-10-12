import type { LucideIcon } from 'lucide-react'
import { Children, type ReactNode } from 'react'
import { t } from '../lib/i18n'

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
      <p className="font-medium">{t(title)}</p>
      {children && (
        <p className="max-w-sm text-sm text-muted-foreground">
          {Children.map(children, (child) => (typeof child === 'string' ? t(child) : child))}
        </p>
      )}
      {action}
    </div>
  )
}
