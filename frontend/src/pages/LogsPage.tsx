import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { PageSpinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import { formatDate } from '../lib/utils'
import { ScrollText, Brain } from 'lucide-react'

interface AuditEntry {
  id: string
  action: string
  entity_type: string | null
  entity_id: string | null
  user: string | null
  details: Record<string, any> | null
  ip_address: string | null
  created_at: string
}

interface LlmTask {
  id: string
  task_type: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  duration_ms: number
  status: string
  error: string | null
  created_at: string
}

interface AuditResponse {
  items: AuditEntry[]
  total: number
  page: number
  page_size: number
}

export default function LogsPage() {
  const [tab, setTab] = useState<'audit' | 'llm'>('llm')
  const [auditLogs, setAuditLogs] = useState<AuditEntry[]>([])
  const [llmTasks, setLlmTasks] = useState<LlmTask[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get<AuditResponse>('/audit/'),
      api.get<LlmTask[]>('/llm/tasks'),
    ]).then(([a, l]) => {
      setAuditLogs(a.items)
      setLlmTasks(l)
    }).finally(() => setLoading(false))
  }, [])

  if (loading) return <PageSpinner />

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <ScrollText className="w-5 h-5 text-primary" />
        <h1 className="text-xl font-semibold">Logs</h1>
      </div>

      <div className="flex gap-1 mb-6 bg-card rounded-lg p-1 w-fit">
        <button onClick={() => setTab('llm')}
          className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors ${
            tab === 'llm' ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:text-foreground'
          }`}>
          <Brain className="w-3.5 h-3.5" /> LLM Tasks ({llmTasks.length})
        </button>
        <button onClick={() => setTab('audit')}
          className={`flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors ${
            tab === 'audit' ? 'bg-primary/15 text-primary font-medium' : 'text-muted-foreground hover:text-foreground'
          }`}>
          <ScrollText className="w-3.5 h-3.5" /> Audit Log ({auditLogs.length})
        </button>
      </div>

      {tab === 'llm' && (
        llmTasks.length === 0 ? (
          <EmptyState icon={Brain} title="No LLM tasks yet" description="Tasks will appear here when you classify emails or generate drafts." />
        ) : (
          <div className="space-y-2">
            {llmTasks.map(task => (
              <div key={task.id} className="bg-card rounded-lg border border-border p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Brain className={`w-4 h-4 ${task.status === 'completed' ? 'text-emerald-400' : task.status === 'failed' ? 'text-red-400' : 'text-amber-400'}`} />
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">{task.task_type}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          task.status === 'completed' ? 'bg-emerald-500/15 text-emerald-400' :
                          task.status === 'failed' ? 'bg-red-500/15 text-red-400' : 'bg-amber-500/15 text-amber-400'
                        }`}>{task.status}</span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {task.model} · {task.total_tokens} tokens · {task.duration_ms}ms
                      </div>
                    </div>
                  </div>
                  <span className="text-xs text-muted-foreground">{formatDate(task.created_at)}</span>
                </div>
                {task.error && <div className="mt-2 text-xs text-red-400 bg-red-500/10 rounded p-2">{task.error}</div>}
              </div>
            ))}
          </div>
        )
      )}

      {tab === 'audit' && (
        auditLogs.length === 0 ? (
          <EmptyState icon={ScrollText} title="No audit logs yet" description="Actions will be logged here." />
        ) : (
          <div className="bg-card rounded-lg border border-border overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="px-4 py-2.5 text-left font-medium">Time</th>
                  <th className="px-4 py-2.5 text-left font-medium">Action</th>
                  <th className="px-4 py-2.5 text-left font-medium">Entity</th>
                  <th className="px-4 py-2.5 text-left font-medium">User</th>
                </tr>
              </thead>
              <tbody>
                {auditLogs.map(log => (
                  <tr key={log.id} className="border-b border-border/50 hover:bg-secondary/30 transition-colors">
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{formatDate(log.created_at)}</td>
                    <td className="px-4 py-2.5">{log.action}</td>
                    <td className="px-4 py-2.5 text-muted-foreground">{log.entity_type} {log.entity_id ? `#${log.entity_id.slice(0, 8)}` : ''}</td>
                    <td className="px-4 py-2.5 text-muted-foreground">{log.user || 'system'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}
    </div>
  )
}
