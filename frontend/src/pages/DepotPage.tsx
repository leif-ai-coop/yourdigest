import { useEffect, useState, useRef, useCallback } from 'react'
import { api } from '../api/client'
import { PageSpinner, Spinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import { Wallet, Upload, RefreshCw, Plus, Trash2, Pencil, X, AlertTriangle, TrendingUp, TrendingDown, Code, History, ChevronUp, ChevronDown } from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'

interface Position {
  id: string
  name: string
  isin: string | null
  wkn: string | null
  quantity: number
  avg_buy_price: number | null
  currency: string
  last_price: number | null
  last_value: number | null
  last_price_at: string | null
  day_change_pct: number | null
  total_change_pct: number | null
  market_symbol: string | null
  price_stale: boolean
  source: string
  is_active: boolean
}

interface Totals {
  total_value: number
  total_cost: number | null
  total_gain: number | null
  total_gain_pct: number | null
  day_change_value: number | null
  position_count: number
  currency: string
  last_update: string | null
  has_stale_prices: boolean
}

interface Overview { totals: Totals; positions: Position[] }

interface ParsedPosition {
  name: string
  isin: string | null
  wkn: string | null
  quantity: number | null
  avg_buy_price: number | null
  last_price: number | null
  last_value: number | null
  day_change_pct: number | null
  total_change_pct: number | null
  currency: string | null
}

interface PreviewItem {
  parsed: ParsedPosition
  match_id: string | null
  match_name: string | null
  status: 'new' | 'update' | 'unchanged'
}

interface Preview {
  items: PreviewItem[]
  parsed_total_value: number | null
  model_used: string | null
  warning: string | null
}

interface Snapshot {
  id: string
  captured_at: string
  total_value: number | null
  currency: string
  source: string
}

const fmtEur = (v: number | null | undefined, currency = 'EUR') =>
  v == null ? '–' : new Intl.NumberFormat('de-DE', { style: 'currency', currency }).format(v)
const fmtNum = (v: number | null | undefined, d = 2) =>
  v == null ? '–' : new Intl.NumberFormat('de-DE', { minimumFractionDigits: d, maximumFractionDigits: d }).format(v)
const fmtPct = (v: number | null | undefined) =>
  v == null ? '–' : `${v > 0 ? '+' : ''}${fmtNum(v, 2)} %`

type SortKey = 'name' | 'quantity' | 'avg_buy_price' | 'last_price' | 'last_value' | 'dev' | 'day_change_pct'

function sortValue(p: Position, key: SortKey): number | string {
  switch (key) {
    case 'name': return (p.name || '').toLowerCase()
    case 'dev': return p.avg_buy_price && p.last_price ? (p.last_price - p.avg_buy_price) / p.avg_buy_price : -Infinity
    default: return (p[key] as number | null) ?? -Infinity
  }
}

function SortTh({ label, sortKey, sort, onSort, className = '' }: {
  label: string; sortKey: SortKey; sort: { key: SortKey; dir: 'asc' | 'desc' }; onSort: (k: SortKey) => void; className?: string
}) {
  const active = sort.key === sortKey
  return (
    <th className={`font-medium px-3 py-2 cursor-pointer select-none hover:text-foreground ${className}`} onClick={() => onSort(sortKey)}>
      <span className="inline-flex items-center gap-0.5">
        {label}
        {active && (sort.dir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />)}
      </span>
    </th>
  )
}

export default function DepotPage() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [snapshots, setSnapshots] = useState<Snapshot[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [ocrLoading, setOcrLoading] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [selected, setSelected] = useState<Record<number, boolean>>({})
  const [replaceMissing, setReplaceMissing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editPos, setEditPos] = useState<Position | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [showHtml, setShowHtml] = useState(false)
  const [htmlText, setHtmlText] = useState('')
  const [backfilling, setBackfilling] = useState(false)
  const [deduping, setDeduping] = useState(false)
  const [dupCount, setDupCount] = useState(0)
  const [previewSource, setPreviewSource] = useState<'screenshot' | 'quelltext'>('screenshot')
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>(() => {
    try {
      const s = localStorage.getItem('depotSort')
      if (s) return JSON.parse(s)
    } catch { /* ignore */ }
    return { key: 'last_value', dir: 'desc' }
  })
  const [chartRange, setChartRange] = useState<string>(() => {
    try { return localStorage.getItem('depotChartRange') || '3M' } catch { return '3M' }
  })
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    try { localStorage.setItem('depotSort', JSON.stringify(sort)) } catch { /* ignore */ }
  }, [sort])

  useEffect(() => {
    try { localStorage.setItem('depotChartRange', chartRange) } catch { /* ignore */ }
  }, [chartRange])

  const toggleSort = (key: SortKey) =>
    setSort(s => s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'name' ? 'asc' : 'desc' })

  const load = useCallback(async () => {
    try {
      const [ov, snaps, dups] = await Promise.all([
        api.get<Overview>('/depot/positions'),
        api.get<Snapshot[]>('/depot/snapshots?limit=1500'),
        api.get<{ count: number }>('/depot/duplicates'),
      ])
      setOverview(ov)
      setSnapshots(snaps)
      setDupCount(dups.count)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fehler beim Laden')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleImage = useCallback(async (dataUrl: string) => {
    setError(null)
    setOcrLoading(true)
    setPreviewSource('screenshot')
    try {
      const result = await api.post<Preview>('/depot/import-screenshot', { image: dataUrl })
      setPreview(result)
      const sel: Record<number, boolean> = {}
      result.items.forEach((it, i) => { sel[i] = it.status !== 'unchanged' })
      setSelected(sel)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'OCR fehlgeschlagen')
    } finally {
      setOcrLoading(false)
    }
  }, [])

  const onFile = (file: File | null | undefined) => {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => handleImage(reader.result as string)
    reader.readAsDataURL(file)
  }

  // Clipboard paste
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = Array.from(e.clipboardData?.items || []).find(i => i.type.startsWith('image/'))
      if (item) onFile(item.getAsFile())
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [handleImage])

  const applyImport = async () => {
    if (!preview) return
    const positions = preview.items.filter((_, i) => selected[i]).map(it => it.parsed)
    if (!positions.length) { setPreview(null); return }
    setOcrLoading(true)
    try {
      const ov = await api.post<Overview>('/depot/apply-import', { positions, replace_missing: replaceMissing, source: previewSource })
      setOverview(ov)
      setPreview(null)
      setReplaceMissing(false)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Uebernahme fehlgeschlagen')
    } finally {
      setOcrLoading(false)
    }
  }

  const importHtml = async () => {
    if (!htmlText.trim()) return
    setError(null)
    setOcrLoading(true)
    setPreviewSource('quelltext')
    try {
      const result = await api.post<Preview>('/depot/import-html', { html: htmlText })
      setPreview(result)
      const sel: Record<number, boolean> = {}
      result.items.forEach((it, i) => { sel[i] = it.status !== 'unchanged' })
      setSelected(sel)
      setShowHtml(false)
      setHtmlText('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Quelltext-Import fehlgeschlagen')
    } finally {
      setOcrLoading(false)
    }
  }

  const refreshPrices = async () => {
    setRefreshing(true)
    setError(null)
    try {
      const ov = await api.post<Overview>('/depot/refresh-prices', {})
      setOverview(ov)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Kurs-Update fehlgeschlagen')
    } finally {
      setRefreshing(false)
    }
  }

  const backfill = async () => {
    setBackfilling(true)
    setError(null)
    try {
      await api.post('/depot/backfill-history?days=365', {})
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Verlauf laden fehlgeschlagen')
    } finally {
      setBackfilling(false)
    }
  }

  const runDedupe = async () => {
    setDeduping(true)
    setError(null)
    try {
      await api.post('/depot/dedupe', {})
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Zusammenführen fehlgeschlagen')
    } finally {
      setDeduping(false)
    }
  }

  const deletePos = async (id: string) => {
    if (!confirm('Position wirklich loeschen?')) return
    await api.delete(`/depot/positions/${id}`)
    await load()
  }

  if (loading) return <PageSpinner />

  const totals = overview?.totals
  const positions = overview?.positions || []
  const sortedPositions = [...positions].sort((a, b) => {
    const va = sortValue(a, sort.key), vb = sortValue(b, sort.key)
    const cmp = typeof va === 'string' ? va.localeCompare(vb as string) : (va as number) - (vb as number)
    return sort.dir === 'asc' ? cmp : -cmp
  })
  // Pro Kalendertag nur den letzten Snapshot (sonst erscheint "heute" mehrfach)
  const byDay = new Map<string, { iso: string; t: string; v: number | null }>()
  for (const s of snapshots) {
    if (s.total_value == null) continue
    const d = new Date(s.captured_at)
    const iso = d.toISOString().slice(0, 10)
    byDay.set(iso, {
      iso,
      t: d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' }),
      v: s.total_value,
    })
  }
  const allChart = Array.from(byDay.values()).sort((a, b) => a.iso.localeCompare(b.iso))
  const RANGES = [{ k: '1M', d: 30 }, { k: '3M', d: 90 }, { k: '6M', d: 180 }, { k: '1J', d: 365 }, { k: 'Max', d: 0 }]
  const rangeDays = RANGES.find(r => r.k === chartRange)?.d ?? 90
  const cutoff = rangeDays ? Date.now() - rangeDays * 86400000 : 0
  const chartData = allChart.filter(p => !cutoff || new Date(p.iso).getTime() >= cutoff)
  const dayUp = (totals?.day_change_value || 0) >= 0

  return (
    <div className="p-4 md:p-6 space-y-6 pb-20 md:pb-6">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h1 className="text-xl font-semibold flex items-center gap-2 min-w-0">
          <Wallet className="w-5 h-5 shrink-0" /> Depot
        </h1>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => fileRef.current?.click()} disabled={ocrLoading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50">
            {ocrLoading ? <Spinner className="w-4 h-4" /> : <Upload className="w-4 h-4" />} Screenshot
          </button>
          <button onClick={() => setShowHtml(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-secondary hover:bg-secondary/80">
            <Code className="w-4 h-4" /> Quelltext
          </button>
          <button onClick={refreshPrices} disabled={refreshing}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-secondary hover:bg-secondary/80 disabled:opacity-50">
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} /> Kurse
          </button>
          <button onClick={backfill} disabled={backfilling}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-secondary hover:bg-secondary/80 disabled:opacity-50"
            title="Historischen Wertverlauf aus Marktdaten laden (mit aktuellen Stückzahlen)">
            <History className={`w-4 h-4 ${backfilling ? 'animate-pulse' : ''}`} /> Verlauf
          </button>
          <button onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg bg-secondary hover:bg-secondary/80">
            <Plus className="w-4 h-4" /> Position
          </button>
        </div>
        <input ref={fileRef} type="file" accept="image/*" className="hidden"
          onChange={e => { onFile(e.target.files?.[0]); e.target.value = '' }} />
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertTriangle className="w-4 h-4 shrink-0" /> <span className="min-w-0">{error}</span>
        </div>
      )}

      {dupCount > 0 && (
        <div className="flex items-center justify-between gap-2 text-sm text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          <span className="min-w-0 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            {dupCount} mögliche {dupCount === 1 ? 'Dublette' : 'Dubletten'} erkannt.
          </span>
          <button onClick={runDedupe} disabled={deduping}
            className="shrink-0 px-3 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 disabled:opacity-50">
            {deduping ? 'Führe zusammen…' : 'Zusammenführen'}
          </button>
        </div>
      )}

      {/* Hero */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-card border border-border rounded-xl p-4 col-span-2">
          <div className="text-xs text-muted-foreground">Depotwert</div>
          <div className="text-2xl font-semibold mt-1">{fmtEur(totals?.total_value, totals?.currency)}</div>
          <div className={`text-sm mt-1 flex items-center gap-1 ${dayUp ? 'text-green-400' : 'text-red-400'}`}>
            {dayUp ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            {fmtEur(totals?.day_change_value, totals?.currency)} heute
          </div>
        </div>
        <div className="bg-card border border-border rounded-xl p-4">
          <div className="text-xs text-muted-foreground">Gewinn/Verlust</div>
          <div className={`text-lg font-semibold mt-1 ${(totals?.total_gain || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {totals?.total_gain == null ? '–' : fmtEur(totals.total_gain, totals.currency)}
          </div>
          <div className="text-sm text-muted-foreground mt-1">{fmtPct(totals?.total_gain_pct)}</div>
        </div>
        <div className="bg-card border border-border rounded-xl p-4">
          <div className="text-xs text-muted-foreground">Positionen</div>
          <div className="text-lg font-semibold mt-1">{totals?.position_count ?? 0}</div>
          <div className="text-xs text-muted-foreground mt-1">
            {totals?.last_update ? `Stand ${new Date(totals.last_update).toLocaleString('de-DE')}` : 'kein Stand'}
          </div>
        </div>
      </div>

      {totals?.has_stale_prices && (
        <div className="text-xs text-amber-400 flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5" /> Für einige Positionen konnten keine Live-Kurse geladen werden – es gilt der zuletzt erfasste Wert.
        </div>
      )}

      {/* Chart */}
      {allChart.length > 1 && (
        <div className="bg-card border border-border rounded-xl p-4">
          <div className="flex items-center justify-between gap-2 mb-3">
            <div className="text-sm font-medium">Wertverlauf</div>
            <div className="flex items-center gap-0.5 bg-secondary rounded-lg p-0.5">
              {RANGES.map(r => (
                <button key={r.k} onClick={() => setChartRange(r.k)}
                  className={`px-2 py-0.5 text-xs rounded-md transition-colors ${chartRange === r.k ? 'bg-card shadow text-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                  {r.k}
                </button>
              ))}
            </div>
          </div>
          {chartData.length > 1 ? (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="depotGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366f1" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="hsl(222 40% 18%)" vertical={false} />
              <XAxis dataKey="t" stroke="hsl(215 20% 55%)" fontSize={11} tickLine={false} />
              <YAxis stroke="hsl(215 20% 55%)" fontSize={11} tickLine={false} width={50}
                tickFormatter={(v) => new Intl.NumberFormat('de-DE', { notation: 'compact' }).format(v)} />
              <Tooltip
                contentStyle={{ background: 'hsl(222 44% 11%)', border: '1px solid hsl(222 40% 18%)', borderRadius: 8, fontSize: 12 }}
                formatter={(v) => [fmtEur(Number(v), totals?.currency), 'Wert'] as [string, string]} />
              <Area type="monotone" dataKey="v" stroke="#6366f1" strokeWidth={2} fill="url(#depotGrad)" />
            </AreaChart>
          </ResponsiveContainer>
          ) : (
            <div className="h-[200px] flex items-center justify-center text-sm text-muted-foreground text-center px-4">
              Für diesen Zeitraum liegen zu wenig Datenpunkte vor. Wähle einen größeren Zeitraum oder lade den Verlauf.
            </div>
          )}
        </div>
      )}

      {/* Positions */}
      {positions.length === 0 ? (
        <EmptyState icon={Wallet} title="Noch keine Positionen"
          description="Lade einen Screenshot deiner Depotübersicht hoch oder füge Positionen manuell hinzu." />
      ) : (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground border-b border-border">
                <tr>
                  <SortTh label="Wertpapier" sortKey="name" sort={sort} onSort={toggleSort} className="text-left" />
                  <SortTh label="Stück" sortKey="quantity" sort={sort} onSort={toggleSort} className="text-right [&>span]:flex-row-reverse" />
                  <SortTh label="Kaufkurs" sortKey="avg_buy_price" sort={sort} onSort={toggleSort} className="text-right hidden sm:table-cell [&>span]:flex-row-reverse" />
                  <SortTh label="Kurs" sortKey="last_price" sort={sort} onSort={toggleSort} className="text-right hidden md:table-cell [&>span]:flex-row-reverse" />
                  <SortTh label="Wert" sortKey="last_value" sort={sort} onSort={toggleSort} className="text-right [&>span]:flex-row-reverse" />
                  <SortTh label="± seit Kauf" sortKey="dev" sort={sort} onSort={toggleSort} className="text-right [&>span]:flex-row-reverse" />
                  <SortTh label="Δ Tag" sortKey="day_change_pct" sort={sort} onSort={toggleSort} className="text-right hidden lg:table-cell [&>span]:flex-row-reverse" />
                  <th className="text-right font-medium px-3 py-2 w-16"></th>
                </tr>
              </thead>
              <tbody>
                {sortedPositions.map(p => {
                  const devPct = p.avg_buy_price && p.last_price ? (p.last_price - p.avg_buy_price) / p.avg_buy_price * 100 : null
                  const devAbs = p.avg_buy_price != null && p.last_price != null && p.quantity != null
                    ? (p.last_price - p.avg_buy_price) * p.quantity : null
                  return (
                  <tr key={p.id} className="border-b border-border/50 last:border-0">
                    <td className="px-3 py-2 min-w-0">
                      <div className="font-medium truncate max-w-[40vw] md:max-w-xs">{p.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {p.isin || p.wkn || '—'}{p.price_stale && <span className="text-amber-400"> · Kurs veraltet</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{fmtNum(p.quantity, p.quantity % 1 === 0 ? 0 : 4)}</td>
                    <td className="px-3 py-2 text-right tabular-nums hidden sm:table-cell text-muted-foreground">{fmtEur(p.avg_buy_price, p.currency)}</td>
                    <td className="px-3 py-2 text-right tabular-nums hidden md:table-cell">{fmtEur(p.last_price, p.currency)}</td>
                    <td className="px-3 py-2 text-right tabular-nums font-medium">{fmtEur(p.last_value, p.currency)}</td>
                    <td className={`px-3 py-2 text-right tabular-nums ${(devPct || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      <div>{fmtPct(devPct)}</div>
                      {devAbs != null && <div className="text-xs opacity-80">{devAbs > 0 ? '+' : ''}{fmtEur(devAbs, p.currency)}</div>}
                    </td>
                    <td className={`px-3 py-2 text-right tabular-nums hidden lg:table-cell ${(p.day_change_pct || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {fmtPct(p.day_change_pct)}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <button onClick={() => setEditPos(p)} className="text-muted-foreground hover:text-foreground p-1"><Pencil className="w-3.5 h-3.5" /></button>
                      <button onClick={() => deletePos(p.id)} className="text-muted-foreground hover:text-red-400 p-1"><Trash2 className="w-3.5 h-3.5" /></button>
                    </td>
                  </tr>
                )})}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Preview modal */}
      {preview && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-end md:items-center justify-center p-0 md:p-4" onClick={() => setPreview(null)}>
          <div className="bg-card border border-border rounded-t-2xl md:rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <div className="font-medium">Erkannte Positionen prüfen</div>
              <button onClick={() => setPreview(null)}><X className="w-5 h-5" /></button>
            </div>
            <div className="px-4 py-2 text-xs text-muted-foreground flex items-center justify-between flex-wrap gap-1">
              <span>{preview.items.length} erkannt · Modell: {preview.model_used || '–'}</span>
              {preview.parsed_total_value != null && <span>Summe lt. Screenshot: {fmtEur(preview.parsed_total_value)}</span>}
            </div>
            {preview.warning && (
              <div className="mx-4 mb-2 text-xs text-amber-400 flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" /> {preview.warning}
              </div>
            )}
            <div className="overflow-y-auto flex-1 px-2">
              {preview.items.map((it, i) => (
                <label key={i} className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-secondary/50 cursor-pointer">
                  <input type="checkbox" checked={!!selected[i]}
                    onChange={e => setSelected(s => ({ ...s, [i]: e.target.checked }))} className="shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium truncate">{it.parsed.name || '(ohne Namen)'}</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {it.parsed.isin || it.parsed.wkn || '—'} · {fmtNum(it.parsed.quantity, 4)} Stück · {fmtEur(it.parsed.last_value)}
                    </div>
                  </div>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${
                    it.status === 'new' ? 'bg-green-500/15 text-green-400' :
                    it.status === 'update' ? 'bg-blue-500/15 text-blue-400' :
                    'bg-secondary text-muted-foreground'}`}>
                    {it.status === 'new' ? 'neu' : it.status === 'update' ? 'Update' : 'unverändert'}
                  </span>
                </label>
              ))}
            </div>
            <div className="px-4 py-3 border-t border-border space-y-2">
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input type="checkbox" checked={replaceMissing} onChange={e => setReplaceMissing(e.target.checked)} />
                Nicht erkannte Bestandspositionen deaktivieren (Komplettabgleich)
              </label>
              <div className="flex gap-2">
                <button onClick={applyImport} disabled={ocrLoading}
                  className="flex-1 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50">
                  {ocrLoading ? 'Übernehme…' : 'Auswahl übernehmen'}
                </button>
                <button onClick={() => setPreview(null)} className="px-4 py-2 text-sm rounded-lg bg-secondary hover:bg-secondary/80">Abbrechen</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {showHtml && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-end md:items-center justify-center p-0 md:p-4" onClick={() => setShowHtml(false)}>
          <div className="bg-card border border-border rounded-t-2xl md:rounded-2xl w-full max-w-2xl p-4 space-y-3" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <div className="font-medium">Quelltext der ING-Depotübersicht einfügen</div>
              <button onClick={() => setShowHtml(false)}><X className="w-5 h-5" /></button>
            </div>
            <p className="text-xs text-muted-foreground">
              ING-Depotübersicht öffnen → Rechtsklick → „Seitenquelltext anzeigen" → alles markieren (Strg+A), kopieren (Strg+C) und hier einfügen.
              Enthält ISINs, Stück, Kurs und Einstandskurs — am genauesten.
            </p>
            <textarea value={htmlText} onChange={e => setHtmlText(e.target.value)}
              placeholder="<!DOCTYPE HTML> …"
              className="w-full h-40 px-3 py-2 text-xs font-mono rounded-lg bg-secondary border border-border focus:outline-none focus:ring-1 focus:ring-primary resize-none" />
            <div className="flex gap-2">
              <button onClick={importHtml} disabled={ocrLoading || !htmlText.trim()}
                className="flex-1 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50">
                {ocrLoading ? 'Analysiere…' : 'Auslesen'}
              </button>
              <button onClick={() => setShowHtml(false)} className="px-4 py-2 text-sm rounded-lg bg-secondary hover:bg-secondary/80">Abbrechen</button>
            </div>
          </div>
        </div>
      )}

      {(editPos || showAdd) && (
        <PositionForm
          position={editPos}
          onClose={() => { setEditPos(null); setShowAdd(false) }}
          onSaved={async () => { setEditPos(null); setShowAdd(false); await load() }}
        />
      )}
    </div>
  )
}

function PositionForm({ position, onClose, onSaved }: { position: Position | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(position?.name || '')
  const [isin, setIsin] = useState(position?.isin || '')
  const [quantity, setQuantity] = useState(position?.quantity?.toString() || '')
  const [price, setPrice] = useState(position?.last_price?.toString() || '')
  const [avg, setAvg] = useState(position?.avg_buy_price?.toString() || '')
  const [saving, setSaving] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      const body = {
        name,
        isin: isin || null,
        quantity: quantity ? parseFloat(quantity.replace(',', '.')) : 0,
        last_price: price ? parseFloat(price.replace(',', '.')) : null,
        avg_buy_price: avg ? parseFloat(avg.replace(',', '.')) : null,
      }
      if (position) await api.put(`/depot/positions/${position.id}`, body)
      else await api.post('/depot/positions', body)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-end md:items-center justify-center p-0 md:p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-t-2xl md:rounded-2xl w-full max-w-md p-4 space-y-3" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div className="font-medium">{position ? 'Position bearbeiten' : 'Position hinzufügen'}</div>
          <button onClick={onClose}><X className="w-5 h-5" /></button>
        </div>
        {[
          { label: 'Name', val: name, set: setName, ph: 'z.B. iShares Core MSCI World' },
          { label: 'ISIN', val: isin, set: setIsin, ph: 'IE00B4L5Y983' },
          { label: 'Stückzahl', val: quantity, set: setQuantity, ph: '12,5' },
          { label: 'Aktueller Kurs', val: price, set: setPrice, ph: '95,40' },
          { label: 'Ø Kaufkurs (optional)', val: avg, set: setAvg, ph: '80,00' },
        ].map(f => (
          <div key={f.label}>
            <label className="text-xs text-muted-foreground">{f.label}</label>
            <input value={f.val} onChange={e => f.set(e.target.value)} placeholder={f.ph}
              className="w-full mt-1 px-3 py-2 text-sm rounded-lg bg-secondary border border-border focus:outline-none focus:ring-1 focus:ring-primary" />
          </div>
        ))}
        <button onClick={save} disabled={saving || !name}
          className="w-full py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50">
          {saving ? 'Speichere…' : 'Speichern'}
        </button>
      </div>
    </div>
  )
}
