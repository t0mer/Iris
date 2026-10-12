import { t } from '../lib/i18n'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { dateTime } from '../lib/format'
import { Field, Input } from '../components/ui/field'
import { Pagination } from '../components/Pagination'
import { QueryError } from '../components/QueryError'

type Action = {
  id: number
  username: string
  method: string
  path: string
  status_code: number
  created_at: string
  changes: {
    entity: string
    id: string
    field?: string
    action?: string
    before: unknown
    after: unknown
  }[]
}

export function AuditSettings() {
  const [page, setPage] = useState(1)
  const [username, setUsername] = useState('')
  const { data, isError, refetch } = useQuery({
    queryKey: ['audit', page, username],
    queryFn: () =>
      api<{ items: Action[]; total: number }>(
        `/api/audit?page=${page}&page_size=25&username=${encodeURIComponent(username)}`,
      ),
    refetchInterval: 10_000,
  })
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">{t('User action audit')}</h2>
      <p className="text-sm text-muted-foreground">
        {t(
          'Actions and committed changes are recorded from this update onward. Passwords, credentials and message content are redacted. Failed requests are included; they may have no committed changes.',
        )}
      </p>
      <Field label={t('Filter by exact username')}>
        <Input
          value={username}
          onChange={(e) => {
            setUsername(e.target.value)
            setPage(1)
          }}
        />
      </Field>
      {isError && <QueryError what="user actions" onRetry={() => void refetch()} />}
      {data?.items?.length === 0 && <p>{t('No actions recorded.')}</p>}
      {data?.items?.map((a) => (
        <details key={a.id} className="rounded-lg border bg-surface p-4">
          <summary className="cursor-pointer text-sm">
            <span className="font-medium">{a.username}</span> · {a.method} {a.path} ·{' '}
            {a.status_code} · {dateTime(a.created_at)}
          </summary>
          <div className="mt-3 flex flex-col gap-3">
            {!a.changes.length && (
              <p className="text-sm text-muted-foreground">{t('No committed field changes.')}</p>
            )}
            {a.changes.map((c, i) => (
              <div key={i} className="text-sm">
                <p className="font-medium">
                  {c.entity} {c.id} · {c.field || c.action}
                </p>
                <div className="grid gap-2 sm:grid-cols-2">
                  <div>
                    <p>{t('From')}</p>
                    <pre className="overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-2 p-2">
                      {JSON.stringify(c.before, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <p>{t('To')}</p>
                    <pre className="overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-2 p-2">
                      {JSON.stringify(c.after, null, 2)}
                    </pre>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </details>
      ))}
      {data && (
        <Pagination
          page={page}
          pageSize={25}
          total={data.total}
          noun={['action', 'actions']}
          onPage={setPage}
        />
      )}
    </section>
  )
}
