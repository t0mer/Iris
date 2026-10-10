import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from './ui/button'
import { Dialog, DialogContent, DialogTrigger } from './ui/dialog'

type InstallEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

const INSTALLED_KEY = 'iris.app-installed'
function installedHere() {
  const standalone =
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  try {
    return standalone || localStorage.getItem(INSTALLED_KEY) === 'true'
  } catch {
    return standalone
  }
}

export function InstallApp({ compact = false }: { compact?: boolean }) {
  const [prompt, setPrompt] = useState<InstallEvent | null>(null)
  const [installed, setInstalled] = useState(installedHere)
  useEffect(() => {
    const available = (event: Event) => {
      event.preventDefault()
      // A new install prompt means the browser considers this app installable again.
      try {
        localStorage.removeItem(INSTALLED_KEY)
      } catch {
        /* storage may be disabled */
      }
      setInstalled(false)
      setPrompt(event as InstallEvent)
    }
    const done = () => {
      setInstalled(true)
      setPrompt(null)
      try {
        localStorage.setItem(INSTALLED_KEY, 'true')
      } catch {
        /* standalone detection still works */
      }
    }
    const mode = window.matchMedia('(display-mode: standalone)')
    const modeChanged = () => {
      if (mode.matches) done()
    }
    mode.addEventListener('change', modeChanged)
    window.addEventListener('beforeinstallprompt', available)
    window.addEventListener('appinstalled', done)
    return () => {
      window.removeEventListener('beforeinstallprompt', available)
      window.removeEventListener('appinstalled', done)
      mode.removeEventListener('change', modeChanged)
    }
  }, [])
  if (installed) return null
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size={compact ? 'icon' : 'default'}
          aria-label={installed ? 'App installed' : 'Install app'}
          title="Install app"
        >
          {compact ? <Download /> : installed ? 'App installed' : 'Install app'}
        </Button>
      </DialogTrigger>
      <DialogContent title="Install Iris" description="Use Iris as a desktop or Android app.">
        {installed ? (
          <p>Iris is already running as an installed app.</p>
        ) : (
          <>
            {prompt && (
              <Button
                variant="primary"
                onClick={async () => {
                  await prompt.prompt()
                  await prompt.userChoice
                  setPrompt(null)
                }}
              >
                Install Iris
              </Button>
            )}
            <p>
              In Chrome on Android, open the browser menu and choose Add to home screen, then
              Install. On desktop Chrome, choose Install Iris from the address bar or browser menu.
            </p>
            {!window.isSecureContext && (
              <p>
                Open Iris through an HTTPS address to enable app installation. This HTTP address may
                only support a browser shortcut.
              </p>
            )}
            <p>
              The app needs access to your Iris server. It does not provide background notifications
              or offline monitoring status.
            </p>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
