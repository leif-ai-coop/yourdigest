import { useEffect, useState } from 'react'
import { api } from '../api/client'

interface MailMessage {
  id: string
  subject: string | null
  from_address: string
  date: string | null
  is_read: boolean
  is_flagged: boolean
  folder: string
}

export default function InboxPage() {
  const [messages, setMessages] = useState<MailMessage[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<MailMessage[]>('/mail/messages?is_archived=false')
      .then(setMessages)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-gray-500">Loading...</div>

  return (
    <div>
      <h1 className="text-2xl font-bold mb-4">Inbox</h1>
      {messages.length === 0 ? (
        <p className="text-gray-500">No messages yet. Configure a mail account in Settings.</p>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 divide-y">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`px-4 py-3 flex items-center gap-4 hover:bg-gray-50 cursor-pointer ${
                !msg.is_read ? 'font-semibold' : ''
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="text-sm text-gray-500 truncate">{msg.from_address}</div>
                <div className="truncate">{msg.subject || '(no subject)'}</div>
              </div>
              <div className="text-xs text-gray-400 whitespace-nowrap">
                {msg.date ? new Date(msg.date).toLocaleDateString('de-DE') : ''}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
