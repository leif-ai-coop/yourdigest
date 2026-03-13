import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import InboxPage from './pages/InboxPage'
import SettingsPage from './pages/SettingsPage'
import DigestsPage from './pages/DigestsPage'
import LogsPage from './pages/LogsPage'

const navItems = [
  { to: '/', label: 'Inbox' },
  { to: '/digests', label: 'Digests' },
  { to: '/settings', label: 'Settings' },
  { to: '/logs', label: 'Logs' },
]

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col">
        <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6">
          <span className="font-bold text-lg mr-6">Mail Assistant</span>
          {navItems.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-blue-100 text-blue-700'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                }`
              }
              end={to === '/'}
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <main className="flex-1 p-6">
          <Routes>
            <Route path="/" element={<InboxPage />} />
            <Route path="/digests" element={<DigestsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/logs" element={<LogsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
