import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Suspense, lazy } from 'react'
import Layout from './components/Layout'
import InboxPage from './pages/InboxPage'
import { PageSpinner } from './components/Spinner'

// Inbox is the landing route → keep it eager. Everything else (incl. the
// Recharts-heavy Health/Depot pages) is split into its own chunk and loaded
// on demand, so the initial bundle stays small.
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const DigestsPage = lazy(() => import('./pages/DigestsPage'))
const LogsPage = lazy(() => import('./pages/LogsPage'))
const AssistantPage = lazy(() => import('./pages/AssistantPage'))
const HealthPage = lazy(() => import('./pages/HealthPage'))
const PodcastsPage = lazy(() => import('./pages/PodcastsPage'))
const DepotPage = lazy(() => import('./pages/DepotPage'))

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<InboxPage />} />
          <Route path="/assistant" element={<Suspense fallback={<PageSpinner />}><AssistantPage /></Suspense>} />
          <Route path="/health" element={<Suspense fallback={<PageSpinner />}><HealthPage /></Suspense>} />
          <Route path="/podcasts" element={<Suspense fallback={<PageSpinner />}><PodcastsPage /></Suspense>} />
          <Route path="/depot" element={<Suspense fallback={<PageSpinner />}><DepotPage /></Suspense>} />
          <Route path="/digests" element={<Suspense fallback={<PageSpinner />}><DigestsPage /></Suspense>} />
          <Route path="/settings" element={<Suspense fallback={<PageSpinner />}><SettingsPage /></Suspense>} />
          <Route path="/logs" element={<Suspense fallback={<PageSpinner />}><LogsPage /></Suspense>} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
