export type Band = 'safe' | 'inconclusive' | 'harmful'
export type Verdict = 'safe' | 'review' | 'harmful'
export type Pair = { low: number; high: number }

// Categories the provider adds later use the general pair, like the server does.
const GENERAL: Pair = { low: 0.2, high: 0.7 }

/** Mirror of app/classify/thresholds.py band_for: a score at or above a limit counts. */
export function bandFor(scores: Record<string, number>, thresholds: Record<string, Pair>) {
  const high: string[] = []
  const low: string[] = []
  for (const [cat, score] of Object.entries(scores)) {
    const t = thresholds[cat] ?? GENERAL
    if (score >= t.high) high.push(cat)
    if (score >= t.low) low.push(cat)
  }
  const band: Band = high.length ? 'harmful' : low.length ? 'inconclusive' : 'safe'
  return { band, high, low }
}

/** The final verdict: an unclear first check is settled by the second look, else it needs review. */
export function verdictFor(first: Band, second?: Band): Verdict {
  if (first !== 'inconclusive') return first
  return second && second !== 'inconclusive' ? second : 'review'
}
