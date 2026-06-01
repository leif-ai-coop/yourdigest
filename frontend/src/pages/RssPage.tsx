import { useEffect, useState, useCallback, useRef } from 'react'
import Markdown from 'react-markdown'
import { api } from '../api/client'
import { PageSpinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import { ModelPicker } from '../components/ModelPicker'
import { formatDate } from '../lib/utils'
import {
  Rss, Plus, RefreshCw, Trash2, Search, Settings2, Sparkles, FileText,
  X, ChevronLeft, Check, Newspaper,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Feed {
  id: string
  url: string
  title: string | null
  description: string | null
  enabled: boolean
  fetch_interval_minutes: number
  last_fetched_at: string | null
  last_error: string | null
  auto_summarize_items: boolean
  auto_briefing: boolean
  item_summary_prompt_id: string | null
  briefing_prompt_id: string | null
  summary_model: string | null
  briefing_count: number
  last_briefing_at: string | null
}

interface ItemEntry {
  id: string
  feed_id: string
  feed_title: string | null
  title: string | null
  link: string | null
  author: string | null
  published_at: string | null
  is_read: boolean
  summary_status: string
  has_ai_summary: boolean
  created_at: string
}

interface ItemDetail extends ItemEntry {
  guid: string
  summary: string | null
  content: string | null
  ai_summary: string | null
  ai_summary_model: string | null
  ai_summarized_at: string | null
  summary_error: string | null
}

interface RssPrompt {
  id: string
  name: string
  description: string | null
  system_prompt: string
  prompt_type: string
  version: number
  is_default: boolean
}

interface Briefing {
  id: string
  feed_id: string
  content: string | null
  model: string | null
  item_count: number | null
  period_start: string | null
  period_end: string | null
  is_active: boolean
  created_at: string
}

type Tab = 'items' | 'briefings' | 'prompts' | 'settings'

// Minimal client-side HTML sanitize for displaying feed content.
function sanitizeHtml(html: string): string {
  return html
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, '')
    .replace(/\son\w+="[^"]*"/gi, '')
    .replace(/\son\w+='[^']*'/gi, '')
    .replace(/javascript:/gi, '')
}

// ---------------------------------------------------------------------------

export default function RssPage() {
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>('items')

  const [feeds, setFeeds] = useState<Feed[]>([])
  const [items, setItems] = useState<ItemEntry[]>([])
  const [selected, setSelected] = useState<ItemDetail | null>(null)

  const [selectedFeedId, setSelectedFeedId] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'unread' | 'summarized'>('all')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [mobileStep, setMobileStep] = useState<'feeds' | 'list' | 'detail'>('feeds')

  const [prompts, setPrompts] = useState<RssPrompt[]>([])
  const [globalModels, setGlobalModels] = useState<{ id: string }[]>([])
  const [globalAppDefault, setGlobalAppDefault] = useState('')

  const [showAddFeed, setShowAddFeed] = useState(false)
  const [feedForm, setFeedForm] = useState({ url: '', title: '' })
  const [syncingFeed, setSyncingFeed] = useState<string | null>(null)
  const [settingsFeed, setSettingsFeed] = useState<Feed | null>(null)
  const [summarizing, setSummarizing] = useState(false)

  const pollRef = useRef<number | null>(null)

  // --- loaders ---
  const loadFeeds = useCallback(async () => {
    setFeeds(await api.get<Feed[]>('/feeds/'))
  }, [])

  const loadItems = useCallback(async () => {
    const params = new URLSearchParams()
    if (selectedFeedId) params.set('feed_id', selectedFeedId)
    if (filter === 'unread') params.set('is_read', 'false')
    if (filter === 'summarized') params.set('summary_status', 'done')
    if (debouncedSearch) params.set('q', debouncedSearch)
    params.set('page_size', '100')
    setItems(await api.get<ItemEntry[]>(`/feeds/items?${params.toString()}`))
  }, [selectedFeedId, filter, debouncedSearch])

  const loadPrompts = useCallback(async () => {
    setPrompts(await api.get<RssPrompt[]>('/feeds/prompts'))
  }, [])

  const loadGlobal = useCallback(async () => {
    const [models, active] = await Promise.all([
      api.get<{ id: string }[]>('/llm/models'),
      api.get<{ model: string }>('/llm/active-model'),
    ])
    setGlobalModels(models)
    setGlobalAppDefault(active.model)
  }, [])

  useEffect(() => {
    const init = async () => {
      setLoading(true)
      await Promise.all([loadFeeds(), loadItems(), loadPrompts(), loadGlobal()])
      setLoading(false)
    }
    init()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 400)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => { loadItems() }, [loadItems])

  // poll selected item while a summary is running
  useEffect(() => {
    if (selected && (selected.summary_status === 'pending' || selected.summary_status === 'processing')) {
      pollRef.current = window.setInterval(async () => {
        const fresh = await api.get<ItemDetail>(`/feeds/items/${selected.id}`)
        setSelected(fresh)
        if (fresh.summary_status === 'done' || fresh.summary_status === 'error') {
          loadItems()
        }
      }, 3000)
      return () => { if (pollRef.current) window.clearInterval(pollRef.current) }
    }
  }, [selected, loadItems])

  // --- actions ---
  const openItem = async (id: string) => {
    const detail = await api.get<ItemDetail>(`/feeds/items/${id}`)
    setSelected(detail)
    setMobileStep('detail')
    if (!detail.is_read) {
      await api.put(`/feeds/items/${id}`, { is_read: true })
      setItems(prev => prev.map(it => it.id === id ? { ...it, is_read: true } : it))
    }
  }

  const summarizeSelected = async () => {
    if (!selected) return
    setSummarizing(true)
    try {
      await api.post(`/feeds/items/${selected.id}/summarize`)
      setSelected({ ...selected, summary_status: 'pending', summary_error: null })
    } finally {
      setSummarizing(false)
    }
  }

  const addFeed = async (e: React.FormEvent) => {
    e.preventDefault()
    await api.post<Feed>('/feeds/', { url: feedForm.url, title: feedForm.title || null })
    setShowAddFeed(false)
    setFeedForm({ url: '', title: '' })
    await loadFeeds()
    await loadItems()
  }

  const syncFeed = async (id: string) => {
    setSyncingFeed(id)
    try {
      const r = await api.post<{ new_items: number }>(`/feeds/${id}/sync`)
      await loadFeeds()
      await loadItems()
      alert(`${r.new_items} neue Items`)
    } finally {
      setSyncingFeed(null)
    }
  }

  const deleteFeed = async (id: string) => {
    if (!confirm('Feed wirklich loeschen? Alle Items gehen verloren.')) return
    await api.delete(`/feeds/${id}`)
    if (selectedFeedId === id) setSelectedFeedId(null)
    await loadFeeds()
    await loadItems()
  }

  if (loading) return <PageSpinner />

  const tabs: { key: Tab; label: string }[] = [
    { key: 'items', label: 'Artikel' },
    { key: 'briefings', label: 'Briefings' },
    { key: 'prompts', label: 'Prompts' },
    { key: 'settings', label: 'Einstellungen' },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Rss className="w-5 h-5 text-primary" /> RSS
        </h1>
      </div>

      <div className="flex gap-1 border-b border-border pb-px overflow-x-auto">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-2 text-sm whitespace-nowrap transition-colors ${
              tab === t.key ? 'text-primary border-b-2 border-primary font-medium' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ===================== ITEMS ===================== */}
      {tab === 'items' && (
        <div className="flex gap-4 h-[calc(100dvh-12rem)] md:h-[calc(100vh-12rem)]">
          {/* Feed sidebar */}
          <div className={`${mobileStep === 'feeds' ? 'flex' : 'hidden'} md:flex flex-col w-full md:w-60 flex-shrink-0 border border-border rounded-lg bg-card overflow-hidden`}>
            <div className="p-2 border-b border-border flex items-center justify-between">
              <span className="text-sm font-medium px-1">Feeds</span>
              <button onClick={() => setShowAddFeed(!showAddFeed)} className="p-1 rounded hover:bg-secondary text-muted-foreground">
                {showAddFeed ? <X className="w-4 h-4" /> : <Plus className="w-4 h-4" />}
              </button>
            </div>
            {showAddFeed && (
              <form onSubmit={addFeed} className="p-2 space-y-2 border-b border-border">
                <input value={feedForm.url} onChange={e => setFeedForm({ ...feedForm, url: e.target.value })} placeholder="Feed-URL" required className="w-full px-2 py-1.5 text-xs bg-secondary rounded border border-border" />
                <input value={feedForm.title} onChange={e => setFeedForm({ ...feedForm, title: e.target.value })} placeholder="Titel (optional)" className="w-full px-2 py-1.5 text-xs bg-secondary rounded border border-border" />
                <button type="submit" className="w-full px-2 py-1.5 text-xs bg-primary text-primary-foreground rounded">Hinzufuegen</button>
              </form>
            )}
            <div className="flex-1 overflow-y-auto">
              <button
                onClick={() => { setSelectedFeedId(null); setMobileStep('list') }}
                className={`w-full text-left px-3 py-2 text-sm border-b border-border/30 ${!selectedFeedId ? 'bg-primary/15 text-primary font-medium' : 'hover:bg-secondary/50'}`}
              >
                Alle Artikel
              </button>
              {feeds.map(f => (
                <div key={f.id} className={`group flex items-center border-b border-border/30 ${selectedFeedId === f.id ? 'bg-primary/15' : 'hover:bg-secondary/50'}`}>
                  <button
                    onClick={() => { setSelectedFeedId(f.id); setMobileStep('list') }}
                    className={`flex-1 min-w-0 text-left px-3 py-2 text-sm truncate ${selectedFeedId === f.id ? 'text-primary font-medium' : ''}`}
                  >
                    <span className={`inline-block w-1.5 h-1.5 rounded-full mr-2 ${f.enabled ? 'bg-emerald-400' : 'bg-gray-500'}`} />
                    {f.title || f.url}
                    {f.last_error && <span className="block text-[10px] text-red-400 truncate">{f.last_error}</span>}
                  </button>
                  <div className="flex items-center pr-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={() => syncFeed(f.id)} className="p-1 rounded hover:bg-secondary text-muted-foreground" title="Sync">
                      <RefreshCw className={`w-3.5 h-3.5 ${syncingFeed === f.id ? 'animate-spin' : ''}`} />
                    </button>
                    <button onClick={() => setSettingsFeed(f)} className="p-1 rounded hover:bg-secondary text-muted-foreground" title="Einstellungen">
                      <Settings2 className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => deleteFeed(f.id)} className="p-1 rounded hover:bg-secondary text-red-400" title="Loeschen">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
              {feeds.length === 0 && <div className="p-3 text-xs text-muted-foreground">Noch keine Feeds.</div>}
            </div>
          </div>

          {/* Item list */}
          <div className={`${mobileStep === 'list' ? 'flex' : 'hidden'} md:flex flex-col flex-1 md:max-w-sm border border-border rounded-lg bg-card overflow-hidden`}>
            <div className="p-2 border-b border-border space-y-2">
              <div className="flex items-center gap-2">
                <button onClick={() => setMobileStep('feeds')} className="md:hidden p-1 text-muted-foreground"><ChevronLeft className="w-4 h-4" /></button>
                <div className="relative flex-1">
                  <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Suchen..." className="w-full pl-7 pr-2 py-1.5 text-xs bg-secondary rounded border border-border" />
                </div>
              </div>
              <div className="flex gap-1">
                {(['all', 'unread', 'summarized'] as const).map(f => (
                  <button key={f} onClick={() => setFilter(f)} className={`px-2 py-1 text-xs rounded ${filter === f ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'}`}>
                    {f === 'all' ? 'Alle' : f === 'unread' ? 'Ungelesen' : 'Zusammengefasst'}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto">
              {items.map(it => (
                <button
                  key={it.id}
                  onClick={() => openItem(it.id)}
                  className={`w-full text-left px-3 py-2 border-b border-border/30 ${selected?.id === it.id ? 'bg-primary/10' : 'hover:bg-secondary/50'}`}
                >
                  <div className={`text-sm truncate ${it.is_read ? 'text-muted-foreground' : 'font-medium'}`}>{it.title || '(ohne Titel)'}</div>
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground mt-0.5">
                    <span className="truncate">{it.feed_title}</span>
                    {it.published_at && <span>· {formatDate(it.published_at)}</span>}
                    {it.has_ai_summary && <Sparkles className="w-3 h-3 text-primary flex-shrink-0" />}
                    {(it.summary_status === 'pending' || it.summary_status === 'processing') && <RefreshCw className="w-3 h-3 animate-spin flex-shrink-0" />}
                  </div>
                </button>
              ))}
              {items.length === 0 && <div className="p-4"><EmptyState icon={Newspaper} title="Keine Artikel" description="Feed synchronisieren oder Filter aendern." /></div>}
            </div>
          </div>

          {/* Detail */}
          <div className={`${mobileStep === 'detail' ? 'flex' : 'hidden'} md:flex flex-col flex-1 border border-border rounded-lg bg-card overflow-hidden`}>
            {!selected ? (
              <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">Artikel auswaehlen</div>
            ) : (
              <div className="flex flex-col h-full">
                <div className="p-3 border-b border-border">
                  <button onClick={() => setMobileStep('list')} className="md:hidden mb-2 text-xs text-muted-foreground flex items-center gap-1"><ChevronLeft className="w-3 h-3" /> Liste</button>
                  <h2 className="font-semibold">{selected.title || '(ohne Titel)'}</h2>
                  <div className="text-xs text-muted-foreground mt-1">
                    {selected.feed_title}{selected.author ? ` · ${selected.author}` : ''}{selected.published_at ? ` · ${formatDate(selected.published_at)}` : ''}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 mt-2">
                    <button onClick={summarizeSelected} disabled={summarizing || selected.summary_status === 'pending' || selected.summary_status === 'processing'} className="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded flex items-center gap-1 disabled:opacity-60">
                      <Sparkles className="w-3.5 h-3.5" />
                      {selected.summary_status === 'pending' || selected.summary_status === 'processing'
                        ? 'Laeuft...'
                        : selected.ai_summary ? 'Neu zusammenfassen' : 'Zusammenfassen'}
                    </button>
                    {selected.link && <a href={selected.link} target="_blank" rel="noopener noreferrer" className="px-3 py-1.5 text-xs bg-secondary rounded text-muted-foreground">Original oeffnen</a>}
                  </div>
                </div>
                <div className="flex-1 overflow-y-auto p-3 space-y-4">
                  {selected.summary_error && <div className="text-xs text-red-400 bg-red-500/10 p-2 rounded">{selected.summary_error}</div>}
                  {selected.ai_summary && (
                    <div className="bg-primary/5 border border-primary/20 rounded-lg p-3">
                      <div className="text-xs font-medium text-primary flex items-center gap-1 mb-2"><Sparkles className="w-3.5 h-3.5" /> KI-Zusammenfassung{selected.ai_summary_model ? ` · ${selected.ai_summary_model}` : ''}</div>
                      <div className="prose prose-invert prose-sm max-w-none text-sm"><Markdown>{selected.ai_summary}</Markdown></div>
                    </div>
                  )}
                  <div>
                    <div className="text-xs font-medium text-muted-foreground mb-2">Original-Inhalt</div>
                    {selected.content
                      ? <div className="mail-body prose prose-invert prose-sm max-w-none text-sm" dangerouslySetInnerHTML={{ __html: sanitizeHtml(selected.content) }} />
                      : <div className="text-sm text-muted-foreground">{selected.summary || 'Kein Inhalt — siehe Original.'}</div>}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ===================== BRIEFINGS ===================== */}
      {tab === 'briefings' && <BriefingsTab feeds={feeds} />}

      {/* ===================== PROMPTS ===================== */}
      {tab === 'prompts' && <PromptsTab prompts={prompts} reload={loadPrompts} />}

      {/* ===================== SETTINGS ===================== */}
      {tab === 'settings' && <RssSettingsTab models={globalModels} appDefault={globalAppDefault} />}

      {settingsFeed && (
        <FeedSettingsModal
          feed={settingsFeed}
          prompts={prompts}
          onClose={() => setSettingsFeed(null)}
          onSaved={async () => { setSettingsFeed(null); await loadFeeds() }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Briefings tab
// ---------------------------------------------------------------------------

function BriefingsTab({ feeds }: { feeds: Feed[] }) {
  const [feedId, setFeedId] = useState<string>(feeds[0]?.id || '')
  const [briefing, setBriefing] = useState<Briefing | null>(null)
  const [history, setHistory] = useState<Briefing[]>([])
  const [generating, setGenerating] = useState(false)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (fid: string) => {
    if (!fid) return
    setLoading(true)
    try {
      const [active, hist] = await Promise.all([
        api.get<Briefing | null>(`/feeds/${fid}/briefing`),
        api.get<Briefing[]>(`/feeds/briefings?feed_id=${fid}`),
      ])
      setBriefing(active)
      setHistory(hist)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (feedId) load(feedId) }, [feedId, load])

  const generate = async () => {
    setGenerating(true)
    try {
      await api.post(`/feeds/${feedId}/briefing`)
      // briefing runs in background; poll a few times
      for (let i = 0; i < 8; i++) {
        await new Promise(r => setTimeout(r, 2500))
        const active = await api.get<Briefing | null>(`/feeds/${feedId}/briefing`)
        if (active && (!briefing || active.id !== briefing.id)) { setBriefing(active); break }
      }
      await load(feedId)
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center gap-2 flex-wrap">
        <select value={feedId} onChange={e => setFeedId(e.target.value)} className="px-3 py-2 text-sm bg-secondary rounded border border-border">
          <option value="">Feed waehlen...</option>
          {feeds.map(f => <option key={f.id} value={f.id}>{f.title || f.url}</option>)}
        </select>
        <button onClick={generate} disabled={!feedId || generating} className="px-3 py-2 text-sm bg-primary text-primary-foreground rounded flex items-center gap-1 disabled:opacity-60">
          <Sparkles className="w-4 h-4" /> {generating ? 'Generiere...' : 'Jetzt generieren'}
        </button>
      </div>

      {loading ? <div className="text-sm text-muted-foreground">Laedt...</div> : briefing ? (
        <div className="bg-card border border-border rounded-lg p-4">
          <div className="text-xs text-muted-foreground mb-2">
            {briefing.item_count} Artikel · {briefing.model} · {formatDate(briefing.created_at)}
          </div>
          <div className="prose prose-invert prose-sm max-w-none"><Markdown>{briefing.content || ''}</Markdown></div>
        </div>
      ) : feedId ? (
        <EmptyState icon={FileText} title="Noch kein Briefing" description="Jetzt generieren, um eine Zusammenfassung der letzten Artikel zu erstellen." />
      ) : null}

      {history.length > 1 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">Aeltere Briefings ({history.length - 1})</summary>
          <div className="mt-2 space-y-2">
            {history.filter(b => !b.is_active).map(b => (
              <details key={b.id} className="bg-card border border-border rounded-lg p-3">
                <summary className="cursor-pointer text-xs text-muted-foreground">{formatDate(b.created_at)} · {b.item_count} Artikel</summary>
                <div className="prose prose-invert prose-sm max-w-none mt-2"><Markdown>{b.content || ''}</Markdown></div>
              </details>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Prompts tab
// ---------------------------------------------------------------------------

function PromptsTab({ prompts, reload }: { prompts: RssPrompt[]; reload: () => Promise<void> }) {
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState<RssPrompt | null>(null)

  const save = async (data: Record<string, unknown>, id?: string) => {
    if (id) await api.put(`/feeds/prompts/${id}`, data)
    else await api.post('/feeds/prompts', data)
    setShowAdd(false); setEditing(null)
    await reload()
  }
  const del = async (id: string) => {
    if (!confirm('Prompt loeschen?')) return
    await api.delete(`/feeds/prompts/${id}`)
    await reload()
  }

  const typeLabel = (t: string) => t === 'feed_briefing' ? 'Briefing' : 'Artikel'

  return (
    <div className="space-y-4 max-w-2xl">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">Zusammenfassungs-Prompts</h2>
        <button onClick={() => { setEditing(null); setShowAdd(true) }} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md flex items-center gap-1">
          <Plus className="w-4 h-4" /> Neuer Prompt
        </button>
      </div>
      {(showAdd || editing) && (
        <PromptForm prompt={editing} onSave={(d) => save(d, editing?.id)} onCancel={() => { setShowAdd(false); setEditing(null) }} />
      )}
      {prompts.map(p => (
        <div key={p.id} className="p-4 bg-card rounded-lg border border-border">
          <div className="flex items-center justify-between">
            <div>
              <span className="font-medium text-sm">{p.name}</span>
              <span className="ml-2 px-1.5 py-0.5 text-xs rounded bg-purple-500/20 text-purple-400">{typeLabel(p.prompt_type)}</span>
              {p.is_default && <span className="ml-1 px-1.5 py-0.5 text-xs bg-primary/20 text-primary rounded">Default</span>}
              <span className="ml-2 text-xs text-muted-foreground">v{p.version}</span>
            </div>
            <div className="flex gap-1">
              <button onClick={() => { setShowAdd(false); setEditing(p) }} className="p-1 rounded hover:bg-secondary text-muted-foreground"><Settings2 className="w-4 h-4" /></button>
              <button onClick={() => del(p.id)} className="p-1 rounded hover:bg-secondary text-red-400"><Trash2 className="w-4 h-4" /></button>
            </div>
          </div>
          {p.description && <div className="text-xs text-muted-foreground mt-1">{p.description}</div>}
          <pre className="mt-2 text-xs text-muted-foreground bg-secondary/30 p-2 rounded max-h-32 overflow-y-auto whitespace-pre-wrap">{p.system_prompt}</pre>
        </div>
      ))}
      {prompts.length === 0 && !showAdd && <EmptyState icon={FileText} title="Keine Prompts" description="Der eingebaute Default wird verwendet." />}
    </div>
  )
}

function PromptForm({ prompt, onSave, onCancel }: {
  prompt: RssPrompt | null
  onSave: (data: { name: string; description?: string; system_prompt: string; prompt_type: string; is_default: boolean }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(prompt?.name || '')
  const [desc, setDesc] = useState(prompt?.description || '')
  const [text, setText] = useState(prompt?.system_prompt || '')
  const [promptType, setPromptType] = useState(prompt?.prompt_type || 'item_summary')
  const [isDefault, setIsDefault] = useState(prompt?.is_default || false)

  return (
    <div className="p-4 bg-card rounded-lg border border-border space-y-3">
      <input value={name} onChange={e => setName(e.target.value)} placeholder="Prompt-Name" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
      <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Beschreibung (optional)" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
      <select value={promptType} onChange={e => setPromptType(e.target.value)} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border">
        <option value="item_summary">Artikel-Zusammenfassung</option>
        <option value="feed_briefing">Feed-Briefing</option>
      </select>
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder="System-Prompt..." rows={8} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border font-mono" />
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={isDefault} onChange={e => setIsDefault(e.target.checked)} className="rounded" />
          Default fuer diesen Typ
        </label>
        <div className="flex-1" />
        <button onClick={onCancel} className="px-3 py-1.5 text-sm text-muted-foreground">Abbrechen</button>
        <button onClick={() => onSave({ name, description: desc || undefined, system_prompt: text, prompt_type: promptType, is_default: isDefault })} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md" disabled={!name || !text}>
          Speichern
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Global settings tab
// ---------------------------------------------------------------------------

function RssSettingsTab({ models, appDefault }: { models: { id: string }[]; appDefault: string }) {
  const [form, setForm] = useState({ item_summary_model: '', briefing_model: '' })
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.get<{ item_summary_model: string; briefing_model: string }>('/settings/rss').then(setForm)
  }, [])

  const save = async () => {
    await api.put('/settings/rss', form)
    setSaved(true); setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="space-y-6 max-w-lg">
      <div>
        <h2 className="text-sm font-medium mb-2">Globale AI-Modelle</h2>
        <p className="text-xs text-muted-foreground mb-4">Gelten fuer alle Feeds ohne eigenes Modell. Leer = App-Default.</p>
        <div className="space-y-4">
          <ModelPicker label="Artikel-Zusammenfassung" value={form.item_summary_model} onChange={v => setForm({ ...form, item_summary_model: v })} models={models} appDefault={appDefault} />
          <ModelPicker label="Feed-Briefing" value={form.briefing_model} onChange={v => setForm({ ...form, briefing_model: v })} models={models} appDefault={appDefault} />
        </div>
        <button onClick={save} className="mt-4 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md">{saved ? 'Gespeichert' : 'Speichern'}</button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-feed settings modal
// ---------------------------------------------------------------------------

function FeedSettingsModal({ feed, prompts, onClose, onSaved }: {
  feed: Feed
  prompts: RssPrompt[]
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [form, setForm] = useState({
    title: feed.title || '',
    enabled: feed.enabled,
    auto_summarize_items: feed.auto_summarize_items,
    auto_briefing: feed.auto_briefing,
    item_summary_prompt_id: feed.item_summary_prompt_id || '',
    briefing_prompt_id: feed.briefing_prompt_id || '',
    summary_model: feed.summary_model || '',
    briefing_count: feed.briefing_count,
    fetch_interval_minutes: feed.fetch_interval_minutes,
  })
  const itemPrompts = prompts.filter(p => p.prompt_type === 'item_summary')
  const briefingPrompts = prompts.filter(p => p.prompt_type === 'feed_briefing')

  const save = async () => {
    await api.put(`/feeds/${feed.id}`, {
      ...form,
      item_summary_prompt_id: form.item_summary_prompt_id || null,
      briefing_prompt_id: form.briefing_prompt_id || null,
      summary_model: form.summary_model || null,
    })
    await onSaved()
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-lg w-full max-w-md max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 className="font-semibold text-sm">Feed-Einstellungen</h2>
          <button onClick={onClose} className="p-1 text-muted-foreground"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-4 space-y-3">
          <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="Titel" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
          <div className="text-xs text-muted-foreground break-all">{feed.url}</div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} className="rounded" /> Aktiv
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.auto_summarize_items} onChange={e => setForm({ ...form, auto_summarize_items: e.target.checked })} className="rounded" /> Neue Artikel automatisch zusammenfassen
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.auto_briefing} onChange={e => setForm({ ...form, auto_briefing: e.target.checked })} className="rounded" /> Automatisches Feed-Briefing
          </label>

          <div>
            <label className="text-xs text-muted-foreground">Artikel-Prompt</label>
            <select value={form.item_summary_prompt_id} onChange={e => setForm({ ...form, item_summary_prompt_id: e.target.value })} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border">
              <option value="">Default</option>
              {itemPrompts.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Briefing-Prompt</label>
            <select value={form.briefing_prompt_id} onChange={e => setForm({ ...form, briefing_prompt_id: e.target.value })} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border">
              <option value="">Default</option>
              {briefingPrompts.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="flex gap-3">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">Briefing: Artikel-Anzahl</label>
              <input type="number" min={1} max={50} value={form.briefing_count} onChange={e => setForm({ ...form, briefing_count: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
            </div>
            <div className="flex-1">
              <label className="text-xs text-muted-foreground">Fetch-Intervall (min)</label>
              <input type="number" min={5} value={form.fetch_interval_minutes} onChange={e => setForm({ ...form, fetch_interval_minutes: Number(e.target.value) || 60 })} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
            </div>
          </div>
          <input value={form.summary_model} onChange={e => setForm({ ...form, summary_model: e.target.value })} placeholder="Modell-Override (optional, leer = global)" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
        </div>
        <div className="p-4 border-t border-border flex justify-end gap-2">
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-muted-foreground">Abbrechen</button>
          <button onClick={save} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md flex items-center gap-1"><Check className="w-4 h-4" /> Speichern</button>
        </div>
      </div>
    </div>
  )
}
