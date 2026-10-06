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
  { to: '/', label: 'Home', icon: LayoutDashboard, group: 'watch' },
  {
    to: '/alerts',
    label: 'Alerts',
    icon: BellRing,
    group: 'watch',
    badge: (s) => s.alerts_by_status['new'] ?? 0,
  },
  {
    to: '/review',
    label: 'Review',
    icon: ListChecks,
    group: 'watch',
    badge: (s) => s.review_queue,
  },
  { to: '/messages', label: 'Messages', icon: MessagesSquare, group: 'watch' },
  { to: '/chats', label: 'Chats', icon: Users, group: 'watch' },
  { to: '/instances', label: 'Phones', icon: Smartphone, group: 'manage' },
  { to: '/jobs', label: 'Jobs', icon: Activity, group: 'manage', badge: (s) => s.failed_jobs },
  { to: '/try', label: 'Try it', icon: FlaskConical, group: 'manage' },
  { to: '/settings', label: 'Settings', icon: Settings, group: 'manage' },
]

/** The four destinations on a phone's tab bar; everything else lives under "More". */
export const TAB_BAR = ['/', '/alerts', '/review', '/messages']
