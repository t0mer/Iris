import { t } from '../lib/i18n'
import { Button } from './ui/button'

/** A failed load says what failed and what to try, and offers the retry right there. */
export function QueryError({ what, onRetry }: { what: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-lg bg-danger-soft p-4 text-sm text-danger"
    >
      <span className="min-w-0 flex-1 basis-60">
        {t('Could not load')} {t(what)}
        {t('. Check that Iris is running, then try again.')}
      </span>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t('Try again')}
        </Button>
      )}
    </div>
  )
}
