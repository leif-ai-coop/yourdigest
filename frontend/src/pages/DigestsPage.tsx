import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { formatDate } from '../lib/utils'
import { PageSpinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import {
  FileText, Plus, Trash2, Check, X, Play, Eye, Clock,
  Mail, Rss, CloudSun, Sparkles, Settings, ArrowUp, ArrowDown, Heart, Headphones
} from 'lucide-react'

interface HealthOption {
  id: string
  label: string
}

interface DigestPolicy {
  id: string
  name: string
  schedule_cron: string
  target_email: string | null
  include_categories: string[] | null
  exclude_categories: string[] | null
  max_items: number
  include_weather: boolean
  include_feeds: boolean
  enabled: boolean
  template: string
  digest_prompt: string | null
  weather_prompt: string | null
  max_tokens: number
  since_last_any_digest: boolean
  section_order: string | null
  include_health: boolean
  include_podcasts: boolean
  health_charts: string[] | null
  health_prompt: string | null
  health_data_types: string[] | null
  health_days: number
  created_at: string
}

interface DigestRun {
  id: string
  policy_id: string
  status: string
  started_at: string
  completed_at: string | null
  item_count: number
  error: string | null
  created_at: string
}

type Repeat = 'daily' | 'weekdays' | 'weekly' | 'biweekly' | 'monthly'

const DAYS = [
  { key: '1', label: 'Mo' }, { key: '2', label: 'Di' }, { key: '3', label: 'Mi' },
  { key: '4', label: 'Do' }, { key: '5', label: 'Fr' }, { key: '6', label: 'Sa' }, { key: '0', label: 'So' },
]

function parseCron(cron: string): { hour: string; minute: string; repeat: Repeat; days: string[]; monthDay: string } {
  const parts = cron.split(/\s+/)
  const minute = parts[0] || '0'
  const hour = parts[1] || '7'
  const dom = parts[2] || '*'
  const dow = parts[4] || '*'

  let repeat: Repeat = 'daily'
  let days: string[] = []
  let monthDay = '1'

  if (dom !== '*') {
    repeat = dom.includes('/15') ? 'biweekly' : 'monthly'
    monthDay = dom.replace(/\/.*/, '')
  } else if (dow === '1-5') {
    repeat = 'weekdays'
  } else if (dow !== '*') {
    const dowParts = dow.split(',')
    days = dowParts
    repeat = 'weekly'
  }

  return { hour, minute, repeat, days, monthDay }
}

function buildCron(hour: string, minute: string, repeat: Repeat, days: string[], monthDay: string): string {
  const h = parseInt(hour) || 0
  const m = parseInt(minute) || 0
  switch (repeat) {
    case 'daily': return `${m} ${h} * * *`
    case 'weekdays': return `${m} ${h} * * 1-5`
    case 'weekly': return `${m} ${h} * * ${days.length > 0 ? days.join(',') : '1'}`
    case 'biweekly': return `${m} ${h} 1,15 * *`
    case 'monthly': return `${m} ${h} ${monthDay || '1'} * *`
  }
}

function ScheduleBuilder({ cron, onChange }: { cron: string; onChange: (cron: string) => void }) {
  const parsed = parseCron(cron)
  const [repeat, setRepeat] = useState<Repeat>(parsed.repeat)
  const [hour, setHour] = useState(parsed.hour)
  const [minute, setMinute] = useState(parsed.minute)
  const [days, setDays] = useState<string[]>(parsed.days)
  const [monthDay, setMonthDay] = useState(parsed.monthDay)

  const update = (r: Repeat, h: string, m: string, d: string[], md: string) => {
    onChange(buildCron(h, m, r, d, md))
  }

  const inputCls = "bg-secondary border border-border rounded-md px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"

  return (
    <div className="space-y-2">
      <label className="text-xs text-muted-foreground block mb-1">Schedule</label>
      <div className="flex flex-wrap items-center gap-2">
        <select value={repeat} onChange={e => { const r = e.target.value as Repeat; setRepeat(r); update(r, hour, minute, days, monthDay) }} className={inputCls}>
          <option value="daily">Täglich</option>
          <option value="weekdays">Werktags</option>
          <option value="weekly">Wöchentlich</option>
          <option value="biweekly">Zweiwöchentlich</option>
          <option value="monthly">Monatlich</option>
        </select>
        <span className="text-xs text-muted-foreground">um</span>
        <input type="number" min={0} max={23} value={hour} onChange={e => { setHour(e.target.value); update(repeat, e.target.value, minute, days, monthDay) }} className={`${inputCls} w-14 text-center`} />
        <span className="text-xs text-muted-foreground">:</span>
        <input type="number" min={0} max={59} step={5} value={minute} onChange={e => { setMinute(e.target.value); update(repeat, hour, e.target.value, days, monthDay) }} className={`${inputCls} w-14 text-center`} />
        <span className="text-xs text-muted-foreground">Uhr</span>
      </div>

      {repeat === 'weekly' && (
        <div className="flex gap-1">
          {DAYS.map(d => (
            <button key={d.key} onClick={() => {
              const next = days.includes(d.key) ? days.filter(k => k !== d.key) : [...days, d.key]
              setDays(next)
              update(repeat, hour, minute, next, monthDay)
            }}
              className={`px-2 py-1 text-xs rounded-md transition-colors ${
                days.includes(d.key) ? 'bg-primary/20 text-primary font-medium' : 'bg-secondary text-muted-foreground hover:text-foreground'
              }`}>
              {d.label}
            </button>
          ))}
        </div>
      )}

      {repeat === 'monthly' && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Am</span>
          <input type="number" min={1} max={28} value={monthDay} onChange={e => { setMonthDay(e.target.value); update(repeat, hour, minute, days, e.target.value) }} className={`${inputCls} w-14 text-center`} />
          <span className="text-xs text-muted-foreground">. des Monats</span>
        </div>
      )}

      <div className="text-[10px] text-muted-foreground font-mono">{cron}</div>
    </div>
  )
}

