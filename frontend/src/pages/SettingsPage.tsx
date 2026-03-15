import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageSpinner } from '../components/Spinner'
import {
  Settings, Mail, Plus, TestTube, RefreshCw, Trash2,
  Brain, Zap, Check, X, Forward, Tag, Rss, CloudSun, MessageSquare, HelpCircle, Watch, AlertCircle
} from 'lucide-react'
import { formatDate } from '../lib/utils'

interface MailAccount {
  id: string
  email: string
  display_name: string | null
  imap_host: string
  imap_port: number
  smtp_host: string
  smtp_port: number
  enabled: boolean
  last_sync_at: string | null
  last_error: string | null
  created_at: string
}

interface LlmProvider {
  id: string
  name: string
  provider_type: string
  base_url: string
  default_model: string
  enabled: boolean
  created_at: string
}

interface ForwardingPolicy {
  id: string
  name: string
  description: string | null
  source_category: string | null
  target_email: string
  conditions: Record<string, string> | null
  enabled: boolean
  priority: number
  created_at: string
}

interface ForwardingLogEntry {
  id: string
  message_id: string
  policy_id: string
  target_email: string
  status: string
  error: string | null
  sent_at: string | null
  created_at: string
}

interface LlmPrompt {
  id: string
  task_type: string
  version: number
  system_prompt: string
  user_prompt_template: string
  is_active: boolean
  description: string | null
  created_at: string
}

interface ClassificationRule {
  id: string
  name: string
  description: string | null
  priority: number
  conditions: Record<string, string> | null
  category: string
  enabled: boolean
  created_at: string
}

