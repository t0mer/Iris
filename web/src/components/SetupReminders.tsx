import { t } from '../lib/i18n'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { QueryError } from './QueryError'

type Reminders = {
  skipped: string[]
  steps: { id: string; title: string; warning: string; dismissible: boolean }[]
}

export function SetupReminders({ userId }: { userId: number }) {
  const client = useQueryClient()
  const key = ['setup-reminders', userId]
  const reminders = useQuery({
    queryKey: key,
    queryFn: () => api<Reminders>('/api/setup/reminders'),
    refetchInterval: 30_000,
  })
  const dismiss = useMutation({
    mutationFn: (step: string) =>
      api<Reminders>('/api/setup/reminders/dismiss', {
        method: 'POST',
        body: JSON.stringify({ step }),
      }),
    onSuccess: (data) => client.setQueryData(key, data),
  })
  if (reminders.isError)
    return <QueryError what="setup reminders" onRetry={() => void reminders.refetch()} />
  if (!reminders.data?.steps?.length) return null
  return (
    <section
      aria-labelledby="setup-reminders-heading"
      className="rounded-xl border border-purple-200 bg-purple-50 p-4 text-purple-950 sm:p-5 dark:border-purple-800/70 dark:bg-[#211735] dark:text-purple-50"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="setup-reminders-heading" className="text-lg font-semibold">
          {t('Finish setting up Iris')}
        </h2>
        <Link
          className="rounded-md underline underline-offset-4 focus-visible:outline-2 dark:text-purple-200 dark:focus-visible:outline-purple-300"
          to="/setup"
        >
          {t('Open setup checklist')}
        </Link>
      </div>
      <p className="mt-2 text-sm">
        {t(
          'Incomplete or skipped essentials stay visible until configured. Optional reminders can be dismissed for your account.',
        )}
      </p>
      <ul className="mt-4 space-y-3">
        {reminders.data.steps.map((step) => (
          <li
            key={step.id}
            className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-purple-200 bg-white/70 p-3 dark:border-purple-800/70 dark:bg-[#19142b]"
          >
            <div className="min-w-0 flex-1">
              <p className="font-medium">
                {t(step.title)}
                {reminders.data.skipped.includes(step.id) ? t(' · Skipped') : ''}
              </p>
              <p className="mt-1 text-sm text-purple-900 dark:text-purple-200">{t(step.warning)}</p>
              {!step.dismissible && (
                <p className="mt-1 text-xs font-medium dark:text-purple-300">
                  {t('Essential configuration')}
                </p>
              )}
            </div>
            {step.dismissible && (
              <button
                type="button"
                disabled={dismiss.isPending}
                onClick={() => dismiss.mutate(step.id)}
                aria-label={t('Dismiss {value0}', { value0: t(step.title) })}
                className="min-h-11 rounded-md border border-purple-300 px-3 text-sm font-medium hover:bg-purple-100 focus-visible:outline-2 disabled:opacity-50 dark:border-purple-600 dark:bg-purple-900/40 dark:text-purple-100 dark:hover:bg-purple-800/60 dark:focus-visible:outline-purple-300"
              >
                {t('Dismiss')}
              </button>
            )}
          </li>
        ))}
      </ul>
      {dismiss.isError && (
        <p role="alert" className="mt-3 text-sm">
          {t('Could not dismiss the reminder. Please try again.')}
        </p>
      )}
    </section>
  )
}
