import { useEffect, useState } from 'react'
import { api } from '../api/client'

interface AuditEntry {
  id: string
  action: string
  entity_type: string | null
  entity_id: string | null
  user: string | null
  created_at: string
}

interface AuditResponse {
  items: AuditEntry[]
  total: number
  page: number
  page_size: number
}

export default function LogsPage() {
  const [logs, setLogs] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<AuditResponse>('/audit/')
      .then(r => setLogs(r.items))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-gray-500">Loading...</div>

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Audit Logs</h1>
      {logs.length === 0 ? (
        <p className="text-gray-500">No audit logs yet.</p>
      ) : (
        <div className="bg-white rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="px-4 py-2 text-left">Time</th>
                <th className="px-4 py-2 text-left">Action</th>
                <th className="px-4 py-2 text-left">Entity</th>
                <th className="px-4 py-2 text-left">User</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {logs.map(log => (
                <tr key={log.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-500">{new Date(log.created_at).toLocaleString('de-DE')}</td>
                  <td className="px-4 py-2">{log.action}</td>
                  <td className="px-4 py-2 text-gray-500">{log.entity_type} {log.entity_id ? `#${log.entity_id.slice(0, 8)}` : ''}</td>
                  <td className="px-4 py-2 text-gray-500">{log.user || 'system'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
