import { cn } from '../lib/cn'

const R = 52
const C = 2 * Math.PI * R

interface Props {
  alerts: number
  review: number
  className?: string
}

/**
 * The dashboard's one bold element: a ring in the shape of the logo. Calm is a full violet ring;
 * open alerts are coral arcs and items to review saffron arcs, sized by how many there are.
 */
export function IrisRing({ alerts, review, className }: Props) {
  const total = alerts + review
  const both = alerts > 0 && review > 0
  const gap = both ? 16 : 0 // round caps eat into the visible gap, so leave room
  const usable = C - gap * (both ? 2 : 0)
  const alertLen = total ? (usable * alerts) / total : 0
  const reviewLen = total ? (usable * review) / total : 0
  // Each arc is placed by rotating it to its start angle, so its dash pattern is just "length, rest"
  // and the draw-in animation only has to move the dash offset.
  const arc = (len: number, start: number, color: string, key: string) =>
    len > 0 && (
      <circle
        key={key}
        cx="60"
        cy="60"
        r={R}
        fill="none"
        stroke={color}
        strokeWidth="9"
        strokeLinecap={key === 'calm' ? 'butt' : 'round'}
        strokeDasharray={`${key === 'calm' ? len : Math.max(len - 9, 0.01)} ${C}`}
        className="iris-arc"
        style={{ ['--len' as string]: `${len}` }}
        transform={`rotate(${-90 + (start / C) * 360 + (key === 'calm' ? 0 : (9 / 2 / C) * 360)} 60 60)`}
      />
    )
  return (
    <svg
      viewBox="0 0 120 120"
      role="img"
      aria-label={total ? `${total} need your attention` : 'Nothing needs your attention'}
      className={cn('size-36 shrink-0 sm:size-44', className)}
    >
      <circle cx="60" cy="60" r={R} fill="none" stroke="var(--surface-2)" strokeWidth="9" />
      {total === 0 && arc(C, 0, 'var(--primary)', 'calm')}
      {total > 0 && arc(alertLen, gap / 2, 'var(--danger)', 'alerts')}
      {total > 0 && arc(reviewLen, gap / 2 + alertLen + gap, 'var(--chart-review)', 'review')}
      <circle cx="60" cy="60" r="32" fill="var(--primary-soft)" />
      <circle cx="60" cy="60" r="13" fill="var(--primary)" />
      <circle cx="65" cy="55" r="4" fill="var(--surface)" />
    </svg>
  )
}
