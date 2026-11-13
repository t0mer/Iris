import { t } from '../lib/i18n'
import { Component, type ReactNode } from 'react'
import { Button } from './ui/button'

/** Keep navigation usable when an old tab cannot load a page after an update. */
export class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    if (this.state.failed)
      return (
        <div role="alert" className="flex flex-col items-start gap-3">
          <h1 className="text-xl font-semibold">{t('This page could not load')}</h1>
          <p>
            {t(
              'Iris may have been updated while this tab was open. Reload to get the current version.',
            )}
          </p>
          <Button onClick={() => window.location.reload()}>{t('Reload Iris')}</Button>
        </div>
      )
    return this.props.children
  }
}
