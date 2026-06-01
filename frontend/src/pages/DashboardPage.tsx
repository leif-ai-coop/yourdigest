import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { AreaChart, Area, ResponsiveContainer, YAxis } from 'recharts'
import { api } from '../api/client'
import { PageSpinner } from '../components/Spinner'
import { DashboardCard } from '../components/DashboardCard'
import { CategoryBadge } from '../components/Badge'
import { formatDate } from '../lib/utils'
import { HEALTH_CARDS, deriveHealthData, HealthChartBody, type GarminData } from '../components/healthCharts'
import {
  Inbox, Wallet, Headphones, Rss, FileText, CloudSun, ScrollText, Heart,
  RefreshCw, Settings2, TrendingUp, TrendingDown, Mail, AlertTriangle,
  Sun, Cloud, CloudRain, CloudSnow, CloudFog, CloudLightning, CloudDrizzle, Droplets, Wind,
  type LucideIcon,
} from 'lucide-react'

// ---------------------------------------------------------------------------

interface Summary {
  inbox?: { received: number; unread: number; flagged: number; categories: { category: string; count: number }[]; latest: { id: string; subject: string | null; is_read: boolean }[] } | null
  depot?: { totals: any; series: { date: string; value: number }[]; top: { name: string; last_value: number | null; day_change_pct: number | null }[] } | null
  podcasts?: { queued: number; active: number; errors: number; done: number; latest: { id: string; title: string; feed: string; status: string; published_at: string | null }[] } | null
  rss?: { feeds: number; new_24h: number; latest: { id: string; title: string | null; feed: string; published_at: string | null }[] } | null
  digests?: { last_run: { policy: string; status: string; item_count: number; started_at: string } | null; active_policies: number } | null
  weather?: { source: string; temperature: number | null; feels_like: number | null; condition: string | null; icon: string | null; humidity: number | null; wind: number | null; uv_index: number | null; forecast: any[] } | null
  activity?: { recent: { action: string; entity_type: string | null; at: string }[] } | null
}
interface Config { order: string[]; hidden: string[] }

const WIDGET_META: Record<string, { title: string; icon: LucideIcon; span: '1' | '2'; route?: string }> = {
  inbox: { title: 'Inbox (24h)', icon: Inbox, span: '1', route: '/inbox' },
  weather: { title: 'Wetter', icon: CloudSun, span: '1' },
  depot: { title: 'Depot', icon: Wallet, span: '2', route: '/depot' },
  podcasts: { title: 'Podcasts', icon: Headphones, span: '1', route: '/podcasts' },
  rss: { title: 'RSS', icon: Rss, span: '1', route: '/rss' },
  digests: { title: 'Digests', icon: FileText, span: '1', route: '/digests' },
  activity: { title: 'Aktivität', icon: ScrollText, span: '2', route: '/logs' },
}

function metaFor(id: string): { title: string; icon: LucideIcon; span: '1' | '2'; route?: string } | null {
  if (id.startsWith('health:')) {
    const card = HEALTH_CARDS.find(c => c.id === id.slice(7))
    if (!card) return null
    return { title: card.title, icon: card.icon, span: card.id === 'activities' ? '2' : '1', route: '/health' }
  }
  return WIDGET_META[id] || null
}

const WEATHER_ICONS: Record<string, LucideIcon> = {
  clear: Sun, sunny: Sun, partly_cloudy: CloudSun, cloudy: Cloud, overcast: Cloud,
  fog: CloudFog, drizzle: CloudDrizzle, rain: CloudRain, snow: CloudSnow, thunderstorm: CloudLightning,
}
const weatherIcon = (t: string | null | undefined): LucideIcon => WEATHER_ICONS[t || ''] || CloudSun

// "dd.mm. - 14h", rounded to the full hour, 24h, local time.
function fmtDT(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso.replace(' ', 'T'))
  if (isNaN(d.getTime())) return ''
  if (d.getMinutes() >= 30) d.setHours(d.getHours() + 1)
  d.setMinutes(0, 0, 0)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  return `${dd}.${mm}. - ${String(d.getHours()).padStart(2, '0')}h`
}

