import { he } from '../lib/he'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { LoaderCircle } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../lib/api'
import type { Instance } from '../lib/types'
import { Dialog, DialogTrigger, DialogContent } from './ui/dialog'
import { Button } from './ui/button'

export function RepairPhone({
  phone,
  open: controlled,
  onOpenChange,
}: {
  phone: Instance
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const [localOpen, setLocalOpen] = useState(false)
  const open = controlled ?? localOpen
  const setOpen = useCallback(
    (value: boolean) => {
      setLocalOpen(value)
      onOpenChange?.(value)
    },
    [onOpenChange],
  )
  const qc = useQueryClient()
  const [finishing, setFinishing] = useState(false)
  const [finishError, setFinishError] = useState('')
  const completed = useRef(false)
  const current = useRef(open)
  useEffect(() => {
    current.current = open
  }, [open])
  const check = useQuery({
    queryKey: ['re-pair', phone.id],
    queryFn: () =>
      api<{ status: string; qr: string | null }>(`/api/instances/${phone.id}/re-pair`, {
        method: 'POST',
      }),
    enabled: open,
    refetchInterval: open ? 2000 : false,
    retry: false,
    gcTime: 0,
  })
  const finish = useCallback(async () => {
    setFinishing(true)
    setFinishError('')
    try {
      if (phone.role !== 'parent' && phone.enabled)
        await api(`/api/instances/${phone.id}/register-webhook`, { method: 'POST' })
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['instances'] }),
        qc.invalidateQueries({ queryKey: ['stats'] }),
      ])
      if (current.current) {
        toast.success(`${phone.kid_name} reconnected.`)
        setOpen(false)
      }
    } catch (error) {
      setFinishError(
        error instanceof Error ? error.message : he('Webhook registration failed. Retry below.'),
      )
    } finally {
      setFinishing(false)
    }
  }, [phone.role, phone.enabled, phone.id, phone.kid_name, qc, setOpen])
  useEffect(() => {
    if (!open) completed.current = false
  }, [open])
  useEffect(() => {
    if (open && !check.isFetching && check.data?.status === 'ready' && !completed.current) {
      completed.current = true
      void finish()
    }
  }, [open, check.data?.status, check.isFetching, finish])
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (finishing) return
        if (value) {
          completed.current = false
          setFinishError('')
          void qc.removeQueries({ queryKey: ['re-pair', phone.id] })
        }
        setOpen(value)
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline">{he('Re-pair WhatsApp')}</Button>
      </DialogTrigger>
      <DialogContent
        title={he('Re-pair {name}', { name: phone.kid_name })}
        description={he(
          'Reconnect the existing WhatsApp session. Closing this window never deletes your phone or session.',
        )}
      >
        {check.data?.qr && !check.isError && (
          <img
            alt={he('WhatsApp re-pairing QR code')}
            src={check.data.qr}
            className="mx-auto aspect-square w-full max-w-64 rounded-md bg-white p-2"
            onError={() => void check.refetch()}
          />
        )}
        <p role="status" className="flex items-center gap-2">
          {!check.data?.qr && !check.isError && (
            <LoaderCircle aria-hidden className="size-5 animate-spin" />
          )}
          {finishing
            ? he('Connected. Restoring monitoring…')
            : check.data?.status === 'authenticating'
              ? he('Scan received. Confirming WhatsApp connection…')
              : check.data?.qr
                ? he('WhatsApp → Linked devices → Link a device. QR changes update automatically.')
                : check.isError
                  ? he('Connection check failed.')
                  : he('Checking the existing session and waiting for OpenWA to provide a QR…')}
        </p>
        {check.isError && (
          <p role="alert" className="text-sm text-danger">
            {check.error instanceof Error ? check.error.message : he('OpenWA unavailable')}
          </p>
        )}
        {finishError && (
          <>
            <p role="alert" className="text-sm text-danger">
              {finishError}
            </p>
            <Button disabled={finishing} onClick={() => void finish()}>
              {he('Retry restoring monitoring')}
            </Button>
          </>
        )}
        <Button onClick={() => void check.refetch()} disabled={check.isFetching || finishing}>
          {he('Refresh QR / check connection')}
        </Button>
      </DialogContent>
    </Dialog>
  )
}
