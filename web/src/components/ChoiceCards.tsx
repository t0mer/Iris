import { useId } from 'react'
import { t } from '../lib/i18n'

export function ChoiceCards({
  label,
  value,
  options,
  onChange,
  disabled = false,
}: {
  label: string
  value: string
  options: { value: string; label: string; displayLabel?: string; disabled?: boolean }[]
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const name = useId()
  return (
    <fieldset disabled={disabled} className="min-w-0" aria-label={t(label)}>
      <legend className="mb-2 text-sm font-medium">{t(label)}</legend>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))] gap-2">
        {options.map((option) => (
          <label
            key={option.value}
            className={`flex min-h-12 min-w-0 cursor-pointer items-center gap-3 rounded-lg border px-3 py-3 text-sm transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-primary ${value === option.value ? 'border-primary bg-primary/10' : 'bg-surface hover:bg-surface-2'} ${disabled || option.disabled ? 'cursor-not-allowed opacity-60' : ''}`}
          >
            <input
              type="radio"
              aria-label={t(option.label)}
              name={name}
              value={option.value}
              checked={value === option.value}
              disabled={option.disabled}
              onChange={() => onChange(option.value)}
              className="size-4 shrink-0 accent-primary"
            />
            <span className="min-w-0">{t(option.displayLabel ?? option.label)}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
