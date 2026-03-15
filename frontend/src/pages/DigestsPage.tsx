import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { formatDate } from '../lib/utils'
import { PageSpinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import {
  FileText, Plus, Trash2, Check, X, Play, Eye, Clock,
  Mail, Rss, CloudSun, Sparkles, Settings, ArrowUp, ArrowDown
} from 'lucide-react'

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

export default function DigestsPage() {
  const [policies, setPolicies] = useState<DigestPolicy[]>([])
  const [runs, setRuns] = useState<DigestRun[]>([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [running, setRunning] = useState<string | null>(null)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [previewHtml, setPreviewHtml] = useState<string | null>(null)
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
  const [editSectionOrder, setEditSectionOrder] = useState<string[]>(['weather', 'ai_overview', 'mail', 'feeds', 'unsubscribe'])

  const defaultSectionOrder = ['weather', 'ai_overview', 'mail', 'feeds', 'unsubscribe']
  const sectionLabels: Record<string, string> = {
    weather: 'Weather',
    ai_overview: 'AI Overview',
    mail: 'Emails',
    feeds: 'RSS Feeds',
    unsubscribe: 'Unsubscribe Links',
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
    ]).then(([p, r]) => {
      setPolicies(p)
      setRuns(r)
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
          <div className="grid grid-cols-2 gap-3">
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
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <FileText className="w-4 h-4 text-primary" />
                      <span className="font-medium text-sm">{policy.name}</span>
                      <span className={`w-2 h-2 rounded-full ${policy.enabled ? 'bg-emerald-400' : 'bg-gray-500'}`} />
                    </div>
                    <div className="flex items-center gap-3 text-xs text-muted-foreground mt-1.5">
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
                  <div className="flex items-center gap-1">
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
                          try {
                            setEditSectionOrder(policy.section_order ? JSON.parse(policy.section_order) : defaultSectionOrder)
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
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs text-muted-foreground block mb-1">Schedule</label>
                        <select value={editCron} onChange={e => setEditCron(e.target.value)}
                          className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary">
                          <option value="0 7 * * *">Daily at 7:00</option>
                          <option value="0 7 * * 1-5">Weekdays at 7:00</option>
                          <option value="0 8 * * 1">Mondays at 8:00</option>
                          <option value="0 18 * * *">Daily at 18:00</option>
                          {!['0 7 * * *', '0 7 * * 1-5', '0 8 * * 1', '0 18 * * *'].includes(editCron) && (
                            <option value={editCron}>{editCron}</option>
                          )}
                        </select>
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground block mb-1">Target Email</label>
                        <input value={editTargetEmail} onChange={e => setEditTargetEmail(e.target.value)}
                          placeholder="(default account email)"
                          className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary" />
                      </div>
                    </div>

                    {/* Toggles */}
                    <div className="flex items-center gap-5">
                      <label className="flex items-center gap-2 text-sm text-muted-foreground">
                        <input type="checkbox" checked={editWeather} onChange={e => setEditWeather(e.target.checked)} className="rounded" />
                        <CloudSun className="w-3.5 h-3.5" /> Weather
                      </label>
                      <label className="flex items-center gap-2 text-sm text-muted-foreground">
                        <input type="checkbox" checked={editFeeds} onChange={e => setEditFeeds(e.target.checked)} className="rounded" />
                        <Rss className="w-3.5 h-3.5" /> RSS Feeds
                      </label>
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

                    {/* Section Order */}
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

                    {/* Digest Prompt */}
                    <div>
                      <label className="text-xs text-muted-foreground block mb-1">
                        <Sparkles className="w-3 h-3 inline mr-1" />
                        Digest Prompt (leave empty for default)
                      </label>
                      <textarea rows={3} value={editPromptText} onChange={e => setEditPromptText(e.target.value)}
                        placeholder="e.g. Fasse die Mails kurz auf Deutsch zusammen. Hebe Handlungsbedarf und Fristen hervor."
                        className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-primary resize-y" />
                    </div>

                    {/* Weather Prompt */}
                    <div>
                      <label className="text-xs text-muted-foreground block mb-1">
                        <CloudSun className="w-3 h-3 inline mr-1" />
                        Weather Prompt (leave empty for default)
                      </label>
                      <textarea rows={2} value={editWeatherPrompt} onChange={e => setEditWeatherPrompt(e.target.value)}
                        placeholder="e.g. Sag mir ob ich eine Jacke brauche und wie die Woche wird."
                        className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-primary resize-y" />
                    </div>

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
          <div className="bg-card rounded-lg border border-border overflow-hidden">
            <table className="w-full text-sm">
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
                {runs.map(run => {
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
