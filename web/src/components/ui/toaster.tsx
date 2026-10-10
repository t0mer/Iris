import { Toaster as Sonner } from 'sonner'
import { useIsDark } from '../../lib/theme'
import { useIsDesktop } from '../../lib/useMediaQuery'
import { useLanguage } from '../../lib/i18n'

/** Toasts confirm what changed. They sit above the phone tab bar and respect the theme. */
export function Toaster() {
  const { dir } = useLanguage()
  const desktop = useIsDesktop()
  const dark = useIsDark()
  return (
    <Sonner
      dir={dir}
      position={desktop ? (dir === 'rtl' ? 'bottom-left' : 'bottom-right') : 'top-center'}
      theme={dark ? 'dark' : 'light'}
      toastOptions={{
        classNames: {
          toast: '!border !border-border !bg-surface !text-foreground !shadow-overlay',
        },
      }}
    />
  )
}
