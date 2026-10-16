import { ChevronLeft, ChevronRight } from 'lucide-react'
import { t } from '../lib/i18n'
import { Button } from './ui/button'

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
  noun,
}: {
  page: number
  pageSize: number
  total: number
  onPage: (p: number) => void
  /** Singular and plural, e.g. ['message', 'messages']. */
  noun: [string, string]
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const label = total === 1 ? noun[0] : noun[1]
  if (total <= pageSize && page <= 1)
    return total > 0 ? (
      <p className="text-sm text-muted-foreground">
        {total} {label}
      </p>
    ) : null
  const from = (page - 1) * pageSize + 1
  const pastEnd = from > total
  const to = Math.min(page * pageSize, total)
  return (
    <nav aria-label={t('ui.pagesNav')} className="flex items-center justify-between gap-3">
      <p className="tabular text-sm text-muted-foreground">
        {pastEnd ? t('ui.noneOnPage', page, total, label) : t('ui.rangeOf', from, to, total, label)}
      </p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft className="rtl:rotate-180" /> {t('ui.previous')}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          {t('ui.next')} <ChevronRight className="rtl:rotate-180" />
        </Button>
      </div>
    </nav>
  )
}
