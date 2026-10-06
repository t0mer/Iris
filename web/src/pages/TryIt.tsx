import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, RotateCcw, Save } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { PageHeader } from '../components/PageHeader'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Field, Input, Textarea } from '../components/ui/field'
import { api, ApiError } from '../lib/api'
import { bandFor, verdictFor, type Band, type Pair, type Verdict } from '../lib/bands'
import { cn } from '../lib/cn'
import { draftPair, overridesFrom, validPair, type Draft } from '../lib/thresholds'
import type { ThresholdRow } from '../lib/types'

interface Stage {
  stage: string
  scores: Record<string, number>
}
interface Result {
  model: string
  stages: Stage[]
  thresholds: ThresholdRow[]
}

const BAND: Record<Band, { label: string; tone: 'success' | 'warning' | 'danger' }> = {
  safe: { label: 'Fine', tone: 'success' },
  inconclusive: { label: 'Unclear', tone: 'warning' },
  harmful: { label: 'Harmful', tone: 'danger' },
}
const VERDICT: Record<Verdict, { title: string; text: string; tone: string }> = {
  safe: {
    title: 'Fine',
    text: 'Iris would let this through.',
    tone: 'border-success/40 bg-success-soft',
  },
  review: {
    title: 'Needs a look',
    text: 'Iris would put this in the review queue.',
    tone: 'border-warning/40 bg-warning-soft',
  },
  harmful: {
    title: 'Harmful',
    text: 'Iris would alert you.',
    tone: 'border-danger/40 bg-danger-soft',
  },
}

