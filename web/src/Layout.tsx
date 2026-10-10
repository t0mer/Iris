import { t as translate, useLanguage } from './lib/i18n'
import { useQuery } from '@tanstack/react-query'
import {
  Check,
  LogOut,
  Monitor,
  Moon,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
} from 'lucide-react'
import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { toast } from './lib/notify'
import { IrisMark } from './components/IrisMark'
import { InstallApp } from './components/InstallApp'
import { LanguageSelect } from './components/LanguageSelect'
import { LearningSharing } from './components/LearningSharing'
import { BackButton } from './components/BackButton'
import { LiveStatus } from './components/LiveStatus'
import { PageLoading } from './components/PageLoading'
import { PageBoundary } from './components/PageBoundary'
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
import { useLiveUpdates, type LiveStatus as Status } from './lib/live'
import { getTheme, setTheme, type Theme } from './lib/theme'
import type { Stats } from './lib/types'
import { useIsDesktop, useIsWide } from './lib/useMediaQuery'

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'system', label: 'System', icon: Monitor },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
]

const withoutCount = (title: string) => title.replace(/^\(\d+\) /, '')

function useShellData() {
  const { data: me } = useMe()
  const { data: stats } = useQuery({
    queryKey: ['stats', me?.id],
    queryFn: () => api<Stats>('/api/stats'),
    enabled: !!me,
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
      <span className="sr-only">
        {n} {translate('waiting')}
      </span>
    </span>
  )
}

function SideLink({ item, stats, wide }: { item: NavItem; stats?: Stats; wide: boolean }) {
  const n = stats && item.badge ? item.badge(stats) : 0
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      aria-label={
        wide
          ? undefined
          : n > 0
            ? translate('{value0}, {value1} waiting', { value0: translate(item.label), value1: n })
            : translate(item.label)
      }
      title={wide ? undefined : translate(item.label)}
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
      {wide && <span className="flex-1">{translate(item.label)}</span>}
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
          title={translate('Account and appearance')}
          aria-label={wide ? undefined : translate('Account and appearance')}
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
          {translate('Appearance')}
        </DropdownMenuLabel>
        {THEMES.map((t) => (
          <DropdownMenuItem key={t.value} onSelect={() => choose(t.value)}>
            <t.icon />
            <span className="flex-1">{translate(t.label)}</span>
            {theme === t.value && <Check />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <div className="px-3 py-2">
          <LanguageSelect />
          <LearningSharing />
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()}>
          <LogOut />
          {translate('Sign out')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function Sidebar({ stats, version, live }: { stats?: Stats; version?: string; live: Status }) {
  const { data: me } = useMe()
  const automaticWide = useIsWide()
  const [expanded, setExpanded] = useState<boolean | null>(() => {
    try {
      const saved = localStorage.getItem('iris.sidebar-expanded')
      return saved === null ? null : saved === '1'
    } catch {
      return null
    }
  })
  const wide = expanded ?? automaticWide
  function toggleSidebar() {
    setExpanded(!wide)
    try {
      localStorage.setItem('iris.sidebar-expanded', wide ? '0' : '1')
    } catch {
      /* Storage can be unavailable. */
    }
  }
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
      <Button
        variant="ghost"
        size="sm"
        className="w-full"
        onClick={toggleSidebar}
        aria-label={translate(wide ? 'Collapse side menu' : 'Expand side menu')}
        title={translate(wide ? 'Collapse side menu' : 'Expand side menu')}
        aria-expanded={wide}
      >
        {wide ? (
          <PanelLeftClose className="size-5 rtl:rotate-180" />
        ) : (
          <PanelLeftOpen className="size-5 rtl:rotate-180" />
        )}
        {wide && translate('Collapse side menu')}
      </Button>
      <nav aria-label={translate('Main')} className="flex flex-1 flex-col gap-5 overflow-y-auto">
        {groups
          .filter((g) => me?.role === 'admin' || g.key === 'watch')
          .map((g) => (
            <div key={g.key} className="flex flex-col gap-1">
              {wide && (
                <p className="px-3 pb-1 text-xs font-medium text-muted-foreground">
                  {translate(g.title)}
                </p>
              )}
              {NAV.filter((n) => n.group === g.key).map((item) => (
                <SideLink key={item.to} item={item} stats={stats} wide={wide} />
              ))}
            </div>
          ))}
      </nav>
      {wide && <LiveStatus status={live} />}
      <InstallApp compact={!wide} />
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
      {translate(item.label)}
    </NavLink>
  )
}

function MoreSheet({ stats, version }: { stats?: Stats; version?: string }) {
  useLanguage()
  const { data: me } = useMe()
  const logout = useLogout()
  const [open, setOpen] = useState(false)
  const [theme, setThemeState] = useState<Theme>(getTheme)
  const { pathname } = useLocation()
  const secondary = NAV.filter(
    (n) => !TAB_BAR.includes(n.to) && (me?.role === 'admin' || n.group === 'watch'),
  )
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
          {translate('More')}
        </button>
      </DialogTrigger>
      <DialogContent
        title={translate('More')}
        description={translate('{value0} {value1} · Iris {value2}', {
          value0: translate('Signed in as'),
          value1: me?.username ?? '',
          value2: version ?? '',
        })}
      >
        <nav aria-label={translate('More')} className="flex flex-col">
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
                <span className="flex-1">{translate(item.label)}</span>
                <Count n={n} />
              </NavLink>
            )
          })}
        </nav>
        <div
          role="group"
          aria-label={translate('Appearance')}
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
              {translate(t.label)}
            </button>
          ))}
        </div>
        <LanguageSelect />
        <LearningSharing />
        <Button variant="outline" onClick={() => void logout()}>
          <LogOut />
          {translate('Sign out')}
        </Button>
        <InstallApp />
      </DialogContent>
    </Dialog>
  )
}

