import { SlidersHorizontal } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useIsDesktop } from '../lib/useMediaQuery'
import { Button } from './ui/button'
import { Dialog, DialogClose, DialogContent, DialogTrigger } from './ui/dialog'

/**
 * Filters sit inline on wider screens. On a phone they collapse behind one "Filters" button into
 * a bottom sheet, so the list stays the first thing on screen.
 */
export function FilterBar({
  children,
  active,
  onClear,
  leading,
}: {
  children: ReactNode
  /** How many filters are currently narrowing the list. */
  active: number
  onClear: () => void
  /** Always-visible controls, such as the search box or status chips. */
  leading?: ReactNode
}) {
  const desktop = useIsDesktop()
  const [open, setOpen] = useState(false)
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {leading}
        {desktop ? (
          <>
            {children}
            {active > 0 && (
              <Button variant="ghost" size="sm" onClick={onClear}>
                Clear filters
              </Button>
            )}
          </>
        ) : (
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" className="shrink-0">
                <SlidersHorizontal /> Filters
                {active > 0 && (
                  <span className="tabular rounded-full bg-primary px-1.5 text-xs text-primary-foreground">
                    {active}
                  </span>
                )}
              </Button>
            </DialogTrigger>
            <DialogContent title="Filters" description="Narrow the list.">
              <div className="flex flex-col gap-4">{children}</div>
              <div className="flex gap-2">
                <Button variant="outline" className="flex-1" onClick={onClear}>
                  Clear filters
                </Button>
                <DialogClose asChild>
                  <Button variant="primary" className="flex-1">
                    Show results
                  </Button>
                </DialogClose>
              </div>
            </DialogContent>
          </Dialog>
        )}
      </div>
    </div>
  )
}

/** A row of single-choice chips (for status, date ranges). Scrolls sideways instead of wrapping. */
export function Chips<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-0.5 md:mx-0 md:px-0"
    >
      {options.map((o) => (
        <button
          key={o.value}
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`min-h-9 shrink-0 rounded-full border px-3.5 text-sm font-medium transition-colors ${value === o.value ? 'border-primary bg-primary-soft text-primary' : 'border-border-strong text-muted-foreground hover:bg-surface-2'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
