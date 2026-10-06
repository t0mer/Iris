import { useQuery } from '@tanstack/react-query'
import { Check, LogOut, Monitor, Moon, MoreHorizontal, Sun } from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { IrisMark } from './components/IrisMark'
import { NAV, TAB_BAR, type NavItem } from './components/nav'
import { Button } from './components/ui/button'
import { Dialog, DialogContent, DialogTrigger } from './components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from './components/ui/dropdown'
import { Toaster } from './components/ui/toaster'
import { api } from './lib/api'
import { useLogout, useMe } from './lib/auth'
import { cn } from './lib/cn'
import { getTheme, setTheme, type Theme } from './lib/theme'
import type { Stats } from './lib/types'
import { useIsDesktop, useIsWide } from './lib/useMediaQuery'

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'system', label: 'System', icon: Monitor },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
]

function useShellData() {
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api<Stats>('/api/stats'),
    refetchInterval: 60_000,
  })
  const { data: version } = useQuery({
    queryKey: ['version'],
    queryFn: () => api<{ version: string }>('/api/version'),
  })
  return { stats, version: version?.version }
}

function Count({ n, className }: { n: number; className?: string }) {
  if (n <= 0) return null
  return (
    <span
      className={cn(
        'tabular grid min-w-5 place-items-center rounded-full bg-danger px-1.5 text-[11px] font-semibold leading-5 text-primary-foreground dark:text-[#14122b]',
        className,
      )}
    >
      <span aria-hidden>{n > 99 ? '99+' : n}</span>
      <span className="sr-only">{n} waiting</span>
    </span>
  )
}

function SideLink({ item, stats, wide }: { item: NavItem; stats?: Stats; wide: boolean }) {
  const n = stats && item.badge ? item.badge(stats) : 0
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      aria-label={wide ? undefined : item.label}
      title={wide ? undefined : item.label}
      className={({ isActive }) =>
        cn(
          'relative flex min-h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors',
          wide ? '' : 'justify-center px-0',
          isActive
            ? 'bg-primary-soft text-primary before:absolute before:inset-y-2 before:start-0 before:w-1 before:rounded-full before:bg-primary'
            : 'text-muted-foreground hover:bg-surface-2 hover:text-foreground',
        )
      }
    >
      <item.icon className="size-5 shrink-0" />
      {wide && <span className="flex-1">{item.label}</span>}
      {wide ? (
        <Count n={n} />
      ) : (
        <Count n={n} className="absolute end-1 top-0.5 min-w-4 px-1 text-[10px] leading-4" />
      )}
    </NavLink>
  )
}

