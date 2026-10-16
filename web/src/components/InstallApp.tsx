import { he } from '../lib/he'
import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from './ui/button'
import { Dialog, DialogContent, DialogTrigger } from './ui/dialog'

type InstallEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export function InstallApp({ compact = false }: { compact?: boolean }) {
  const [prompt, setPrompt] = useState<InstallEvent | null>(null)
  const [installed, setInstalled] = useState(
    () => window.matchMedia('(display-mode: standalone)').matches,
  )
  useEffect(() => {
    const available = (event: Event) => {
      event.preventDefault()
      setPrompt(event as InstallEvent)
    }
    const done = () => {
      setInstalled(true)
      setPrompt(null)
    }
    window.addEventListener('beforeinstallprompt', available)
    window.addEventListener('appinstalled', done)
    return () => {
      window.removeEventListener('beforeinstallprompt', available)
      window.removeEventListener('appinstalled', done)
    }
  }, [])
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size={compact ? 'icon' : 'default'}
          aria-label={installed ? he('App installed') : he('Install app')}
          title={he('Install app')}
        >
          {compact ? <Download /> : installed ? he('App installed') : he('Install app')}
        </Button>
      </DialogTrigger>
      <DialogContent
        title={he('Install Iris')}
        description={he('Use Iris as a desktop or Android app.')}
      >
        {installed ? (
          <p>{he('Iris is already running as an installed app.')}</p>
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
                {he('Install Iris')}
              </Button>
            )}
            <p>
              {he(
                'In Chrome on Android, open the browser menu and choose Add to home screen, then Install. On desktop Chrome, choose Install Iris from the address bar or browser menu.',
              )}
            </p>
            {!window.isSecureContext && (
              <p>
                {he(
                  'Open Iris through an HTTPS address to enable app installation. This HTTP address may only support a browser shortcut.',
                )}
              </p>
            )}
            <p>
              {he(
                'The app needs access to your Iris server. It does not provide background notifications or offline monitoring status.',
              )}
            </p>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
