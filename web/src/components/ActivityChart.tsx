import { useEffect, useRef, useState } from 'react'
import { cn } from '../lib/cn'
import { shortDate } from '../lib/format'
import type { DayActivity } from '../lib/types'

const SERIES = [
  { key: 'safe', label: 'Fine', color: 'var(--chart-safe)' },
  { key: 'review', label: 'Worth a look', color: 'var(--chart-review)' },
  { key: 'harmful', label: 'Harmful', color: 'var(--chart-harmful)' },
] as const

const GAP = 2 // surface-coloured spacer between stacked segments
const H = 200
const PAD = { top: 12, right: 8, bottom: 28, left: 34 }

function useWidth(fallback = 640) {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => el.clientWidth > 0 && setW(el.clientWidth)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

const NICE = [4, 8, 10, 20, 40, 50, 100, 200, 400, 500, 1000, 2000, 5000]

function niceMax(n: number) {
  return NICE.find((v) => v >= n) ?? Math.ceil(n / 1000) * 1000
}

function total(d: DayActivity) {
  return d.safe + d.review + d.harmful
}

/** Messages per day, stacked by how Iris judged them. Only the plot is a picture; the numbers are also a table. */
export function ActivityChart({ days }: { days: DayActivity[] }) {
  const [ref, width] = useWidth()
  const [active, setActive] = useState<number | null>(null)
  const [table, setTable] = useState(false)

  const max = niceMax(Math.max(1, ...days.map(total)))
  const plotW = Math.max(width - PAD.left - PAD.right, 10)
  const plotH = H - PAD.top - PAD.bottom
  const step = plotW / Math.max(days.length, 1)
  const barW = Math.min(Math.max(step * 0.56, 6), 30)
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH
  const labelEvery = step < 34 ? 3 : step < 52 ? 2 : 1
  const peak = days.reduce((a, d) => (total(d) > total(a) ? d : a), days[0])
  const summary = `Messages per day over the last ${days.length} days. ${
    total(peak)
      ? `Busiest day ${shortDate(peak.date)} with ${total(peak)} messages, ${peak.harmful} harmful.`
      : 'No messages yet.'
  }`
  const hover = active === null ? null : days[active]

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {SERIES.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span aria-hidden className="size-3 rounded-[3px]" style={{ background: s.color }} />
              {s.label}
            </li>
          ))}
        </ul>
        <button
          className="min-h-9 rounded-md px-2 text-sm font-medium text-primary hover:bg-primary-soft"
          aria-pressed={table}
          onClick={() => setTable((t) => !t)}
        >
          {table ? 'Show chart' : 'Show as table'}
        </button>
      </div>

      {table ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{summary}</caption>
            <thead>
              <tr className="text-start text-muted-foreground">
                <th className="py-1.5 pe-3 text-start font-medium">Day</th>
                {SERIES.map((s) => (
                  <th key={s.key} className="px-3 py-1.5 text-end font-medium">
                    {s.label}
                  </th>
                ))}
                <th className="px-3 py-1.5 text-end font-medium">Not checked</th>
                <th className="ps-3 py-1.5 text-end font-medium">Alerts</th>
              </tr>
            </thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.date} className="border-t">
                  <th scope="row" className="py-1.5 pe-3 text-start font-normal">
                    {shortDate(d.date)}
                  </th>
                  {SERIES.map((s) => (
                    <td key={s.key} className="tabular px-3 py-1.5 text-end">
                      {d[s.key]}
                    </td>
                  ))}
                  <td className="tabular px-3 py-1.5 text-end text-muted-foreground">{d.other}</td>
                  <td className="tabular ps-3 py-1.5 text-end">{d.alerts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div ref={ref} className="relative">
          <svg width="100%" height={H} role="img" aria-label={summary} className="overflow-visible">
            {[0, 0.5, 1].map((f) => (
              <g key={f}>
                <line
                  x1={PAD.left}
                  x2={width - PAD.right}
                  y1={y(max * f)}
                  y2={y(max * f)}
                  stroke="var(--border)"
                  strokeWidth="1"
                  strokeDasharray={f === 0 ? undefined : '3 4'}
                />
                <text
                  x={PAD.left - 8}
                  y={y(max * f) + 4}
                  textAnchor="end"
                  fontSize="11"
                  fill="var(--muted-foreground)"
                  className="tabular"
                >
                  {Math.round(max * f)}
                </text>
              </g>
            ))}
            {days.map((d, i) => {
              const cx = PAD.left + step * i + step / 2
              let acc = 0
              const segs = SERIES.map((s) => {
                const v = d[s.key]
                const y1 = y(acc + v)
                const h = y(acc) - y1
                acc += v
                return { s, v, y1, h }
              }).filter((x) => x.v > 0)
              return (
                <g
                  key={d.date}
                  tabIndex={0}
                  role="img"
                  aria-label={`${shortDate(d.date)}: ${d.safe} fine, ${d.review} worth a look, ${d.harmful} harmful`}
                  onMouseEnter={() => setActive(i)}
                  onMouseLeave={() => setActive(null)}
                  onFocus={() => setActive(i)}
                  onBlur={() => setActive(null)}
                  className="outline-none [&:focus-visible_.hit]:stroke-ring"
                >
                  <rect
                    className="hit"
                    x={cx - step / 2}
                    y={PAD.top}
                    width={step}
                    height={plotH}
                    fill="transparent"
                    stroke="transparent"
                    strokeWidth="2"
                    rx="4"
                  />
                  {segs.map((g, k) => {
                    const topmost = k === segs.length - 1
                    const h = Math.max(g.h - (k > 0 ? GAP : 0), 1)
                    return (
                      <rect
                        key={g.s.key}
                        x={cx - barW / 2}
                        y={g.y1}
                        width={barW}
                        height={h}
                        rx={topmost ? Math.min(4, barW / 2) : 0}
                        fill={g.s.color}
                        opacity={active === null || active === i ? 1 : 0.55}
                      />
                    )
                  })}
                  {i % labelEvery === 0 && (
                    <text
                      x={cx}
                      y={H - 8}
                      textAnchor="middle"
                      fontSize="11"
                      fill="var(--muted-foreground)"
                    >
                      {shortDate(d.date)}
                    </text>
                  )}
                </g>
              )
            })}
          </svg>
          {hover && (
            <div
              role="status"
              className={cn(
                'pointer-events-none absolute top-0 z-10 w-44 rounded-md border bg-surface p-2.5 text-xs shadow-overlay',
              )}
              style={{
                left: Math.min(
                  Math.max(PAD.left + step * (active ?? 0) + step / 2 - 88, 0),
                  Math.max(width - 176, 0),
                ),
              }}
            >
              <p className="mb-1 text-sm font-medium">{shortDate(hover.date)}</p>
              {SERIES.map((s) => (
                <p key={s.key} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5">
                    <span
                      aria-hidden
                      className="size-2.5 rounded-[2px]"
                      style={{ background: s.color }}
                    />
                    {s.label}
                  </span>
                  <span className="tabular">{hover[s.key]}</span>
                </p>
              ))}
              {hover.other > 0 && (
                <p className="mt-1 flex justify-between text-muted-foreground">
                  <span>Not checked</span>
                  <span className="tabular">{hover.other}</span>
                </p>
              )}
              <p className="mt-1 flex justify-between border-t pt-1">
                <span>Alerts sent</span>
                <span className="tabular">{hover.alerts}</span>
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