function PhoneChrome({ stats, version, live }: { stats?: Stats; version?: string; live: Status }) {
  const { pathname } = useLocation()
  const tabs = NAV.filter((n) => TAB_BAR.includes(n.to))
  return (
    <>
      <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-background/85 px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] text-primary backdrop-blur">
        {pathname !== '/' && <BackButton />}
        <IrisMark className="size-6" />
        <span className="text-lg font-semibold tracking-tight text-foreground">Iris</span>
        <LiveStatus status={live} compact />
      </header>
      <nav
        aria-label={translate('Main')}
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
  useLanguage()
  const desktop = useIsDesktop()
  const { pathname } = useLocation()
  const mainRef = useRef<HTMLElement>(null)
  const firstRender = useRef(true)
  // After a route change, move focus to the page so keyboard and screen-reader users land on it.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    mainRef.current?.focus({ preventScroll: true })
  }, [pathname])
  const { stats, version } = useShellData()
  const navigate = useNavigate()
  const unread = useRef(0)
  const onAlert = useCallback(
    (id: number | null) => {
      // The tab title counts only what you have not seen; the toast shows either way.
      if (document.visibilityState === 'hidden') {
        unread.current += 1
        document.title = `(${unread.current}) ${withoutCount(document.title)}`
      }
      toast('A new alert needs you', {
        action: { label: 'Open', onClick: () => navigate(id ? `/alerts/${id}` : '/alerts') },
      })
    },
    [navigate],
  )
  // Back on the tab means the owner has seen it: drop the count from the title.
  useEffect(() => {
    const seen = () => {
      if (document.visibilityState === 'visible') {
        unread.current = 0
        document.title = withoutCount(document.title)
      }
    }
    document.addEventListener('visibilitychange', seen)
    return () => document.removeEventListener('visibilitychange', seen)
  }, [])
  const live = useLiveUpdates(onAlert)
  return (
    <div className="min-h-dvh md:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:start-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground"
      >
        {translate('Skip to content')}
      </a>
      {desktop ? (
        <Sidebar stats={stats} version={version} live={live} />
      ) : (
        <PhoneChrome stats={stats} version={version} live={live} />
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <main
          ref={mainRef}
          id="main"
          tabIndex={-1}
          className="mx-auto w-full max-w-6xl flex-1 px-4 pb-24 pt-5 outline-none md:px-8 md:pb-10 md:pt-8"
        >
          {desktop && pathname !== '/' && (
            <div className="mb-4">
              <BackButton />
            </div>
          )}
          <PageBoundary key={pathname}>
            <Suspense key={pathname} fallback={<PageLoading />}>
              <Outlet />
            </Suspense>
          </PageBoundary>
        </main>
      </div>
      <Toaster />
    </div>
  )
}
