import { useState } from 'react'

export const reviewCategories = [
  'sexual/minors',
  'self-harm',
  'self-harm/intent',
  'self-harm/instructions',
  'harassment/threatening',
  'hate/threatening',
  'illicit/violent',
  'sexual',
  'violence/graphic',
  'harassment',
  'hate',
  'illicit',
  'violence',
]

export type ReviewDraft = { categories: string[]; explanation: string }

export function ReviewDetails({
  id,
  value,
  onChange,
  disabled,
}: {
  id: number
  value: ReviewDraft
  onChange: (value: ReviewDraft) => void
  disabled: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <details className="rounded-md border p-3" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="cursor-pointer text-sm font-medium">
        Add review details (optional)
      </summary>
      {open && (
        <fieldset disabled={disabled} className="mt-3 flex flex-col gap-3">
          <legend className="text-sm">Harm categories — included only when marking Harmful</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {reviewCategories.map((category) => (
              <label key={category} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={value.categories.includes(category)}
                  onChange={(e) =>
                    onChange({
                      ...value,
                      categories: e.target.checked
                        ? [...value.categories, category]
                        : value.categories.filter((c) => c !== category),
                    })
                  }
                />
                {category.replaceAll('/', ' / ')}
              </label>
            ))}
          </div>
          <label htmlFor={`review-explanation-${id}`} className="text-sm">
            Your explanation
          </label>
          <textarea
            id={`review-explanation-${id}`}
            dir="auto"
            maxLength={1000}
            rows={3}
            className="rounded-md border bg-background p-2 text-sm"
            value={value.explanation}
            onChange={(e) => onChange({ ...value, explanation: e.target.value })}
          />
        </fieldset>
      )}
    </details>
  )
}
