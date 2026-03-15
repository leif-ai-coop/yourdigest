import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { formatDate, truncate } from '../lib/utils'
import { CategoryBadge } from '../components/Badge'
import { PageSpinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import {
  Inbox, Star, Archive, Eye, EyeOff, ChevronLeft,
  RefreshCw, Sparkles, Paperclip, Link2, AlertCircle,
  PenLine, Copy, Check, X, Send, Trash2, MailX,
  FolderOpen
} from 'lucide-react'

interface MailMessage {
  id: string
  account_id: string
  message_id: string | null
  subject: string | null
  from_address: string
  to_addresses: string | null
  cc_addresses: string | null
  date: string | null
  is_read: boolean
  is_flagged: boolean
  is_archived: boolean
  folder: string
  size_bytes: number | null
  created_at: string
  unsubscribe_url?: string | null
  body_text?: string | null
  body_html?: string | null
  attachments?: { id: string; filename: string | null; content_type: string | null; size_bytes: number | null }[]
  links?: { id: string; url: string; text: string | null; domain: string | null }[]
  classifications?: { category: string; confidence: number; priority: number; summary: string | null; action_required: boolean }[]
}

interface Classification {
  id: string
  category: string
  confidence: number
  priority: number
  summary: string | null
  action_required: boolean
  tags: string[] | null
  classified_by: string
  llm_model: string | null
  created_at: string
}

function stripStyleTags(html: string): string {
  return html.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
}

function extractSender(from: string): { name: string; email: string } {
  const match = from.match(/^"?([^"<]*)"?\s*<?([^>]*)>?$/)
  if (match) return { name: match[1].trim() || match[2], email: match[2] || from }
  return { name: from, email: from }
}

