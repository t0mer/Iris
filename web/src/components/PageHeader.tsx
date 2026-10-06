import { useEffect, type ReactNode } from 'react'

/** Every page opens with the same header: a title, one line saying what the page is for, and its actions. */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  useEffect(() => {
    document.title = `${title} · Iris`
  }, [title])
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-[28px]">{title}</h1>
        {description && <p className="max-w-prose text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
