import { t, useLanguage } from '../../lib/i18n'
import * as AlertPrimitive from '@radix-ui/react-alert-dialog'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { cn } from '../../lib/cn'
import { Button, type ButtonProps } from './button'

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close

const overlay = 'fixed inset-0 z-50 bg-[#14122b]/60 backdrop-blur-[2px]'

/** A centred dialog on desktop, a bottom sheet on phones. */
export function DialogContent({
  title,
  description,
  children,
  className,
}: {
  title: string
  description?: string
  children: ReactNode
  className?: string
}) {
  const { dir } = useLanguage()
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className={overlay} />
      <DialogPrimitive.Content
        dir={dir}
        {...(description ? {} : { 'aria-describedby': undefined })}
        className={cn(
          'fixed inset-x-0 bottom-0 z-50 flex max-h-[88dvh] flex-col gap-4 overflow-y-auto rounded-t-xl border border-border bg-surface p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] shadow-overlay',
          'md:inset-x-auto md:bottom-auto md:left-1/2 md:top-1/2 md:w-full md:max-w-md md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-lg',
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <DialogPrimitive.Title className="text-lg font-semibold">
              {t(title)}
            </DialogPrimitive.Title>
            {description && (
              <DialogPrimitive.Description className="text-sm text-muted-foreground">
                {t(description)}
              </DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close asChild>
            <Button variant="ghost" size="icon" aria-label={t('Close')} className="-me-2 -mt-2">
              <X />
            </Button>
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}

/** A confirmation that names the consequence and uses the action's own verb on the button. */
export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  onConfirm,
  tone = 'danger',
  children,
  onOpenChange,
  pending = false,
  keepOpen = false,
}: {
  trigger: ReactNode
  title: string
  description: string
  confirmLabel: string
  onConfirm: () => void | Promise<void>
  tone?: ButtonProps['variant']
  children?: ReactNode
  onOpenChange?: (open: boolean) => void
  pending?: boolean
  keepOpen?: boolean
}) {
  const { dir } = useLanguage()
  const [open, setOpen] = useState(false)
  return (
    <AlertPrimitive.Root
      open={open}
      onOpenChange={(value) => {
        if (pending) return
        setOpen(value)
        onOpenChange?.(value)
      }}
    >
      <AlertPrimitive.Trigger asChild>{trigger}</AlertPrimitive.Trigger>
      <AlertPrimitive.Portal>
        <AlertPrimitive.Overlay className={overlay} />
        <AlertPrimitive.Content
          dir={dir}
          className="fixed left-1/2 top-1/2 z-50 flex w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-lg border border-border bg-surface p-5 shadow-overlay"
        >
          <AlertPrimitive.Title className="text-lg font-semibold">{t(title)}</AlertPrimitive.Title>
          <AlertPrimitive.Description className="text-sm text-muted-foreground">
            {t(description)}
          </AlertPrimitive.Description>
          {children}
          <div className="flex flex-wrap justify-end gap-2">
            <AlertPrimitive.Cancel asChild>
              <Button variant="outline" disabled={pending}>
                {t('Cancel')}
              </Button>
            </AlertPrimitive.Cancel>
            <AlertPrimitive.Action asChild>
              <Button
                variant={tone}
                disabled={pending}
                onClick={(event) => {
                  if (keepOpen) {
                    event.preventDefault()
                    void Promise.resolve(onConfirm())
                      .then(() => setOpen(false))
                      .catch(() => {})
                  } else {
                    void onConfirm()
                  }
                }}
              >
                {t(confirmLabel)}
              </Button>
            </AlertPrimitive.Action>
          </div>
        </AlertPrimitive.Content>
      </AlertPrimitive.Portal>
    </AlertPrimitive.Root>
  )
}
