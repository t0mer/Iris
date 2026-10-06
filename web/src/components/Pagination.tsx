import { ChevronLeft, ChevronRight } from 'lucide-react'
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
  if (total <= pageSize)
    return total > 0 ? (
      <p className="text-sm text-muted-foreground">
        {total} {noun}
      </p>
    ) : null
  const from = (page - 1) * pageSize + 1
  const to = Math.min(page * pageSize, total)
  return (
    <nav aria-label="Pages" className="flex items-center justify-between gap-3">
      <p className="tabular text-sm text-muted-foreground">
        {from} to {to} of {total} {label}
      </p>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          <ChevronLeft className="rtl:rotate-180" /> Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Next <ChevronRight className="rtl:rotate-180" />
        </Button>
      </div>
    </nav>
  )
}
