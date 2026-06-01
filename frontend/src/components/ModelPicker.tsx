import { useState } from 'react'
import { ChevronRight } from 'lucide-react'

/** Searchable LLM model dropdown. Empty value = app default. Shared by
 *  PodcastsPage and RssPage. */
export function ModelPicker({ label, value, onChange, models, appDefault }: {
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
