import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from './ui/button'
import { t } from '../lib/i18n'

/** Direct links have no in-app history: return to a known Iris page in that case. */
export function BackButton({ fallback = '/' }: { fallback?: string }) {
  const navigate = useNavigate()
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => {
        if (typeof window.history.state?.idx === 'number' && window.history.state.idx > 0)
          navigate(-1)
        else navigate(fallback, { replace: true })
      }}
    >
      <ArrowLeft className="rtl:rotate-180" />
      {t('Back')}
    </Button>
  )
}
