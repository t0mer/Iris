import { locale, t } from './i18n'
import { language } from './language'

export function relativeTime(iso: string | null, now = Date.now()): string {
  if (!iso) return t('common.never')
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 60) return t('time.justNow')
  if (s < 3600) return t('time.minutesAgo', Math.floor(s / 60))
  if (s < 86400) return t('time.hoursAgo', Math.floor(s / 3600))
  return t('time.daysAgo', Math.floor(s / 86400))
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(locale, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/** "6 באוק׳" for a calendar date (YYYY-MM-DD), read as that local date, not shifted by time zone. */
export function shortDate(isoDate: string): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(locale, { month: 'short', day: 'numeric' })
}

export function fileSize(bytes: number): string {
  if (language === 'en') {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 ** 2) return `${Math.round(bytes / 1024)} KB`
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
    return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  }
  if (bytes < 1024) return `${bytes} ב׳`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} ק״ב`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} מ״ב`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} ג״ב`
}