function AccountMenu({ wide, version }: { wide: boolean; version?: string }) {
  const { data: me } = useMe()
  const logout = useLogout()
  const [theme, setThemeState] = useState<Theme>(getTheme)
  const choose = (t: Theme) => {
    setTheme(t)
    setThemeState(t)
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className={cn(
            'flex min-h-11 w-full items-center gap-3 rounded-md px-2 text-start text-sm hover:bg-surface-2',
            !wide && 'justify-center',
          )}
          title="Account and appearance"
          aria-label={wide ? undefined : 'Account and appearance'}
        >
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary-soft text-sm font-semibold text-primary">
            {(me?.username ?? '?').slice(0, 1).toUpperCase()}
          </span>
          {wide && (
            <span className="flex min-w-0 flex-col leading-tight">
              <span className="truncate font-medium">{me?.username}</span>
              <span className="text-xs text-muted-foreground">Iris {version ?? ''}</span>
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top">
        <DropdownMenuLabel className="px-3 py-1.5 text-xs text-muted-foreground">
          Appearance
        </DropdownMenuLabel>
        {THEMES.map((t) => (
          <DropdownMenuItem key={t.value} onSelect={() => choose(t.value)}>
            <t.icon />
            <span className="flex-1">{t.label}</span>
            {theme === t.value && <Check />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()}>
          <LogOut />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function Sidebar({ stats, version }: { stats?: Stats; version?: string }) {
  const wide = useIsWide()
  const groups = [
    { key: 'watch', title: 'Watch' },
    { key: 'manage', title: 'Manage' },
  ] as const
  return (
    <aside
      className={cn(
        'sticky top-0 flex h-dvh shrink-0 flex-col gap-4 border-e bg-surface px-2 py-4',
        wide ? 'w-60' : 'w-16',
      )}
    >
      <div
        className={cn(
          'flex items-center gap-2.5 px-2 text-primary',
          !wide && 'justify-center px-0',
        )}
      >
        <IrisMark />
        {wide && <span className="text-lg font-semibold tracking-tight text-foreground">Iris</span>}
      </div>
      <nav aria-label="Main" className="flex flex-1 flex-col gap-5 overflow-y-auto">
        {groups.map((g) => (
          <div key={g.key} className="flex flex-col gap-1">
            {wide && (
              <p className="px-3 pb-1 text-xs font-medium text-muted-foreground">{g.title}</p>
            )}
            {NAV.filter((n) => n.group === g.key).map((item) => (
              <SideLink key={item.to} item={item} stats={stats} wide={wide} />
            ))}
          </div>
        ))}
      </nav>
      <AccountMenu wide={wide} version={version} />
    </aside>
  )
}

function TabLink({ item, stats }: { item: NavItem; stats?: Stats }) {
  const n = stats && item.badge ? item.badge(stats) : 0
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) =>
        cn(
          'relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium',
          isActive ? 'text-primary' : 'text-muted-foreground',
        )
      }
    >
      <span className="relative">
        <item.icon className="size-6" />
        <Count n={n} className="absolute -end-2.5 -top-1.5 min-w-4 px-1 text-[10px] leading-4" />
      </span>
      {item.label}
    </NavLink>
  )
}

function MoreSheet({ stats, version }: { stats?: Stats; version?: string }) {
  const { data: me } = useMe()
  const logout = useLogout()
  const [open, setOpen] = useState(false)
  const [theme, setThemeState] = useState<Theme>(getTheme)
  const { pathname } = useLocation()
  const secondary = NAV.filter((n) => !TAB_BAR.includes(n.to))
  const active = secondary.some((n) => pathname.startsWith(n.to))
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          className={cn(
            'relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium',
            active ? 'text-primary' : 'text-muted-foreground',
          )}
        >
          <span className="relative">
            <MoreHorizontal className="size-6" />
            <Count
              n={stats?.failed_jobs ?? 0}
              className="absolute -end-2.5 -top-1.5 min-w-4 px-1 text-[10px] leading-4"
            />
          </span>
          More
        </button>
      </DialogTrigger>
      <DialogContent
        title="More"
        description={`Signed in as ${me?.username ?? ''} · Iris ${version ?? ''}`}
      >
        <nav aria-label="More" className="flex flex-col">
          {secondary.map((item) => {
            const n = stats && item.badge ? item.badge(stats) : 0
            return (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setOpen(false)}
                className="flex min-h-12 items-center gap-3 rounded-md px-2 text-base hover:bg-surface-2"
              >
                <item.icon className="size-5 text-muted-foreground" />
                <span className="flex-1">{item.label}</span>
                <Count n={n} />
              </NavLink>
            )
          })}
        </nav>
        <div
          role="group"
          aria-label="Appearance"
          className="grid grid-cols-3 gap-1 rounded-md bg-surface-2 p-1"
        >
          {THEMES.map((t) => (
            <button
              key={t.value}
              aria-pressed={theme === t.value}
              onClick={() => {
                setTheme(t.value)
                setThemeState(t.value)
              }}
              className={cn(
                'flex min-h-10 items-center justify-center gap-1.5 rounded-sm text-sm font-medium',
                theme === t.value ? 'bg-surface text-primary shadow-sm' : 'text-muted-foreground',
              )}
            >
              <t.icon className="size-4" />
              {t.label}
            </button>
          ))}
        </div>
        <Button variant="outline" onClick={() => void logout()}>
          <LogOut />
          Sign out
        </Button>
      </DialogContent>
    </Dialog>
  )
}

function PhoneChrome({ stats, version }: { stats?: Stats; version?: string }) {
  const tabs = NAV.filter((n) => TAB_BAR.includes(n.to))
  return (
    <>
      <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-background/85 px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] text-primary backdrop-blur">
        <IrisMark className="size-6" />
        <span className="text-lg font-semibold tracking-tight text-foreground">Iris</span>
      </header>
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-surface pb-[env(safe-area-inset-bottom)]"
      >
        {tabs.map((item) => (
          <TabLink key={item.to} item={item} stats={stats} />
        ))}
        <MoreSheet stats={stats} version={version} />
      </nav>
    </>
  )
}

export function Layout() {
  const desktop = useIsDesktop()
  const { stats, version } = useShellData()
  return (
    <div className="min-h-dvh md:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:start-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        Skip to content
      </a>
      {desktop ? (
        <Sidebar stats={stats} version={version} />
      ) : (
        <PhoneChrome stats={stats} version={version} />
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <main
          id="main"
          tabIndex={-1}
          className="mx-auto w-full max-w-6xl flex-1 px-4 pb-24 pt-5 outline-none md:px-8 md:pb-10 md:pt-8"
        >
          <Outlet />
        </main>
      </div>
      <Toaster />
    </div>
  )
}
