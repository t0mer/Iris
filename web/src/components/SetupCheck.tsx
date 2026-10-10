import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, LoaderCircle } from 'lucide-react'
import { api } from '../lib/api'
import { Button } from './ui/button'

export function SetupCheck({
  path,
  label,
  passed = false,
  disabled = false,
  detail,
  step,
  body = {},
}: {
  path: string
  label: string
  passed?: boolean
  disabled?: boolean
  detail?: string | null
  step?: string
  body?: object
}) {
  const client = useQueryClient()
  const check = useMutation({
    mutationFn: async () => {
      const result = await api<{
        ok?: boolean
        detail?: string
        steps?: { id: string; ready: boolean }[]
      }>(path, { method: 'POST', body: JSON.stringify(body) })
      if (result.ok === false)
        throw new Error(result.detail || 'Test failed. Check the saved configuration.')
      if (step && result.steps && !result.steps.find((item) => item.id === step)?.ready)
        throw new Error('Connection is not ready. Check the configuration and try again.')
      return result
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: ['setup'] })
      void client.invalidateQueries({ queryKey: ['setup-reminders'] })
    },
  })
  const queued = /queued/i.test(check.data?.detail ?? '')
  const success = passed || (check.isSuccess && !queued)
  const message = check.isPending
    ? 'Testing… Please wait.'
    : check.isError
      ? check.error.message
      : passed
        ? detail || 'Test passed for saved settings.'
        : check.data?.detail || detail
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button disabled={disabled || success || check.isPending} onClick={() => check.mutate()}>
        {check.isPending && (
          <LoaderCircle
            aria-hidden="true"
            className="size-4 animate-spin motion-reduce:animate-none"
          />
        )}
        {success && <CheckCircle2 aria-hidden="true" className="size-4" />}
        {label}
      </Button>
      {message && (
        <p
          role={
            check.isError || (!passed && detail && !check.isSuccess && !check.isPending)
              ? 'alert'
              : 'status'
          }
          aria-live="polite"
          className={`max-w-prose text-sm ${success ? 'text-success' : check.isError || (detail && !passed && !check.isPending && !check.isSuccess) ? 'text-danger' : 'text-muted-foreground'}`}
        >
          {message}
        </p>
      )}
    </div>
  )
}
