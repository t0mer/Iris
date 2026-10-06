import { CircleAlert } from 'lucide-react'
import { Badge } from './ui/badge'

/** Category score bars (0 to 1). `_meta` is bookkeeping, not a score. */
export function Scores({ scores, min = 0.02 }: { scores: Record<string, unknown>; min?: number }) {
  const rows = Object.entries(scores)
    .filter(([k, v]) => k !== '_meta' && typeof v === 'number' && v >= min)
    .sort((a, b) => (b[1] as number) - (a[1] as number))
  if (rows.length === 0)
    return <p className="text-sm text-muted-foreground">No category scored above {min}.</p>
  return (
    <ul className="flex flex-col gap-2.5">
      {rows.map(([cat, v]) => (
        <li
          key={cat}
          className="grid grid-cols-[minmax(0,9.5rem)_1fr_2.5rem] items-center gap-3 text-sm sm:grid-cols-[12rem_1fr_2.5rem]"
        >
          <span className="truncate" title={cat}>
            {cat}
          </span>
          <span className="h-2 rounded-full bg-surface-2" aria-hidden>
            <span
              className="block h-2 rounded-full bg-primary"
              style={{ width: `${Math.round((v as number) * 100)}%` }}
            />
          </span>
          <span className="tabular text-end">{(v as number).toFixed(2)}</span>
        </li>
      ))}
    </ul>
  )
}

export function CategoryChips({ categories, score }: { categories: string[]; score?: number }) {
  return (
    <span className="flex flex-wrap gap-1.5">
      {categories.map((c, i) => (
        <Badge key={c} tone={i === 0 ? 'danger' : 'neutral'}>
          {i === 0 && <CircleAlert />}
          {c}
          {i === 0 && score !== undefined ? (
            <span className="tabular"> {score.toFixed(2)}</span>
          ) : (
            ''
          )}
        </Badge>
      ))}
    </span>
  )
}
