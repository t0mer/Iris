import {
  Activity,
  FlaskConical,
  BellRing,
  LayoutDashboard,
  ListChecks,
  MessagesSquare,
  Settings,
  Smartphone,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { t } from '../lib/i18n'
import type { Stats } from '../lib/types'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  group: 'watch' | 'manage'
  /** Number shown on the item, taken from the live stats. */
  badge?: (s: Stats) => number
}

export const NAV: NavItem[] = [
  { to: '/', label: t('nav.home'), icon: LayoutDashboard, group: 'watch' },
  {
    to: '/alerts',
    label: t('nav.alerts'),
    icon: BellRing,
    group: 'watch',
    badge: (s) => s.alerts_by_status['new'] ?? 0,
  },
  {
    to: '/review',
    label: t('nav.review'),
    icon: ListChecks,
    group: 'watch',
    badge: (s) => s.review_queue,
  },
  { to: '/messages', label: t('nav.messages'), icon: MessagesSquare, group: 'watch' },
  { to: '/chats', label: t('nav.chats'), icon: Users, group: 'watch' },
  { to: '/instances', label: t('nav.phones'), icon: Smartphone, group: 'manage' },
  {
    to: '/jobs',
    label: t('nav.jobs'),
    icon: Activity,
    group: 'manage',
    badge: (s) => s.failed_jobs,
  },
  { to: '/try', label: t('nav.tryIt'), icon: FlaskConical, group: 'manage' },
  { to: '/settings', label: t('nav.settings'), icon: Settings, group: 'manage' },
]

/** The four destinations on a phone's tab bar; everything else lives under "More". */
export const TAB_BAR = ['/', '/alerts', '/review', '/messages']
