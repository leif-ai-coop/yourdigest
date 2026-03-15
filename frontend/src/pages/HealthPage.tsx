import { useEffect, useState, useMemo, useCallback, useRef } from 'react'
import { api } from '../api/client'
import { PageSpinner } from '../components/Spinner'
import { EmptyState } from '../components/EmptyState'
import {
  Heart, Battery, Moon, Footprints, Brain, Activity,
  Wind, Weight, Layers, Flame, Gauge, Settings, RefreshCw, GripVertical
} from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Legend, ComposedChart
} from 'recharts'
import type { LucideIcon } from 'lucide-react'

// -- Theme colors for recharts (dark theme) --
const CHART_COLORS = {
  grid: 'hsl(222 40% 18%)',
  axis: 'hsl(215 20% 55%)',
  tooltip_bg: 'hsl(222 44% 11%)',
  tooltip_border: 'hsl(222 40% 18%)',
  green: '#22c55e',
  red: '#ef4444',
  blue: '#3b82f6',
  indigo: '#6366f1',
  purple: '#a855f7',
  orange: '#f97316',
  cyan: '#06b6d4',
  gray: '#9ca3af',
  teal: '#14b8a6',
  yellow: '#eab308',
  amber: '#f59e0b',
}

interface GarminSnapshot {
  date: string
  data: Record<string, any>
}

interface GarminData {
  stats: GarminSnapshot[]
  sleep: GarminSnapshot[]
  heart_rate: GarminSnapshot[]
  body_battery: GarminSnapshot[]
  stress: GarminSnapshot[]
  steps: GarminSnapshot[]
  hrv: GarminSnapshot[]
  spo2: GarminSnapshot[]
  weight: GarminSnapshot[]
  activities: GarminSnapshot[]
  floors: GarminSnapshot[]
  intensity_minutes: GarminSnapshot[]
  training_readiness: GarminSnapshot[]
}

type TimeRange = 'today' | '7d' | '30d' | '90d'

function getDateRange(range: TimeRange): { start: string; end: string } {
  const end = new Date()
  const start = new Date()
  switch (range) {
    case 'today': break
    case '7d': start.setDate(start.getDate() - 7); break
    case '30d': start.setDate(start.getDate() - 30); break
    case '90d': start.setDate(start.getDate() - 90); break
  }
  return {
    start: start.toISOString().split('T')[0],
    end: end.toISOString().split('T')[0],
  }
}

function formatDateShort(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
}

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function formatDistance(meters: number): string {
  if (meters >= 1000) return `${(meters / 1000).toFixed(1)} km`
  return `${Math.round(meters)} m`
}

// Custom tooltip for dark theme
function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div
      className="rounded-lg border px-3 py-2 text-xs shadow-lg"
      style={{
        backgroundColor: CHART_COLORS.tooltip_bg,
        borderColor: CHART_COLORS.tooltip_border,
      }}
    >
      <p className="text-muted-foreground mb-1">{label}</p>
      {payload.map((p: any, i: number) => (
        <p key={i} style={{ color: p.color || p.fill }}>
          {p.name}: <span className="font-medium">{typeof p.value === 'number' ? p.value.toFixed(1) : p.value}</span>
        </p>
      ))}
    </div>
  )
}

// Card wrapper with drag support
function DashboardCard({
  title, icon: Icon, children, cardId, dragging, onDragStart, onDragOver, onDrop, onDragEnd,
}: {
  title: string; icon: LucideIcon; children: React.ReactNode
  cardId: string; dragging: string | null
  onDragStart: (id: string) => void; onDragOver: (e: React.DragEvent, id: string) => void
  onDrop: (id: string) => void; onDragEnd: () => void
}) {
  return (
    <div
      className={`bg-card border rounded-lg p-4 transition-opacity ${dragging === cardId ? 'opacity-40 border-primary' : 'border-border'}`}
      onDragOver={(e) => { e.preventDefault(); onDragOver(e, cardId) }}
      onDrop={() => onDrop(cardId)}
    >
      <div className="flex items-center gap-2 mb-3">
        <div
          draggable
          onDragStart={() => onDragStart(cardId)}
          onDragEnd={onDragEnd}
          className="cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground transition-colors"
          title="Drag to reorder"
        >
          <GripVertical className="w-4 h-4" />
        </div>
        <Icon className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
      </div>
      {children}
    </div>
  )
}

const STORAGE_KEY = 'health-card-order'
const DEFAULT_CARD_ORDER = [
  'body-battery', 'heart-rate', 'sleep', 'steps', 'stress', 'sleep-stress', 'hrv',
  'spo2', 'weight', 'floors', 'training-load', 'fitness-age', 'vo2max',
  'intensity', 'activities',
]

