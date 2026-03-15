import { useState } from 'react'
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { Inbox, FileText, Settings, ScrollText, PanelLeftClose, PanelLeft, MessageSquare, Heart, LogOut } from 'lucide-react'

function AppIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 512 512" fill="none" className={className} xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="ic-accent" x1="0" y1="0" x2="512" y2="512" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#5b9cf6"/>
          <stop offset="100%" stopColor="#3b7dd8"/>
        </linearGradient>
        <linearGradient id="ic-glow" x1="200" y1="200" x2="312" y2="312" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#7bb8ff"/>
          <stop offset="100%" stopColor="#5b9cf6"/>
        </linearGradient>
      </defs>
      <path d="M 100 140 Q 180 160 220 230" stroke="url(#ic-accent)" strokeWidth="14" strokeLinecap="round" opacity="0.5"/>
      <path d="M 80 256 Q 160 256 220 256" stroke="url(#ic-accent)" strokeWidth="14" strokeLinecap="round" opacity="0.65"/>
      <path d="M 100 372 Q 180 352 220 282" stroke="url(#ic-accent)" strokeWidth="14" strokeLinecap="round" opacity="0.5"/>
      <circle cx="92" cy="140" r="12" fill="#5b9cf6" opacity="0.6"/>
      <circle cx="72" cy="256" r="12" fill="#5b9cf6" opacity="0.75"/>
      <circle cx="92" cy="372" r="12" fill="#5b9cf6" opacity="0.6"/>
      <circle cx="256" cy="256" r="52" fill="url(#ic-glow)" opacity="0.15"/>
      <circle cx="256" cy="256" r="36" fill="url(#ic-glow)" opacity="0.25"/>
      <circle cx="256" cy="256" r="22" fill="url(#ic-glow)"/>
      <path d="M 256 238 L 260 250 L 274 250 L 263 258 L 267 270 L 256 263 L 245 270 L 249 258 L 238 250 L 252 250 Z" fill="currentColor" opacity="0.7"/>
      <path d="M 292 230 Q 332 180 390 130" stroke="url(#ic-accent)" strokeWidth="14" strokeLinecap="round" opacity="0.7"/>
      <path d="M 292 250 Q 350 250 410 220" stroke="url(#ic-accent)" strokeWidth="14" strokeLinecap="round" opacity="0.8"/>
      <path d="M 292 256 Q 360 256 420 256" stroke="url(#ic-accent)" strokeWidth="16" strokeLinecap="round" opacity="0.9"/>
      <path d="M 292 262 Q 350 262 410 292" stroke="url(#ic-accent)" strokeWidth="14" strokeLinecap="round" opacity="0.8"/>
      <path d="M 292 282 Q 332 332 390 382" stroke="url(#ic-accent)" strokeWidth="14" strokeLinecap="round" opacity="0.7"/>
      <circle cx="396" cy="126" r="10" fill="#5b9cf6" opacity="0.7"/>
      <circle cx="416" cy="216" r="10" fill="#5b9cf6" opacity="0.8"/>
      <circle cx="428" cy="256" r="13" fill="#5b9cf6" opacity="0.95"/>
      <circle cx="416" cy="296" r="10" fill="#5b9cf6" opacity="0.8"/>
      <circle cx="396" cy="386" r="10" fill="#5b9cf6" opacity="0.7"/>
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
          <span className="text-sm font-semibold tracking-tight whitespace-nowrap">CuraOS Assistant</span>
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
            assistant.curaos.de
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
