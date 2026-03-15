import { useState } from 'react'
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { Inbox, FileText, Settings, ScrollText, PanelLeftClose, PanelLeft, MessageSquare, Heart, LogOut } from 'lucide-react'

function AppIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 128 128" fill="none" className={className} xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="ic-gM" x1="32" y1="0" x2="64" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#E91E63"/><stop offset="100%" stopColor="#00E5FF"/>
        </linearGradient>
        <linearGradient id="ic-gO" x1="32" y1="0" x2="64" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FF9800"/><stop offset="100%" stopColor="#00E5FF"/>
        </linearGradient>
        <linearGradient id="ic-gG" x1="32" y1="0" x2="64" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#00E676"/><stop offset="100%" stopColor="#00E5FF"/>
        </linearGradient>
        <linearGradient id="ic-gP" x1="32" y1="0" x2="64" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#7C4DFF"/><stop offset="100%" stopColor="#00E5FF"/>
        </linearGradient>
      </defs>
      <g>
        <polygon points="0,16 32,48 32,56 0,40" fill="#E91E63"/>
        <polygon points="0,40 32,56 32,64 0,64" fill="#FF9800"/>
        <polygon points="0,64 32,64 32,72 0,88" fill="#00E676"/>
        <polygon points="0,88 32,72 32,80 0,112" fill="#7C4DFF"/>
      </g>
      <polygon points="64,64 96,48 96,80 64,96" fill="#0D141F"/>
      <polygon points="32,48 64,64 64,96 32,80" fill="#121B29"/>
      <polygon points="64,32 32,48 64,64 96,48" fill="#182436"/>
      <g>
        <polygon points="32,48 64,72 64,76 32,56" fill="url(#ic-gM)"/>
        <polygon points="32,56 64,76 64,80 32,64" fill="url(#ic-gO)"/>
        <polygon points="32,64 64,80 64,84 32,72" fill="url(#ic-gG)"/>
        <polygon points="32,72 64,84 64,88 32,80" fill="url(#ic-gP)"/>
      </g>
      <polygon points="64,72 96,56 96,72 64,88" fill="#00E5FF"/>
      <polygon points="64,76 96,60 96,68 64,84" fill="#FFFFFF"/>
      <polygon points="96,56 128,52 128,76 96,72" fill="#00E5FF"/>
      <polygon points="96,60 128,58 128,70 96,68" fill="#FFFFFF"/>
    </svg>
  )
}

const navItems = [
  { to: '/', label: 'Inbox', icon: Inbox },
  { to: '/assistant', label: 'Assistant', icon: MessageSquare },
  { to: '/health', label: 'Health', icon: Heart },
  { to: '/digests', label: 'Digests', icon: FileText },
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/logs', label: 'Logs', icon: ScrollText },
]

export default function Layout() {
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? 'w-56' : 'w-0'} bg-card border-r border-border flex flex-col fixed h-screen overflow-hidden transition-all duration-200`}>
        {/* Logo */}
        <div className="px-5 py-5 flex items-center gap-2.5 min-w-[14rem]">
          <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center overflow-hidden flex-shrink-0">
            <AppIcon className="w-7 h-7 text-background" />
          </div>
          <span className="text-sm font-semibold tracking-tight whitespace-nowrap">You Digest</span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-2 space-y-0.5 min-w-[14rem]">
          {navItems.map(({ to, label, icon: Icon }) => {
            const isActive = to === '/' ? location.pathname === '/' : location.pathname.startsWith(to)
            return (
              <NavLink
                key={to}
                to={to}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors whitespace-nowrap ${
                  isActive
                    ? 'bg-primary/15 text-primary font-medium'
                    : 'text-foreground/70 hover:text-foreground hover:bg-secondary'
                }`}
              >
                <Icon className="w-4 h-4" />
                {label}
              </NavLink>
            )
          })}
        </nav>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-border min-w-[14rem] flex items-center justify-between">
          <div className="text-xs text-muted-foreground whitespace-nowrap">
            You Digest
          </div>
          <a
            href="/outpost.goauthentik.io/sign_out"
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            title="Logout"
          >
            <LogOut className="w-3.5 h-3.5" />
          </a>
        </div>
      </aside>

      {/* Sidebar Toggle */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className={`fixed top-4 ${sidebarOpen ? 'left-[13rem]' : 'left-3'} z-10 p-1.5 rounded-md bg-card border border-border text-muted-foreground hover:text-foreground transition-all duration-200`}
        title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
      >
        {sidebarOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeft className="w-4 h-4" />}
      </button>

      {/* Main Content */}
      <main className={`${sidebarOpen ? 'ml-56' : 'ml-0'} flex-1 min-h-screen transition-all duration-200`}>
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