function loadCardOrder(): string[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored) as string[]
      // Merge: keep stored order, append any new cards not in stored
      const merged = parsed.filter(id => DEFAULT_CARD_ORDER.includes(id))
      for (const id of DEFAULT_CARD_ORDER) {
        if (!merged.includes(id)) merged.push(id)
      }
      return merged
    }
  } catch { /* ignore */ }
  return [...DEFAULT_CARD_ORDER]
}

function saveCardOrder(order: string[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(order))
}

export default function HealthPage() {
  const [range, setRange] = useState<TimeRange>('7d')
  const [data, setData] = useState<GarminData | null>(null)
  const [loading, setLoading] = useState(true)
  const [hasAccount, setHasAccount] = useState<boolean | null>(null)
  const [syncing, setSyncing] = useState(false)

  const [lastSyncAt, setLastSyncAt] = useState<string | null>(null)
  const [cardOrder, setCardOrder] = useState<string[]>(loadCardOrder)
  const [draggingCard, setDraggingCard] = useState<string | null>(null)
  const dragOverCard = useRef<string | null>(null)

  const handleDragStart = useCallback((id: string) => setDraggingCard(id), [])
  const handleDragOver = useCallback((_e: React.DragEvent, id: string) => { dragOverCard.current = id }, [])
  const handleDrop = useCallback((targetId: string) => {
    if (!draggingCard || draggingCard === targetId) return
    setCardOrder(prev => {
      const next = [...prev]
      const fromIdx = next.indexOf(draggingCard)
      const toIdx = next.indexOf(targetId)
      if (fromIdx === -1 || toIdx === -1) return prev
      next.splice(fromIdx, 1)
      next.splice(toIdx, 0, draggingCard)
      saveCardOrder(next)
      return next
    })
    setDraggingCard(null)
  }, [draggingCard])
  const handleDragEnd = useCallback(() => setDraggingCard(null), [])

  useEffect(() => {
    api.get<any>('/garmin/account')
      .then((acc) => {
        setHasAccount(true)
        setLastSyncAt(acc.last_sync_at || null)
      })
      .catch(() => {
        setHasAccount(false)
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    if (hasAccount !== true) return
    setLoading(true)
    const { start, end } = getDateRange(range)
    api.get<GarminData>(`/garmin/data?start_date=${start}&end_date=${end}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [range, hasAccount])

  if (hasAccount === false) {
    return (
      <div>
        <div className="flex items-center gap-3 mb-6">
          <Heart className="w-5 h-5 text-primary" />
          <h1 className="text-xl font-semibold">Health</h1>
        </div>
        <EmptyState
          icon={Heart}
          title="No Garmin account configured"
          description="Connect your Garmin account in Settings to view health data."
        />
        <div className="flex justify-center mt-4">
          <Link
            to="/settings"
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors"
          >
            <Settings className="w-3.5 h-3.5" />
            Go to Settings
          </Link>
        </div>
      </div>
    )
  }

  // -- Data extraction (hooks must be before any early return) --
  const bodyBatteryData = useMemo(() => {
    if (!data?.body_battery) return []
    return data.body_battery.map(s => {
      // data is a list with one item, or a dict directly
      const d = Array.isArray(s.data) ? s.data[0] : s.data
      if (!d) return { date: formatDateShort(s.date), value: 0 }
      // Try bodyBatteryValuesArray for max value
      const vals = d.bodyBatteryValuesArray
      let max = 0
      if (Array.isArray(vals)) {
        for (const v of vals) {
          const val = Array.isArray(v) ? v[1] : v
          if (typeof val === 'number' && val > max) max = val
        }
      }
      if (max === 0) max = d.charged || 0
      return { date: formatDateShort(s.date), value: max }
    })
  }, [data?.body_battery])

  const heartRateData = useMemo(() => {
    if (!data?.heart_rate) return []
    return data.heart_rate.map(s => ({
      date: formatDateShort(s.date),
      resting: s.data?.restingHeartRate || 0,
      max: s.data?.maxHeartRate || 0,
    }))
  }, [data?.heart_rate])

  const sleepData = useMemo(() => {
    if (!data?.sleep) return []
    return data.sleep.map(s => {
      const d = s.data?.dailySleepDTO || s.data || {}
      return {
        date: formatDateShort(s.date),
        deep: (d.deepSleepSeconds || 0) / 3600,
        light: (d.lightSleepSeconds || 0) / 3600,
        rem: (d.remSleepSeconds || 0) / 3600,
        awake: (d.awakeSleepSeconds || 0) / 3600,
      }
    })
  }, [data?.sleep])

  const stepsData = useMemo(() => {
    // Steps from stats (totalSteps is there), steps data_type is intraday granularity
    if (!data?.stats) return []
    return data.stats.map(s => ({
      date: formatDateShort(s.date),
      steps: s.data?.totalSteps || 0,
      goal: s.data?.dailyStepGoal || s.data?.totalStepsGoal || 0,
    }))
  }, [data?.stats])

  const stressData = useMemo(() => {
    if (!data?.stress) return []
    return data.stress.map(s => ({
      date: formatDateShort(s.date),
      average: s.data?.avgStressLevel || 0,
      max: s.data?.maxStressLevel || 0,
    }))
  }, [data?.stress])

  const sleepStressData = useMemo(() => {
    if (!data?.stress || !data?.sleep) return []
    // Build a map of sleep start/end per date
    const sleepTimes: Record<string, { start: number; end: number }> = {}
    for (const s of data.sleep) {
      const dto = s.data?.dailySleepDTO || s.data || {}
      const start = dto.sleepStartTimestampGMT
      const end = dto.sleepEndTimestampGMT
      if (start && end) sleepTimes[s.date] = { start, end }
    }
    return data.stress.map(s => {
      const sleepWindow = sleepTimes[s.date]
      const stressVals: number[][] = s.data?.stressValuesArray || []
      let avg = 0
      if (sleepWindow && stressVals.length > 0) {
        const sleepVals = stressVals.filter(
          ([ts, val]) => ts >= sleepWindow.start && ts <= sleepWindow.end && val > 0
        )
        if (sleepVals.length > 0) {
          avg = Math.round(sleepVals.reduce((sum, [, v]) => sum + v, 0) / sleepVals.length)
        }
      }
      return { date: formatDateShort(s.date), sleepStress: avg }
    }).filter(d => d.sleepStress > 0)
  }, [data?.stress, data?.sleep])

  const hrvData = useMemo(() => {
    if (!data?.hrv) return []
    return data.hrv.map(s => {
      const summary = s.data?.hrvSummary || {}
      const baseline = summary.baseline || {}
      return {
        date: formatDateShort(s.date),
        hrv: summary.lastNightAvg || summary.weeklyAvg || 0,
        balancedLow: baseline.balancedLow || null,
        balancedUpper: baseline.balancedUpper || null,
        status: summary.status || null,
      }
    })
  }, [data?.hrv])

  const spo2Data = useMemo(() => {
    if (!data?.spo2) return []
    return data.spo2.map(s => ({
      date: formatDateShort(s.date),
      spo2: s.data?.averageSpO2 || s.data?.latestSpO2 || 0,
    })).filter(d => d.spo2 > 0)
  }, [data?.spo2])

  const weightData = useMemo(() => {
    if (!data?.weight) return []
    return data.weight.map(s => {
      const wl = s.data?.dateWeightList || []
      const entry = wl[0] || {}
      let w = entry.weight || s.data?.totalAverage?.weight || 0
      if (w > 1000) w = w / 1000 // grams to kg
      return {
        date: formatDateShort(s.date),
        weight: parseFloat(w.toFixed(1)),
      }
    }).filter(d => d.weight > 0)
  }, [data?.weight])

  const floorsData = useMemo(() => {
    // Use stats for daily floor totals
    if (!data?.stats) return []
    return data.stats.map(s => ({
      date: formatDateShort(s.date),
      floors: Math.round(s.data?.floorsAscended || 0),
    }))
  }, [data?.stats])

  const activitiesData = useMemo(() => {
    if (!data?.activities) return []
    const items: any[] = []
    for (const s of data.activities) {
      const acts = Array.isArray(s.data) ? s.data : s.data?.ActivitiesForDay?.payload || []
      for (const a of acts) items.push({ ...a, _date: s.date })
    }
    return items.slice(0, 20)
  }, [data?.activities])

  const { trainingLoadData, acuteLoad, optimalLow, optimalHigh, highThreshold } = useMemo(() => {
    if (!data?.activities) return { trainingLoadData: [], acuteLoad: 0, optimalLow: 0, optimalHigh: 0, highThreshold: 0 }

    // Get VO2max from maxmet data — use the highest value across running/cycling
    let vo2max = 50
    const maxmetEntries = (data as any)?.maxmet as GarminSnapshot[] | undefined
    if (maxmetEntries?.length) {
      for (const s of maxmetEntries) {
        const entries = Array.isArray(s.data) ? s.data : [s.data]
        for (const e of entries) {
          if (!e) continue
          for (const src of [e.generic, e.cycling]) {
            const v = src?.vo2MaxPreciseValue || src?.vo2MaxValue
            if (v && v > vo2max) vo2max = Math.round(v)
          }
        }
      }
    }

    // Build daily loads
    const dailyLoads: Record<string, number> = {}
    for (const s of data.activities) {
      const acts = Array.isArray(s.data) ? s.data : s.data?.ActivitiesForDay?.payload || []
      let dayLoad = 0
      for (const a of acts) dayLoad += a.activityTrainingLoad || 0
      dailyLoads[s.date] = dayLoad
    }

    // Fill in missing days with 0 load (important for EWMA decay)
    const allDates = Object.keys(dailyLoads).sort()
    if (allDates.length === 0) return { trainingLoadData: [], acuteLoad: 0, optimalLow: 0, optimalHigh: 0, highThreshold: 0 }
    // Use local date to ensure today is included
    const now = new Date()
    const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    const startD = new Date(allDates[0] + 'T00:00:00')
    const endD = new Date(todayStr + 'T00:00:00')
    const dates: string[] = []
    for (let d = new Date(startD); d <= endD; d.setDate(d.getDate() + 1)) {
      const y = d.getFullYear()
      const m = String(d.getMonth() + 1).padStart(2, '0')
      const day = String(d.getDate()).padStart(2, '0')
      const iso = `${y}-${m}-${day}`
      dates.push(iso)
      if (!(iso in dailyLoads)) dailyLoads[iso] = 0
    }

    // VO2max-based optimal range (Garmin formula: center = VO2max * 5, ±30%)
    const optCenter = vo2max * 5
    const oLow = Math.round(optCenter * 0.7)
    const oHigh = Math.round(optCenter * 1.3)
    const hThreshold = Math.round(optCenter * 1.7)

    // Calculate EWMA-based acute load per day
    const alpha7 = 2 / (7 + 1)
    let ewma7 = 0
    const chartData = dates.map(d => {
      const v = dailyLoads[d] || 0
      ewma7 = alpha7 * v + (1 - alpha7) * ewma7
      const acute = Math.round(ewma7 * 7.5)
      return {
        date: formatDateShort(d),
        load: Math.round(v),
        acute,
        optLow: oLow,
        optHigh: oHigh,
      }
    })

    const latest = chartData[chartData.length - 1]
    return {
      trainingLoadData: chartData,
      acuteLoad: latest?.acute || 0,
      optimalLow: oLow,
      optimalHigh: oHigh,
      highThreshold: hThreshold,
    }
  }, [data?.activities, (data as any)?.fitnessage])

  const vo2maxData = useMemo(() => {
    const maxmet = (data as any)?.maxmet as GarminSnapshot[] | undefined
    if (!maxmet) return { points: [] as { date: string; running: number | null; cycling: number | null }[], latestRunning: 0, latestCycling: 0 }
    let latestRunning = 0, latestCycling = 0
    const points = maxmet
      .filter(s => Array.isArray(s.data) && s.data.length > 0)
      .map(s => {
        const entry = s.data[0]
        const running = entry?.generic?.vo2MaxPreciseValue || entry?.generic?.vo2MaxValue || null
        const cycling = entry?.cycling?.vo2MaxPreciseValue || entry?.cycling?.vo2MaxValue || null
        if (running) latestRunning = running
        if (cycling) latestCycling = cycling
        return { date: formatDateShort(s.date), running, cycling }
      })
      .filter(d => d.running || d.cycling)
    return { points, latestRunning, latestCycling }
  }, [(data as any)?.maxmet])

  const fitnessAgeData = useMemo(() => {
    if (!(data as any)?.fitnessage) return null
    const items = (data as any).fitnessage as GarminSnapshot[]
    const latest = items[items.length - 1]
    if (!latest?.data) return null
    return {
      fitnessAge: Math.round(latest.data.fitnessAge || 0),
      chronologicalAge: latest.data.chronologicalAge || 0,
      components: latest.data.components || {},
    }
  }, [(data as any)?.fitnessage])

  const { intensityData, intensityWeekKeys } = useMemo(() => {
    if (!data?.intensity_minutes) return { intensityData: [], intensityWeekKeys: [] as string[] }
    // Group into weeks, each week gets its own data key (w0, w1, ...)
    let weekIdx = 0
    const weekKeys: string[] = ['w0']
    const result: Record<string, any>[] = []
    for (let i = 0; i < data.intensity_minutes.length; i++) {
      const s = data.intensity_minutes[i]
      const d = new Date(s.date + 'T00:00:00')
      if (d.getDay() === 1 && i > 0) {
        weekIdx++
        weekKeys.push(`w${weekIdx}`)
      }
      const point: Record<string, any> = {
        date: formatDateShort(s.date),
        goal: s.data?.weekGoal || 150,
      }
      point[`w${weekIdx}`] = s.data?.endDayMinutes || 0
      result.push(point)
    }
    return { intensityData: result, intensityWeekKeys: weekKeys }
  }, [data?.intensity_minutes])

  if (loading) return <PageSpinner />

  const ranges: { key: TimeRange; label: string }[] = [
    { key: 'today', label: 'Today' },
    { key: '7d', label: '7 Days' },
    { key: '30d', label: '30 Days' },
    { key: '90d', label: '90 Days' },
  ]

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Heart className="w-5 h-5 text-primary" />
          <h1 className="text-xl font-semibold">Health</h1>
          {lastSyncAt && (
            <span className="text-xs text-muted-foreground ml-2">
              Last sync: {new Date(lastSyncAt).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
        {/* Sync Button */}
        <button
          onClick={async () => {
            setSyncing(true)
            try {
              const rangeDays = range === 'today' ? 1 : range === '7d' ? 7 : range === '30d' ? 30 : 90
              await api.post('/garmin/sync', { days: rangeDays })
              const [fresh, acc] = await Promise.all([
                api.get<GarminData>(`/garmin/data?start_date=${getDateRange(range).start}&end_date=${getDateRange(range).end}`),
                api.get<any>('/garmin/account'),
              ])
              setData(fresh)
              setLastSyncAt(acc.last_sync_at || null)
            } catch (e: any) {
              alert(`Sync failed: ${e.message}`)
            } finally {
              setSyncing(false)
            }
          }}
          disabled={syncing}
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
          title="Sync Garmin data"
        >
          <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
        </button>

        {/* Time Range Picker */}
        <div className="flex gap-1 bg-card rounded-lg p-1">
          {ranges.map(r => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                range === r.key
                  ? 'bg-primary/15 text-primary font-medium'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
        </div>
      </div>

      {/* Dashboard Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {cardOrder.map(cardId => {
          const cp = { cardId, dragging: draggingCard, onDragStart: handleDragStart, onDragOver: handleDragOver, onDrop: handleDrop, onDragEnd: handleDragEnd }
          switch (cardId) {

          case 'body-battery': return (
            <DashboardCard key={cardId} title="Body Battery" icon={Battery} {...cp}>
              {bodyBatteryData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={bodyBatteryData}>
                    <defs>
                      <linearGradient id="bbGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={CHART_COLORS.green} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={CHART_COLORS.green} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                    <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <YAxis domain={[0, 100]} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <Tooltip content={<ChartTooltip />} />
                    <Area type="monotone" dataKey="value" name="Battery" stroke={CHART_COLORS.green} fill="url(#bbGrad)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'heart-rate': return (
            <DashboardCard key={cardId} title="Heart Rate" icon={Heart} {...cp}>
              {heartRateData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={heartRateData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                    <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <Tooltip content={<ChartTooltip />} />
                    <Line type="monotone" dataKey="resting" name="Resting HR" stroke={CHART_COLORS.red} strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="max" name="Max HR" stroke={CHART_COLORS.orange} strokeWidth={1.5} dot={false} strokeDasharray="4 4" />
                    <Legend wrapperStyle={{ fontSize: 11, color: CHART_COLORS.axis }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'sleep': return (
            <DashboardCard key={cardId} title="Sleep" icon={Moon} {...cp}>
              {sleepData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={sleepData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                    <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} unit="h" />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="deep" name="Deep" stackId="sleep" fill={CHART_COLORS.indigo} radius={[0, 0, 0, 0]} />
                    <Bar dataKey="light" name="Light" stackId="sleep" fill={CHART_COLORS.blue} />
                    <Bar dataKey="rem" name="REM" stackId="sleep" fill={CHART_COLORS.purple} />
                    <Bar dataKey="awake" name="Awake" stackId="sleep" fill={CHART_COLORS.orange} radius={[2, 2, 0, 0]} />
                    <Legend wrapperStyle={{ fontSize: 11, color: CHART_COLORS.axis }} />
                  </BarChart>
                </ResponsiveContainer>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'steps': return (
            <DashboardCard key={cardId} title="Steps" icon={Footprints} {...cp}>
              {stepsData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={stepsData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                    <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="steps" name="Steps" fill={CHART_COLORS.blue} radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'stress': return (
            <DashboardCard key={cardId} title="Stress" icon={Brain} {...cp}>
              {stressData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={stressData}>
                    <defs>
                      <linearGradient id="stressGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={CHART_COLORS.orange} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={CHART_COLORS.red} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                    <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <Tooltip content={<ChartTooltip />} />
                    <Area type="monotone" dataKey="average" name="Avg Stress" stroke={CHART_COLORS.orange} fill="url(#stressGrad)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'sleep-stress': {
            const ssMax = sleepStressData.reduce((m, d) => Math.max(m, d.sleepStress), 0)
            const ssYMax = Math.round(ssMax * 1.15) || 50
            return (
              <DashboardCard key={cardId} title="Sleep Stress" icon={Moon} {...cp}>
                {sleepStressData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <AreaChart data={sleepStressData}>
                      <defs>
                        <linearGradient id="sleepStressGrad" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={CHART_COLORS.purple} stopOpacity={0.3} />
                          <stop offset="95%" stopColor={CHART_COLORS.purple} stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                      <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                      <YAxis domain={[0, ssYMax]} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                      <Tooltip content={<ChartTooltip />} />
                      <Area type="monotone" dataKey="sleepStress" name="Avg Sleep Stress" stroke={CHART_COLORS.purple} fill="url(#sleepStressGrad)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
              </DashboardCard>
            )
          }

          case 'hrv': {
            // Get latest baseline for the status badge
            const latestHrv = hrvData.length > 0 ? hrvData[hrvData.length - 1] : null
            const hrvStatus = latestHrv?.status as string | null
            // Compute Y domain from all visible values (hrv + baseline) ± 15%
            let hrvMin = Infinity, hrvMax = -Infinity
            for (const d of hrvData) {
              if (d.hrv > 0) { hrvMin = Math.min(hrvMin, d.hrv); hrvMax = Math.max(hrvMax, d.hrv) }
              if (d.balancedLow) { hrvMin = Math.min(hrvMin, d.balancedLow) }
              if (d.balancedUpper) { hrvMax = Math.max(hrvMax, d.balancedUpper) }
            }
            const hrvPad = Math.max(3, Math.round((hrvMax - hrvMin) * 0.15))
            const hrvYDomain: [number, number] = hrvMin === Infinity ? [0, 100] : [Math.max(0, hrvMin - hrvPad), hrvMax + hrvPad]
            const statusColors: Record<string, string> = {
              BALANCED: 'bg-emerald-500/15 text-emerald-400',
              UNBALANCED: 'bg-orange-500/15 text-orange-400',
              LOW: 'bg-red-500/15 text-red-400',
              POOR: 'bg-red-500/15 text-red-400',
            }
            return (
              <DashboardCard key={cardId} title="HRV" icon={Activity} {...cp}>
                {hrvData.length > 0 ? (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-2xl font-bold text-foreground">{latestHrv?.hrv || 0}</span>
                        <span className="text-xs text-muted-foreground">ms</span>
                        {hrvStatus && (
                          <span className={`text-xs font-medium px-2 py-0.5 rounded ${statusColors[hrvStatus] || 'bg-gray-500/15 text-gray-400'}`}>
                            {hrvStatus.charAt(0) + hrvStatus.slice(1).toLowerCase()}
                          </span>
                        )}
                      </div>
                      {latestHrv?.balancedLow && latestHrv?.balancedUpper && (
                        <span className="text-xs text-muted-foreground">Baseline: {latestHrv.balancedLow}–{latestHrv.balancedUpper} ms</span>
                      )}
                    </div>
                    <ResponsiveContainer width="100%" height={180}>
                      <ComposedChart data={hrvData}>
                        <defs>
                          <linearGradient id="hrvBaseline" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={CHART_COLORS.green} stopOpacity={0.2} />
                            <stop offset="100%" stopColor={CHART_COLORS.green} stopOpacity={0.05} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                        <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                        <YAxis domain={hrvYDomain} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                        <Tooltip content={<ChartTooltip />} />
                        <Area type="monotone" dataKey="balancedUpper" name="Baseline High" stroke="none" fill="url(#hrvBaseline)" />
                        <Area type="monotone" dataKey="balancedLow" name="Baseline Low" stroke="none" fill="hsl(222 47% 8%)" />
                        <Line type="monotone" dataKey="hrv" name="HRV" stroke={CHART_COLORS.green} strokeWidth={2} dot={{ fill: CHART_COLORS.green, r: 2 }} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
              </DashboardCard>
            )
          }

          case 'spo2': return (
            <DashboardCard key={cardId} title="SpO2" icon={Wind} {...cp}>
              {spo2Data.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={spo2Data}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                    <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <YAxis domain={[90, 100]} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} unit="%" />
                    <Tooltip content={<ChartTooltip />} />
                    <Line type="monotone" dataKey="spo2" name="SpO2" stroke={CHART_COLORS.cyan} strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'weight': return (
            <DashboardCard key={cardId} title="Weight" icon={Weight} {...cp}>
              {weightData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={weightData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                    <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} unit=" kg" />
                    <Tooltip content={<ChartTooltip />} />
                    <Line type="monotone" dataKey="weight" name="Weight" stroke={CHART_COLORS.gray} strokeWidth={2} dot={{ fill: CHART_COLORS.gray, r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'floors': return (
            <DashboardCard key={cardId} title="Floors Climbed" icon={Layers} {...cp}>
              {floorsData.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={floorsData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                    <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="floors" name="Floors" fill={CHART_COLORS.teal} radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'training-load': return (
            <DashboardCard key={cardId} title="Acute Training Load" icon={Flame} {...cp}>
              {trainingLoadData.length > 0 ? (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl font-bold text-foreground">{acuteLoad}</span>
                      <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                        acuteLoad < optimalLow ? 'bg-blue-500/15 text-blue-400' :
                        acuteLoad <= optimalHigh ? 'bg-emerald-500/15 text-emerald-400' :
                        acuteLoad <= highThreshold ? 'bg-orange-500/15 text-orange-400' :
                        'bg-red-500/15 text-red-400'
                      }`}>
                        {acuteLoad < optimalLow ? 'Low' : acuteLoad <= optimalHigh ? 'Optimal' : acuteLoad <= highThreshold ? 'High' : 'Very High'}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">Optimal: {optimalLow}–{optimalHigh}</span>
                  </div>
                  <ResponsiveContainer width="100%" height={180}>
                    <ComposedChart data={trainingLoadData}>
                      <defs>
                        <linearGradient id="optZone" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={CHART_COLORS.green} stopOpacity={0.15} />
                          <stop offset="100%" stopColor={CHART_COLORS.green} stopOpacity={0.05} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                      <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                      <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                      <Tooltip content={<ChartTooltip />} />
                      <Area type="monotone" dataKey="optHigh" name="Optimal High" stroke="none" fill="url(#optZone)" />
                      <Area type="monotone" dataKey="optLow" name="Optimal Low" stroke="none" fill="hsl(222 47% 8%)" />
                      <Line type="monotone" dataKey="acute" name="Acute Load" stroke={CHART_COLORS.red} strokeWidth={2.5} dot={false} />
                      <Bar dataKey="load" name="Activity Load" fill={CHART_COLORS.red} fillOpacity={0.3} radius={[2, 2, 0, 0]} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No activities with training load</div>}
            </DashboardCard>
          )

          case 'fitness-age': return (
            <DashboardCard key={cardId} title="Fitness Age" icon={Gauge} {...cp}>
              {fitnessAgeData ? (
                <div className="flex flex-col items-center justify-center h-[200px]">
                  <div className="text-center mb-4">
                    <span className="text-5xl font-bold text-foreground">{fitnessAgeData.fitnessAge}</span>
                    <span className="text-lg text-muted-foreground ml-2">Jahre</span>
                  </div>
                  <div className="text-sm text-muted-foreground">
                    Chronologisch: <span className="text-foreground font-medium">{fitnessAgeData.chronologicalAge}</span>
                    <span className={`ml-2 font-medium ${fitnessAgeData.fitnessAge < fitnessAgeData.chronologicalAge ? 'text-emerald-400' : 'text-orange-400'}`}>
                      ({fitnessAgeData.fitnessAge < fitnessAgeData.chronologicalAge ? '-' : '+'}{Math.abs(fitnessAgeData.chronologicalAge - fitnessAgeData.fitnessAge)} Jahre)
                    </span>
                  </div>
                  {fitnessAgeData.components?.rhr && (
                    <div className="text-xs text-muted-foreground mt-2">
                      Ruhe-HR: {fitnessAgeData.components.rhr.value} · BMI: {fitnessAgeData.components.bmi?.value}
                    </div>
                  )}
                </div>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'vo2max': return (
            <DashboardCard key={cardId} title="VO2max" icon={Activity} {...cp}>
              {vo2maxData.points.length > 0 ? (
                <div>
                  <div className="flex items-center justify-center gap-6 mb-2">
                    {vo2maxData.latestRunning > 0 && (
                      <div className="text-center">
                        <span className="text-2xl font-bold text-foreground">{vo2maxData.latestRunning}</span>
                        <span className="text-xs text-muted-foreground block">Running</span>
                      </div>
                    )}
                    {vo2maxData.latestCycling > 0 && (
                      <div className="text-center">
                        <span className="text-2xl font-bold text-foreground">{vo2maxData.latestCycling}</span>
                        <span className="text-xs text-muted-foreground block">Cycling</span>
                      </div>
                    )}
                  </div>
                  <ResponsiveContainer width="100%" height={140}>
                    <LineChart data={vo2maxData.points}>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                      <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                      <YAxis domain={['auto', 'auto']} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                      <Tooltip content={<ChartTooltip />} />
                      <Line type="monotone" dataKey="running" name="Running" stroke={CHART_COLORS.green} strokeWidth={2} dot={{ fill: CHART_COLORS.green, r: 3 }} connectNulls={false} />
                      <Line type="monotone" dataKey="cycling" name="Cycling" stroke={CHART_COLORS.blue} strokeWidth={2} dot={{ fill: CHART_COLORS.blue, r: 3 }} connectNulls={false} />
                      <Legend wrapperStyle={{ fontSize: 11, color: CHART_COLORS.axis }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
            </DashboardCard>
          )

          case 'intensity': {
            const latest = intensityData.length > 0 ? intensityData[intensityData.length - 1] : null
            const lastWeekKey = intensityWeekKeys[intensityWeekKeys.length - 1]
            const goal = latest?.goal || 150
            const current = latest?.[lastWeekKey] ?? 0
            const maxCumulative = intensityData.reduce((m, d) => {
              for (const k of intensityWeekKeys) { if (d[k] != null) m = Math.max(m, d[k]) }
              return m
            }, 0)
            const remaining = Math.max(0, goal - current)
            const remainingMod = remaining
            const remainingVig = Math.ceil(remaining / 2)
            return (
              <DashboardCard key={cardId} title="Intensity Minutes" icon={Flame} {...cp}>
                {intensityData.length > 0 ? (
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-2xl font-bold text-foreground">{current}</span>
                        <span className="text-xs text-muted-foreground">/ {goal} min</span>
                        {current >= goal && (
                          <span className="text-xs font-medium px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400">Reached</span>
                        )}
                      </div>
                      {remaining > 0 && (
                        <div className="text-right text-xs text-muted-foreground leading-tight">
                          <span className="block">Noch {remainingMod} min Moderate</span>
                          <span className="block">oder {remainingVig} min Vigorous</span>
                        </div>
                      )}
                    </div>
                    <ResponsiveContainer width="100%" height={180}>
                      <ComposedChart data={intensityData}>
                        <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
                        <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
                        <YAxis domain={[0, Math.round(Math.max(goal, maxCumulative) * 1.1)]} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} unit=" min" />
                        <Tooltip content={<ChartTooltip />} />
                        {intensityWeekKeys.map((wk, i) => (
                          <Line key={wk} type="stepAfter" dataKey={wk} name="Total" stroke={CHART_COLORS.yellow} strokeWidth={2.5} dot={{ fill: CHART_COLORS.yellow, r: 2 }} connectNulls={false} legendType={i === 0 ? 'line' : 'none'} />
                        ))}
                        <Line type="stepAfter" dataKey="goal" name="Goal" stroke={CHART_COLORS.green} strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
                        <Legend wrapperStyle={{ fontSize: 11, color: CHART_COLORS.axis }} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No data</div>}
              </DashboardCard>
            )
          }

          case 'activities': return (
            <DashboardCard key={cardId} title="Recent Activities" icon={Activity} {...cp}>
              {activitiesData.length > 0 ? (
                <div className="overflow-auto max-h-[240px]">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border text-muted-foreground">
                        <th className="text-left py-1.5 px-2 font-medium">Type</th>
                        <th className="text-left py-1.5 px-2 font-medium">Date</th>
                        <th className="text-left py-1.5 px-2 font-medium">Duration</th>
                        <th className="text-left py-1.5 px-2 font-medium">Distance</th>
                        <th className="text-left py-1.5 px-2 font-medium">Avg HR</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activitiesData.map((a, i) => (
                        <tr key={i} className="border-b border-border/50">
                          <td className="py-1.5 px-2 text-foreground">
                            {a.activityType?.typeKey || a.activityType || a.sportType || 'Activity'}
                          </td>
                          <td className="py-1.5 px-2 text-muted-foreground">
                            {formatDateShort(a.startTimeLocal || a.date)}
                          </td>
                          <td className="py-1.5 px-2 text-muted-foreground">
                            {a.duration ? formatDuration(a.duration) : a.elapsedDuration ? formatDuration(a.elapsedDuration / 1000) : '-'}
                          </td>
                          <td className="py-1.5 px-2 text-muted-foreground">
                            {a.distance ? formatDistance(a.distance) : '-'}
                          </td>
                          <td className="py-1.5 px-2 text-muted-foreground">
                            {a.averageHR || a.averageHeartRate || '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">No activities</div>}
            </DashboardCard>
          )

          default: return null
          }
        })}
      </div>
    </div>
  )
}