export default function DigestsPage() {
  const [policies, setPolicies] = useState<DigestPolicy[]>([])
  const [runs, setRuns] = useState<DigestRun[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [running, setRunning] = useState<string | null>(null)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [previewHtml, setPreviewHtml] = useState<string | null>(null)
  const [runsPage, setRunsPage] = useState(0)
  const RUNS_PER_PAGE = 5
  const [form, setForm] = useState({
    name: '', schedule_cron: '0 7 * * *', target_email: '',
    include_weather: true, include_feeds: true, since_last_any_digest: false,
    include_categories: '', exclude_categories: '',
    digest_prompt: '',
  })
  const [editingSettings, setEditingSettings] = useState<string | null>(null)
  const [editWeather, setEditWeather] = useState(true)
  const [editFeeds, setEditFeeds] = useState(true)
  const [editSinceAny, setEditSinceAny] = useState(false)
  const [editTargetEmail, setEditTargetEmail] = useState('')
  const [editCron, setEditCron] = useState('')
  const [editPromptText, setEditPromptText] = useState('')
  const [editWeatherPrompt, setEditWeatherPrompt] = useState('')
  const [editMaxTokens, setEditMaxTokens] = useState(4000)
  const [editSectionOrder, setEditSectionOrder] = useState<string[]>(['weather', 'health', 'ai_overview', 'mail', 'feeds', 'unsubscribe'])
  const [editHealth, setEditHealth] = useState(false)
  const [editHealthCharts, setEditHealthCharts] = useState<string[]>([])
  const [editHealthPrompt, setEditHealthPrompt] = useState('')
  const [editHealthDataTypes, setEditHealthDataTypes] = useState<string[]>([])
  const [healthChartOptions, setHealthChartOptions] = useState<HealthOption[]>([])
  const [healthDataTypeOptions, setHealthDataTypeOptions] = useState<HealthOption[]>([])
  const [editHealthDays, setEditHealthDays] = useState(7)
  const [editPodcasts, setEditPodcasts] = useState(false)

  const defaultSectionOrder = ['weather', 'health', 'ai_overview', 'mail', 'podcasts', 'feeds', 'unsubscribe']
  const sectionLabels: Record<string, string> = {
    weather: 'Weather',
    health: 'Health',
    ai_overview: 'AI Overview',
    mail: 'Emails',
    podcasts: 'Podcasts',
    feeds: 'RSS Feeds',
    unsubscribe: 'Unsubscribe Links',
  }

  // Toggle a section: add to order if enabling, remove if disabling
  const toggleSection = (key: string, enabled: boolean) => {
    if (enabled) {
      if (!editSectionOrder.includes(key)) {
        // Insert at default position
        const defIdx = defaultSectionOrder.indexOf(key)
        const newOrder = [...editSectionOrder]
        let insertAt = newOrder.length
        for (let i = defIdx + 1; i < defaultSectionOrder.length; i++) {
          const pos = newOrder.indexOf(defaultSectionOrder[i])
          if (pos !== -1) { insertAt = pos; break }
        }
        newOrder.splice(insertAt, 0, key)
        setEditSectionOrder(newOrder)
      }
    } else {
      setEditSectionOrder(prev => prev.filter(k => k !== key))
    }
  }

  const moveSectionUp = (idx: number) => {
    if (idx === 0) return
    const arr = [...editSectionOrder]
    ;[arr[idx - 1], arr[idx]] = [arr[idx], arr[idx - 1]]
    setEditSectionOrder(arr)
  }

  const moveSectionDown = (idx: number) => {
    if (idx >= editSectionOrder.length - 1) return
    const arr = [...editSectionOrder]
    ;[arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]]
    setEditSectionOrder(arr)
  }

  useEffect(() => {
    Promise.all([
      api.get<DigestPolicy[]>('/digest/policies'),
      api.get<DigestRun[]>('/digest/runs'),
      api.get<{ charts: HealthOption[]; data_types: HealthOption[] }>('/digest/health-options'),
    ]).then(([p, r, ho]) => {
      setPolicies(p)
      setRuns(r)
      setHealthChartOptions(ho.charts)
      setHealthDataTypeOptions(ho.data_types)
    }).finally(() => setLoading(false))
  }, [])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    const incCats = form.include_categories ? form.include_categories.split(',').map(s => s.trim()).filter(Boolean) : null
    const exCats = form.exclude_categories ? form.exclude_categories.split(',').map(s => s.trim()).filter(Boolean) : null
    const policy = await api.post<DigestPolicy>('/digest/policies', {
      name: form.name,
      schedule_cron: form.schedule_cron,
      target_email: form.target_email || null,
      max_items: 9999,
      include_weather: form.include_weather,
      include_feeds: form.include_feeds,
      since_last_any_digest: form.since_last_any_digest,
      include_categories: incCats,
      exclude_categories: exCats,
      digest_prompt: form.digest_prompt || null,
      enabled: true,
    })
    setPolicies(prev => [...prev, policy])
    setShowAdd(false)
    setForm({ name: '', schedule_cron: '0 7 * * *', target_email: '', include_weather: true, include_feeds: true, since_last_any_digest: false, include_categories: '', exclude_categories: '', digest_prompt: '' })
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this digest policy?')) return
    await api.delete(`/digest/policies/${id}`)
    setPolicies(prev => prev.filter(p => p.id !== id))
  }

  const handleToggle = async (policy: DigestPolicy) => {
    const updated = await api.put<DigestPolicy>(`/digest/policies/${policy.id}`, {
      enabled: !policy.enabled,
    })
    setPolicies(prev => prev.map(p => p.id === policy.id ? updated : p))
  }

  const [runMenuOpen, setRunMenuOpen] = useState<string | null>(null)

  const handleRun = async (policyId: string, sinceHours?: number, cross?: boolean) => {
    setRunning(policyId)
    setRunMenuOpen(null)
    try {
      const params = new URLSearchParams()
      if (sinceHours !== undefined) params.set('since_hours', String(sinceHours))
      if (cross) params.set('cross', 'true')
      const query = params.toString() ? `?${params}` : ''
      const run = await api.post<DigestRun>(`/digest/policies/${policyId}/run${query}`)
      setRuns(prev => [run, ...prev])
    } catch (e: any) {
      alert(`Digest run failed: ${e.message}`)
    } finally {
      setRunning(null)
    }
  }

  const handlePreview = async (runId: string) => {
    if (previewId === runId) {
      setPreviewId(null)
      setPreviewHtml(null)
      return
    }
    try {
      const res = await fetch(`/api/digest/runs/${runId}/html`)
      if (!res.ok) throw new Error('No HTML available')
      const html = await res.text()
      setPreviewId(runId)
      setPreviewHtml(html)
    } catch {
      alert('No preview available for this run')
    }
  }

  if (loading) return <PageSpinner />

  const cronLabels: Record<string, string> = {
    '0 7 * * *': 'Daily at 7:00',
    '0 7 * * 1-5': 'Weekdays at 7:00',
    '0 8 * * 1': 'Mondays at 8:00',
    '0 18 * * *': 'Daily at 18:00',
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <FileText className="w-5 h-5 text-primary" />
          <h1 className="text-xl font-semibold">Digests</h1>
        </div>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors"
        >
          {showAdd ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
          {showAdd ? 'Cancel' : 'New Policy'}
        </button>
      </div>

      {/* Add Policy Form */}
      {showAdd && (
        <form onSubmit={handleAdd} className="bg-card rounded-lg border border-border p-4 mb-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <input placeholder="Policy Name" value={form.name} onChange={e => setForm({...form, name: e.target.value})}
              className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
            <select value={form.schedule_cron} onChange={e => setForm({...form, schedule_cron: e.target.value})}
              className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary">
              <option value="0 7 * * *">Daily at 7:00</option>
              <option value="0 7 * * 1-5">Weekdays at 7:00</option>
              <option value="0 8 * * 1">Mondays at 8:00</option>
              <option value="0 18 * * *">Daily at 18:00</option>
            </select>
            <input placeholder="Target Email (optional)" type="email" value={form.target_email}
              onChange={e => setForm({...form, target_email: e.target.value})}
              className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
            <input placeholder="Include categories (comma-separated)" value={form.include_categories}
              onChange={e => setForm({...form, include_categories: e.target.value})}
              className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
            <input placeholder="Exclude categories (comma-separated)" value={form.exclude_categories}
              onChange={e => setForm({...form, exclude_categories: e.target.value})}
              className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
          </div>
          <div className="flex items-center gap-4 mt-3">
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input type="checkbox" checked={form.include_weather} onChange={e => setForm({...form, include_weather: e.target.checked})}
                className="rounded" />
              <CloudSun className="w-3.5 h-3.5" /> Include Weather
            </label>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input type="checkbox" checked={form.include_feeds} onChange={e => setForm({...form, include_feeds: e.target.checked})}
                className="rounded" />
              <Rss className="w-3.5 h-3.5" /> Include RSS Feeds
            </label>
            <label className="flex items-center gap-2 text-sm text-muted-foreground" title="Zeitraum beginnt beim letzten Lauf einer beliebigen Digest-Policy statt nur der eigenen">
              <input type="checkbox" checked={form.since_last_any_digest} onChange={e => setForm({...form, since_last_any_digest: e.target.checked})}
                className="rounded" />
              <Clock className="w-3.5 h-3.5" /> Since last any digest
            </label>
          </div>
          <div className="mt-3">
            <label className="text-xs text-muted-foreground block mb-1">
              Digest Prompt (optional — how the AI should summarize, leave empty for default)
            </label>
            <textarea
              placeholder="e.g. Summarize the emails briefly in German. Focus on action items and deadlines. Group by urgency."
              rows={3}
              value={form.digest_prompt}
              onChange={e => setForm({...form, digest_prompt: e.target.value})}
              className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary resize-y"
            />
          </div>
          <button type="submit" className="mt-3 flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm">
            <Check className="w-3.5 h-3.5" /> Create Policy
          </button>
        </form>
      )}

      {/* Policies */}
      {policies.length === 0 && !showAdd ? (
        <EmptyState icon={FileText} title="No digest policies" description="Create a digest policy to receive automated email summaries." />
      ) : (
        <div className="space-y-3 mb-8">
          {policies.map(policy => {
            const policyRuns = runs.filter(r => r.policy_id === policy.id)
            const lastRun = policyRuns[0]
            return (
              <div key={policy.id} className="bg-card rounded-lg border border-border p-4">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-primary" />
                      <span className="font-medium text-sm">{policy.name}</span>
                      <span className={`w-2 h-2 rounded-full ${policy.enabled ? 'bg-emerald-400' : 'bg-gray-500'}`} />
                    </div>
                    <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-xs text-muted-foreground mt-1.5">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {cronLabels[policy.schedule_cron] || policy.schedule_cron}
                      </span>
                      {policy.target_email && (
                        <span className="flex items-center gap-1">
                          <Mail className="w-3 h-3" /> {policy.target_email}
                        </span>
                      )}
                      {policy.include_weather && <CloudSun className="w-3 h-3" />}
                      {policy.include_feeds && <Rss className="w-3 h-3" />}
                      {policy.include_podcasts && <Headphones className="w-3 h-3" />}
                      {policy.since_last_any_digest && <span className="text-xs text-primary" title="Since last any digest">cross</span>}
                    </div>
                    {policy.include_categories && (
                      <div className="text-xs text-muted-foreground mt-1">
                        Include: {policy.include_categories.join(', ')}
                      </div>
                    )}
                    {lastRun && (
                      <div className="text-xs text-muted-foreground mt-1">
                        Last run: {formatDate(lastRun.started_at)} —{' '}
                        <span className={lastRun.status === 'completed' ? 'text-emerald-400' : lastRun.status === 'failed' ? 'text-red-400' : ''}>
                          {lastRun.status}
                        </span>
                        {lastRun.item_count > 0 && ` (${lastRun.item_count} items)`}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-1">
                    <button
                      onClick={() => {
                        if (editingSettings === policy.id) {
                          setEditingSettings(null)
                        } else {
                          setEditingSettings(policy.id)
                          setEditWeather(policy.include_weather)
                          setEditFeeds(policy.include_feeds)
                          setEditSinceAny(policy.since_last_any_digest || false)
                          setEditTargetEmail(policy.target_email || '')
                          setEditCron(policy.schedule_cron)
                          setEditPromptText(policy.digest_prompt || '')
                          setEditWeatherPrompt(policy.weather_prompt || '')
                          setEditMaxTokens(policy.max_tokens || 4000)
                          setEditHealth(policy.include_health || false)
                          setEditPodcasts(policy.include_podcasts || false)
                          setEditHealthCharts(policy.health_charts || [])
                          setEditHealthPrompt(policy.health_prompt || '')
                          setEditHealthDataTypes(policy.health_data_types || [])
                          setEditHealthDays(policy.health_days || 7)
                          try {
                            const stored = policy.section_order ? JSON.parse(policy.section_order) as string[] : defaultSectionOrder
                            // Merge: append any new default keys not in stored order
                            const merged = [...stored]
                            for (const key of defaultSectionOrder) {
                              if (!merged.includes(key)) merged.push(key)
                            }
                            setEditSectionOrder(merged)
                          } catch { setEditSectionOrder(defaultSectionOrder) }
                        }
                      }}
                      className={`flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-border transition-colors ${
                        editingSettings === policy.id ? 'text-primary bg-primary/10' : 'text-muted-foreground hover:text-primary hover:bg-primary/10'
                      }`}
                    >
                      <Settings className="w-3 h-3" /> Settings
                    </button>
                    <div className="relative">
                      <button
                        onClick={() => setRunMenuOpen(runMenuOpen === policy.id ? null : policy.id)}
                        disabled={running === policy.id}
                        className="flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-border text-muted-foreground hover:text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
                      >
                        <Play className={`w-3 h-3 ${running === policy.id ? 'animate-pulse' : ''}`} /> Run Now
                      </button>
                      {runMenuOpen === policy.id && (
                        <div className="absolute right-0 top-full mt-1 z-10 bg-card border border-border rounded-md shadow-lg py-1 min-w-[160px]">
                          {[
                            { label: 'Since last run', hours: undefined, cross: false },
                            { label: 'Since last any digest', hours: undefined, cross: true },
                            { label: 'Last 1 hour', hours: 1, cross: false },
                            { label: 'Last 6 hours', hours: 6, cross: false },
                            { label: 'Last 12 hours', hours: 12, cross: false },
                            { label: 'Last 24 hours', hours: 24, cross: false },
                            { label: 'Last 48 hours', hours: 48, cross: false },
                            { label: 'Last 7 days', hours: 168, cross: false },
                          ].map(opt => (
                            <button
                              key={opt.label}
                              onClick={() => handleRun(policy.id, opt.hours, opt.cross)}
                              className="w-full text-left px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                            >
                              {opt.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    <button onClick={() => handleToggle(policy)}
                      className={`px-2 py-1 text-xs rounded-md border border-border transition-colors ${policy.enabled ? 'text-emerald-400 hover:text-amber-400' : 'text-muted-foreground hover:text-emerald-400'}`}>
                      {policy.enabled ? 'Disable' : 'Enable'}
                    </button>
                    <button onClick={() => handleDelete(policy.id)} className="p-1 text-muted-foreground hover:text-red-400 transition-colors">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Inline Settings Panel */}
                {editingSettings === policy.id && (
                  <div className="mt-3 pt-3 border-t border-border space-y-3">
                    {/* Schedule & Email */}
                    <ScheduleBuilder cron={editCron} onChange={setEditCron} />
                    <div>
                      <label className="text-xs text-muted-foreground block mb-1">Target Email</label>
                      <input value={editTargetEmail} onChange={e => setEditTargetEmail(e.target.value)}
                        placeholder="(default account email)"
                        className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary" />
                    </div>

                    {/* Content Modules */}
                    <div>
                      <label className="text-xs text-muted-foreground block mb-1.5">Inhalte</label>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                        <label className="flex items-center gap-2 text-sm text-muted-foreground">
                          <input type="checkbox" checked={editSectionOrder.includes('mail')}
                            onChange={e => toggleSection('mail', e.target.checked)} className="rounded" />
                          <Mail className="w-3.5 h-3.5" /> Emails
                        </label>
                        <label className="flex items-center gap-2 text-sm text-muted-foreground">
                          <input type="checkbox" checked={editSectionOrder.includes('ai_overview')}
                            onChange={e => toggleSection('ai_overview', e.target.checked)} className="rounded" />
                          <Sparkles className="w-3.5 h-3.5" /> AI Overview
                        </label>
                        <label className="flex items-center gap-2 text-sm text-muted-foreground">
                          <input type="checkbox" checked={editWeather}
                            onChange={e => { setEditWeather(e.target.checked); toggleSection('weather', e.target.checked) }} className="rounded" />
                          <CloudSun className="w-3.5 h-3.5" /> Weather
                        </label>
                        <label className="flex items-center gap-2 text-sm text-muted-foreground">
                          <input type="checkbox" checked={editFeeds}
                            onChange={e => { setEditFeeds(e.target.checked); toggleSection('feeds', e.target.checked) }} className="rounded" />
                          <Rss className="w-3.5 h-3.5" /> RSS Feeds
                        </label>
                        <label className="flex items-center gap-2 text-sm text-muted-foreground">
                          <input type="checkbox" checked={editHealth}
                            onChange={e => { setEditHealth(e.target.checked); toggleSection('health', e.target.checked) }} className="rounded" />
                          <Heart className="w-3.5 h-3.5" /> Health
                        </label>
                        <label className="flex items-center gap-2 text-sm text-muted-foreground">
                          <input type="checkbox" checked={editPodcasts}
                            onChange={e => { setEditPodcasts(e.target.checked); toggleSection('podcasts', e.target.checked) }} className="rounded" />
                          Podcasts
                        </label>
                        <label className="flex items-center gap-2 text-sm text-muted-foreground">
                          <input type="checkbox" checked={editSectionOrder.includes('unsubscribe')}
                            onChange={e => toggleSection('unsubscribe', e.target.checked)} className="rounded" />
                          Unsubscribe
                        </label>
                      </div>
                    </div>

                    {/* Options row */}
                    <div className="flex flex-wrap items-center gap-3">
                      <label className="flex items-center gap-2 text-sm text-muted-foreground">
                        <input type="checkbox" checked={editSinceAny} onChange={e => setEditSinceAny(e.target.checked)} className="rounded" />
                        <Clock className="w-3.5 h-3.5" /> Since last any digest
                      </label>
                      <label className="text-xs text-muted-foreground flex items-center gap-1.5">
                        Max Tokens
                        <input type="number" min={500} max={65536} step={500} value={editMaxTokens}
                          onChange={e => setEditMaxTokens(parseInt(e.target.value) || 4000)}
                          className="w-24 bg-secondary border border-border rounded-md px-2 py-1 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary" />
                      </label>
                    </div>

                    {/* Section Order — only active sections */}
                    {editSectionOrder.length > 1 && (
                      <div>
                        <label className="text-xs text-muted-foreground block mb-1.5">Section Order</label>
                        <div className="flex flex-col gap-1">
                          {editSectionOrder.map((key, idx) => (
                            <div key={key} className="flex items-center gap-2 bg-secondary/50 rounded-md px-3 py-1.5">
                              <span className="text-sm text-foreground flex-1">{sectionLabels[key] || key}</span>
                              <button onClick={() => moveSectionUp(idx)} disabled={idx === 0}
                                className="p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-25 transition-colors">
                                <ArrowUp className="w-3.5 h-3.5" />
                              </button>
                              <button onClick={() => moveSectionDown(idx)} disabled={idx >= editSectionOrder.length - 1}
                                className="p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-25 transition-colors">
                                <ArrowDown className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* AI Overview Prompt */}
                    {editSectionOrder.includes('ai_overview') && (
                      <div>
                        <label className="text-xs text-muted-foreground block mb-1">
                          <Sparkles className="w-3 h-3 inline mr-1" />
                          AI Overview Prompt (leave empty for default)
                        </label>
                        <textarea rows={3} value={editPromptText} onChange={e => setEditPromptText(e.target.value)}
                          placeholder="e.g. Fasse die Mails kurz auf Deutsch zusammen. Hebe Handlungsbedarf und Fristen hervor."
                          className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-primary resize-y" />
                      </div>
                    )}

                    {/* Weather Prompt */}
                    {editWeather && (
                      <div>
                        <label className="text-xs text-muted-foreground block mb-1">
                          <CloudSun className="w-3 h-3 inline mr-1" />
                          Weather Prompt (leave empty for default)
                        </label>
                        <textarea rows={2} value={editWeatherPrompt} onChange={e => setEditWeatherPrompt(e.target.value)}
                          placeholder="e.g. Sag mir ob ich eine Jacke brauche und wie die Woche wird."
                          className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-primary resize-y" />
                      </div>
                    )}

                    {/* Health Settings */}
                    {editHealth && (
                      <div className="border-t border-border pt-3 mt-1 space-y-3">
                        <div className="flex items-center gap-3">
                          <Heart className="w-3.5 h-3.5 text-muted-foreground" />
                          <span className="text-xs font-medium text-muted-foreground">Health Settings</span>
                          <div className="flex gap-1 ml-auto">
                            {[7, 30, 90].map(d => (
                              <button key={d} onClick={() => setEditHealthDays(d)}
                                className={`px-2.5 py-0.5 text-xs rounded-md transition-colors ${
                                  editHealthDays === d
                                    ? 'bg-primary/15 text-primary font-medium'
                                    : 'text-muted-foreground hover:text-foreground bg-secondary'
                                }`}>
                                {d}d
                              </button>
                            ))}
                          </div>
                        </div>

                        <div>
                          <label className="text-xs text-muted-foreground block mb-1.5">Charts im Digest</label>
                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                            {healthChartOptions.map(opt => (
                              <label key={opt.id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                <input type="checkbox"
                                  checked={editHealthCharts.includes(opt.id)}
                                  onChange={e => {
                                    if (e.target.checked) setEditHealthCharts(prev => [...prev, opt.id])
                                    else setEditHealthCharts(prev => prev.filter(id => id !== opt.id))
                                  }}
                                  className="rounded" />
                                {opt.label}
                              </label>
                            ))}
                          </div>
                        </div>

                        <div>
                          <label className="text-xs text-muted-foreground block mb-1.5">Daten fuer AI Health Summary</label>
                          <div className="grid grid-cols-2 gap-1.5">
                            {healthDataTypeOptions.map(opt => (
                              <label key={opt.id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                                <input type="checkbox"
                                  checked={editHealthDataTypes.includes(opt.id)}
                                  onChange={e => {
                                    if (e.target.checked) setEditHealthDataTypes(prev => [...prev, opt.id])
                                    else setEditHealthDataTypes(prev => prev.filter(id => id !== opt.id))
                                  }}
                                  className="rounded" />
                                {opt.label}
                              </label>
                            ))}
                          </div>
                        </div>

                        <div>
                          <label className="text-xs text-muted-foreground block mb-1">
                            <Heart className="w-3 h-3 inline mr-1" />
                            Health Prompt (leave empty for default)
                          </label>
                          <textarea rows={2} value={editHealthPrompt} onChange={e => setEditHealthPrompt(e.target.value)}
                            placeholder="e.g. Analysiere meine Gesundheitsdaten und gib Empfehlungen."
                            className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-primary resize-y" />
                        </div>
                      </div>
                    )}

                    {/* Save / Cancel */}
                    <div className="flex items-center gap-2">
                      <button
                        onClick={async () => {
                          const updated = await api.put<DigestPolicy>(`/digest/policies/${policy.id}`, {
                            schedule_cron: editCron,
                            target_email: editTargetEmail || null,
                            include_weather: editWeather,
                            include_feeds: editFeeds,
                            since_last_any_digest: editSinceAny,
                            max_tokens: editMaxTokens,
                            digest_prompt: editPromptText || null,
                            weather_prompt: editWeatherPrompt || null,
                            section_order: editSectionOrder,
                            include_health: editHealth,
                            include_podcasts: editPodcasts,
                            health_charts: editHealthCharts.length > 0 ? editHealthCharts : null,
                            health_prompt: editHealthPrompt || null,
                            health_data_types: editHealthDataTypes.length > 0 ? editHealthDataTypes : null,
                            health_days: editHealthDays,
                          })
                          setPolicies(prev => prev.map(p => p.id === policy.id ? updated : p))
                          setEditingSettings(null)
                        }}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-xs"
                      >
                        <Check className="w-3 h-3" /> Save
                      </button>
                      <button onClick={() => setEditingSettings(null)}
                        className="px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Recent Runs */}
      {runs.length > 0 && (
        <div>
          <h2 className="text-sm font-medium mb-3">Recent Runs</h2>
          <div className="bg-card rounded-lg border border-border overflow-x-auto">
            <table className="w-full text-sm min-w-[500px]">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="text-left px-4 py-2 font-medium">Policy</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                  <th className="text-left px-4 py-2 font-medium">Items</th>
                  <th className="text-left px-4 py-2 font-medium">Time</th>
                  <th className="text-left px-4 py-2 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {runs.slice(runsPage * RUNS_PER_PAGE, (runsPage + 1) * RUNS_PER_PAGE).map(run => {
                  const policy = policies.find(p => p.id === run.policy_id)
                  return (
                    <tr key={run.id} className="border-b border-border/50">
                      <td className="px-4 py-2 text-xs">{policy?.name || run.policy_id.slice(0, 8)}</td>
                      <td className="px-4 py-2">
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          run.status === 'completed' ? 'bg-emerald-500/15 text-emerald-400' :
                          run.status === 'failed' ? 'bg-red-500/15 text-red-400' :
                          run.status === 'running' ? 'bg-blue-500/15 text-blue-400' :
                          'bg-secondary text-muted-foreground'
                        }`}>
                          {run.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">{run.item_count}</td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">{formatDate(run.started_at)}</td>
                      <td className="px-4 py-2">
                        {run.status === 'completed' && (
                          <button
                            onClick={() => handlePreview(run.id)}
                            className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors"
                          >
                            <Eye className="w-3 h-3" />
                            {previewId === run.id ? 'Hide' : 'Preview'}
                          </button>
                        )}
                        {run.error && <span className="text-xs text-red-400">{run.error.slice(0, 60)}</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {runs.length > RUNS_PER_PAGE && (
              <div className="flex items-center justify-between px-4 py-2 border-t border-border">
                <span className="text-xs text-muted-foreground">
                  {runsPage * RUNS_PER_PAGE + 1}–{Math.min((runsPage + 1) * RUNS_PER_PAGE, runs.length)} of {runs.length}
                </span>
                <div className="flex gap-1">
                  <button onClick={() => setRunsPage(p => p - 1)} disabled={runsPage === 0}
                    className="px-2 py-1 text-xs rounded-md text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors">
                    Prev
                  </button>
                  <button onClick={() => setRunsPage(p => p + 1)} disabled={(runsPage + 1) * RUNS_PER_PAGE >= runs.length}
                    className="px-2 py-1 text-xs rounded-md text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors">
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* HTML Preview */}
      {previewId && previewHtml && (
        <div className="mt-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium">Digest Preview</h2>
            <button onClick={() => { setPreviewId(null); setPreviewHtml(null) }}
              className="text-xs text-muted-foreground hover:text-foreground">
              Close Preview
            </button>
          </div>
          <div className="rounded-lg border border-border overflow-hidden">
            <iframe
              srcDoc={previewHtml}
              className="w-full bg-white rounded-lg"
              style={{ minHeight: '600px', border: 'none' }}
              title="Digest Preview"
            />
          </div>
        </div>
      )}
    </div>
  )
}
