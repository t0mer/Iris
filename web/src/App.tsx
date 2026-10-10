import { lazy } from 'react'
import { RequestProgress } from './components/RequestProgress'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Layout } from './Layout'
import { useMe } from './lib/auth'
import { Dashboard } from './pages/Dashboard'
import { Login } from './pages/Login'
import { ContactApproval } from './pages/ContactApproval'
import { PageLoading } from './components/PageLoading'
import { QueryError } from './components/QueryError'

// Everything but the home screen loads on demand, so the first paint on a phone stays small.
const page = <K extends string>(load: () => Promise<Record<K, React.ComponentType>>, name: K) =>
  lazy(() => load().then((m) => ({ default: m[name] })))
const Alerts = page(() => import('./pages/Alerts'), 'Alerts')
const AlertDetail = page(() => import('./pages/AlertDetail'), 'AlertDetail')
const Review = page(() => import('./pages/Review'), 'Review')
const IrisReview = page(() => import('./pages/IrisReview'), 'IrisReview')
const Messages = page(() => import('./pages/Messages'), 'Messages')
const MessageContext = page(() => import('./pages/MessageContext'), 'MessageContext')
const Chats = page(() => import('./pages/Chats'), 'Chats')
const Jobs = page(() => import('./pages/Jobs'), 'Jobs')
const Instances = page(() => import('./pages/Instances'), 'Instances')
const MediaViewer = page(() => import('./pages/MediaViewer'), 'MediaViewer')
const TryIt = page(() => import('./pages/TryIt'), 'TryIt')
const Settings = page(() => import('./pages/Settings'), 'Settings')
const Setup = page(() => import('./pages/Setup'), 'Setup')

export function App() {
  return (
    <>
      <RequestProgress />
      <AppContent />
    </>
  )
}

function AppContent() {
  const { data: me, isLoading, isError, refetch } = useMe()
  const location = useLocation()
  if (location.pathname === '/verify-contact') return <ContactApproval />
  if (isLoading)
    return (
      <main className="p-6">
        <PageLoading />
      </main>
    )
  if (isError && !me)
    return (
      <main className="p-6">
        <QueryError what="your session" onRetry={() => void refetch()} />
      </main>
    )
  if (!me) return <Login />
  const manage = (element: React.ReactNode) =>
    me.role !== 'admin' ? <Navigate to="/" replace /> : element
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="setup" element={manage(<Setup />)} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="alerts/:id" element={<AlertDetail />} />
        <Route path="review" element={<Review />} />
        <Route path="iris-review" element={<IrisReview />} />
        <Route path="messages" element={<Messages />} />
        <Route path="messages/:id" element={<MessageContext />} />
        <Route path="chats" element={<Chats />} />
        <Route path="jobs" element={manage(<Jobs />)} />
        <Route path="instances" element={manage(<Instances />)} />
        <Route path="media/:id" element={<MediaViewer />} />
        <Route path="try" element={manage(<TryIt />)} />
        <Route path="settings" element={manage(<Settings />)} />
      </Route>
    </Routes>
  )
}
