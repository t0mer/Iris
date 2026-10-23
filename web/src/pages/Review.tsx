import { t } from '../lib/i18n'
import { Pagination } from '../components/Pagination'
import { SkipGroup } from '../components/SkipGroup'
import { useUrlState } from '../lib/urlState'
import { ConfirmDialog } from '../components/ui/dialog'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  CircleHelp,
  ListChecks,
  MessagesSquare,
  ShieldAlert,
  RotateCcw,
  Copy,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from '../lib/notify'
import { EmptyState } from '../components/EmptyState'
import { KidStack } from '../components/KidAvatar'
import { MessageFlags } from '../components/MessageFlags'
import { revokedClass } from '../lib/revoked'
import { RevealableMessage } from '../components/MessageBody'
import { PageHeader } from '../components/PageHeader'
import { Scores } from '../components/Scores'
import { Button } from '../components/ui/button'
import { Skeleton } from '../components/ui/skeleton'
import { api, ApiError } from '../lib/api'
import { cn } from '../lib/cn'
import { relativeTime } from '../lib/format'
import type { Message, ReviewPage } from '../lib/types'
import { useMe } from '../lib/auth'
import { QueryError } from '../components/QueryError'
import { useState } from 'react'
import { ReviewDetails, type ReviewDraft } from '../components/ReviewDetails'

const reviewKinds: Record<string, string> = {
  uncertain: 'Uncertain classification',
  attachment: 'Attachment check',
  technical: 'Technical issue',
  unavailable: 'Unavailable content',
}