export function TryIt() {
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const [context, setContext] = useState('')
  const [draft, setDraft] = useState<Draft>({})
  const [result, setResult] = useState<Result | null>(null)

  const check = useMutation({
    mutationFn: () =>
      api<Result>('/api/classify/test', {
        method: 'POST',
        body: JSON.stringify({
          text: text.trim(),
          context: context
            .split('\n')
            .map((l) => l.trim())
            .filter(Boolean),
        }),
      }),
    onSuccess: (r) => {
      setResult(r)
      setDraft({})
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not check the text.'),
  })

  const save = useMutation({
    mutationFn: (overrides: Record<string, Pair>) =>
      api('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ settings: { 'classification.thresholds': overrides } }),
      }),
    onSuccess: async () => {
      toast.success('Thresholds saved.')
      // What was previewed is now what is saved; keep the result on screen without a new check.
      setResult((r) =>
        r
          ? {
              ...r,
              thresholds: r.thresholds.map((t) => ({ ...t, ...draftPair(t, draft) })),
            }
          : r,
      )
      setDraft({})
      await qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not save thresholds.'),
  })

  const current = useMemo(() => {
    const out: Record<string, Pair> = {}
    for (const r of result?.thresholds ?? []) out[r.category] = draftPair(r, draft)
    return out
  }, [result, draft])

  const stages = useMemo(
    () => (result?.stages ?? []).map((s) => ({ ...s, ...bandFor(s.scores, current) })),
    [result, current],
  )
  const verdict = stages.length ? verdictFor(stages[0].band, stages[1]?.band) : null
  const rows = useMemo(
    () =>
      [...(result?.thresholds ?? [])].sort(
        (a, b) =>
          Math.max(...stages.map((s) => s.scores[b.category] ?? 0), 0) -
          Math.max(...stages.map((s) => s.scores[a.category] ?? 0), 0),
      ),
    [result, stages],
  )
  const overrides = overridesFrom(result?.thresholds, draft)
  const changedFromSaved =
    result?.thresholds.some((r) => {
      const p = draftPair(r, draft)
      return p.low !== r.low || p.high !== r.high
    }) ?? false

  function edit(r: ThresholdRow, field: 'low' | 'high', value: string) {
    setDraft((d) => {
      const e = d[r.category] ?? { low: String(r.low), high: String(r.high) }
      return { ...d, [r.category]: { ...e, [field]: value } }
    })
  }

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <PageHeader
        title="Try it"
        description="Type a message to see how Iris would classify it, then adjust the thresholds and watch the result change."
      />
      <form
        className="flex flex-col gap-4 rounded-lg border bg-surface p-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (text.trim()) check.mutate()
        }}
      >
        <Field label="Message to check">
          <Textarea
            dir="auto"
            rows={3}
            maxLength={4000}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </Field>
        <Field
          label="Earlier messages in the chat (optional)"
          hint="One per line, oldest first. Iris uses them for the second look when the first check is unclear."
        >
          <Textarea
            dir="auto"
            rows={3}
            value={context}
            onChange={(e) => setContext(e.target.value)}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!text.trim() || check.isPending}>
            <FlaskConical /> {check.isPending ? 'Checking…' : 'Check'}
          </Button>
          <p className="text-xs text-muted-foreground">
            The text is sent to OpenAI for moderation and is not stored by Iris.
          </p>
        </div>
      </form>

      {result && verdict && (
        <>
          <section
            aria-live="polite"
            className={cn('flex flex-col gap-1 rounded-lg border p-4', VERDICT[verdict].tone)}
          >
            <h2 className="text-lg font-semibold">{VERDICT[verdict].title}</h2>
            <p className="text-sm">{VERDICT[verdict].text}</p>
            <ul className="mt-1 flex flex-wrap gap-2 text-sm">
              {stages.map((s) => (
                <li key={s.stage} className="flex items-center gap-1.5">
                  {s.stage === 'moderation' ? 'First check' : 'Second look'}
                  <Badge tone={BAND[s.band].tone}>{BAND[s.band].label}</Badge>
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="th" className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 id="th" className="text-lg font-semibold">
                  Thresholds
                </h2>
                <p className="text-sm text-muted-foreground">
                  A score at or above <b>needs a look</b> is unclear; at or above <b>harmful</b> it
                  alerts you. Changes here are only a preview until you save.
                </p>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  type="button"
                  disabled={!changedFromSaved}
                  onClick={() => setDraft({})}
                >
                  <RotateCcw /> Reset to saved
                </Button>
                <Button
                  type="button"
                  disabled={!changedFromSaved || save.isPending}
                  onClick={() => {
                    if (overrides === 'invalid') {
                      toast.error(
                        'Thresholds must be numbers from 0 to 1, with "needs a look" lower than "harmful".',
                      )
                      return
                    }
                    save.mutate(overrides ?? {})
                  }}
                >
                  <Save /> Save these thresholds
                </Button>
              </div>
            </div>
            <ul className="flex flex-col divide-y rounded-lg border bg-surface">
              {rows.map((r) => {
                const p = draftPair(r, draft)
                const e = draft[r.category]
                const ok = validPair(p.low, p.high)
                return (
                  <li
                    key={r.category}
                    className="grid grid-cols-1 items-center gap-2 p-3 sm:grid-cols-[11rem_1fr_9rem_9rem]"
                  >
                    <span className="text-sm font-medium">{r.category}</span>
                    <div className="flex flex-col gap-1">
                      {stages.map((s) => {
                        const v = s.scores[r.category] ?? 0
                        const b = ok ? bandFor({ [r.category]: v }, { [r.category]: p }).band : null
                        return (
                          <div key={s.stage} className="flex items-center gap-2">
                            <span
                              className="relative h-2 flex-1 rounded-full bg-surface-2"
                              aria-hidden
                            >
                              <span
                                className="absolute inset-y-0 start-0 rounded-full bg-primary"
                                style={{ width: `${Math.round(v * 100)}%` }}
                              />
                              {ok && (
                                <>
                                  <span
                                    className="absolute -inset-y-0.5 w-0.5 bg-warning"
                                    style={{ insetInlineStart: `${p.low * 100}%` }}
                                  />
                                  <span
                                    className="absolute -inset-y-0.5 w-0.5 bg-danger"
                                    style={{ insetInlineStart: `${p.high * 100}%` }}
                                  />
                                </>
                              )}
                            </span>
                            <span className="tabular w-10 text-end text-sm">{v.toFixed(2)}</span>
                            {b && (
                              <Badge tone={BAND[b].tone} className="w-16 justify-center">
                                {BAND[b].label}
                              </Badge>
                            )}
                          </div>
                        )
                      })}
                    </div>
                    <Field label="Needs a look">
                      <Input
                        className="tabular"
                        type="number"
                        step="0.01"
                        min={0}
                        max={1}
                        value={e?.low ?? String(r.low)}
                        aria-label={`${r.category} needs a look`}
                        aria-invalid={!ok}
                        onChange={(ev) => edit(r, 'low', ev.target.value)}
                      />
                    </Field>
                    <Field label="Harmful">
                      <Input
                        className="tabular"
                        type="number"
                        step="0.01"
                        min={0}
                        max={1}
                        value={e?.high ?? String(r.high)}
                        aria-label={`${r.category} harmful`}
                        aria-invalid={!ok}
                        onChange={(ev) => edit(r, 'high', ev.target.value)}
                      />
                    </Field>
                  </li>
                )
              })}
            </ul>
            <p className="text-sm text-muted-foreground">
              Every threshold is also listed under{' '}
              <Link className="font-medium text-primary" to="/settings">
                Settings
              </Link>
              .
            </p>
          </section>
        </>
      )}
    </div>
  )
}
