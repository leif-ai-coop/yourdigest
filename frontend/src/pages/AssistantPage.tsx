import { useEffect, useState, useRef, useCallback } from 'react'
import Markdown from 'react-markdown'
import { api } from '../api/client'
import { PageSpinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import {
  MessageSquare, Send, Plus, Trash2, Sparkles, User
} from 'lucide-react'

interface Conversation {
  id: string
  title: string | null
  created_at: string
  updated_at: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export default function AssistantPage() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState('')
  const [toolName, setToolName] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => { scrollToBottom() }, [messages, streamContent])

  const loadConversations = useCallback(async () => {
    try {
      const data = await api.get<Conversation[]>('/assistant/conversations')
      setConversations(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadConversations() }, [loadConversations])

  const loadConversation = async (id: string) => {
    setActiveId(id)
    try {
      const data = await api.get<{ messages: Message[] }>(`/assistant/conversations/${id}`)
      setMessages(data.messages)
    } catch (e) {
      console.error(e)
    }
  }

  const startNewChat = () => {
    setActiveId(null)
    setMessages([])
    setStreamContent('')
    setInput('')
    inputRef.current?.focus()
  }

  const deleteConversation = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Conversation loeschen?')) return
    await api.delete(`/assistant/conversations/${id}`)
    if (activeId === id) startNewChat()
    loadConversations()
  }

  const sendMessage = async () => {
    const content = input.trim()
    if (!content || streaming) return

    // Add user message to UI immediately
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setStreaming(true)
    setStreamContent('')
    setToolName(null)

    // Resize textarea back
    if (inputRef.current) inputRef.current.style.height = 'auto'

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const res = await fetch('/api/assistant/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          conversation_id: activeId,
        }),
        signal: controller.signal,
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || res.statusText)
      }

      const reader = res.body?.getReader()
      if (!reader) throw new Error('No response body')

      const decoder = new TextDecoder()
      let buffer = ''
      let fullContent = ''
      let newConvId = activeId

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))
            if (event.type === 'start' && event.conversation_id) {
              newConvId = event.conversation_id
              setActiveId(newConvId)
            } else if (event.type === 'tool') {
              setToolName(event.name)
            } else if (event.type === 'chunk') {
              setToolName(null)
              fullContent += event.content
              setStreamContent(fullContent)
            } else if (event.type === 'error') {
              throw new Error(event.content)
            }
          } catch (parseErr) {
            // Skip malformed events
          }
        }
      }

      // Add final assistant message
      if (fullContent) {
        const assistantMsg: Message = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: fullContent,
          created_at: new Date().toISOString(),
        }
        setMessages(prev => [...prev, assistantMsg])
      }

      setStreamContent('')
      loadConversations()
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        const errorMsg: Message = {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Fehler: ${e.message}`,
          created_at: new Date().toISOString(),
        }
        setMessages(prev => [...prev, errorMsg])
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const autoResize = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  if (loading) return <PageSpinner />

  return (
    <div className="flex h-[calc(100vh-48px)] -m-6">
      {/* Conversation List */}
      <div className="w-72 border-r border-border flex flex-col bg-background">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <span className="text-sm font-medium text-foreground">Conversations</span>
          <button
            onClick={startNewChat}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            title="New chat"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {conversations.length === 0 ? (
            <div className="p-4 text-xs text-muted-foreground text-center">
              Noch keine Conversations
            </div>
          ) : (
            conversations.map(conv => (
              <div
                key={conv.id}
                onClick={() => loadConversation(conv.id)}
                className={`group px-4 py-3 border-b border-border/50 border-l-2 cursor-pointer transition-colors ${
                  activeId === conv.id ? 'bg-primary/10 border-l-primary' : 'border-l-transparent hover:bg-secondary/50'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-foreground truncate">
                      {conv.title || 'Neue Unterhaltung'}
                    </div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      {formatTime(conv.updated_at)}
                    </div>
                  </div>
                  <button
                    onClick={e => deleteConversation(conv.id, e)}
                    className="p-1 rounded opacity-0 group-hover:opacity-100 !text-muted-foreground hover:!text-red-400 transition-all"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 flex flex-col bg-background">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {messages.length === 0 && !streaming ? (
            <div className="h-full flex items-center justify-center">
              <EmptyState
                icon={MessageSquare}
                title="CuraOS Assistant"
                description="Frage mich etwas zu deinen E-Mails, Digests oder Einstellungen."
              />
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-4">
              {messages.map(msg => (
                <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : ''}`}>
                  {msg.role === 'assistant' && (
                    <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                      <Sparkles className="w-3.5 h-3.5 text-primary" />
                    </div>
                  )}
                  <div className={`max-w-[80%] rounded-lg px-4 py-2.5 text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-secondary text-foreground'
                  }`}>
                    {msg.role === 'assistant' ? (
                      <div className="prose prose-invert prose-sm max-w-none [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_li]:my-0.5 [&_pre]:bg-background/50 [&_pre]:rounded [&_pre]:p-2 [&_code]:text-primary [&_a]:text-primary"><Markdown>{msg.content}</Markdown></div>
                    ) : (
                      <div className="whitespace-pre-wrap">{msg.content}</div>
                    )}
                  </div>
                  {msg.role === 'user' && (
                    <div className="w-7 h-7 rounded-full bg-secondary flex items-center justify-center flex-shrink-0 mt-0.5">
                      <User className="w-3.5 h-3.5 text-muted-foreground" />
                    </div>
                  )}
                </div>
              ))}

              {/* Streaming indicator */}
              {streaming && (
                <div className="flex gap-3">
                  <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Sparkles className="w-3.5 h-3.5 text-primary animate-pulse" />
                  </div>
                  <div className="max-w-[80%] rounded-lg px-4 py-2.5 text-sm leading-relaxed bg-secondary text-foreground">
                    {streamContent ? (
                      <div>
                        <div className="prose prose-invert prose-sm max-w-none [&_p]:my-1.5 [&_ul]:my-1.5 [&_ol]:my-1.5 [&_li]:my-0.5 [&_pre]:bg-background/50 [&_pre]:rounded [&_pre]:p-2 [&_code]:text-primary [&_a]:text-primary"><Markdown>{streamContent}</Markdown></div>
                        <span className="animate-pulse">|</span>
                      </div>
                    ) : toolName ? (
                      <div className="flex items-center gap-2 text-muted-foreground">
                        <Sparkles className="w-3.5 h-3.5 text-primary animate-spin" />
                        <span className="text-xs">{toolName.replace(/_/g, ' ')}...</span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5 text-muted-foreground">
                        <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: '0ms' }} />
                        <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: '150ms' }} />
                        <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input */}
        <div className="px-6 py-4 border-t border-border">
          <div className="max-w-3xl mx-auto flex gap-3 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => { setInput(e.target.value); autoResize(e.target) }}
              onKeyDown={handleKeyDown}
              placeholder="Nachricht eingeben... (Enter zum Senden, Shift+Enter für Zeilenumbruch)"
              rows={1}
              className="flex-1 bg-secondary border border-border rounded-lg px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary resize-none"
              disabled={streaming}
            />
            <button
              onClick={sendMessage}
              disabled={streaming || !input.trim()}
              className="p-3 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Senden"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
