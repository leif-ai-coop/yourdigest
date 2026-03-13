import { useEffect, useState } from 'react'
import { api } from '../api/client'

interface MailAccount {
  id: string
  email: string
  display_name: string | null
  imap_host: string
  enabled: boolean
  last_sync_at: string | null
  last_error: string | null
}

export default function SettingsPage() {
  const [accounts, setAccounts] = useState<MailAccount[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    email: '', imap_host: '', imap_port: 993, smtp_host: '', smtp_port: 587,
    username: '', password: '', display_name: '',
  })

  const loadAccounts = () => {
    api.get<MailAccount[]>('/mail/accounts').then(setAccounts).catch(console.error)
  }

  useEffect(loadAccounts, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/mail/accounts', { ...form, imap_use_ssl: true, smtp_use_tls: true, enabled: true })
      setShowForm(false)
      setForm({ email: '', imap_host: '', imap_port: 993, smtp_host: '', smtp_port: 587, username: '', password: '', display_name: '' })
      loadAccounts()
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold">Settings</h1>
        <button onClick={() => setShowForm(!showForm)} className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm">
          {showForm ? 'Cancel' : 'Add Account'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="bg-white p-4 rounded-lg border mb-4 grid grid-cols-2 gap-3">
          <input placeholder="Email" value={form.email} onChange={e => setForm({...form, email: e.target.value})} className="border rounded px-3 py-2 text-sm" required />
          <input placeholder="Display Name" value={form.display_name} onChange={e => setForm({...form, display_name: e.target.value})} className="border rounded px-3 py-2 text-sm" />
          <input placeholder="IMAP Host" value={form.imap_host} onChange={e => setForm({...form, imap_host: e.target.value})} className="border rounded px-3 py-2 text-sm" required />
          <input placeholder="IMAP Port" type="number" value={form.imap_port} onChange={e => setForm({...form, imap_port: Number(e.target.value)})} className="border rounded px-3 py-2 text-sm" />
          <input placeholder="SMTP Host" value={form.smtp_host} onChange={e => setForm({...form, smtp_host: e.target.value})} className="border rounded px-3 py-2 text-sm" required />
          <input placeholder="SMTP Port" type="number" value={form.smtp_port} onChange={e => setForm({...form, smtp_port: Number(e.target.value)})} className="border rounded px-3 py-2 text-sm" />
          <input placeholder="Username" value={form.username} onChange={e => setForm({...form, username: e.target.value})} className="border rounded px-3 py-2 text-sm" required />
          <input placeholder="Password" type="password" value={form.password} onChange={e => setForm({...form, password: e.target.value})} className="border rounded px-3 py-2 text-sm" required />
          <button type="submit" className="col-span-2 px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 text-sm">Save Account</button>
        </form>
      )}

      <div className="bg-white rounded-lg border divide-y">
        {accounts.length === 0 ? (
          <p className="p-4 text-gray-500">No mail accounts configured.</p>
        ) : accounts.map(acc => (
          <div key={acc.id} className="px-4 py-3 flex items-center justify-between">
            <div>
              <div className="font-medium">{acc.email}</div>
              <div className="text-sm text-gray-500">{acc.imap_host} {acc.last_sync_at ? `| Last sync: ${new Date(acc.last_sync_at).toLocaleString('de-DE')}` : ''}</div>
              {acc.last_error && <div className="text-sm text-red-500">{acc.last_error}</div>}
            </div>
            <div className="flex gap-2">
              <button onClick={() => api.post(`/mail/accounts/${acc.id}/test`).then(r => alert((r as {message: string}).message)).catch(e => alert(e.message))} className="px-3 py-1 text-xs border rounded hover:bg-gray-50">Test</button>
              <button onClick={() => api.post(`/mail/accounts/${acc.id}/sync`).then(() => loadAccounts()).catch(e => alert(e.message))} className="px-3 py-1 text-xs border rounded hover:bg-gray-50">Sync</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