export default function SettingsPage() {
  const [tab, setTab] = useState<'accounts' | 'rules' | 'categories' | 'forwarding' | 'llm' | 'feeds' | 'weather' | 'assistant' | 'garmin'>('accounts')
  const [accounts, setAccounts] = useState<MailAccount[]>([])
  const [rules, setRules] = useState<ClassificationRule[]>([])
  const [providers, setProviders] = useState<LlmProvider[]>([])
  const [policies, setPolicies] = useState<ForwardingPolicy[]>([])
  const [fwdLogs, setFwdLogs] = useState<ForwardingLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [showAddAccount, setShowAddAccount] = useState(false)
  const [showAddRule, setShowAddRule] = useState(false)
  const [showAddPolicy, setShowAddPolicy] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [syncing, setSyncing] = useState<string | null>(null)
  const [accountForm, setAccountForm] = useState({
    email: '', imap_host: '', imap_port: 993, smtp_host: '', smtp_port: 587,
    username: '', password: '', display_name: '',
  })
  const [ruleForm, setRuleForm] = useState({
    name: '', category: '', priority: 0, description: '',
    from_contains: '', subject_contains: '',
  })
  const [policyForm, setPolicyForm] = useState({
    name: '', target_email: '', source_category: '', description: '',
    priority: 0, from_contains: '', subject_contains: '',
  })
  const [categories, setCategories] = useState<Record<string, string>>({})
  const [newCatKey, setNewCatKey] = useState('')
  const [newCatDesc, setNewCatDesc] = useState('')
  const [thresholds, setThresholds] = useState({ detail_threshold: 50, compact_threshold: 200 })
  const [prompts, setPrompts] = useState<LlmPrompt[]>([])
  const [editingPrompt, setEditingPrompt] = useState<string | null>(null)
  const [promptForm, setPromptForm] = useState({
    task_type: 'classify', system_prompt: '', user_prompt_template: '', description: '',
  })
  const [editingFolders, setEditingFolders] = useState<string | null>(null)
  const [availableFolders, setAvailableFolders] = useState<string[]>([])
  const [syncedFolders, setSyncedFolders] = useState<string[]>([])
  const [loadingFolders, setLoadingFolders] = useState(false)
  const [assistantSettings, setAssistantSettings] = useState({ browse_days: 7, browse_limit: 50, body_max_chars: 3000 })
  const [assistantSaving, setAssistantSaving] = useState(false)
  const [showAssistantHelp, setShowAssistantHelp] = useState(false)
  const [availableModels, setAvailableModels] = useState<{ id: string; name: string }[]>([])
  const [activeModel, setActiveModel] = useState('')
  const [modelSearch, setModelSearch] = useState('')
  const [modelsLoaded, setModelsLoaded] = useState(false)
  const [feeds, setFeeds] = useState<any[]>([])
  const [showAddFeed, setShowAddFeed] = useState(false)
  const [feedForm, setFeedForm] = useState({ url: '', title: '' })
  const [syncingFeed, setSyncingFeed] = useState<string | null>(null)
  const [weatherSources, setWeatherSources] = useState<any[]>([])
  const [showAddWeather, setShowAddWeather] = useState(false)
  const [weatherForm, setWeatherForm] = useState({ name: '', latitude: '', longitude: '' })
  const [geoQuery, setGeoQuery] = useState('')
  const [geoResults, setGeoResults] = useState<any[]>([])
  const [geoSearching, setGeoSearching] = useState(false)
  const [garminAccount, setGarminAccount] = useState<{ email: string; last_sync_at: string | null; last_error: string | null } | null>(null)
  const [garminLoaded, setGarminLoaded] = useState(false)
  const [garminEmail, setGarminEmail] = useState('')
  const [garminPassword, setGarminPassword] = useState('')
  const [garminTesting, setGarminTesting] = useState(false)
  const [garminSaving, setGarminSaving] = useState(false)
  const [garminTestResult, setGarminTestResult] = useState<{ success: boolean; message: string } | null>(null)

  useEffect(() => {
    Promise.all([
      api.get<MailAccount[]>('/mail/accounts'),
      api.get<ClassificationRule[]>('/classification/rules'),
      api.get<LlmProvider[]>('/llm/providers'),
      api.get<ForwardingPolicy[]>('/forwarding/policies'),
      api.get<ForwardingLogEntry[]>('/forwarding/log?limit=50'),
      api.get<Record<string, string>>('/settings/categories'),
      api.get<{ detail_threshold: number; compact_threshold: number }>('/settings/digest-thresholds'),
      api.get<LlmPrompt[]>('/llm/prompts'),
      api.get<any[]>('/feeds/'),
      api.get<any[]>('/weather/sources'),
      api.get<{ browse_days: number; browse_limit: number; body_max_chars: number }>('/settings/assistant'),
    ]).then(([a, r, p, fp, fl, cats, thr, pr, fd, ws, as_]) => {
      setAccounts(a)
      setRules(r)
      setProviders(p)
      setPolicies(fp)
      setFwdLogs(fl)
      setCategories(cats)
      setThresholds(thr)
      setPrompts(pr)
      setFeeds(fd)
      setWeatherSources(ws)
      setAssistantSettings(as_)
    }).finally(() => setLoading(false))
  }, [])

  const handleAddAccount = async (e: React.FormEvent) => {
    e.preventDefault()
    const acc = await api.post<MailAccount>('/mail/accounts', {
      ...accountForm, imap_use_ssl: true, smtp_use_tls: true, enabled: true,
    })
    setAccounts(prev => [...prev, acc])
    setShowAddAccount(false)
    setAccountForm({ email: '', imap_host: '', imap_port: 993, smtp_host: '', smtp_port: 587, username: '', password: '', display_name: '' })
  }

  const handleTest = async (id: string) => {
    setTesting(id)
    try {
      const r = await api.post<{ message: string }>(`/mail/accounts/${id}/test`)
      alert(r.message)
    } catch (e: any) { alert(e.message) }
    finally { setTesting(null) }
  }

  const handleSync = async (id: string) => {
    setSyncing(id)
    try {
      const r = await api.post<{ message: string }>(`/mail/accounts/${id}/sync`)
      alert(r.message)
      const accs = await api.get<MailAccount[]>('/mail/accounts')
      setAccounts(accs)
    } catch (e: any) { alert(e.message) }
    finally { setSyncing(null) }
  }

  const handleDeleteAccount = async (id: string) => {
    if (!confirm('Delete this account?')) return
    await api.delete(`/mail/accounts/${id}`)
    setAccounts(prev => prev.filter(a => a.id !== id))
  }

  const handleAddRule = async (e: React.FormEvent) => {
    e.preventDefault()
    const conditions: Record<string, string> = {}
    if (ruleForm.from_contains) conditions.from_contains = ruleForm.from_contains
    if (ruleForm.subject_contains) conditions.subject_contains = ruleForm.subject_contains
    const rule = await api.post<ClassificationRule>('/classification/rules', {
      name: ruleForm.name,
      category: ruleForm.category,
      priority: ruleForm.priority,
      description: ruleForm.description || null,
      conditions: Object.keys(conditions).length ? conditions : null,
      enabled: true,
    })
    setRules(prev => [...prev, rule])
    setShowAddRule(false)
    setRuleForm({ name: '', category: '', priority: 0, description: '', from_contains: '', subject_contains: '' })
  }

  const handleDeleteRule = async (id: string) => {
    if (!confirm('Delete this rule?')) return
    await api.delete(`/classification/rules/${id}`)
    setRules(prev => prev.filter(r => r.id !== id))
  }

  const handleAddPolicy = async (e: React.FormEvent) => {
    e.preventDefault()
    const conditions: Record<string, string> = {}
    if (policyForm.from_contains) conditions.from_contains = policyForm.from_contains
    if (policyForm.subject_contains) conditions.subject_contains = policyForm.subject_contains
    const policy = await api.post<ForwardingPolicy>('/forwarding/policies', {
      name: policyForm.name,
      target_email: policyForm.target_email,
      source_category: policyForm.source_category || null,
      description: policyForm.description || null,
      conditions: Object.keys(conditions).length ? conditions : null,
      priority: policyForm.priority,
      enabled: true,
    })
    setPolicies(prev => [...prev, policy])
    setShowAddPolicy(false)
    setPolicyForm({ name: '', target_email: '', source_category: '', description: '', priority: 0, from_contains: '', subject_contains: '' })
  }

  const handleDeletePolicy = async (id: string) => {
    if (!confirm('Delete this forwarding policy?')) return
    await api.delete(`/forwarding/policies/${id}`)
    setPolicies(prev => prev.filter(p => p.id !== id))
  }

  const handleTogglePolicy = async (policy: ForwardingPolicy) => {
    const updated = await api.put<ForwardingPolicy>(`/forwarding/policies/${policy.id}`, {
      enabled: !policy.enabled,
    })
    setPolicies(prev => prev.map(p => p.id === policy.id ? updated : p))
  }


  if (loading) return <PageSpinner />

  const tabs = [
    { key: 'accounts' as const, label: 'Mail Accounts', icon: Mail },
    { key: 'rules' as const, label: 'Classification Rules', icon: Zap },
    { key: 'categories' as const, label: 'Categories', icon: Tag },
    { key: 'forwarding' as const, label: 'Forwarding', icon: Forward },
    { key: 'feeds' as const, label: 'RSS Feeds', icon: Rss },
    { key: 'weather' as const, label: 'Weather', icon: CloudSun },
    { key: 'llm' as const, label: 'LLM Providers', icon: Brain },
    { key: 'assistant' as const, label: 'Assistant', icon: MessageSquare },
    { key: 'garmin' as const, label: 'Garmin', icon: Watch },
  ]

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Settings className="w-5 h-5 text-primary" />
        <h1 className="text-xl font-semibold">Settings</h1>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-card rounded-lg p-1 w-fit">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors ${
              tab === t.key ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
          </button>
        ))}
      </div>

      {/* Mail Accounts Tab */}
      {tab === 'accounts' && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-muted-foreground">{accounts.length} account{accounts.length !== 1 ? 's' : ''} configured</p>
            <button
              onClick={() => setShowAddAccount(!showAddAccount)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors"
            >
              {showAddAccount ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
              {showAddAccount ? 'Cancel' : 'Add Account'}
            </button>
          </div>

          {showAddAccount && (
            <form onSubmit={handleAddAccount} className="bg-card rounded-lg border border-border p-4 mb-4">
              <div className="grid grid-cols-2 gap-3">
                <input placeholder="Email" value={accountForm.email} onChange={e => setAccountForm({...accountForm, email: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
                <input placeholder="Display Name" value={accountForm.display_name} onChange={e => setAccountForm({...accountForm, display_name: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                <input placeholder="IMAP Host" value={accountForm.imap_host} onChange={e => setAccountForm({...accountForm, imap_host: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
                <input placeholder="IMAP Port" type="number" value={accountForm.imap_port} onChange={e => setAccountForm({...accountForm, imap_port: Number(e.target.value)})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                <input placeholder="SMTP Host" value={accountForm.smtp_host} onChange={e => setAccountForm({...accountForm, smtp_host: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
                <input placeholder="SMTP Port" type="number" value={accountForm.smtp_port} onChange={e => setAccountForm({...accountForm, smtp_port: Number(e.target.value)})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                <input placeholder="Username" value={accountForm.username} onChange={e => setAccountForm({...accountForm, username: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
                <input placeholder="Password" type="password" value={accountForm.password} onChange={e => setAccountForm({...accountForm, password: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
              </div>
              <button type="submit" className="mt-3 flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm">
                <Check className="w-3.5 h-3.5" /> Save Account
              </button>
            </form>
          )}

          <div className="space-y-2">
            {accounts.map(acc => (
              <div key={acc.id} className="bg-card rounded-lg border border-border p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <Mail className="w-4 h-4 text-primary" />
                      <span className="font-medium text-sm">{acc.email}</span>
                      {acc.display_name && <span className="text-xs text-muted-foreground">({acc.display_name})</span>}
                      <span className={`w-2 h-2 rounded-full ${acc.enabled ? 'bg-emerald-400' : 'bg-gray-500'}`} />
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {acc.imap_host}:{acc.imap_port}
                      {acc.last_sync_at && <> · Last sync: {new Date(acc.last_sync_at).toLocaleString('de-DE')}</>}
                    </div>
                    {acc.last_error && <div className="text-xs text-red-400 mt-1">{acc.last_error}</div>}
                  </div>
                  <div className="flex items-center gap-1">
                    <button onClick={() => handleTest(acc.id)} disabled={testing === acc.id}
                      className="flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50">
                      <TestTube className={`w-3 h-3 ${testing === acc.id ? 'animate-pulse' : ''}`} /> Test
                    </button>
                    <button onClick={() => handleSync(acc.id)} disabled={syncing === acc.id}
                      className="flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50">
                      <RefreshCw className={`w-3 h-3 ${syncing === acc.id ? 'animate-spin' : ''}`} /> Sync
                    </button>
                    <button
                      onClick={async () => {
                        if (editingFolders === acc.id) {
                          setEditingFolders(null)
                        } else {
                          setEditingFolders(acc.id)
                          setLoadingFolders(true)
                          try {
                            const data = await api.get<{ available: string[]; synced: string[] }>(`/mail/accounts/${acc.id}/folders`)
                            setAvailableFolders(data.available)
                            setSyncedFolders(data.synced)
                          } finally {
                            setLoadingFolders(false)
                          }
                        }
                      }}
                      className={`flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-border transition-colors ${
                        editingFolders === acc.id ? 'text-primary bg-primary/10' : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                      }`}
                    >
                      Folders
                    </button>
                    <button onClick={() => handleDeleteAccount(acc.id)}
                      className="p-1 text-muted-foreground hover:text-red-400 transition-colors">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
                {/* Folder Config */}
                {editingFolders === acc.id && (
                  <div className="mt-3 pt-3 border-t border-border">
                    {loadingFolders ? (
                      <p className="text-xs text-muted-foreground">Loading folders...</p>
                    ) : (
                      <div>
                        <p className="text-xs text-muted-foreground mb-2">Select folders to sync:</p>
                        <div className="flex flex-wrap gap-2">
                          {availableFolders.map(f => (
                            <button
                              key={f}
                              onClick={() => {
                                setSyncedFolders(prev =>
                                  prev.includes(f) ? prev.filter(x => x !== f) : [...prev, f]
                                )
                              }}
                              className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
                                syncedFolders.includes(f)
                                  ? 'border-primary bg-primary/15 text-primary'
                                  : 'border-border text-muted-foreground hover:text-foreground hover:bg-secondary'
                              }`}
                            >
                              {f}
                            </button>
                          ))}
                        </div>
                        <button
                          onClick={async () => {
                            await api.put(`/mail/accounts/${acc.id}/folders`, { folders: syncedFolders })
                            setEditingFolders(null)
                          }}
                          className="mt-3 flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-xs"
                        >
                          <Check className="w-3 h-3" /> Save
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Classification Rules Tab */}
      {tab === 'rules' && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-muted-foreground">{rules.length} rule{rules.length !== 1 ? 's' : ''} configured</p>
            <button
              onClick={() => setShowAddRule(!showAddRule)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors"
            >
              {showAddRule ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
              {showAddRule ? 'Cancel' : 'Add Rule'}
            </button>
          </div>

          {showAddRule && (
            <form onSubmit={handleAddRule} className="bg-card rounded-lg border border-border p-4 mb-4">
              <div className="grid grid-cols-2 gap-3">
                <input placeholder="Rule Name" value={ruleForm.name} onChange={e => setRuleForm({...ruleForm, name: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
                <select value={ruleForm.category} onChange={e => setRuleForm({...ruleForm, category: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required>
                  <option value="">Category...</option>
                  {Object.keys(categories).map(c =>
                    <option key={c} value={c}>{c}</option>
                  )}
                </select>
                <input placeholder="From contains..." value={ruleForm.from_contains} onChange={e => setRuleForm({...ruleForm, from_contains: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                <input placeholder="Subject contains..." value={ruleForm.subject_contains} onChange={e => setRuleForm({...ruleForm, subject_contains: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                <input placeholder="Priority (0-10)" type="number" value={ruleForm.priority} onChange={e => setRuleForm({...ruleForm, priority: Number(e.target.value)})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                <input placeholder="Description" value={ruleForm.description} onChange={e => setRuleForm({...ruleForm, description: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              </div>
              <button type="submit" className="mt-3 flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm">
                <Check className="w-3.5 h-3.5" /> Save Rule
              </button>
            </form>
          )}

          <div className="space-y-2">
            {rules.map(rule => (
              <div key={rule.id} className="bg-card rounded-lg border border-border p-4 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <Zap className="w-4 h-4 text-primary" />
                    <span className="font-medium text-sm">{rule.name}</span>
                    <span className="text-xs px-2 py-0.5 rounded bg-secondary text-muted-foreground">{rule.category}</span>
                    <span className="text-xs text-muted-foreground">Priority: {rule.priority}</span>
                  </div>
                  {rule.conditions && (
                    <div className="text-xs text-muted-foreground mt-1">
                      {Object.entries(rule.conditions).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                    </div>
                  )}
                </div>
                <button onClick={() => handleDeleteRule(rule.id)} className="p-1 text-muted-foreground hover:text-red-400 transition-colors">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Categories Tab */}
      {tab === 'categories' && (
        <div>
          <p className="text-sm text-muted-foreground mb-4">
            Categories used by the LLM to classify emails. Changes apply to future classifications.
          </p>

          <div className="space-y-2 mb-4">
            {Object.entries(categories).map(([key, desc]) => (
              <div key={key} className="bg-card rounded-lg border border-border p-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Tag className="w-3.5 h-3.5 text-primary" />
                  <span className="text-sm font-medium">{key}</span>
                  <span className="text-xs text-muted-foreground">— {desc}</span>
                </div>
                <button
                  onClick={async () => {
                    const updated = { ...categories }
                    delete updated[key]
                    await api.put('/settings/categories', { categories: updated })
                    setCategories(updated)
                  }}
                  className="p-1 text-muted-foreground hover:text-red-400 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>

          <div className="bg-card rounded-lg border border-border p-4">
            <div className="grid grid-cols-2 gap-3">
              <input placeholder="Category name (e.g. work)" value={newCatKey}
                onChange={e => setNewCatKey(e.target.value.toLowerCase().replace(/\s+/g, '_'))}
                className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              <input placeholder="Description" value={newCatDesc}
                onChange={e => setNewCatDesc(e.target.value)}
                className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
            </div>
            <button
              onClick={async () => {
                if (!newCatKey || !newCatDesc) return
                const updated = { ...categories, [newCatKey]: newCatDesc }
                await api.put('/settings/categories', { categories: updated })
                setCategories(updated)
                setNewCatKey('')
                setNewCatDesc('')
              }}
              className="mt-3 flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm"
            >
              <Plus className="w-3.5 h-3.5" /> Add Category
            </button>
          </div>
        </div>
      )}

      {/* Digest Thresholds (inside categories tab) */}
      {tab === 'categories' && (
        <div className="mt-6">
          <h3 className="text-sm font-medium mb-2">Digest Display Thresholds</h3>
          <p className="text-xs text-muted-foreground mb-3">
            Controls how emails are displayed in digests. Full detail up to the first threshold, compact (sender + subject only) up to the second, counts only beyond.
          </p>
          <div className="bg-card rounded-lg border border-border p-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Full detail up to</label>
                <input type="number" value={thresholds.detail_threshold}
                  onChange={e => setThresholds({...thresholds, detail_threshold: Number(e.target.value)})}
                  className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Compact view up to</label>
                <input type="number" value={thresholds.compact_threshold}
                  onChange={e => setThresholds({...thresholds, compact_threshold: Number(e.target.value)})}
                  className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              </div>
            </div>
            <button
              onClick={async () => {
                await api.put('/settings/digest-thresholds', thresholds)
              }}
              className="mt-3 flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm"
            >
              <Check className="w-3.5 h-3.5" /> Save Thresholds
            </button>
          </div>
        </div>
      )}

      {/* Forwarding Tab */}
      {tab === 'forwarding' && (
        <div className="space-y-6">
          {/* Policies */}
          <div>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-medium">Forwarding Policies</h3>
                <p className="text-xs text-muted-foreground mt-0.5">Automatically forward messages matching criteria</p>
              </div>
              <button
                onClick={() => setShowAddPolicy(!showAddPolicy)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors"
              >
                {showAddPolicy ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
                {showAddPolicy ? 'Cancel' : 'Add Policy'}
              </button>
            </div>

            {showAddPolicy && (
              <form onSubmit={handleAddPolicy} className="bg-card rounded-lg border border-border p-4 mb-4">
                <div className="grid grid-cols-2 gap-3">
                  <input placeholder="Policy Name" value={policyForm.name} onChange={e => setPolicyForm({...policyForm, name: e.target.value})}
                    className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
                  <input placeholder="Target Email" type="email" value={policyForm.target_email} onChange={e => setPolicyForm({...policyForm, target_email: e.target.value})}
                    className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
                  <select value={policyForm.source_category} onChange={e => setPolicyForm({...policyForm, source_category: e.target.value})}
                    className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary">
                    <option value="">Any category</option>
                    {Object.keys(categories).map(c =>
                      <option key={c} value={c}>{c}</option>
                    )}
                  </select>
                  <input placeholder="Priority (0-10)" type="number" value={policyForm.priority} onChange={e => setPolicyForm({...policyForm, priority: Number(e.target.value)})}
                    className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                  <input placeholder="From contains..." value={policyForm.from_contains} onChange={e => setPolicyForm({...policyForm, from_contains: e.target.value})}
                    className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                  <input placeholder="Subject contains..." value={policyForm.subject_contains} onChange={e => setPolicyForm({...policyForm, subject_contains: e.target.value})}
                    className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                  <input placeholder="Description" value={policyForm.description} onChange={e => setPolicyForm({...policyForm, description: e.target.value})}
                    className="col-span-2 bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
                </div>
                <button type="submit" className="mt-3 flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm">
                  <Check className="w-3.5 h-3.5" /> Save Policy
                </button>
              </form>
            )}

            <div className="space-y-2">
              {policies.length === 0 ? (
                <div className="bg-card rounded-lg border border-border p-4 text-sm text-muted-foreground text-center">
                  No forwarding policies configured yet.
                </div>
              ) : policies.map(policy => (
                <div key={policy.id} className="bg-card rounded-lg border border-border p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <Forward className="w-4 h-4 text-primary" />
                        <span className="font-medium text-sm">{policy.name}</span>
                        {policy.source_category && (
                          <span className="text-xs px-2 py-0.5 rounded bg-secondary text-muted-foreground">{policy.source_category}</span>
                        )}
                        <span className="text-xs text-muted-foreground">→ {policy.target_email}</span>
                        <span className={`w-2 h-2 rounded-full ${policy.enabled ? 'bg-emerald-400' : 'bg-gray-500'}`} />
                      </div>
                      {policy.description && <div className="text-xs text-muted-foreground mt-1">{policy.description}</div>}
                      {policy.conditions && (
                        <div className="text-xs text-muted-foreground mt-1">
                          {Object.entries(policy.conditions).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      <button onClick={() => handleTogglePolicy(policy)}
                        className={`px-2 py-1 text-xs rounded-md border border-border transition-colors ${policy.enabled ? 'text-emerald-400 hover:text-amber-400' : 'text-muted-foreground hover:text-emerald-400'}`}>
                        {policy.enabled ? 'Disable' : 'Enable'}
                      </button>
                      <button onClick={() => handleDeletePolicy(policy.id)} className="p-1 text-muted-foreground hover:text-red-400 transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Recent Forwarding Log */}
          <div>
            <h3 className="text-sm font-medium mb-3">Recent Forwarding Activity</h3>
            {fwdLogs.length === 0 ? (
              <div className="bg-card rounded-lg border border-border p-4 text-sm text-muted-foreground text-center">
                No forwarding activity yet.
              </div>
            ) : (
              <div className="bg-card rounded-lg border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-xs text-muted-foreground">
                      <th className="text-left px-4 py-2 font-medium">Target</th>
                      <th className="text-left px-4 py-2 font-medium">Status</th>
                      <th className="text-left px-4 py-2 font-medium">Time</th>
                      <th className="text-left px-4 py-2 font-medium">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fwdLogs.map(log => (
                      <tr key={log.id} className="border-b border-border/50">
                        <td className="px-4 py-2 text-xs">{log.target_email}</td>
                        <td className="px-4 py-2">
                          <span className={`text-xs px-1.5 py-0.5 rounded ${
                            log.status === 'sent' ? 'bg-emerald-500/15 text-emerald-400' :
                            log.status === 'failed' ? 'bg-red-500/15 text-red-400' :
                            log.status === 'blocked' ? 'bg-amber-500/15 text-amber-400' :
                            'bg-secondary text-muted-foreground'
                          }`}>
                            {log.status}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-xs text-muted-foreground">{formatDate(log.created_at)}</td>
                        <td className="px-4 py-2 text-xs text-red-400">{log.error}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* RSS Feeds Tab */}
      {tab === 'feeds' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium">RSS Feeds</h2>
            <button onClick={() => setShowAddFeed(!showAddFeed)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90">
              {showAddFeed ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
              {showAddFeed ? 'Cancel' : 'Add Feed'}
            </button>
          </div>

          {showAddFeed && (
            <form onSubmit={async (e) => {
              e.preventDefault()
              const f = await api.post<any>('/feeds/', { url: feedForm.url, title: feedForm.title || null })
              setFeeds(prev => [...prev, f])
              setShowAddFeed(false)
              setFeedForm({ url: '', title: '' })
            }} className="bg-card rounded-lg border border-border p-4">
              <div className="grid grid-cols-2 gap-3">
                <input placeholder="Feed URL" value={feedForm.url} onChange={e => setFeedForm({...feedForm, url: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
                <input placeholder="Title (optional — auto-detected)" value={feedForm.title} onChange={e => setFeedForm({...feedForm, title: e.target.value})}
                  className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" />
              </div>
              <button type="submit" className="mt-3 flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm">
                <Check className="w-3.5 h-3.5" /> Add Feed
              </button>
            </form>
          )}

          {feeds.length === 0 && !showAddFeed ? (
            <div className="text-center py-8 text-muted-foreground text-sm">No RSS feeds configured.</div>
          ) : (
            <div className="space-y-2">
              {feeds.map((feed: any) => (
                <div key={feed.id} className="bg-card rounded-lg border border-border p-4 flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <Rss className="w-4 h-4 text-primary" />
                      <span className="text-sm font-medium">{feed.title || feed.url}</span>
                      <span className={`w-2 h-2 rounded-full ${feed.enabled ? 'bg-emerald-400' : 'bg-gray-500'}`} />
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">{feed.url}</div>
                    {feed.last_fetched_at && (
                      <div className="text-xs text-muted-foreground mt-0.5">Last fetched: {formatDate(feed.last_fetched_at)}</div>
                    )}
                    {feed.last_error && (
                      <div className="text-xs text-red-400 mt-0.5">{feed.last_error}</div>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={async () => {
                        setSyncingFeed(feed.id)
                        try {
                          const r = await api.post<any>(`/feeds/${feed.id}/sync`)
                          alert(`Synced: ${r.new_items} new items`)
                          const updated = await api.get<any[]>('/feeds/')
                          setFeeds(updated)
                        } finally { setSyncingFeed(null) }
                      }}
                      disabled={syncingFeed === feed.id}
                      className="p-1.5 rounded-md text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${syncingFeed === feed.id ? 'animate-spin' : ''}`} />
                    </button>
                    <button
                      onClick={async () => {
                        if (!confirm('Delete this feed?')) return
                        await api.delete(`/feeds/${feed.id}`)
                        setFeeds(prev => prev.filter((f: any) => f.id !== feed.id))
                      }}
                      className="p-1.5 rounded-md text-muted-foreground hover:text-red-400 transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Weather Tab */}
      {tab === 'weather' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium">Weather Sources</h2>
            <button onClick={() => setShowAddWeather(!showAddWeather)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90">
              {showAddWeather ? <X className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
              {showAddWeather ? 'Cancel' : 'Add Location'}
            </button>
          </div>

          {showAddWeather && (
            <div className="bg-card rounded-lg border border-border p-4">
              {/* Search input */}
              <div className="flex gap-2 mb-3">
                <input
                  placeholder="Search location (e.g. Berlin, Hamburg, München)..."
                  value={geoQuery}
                  onChange={e => setGeoQuery(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === 'Enter' && geoQuery.length >= 2) {
                      e.preventDefault()
                      setGeoSearching(true)
                      try {
                        const res = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(geoQuery)}&count=5&language=de`)
                        const data = await res.json()
                        setGeoResults(data.results || [])
                      } finally { setGeoSearching(false) }
                    }
                  }}
                  className="flex-1 bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
                <button
                  type="button"
                  onClick={async () => {
                    if (geoQuery.length < 2) return
                    setGeoSearching(true)
                    try {
                      const res = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(geoQuery)}&count=5&language=de`)
                      const data = await res.json()
                      setGeoResults(data.results || [])
                    } finally { setGeoSearching(false) }
                  }}
                  disabled={geoSearching || geoQuery.length < 2}
                  className="px-3 py-2 text-sm bg-secondary border border-border rounded-md text-muted-foreground hover:text-foreground disabled:opacity-50 transition-colors"
                >
                  {geoSearching ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : 'Search'}
                </button>
              </div>

              {/* Search results */}
              {geoResults.length > 0 && !weatherForm.name && (
                <div className="space-y-1 mb-3">
                  {geoResults.map((r: any) => (
                    <button
                      key={`${r.latitude}-${r.longitude}`}
                      type="button"
                      onClick={() => {
                        setWeatherForm({
                          name: r.name,
                          latitude: String(r.latitude),
                          longitude: String(r.longitude),
                        })
                        setGeoResults([])
                      }}
                      className="w-full text-left px-3 py-2 rounded-md bg-secondary/50 hover:bg-secondary text-sm transition-colors"
                    >
                      <span className="font-medium">{r.name}</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        {[r.admin1, r.country].filter(Boolean).join(', ')}
                      </span>
                      <span className="text-xs text-muted-foreground ml-2">
                        ({r.latitude.toFixed(2)}, {r.longitude.toFixed(2)})
                      </span>
                    </button>
                  ))}
                </div>
              )}

              {/* Selected location — confirm */}
              {weatherForm.name && (
                <form onSubmit={async (e) => {
                  e.preventDefault()
                  const s = await api.post<any>('/weather/sources', {
                    name: weatherForm.name,
                    latitude: parseFloat(weatherForm.latitude),
                    longitude: parseFloat(weatherForm.longitude),
                  })
                  setWeatherSources(prev => [...prev, s])
                  setShowAddWeather(false)
                  setWeatherForm({ name: '', latitude: '', longitude: '' })
                  setGeoQuery('')
                  setGeoResults([])
                }}>
                  <div className="grid grid-cols-3 gap-3">
                    <input value={weatherForm.name} onChange={e => setWeatherForm({...weatherForm, name: e.target.value})}
                      className="bg-secondary border border-border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary" required />
                    <input value={weatherForm.latitude} onChange={e => setWeatherForm({...weatherForm, latitude: e.target.value})}
                      className="bg-secondary border border-border rounded-md px-3 py-2 text-sm text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary" required />
                    <input value={weatherForm.longitude} onChange={e => setWeatherForm({...weatherForm, longitude: e.target.value})}
                      className="bg-secondary border border-border rounded-md px-3 py-2 text-sm text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary" required />
                  </div>
                  <div className="flex items-center gap-2 mt-3">
                    <button type="submit" className="flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm">
                      <Check className="w-3.5 h-3.5" /> Add Location
                    </button>
                    <button type="button" onClick={() => { setWeatherForm({ name: '', latitude: '', longitude: '' }); setGeoResults([]) }}
                      className="px-3 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
                      Change
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}

          {weatherSources.length === 0 && !showAddWeather ? (
            <div className="text-center py-8 text-muted-foreground text-sm">No weather locations configured.</div>
          ) : (
            <div className="space-y-2">
              {weatherSources.map((source: any) => (
                <div key={source.id} className="bg-card rounded-lg border border-border p-4 flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <CloudSun className="w-4 h-4 text-primary" />
                      <span className="text-sm font-medium">{source.name}</span>
                      <span className={`w-2 h-2 rounded-full ${source.enabled ? 'bg-emerald-400' : 'bg-gray-500'}`} />
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">
                      {source.latitude}, {source.longitude} · {source.provider || 'openmeteo'}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={async () => {
                        const r = await api.post<any>(`/weather/sources/${source.id}/sync`)
                        if (r.summary) alert(r.summary)
                        else alert(r.error || 'Fetch failed')
                      }}
                      className="p-1.5 rounded-md text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={async () => {
                        if (!confirm('Delete this weather source?')) return
                        await api.delete(`/weather/sources/${source.id}`)
                        setWeatherSources(prev => prev.filter((s: any) => s.id !== source.id))
                      }}
                      className="p-1.5 rounded-md text-muted-foreground hover:text-red-400 transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* LLM Tab */}
      {tab === 'llm' && (
        <div className="space-y-6">
          {/* Active Model */}
          <div>
            <h3 className="text-sm font-medium mb-3">Active Model</h3>
            <div className="bg-card rounded-lg border border-border p-4">
              <div className="flex items-center gap-2 mb-3">
                <Brain className="w-4 h-4 text-primary" />
                <span className="text-sm text-foreground font-medium">{activeModel || 'Loading...'}</span>
              </div>
              {!modelsLoaded ? (
                <button
                  onClick={async () => {
                    const [models, active] = await Promise.all([
                      api.get<{ id: string; name: string }[]>('/llm/models'),
                      api.get<{ model: string }>('/llm/active-model'),
                    ])
                    setAvailableModels(models)
                    setActiveModel(active.model)
                    setModelsLoaded(true)
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-secondary text-muted-foreground hover:text-foreground rounded-md border border-border transition-colors"
                >
                  <RefreshCw className="w-3 h-3" /> Load available models
                </button>
              ) : (
                <div>
                  <input
                    value={modelSearch}
                    onChange={e => setModelSearch(e.target.value)}
                    placeholder="Search models..."
                    className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary mb-2"
                  />
                  <div className="max-h-64 overflow-y-auto border border-border rounded-md">
                    {availableModels
                      .filter(m => !modelSearch || m.id.toLowerCase().includes(modelSearch.toLowerCase()))
                      .slice(0, 50)
                      .map(m => (
                        <button
                          key={m.id}
                          onClick={async () => {
                            await api.put('/llm/active-model?model=' + encodeURIComponent(m.id), {})
                            setActiveModel(m.id)
                          }}
                          className={`w-full text-left px-3 py-2 text-xs border-b border-border/50 transition-colors ${
                            m.id === activeModel
                              ? 'bg-primary/15 text-primary font-medium'
                              : 'text-muted-foreground hover:text-foreground hover:bg-secondary/50'
                          }`}
                        >
                          {m.id}
                        </button>
                      ))}
                  </div>
                  <p className="text-xs text-muted-foreground mt-2">
                    {availableModels.length} models available via OpenRouter
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Providers */}
          <div>
            <h3 className="text-sm font-medium mb-3">Providers</h3>
            {providers.length === 0 ? (
              <div className="bg-card rounded-lg border border-border p-4 text-sm text-muted-foreground">
                Using default OpenRouter configuration from environment variables.
              </div>
            ) : (
              <div className="space-y-2">
                {providers.map(p => (
                  <div key={p.id} className="bg-card rounded-lg border border-border p-4">
                    <div className="flex items-center gap-2">
                      <Brain className="w-4 h-4 text-primary" />
                      <span className="font-medium text-sm">{p.name}</span>
                      <span className="text-xs px-2 py-0.5 rounded bg-secondary text-muted-foreground">{p.provider_type}</span>
                      <span className={`w-2 h-2 rounded-full ${p.enabled ? 'bg-emerald-400' : 'bg-gray-500'}`} />
                    </div>
                    <div className="text-xs text-muted-foreground mt-1">{p.base_url} · Model: {p.default_model}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Prompts */}
          <div>
            <h3 className="text-sm font-medium mb-2">Prompts</h3>
            <p className="text-xs text-muted-foreground mb-4">
              Customize the prompts used for each task. Creating a new version and activating it overrides the default.
              Use {'{'}<code className="text-primary">variable</code>{'}'} placeholders in user prompts.
            </p>

            {/* Prompt list grouped by task_type */}
            {(['classify', 'digest', 'extract', 'draft_reply'] as const).map(taskType => {
              const typePrompts = prompts.filter(p => p.task_type === taskType)
              const active = typePrompts.find(p => p.is_active)
              const isEditing = editingPrompt === taskType

              return (
                <div key={taskType} className="bg-card rounded-lg border border-border mb-3 overflow-hidden">
                  <div
                    className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-secondary/30 transition-colors"
                    onClick={() => setEditingPrompt(isEditing ? null : taskType)}
                  >
                    <div className="flex items-center gap-2">
                      <Brain className="w-4 h-4 text-primary" />
                      <span className="font-medium text-sm">{taskType.replace('_', ' ')}</span>
                      {active ? (
                        <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400">
                          v{active.version} active
                        </span>
                      ) : (
                        <span className="text-xs px-2 py-0.5 rounded bg-secondary text-muted-foreground">
                          using default
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {typePrompts.length} version{typePrompts.length !== 1 ? 's' : ''}
                    </span>
                  </div>

                  {isEditing && (
                    <div className="border-t border-border px-4 py-4">
                      {/* Existing versions */}
                      {typePrompts.length > 0 && (
                        <div className="space-y-2 mb-4">
                          {typePrompts.map(p => (
                            <div key={p.id} className={`p-3 rounded-md border text-xs ${
                              p.is_active ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-border bg-secondary/30'
                            }`}>
                              <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-2">
                                  <span className="font-medium">v{p.version}</span>
                                  {p.description && <span className="text-muted-foreground">— {p.description}</span>}
                                  {p.is_active && <span className="text-emerald-400 font-medium">active</span>}
                                </div>
                                {!p.is_active && (
                                  <button
                                    onClick={async (e) => {
                                      e.stopPropagation()
                                      await api.post(`/llm/prompts/${p.id}/activate`)
                                      const updated = await api.get<LlmPrompt[]>('/llm/prompts')
                                      setPrompts(updated)
                                    }}
                                    className="px-2 py-0.5 rounded bg-primary/15 text-primary hover:bg-primary/25 transition-colors"
                                  >
                                    Activate
                                  </button>
                                )}
                              </div>
                              <div className="text-muted-foreground">
                                <div className="mb-1"><span className="text-foreground/70">System:</span> {p.system_prompt.slice(0, 150)}...</div>
                                <div><span className="text-foreground/70">User:</span> {p.user_prompt_template.slice(0, 100)}...</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* New version form */}
                      <div className="border-t border-border pt-4">
                        <div className="text-xs font-medium text-muted-foreground mb-2">Create new version</div>
                        <input
                          placeholder="Description (e.g. 'Added work category')"
                          value={promptForm.task_type === taskType ? promptForm.description : ''}
                          onChange={e => setPromptForm({...promptForm, task_type: taskType, description: e.target.value})}
                          onFocus={() => {
                            if (promptForm.task_type !== taskType) {
                              const current = active || typePrompts[0]
                              setPromptForm({
                                task_type: taskType,
                                system_prompt: current?.system_prompt || '',
                                user_prompt_template: current?.user_prompt_template || '',
                                description: '',
                              })
                            }
                          }}
                          className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm mb-2 focus:outline-none focus:ring-1 focus:ring-primary"
                        />
                        <textarea
                          placeholder="System prompt"
                          rows={6}
                          value={promptForm.task_type === taskType ? promptForm.system_prompt : ''}
                          onChange={e => setPromptForm({...promptForm, task_type: taskType, system_prompt: e.target.value})}
                          onFocus={() => {
                            if (promptForm.task_type !== taskType) {
                              const current = active || typePrompts[0]
                              setPromptForm({
                                task_type: taskType,
                                system_prompt: current?.system_prompt || '',
                                user_prompt_template: current?.user_prompt_template || '',
                                description: '',
                              })
                            }
                          }}
                          className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm font-mono mb-2 focus:outline-none focus:ring-1 focus:ring-primary resize-y"
                        />
                        <textarea
                          placeholder="User prompt template (use {from}, {subject}, {body}, {items} etc.)"
                          rows={3}
                          value={promptForm.task_type === taskType ? promptForm.user_prompt_template : ''}
                          onChange={e => setPromptForm({...promptForm, task_type: taskType, user_prompt_template: e.target.value})}
                          className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm font-mono mb-2 focus:outline-none focus:ring-1 focus:ring-primary resize-y"
                        />
                        <button
                          onClick={async () => {
                            if (!promptForm.system_prompt || !promptForm.user_prompt_template) return
                            const created = await api.post<LlmPrompt>('/llm/prompts', {
                              task_type: taskType,
                              system_prompt: promptForm.system_prompt,
                              user_prompt_template: promptForm.user_prompt_template,
                              description: promptForm.description || null,
                            })
                            // Auto-activate
                            await api.post(`/llm/prompts/${created.id}/activate`)
                            const updated = await api.get<LlmPrompt[]>('/llm/prompts')
                            setPrompts(updated)
                            setPromptForm({ task_type: 'classify', system_prompt: '', user_prompt_template: '', description: '' })
                          }}
                          className="flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm"
                        >
                          <Check className="w-3.5 h-3.5" /> Save & Activate
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Garmin Tab */}
      {tab === 'garmin' && (
        <div>
          <p className="text-sm text-muted-foreground mb-4">
            Connect your Garmin account to view health data on the Health dashboard.
          </p>

          {!garminLoaded ? (
            <button
              onClick={async () => {
                try {
                  const acc = await api.get<{ email: string; last_sync_at: string | null; last_error: string | null }>('/garmin/account')
                  setGarminAccount(acc)
                  setGarminEmail(acc.email)
                } catch {
                  setGarminAccount(null)
                }
                setGarminLoaded(true)
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-secondary text-muted-foreground hover:text-foreground rounded-md border border-border transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" /> Load Garmin account
            </button>
          ) : (
            <div className="bg-card rounded-lg border border-border p-4 space-y-4 max-w-lg">
              {garminAccount && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Watch className="w-4 h-4 text-primary" />
                    <span className="text-sm font-medium text-foreground">{garminAccount.email}</span>
                    <span className="w-2 h-2 rounded-full bg-emerald-400" />
                  </div>
                  {garminAccount.last_sync_at && (
                    <p className="text-xs text-muted-foreground">Last sync: {formatDate(garminAccount.last_sync_at)}</p>
                  )}
                  {garminAccount.last_error && (
                    <div className="flex items-start gap-2 text-xs text-red-400">
                      <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                      <span>{garminAccount.last_error}</span>
                    </div>
                  )}
                </div>
              )}

              <div className="space-y-3">
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Email</label>
                  <input
                    type="email"
                    value={garminEmail}
                    onChange={e => setGarminEmail(e.target.value)}
                    placeholder="your.email@example.com"
                    className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Password</label>
                  <input
                    type="password"
                    value={garminPassword}
                    onChange={e => setGarminPassword(e.target.value)}
                    placeholder={garminAccount ? '(unchanged)' : 'Garmin password'}
                    className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  />
                </div>
              </div>

              {garminTestResult && (
                <div className={`text-xs px-3 py-2 rounded-md ${
                  garminTestResult.success ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
                }`}>
                  {garminTestResult.message}
                </div>
              )}

              <div className="flex items-center gap-2">
                <button
                  onClick={async () => {
                    setGarminTesting(true)
                    setGarminTestResult(null)
                    try {
                      const r = await api.post<{ message: string }>('/garmin/account/test')
                      setGarminTestResult({ success: true, message: r.message || 'Connection successful' })
                    } catch (e: any) {
                      setGarminTestResult({ success: false, message: e.message || 'Connection failed' })
                    } finally {
                      setGarminTesting(false)
                    }
                  }}
                  disabled={garminTesting || !garminAccount}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-secondary text-muted-foreground hover:text-foreground rounded-md border border-border transition-colors disabled:opacity-50"
                >
                  <TestTube className={`w-3 h-3 ${garminTesting ? 'animate-pulse' : ''}`} />
                  {garminTesting ? 'Testing...' : 'Test'}
                </button>
                <button
                  onClick={async () => {
                    if (!garminEmail) return
                    setGarminSaving(true)
                    setGarminTestResult(null)
                    try {
                      const body: any = { email: garminEmail }
                      if (garminPassword) body.password = garminPassword
                      const acc = await api.post<{ email: string; last_sync_at: string | null; last_error: string | null }>('/garmin/account', body)
                      setGarminAccount(acc)
                      setGarminPassword('')
                      setGarminTestResult({ success: true, message: 'Account saved' })
                    } catch (e: any) {
                      setGarminTestResult({ success: false, message: e.message || 'Save failed' })
                    } finally {
                      setGarminSaving(false)
                    }
                  }}
                  disabled={garminSaving || !garminEmail}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-xs disabled:opacity-50"
                >
                  <Check className={`w-3 h-3 ${garminSaving ? 'animate-pulse' : ''}`} />
                  {garminSaving ? 'Saving...' : 'Save'}
                </button>
                {garminAccount && (
                  <button
                    onClick={async () => {
                      if (!confirm('Delete Garmin account and all synced data?')) return
                      try {
                        await api.delete('/garmin/account')
                        setGarminAccount(null)
                        setGarminEmail('')
                        setGarminPassword('')
                        setGarminTestResult(null)
                      } catch (e: any) {
                        alert(e.message || 'Delete failed')
                      }
                    }}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-muted-foreground hover:text-red-400 rounded-md border border-border transition-colors"
                  >
                    <Trash2 className="w-3 h-3" /> Delete
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Assistant Tab */}
      {tab === 'assistant' && (
        <div>
          <div className="flex items-center gap-2 mb-4">
            <p className="text-sm text-muted-foreground">
              Configure how the Assistant reads and browses your emails in chat.
            </p>
            <button onClick={() => setShowAssistantHelp(!showAssistantHelp)}
              className="p-0.5 text-muted-foreground hover:text-primary transition-colors">
              <HelpCircle className="w-4 h-4" />
            </button>
          </div>
          {showAssistantHelp && (
            <div className="bg-secondary/50 border border-border rounded-lg p-4 mb-4 text-xs text-muted-foreground space-y-2">
              <p className="text-foreground font-medium text-sm">Wie funktioniert der Assistant?</p>
              <p>Wenn du den Assistant nach E-Mail-Inhalten fragst, arbeitet er in zwei Stufen:</p>
              <p><strong className="text-foreground">Stufe 1 — Ueberblick:</strong> Der Assistant ruft eine kompakte Liste deiner letzten Mails ab (nur Absender + Betreff + Datum). So bekommt er einen Ueberblick, ohne das Context Window zu belasten. Wie viele Tage und Mails dabei beruecksichtigt werden, steuerst du mit <em>Browse Days</em> und <em>Browse Limit</em>.</p>
              <p><strong className="text-foreground">Stufe 2 — Detail:</strong> Basierend auf dem Ueberblick entscheidet der Assistant selbst, welche Mails fuer deine Frage relevant sind, und liest nur deren Inhalt. Die maximale Textlaenge pro Mail steuerst du mit <em>Body Max Chars</em>.</p>
              <p>Dieses Vorgehen haelt den Kontext schlank — auch bei hunderten Mails in der Inbox.</p>
            </div>
          )}
          <div className="bg-card rounded-lg border border-border p-4 space-y-4">
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Browse Days (default)</label>
                <input type="number" min={1} max={90} value={assistantSettings.browse_days}
                  onChange={e => setAssistantSettings({...assistantSettings, browse_days: parseInt(e.target.value) || 7})}
                  className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary" />
                <p className="text-xs text-muted-foreground mt-1">Wie viele Tage der Assistant standardmässig zurückschaut</p>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Browse Limit (default)</label>
                <input type="number" min={5} max={200} value={assistantSettings.browse_limit}
                  onChange={e => setAssistantSettings({...assistantSettings, browse_limit: parseInt(e.target.value) || 50})}
                  className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary" />
                <p className="text-xs text-muted-foreground mt-1">Max. Anzahl Mails in der Übersichtsliste</p>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Body Max Chars</label>
                <input type="number" min={500} max={20000} step={500} value={assistantSettings.body_max_chars}
                  onChange={e => setAssistantSettings({...assistantSettings, body_max_chars: parseInt(e.target.value) || 3000})}
                  className="w-full bg-secondary border border-border rounded-md px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary" />
                <p className="text-xs text-muted-foreground mt-1">Max. Zeichenlänge des Mail-Bodys beim Lesen einzelner Mails</p>
              </div>
            </div>
            <button
              onClick={async () => {
                setAssistantSaving(true)
                try {
                  const updated = await api.put<typeof assistantSettings>('/settings/assistant', assistantSettings)
                  setAssistantSettings(updated)
                } finally {
                  setAssistantSaving(false)
                }
              }}
              disabled={assistantSaving}
              className="flex items-center gap-1.5 px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-sm disabled:opacity-50"
            >
              <Check className="w-3.5 h-3.5" />
              {assistantSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
