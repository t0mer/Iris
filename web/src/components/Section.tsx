import { createContext, useContext, useId, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { t } from '../lib/i18n'

const AccordionContext = createContext<{
  active: string | null | undefined
  setActive: (id: string | null) => void
} | null>(null)

export function SectionGroup({ children }: { children: ReactNode }) {
  const [automatic, setAutomatic] = useState(true)
  const [active, setActive] = useState<string | null>()
  return (
    <AccordionContext.Provider value={automatic ? { active, setActive } : null}>
      <div className="flex flex-col gap-5">
        <label className="flex min-h-11 items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={automatic}
            onChange={(e) => {
              setAutomatic(e.target.checked)
              setActive(undefined)
            }}
            className="size-4 accent-primary"
          />
          {t('Close other sections automatically')}
        </label>
        {children}
      </div>
    </AccordionContext.Provider>
  )
}

/** A titled group of related settings. */
export function Section({
  title,
  description,
  children,
  collapsible = false,
  defaultOpen = false,
}: {
  title: string
  description?: string
  children: ReactNode
  collapsible?: boolean
  defaultOpen?: boolean
}) {
  const [localOpen, setLocalOpen] = useState(defaultOpen)
  const id = useId()
  const group = useContext(AccordionContext)
  const open = group ? (group.active === undefined ? defaultOpen : group.active === id) : localOpen
  function toggle() {
    setLocalOpen(!open)
    group?.setActive(open ? null : id)
  }
  return (
    <section className="flex flex-col gap-4 rounded-lg border bg-surface p-4 sm:p-5">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">
          {collapsible ? (
            <button
              type="button"
              className="flex min-h-11 w-full items-center justify-between gap-3 text-start"
              aria-expanded={open}
              aria-controls={id}
              onClick={toggle}
            >
              {t(title)}
              <ChevronDown
                className={`size-5 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
              />
            </button>
          ) : (
            t(title)
          )}
        </h2>
        {description && (!collapsible || open) && (
          <p className="max-w-prose text-sm text-muted-foreground">{t(description)}</p>
        )}
      </div>
      {collapsible ? (
        <div id={id} hidden={!open} className="flex flex-col gap-4">
          {children}
        </div>
      ) : (
        children
      )}
    </section>
  )
}
