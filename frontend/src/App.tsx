import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Suspense, lazy } from 'react'
import Layout from './components/Layout'
import { PageSpinner } from './components/Spinner'

// Dashboard is the landing route. Every page is lazy-split into its own chunk
// (incl. the Recharts-heavy Dashboard/Health/Depot pages), so the initial
// bundle stays small and recharts loads on demand.
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const InboxPage = lazy(() => import('./pages/InboxPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const DigestsPage = lazy(() => import('./pages/DigestsPage'))
const LogsPage = lazy(() => import('./pages/LogsPage'))
const AssistantPage = lazy(() => import('./pages/AssistantPage'))
const HealthPage = lazy(() => import('./pages/HealthPage'))
const PodcastsPage = lazy(() => import('./pages/PodcastsPage'))
const RssPage = lazy(() => import('./pages/RssPage'))
const DepotPage = lazy(() => import('./pages/DepotPage'))

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Suspense fallback={<PageSpinner />}><DashboardPage /></Suspense>} />
          <Route path="/inbox" element={<Suspense fallback={<PageSpinner />}><InboxPage /></Suspense>} />
          <Route path="/assistant" element={<Suspense fallback={<PageSpinner />}><AssistantPage /></Suspense>} />
          <Route path="/health" element={<Suspense fallback={<PageSpinner />}><HealthPage /></Suspense>} />
          <Route path="/podcasts" element={<Suspense fallback={<PageSpinner />}><PodcastsPage /></Suspense>} />
          <Route path="/rss" element={<Suspense fallback={<PageSpinner />}><RssPage /></Suspense>} />
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
