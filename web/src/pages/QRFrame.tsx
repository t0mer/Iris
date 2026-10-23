import { useMutation, useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { useState } from 'react'
import { api } from '../lib/api'
import { t, useLanguage } from '../lib/i18n'
import { Button } from '../components/ui/button'

type QRState = { status: string; qr: string | null }

/** A dedicated, authenticated iframe: provider credentials never reach the browser. */
export function QRFrame() {
  useLanguage()
  const { id } = useParams()
  const [brokenImage, setBrokenImage] = useState<string | null>(null)
  const qr = useQuery({
    queryKey: ['provider-qr', id],
    queryFn: () => api<QRState>(`/api/instances/${id}/qr`),
    refetchInterval: 2000,
    retry: false,
    gcTime: 0,
  })
  const refresh = useMutation({
    mutationFn: () => api<QRState>(`/api/instances/${id}/qr/refresh`, { method: 'POST' }),
    onSuccess: () => {
      setBrokenImage(qr.data?.qr ?? null)
      void qr.refetch()
    },
  })
  const image =
    !qr.isError && !refresh.isPending && qr.data?.qr && qr.data.qr !== brokenImage
      ? qr.data.qr
      : null
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 bg-surface p-3 text-center">
      {image ? (
        <img
          src={image}
          alt={t('WhatsApp QR code')}
          className="aspect-square w-full max-w-64 rounded-lg bg-white p-2"
          onError={() => setBrokenImage(image)}
        />
      ) : (
        <p role="status" className="text-sm text-muted-foreground">
          {qr.data?.status === 'expired' || brokenImage
            ? t('This QR code is no longer valid. Request a new code.')
            : t('No QR code is available yet. You can request a new code.')}
        </p>
      )}
      {image && (
        <p className="text-xs text-muted-foreground">
          {t('Scan with WhatsApp → Linked devices. The QR updates automatically.')}
        </p>
      )}
      {(qr.isError || refresh.isError) && (
        <p role="alert" className="text-sm text-danger">
          {t((refresh.error ?? qr.error)?.message ?? 'OpenWA unavailable')}
        </p>
      )}
      <Button variant="outline" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
        {refresh.isPending ? t('Requesting a new QR…') : t('Request a new QR code')}
      </Button>
    </main>
  )
}
