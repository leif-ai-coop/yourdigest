import { useEffect, useState, useCallback, useRef } from 'react'
import Markdown from 'react-markdown'
import { api } from '../api/client'
import { PageSpinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import {
  Headphones, Plus, RefreshCw, Trash2, Star, StarOff, Search,
  AlertTriangle, ChevronRight, Settings2, Send, Play, PanelLeftClose, PanelLeft,
  FileText, MessageSquare, EyeOff, X
} from 'lucide-react'

// Types
interface PodcastFeed {
  id: string
  url: string
  title: string | null
  description: string | null
  image_url: string | null
  language: string | null
  enabled: boolean
  auto_process_new: boolean
  map_prompt_id: string | null
  reduce_prompt_id: string | null
  transcription_model: string | null
  summary_model: string | null
  fetch_interval_minutes: number
  max_episode_duration_seconds: number | null
  min_episode_duration_seconds: number | null
  max_audio_size_mb: number | null
  keep_audio_days: number | null
  ignore_title_patterns: string[] | null
  prefer_external_transcript_url: boolean
  last_fetched_at: string | null
  last_successful_fetch_at: string | null
  consecutive_failures: number
  last_error: string | null
  created_at: string
}

interface PodcastEpisode {
  id: string
  feed_id: string
  guid: string | null
  audio_url: string | null
  title: string | null
  description: string | null
  link: string | null
  episode_number: number | null
  season_number: number | null
  duration_seconds: number | null
  published_at: string | null
  discovery_status: string
  skipped_reason: string | null
  processing_status: string
  processing_attempts: number
  error_class: string | null
  error_message: string | null
  is_retryable: boolean
  chunk_count: number | null
  is_saved: boolean
  summarize_enabled: boolean
  created_at: string
}

interface PodcastArtifact {
  id: string
  episode_id: string
  artifact_type: string
  content: string | null
  prompt_id: string | null
  prompt_version: number | null
  model: string | null
  word_count: number | null
  is_active: boolean
  created_at: string
}

interface PodcastChunk {
  id: string
  chunk_index: number
  start_seconds: number
  end_seconds: number
  status: string
  transcript_text: string | null
  map_summary_text: string | null
  error_class: string | null
  error_message: string | null
  processing_attempts: number
  completed_at: string | null
}

interface EpisodeDetail extends PodcastEpisode {
  artifacts: PodcastArtifact[]
  chunks: PodcastChunk[]
  feed_title: string | null
}

interface PodcastPrompt {
  id: string
  name: string
  description: string | null
  system_prompt: string
  prompt_type: string
  version: number
  is_default: boolean
  created_at: string
  updated_at: string
}

interface PodcastMailPolicy {
  id: string
  name: string
  schedule_cron: string
  target_email: string
  prompt_id: string | null
  feed_filter: string[] | null
  enabled: boolean
  created_at: string
}

interface QueueStatus {
  pending_downloads: number
  active_downloads: number
  pending_transcriptions: number
  active_transcriptions: number
  pending_summaries: number
  active_summaries: number
  errors: number
  done_today: number
  total_episodes: number
}

interface ProcessingRun {
  id: string
  episode_id: string
  chunk_id: string | null
  stage: string
  status: string
  model: string | null
  started_at: string
  completed_at: string | null
  error_class: string | null
  error_message: string | null
  tokens_used: number | null
  duration_ms: number | null
}

type Tab = 'episodes' | 'prompts' | 'policies' | 'queue' | 'settings'

function formatDuration(seconds: number | null): string {
  if (!seconds) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function formatDate(d: string | null): string {
  if (!d) return ''
  return new Date(d).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

function formatDateTime(d: string | null): string {
  if (!d) return ''
  return new Date(d).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    done: 'bg-green-500/20 text-green-400',
    error: 'bg-red-500/20 text-red-400',
    pending: 'bg-yellow-500/20 text-yellow-400',
    downloading: 'bg-blue-500/20 text-blue-400',
    chunking: 'bg-blue-500/20 text-blue-400',
    transcribing: 'bg-indigo-500/20 text-indigo-400',
    summarizing_chunks: 'bg-purple-500/20 text-purple-400',
    reducing: 'bg-purple-500/20 text-purple-400',
    skipped: 'bg-gray-500/20 text-gray-400',
    new: 'bg-cyan-500/20 text-cyan-400',
    accepted: 'bg-green-500/20 text-green-400',
    running: 'bg-blue-500/20 text-blue-400',
    completed: 'bg-green-500/20 text-green-400',
    failed: 'bg-red-500/20 text-red-400',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${styles[status] || 'bg-gray-500/20 text-gray-400'}`}>
      {status}
    </span>
  )
}

export default function PodcastsPage() {
  const [feeds, setFeeds] = useState<PodcastFeed[]>([])
  const [selectedFeed, _setSelectedFeed] = useState<string | null>(null)
  const selectedFeedRef = useRef<string | null>(null)
  const setSelectedFeed = (id: string | null) => { selectedFeedRef.current = id; _setSelectedFeed(id) }
  const [episodes, setEpisodes] = useState<PodcastEpisode[]>([])
  const [selectedEpisode, setSelectedEpisode] = useState<EpisodeDetail | null>(null)
  const [prompts, setPrompts] = useState<PodcastPrompt[]>([])
  const [policies, setPolicies] = useState<PodcastMailPolicy[]>([])
  const [queue, setQueue] = useState<QueueStatus | null>(null)
  const [processingRuns, setProcessingRuns] = useState<ProcessingRun[]>([])
  const [tab, setTab] = useState<Tab>('episodes')
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState<string | null>(null)
  const [showAddFeed, setShowAddFeed] = useState(false)
  const [newFeedUrl, setNewFeedUrl] = useState('')
  const [showAddPrompt, setShowAddPrompt] = useState(false)
  const [showAddPolicy, setShowAddPolicy] = useState(false)
  const [editingPrompt, setEditingPrompt] = useState<PodcastPrompt | null>(null)
  const [editingPolicy, setEditingPolicy] = useState<PodcastMailPolicy | null>(null)
  const [editingFeed, setEditingFeed] = useState<PodcastFeed | null>(null)
  const [episodeFilter, setEpisodeFilter] = useState<'all' | 'saved' | 'done' | 'error' | 'skipped'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchFields, setSearchFields] = useState<Set<string>>(new Set(['title', 'description', 'summary', 'transcript']))
  const [showSearchSettings, setShowSearchSettings] = useState(false)
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [processing, setProcessing] = useState<Set<string>>(new Set())
  const [feedSidebarOpen, setFeedSidebarOpen] = useState(true)
  const detailRef = useRef<HTMLDivElement>(null)
  const [globalSettings, setGlobalSettings] = useState<{ transcription_model: string; summary_model: string }>({ transcription_model: '', summary_model: '' })
  const [globalModels, setGlobalModels] = useState<{ id: string }[]>([])
  const [globalAppDefault, setGlobalAppDefault] = useState('')
  // Mobile: show detail instead of list
  const [mobileShowDetail, setMobileShowDetail] = useState(false)

  const loadFeeds = useCallback(async () => {
    const data = await api.get<PodcastFeed[]>('/podcasts/feeds')
    setFeeds(data)
    return data
  }, [])

  const loadEpisodes = useCallback(async (feedId?: string | null, search?: string) => {
    let path = '/podcasts/episodes?limit=100'
    if (feedId) path += `&feed_id=${feedId}`
    if (episodeFilter === 'saved') path += '&saved_only=true'
    if (episodeFilter === 'done') path += '&status=done'
    if (episodeFilter === 'error') path += '&status=error'
    if (episodeFilter === 'skipped') path += '&discovery=skipped'
    const q = search ?? searchQuery
    if (q.trim()) {
      path += `&search=${encodeURIComponent(q.trim())}`
      path += `&search_fields=${[...searchFields].join(',')}`
    }
    const data = await api.get<PodcastEpisode[]>(path)
    setEpisodes(data)
  }, [episodeFilter])

  const loadEpisodeDetail = useCallback(async (id: string) => {
    const data = await api.get<EpisodeDetail>(`/podcasts/episodes/${id}`)
    setSelectedEpisode(data)
    setMobileShowDetail(true)
    requestAnimationFrame(() => detailRef.current?.scrollTo(0, 0))
  }, [])

  const loadPrompts = useCallback(async () => {
    const data = await api.get<PodcastPrompt[]>('/podcasts/prompts')
    setPrompts(data)
  }, [])

  const loadPolicies = useCallback(async () => {
    const data = await api.get<PodcastMailPolicy[]>('/podcasts/mail-policies')
    setPolicies(data)
  }, [])

  const loadQueue = useCallback(async () => {
    const [q, runs] = await Promise.all([
      api.get<QueueStatus>('/podcasts/queue'),
      api.get<ProcessingRun[]>('/podcasts/processing-runs?limit=30'),
    ])
    setQueue(q)
    setProcessingRuns(runs)
  }, [])

  const loadGlobalSettings = useCallback(async () => {
    const [settings, models, active] = await Promise.all([
      api.get<{ transcription_model: string; summary_model: string }>('/settings/podcasts'),
      api.get<{ id: string }[]>('/llm/models'),
      api.get<{ model: string }>('/llm/active-model'),
    ])
    setGlobalSettings(settings)
    setGlobalModels(models)
    setGlobalAppDefault(active.model)
  }, [])

  useEffect(() => {
    const init = async () => {
      setLoading(true)
      await Promise.all([loadFeeds(), loadEpisodes(), loadPrompts(), loadPolicies(), loadQueue(), loadGlobalSettings()])
      setLoading(false)
    }
    init()
  }, [])

  useEffect(() => {
    loadEpisodes(selectedFeed)
  }, [selectedFeed, episodeFilter])

  const handleSearchChange = (value: string) => {
    setSearchQuery(value)
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current)
    searchTimeoutRef.current = setTimeout(() => {
      loadEpisodes(selectedFeedRef.current, value)
    }, 400)
  }

  const toggleSearchField = (field: string) => {
    setSearchFields(prev => {
      const next = new Set(prev)
      if (next.has(field)) next.delete(field)
      else next.add(field)
      return next
    })
  }

  // Re-search when fields change
  useEffect(() => {
    if (searchQuery.trim()) loadEpisodes(selectedFeed)
  }, [searchFields])

  // Feed actions
  const addFeed = async () => {
    if (!newFeedUrl.trim()) return
    await api.post('/podcasts/feeds', { url: newFeedUrl.trim() })
    setNewFeedUrl('')
    setShowAddFeed(false)
    await loadFeeds()
    await loadEpisodes(selectedFeed)
  }

  const syncFeed = async (id: string) => {
    setSyncing(id)
    await api.post(`/podcasts/feeds/${id}/sync`)
    setSyncing(null)
    await loadEpisodes(selectedFeed)
    await loadFeeds()
  }

  const deleteFeed = async (id: string) => {
    if (!confirm('Feed und alle Episoden loeschen?')) return
    await api.delete(`/podcasts/feeds/${id}`)
    if (selectedFeed === id) setSelectedFeed(null)
    await loadFeeds()
    await loadEpisodes(null)
  }

  const updateFeed = async (id: string, data: Record<string, unknown>) => {
    await api.put(`/podcasts/feeds/${id}`, data)
    await loadFeeds()
    setEditingFeed(null)
  }

  // Episode actions
  const toggleSaved = async (ep: PodcastEpisode) => {
    await api.put(`/podcasts/episodes/${ep.id}`, { is_saved: !ep.is_saved })
    await loadEpisodes(selectedFeed)
    if (selectedEpisode?.id === ep.id) await loadEpisodeDetail(ep.id)
  }

  const skipEpisode = async (id: string) => {
    await api.post(`/podcasts/episodes/${id}/skip`)
    await loadEpisodes(selectedFeed)
    if (selectedEpisode?.id === id) await loadEpisodeDetail(id)
  }

  const processNow = async (id: string) => {
    if (processing.has(id)) return
    setProcessing(prev => new Set(prev).add(id))
    try {
      await api.post<{ message: string; status: string }>(`/podcasts/episodes/${id}/process`)
    } catch { /* ignore — status tracked via polling */ }
    pollEpisodeStatus(id)
  }

  const pollEpisodeStatus = useCallback((id: string) => {
    const poll = async () => {
      try {
        const ep = await api.get<PodcastEpisode>(`/podcasts/episodes/${id}`)
        if (['pending', 'downloading', 'chunking', 'transcribing', 'summarizing_chunks', 'reducing'].includes(ep.processing_status)) {
          setTimeout(poll, 5000)
          return
        }
        // Done or error — stop polling
        setProcessing(prev => { const next = new Set(prev); next.delete(id); return next })
        await loadEpisodes(selectedFeedRef.current)
        await loadQueue()
      } catch {
        setProcessing(prev => { const next = new Set(prev); next.delete(id); return next })
      }
    }
    setTimeout(poll, 3000)
  }, [])

  const resummarize = async (id: string) => {
    await api.post(`/podcasts/episodes/${id}/resummarize`)
    await loadEpisodes(selectedFeed)
    if (selectedEpisode?.id === id) await loadEpisodeDetail(id)
  }

  // Prompt actions
  const savePrompt = async (data: { name: string; description?: string; system_prompt: string; is_default?: boolean }, id?: string) => {
    if (id) {
      await api.put(`/podcasts/prompts/${id}`, data)
    } else {
      await api.post('/podcasts/prompts', data)
    }
    await loadPrompts()
    setShowAddPrompt(false)
    setEditingPrompt(null)
  }

  const deletePrompt = async (id: string) => {
    if (!confirm('Prompt loeschen?')) return
    await api.delete(`/podcasts/prompts/${id}`)
    await loadPrompts()
  }

  // Policy actions
  const savePolicy = async (data: Record<string, unknown>, id?: string) => {
    if (id) {
      await api.put(`/podcasts/mail-policies/${id}`, data)
    } else {
      await api.post('/podcasts/mail-policies', data)
    }
    await loadPolicies()
    setShowAddPolicy(false)
    setEditingPolicy(null)
  }

  const deletePolicy = async (id: string) => {
    if (!confirm('Mail-Policy loeschen?')) return
    await api.delete(`/podcasts/mail-policies/${id}`)
    await loadPolicies()
  }

  const runPolicy = async (id: string, hours: number = 24) => {
    await api.post(`/podcasts/mail-policies/${id}/run?since_hours=${hours}`)
    await loadQueue()
  }

  if (loading) return <PageSpinner />

  const tabs: { key: Tab; label: string }[] = [
    { key: 'episodes', label: 'Episoden' },
    { key: 'prompts', label: 'Prompts' },
    { key: 'policies', label: 'Mail-Policies' },
    { key: 'queue', label: 'Queue' },
    { key: 'settings', label: 'Einstellungen' },
  ]

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Headphones className="w-5 h-5 text-primary" /> Podcasts
        </h1>
        <div className="flex items-center gap-2">
          {queue && (queue.pending_downloads > 0 || queue.errors > 0) && (
            <div className="flex items-center gap-2 text-xs">
              {queue.pending_downloads > 0 && (
                <span className="text-yellow-400">{queue.pending_downloads} pending</span>
              )}
              {queue.errors > 0 && (
                <span className="text-red-400">{queue.errors} errors</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
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

      {/* Tab Content */}
      {tab === 'episodes' && (
        <div className="flex gap-4" style={{ height: 'calc(100vh - 11rem)' }}>
          {/* Feed Sidebar */}
          <div className={`${mobileShowDetail ? 'hidden md:block' : ''} flex-shrink-0 flex flex-col transition-all duration-200 ${feedSidebarOpen ? 'w-full md:w-64' : 'w-8'}`} style={{ height: 'calc(100vh - 11rem)' }}>
            {feedSidebarOpen ? (
            <div className="flex items-center justify-between mb-2 flex-shrink-0">
              <span className="text-sm font-medium text-muted-foreground">Feeds</span>
              <div className="flex items-center gap-0.5">
                <button onClick={() => setShowAddFeed(true)} className="p-1 rounded hover:bg-secondary text-muted-foreground hover:text-foreground">
                  <Plus className="w-4 h-4" />
                </button>
                <button onClick={() => setFeedSidebarOpen(false)} className="p-1 rounded hover:bg-secondary text-muted-foreground hover:text-foreground" title="Feeds ausblenden">
                  <PanelLeftClose className="w-4 h-4" />
                </button>
              </div>
            </div>
            ) : (
            <button onClick={() => setFeedSidebarOpen(true)} className="p-1 rounded hover:bg-secondary text-muted-foreground hover:text-foreground mb-2" title="Feeds einblenden">
              <PanelLeft className="w-4 h-4" />
            </button>
            )}

            {feedSidebarOpen && <div className="flex-1 overflow-y-auto overscroll-contain space-y-2 min-h-0">
            {showAddFeed && (
              <div className="p-2 bg-card rounded-lg border border-border space-y-2">
                <input
                  value={newFeedUrl}
                  onChange={e => setNewFeedUrl(e.target.value)}
                  placeholder="Podcast RSS URL..."
                  className="w-full px-2 py-1.5 text-sm bg-secondary rounded border border-border"
                  onKeyDown={e => e.key === 'Enter' && addFeed()}
                />
                <div className="flex gap-1">
                  <button onClick={addFeed} className="px-2 py-1 text-xs bg-primary text-primary-foreground rounded">Hinzufuegen</button>
                  <button onClick={() => { setShowAddFeed(false); setNewFeedUrl('') }} className="px-2 py-1 text-xs text-muted-foreground">Abbrechen</button>
                </div>
              </div>
            )}

            {/* All episodes */}
            <button
              onClick={() => { setSelectedFeed(null); setSelectedEpisode(null); setMobileShowDetail(false) }}
              className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                !selectedFeed ? 'bg-primary/15 text-primary font-medium' : 'text-foreground/70 hover:bg-secondary'
              }`}
            >
              Alle Episoden
            </button>

            {feeds.map(feed => (
              <div
                key={feed.id}
                className={`group px-3 py-2 rounded-md text-sm cursor-pointer transition-colors ${
                  selectedFeed === feed.id ? 'bg-primary/15 text-primary' : 'text-foreground/70 hover:bg-secondary'
                } ${!feed.enabled ? 'opacity-50' : ''}`}
                onClick={() => { setSelectedFeed(feed.id); setSelectedEpisode(null); setMobileShowDetail(false) }}
              >
                <div className="flex items-center gap-2 min-w-0">
                  {/* Toggle switch */}
                  <button
                    onClick={e => { e.stopPropagation(); updateFeed(feed.id, { enabled: !feed.enabled }) }}
                    className={`relative flex-shrink-0 w-7 h-4 rounded-full transition-colors ${feed.enabled ? 'bg-primary' : 'bg-secondary'}`}
                    title={feed.enabled ? 'Deaktivieren' : 'Aktivieren'}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white transition-transform ${feed.enabled ? 'translate-x-3' : ''}`} />
                  </button>
                  <span className="truncate font-medium flex-1 min-w-0">{feed.title || feed.url}</span>
                  <div className="hidden group-hover:flex items-center gap-0.5 flex-shrink-0">
                    <button onClick={e => { e.stopPropagation(); syncFeed(feed.id) }} className="p-0.5 rounded hover:bg-secondary" title="Sync">
                      <RefreshCw className={`w-3 h-3 ${syncing === feed.id ? 'animate-spin' : ''}`} />
                    </button>
                    <button onClick={e => { e.stopPropagation(); setEditingFeed(feed) }} className="p-0.5 rounded hover:bg-secondary" title="Settings">
                      <Settings2 className="w-3 h-3" />
                    </button>
                    <button onClick={e => { e.stopPropagation(); deleteFeed(feed.id) }} className="p-0.5 rounded hover:bg-secondary text-red-400" title="Loeschen">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
                {feed.last_error && (
                  <div className="text-xs text-red-400 mt-0.5 truncate">{feed.last_error}</div>
                )}
              </div>
            ))}

            {feeds.length === 0 && !showAddFeed && (
              <div className="text-sm text-muted-foreground text-center py-4">
                Keine Feeds. Fuege einen hinzu.
              </div>
            )}
            </div>}
          </div>

          {/* Episode List + Detail */}
          <div className="flex-1 min-w-0 flex gap-4" style={{ height: 'calc(100vh - 11rem)' }}>
            {/* Episode List */}
            <div className={`${mobileShowDetail ? 'hidden md:block' : ''} ${selectedEpisode ? 'md:w-1/2 lg:w-2/5' : 'w-full'} min-w-0 flex flex-col`} style={{ height: 'calc(100vh - 11rem)' }}>
              {/* Filter — fixed */}
              <div className="flex gap-1 pb-2 overflow-x-auto flex-shrink-0">
                {(['all', 'saved', 'done', 'skipped', 'error'] as const).map(f => (
                  <button
                    key={f}
                    onClick={() => setEpisodeFilter(f)}
                    className={`px-2 py-1 text-xs rounded whitespace-nowrap ${
                      episodeFilter === f ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:bg-secondary'
                    }`}
                  >
                    {{ all: 'Alle', saved: 'Gemerkt', done: 'Fertig', skipped: 'Uebersprungen', error: 'Fehler' }[f]}
                  </button>
                ))}
              </div>

              {/* Search */}
              <div className="flex-shrink-0 pb-2">
                <div className="flex items-center gap-1">
                  <div className="flex-1 relative">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                    <input
                      value={searchQuery}
                      onChange={e => handleSearchChange(e.target.value)}
                      placeholder="Suchen..."
                      className="w-full pl-7 pr-7 py-1.5 text-sm bg-secondary rounded border border-border"
                    />
                    {searchQuery && (
                      <button onClick={() => { setSearchQuery(''); loadEpisodes(selectedFeedRef.current, '') }} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  <button
                    onClick={() => setShowSearchSettings(!showSearchSettings)}
                    className={`p-1.5 rounded border border-border transition-colors ${showSearchSettings ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:text-foreground bg-secondary'}`}
                    title="Suchfelder"
                  >
                    <Settings2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                {showSearchSettings && (
                  <div className="flex flex-wrap gap-2 mt-1.5">
                    {([['title', 'Titel'], ['description', 'Beschreibung'], ['summary', 'Summary'], ['transcript', 'Transkript']] as const).map(([key, label]) => (
                      <button
                        key={key}
                        onClick={() => toggleSearchField(key)}
                        className={`px-2 py-0.5 text-xs rounded transition-colors ${
                          searchFields.has(key) ? 'bg-primary/20 text-primary' : 'bg-secondary text-muted-foreground'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Scrollable episode list */}
              <div className="overflow-y-auto overscroll-contain space-y-2" style={{ maxHeight: 'calc(100vh - 16rem)' }}>
              {episodes.length === 0 ? (
                <EmptyState icon={Headphones} title="Keine Episoden" description="Keine Episoden gefunden" />
              ) : (
                episodes.map(ep => (
                  <div
                    key={ep.id}
                    onClick={() => loadEpisodeDetail(ep.id)}
                    className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedEpisode?.id === ep.id ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/30 bg-card'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2 min-w-0">
                      <div className="min-w-0 flex-1">
                        <div className={`text-sm font-medium truncate ${ep.discovery_status === 'skipped' ? 'text-muted-foreground' : ''}`}>{ep.title || 'Ohne Titel'}</div>
                        <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                          {ep.published_at && <span>{formatDate(ep.published_at)}</span>}
                          {ep.duration_seconds && <span>{formatDuration(ep.duration_seconds)}</span>}
                          {ep.discovery_status === 'accepted' && ep.processing_status !== 'done' && (
                            <span className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 font-medium">in Queue</span>
                          )}
                          {ep.discovery_status === 'skipped' && (
                            <span className="px-1.5 py-0.5 rounded bg-gray-500/20 text-gray-400">uebersprungen</span>
                          )}
                          {ep.processing_status === 'done' && (
                            <StatusBadge status="done" />
                          )}
                          {ep.processing_status === 'error' && (
                            <StatusBadge status="error" />
                          )}
                          {!['pending', 'done', 'error', 'skipped', 'new'].includes(ep.processing_status) && (
                            <StatusBadge status={ep.processing_status} />
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        {ep.processing_status !== 'done' && (
                          <button
                            onClick={e => { e.stopPropagation(); processNow(ep.id) }}
                            disabled={processing.has(ep.id)}
                            className="px-1.5 py-0.5 text-xs rounded bg-green-500/20 text-green-400 hover:bg-green-500/30 disabled:opacity-50"
                            title={processing.has(ep.id) ? 'Wird verarbeitet...' : 'Jetzt verarbeiten'}
                          >
                            {processing.has(ep.id) ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                          </button>
                        )}
                        {ep.is_saved && <Star className="w-3.5 h-3.5 text-yellow-400 fill-yellow-400" />}
                        <ChevronRight className="w-4 h-4 text-muted-foreground" />
                      </div>
                    </div>
                  </div>
                ))
              )}
              </div>
            </div>

            {/* Episode Detail */}
            {selectedEpisode && (
              <div ref={detailRef} className={`${mobileShowDetail ? '' : 'hidden md:block'} md:flex-1 min-w-0 bg-card rounded-lg border border-border p-4 overflow-y-auto overscroll-contain`} style={{ maxHeight: 'calc(100vh - 11rem)' }}>
                {/* Mobile back */}
                <button
                  onClick={() => { setMobileShowDetail(false); setSelectedEpisode(null) }}
                  className="md:hidden text-sm text-primary mb-3 flex items-center gap-1"
                >
                  &larr; Zurueck
                </button>

                <div className="space-y-4">
                  {/* Title + Meta */}
                  <div>
                    <h2 className="text-lg font-semibold">{selectedEpisode.title || 'Ohne Titel'}</h2>
                    {selectedEpisode.feed_title && (
                      <div className="text-sm text-primary mt-0.5">{selectedEpisode.feed_title}</div>
                    )}
                    <div className="flex flex-wrap items-center gap-2 mt-2 text-xs text-muted-foreground">
                      {selectedEpisode.published_at && <span>{formatDateTime(selectedEpisode.published_at)}</span>}
                      {selectedEpisode.duration_seconds && <span>{formatDuration(selectedEpisode.duration_seconds)}</span>}
                      {selectedEpisode.episode_number && <span>Ep. {selectedEpisode.episode_number}</span>}
                      {selectedEpisode.chunk_count && <span>{selectedEpisode.chunk_count} Chunks</span>}
                      <StatusBadge status={selectedEpisode.processing_status} />
                      <StatusBadge status={selectedEpisode.discovery_status} />
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => toggleSaved(selectedEpisode)}
                      className={`px-2 py-1 text-xs rounded flex items-center gap-1 ${
                        selectedEpisode.is_saved ? 'bg-yellow-500/20 text-yellow-400' : 'bg-secondary text-muted-foreground'
                      }`}
                    >
                      {selectedEpisode.is_saved ? <Star className="w-3 h-3 fill-current" /> : <StarOff className="w-3 h-3" />}
                      {selectedEpisode.is_saved ? 'Gemerkt' : 'Merken'}
                    </button>

                    {/* Jetzt verarbeiten — fuer skipped, pending, error */}
                    {selectedEpisode.processing_status !== 'done' && (
                      <button
                        onClick={() => processNow(selectedEpisode.id)}
                        disabled={processing.has(selectedEpisode.id)}
                        className="px-2 py-1 text-xs rounded bg-green-500/20 text-green-400 hover:bg-green-500/30 flex items-center gap-1 disabled:opacity-50"
                      >
                        {processing.has(selectedEpisode.id) ? (
                          <><RefreshCw className="w-3 h-3 animate-spin" /> Verarbeite...</>
                        ) : (
                          <><Play className="w-3 h-3" /> Jetzt verarbeiten</>
                        )}
                      </button>
                    )}

                    {/* Zuruecknehmen — accepted/pending Episode wieder auf skipped */}
                    {selectedEpisode.discovery_status === 'accepted' && selectedEpisode.processing_status !== 'done' && (
                      <button onClick={() => skipEpisode(selectedEpisode.id)} className="px-2 py-1 text-xs rounded bg-secondary text-muted-foreground flex items-center gap-1">
                        <EyeOff className="w-3 h-3" /> Ueberspringen
                      </button>
                    )}

                    {selectedEpisode.processing_status === 'done' && (
                      <button onClick={() => resummarize(selectedEpisode.id)} className="px-2 py-1 text-xs rounded bg-purple-500/20 text-purple-400 flex items-center gap-1">
                        <RefreshCw className="w-3 h-3" /> Re-Summarize
                      </button>
                    )}
                    {selectedEpisode.link && (
                      <a href={selectedEpisode.link} target="_blank" rel="noopener noreferrer" className="px-2 py-1 text-xs rounded bg-secondary text-muted-foreground flex items-center gap-1">
                        Zur Episode &rarr;
                      </a>
                    )}
                  </div>

                  {/* Processing indicator */}
                  {processing.has(selectedEpisode.id) && (
                    <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg text-sm text-blue-300">
                      Verarbeitung laeuft im Hintergrund... Du kannst weiter navigieren.
                    </div>
                  )}

                  {/* Error */}
                  {selectedEpisode.error_message && (
                    <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-sm">
                      <div className="font-medium text-red-400 flex items-center gap-1">
                        <AlertTriangle className="w-4 h-4" />
                        {selectedEpisode.error_class || 'Error'}
                      </div>
                      <div className="text-red-300 mt-1 text-xs break-all">{selectedEpisode.error_message}</div>
                    </div>
                  )}

                  {/* Summary (active artifact) */}
                  {selectedEpisode.artifacts.filter(a => a.artifact_type === 'summary' && a.is_active).map(art => (
                    <div key={art.id} className="space-y-1">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-medium flex items-center gap-1"><MessageSquare className="w-4 h-4 text-primary" /> Zusammenfassung</h3>
                        <span className="text-xs text-muted-foreground">{art.word_count} Woerter &middot; {art.model}</span>
                      </div>
                      <div className="p-3 bg-secondary/50 rounded-lg text-sm leading-relaxed prose prose-invert prose-sm max-w-none [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_li]:my-0.5 [&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm [&_a]:text-primary">
                        <Markdown>{art.content || ''}</Markdown>
                      </div>
                    </div>
                  ))}

                  {/* Transcript (active artifact) */}
                  {selectedEpisode.artifacts.filter(a => a.artifact_type === 'transcript' && a.is_active).map(art => (
                    <details key={art.id} className="group">
                      <summary className="text-sm font-medium flex items-center gap-1 cursor-pointer">
                        <FileText className="w-4 h-4 text-muted-foreground" /> Transkript
                        <span className="text-xs text-muted-foreground ml-2">{art.word_count} Woerter</span>
                      </summary>
                      <div className="mt-2 p-3 bg-secondary/30 rounded-lg text-xs whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto">{art.content}</div>
                    </details>
                  ))}

                  {/* Chunks */}
                  {selectedEpisode.chunks.length > 0 && (
                    <details>
                      <summary className="text-sm font-medium cursor-pointer">Chunks ({selectedEpisode.chunks.length})</summary>
                      <div className="mt-2 space-y-1">
                        {selectedEpisode.chunks.map(chunk => (
                          <div key={chunk.id} className="flex items-center gap-2 text-xs p-1.5 bg-secondary/30 rounded">
                            <span className="text-muted-foreground w-6">#{chunk.chunk_index}</span>
                            <span className="text-muted-foreground">{Math.floor(chunk.start_seconds/60)}-{Math.floor(chunk.end_seconds/60)}m</span>
                            <StatusBadge status={chunk.status} />
                            {chunk.error_message && <span className="text-red-400 truncate flex-1">{chunk.error_message}</span>}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}

                  {/* Old artifacts */}
                  {selectedEpisode.artifacts.filter(a => !a.is_active).length > 0 && (
                    <details>
                      <summary className="text-sm font-medium cursor-pointer text-muted-foreground">
                        Fruehere Versionen ({selectedEpisode.artifacts.filter(a => !a.is_active).length})
                      </summary>
                      <div className="mt-2 space-y-2">
                        {selectedEpisode.artifacts.filter(a => !a.is_active).map(art => (
                          <div key={art.id} className="p-2 bg-secondary/20 rounded text-xs">
                            <div className="text-muted-foreground">{art.artifact_type} &middot; v{art.prompt_version} &middot; {art.model} &middot; {formatDateTime(art.created_at)}</div>
                            <div className="mt-1 max-h-24 overflow-hidden text-muted-foreground/70">{art.content?.slice(0, 300)}...</div>
                          </div>
                        ))}
                      </div>
                    </details>
                  )}

                  {/* Description */}
                  {selectedEpisode.description && (
                    <details>
                      <summary className="text-sm font-medium cursor-pointer text-muted-foreground">Beschreibung</summary>
                      <div className="mt-2 text-sm text-muted-foreground prose prose-invert prose-sm max-w-none [&_p]:my-1 [&_a]:text-primary" dangerouslySetInnerHTML={{ __html: selectedEpisode.description }} />
                    </details>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {tab === 'prompts' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium">Zusammenfassungs-Prompts</h2>
            <button onClick={() => setShowAddPrompt(true)} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md flex items-center gap-1">
              <Plus className="w-4 h-4" /> Neuer Prompt
            </button>
          </div>

          {(showAddPrompt || editingPrompt) && (
            <PromptForm
              prompt={editingPrompt}
              onSave={(data) => savePrompt(data, editingPrompt?.id)}
              onCancel={() => { setShowAddPrompt(false); setEditingPrompt(null) }}
            />
          )}

          {prompts.map(p => (
            <div key={p.id} className="p-4 bg-card rounded-lg border border-border">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-sm">{p.name}</span>
                  <span className={`ml-2 px-1.5 py-0.5 text-xs rounded ${p.prompt_type === 'map_summary' ? 'bg-blue-500/20 text-blue-400' : 'bg-purple-500/20 text-purple-400'}`}>
                    {p.prompt_type === 'map_summary' ? 'Chunk' : 'Gesamt'}
                  </span>
                  {p.is_default && <span className="ml-1 px-1.5 py-0.5 text-xs bg-primary/20 text-primary rounded">Default</span>}
                  <span className="ml-2 text-xs text-muted-foreground">v{p.version}</span>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => setEditingPrompt(p)} className="p-1 rounded hover:bg-secondary text-muted-foreground">
                    <Settings2 className="w-4 h-4" />
                  </button>
                  <button onClick={() => deletePrompt(p.id)} className="p-1 rounded hover:bg-secondary text-red-400">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
              {p.description && <div className="text-xs text-muted-foreground mt-1">{p.description}</div>}
              <pre className="mt-2 text-xs text-muted-foreground bg-secondary/30 p-2 rounded max-h-32 overflow-y-auto whitespace-pre-wrap">{p.system_prompt}</pre>
            </div>
          ))}

          {prompts.length === 0 && !showAddPrompt && (
            <EmptyState icon={FileText} title="Keine Prompts" description="Der System-Default wird verwendet." />
          )}
        </div>
      )}

      {tab === 'policies' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium">Mail-Policies</h2>
            <button onClick={() => setShowAddPolicy(true)} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md flex items-center gap-1">
              <Plus className="w-4 h-4" /> Neue Policy
            </button>
          </div>

          {(showAddPolicy || editingPolicy) && (
            <PolicyForm
              policy={editingPolicy}
              feeds={feeds}
              prompts={prompts}
              onSave={(data) => savePolicy(data, editingPolicy?.id)}
              onCancel={() => { setShowAddPolicy(false); setEditingPolicy(null) }}
            />
          )}

          {policies.map(p => (
            <div key={p.id} className="p-4 bg-card rounded-lg border border-border">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-medium text-sm">{p.name}</span>
                  <span className={`ml-2 px-1.5 py-0.5 text-xs rounded ${p.enabled ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'}`}>
                    {p.enabled ? 'Aktiv' : 'Inaktiv'}
                  </span>
                </div>
                <div className="flex gap-1">
                  <button onClick={() => runPolicy(p.id)} className="p-1 rounded hover:bg-secondary text-primary" title="Jetzt ausfuehren">
                    <Play className="w-4 h-4" />
                  </button>
                  <button onClick={() => setEditingPolicy(p)} className="p-1 rounded hover:bg-secondary text-muted-foreground">
                    <Settings2 className="w-4 h-4" />
                  </button>
                  <button onClick={() => deletePolicy(p.id)} className="p-1 rounded hover:bg-secondary text-red-400">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
              <div className="flex flex-wrap gap-3 mt-2 text-xs text-muted-foreground">
                <span>Cron: {p.schedule_cron}</span>
                <span>An: {p.target_email}</span>
                {p.feed_filter && <span>Feeds: {p.feed_filter.length}</span>}
              </div>
            </div>
          ))}

          {policies.length === 0 && !showAddPolicy && (
            <EmptyState icon={Send} title="Keine Policies" description="Keine Mail-Policies angelegt." />
          )}
        </div>
      )}

      {tab === 'queue' && queue && (
        <div className="space-y-4">
          {/* Queue Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: 'Pending', value: queue.pending_downloads, color: 'text-yellow-400' },
              { label: 'Aktiv', value: queue.active_downloads + queue.active_transcriptions + queue.active_summaries, color: 'text-blue-400' },
              { label: 'Fehler', value: queue.errors, color: 'text-red-400' },
              { label: 'Heute fertig', value: queue.done_today, color: 'text-green-400' },
            ].map(s => (
              <div key={s.label} className="p-3 bg-card rounded-lg border border-border text-center">
                <div className={`text-2xl font-bold ${s.color}`}>{s.value}</div>
                <div className="text-xs text-muted-foreground mt-1">{s.label}</div>
              </div>
            ))}
          </div>

          {/* Processing Runs */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium">Letzte Verarbeitungen</h3>
              <button onClick={loadQueue} className="p-1 rounded hover:bg-secondary text-muted-foreground">
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-1">
              {processingRuns.map(run => (
                <div key={run.id} className="flex items-center gap-2 text-xs p-2 bg-card rounded border border-border">
                  <StatusBadge status={run.status} />
                  <span className="font-medium">{run.stage}</span>
                  {run.model && <span className="text-muted-foreground truncate">{run.model.split('/').pop()}</span>}
                  {run.tokens_used && <span className="text-muted-foreground">{run.tokens_used} tok</span>}
                  {run.duration_ms && <span className="text-muted-foreground">{(run.duration_ms/1000).toFixed(1)}s</span>}
                  {run.error_message && <span className="text-red-400 truncate flex-1">{run.error_message}</span>}
                  <span className="text-muted-foreground ml-auto flex-shrink-0">{formatDateTime(run.started_at)}</span>
                </div>
              ))}
              {processingRuns.length === 0 && (
                <div className="text-sm text-muted-foreground text-center py-4">Keine Verarbeitungen bisher.</div>
              )}
            </div>
          </div>
        </div>
      )}

      {tab === 'settings' && (
        <PodcastGlobalSettings
          settings={globalSettings}
          models={globalModels}
          appDefault={globalAppDefault}
          onSave={async (data) => {
            await api.put('/settings/podcasts', data)
            await loadGlobalSettings()
          }}
          onResetFeeds={async () => {
            if (!confirm('Alle individuellen Feed-Modell-Einstellungen zuruecksetzen?')) return
            await api.post<{ message: string }>('/settings/podcasts/reset-feeds')
            await loadFeeds()
          }}
        />
      )}

      {/* Feed Settings Modal */}
      {editingFeed && (
        <FeedSettingsModal
          feed={editingFeed}
          prompts={prompts}
          onSave={(data) => updateFeed(editingFeed.id, data)}
          onClose={() => setEditingFeed(null)}
        />
      )}
    </div>
  )
}

// -- Subcomponents --

function PromptForm({ prompt, onSave, onCancel }: {
  prompt: PodcastPrompt | null
  onSave: (data: { name: string; description?: string; system_prompt: string; prompt_type: string; is_default?: boolean }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(prompt?.name || '')
  const [desc, setDesc] = useState(prompt?.description || '')
  const [text, setText] = useState(prompt?.system_prompt || '')
  const [promptType, setPromptType] = useState(prompt?.prompt_type || 'map_summary')
  const [isDefault, setIsDefault] = useState(prompt?.is_default || false)

  return (
    <div className="p-4 bg-card rounded-lg border border-border space-y-3">
      <input value={name} onChange={e => setName(e.target.value)} placeholder="Prompt-Name" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
      <input value={desc} onChange={e => setDesc(e.target.value)} placeholder="Beschreibung (optional)" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
      <select value={promptType} onChange={e => setPromptType(e.target.value)} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border">
        <option value="map_summary">Chunk-Summary (Map-Phase)</option>
        <option value="reduce_summary">Gesamt-Summary (Reduce-Phase)</option>
      </select>
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder="System-Prompt..." rows={8} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border font-mono" />
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={isDefault} onChange={e => setIsDefault(e.target.checked)} className="rounded" />
          Default-Prompt
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

function PolicyForm({ policy, feeds, prompts, onSave, onCancel }: {
  policy: PodcastMailPolicy | null
  feeds: PodcastFeed[]
  prompts: PodcastPrompt[]
  onSave: (data: Record<string, unknown>) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(policy?.name || '')
  const [cron, setCron] = useState(policy?.schedule_cron || '0 8 * * 1')
  const [email, setEmail] = useState(policy?.target_email || '')
  const [promptId, setPromptId] = useState(policy?.prompt_id || '')
  const [selectedFeeds, setSelectedFeeds] = useState<string[]>(policy?.feed_filter || [])
  const [enabled, setEnabled] = useState(policy?.enabled ?? true)

  return (
    <div className="p-4 bg-card rounded-lg border border-border space-y-3">
      <input value={name} onChange={e => setName(e.target.value)} placeholder="Policy-Name" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <input value={cron} onChange={e => setCron(e.target.value)} placeholder="Cron (z.B. 0 8 * * 1)" className="px-3 py-2 text-sm bg-secondary rounded border border-border" />
        <input value={email} onChange={e => setEmail(e.target.value)} placeholder="Ziel-Email" className="px-3 py-2 text-sm bg-secondary rounded border border-border" />
      </div>
      <select value={promptId} onChange={e => setPromptId(e.target.value)} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border">
        <option value="">Standard-Prompt</option>
        {prompts.map(p => <option key={p.id} value={p.id}>{p.name} (v{p.version})</option>)}
      </select>
      <div className="space-y-1">
        <span className="text-xs text-muted-foreground">Feeds filtern (leer = alle):</span>
        {feeds.map(f => (
          <label key={f.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selectedFeeds.includes(f.id)}
              onChange={e => setSelectedFeeds(e.target.checked ? [...selectedFeeds, f.id] : selectedFeeds.filter(x => x !== f.id))}
              className="rounded"
            />
            {f.title || f.url}
          </label>
        ))}
      </div>
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} className="rounded" />
          Aktiviert
        </label>
        <div className="flex-1" />
        <button onClick={onCancel} className="px-3 py-1.5 text-sm text-muted-foreground">Abbrechen</button>
        <button
          onClick={() => onSave({ name, schedule_cron: cron, target_email: email, prompt_id: promptId || null, feed_filter: selectedFeeds.length > 0 ? selectedFeeds : null, enabled })}
          className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md"
          disabled={!name || !cron || !email}
        >
          Speichern
        </button>
      </div>
    </div>
  )
}

function PodcastGlobalSettings({ settings, models, appDefault, onSave, onResetFeeds }: {
  settings: { transcription_model: string; summary_model: string }
  models: { id: string }[]
  appDefault: string
  onSave: (data: { transcription_model: string; summary_model: string }) => Promise<void>
  onResetFeeds: () => Promise<void>
}) {
  const [form, setForm] = useState(settings)
  const [saved, setSaved] = useState(false)

  useEffect(() => { setForm(settings) }, [settings])

  const handleSave = async () => {
    await onSave(form)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="space-y-6 max-w-lg">
      <div>
        <h2 className="text-sm font-medium mb-4">Globale AI-Modelle</h2>
        <p className="text-xs text-muted-foreground mb-4">
          Diese Modelle gelten fuer alle Feeds ohne individuelle Einstellung. Feeds mit eigener Modell-Konfiguration verwenden ihre eigene.
        </p>
        <div className="space-y-4">
          <ModelPicker
            label="Transkriptions-Modell"
            value={form.transcription_model}
            onChange={v => setForm({...form, transcription_model: v})}
            models={models}
            appDefault={appDefault}
          />
          <ModelPicker
            label="Summary-Modell"
            value={form.summary_model}
            onChange={v => setForm({...form, summary_model: v})}
            models={models}
            appDefault={appDefault}
          />
        </div>
        <div className="flex items-center gap-3 mt-4">
          <button onClick={handleSave} className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-md">
            {saved ? 'Gespeichert' : 'Speichern'}
          </button>
        </div>
      </div>

      <div className="border-t border-border pt-4">
        <h2 className="text-sm font-medium mb-2">Feeds zuruecksetzen</h2>
        <p className="text-xs text-muted-foreground mb-3">
          Entfernt individuelle Modell-Einstellungen von allen Feeds. Danach verwenden alle Feeds die globalen Einstellungen.
        </p>
        <button onClick={onResetFeeds} className="px-4 py-2 text-sm bg-secondary text-foreground rounded-md border border-border hover:bg-secondary/80">
          Alle Feed-Modelle zuruecksetzen
        </button>
      </div>
    </div>
  )
}

function ModelPicker({ label, value, onChange, models, appDefault }: {
  label: string
  value: string
  onChange: (v: string) => void
  models: { id: string }[]
  appDefault: string
}) {
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const filtered = models.filter(m => !search || m.id.toLowerCase().includes(search.toLowerCase())).slice(0, 40)
  const displayValue = value || `App-Default (${appDefault})`

  return (
    <div>
      <label className="text-xs text-muted-foreground">{label}</label>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border text-left truncate flex items-center justify-between"
      >
        <span className={`truncate ${!value ? 'text-muted-foreground' : ''}`}>{displayValue}</span>
        <ChevronRight className={`w-3 h-3 flex-shrink-0 transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && (
        <div className="mt-1 border border-border rounded-md bg-card">
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Modell suchen..."
            className="w-full px-3 py-1.5 text-xs bg-secondary border-b border-border rounded-t-md"
            autoFocus
          />
          <div className="max-h-48 overflow-y-auto">
            <button
              onClick={() => { onChange(''); setOpen(false); setSearch('') }}
              className={`w-full text-left px-3 py-1.5 text-xs border-b border-border/30 transition-colors ${
                !value ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:bg-secondary/50'
              }`}
            >
              App-Default ({appDefault})
            </button>
            {filtered.map(m => (
              <button
                key={m.id}
                onClick={() => { onChange(m.id); setOpen(false); setSearch('') }}
                className={`w-full text-left px-3 py-1.5 text-xs border-b border-border/30 transition-colors ${
                  m.id === value ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:bg-secondary/50'
                }`}
              >
                {m.id}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function FeedSettingsModal({ feed, prompts, onSave, onClose }: {
  feed: PodcastFeed
  prompts: PodcastPrompt[]
  onSave: (data: Record<string, unknown>) => void
  onClose: () => void
}) {
  const [form, setForm] = useState({
    title: feed.title || '',
    enabled: feed.enabled,
    auto_process_new: feed.auto_process_new,
    map_prompt_id: feed.map_prompt_id || '',
    reduce_prompt_id: feed.reduce_prompt_id || '',
    transcription_model: feed.transcription_model || '',
    summary_model: feed.summary_model || '',
    fetch_interval_minutes: feed.fetch_interval_minutes,
    max_episode_duration_seconds: feed.max_episode_duration_seconds || '',
    min_episode_duration_seconds: feed.min_episode_duration_seconds || '',
    max_audio_size_mb: feed.max_audio_size_mb || '',
    keep_audio_days: feed.keep_audio_days ?? '',
    language: feed.language || '',
    ignore_title_patterns: (feed.ignore_title_patterns || []).join('\n'),
  })
  const [availableModels, setAvailableModels] = useState<{ id: string }[]>([])
  const [appDefaultModel, setAppDefaultModel] = useState('')

  useEffect(() => {
    Promise.all([
      api.get<{ id: string }[]>('/llm/models'),
      api.get<{ model: string }>('/llm/active-model'),
    ]).then(([models, active]) => {
      setAvailableModels(models)
      setAppDefaultModel(active.model)
    })
  }, [])

  const handleSave = () => {
    const patterns = form.ignore_title_patterns.split('\n').map(s => s.trim()).filter(Boolean)
    onSave({
      title: form.title || null,
      enabled: form.enabled,
      auto_process_new: form.auto_process_new,
      map_prompt_id: form.map_prompt_id || null,
      reduce_prompt_id: form.reduce_prompt_id || null,
      transcription_model: form.transcription_model || null,
      summary_model: form.summary_model || null,
      fetch_interval_minutes: form.fetch_interval_minutes,
      max_episode_duration_seconds: form.max_episode_duration_seconds ? Number(form.max_episode_duration_seconds) : null,
      min_episode_duration_seconds: form.min_episode_duration_seconds ? Number(form.min_episode_duration_seconds) : null,
      max_audio_size_mb: form.max_audio_size_mb ? Number(form.max_audio_size_mb) : null,
      keep_audio_days: form.keep_audio_days !== '' ? Number(form.keep_audio_days) : null,
      language: form.language || null,
      ignore_title_patterns: patterns.length > 0 ? patterns : null,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="bg-card rounded-lg border border-border p-6 w-full max-w-lg max-h-[80vh] overflow-y-auto space-y-4" onClick={e => e.stopPropagation()}>
        <h3 className="text-lg font-semibold">Feed-Einstellungen</h3>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground">Titel</label>
            <input value={form.title} onChange={e => setForm({...form, title: e.target.value})} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.enabled} onChange={e => setForm({...form, enabled: e.target.checked})} className="rounded" />
              Aktiviert
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.auto_process_new} onChange={e => setForm({...form, auto_process_new: e.target.checked})} className="rounded" />
              Auto-Verarbeitung
            </label>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">Fetch-Intervall (min)</label>
              <input type="number" value={form.fetch_interval_minutes} onChange={e => setForm({...form, fetch_interval_minutes: Number(e.target.value)})} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Sprache</label>
              <input value={form.language} onChange={e => setForm({...form, language: e.target.value})} placeholder="de" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">Min. Dauer (Sek)</label>
              <input type="number" value={form.min_episode_duration_seconds} onChange={e => setForm({...form, min_episode_duration_seconds: e.target.value})} placeholder="180" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Max. Dauer (Sek)</label>
              <input type="number" value={form.max_episode_duration_seconds} onChange={e => setForm({...form, max_episode_duration_seconds: e.target.value})} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">Max. Audio-Groesse (MB)</label>
              <input type="number" value={form.max_audio_size_mb} onChange={e => setForm({...form, max_audio_size_mb: e.target.value})} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Audio behalten (Tage)</label>
              <input type="number" value={form.keep_audio_days} onChange={e => setForm({...form, keep_audio_days: e.target.value})} placeholder="Sofort loeschen" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border" />
            </div>
          </div>

          <div>
            <label className="text-xs text-muted-foreground">Chunk-Summary Prompt (Map-Phase)</label>
            <select value={form.map_prompt_id} onChange={e => setForm({...form, map_prompt_id: e.target.value})} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border">
              <option value="">System-Default</option>
              {prompts.filter(p => p.prompt_type === 'map_summary').map(p => <option key={p.id} value={p.id}>{p.name} (v{p.version})</option>)}
            </select>
          </div>

          <div>
            <label className="text-xs text-muted-foreground">Gesamt-Summary Prompt (Reduce-Phase)</label>
            <select value={form.reduce_prompt_id} onChange={e => setForm({...form, reduce_prompt_id: e.target.value})} className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border">
              <option value="">System-Default</option>
              {prompts.filter(p => p.prompt_type === 'reduce_summary').map(p => <option key={p.id} value={p.id}>{p.name} (v{p.version})</option>)}
            </select>
          </div>

          <ModelPicker
            label="Transkriptions-Modell"
            value={form.transcription_model}
            onChange={v => setForm({...form, transcription_model: v})}
            models={availableModels}
            appDefault={appDefaultModel}
          />

          <ModelPicker
            label="Summary-Modell"
            value={form.summary_model}
            onChange={v => setForm({...form, summary_model: v})}
            models={availableModels}
            appDefault={appDefaultModel}
          />

          <div>
            <label className="text-xs text-muted-foreground">Titel-Muster ignorieren (eins pro Zeile, Regex)</label>
            <textarea value={form.ignore_title_patterns} onChange={e => setForm({...form, ignore_title_patterns: e.target.value})} rows={3} placeholder="trailer\nteaser\nbonus" className="w-full px-3 py-2 text-sm bg-secondary rounded border border-border font-mono" />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-muted-foreground">Abbrechen</button>
          <button onClick={handleSave} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md">Speichern</button>
        </div>
      </div>
    </div>
  )
}