export function Review() {
  const [drafts, setDrafts] = useState<Record<number, ReviewDraft>>({})
  const { get, page, update } = useUrlState()
  const view =
    get('view') === 'responses'
      ? 'responses'
      : get('view') === 'missing_data'
        ? 'missing_data'
        : 'pending'
  const pageSize = 25
  const reason = view === 'pending' && reviewKinds[get('reason')] ? get('reason') : 'all'
  const qc = useQueryClient()
  const { data: me } = useMe()
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['review', view, page, reason],
    queryFn: () =>
      api<ReviewPage>(
        `/api/review?page=${page}&page_size=${pageSize}&view=${view}${reason === 'all' ? '' : `&reason=${reason}`}`,
      ),
    refetchInterval: 15_000,
  })
  const purge = useMutation({
    mutationFn: () => api('/api/media', { method: 'DELETE' }),
    onSuccess: () => {
      toast.success('Saved media scheduled for deletion.')
      return qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not delete media.'),
  })
  const resolve = useMutation({
    mutationFn: (v: { id: number; resolution: 'safe' | 'harmful' | 'missing_data' }) =>
      api(`/api/review/${v.id}${v.resolution === 'missing_data' ? '/data-issue' : ''}`, {
        method: 'POST',
        body: JSON.stringify(
          v.resolution === 'missing_data'
            ? { issue: 'missing_data' }
            : {
                resolution: v.resolution,
                ...(drafts[v.id]?.explanation ? { explanation: drafts[v.id].explanation } : {}),
                ...(v.resolution === 'harmful' && drafts[v.id]?.categories.length
                  ? { categories: drafts[v.id].categories }
                  : {}),
              },
        ),
      }),
    onSuccess: (_d, v) => {
      toast.success(
        v.resolution === 'missing_data'
          ? 'Ignored because data is missing. Saved for later design review.'
          : v.resolution === 'safe'
            ? 'Marked safe.'
            : 'Marked harmful. An alert was created.',
      )
      return qc.invalidateQueries()
    },
    onError: (e) =>
      toast.error(e instanceof ApiError ? e.message : 'Could not save your decision. Try again.'),
  })
  const judgeAgain = useMutation({
    mutationFn: (id: number) => api(`/api/messages/${id}/reprocess`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('AI judgment queued. Review and the dashboard update when it completes.')
      return qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not queue AI judgment.'),
  })
  const rejudging = (m: Message) =>
    (recoverMedia.isPending && recoverMedia.variables === m.id) ||
    (judgeAgain.isPending && judgeAgain.variables === m.id) ||
    ['pending', 'processing'].includes(m.status)
  const recoverMedia = useMutation({
    mutationFn: (id: number) => api(`/api/messages/${id}/recover-media`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Media recovery queued. Iris will check recovered content before deciding.')
      return qc.invalidateQueries()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not queue media recovery.'),
  })
  async function copyTrace(id: number) {
    try {
      const trace = await api<unknown>(`/api/review/${id}/trace`)
      await navigator.clipboard.writeText(JSON.stringify(trace, null, 2))
      toast.success('Full saved trace copied to clipboard.')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not copy the trace.')
    }
  }
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <PageHeader
        title={t('Review')}
        description={t(
          'Human review: messages ready for your Safe or Harmful decision. Messages still being checked by AI are in IrisReview. Reviewed text can guide future Ollama checks when learning is enabled.',
        )}
      />
      <Link to="/iris-review" className="text-sm text-primary">
        {t('Open IrisReview AI queue')}
      </Link>
      {['admin', 'parent'].includes(me?.role || '') && (
        <ConfirmDialog
          trigger={
            <Button variant="outline" disabled={purge.isPending}>
              {t('Delete all saved media evidence')}
            </Button>
          }
          title={t('Delete all saved media evidence?')}
          description={t(
            'This permanently removes all saved media copies. Message records and review decisions remain.',
          )}
          confirmLabel={t('Delete media')}
          onConfirm={() => purge.mutateAsync().then(() => undefined)}
        />
      )}
      <div className="flex flex-wrap gap-2" aria-label={t('Review views')}>
        <Button
          variant={view === 'pending' ? 'primary' : 'outline'}
          onClick={() => update({ view: '' })}
        >
          {t('Awaiting review')}
        </Button>
        <Button
          variant={view === 'missing_data' ? 'primary' : 'outline'}
          onClick={() => update({ view: 'missing_data' })}
        >
          {t('Unavailable content')}
        </Button>
        <Button
          variant={view === 'responses' ? 'primary' : 'outline'}
          onClick={() => update({ view: 'responses' })}
        >
          {t('Parent responses & notes')}
        </Button>
      </div>
      {view === 'missing_data' && (
        <p className="text-sm text-muted-foreground">
          {t(
            'Unavailable content is kept here for recovery. These messages have not been marked safe.',
          )}
        </p>
      )}
      {view === 'pending' && (
        <section className="flex flex-col gap-2" aria-label={t('Filter review reasons')}>
          <p className="text-sm text-muted-foreground">
            {t('Choose what to review. A technical failure is not a harmful-content decision.')}
          </p>
          <div className="flex flex-wrap gap-2">
            {['all', 'uncertain', 'attachment', 'technical'].map((key) => (
              <Button
                key={key}
                size="sm"
                variant={reason === key ? 'primary' : 'outline'}
                aria-pressed={reason === key}
                onClick={() => update({ reason: key === 'all' ? '' : key })}
              >
                {t(key === 'all' ? 'All review reasons' : reviewKinds[key])}
                {data?.reason_counts && (
                  <span className="ms-1 tabular-nums">
                    {key === 'all'
                      ? Object.values(data.reason_counts).reduce((a, b) => a + b, 0)
                      : data.reason_counts[key] || 0}
                  </span>
                )}
              </Button>
            ))}
          </div>
        </section>
      )}
      {data && (
        <p className="text-sm text-muted-foreground">
          {data.total}{' '}
          {t(
            view === 'responses'
              ? 'with parent responses'
              : view === 'missing_data'
                ? 'with unavailable content'
                : 'awaiting review',
          )}
          ; {data.reviewed_total ?? 0}{' '}
          {t('judged. Human labels are review records, not proof of AI accuracy.')}
        </p>
      )}
      {isLoading && <Skeleton className="h-40" />}
      {isError && <QueryError what="the review queue" onRetry={() => void refetch()} />}
      {data && data.items.length === 0 && (
        <div className="rounded-lg border bg-surface">
          <EmptyState
            icon={ListChecks}
            title={view === 'missing_data' ? t('No unavailable content') : t('Nothing to review')}
          >
            {view === 'missing_data'
              ? t(
                  'Unavailable content is kept here for recovery. These messages have not been marked safe.',
                )
              : t('When Iris cannot tell whether a message is harmful, it waits here for you.')}
          </EmptyState>
        </div>
      )}
      <ul className="flex flex-col gap-4">
        {data?.items
          .filter(({ message: m }) => !['pending', 'processing'].includes(m.status))
          .map(
            ({
              message: m,
              classifications,
              missing_data: missingData,
              response_notes: notes,
              human_feedback: feedback,
              review_kind: kind,
              can_recover_media: canRecover,
            }) => (
              <li
                key={m.id}
                className={cn(
                  'flex flex-col gap-4 rounded-lg border bg-surface p-4 sm:p-5',
                  revokedClass(m, 'row'),
                )}
              >
                <div className="flex flex-wrap items-center gap-3">
                  <KidStack names={m.kids.map((k) => k.kid_name)} />
                  <span className="font-medium">{m.kids.map((k) => k.kid_name).join(' and ')}</span>
                  {m.chat_name && (
                    <span className="text-sm text-muted-foreground">
                      {t('in')} {m.chat_name}
                    </span>
                  )}
                  <span className="ms-auto text-xs text-muted-foreground">
                    {relativeTime(m.sent_at)}
                  </span>
                </div>
                <div className="max-w-prose text-lg leading-relaxed">
                  {m.sender_name && (
                    <span className="me-2 text-sm text-muted-foreground">{m.sender_name}:</span>
                  )}
                  <RevealableMessage m={m} showMedia />
                </div>
                <div className="flex flex-wrap items-center gap-1.5 empty:hidden">
                  <MessageFlags m={m} history />
                </div>
                {missingData && (
                  <p role="status" className="rounded-md bg-warning-soft p-3 text-sm text-warning">
                    {t(
                      'Ignored because data is missing. This report is saved separately from safety decisions.',
                    )}
                  </p>
                )}
                {!!notes?.length && (
                  <section className="rounded-lg bg-surface-2/40 p-3">
                    <h3 className="mb-2 text-sm font-medium">{t('Parent response notes')}</h3>
                    <ul className="flex flex-col gap-2">
                      {notes.map((note, i) => (
                        <li key={i} className="text-sm">
                          <p>{note.note}</p>
                          <time className="text-xs text-muted-foreground">
                            {relativeTime(note.created_at)}
                          </time>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
                {m.review_reason && (
                  <p className="text-sm text-muted-foreground">{t(m.review_reason)}</p>
                )}
                {kind && (
                  <p className="text-sm font-medium">
                    {t(reviewKinds[kind] || 'Uncertain classification')}
                  </p>
                )}
                {feedback && (
                  <section className="rounded-md bg-surface-2 p-3 text-sm">
                    <p className="font-medium">
                      {t('Human decision:')} {feedback.verdict}
                    </p>
                    {!!feedback.categories?.length && <p>{feedback.categories.join(', ')}</p>}
                    {feedback.explanation && (
                      <p dir="auto" className="whitespace-pre-wrap">
                        {feedback.explanation}
                      </p>
                    )}
                  </section>
                )}
                {view !== 'responses' &&
                  ['admin', 'parent'].includes(me?.role || '') &&
                  !m.redacted && (
                    <ReviewDetails
                      id={m.id}
                      value={drafts[m.id] || { categories: [], explanation: '' }}
                      disabled={resolve.isPending || rejudging(m)}
                      onChange={(value) =>
                        setDrafts((previous) => ({ ...previous, [m.id]: value }))
                      }
                    />
                  )}
                {classifications.slice(-1).map((c) => (
                  <details key={c.id} className="group rounded-md bg-surface-2/60 p-3">
                    <summary className="cursor-pointer text-sm font-medium">
                      {t('Why it is unclear')}
                    </summary>
                    <div className="mt-3">
                      <Scores scores={c.scores} min={0.05} />
                    </div>
                  </details>
                ))}
                <div className="flex flex-wrap items-center gap-2 border-t pt-3 [&>button]:min-w-0 [&>button]:whitespace-normal">
                  {view !== 'responses' && (
                    <>
                      <Button
                        variant="success"
                        size="sm"
                        aria-label={t('Mark safe')}
                        title={t('Mark this message safe')}
                        disabled={
                          resolve.isPending ||
                          rejudging(m) ||
                          !['admin', 'parent'].includes(me?.role || '')
                        }
                        onClick={() => resolve.mutate({ id: m.id, resolution: 'safe' })}
                      >
                        <Check /> {t('Safe')}
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        aria-label={t('Mark harmful')}
                        title={t('Mark this message harmful')}
                        disabled={
                          resolve.isPending ||
                          rejudging(m) ||
                          !['admin', 'parent'].includes(me?.role || '')
                        }
                        onClick={() => resolve.mutate({ id: m.id, resolution: 'harmful' })}
                      >
                        <ShieldAlert /> {t('Harmful')}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label={
                          missingData ? t('Content unavailable') : t('Ignore — missing data')
                        }
                        title={t(
                          'Ignore this item and save a missing-data report without judging safety.',
                        )}
                        className="min-[400px]:col-span-2 sm:col-span-1"
                        disabled={
                          resolve.isPending ||
                          rejudging(m) ||
                          missingData ||
                          !['admin', 'parent'].includes(me?.role || '')
                        }
                        onClick={() => resolve.mutate({ id: m.id, resolution: 'missing_data' })}
                      >
                        <CircleHelp /> {missingData ? t('Reported') : t('Ignore')}
                      </Button>
                    </>
                  )}
                  <Button
                    asChild
                    variant="ghost"
                    size="sm"
                    className="min-w-0 whitespace-normal min-[400px]:col-span-2 sm:col-span-1"
                  >
                    <Link
                      to={`/messages/${m.id}`}
                      aria-label={t('See the conversation')}
                      title={t('Open the full conversation')}
                    >
                      <MessagesSquare /> {t('Chat')}
                    </Link>
                  </Button>
                </div>
                {rejudging(m) && (
                  <p role="status" className="text-xs text-muted-foreground">
                    {t('AI recheck queued or running. Actions unlock when it finishes.')}
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  {canRecover && view !== 'responses' && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={rejudging(m) || !['admin', 'parent'].includes(me?.role || '')}
                      onClick={() => recoverMedia.mutate(m.id)}
                    >
                      <RotateCcw /> {t('Recover media and recheck')}
                    </Button>
                  )}
                  <SkipGroup messageId={m.id} isGroup={m.is_group} disabled={rejudging(m)} />
                  <Button
                    variant="outline"
                    size="sm"
                    aria-label={t('Ask AI to judge again')}
                    title={t('Run AI judgment again using available message content and media')}
                    disabled={
                      judgeAgain.isPending ||
                      m.redacted ||
                      !!m.revoked_at ||
                      view === 'responses' ||
                      !['admin', 'parent'].includes(me?.role || '') ||
                      ['pending', 'processing'].includes(m.status)
                    }
                    onClick={() => judgeAgain.mutate(m.id)}
                  >
                    <RotateCcw /> {t('Rejudge')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t('Copy full trace')}
                    title={t('Copy the full saved AI execution trace')}
                    disabled={rejudging(m)}
                    onClick={() => void copyTrace(m.id)}
                  >
                    <Copy />
                  </Button>
                </div>
              </li>
            ),
          )}
      </ul>
      {data && (
        <Pagination
          page={page}
          pageSize={pageSize}
          total={data.total}
          onPage={(p) => update({ page: String(p) })}
          noun={['message', 'messages']}
        />
      )}
    </div>
  )
}