export default function InboxPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [messages, setMessages] = useState<MailMessage[]>([])
  const [selected, setSelected] = useState<MailMessage | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [classifying, setClassifying] = useState(false)
  const [filter, setFilter] = useState<'all' | 'unread' | 'flagged'>('all')
  const [showArchived, setShowArchived] = useState(false)
  const [folders, setFolders] = useState<{ folder: string; count: number }[]>([])
  const [activeFolder, setActiveFolder] = useState('INBOX')
  const [drafting, setDrafting] = useState(false)
  const [showDraftForm, setShowDraftForm] = useState(false)
  const [draftInstructions, setDraftInstructions] = useState('')
  const [draftTone, setDraftTone] = useState('professional')
  const [draftResult, setDraftResult] = useState<string | null>(null)
  const [draftSavedToDrafts, setDraftSavedToDrafts] = useState(false)
  const [draftCopied, setDraftCopied] = useState(false)
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [replyTo, setReplyTo] = useState('')
  const [replySubject, setReplySubject] = useState('')

  const loadMessages = useCallback(async () => {
    try {
      let url = `/mail/messages?page_size=100&folder=${encodeURIComponent(activeFolder)}`
      if (!showArchived) url += '&is_archived=false'
      if (filter === 'unread') url += '&is_read=false'
      const data = await api.get<MailMessage[]>(url)
      setMessages(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [filter, showArchived, activeFolder])

  useEffect(() => { loadMessages() }, [loadMessages])

  useEffect(() => {
    api.get<{ folder: string; count: number }[]>('/mail/folders').then(setFolders).catch(() => {})
  }, [])

  // Deep-link: open mail directly from ?msg=ID (hide mail list)
  const [deepLinked, setDeepLinked] = useState(false)

  useEffect(() => {
    const msgId = searchParams.get('msg')
    if (msgId && !selected) {
      setDeepLinked(true)
      api.get<MailMessage>(`/mail/messages/${msgId}`)
        .then(detail => setSelected(detail))
        .catch(() => {
          setSearchParams({}, { replace: true })
          setDeepLinked(false)
        })
    }
  }, [searchParams])

  const loadDetail = async (msg: MailMessage) => {
    try {
      const detail = await api.get<MailMessage>(`/mail/messages/${msg.id}`)
      setSelected(detail)
      setSearchParams({ msg: msg.id }, { replace: true })
      if (!msg.is_read) {
        // Mark as read on server but don't update list immediately to avoid layout shift
        api.post('/mail/messages/action', { action: 'read', message_ids: [msg.id] })
      }
    } catch (e) {
      console.error(e)
    }
  }

  const clearSelection = () => {
    setSelected(null)
    setDeepLinked(false)
    setSearchParams({}, { replace: true })
    setDraftResult(null)
    setShowDraftForm(false)
    setDraftInstructions('')
    setSent(false)
    // Reload to pick up read status changes
    loadMessages()
  }

  const handleAction = async (action: string, ids: string[]) => {
    await api.post('/mail/messages/action', { action, message_ids: ids })
    await loadMessages()
    if (selected && ids.includes(selected.id)) {
      if (action === 'archive' || action === 'delete') clearSelection()
      else {
        const detail = await api.get<MailMessage>(`/mail/messages/${selected.id}`)
        setSelected(detail)
      }
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this message permanently?')) return
    await handleAction('delete', [id])
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const accounts = await api.get<{ id: string }[]>('/mail/accounts')
      for (const acc of accounts) {
        await api.post(`/mail/accounts/${acc.id}/sync`)
      }
      await loadMessages()
      api.get<{ folder: string; count: number }[]>('/mail/folders').then(setFolders).catch(() => {})
    } finally {
      setSyncing(false)
    }
  }

  const handleClassify = async (messageId: string) => {
    setClassifying(true)
    try {
      await api.post<Classification>(`/classification/classify/${messageId}`)
      const detail = await api.get<MailMessage>(`/mail/messages/${messageId}`)
      setSelected(detail)
    } finally {
      setClassifying(false)
    }
  }

  const handleDraftReply = async (messageId: string) => {
    setDrafting(true)
    setDraftResult(null)
    try {
      const result = await api.post<{ draft: string; model: string; tokens_used: number; saved_to_drafts: boolean }>('/llm/draft-reply', {
        message_id: messageId,
        instructions: draftInstructions || null,
        tone: draftTone,
      })
      setDraftResult(result.draft)
      setDraftSavedToDrafts(result.saved_to_drafts)
      setSent(false)
      // Pre-fill reply fields
      if (selected) {
        setReplyTo(selected.from_address)
        const subj = selected.subject || ''
        setReplySubject(subj.toLowerCase().startsWith('re:') ? subj : `Re: ${subj}`)
      }
      setShowDraftForm(false)
    } catch (e: any) {
      alert(`Draft failed: ${e.message}`)
    } finally {
      setDrafting(false)
    }
  }

  const copyDraft = () => {
    if (draftResult) {
      navigator.clipboard.writeText(draftResult)
      setDraftCopied(true)
      setTimeout(() => setDraftCopied(false), 2000)
    }
  }

  const handleSendReply = async () => {
    if (!draftResult || !selected) return
    if (!confirm(`Send reply to ${replyTo}?`)) return
    setSending(true)
    try {
      await api.post('/mail/send-reply', {
        message_id: selected.id,
        to: replyTo,
        subject: replySubject,
        body: draftResult,
      })
      setSent(true)
    } catch (e: any) {
      alert(`Send failed: ${e.message}`)
    } finally {
      setSending(false)
    }
  }

  if (loading) return <PageSpinner />

  return (
    <div className="flex h-[calc(100vh-48px)] -m-6">
      {/* Mail List */}
      <div className={`${deepLinked && selected ? 'hidden' : selected ? 'w-96' : 'flex-1'} border-r border-border flex flex-col bg-background`}>
        {/* Folder Tabs */}
        {folders.length > 1 && (
          <div className="flex items-center gap-1 px-4 py-2 border-b border-border overflow-x-auto">
            {folders.map(f => (
              <button
                key={f.folder}
                onClick={() => {
                  setActiveFolder(f.folder)
                  setSelected(null)
                  setDeepLinked(false)
                  setSearchParams({}, { replace: true })
                }}
                className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md whitespace-nowrap transition-colors ${
                  activeFolder === f.folder
                    ? 'bg-primary/15 text-primary font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                }`}
              >
                <FolderOpen className="w-3 h-3" />
                {f.folder.replace('INBOX.', '').replace('INBOX/', '')}
                <span className="text-xs opacity-60">{f.count}</span>
              </button>
            ))}
          </div>
        )}

        {/* Toolbar */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-1">
            {(['all', 'unread', 'flagged'] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  filter === f
                    ? 'bg-primary/15 text-primary font-medium'
                    : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                }`}
              >
                {f === 'all' ? 'All' : f === 'unread' ? 'Unread' : 'Flagged'}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowArchived(!showArchived)}
              className={`p-1.5 rounded-md text-xs transition-colors ${showArchived ? 'text-primary bg-primary/15' : 'text-muted-foreground hover:text-foreground'}`}
              title={showArchived ? 'Hide archived' : 'Show archived'}
            >
              <Archive className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={handleSync}
              disabled={syncing}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
              title="Sync now"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${syncing ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Message List */}
        <div className="flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <EmptyState icon={Inbox} title="No messages" description="Your inbox is empty or no messages match this filter." />
          ) : (
            messages.map(msg => {
              const sender = extractSender(msg.from_address)
              const isSelected = selected?.id === msg.id
              return (
                <div
                  key={msg.id}
                  onClick={() => loadDetail(msg)}
                  className={`px-4 py-3 border-b border-border/50 border-l-2 cursor-pointer transition-colors ${
                    isSelected ? 'bg-primary/10 border-l-primary' : 'border-l-transparent hover:bg-secondary/50'
                  } ${!msg.is_read ? 'text-foreground' : 'text-muted-foreground'}`}
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        {!msg.is_read && <div className="w-1.5 h-1.5 rounded-full bg-primary flex-shrink-0" />}
                        <span className={`text-sm truncate ${!msg.is_read ? 'font-semibold text-foreground' : ''}`}>
                          {sender.name}
                        </span>
                        {msg.is_flagged && <Star className="w-3 h-3 text-amber-400 fill-amber-400 flex-shrink-0" />}
                      </div>
                      <div className={`text-sm truncate mb-0.5 ${!msg.is_read ? 'text-foreground' : 'text-muted-foreground'}`}>
                        {msg.subject || '(no subject)'}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0 pt-0.5">
                      {msg.unsubscribe_url && (
                        <a
                          href={msg.unsubscribe_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={e => e.stopPropagation()}
                          className="p-1 rounded !text-muted-foreground hover:!text-orange-400 transition-colors"
                          title="Unsubscribe"
                        >
                          <MailX className="w-3.5 h-3.5" />
                        </a>
                      )}
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(msg.id) }}
                        className="p-1 rounded !text-muted-foreground hover:!text-red-400 transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                      <span className="text-xs !text-muted-foreground whitespace-nowrap ml-1">
                        {formatDate(msg.date)}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>

        <div className="px-4 py-2 border-t border-border text-xs text-muted-foreground">
          {messages.length} messages
        </div>
      </div>

      {/* Detail Panel */}
      {selected && (
        <div className="flex-1 flex flex-col bg-background overflow-hidden">
          {/* Detail Header */}
          <div className="px-6 py-4 border-b border-border">
            <div className="flex items-center gap-3 mb-3">
              <button
                onClick={clearSelection}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <div className="flex items-center gap-2 flex-1">
                {selected.classifications?.map((c, i) => (
                  <CategoryBadge key={i} category={c.category} />
                ))}
                {selected.classifications?.some(c => c.action_required) && (
                  <span className="flex items-center gap-1 text-xs text-amber-400">
                    <AlertCircle className="w-3 h-3" /> Action required
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => handleClassify(selected.id)}
                  disabled={classifying}
                  className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md bg-primary/15 text-primary hover:bg-primary/25 transition-colors disabled:opacity-50"
                  title="Classify with AI"
                >
                  <Sparkles className={`w-3 h-3 ${classifying ? 'animate-pulse' : ''}`} />
                  Classify
                </button>
                <button
                  onClick={() => { setShowDraftForm(!showDraftForm); setDraftResult(null) }}
                  className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md transition-colors ${
                    showDraftForm || draftResult ? 'bg-primary/15 text-primary' : 'bg-secondary text-muted-foreground hover:text-foreground'
                  }`}
                  title="Draft a reply with AI"
                >
                  <PenLine className="w-3 h-3" />
                  Draft Reply
                </button>
                <button
                  onClick={() => handleAction(selected.is_flagged ? 'unflag' : 'flag', [selected.id])}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-amber-400 transition-colors"
                >
                  <Star className={`w-3.5 h-3.5 ${selected.is_flagged ? 'fill-amber-400 text-amber-400' : ''}`} />
                </button>
                <button
                  onClick={() => handleAction('archive', [selected.id])}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground transition-colors"
                  title="Archive"
                >
                  <Archive className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => handleDelete(selected.id)}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-red-400 transition-colors"
                  title="Delete"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
                {selected.unsubscribe_url && (
                  <a
                    href={selected.unsubscribe_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md bg-orange-500/15 text-orange-400 hover:bg-orange-500/25 transition-colors"
                    title="Unsubscribe"
                  >
                    <MailX className="w-3 h-3" />
                    Unsubscribe
                  </a>
                )}
                <button
                  onClick={() => handleAction(selected.is_read ? 'unread' : 'read', [selected.id])}
                  className="p-1.5 rounded-md text-muted-foreground hover:text-foreground transition-colors"
                >
                  {selected.is_read ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>

            <h2 className="text-lg font-semibold mb-2 text-foreground">{selected.subject || '(no subject)'}</h2>

            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>From: <span className="text-foreground">{extractSender(selected.from_address).name}</span></span>
              {selected.to_addresses && <span>To: {truncate(selected.to_addresses, 40)}</span>}
              <span>{formatDate(selected.date)}</span>
            </div>

            {/* Classification Summary */}
            {selected.classifications && selected.classifications.length > 0 && (
              <div className="mt-3 p-3 rounded-lg bg-secondary/50 text-sm">
                <div className="flex items-center gap-2 mb-1">
                  <Sparkles className="w-3.5 h-3.5 text-primary" />
                  <span className="text-xs font-medium text-primary">AI Summary</span>
                </div>
                <p className="text-muted-foreground text-xs">{selected.classifications[0].summary}</p>
              </div>
            )}

            {/* Draft Reply Form */}
            {showDraftForm && (
              <div className="mt-3 p-3 rounded-lg bg-secondary/50 border border-border">
                <div className="flex items-center gap-2 mb-2">
                  <PenLine className="w-3.5 h-3.5 text-primary" />
                  <span className="text-xs font-medium text-primary">Draft Reply</span>
                </div>
                <textarea
                  rows={2}
                  value={draftInstructions}
                  onChange={e => setDraftInstructions(e.target.value)}
                  placeholder="Instructions (optional) — e.g. 'Decline politely' or 'Ask for details about the deadline'"
                  className="w-full bg-background border border-border rounded-md px-3 py-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary resize-y mb-2"
                />
                <div className="flex items-center gap-2">
                  <select
                    value={draftTone}
                    onChange={e => setDraftTone(e.target.value)}
                    className="bg-background border border-border rounded-md px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="professional">Professional</option>
                    <option value="friendly">Friendly</option>
                    <option value="formal">Formal</option>
                    <option value="casual">Casual</option>
                    <option value="brief">Brief</option>
                  </select>
                  <button
                    onClick={() => handleDraftReply(selected.id)}
                    disabled={drafting}
                    className="flex items-center gap-1.5 px-3 py-1 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-xs disabled:opacity-50"
                  >
                    <Sparkles className={`w-3 h-3 ${drafting ? 'animate-pulse' : ''}`} />
                    {drafting ? 'Generating...' : 'Generate'}
                  </button>
                  <button onClick={() => setShowDraftForm(false)} className="text-xs text-muted-foreground hover:text-foreground">
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Draft Result — editable + sendable */}
            {draftResult && (
              <div className="mt-3 p-3 rounded-lg bg-secondary/50 border border-primary/20">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <PenLine className="w-3.5 h-3.5 text-primary" />
                    <span className="text-xs font-medium text-primary">{sent ? 'Sent' : 'Draft Reply'}</span>
                    {draftSavedToDrafts && !sent && (
                      <span className="text-xs text-muted-foreground">· saved to drafts</span>
                    )}
                    {sent && (
                      <span className="text-xs text-emerald-400 flex items-center gap-1">
                        <Check className="w-3 h-3" /> Sent successfully
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={copyDraft}
                      className="flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-secondary text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {draftCopied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                      {draftCopied ? 'Copied' : 'Copy'}
                    </button>
                    <button onClick={() => setDraftResult(null)} className="p-0.5 text-muted-foreground hover:text-foreground">
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                </div>
                {!sent && (
                  <>
                    <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1.5 mb-2 text-xs">
                      <span className="text-muted-foreground pt-1">To:</span>
                      <input
                        value={replyTo}
                        onChange={e => setReplyTo(e.target.value)}
                        className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                      <span className="text-muted-foreground pt-1">Subject:</span>
                      <input
                        value={replySubject}
                        onChange={e => setReplySubject(e.target.value)}
                        className="bg-background border border-border rounded px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>
                    <textarea
                      rows={8}
                      value={draftResult}
                      onChange={e => setDraftResult(e.target.value)}
                      className="w-full bg-background border border-border rounded-md px-3 py-2 text-xs text-foreground font-sans leading-relaxed focus:outline-none focus:ring-1 focus:ring-primary resize-y mb-2"
                    />
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleSendReply}
                        disabled={sending || !replyTo}
                        className="flex items-center gap-1.5 px-4 py-1.5 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 text-xs font-medium disabled:opacity-50 transition-colors"
                      >
                        <Send className={`w-3 h-3 ${sending ? 'animate-pulse' : ''}`} />
                        {sending ? 'Sending...' : 'Send'}
                      </button>
                      <button
                        onClick={() => { setShowDraftForm(true); setDraftResult(null); setSent(false) }}
                        className="px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                      >
                        Regenerate
                      </button>
                    </div>
                  </>
                )}
                {sent && (
                  <div className="text-xs text-muted-foreground mt-1">
                    Reply sent to {replyTo}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Detail Body */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {selected.body_html ? (
              <div
                ref={el => {
                  if (el) el.querySelectorAll('a[href]').forEach(a => {
                    a.setAttribute('target', '_blank')
                    a.setAttribute('rel', 'noopener noreferrer')
                  })
                }}
                className="mail-body prose prose-invert prose-sm max-w-none"
                dangerouslySetInnerHTML={{ __html: stripStyleTags(selected.body_html) }}
              />
            ) : (
              <pre className="text-sm text-muted-foreground whitespace-pre-wrap font-sans">{selected.body_text}</pre>
            )}
          </div>

          {/* Detail Footer - Attachments & Links */}
          {((selected.attachments && selected.attachments.length > 0) || (selected.links && selected.links.length > 0)) && (
            <div className="px-6 py-3 border-t border-border">
              {selected.attachments && selected.attachments.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap mb-2">
                  <Paperclip className="w-3.5 h-3.5 text-muted-foreground" />
                  {selected.attachments.map(att => (
                    <span key={att.id} className="text-xs bg-secondary px-2 py-0.5 rounded">
                      {att.filename || 'attachment'}
                    </span>
                  ))}
                </div>
              )}
              {selected.links && selected.links.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap">
                  <Link2 className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">{selected.links.length} links</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
