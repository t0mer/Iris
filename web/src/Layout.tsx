import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from './lib/api'
import { useState } from 'react'
import { useLogout, useMe } from './lib/auth'
import { getTheme, setTheme, type Theme } from './lib/theme'

const NEXT: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' }
const LABEL: Record<Theme, string> = { system: 'System', light: 'Light', dark: 'Dark' }

export function Layout() {
  const [theme, setThemeState] = useState<Theme>(getTheme)
  const { data: me } = useMe()
  const logout = useLogout()
  const { data: v } = useQuery({
    queryKey: ['version'],
    queryFn: () => api<{ version: string }>('/api/version'),
  })
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <nav className="flex items-center gap-4 text-sm">
          <span className="font-semibold">Iris</span>
          {[
            ['/', 'Dashboard'],
            ['/alerts', 'Alerts'],
            ['/review', 'Review'],
            ['/messages', 'Messages'],
            ['/chats', 'Chats'],
            ['/instances', 'Instances'],
            ['/jobs', 'Jobs'],
            ['/settings', 'Settings'],
          ].map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                isActive ? 'font-medium underline' : 'text-slate-600 dark:text-slate-400'
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <span className="flex items-center gap-3 text-sm">
          <button
            className="rounded border px-2 py-0.5 text-xs"
            aria-label={`Theme: ${LABEL[theme]}. Switch to ${LABEL[NEXT[theme]]}`}
            onClick={() => {
              setTheme(NEXT[theme])
              setThemeState(NEXT[theme])
            }}
          >
            {LABEL[theme]}
          </button>
          {me?.username}
          <button className="underline" onClick={logout}>
            Sign out
          </button>
        </span>
      </header>
      <main className="flex-1 p-4">
        <Outlet />
      </main>
      <footer className="px-4 py-2 text-xs text-slate-500">Iris {v?.version ?? ''}</footer>
    </div>
  )
}
