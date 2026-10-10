import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import { Section } from '../components/Section'
import { Button } from '../components/ui/button'
import { QueryError } from '../components/QueryError'

type Example = { message_id: number; verdict: string; enabled: boolean; source_valid: boolean }
type Metric = {
  false_positive: number
  false_negative: number
  review: number
  precision: number | null
  harmful_detection_rate: number | null
}
type Run = {
  id: number
  message_id: number
  baseline_verdict: string
  candidate_verdict: string | null
  error: string | null
  example_ids: number[]
  retrieval?: { actual: string; embedding_model: string | null; fallback: string | null } | null
}
type Runs = {
  summary: { sampled_runs: number; reviewed_messages: number; baseline: Metric; candidate: Metric }
  items: Run[]
}

export function LearningSettings() {
  const [importCursor, setImportCursor] = useState(0)
  const qc = useQueryClient()
  const examples = useQuery({
    queryKey: ['learning', 'examples'],
    queryFn: () => api<{ items: Example[] }>('/api/learning/examples'),
  })
  const runs = useQuery({
    queryKey: ['learning', 'runs'],
    queryFn: () => api<Runs>('/api/learning/runs'),
  })
  const refresh = () => qc.invalidateQueries({ queryKey: ['learning'] })
  const update = useMutation({
    mutationFn: (example: Example) =>
      api(`/api/learning/examples/${example.message_id}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled: !example.enabled }),
      }),
    onSuccess: refresh,
    onError: (e) => toast.error(e.message),
  })
  const importReviews = useMutation({
    mutationFn: () =>
      api<{ imported: number; next_cursor: number }>(
        `/api/learning/examples/import?after=${importCursor}`,
        { method: 'POST' },
      ),
    onSuccess: (result) => {
      toast.success(`Imported ${result.imported} reviewed text examples.`)
      setImportCursor(result.next_cursor)
      void refresh()
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <Section
      title="Learning evidence"
      description="Safe and Harmful reviews supply overall labels. Ignore and missing-data reports do not teach the model. Examples stay with their source messages and disappear when those messages are deleted."
    >
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={() => importReviews.mutate()}
          disabled={importReviews.isPending}
        >
          Import existing reviewed text
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            void examples.refetch()
            void runs.refetch()
          }}
        >
          Refresh learning evidence
        </Button>
      </div>
      {examples.isError && (
        <QueryError what="learning examples" onRetry={() => void examples.refetch()} />
      )}
      {runs.isError && (
        <QueryError what="learning comparisons" onRetry={() => void runs.refetch()} />
      )}
      {examples.data && (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">
            Latest {examples.data.items.length} examples. Retrieval uses the method selected above
            and only messages belonging to the same monitored children.
          </p>
          {examples.data.items.map((e) => (
            <div key={e.message_id} className="flex items-center justify-between gap-2 text-sm">
              <span>
                <Link to={`/messages/${e.message_id}`}>Message #{e.message_id}</Link> · {e.verdict}{' '}
                · {e.source_valid ? 'source available' : 'source changed or unavailable'}
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={update.isPending}
                onClick={() => update.mutate(e)}
              >
                {e.enabled ? 'Exclude example' : 'Include example'}
              </Button>
            </div>
          ))}
        </div>
      )}
      {runs.data && (
        <>
          <p className="text-sm text-muted-foreground">
            Latest {runs.data.summary.sampled_runs} comparisons;{' '}
            {runs.data.summary.reviewed_messages} distinct messages with human labels. These are
            operational comparisons, not a held-out accuracy benchmark.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-left">Result</th>
                  <th>False alerts</th>
                  <th>Missed harm</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {(['baseline', 'candidate'] as const).map((name) => (
                  <tr key={name}>
                    <td>{name === 'baseline' ? 'Current classifier' : 'With examples'}</td>
                    <td className="text-center">{runs.data!.summary[name].false_positive}</td>
                    <td className="text-center">{runs.data!.summary[name].false_negative}</td>
                    <td className="text-center">{runs.data!.summary[name].review}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {runs.data.items.slice(0, 10).map((r) => (
            <p key={r.id} className="text-sm">
              <Link to={`/messages/${r.message_id}`}>Message #{r.message_id}</Link>:{' '}
              {r.baseline_verdict} → {r.candidate_verdict ?? 'failed'} · examples{' '}
              {r.example_ids.join(', ')}
              {r.error ? ` · ${r.error}` : ''}
              {r.retrieval
                ? ` · ${r.retrieval.actual}${r.retrieval.embedding_model ? ` (${r.retrieval.embedding_model})` : ''}${r.retrieval.fallback ? ` · fallback: ${r.retrieval.fallback}` : ''}`
                : ''}
            </p>
          ))}
        </>
      )}
    </Section>
  )
}
