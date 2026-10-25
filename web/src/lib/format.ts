import { getLanguage, t } from './i18n'

export function relativeTime(iso: string | null, now = Date.now()): string {
  if (!iso) return t('never')
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 60) return t('just now')
  if (getLanguage() === 'he') {
    const [unit, value] =
      s < 3600
        ? (['minute', Math.floor(s / 60)] as const)
        : s < 86400
          ? (['hour', Math.floor(s / 3600)] as const)
          : (['day', Math.floor(s / 86400)] as const)
    return new Intl.RelativeTimeFormat('he', { numeric: 'always' }).format(-value, unit)
  }
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(getLanguage(), {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** "Oct 6" for a calendar date (YYYY-MM-DD), read as that local date, not shifted by time zone. */
export function shortDate(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(getLanguage(), { month: 'short', day: 'numeric' })
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}
