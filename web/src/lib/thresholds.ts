import type { ThresholdRow } from './types'

export type Draft = Record<string, { low: string; high: string }>
export type Overrides = Record<string, { low: number; high: number }>

/** The pair a row currently shows: the typed draft if there is one, else the saved values. */
const num = (v: string) => (v.trim() === '' ? NaN : Number(v))

/** The pair a row currently shows: the typed draft if there is one (NaN while a field is blank). */
export function draftPair(r: ThresholdRow, draft: Draft) {
  const e = draft[r.category]
  return e ? { low: num(e.low), high: num(e.high) } : { low: r.low, high: r.high }
}

export function validPair(low: number, high: number) {
  return Number.isFinite(low) && Number.isFinite(high) && low >= 0 && high <= 1 && low < high
}

/**
 * The thresholds that differ from the defaults, null when nothing was edited, or 'invalid'
 * when any typed value cannot be used.
 */
export function overridesFrom(
  rows: ThresholdRow[] | undefined,
  draft: Draft,
): Overrides | null | 'invalid' {
  if (!rows || Object.keys(draft).length === 0) return null
  const out: Overrides = {}
  for (const r of rows) {
    const e = draft[r.category]
    const { low, high } = draftPair(r, draft)
    if ((e && (e.low.trim() === '' || e.high.trim() === '')) || !validPair(low, high))
      return 'invalid'
    if (low !== r.default_low || high !== r.default_high) out[r.category] = { low, high }
  }
  return out
}
