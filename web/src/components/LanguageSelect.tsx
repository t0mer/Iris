import { useState } from 'react'
import { getLanguage, saveLanguage, type Language } from '../lib/language'

export function LanguageSelect({
  reload = () => window.location.reload(),
}: {
  reload?: () => void
}) {
  const [value, setValue] = useState(getLanguage)
  const [failed, setFailed] = useState(false)
  return (
    <div className="flex flex-col gap-1 text-sm">
      <label className="flex items-center gap-2">
        <span>Language / שפה</span>
        <select
          aria-label="Language / שפה"
          value={value}
          title="Changing language reloads this page / שינוי שפה מרענן את העמוד"
          className="min-h-11 rounded-md border bg-surface px-2 text-foreground"
          onChange={(event) => {
            const next = event.target.value as Language
            if (next === value) return
            if (!saveLanguage(next)) {
              setFailed(true)
              return
            }
            setValue(next)
            setFailed(false)
            reload()
          }}
        >
          <option value="en">English</option>
          <option value="he">עברית</option>
        </select>
      </label>
      {failed && (
        <p role="alert">Could not save language preference / לא ניתן לשמור את בחירת השפה</p>
      )}
    </div>
  )
}
