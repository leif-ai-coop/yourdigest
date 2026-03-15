import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import InboxPage from './pages/InboxPage'
import SettingsPage from './pages/SettingsPage'
import DigestsPage from './pages/DigestsPage'
import LogsPage from './pages/LogsPage'
import AssistantPage from './pages/AssistantPage'
import HealthPage from './pages/HealthPage'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<InboxPage />} />
          <Route path="/assistant" element={<AssistantPage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route path="/digests" element={<DigestsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/logs" element={<LogsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