const eur = (v: number | null | undefined) => v == null ? '–' : v.toLocaleString('de-DE', { maximumFractionDigits: 0 }) + ' €'
const pct = (v: number | null | undefined) => (v == null ? '' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

function garminRange(days: number) {
  const end = new Date(); const start = new Date(); start.setDate(start.getDate() - days)
  return { start: start.toISOString().split('T')[0], end: end.toISOString().split('T')[0] }
}

// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const navigate = useNavigate()
  const [summary, setSummary] = useState<Summary | null>(null)
  const [garmin, setGarmin] = useState<GarminData | null>(null)
  const [order, setOrder] = useState<string[]>([])
  const [hidden, setHidden] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [configuring, setConfiguring] = useState(false)
  const [draggingCard, setDraggingCard] = useState<string | null>(null)
  const dragOverCard = useRef<string | null>(null)

  const derived = useMemo(() => deriveHealthData(garmin), [garmin])

  const loadData = useCallback(async () => {
    const { start, end } = garminRange(30)
    const [s, g] = await Promise.all([
      api.get<Summary>('/dashboard/summary'),
      api.get<GarminData>(`/garmin/data?start_date=${start}&end_date=${end}`).catch(() => null),
    ])
    setSummary(s); setGarmin(g)
  }, [])

  useEffect(() => {
    const init = async () => {
      setLoading(true)
      const [cfg] = await Promise.all([api.get<Config>('/dashboard/config'), loadData()])
      setOrder(cfg.order); setHidden(cfg.hidden)
      setLoading(false)
    }
    init()
  }, [loadData])

  const saveConfig = useCallback((o: string[], h: string[]) => {
    api.put('/dashboard/config', { order: o, hidden: h }).catch(() => {})
  }, [])

  const handleRefresh = async () => { setRefreshing(true); try { await loadData() } finally { setRefreshing(false) } }

  const handleDragStart = useCallback((id: string) => setDraggingCard(id), [])
  const handleDragOver = useCallback((_e: React.DragEvent, id: string) => { dragOverCard.current = id }, [])
  const handleDrop = useCallback((targetId: string) => {
    if (!draggingCard || draggingCard === targetId) return
    setOrder(prev => {
      const next = [...prev]; const f = next.indexOf(draggingCard); const t = next.indexOf(targetId)
      if (f === -1 || t === -1) return prev
      next.splice(f, 1); next.splice(t, 0, draggingCard); saveConfig(next, hidden); return next
    })
    setDraggingCard(null)
  }, [draggingCard, hidden, saveConfig])
  const handleDragEnd = useCallback(() => setDraggingCard(null), [])
  const moveCard = useCallback((cardId: string, dir: -1 | 1) => {
    setOrder(prev => {
      const next = [...prev]; const idx = next.indexOf(cardId); if (idx === -1) return prev
      const target = idx + dir; if (target < 0 || target >= next.length) return prev
      ;[next[idx], next[target]] = [next[target], next[idx]]; saveConfig(next, hidden); return next
    })
  }, [hidden, saveConfig])

  const toggleVisible = (id: string) => {
    setHidden(prev => { const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]; saveConfig(order, next); return next })
  }

  if (loading) return <PageSpinner />

  const visible = order.filter(id => metaFor(id) && !hidden.includes(id))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Dashboard</h1>
        <div className="flex items-center gap-2">
          <button onClick={() => setConfiguring(v => !v)} className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md border border-border ${configuring ? 'text-primary bg-primary/10' : 'text-muted-foreground hover:text-foreground'}`}>
            <Settings2 className="w-4 h-4" /> Konfigurieren
          </button>
          <button onClick={handleRefresh} className="p-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground" title="Aktualisieren">
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {configuring && (
        <div className="bg-card border border-border rounded-lg p-3 space-y-3">
          <div>
            <div className="text-xs text-muted-foreground mb-2">Widgets ein-/ausblenden (Reihenfolge per Drag bzw. Pfeile auf den Karten)</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {order.filter(id => WIDGET_META[id]).map(id => (
                <label key={id} className="flex items-center gap-2 text-sm text-muted-foreground">
                  <input type="checkbox" checked={!hidden.includes(id)} onChange={() => toggleVisible(id)} className="rounded" />
                  {WIDGET_META[id].title}
                </label>
              ))}
            </div>
          </div>
          <div className="border-t border-border pt-3">
            <div className="text-xs text-muted-foreground mb-2 flex items-center gap-1.5"><Heart className="w-3.5 h-3.5" /> Health-Diagramme (exakt wie auf der Health-Seite)</div>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {HEALTH_CARDS.map(c => (
                <label key={c.id} className="flex items-center gap-2 text-sm text-muted-foreground">
                  <input type="checkbox" checked={!hidden.includes(`health:${c.id}`)} onChange={() => toggleVisible(`health:${c.id}`)} className="rounded" />
                  {c.title}
                </label>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {visible.map((id, idx) => {
          const meta = metaFor(id)!
          return (
            <DashboardCard
              key={id} cardId={id} title={meta.title} icon={meta.icon} span={meta.span}
              dragging={draggingCard}
              onDragStart={handleDragStart} onDragOver={handleDragOver} onDrop={handleDrop} onDragEnd={handleDragEnd}
              onMoveUp={() => moveCard(id, -1)} onMoveDown={() => moveCard(id, 1)}
              isFirst={idx === 0} isLast={idx === visible.length - 1}
              onOpen={meta.route && !configuring ? () => navigate(meta.route!) : undefined}
            >
              {id.startsWith('health:')
                ? <HealthChartBody id={id.slice(7)} d={derived} />
                : <Widget id={id} summary={summary} />}
            </DashboardCard>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><div className="text-lg font-semibold text-foreground leading-tight">{value}</div><div className="text-[11px] text-muted-foreground">{label}</div></div>
}
const Empty = () => <div className="flex items-center gap-2 text-xs text-muted-foreground"><AlertTriangle className="w-3.5 h-3.5" /> Keine Daten</div>

function Widget({ id, summary }: { id: string; summary: Summary | null }) {
  const navigate = useNavigate()
  const go = (e: React.MouseEvent, path: string) => { e.stopPropagation(); navigate(path) }
  if (!summary) return <div className="text-xs text-muted-foreground">–</div>

  if (id === 'inbox') {
    const dd = summary.inbox; if (!dd) return <Empty />
    const maxCount = Math.max(1, ...dd.categories.map(c => c.count))
    return (
      <div className="space-y-3">
        <div className="flex gap-6">
          <Stat label="empfangen" value={dd.received} />
          <Stat label="ungelesen" value={<span className="text-primary">{dd.unread}</span>} />
          <Stat label="markiert" value={dd.flagged} />
        </div>
        {dd.categories.length > 0 ? (
          <div className="space-y-1">
            {dd.categories.slice(0, 6).map(c => (
              <button key={c.category} onClick={ev => go(ev, `/inbox?category=${encodeURIComponent(c.category)}`)} className="w-full flex items-center gap-2 group/cat">
                <div className="w-24 flex-shrink-0 text-left"><CategoryBadge category={c.category} /></div>
                <div className="flex-1 h-2 bg-secondary rounded overflow-hidden"><div className="h-full bg-primary/60 group-hover/cat:bg-primary rounded" style={{ width: `${(c.count / maxCount) * 100}%` }} /></div>
                <span className="text-xs text-muted-foreground w-6 text-right">{c.count}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="space-y-1">
            {dd.latest.slice(0, 3).map(m => (
              <div key={m.id} className="flex items-center gap-2 text-xs"><Mail className={`w-3 h-3 flex-shrink-0 ${m.is_read ? 'text-muted-foreground' : 'text-primary'}`} /><span className={`truncate ${m.is_read ? 'text-muted-foreground' : 'text-foreground'}`}>{m.subject || '(ohne Betreff)'}</span></div>
            ))}
            {dd.latest.length === 0 && <div className="text-xs text-muted-foreground">Keine Mails in den letzten 24h</div>}
          </div>
        )}
      </div>
    )
  }

  if (id === 'depot') {
    const dd = summary.depot; if (!dd) return <Empty />
    const t = dd.totals || {}; const dc = t.day_change_value
    return (
      <div className="flex flex-col sm:flex-row gap-4">
        <div className="space-y-2 sm:w-1/3">
          <Stat label="Depotwert" value={eur(t.total_value)} />
          <div className={`text-sm font-medium flex items-center gap-1 ${dc >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {dc >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            {dc != null ? `${dc >= 0 ? '+' : ''}${dc.toFixed(0)} € heute` : '–'}
          </div>
          {t.total_gain != null && <div className={`text-xs ${t.total_gain >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>G/V {t.total_gain >= 0 ? '+' : ''}{t.total_gain.toFixed(0)} € ({pct(t.total_gain_pct)})</div>}
        </div>
        <div className="flex-1 min-h-[90px]">
          {dd.series.length > 1 ? (
            <ResponsiveContainer width="100%" height={100}>
              <AreaChart data={dd.series} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                <defs><linearGradient id="dashDepot" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6366f1" stopOpacity={0.35} /><stop offset="100%" stopColor="#6366f1" stopOpacity={0} /></linearGradient></defs>
                <YAxis domain={['dataMin', 'dataMax']} hide />
                <Area type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} fill="url(#dashDepot)" baseValue="dataMin" />
              </AreaChart>
            </ResponsiveContainer>
          ) : <div className="text-xs text-muted-foreground">Noch kein Verlauf</div>}
        </div>
      </div>
    )
  }

  if (id === 'podcasts') {
    const dd = summary.podcasts; if (!dd) return <Empty />
    return (
      <div className="space-y-2">
        <div className="flex gap-4">
          {dd.active > 0 && <span className="text-xs text-blue-400">{dd.active} aktiv</span>}
          {dd.queued > 0 && <span className="text-xs text-muted-foreground">{dd.queued} wartend</span>}
          {dd.errors > 0 && <span className="text-xs text-red-400">{dd.errors} Fehler</span>}
          <span className="text-xs text-emerald-400">{dd.done} fertig</span>
        </div>
        <div className="space-y-1">
          {dd.latest.map((e) => (
            <button key={e.id} onClick={ev => go(ev, `/podcasts?episode=${e.id}`)} className="w-full text-left text-xs flex items-center gap-2 hover:text-primary">
              <span className="text-muted-foreground tabular-nums whitespace-nowrap flex-shrink-0">{fmtDT(e.published_at)}</span>
              <span className="truncate">{e.title}</span>
            </button>
          ))}
          {dd.latest.length === 0 && <div className="text-xs text-muted-foreground">Keine Episoden</div>}
        </div>
      </div>
    )
  }

  if (id === 'rss') {
    const dd = summary.rss; if (!dd) return <Empty />
    return (
      <div className="space-y-2">
        <div className="flex gap-6"><Stat label="Feeds" value={dd.feeds} /><Stat label="neu (24h)" value={<span className="text-primary">{dd.new_24h}</span>} /></div>
        <div className="space-y-1">
          {dd.latest.map((it) => (
            <button key={it.id} onClick={ev => go(ev, `/rss?item=${it.id}`)} className="w-full text-left text-xs flex items-center gap-2 hover:text-primary">
              <span className="text-muted-foreground tabular-nums whitespace-nowrap flex-shrink-0">{fmtDT(it.published_at)}</span>
              <span className="truncate min-w-0">{it.title || '(ohne Titel)'}</span>
              <span className="ml-auto text-muted-foreground truncate max-w-[38%] flex-shrink-0">{it.feed}</span>
            </button>
          ))}
          {dd.latest.length === 0 && <div className="text-xs text-muted-foreground">Keine Items</div>}
        </div>
      </div>
    )
  }

  if (id === 'digests') {
    const dd = summary.digests; if (!dd) return <Empty />
    const r = dd.last_run
    return (
      <div className="space-y-1">
        <Stat label="aktive Policies" value={dd.active_policies} />
        {r ? <div className="text-xs text-muted-foreground">Letzter Lauf: <span className="text-foreground">{r.policy}</span> · {r.status} · {r.item_count} Items · {formatDate(r.started_at)}</div> : <div className="text-xs text-muted-foreground">Noch kein Lauf</div>}
      </div>
    )
  }

  if (id === 'weather') {
    const dd = summary.weather; if (!dd) return <Empty />
    const Icon = weatherIcon(dd.icon)
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <Icon className="w-12 h-12 text-primary flex-shrink-0" />
          <div>
            <div className="flex items-baseline gap-2"><span className="text-3xl font-semibold text-foreground">{dd.temperature != null ? `${dd.temperature.toFixed(0)}°` : '–'}</span><span className="text-sm text-muted-foreground">{dd.condition}</span></div>
            <div className="text-xs text-muted-foreground">{dd.source}{dd.feels_like != null ? ` · gefühlt ${dd.feels_like.toFixed(0)}°` : ''}</div>
          </div>
        </div>
        <div className="flex gap-4 text-xs text-muted-foreground">
          {dd.humidity != null && <span className="flex items-center gap-1"><Droplets className="w-3.5 h-3.5" />{dd.humidity}%</span>}
          {dd.wind != null && <span className="flex items-center gap-1"><Wind className="w-3.5 h-3.5" />{dd.wind} km/h</span>}
          {dd.uv_index != null && <span className="flex items-center gap-1"><Sun className="w-3.5 h-3.5 text-amber-400" />UV {dd.uv_index.toFixed(0)}</span>}
        </div>
        {dd.forecast?.length > 0 && (
          <div className="flex gap-3 pt-1 border-t border-border">
            {dd.forecast.slice(0, 3).map((f, i) => {
              const FI = weatherIcon(f.icon_type)
              return (
                <div key={i} className="flex flex-col items-center text-[11px] text-muted-foreground flex-1">
                  <span>{new Date(f.date).toLocaleDateString('de-DE', { weekday: 'short' })}</span>
                  <FI className="w-5 h-5 my-0.5 text-foreground/70" />
                  <span className="text-foreground">{Math.round(f.temp_max)}°<span className="text-muted-foreground">/{Math.round(f.temp_min)}°</span></span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  if (id === 'activity') {
    const dd = summary.activity; if (!dd || dd.recent.length === 0) return <Empty />
    return (
      <div className="space-y-1">
        {dd.recent.slice(0, 6).map((a, i) => (
          <div key={i} className="flex items-center gap-2 text-xs"><span className="text-foreground">{a.action}</span>{a.entity_type && <span className="text-muted-foreground">{a.entity_type}</span>}<span className="text-muted-foreground ml-auto">{formatDate(a.at)}</span></div>
        ))}
      </div>
    )
  }

  return null
}
