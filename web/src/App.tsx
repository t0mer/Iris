import { lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Layout } from './Layout'
import { useMe } from './lib/auth'
import { Dashboard } from './pages/Dashboard'
import { Login } from './pages/Login'

// Everything but the home screen loads on demand, so the first paint on a phone stays small.
const page = <K extends string>(load: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  lazy(() => load().then((m) => ({ default: m[name] })))
const Alerts = page(() => import('./pages/Alerts'), 'Alerts')
const AlertDetail = page(() => import('./pages/AlertDetail'), 'AlertDetail')
const Review = page(() => import('./pages/Review'), 'Review')
const Messages = page(() => import('./pages/Messages'), 'Messages')
const MessageContext = page(() => import('./pages/MessageContext'), 'MessageContext')
const Chats = page(() => import('./pages/Chats'), 'Chats')
const Jobs = page(() => import('./pages/Jobs'), 'Jobs')
const Instances = page(() => import('./pages/Instances'), 'Instances')
const MediaViewer = page(() => import('./pages/MediaViewer'), 'MediaViewer')
const TryIt = page(() => import('./pages/TryIt'), 'TryIt')
const Settings = page(() => import('./pages/Settings'), 'Settings')

export function App() {
  const { data: me, isLoading } = useMe()
  if (isLoading) return null
  if (!me) return <Login />
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="alerts/:id" element={<AlertDetail />} />
        <Route path="review" element={<Review />} />
        <Route path="messages" element={<Messages />} />
        <Route path="messages/:id" element={<MessageContext />} />
        <Route path="chats" element={<Chats />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="instances" element={<Instances />} />
        <Route path="media/:id" element={<MediaViewer />} />
        <Route path="try" element={<TryIt />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
