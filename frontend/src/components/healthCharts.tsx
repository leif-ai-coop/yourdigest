import {
  Heart, Battery, Moon, Footprints, Brain, Activity,
  Wind, Weight, Layers, Flame, Gauge,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Legend, ComposedChart,
} from 'recharts'

// Shared between HealthPage and the Dashboard so the dashboard renders the
// EXACT same diagrams. deriveHealthData = the per-card transforms; HealthChartBody
// = the chart JSX (without any card wrapper).

export const CHART_COLORS = {
  grid: 'hsl(222 40% 18%)', axis: 'hsl(215 20% 55%)',
  tooltip_bg: 'hsl(222 44% 11%)', tooltip_border: 'hsl(222 40% 18%)',
  green: '#22c55e', red: '#ef4444', blue: '#3b82f6', indigo: '#6366f1',
  purple: '#a855f7', orange: '#f97316', cyan: '#06b6d4', gray: '#9ca3af',
  teal: '#14b8a6', yellow: '#eab308', amber: '#f59e0b',
}

export interface GarminSnapshot { date: string; data: Record<string, any> }
export interface GarminData {
  stats: GarminSnapshot[]; sleep: GarminSnapshot[]; heart_rate: GarminSnapshot[]
  body_battery: GarminSnapshot[]; stress: GarminSnapshot[]; steps: GarminSnapshot[]
  hrv: GarminSnapshot[]; spo2: GarminSnapshot[]; weight: GarminSnapshot[]
  activities: GarminSnapshot[]; floors: GarminSnapshot[]; intensity_minutes: GarminSnapshot[]
  training_readiness: GarminSnapshot[]; [k: string]: GarminSnapshot[]
}

export const HEALTH_CARDS: { id: string; title: string; icon: LucideIcon }[] = [
  { id: 'body-battery', title: 'Body Battery', icon: Battery },
  { id: 'heart-rate', title: 'Heart Rate', icon: Heart },
  { id: 'sleep', title: 'Sleep', icon: Moon },
  { id: 'steps', title: 'Steps', icon: Footprints },
  { id: 'stress', title: 'Stress', icon: Brain },
  { id: 'sleep-stress', title: 'Sleep Stress', icon: Moon },
  { id: 'hrv', title: 'HRV', icon: Activity },
  { id: 'spo2', title: 'SpO2', icon: Wind },
  { id: 'weight', title: 'Weight', icon: Weight },
  { id: 'floors', title: 'Floors Climbed', icon: Layers },
  { id: 'training-load', title: 'Acute Training Load', icon: Flame },
  { id: 'fitness-age', title: 'Fitness Age', icon: Gauge },
  { id: 'vo2max', title: 'VO2max', icon: Activity },
  { id: 'intensity', title: 'Intensity Minutes', icon: Flame },
  { id: 'activities', title: 'Recent Activities', icon: Activity },
]

export function formatDateShort(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
}
function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600); const m = Math.floor((seconds % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}
function formatDistance(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`
}

export function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border px-3 py-2 text-xs shadow-lg" style={{ backgroundColor: CHART_COLORS.tooltip_bg, borderColor: CHART_COLORS.tooltip_border }}>
      <p className="text-muted-foreground mb-1">{label}</p>
      {payload.map((p: any, i: number) => (
        <p key={i} style={{ color: p.color || p.fill }}>
          {p.name}: <span className="font-medium">{typeof p.value === 'number' ? p.value.toFixed(1) : p.value}</span>
        </p>
      ))}
    </div>
  )
}

export function deriveHealthData(data: GarminData | null) {
  const bodyBatteryData = (data?.body_battery || []).map(s => {
    const d = Array.isArray(s.data) ? s.data[0] : s.data
    if (!d) return { date: formatDateShort(s.date), value: 0 }
    const vals = d.bodyBatteryValuesArray
    let max = 0
    if (Array.isArray(vals)) for (const v of vals) { const val = Array.isArray(v) ? v[1] : v; if (typeof val === 'number' && val > max) max = val }
    if (max === 0) max = d.charged || 0
    return { date: formatDateShort(s.date), value: max }
  })

  const heartRateData = (data?.heart_rate || []).map(s => ({
    date: formatDateShort(s.date), resting: s.data?.restingHeartRate || 0, max: s.data?.maxHeartRate || 0,
  }))

  const sleepData = (data?.sleep || []).map(s => {
    const d = s.data?.dailySleepDTO || s.data || {}
    return {
      date: formatDateShort(s.date),
      deep: (d.deepSleepSeconds || 0) / 3600, light: (d.lightSleepSeconds || 0) / 3600,
      rem: (d.remSleepSeconds || 0) / 3600, awake: (d.awakeSleepSeconds || 0) / 3600,
    }
  })

  const stepsData = (data?.stats || []).map(s => ({
    date: formatDateShort(s.date), steps: s.data?.totalSteps || 0, goal: s.data?.dailyStepGoal || s.data?.totalStepsGoal || 0,
  }))

  const stressData = (data?.stress || []).map(s => ({
    date: formatDateShort(s.date), average: s.data?.avgStressLevel || 0, max: s.data?.maxStressLevel || 0,
  }))

  const sleepStressData = (() => {
    if (!data?.stress || !data?.sleep) return [] as { date: string; sleepStress: number }[]
    const sleepTimes: Record<string, { start: number; end: number }> = {}
    for (const s of data.sleep) {
      const dto = s.data?.dailySleepDTO || s.data || {}
      const start = dto.sleepStartTimestampGMT; const end = dto.sleepEndTimestampGMT
      if (start && end) sleepTimes[s.date] = { start, end }
    }
    return data.stress.map(s => {
      const sleepWindow = sleepTimes[s.date]; const stressVals: number[][] = s.data?.stressValuesArray || []
      let avg = 0
      if (sleepWindow && stressVals.length > 0) {
        const sleepVals = stressVals.filter(([ts, val]) => ts >= sleepWindow.start && ts <= sleepWindow.end && val > 0)
        if (sleepVals.length > 0) avg = Math.round(sleepVals.reduce((sum, [, v]) => sum + v, 0) / sleepVals.length)
      }
      return { date: formatDateShort(s.date), sleepStress: avg }
    }).filter(d => d.sleepStress > 0)
  })()

  const hrvData = (data?.hrv || []).map(s => {
    const summary = s.data?.hrvSummary || {}; const baseline = summary.baseline || {}
    return {
      date: formatDateShort(s.date), hrv: summary.lastNightAvg || summary.weeklyAvg || 0,
      balancedLow: baseline.balancedLow || null, balancedUpper: baseline.balancedUpper || null, status: summary.status || null,
    }
  })

  const spo2Data = (data?.spo2 || []).map(s => ({
    date: formatDateShort(s.date), spo2: s.data?.averageSpO2 || s.data?.latestSpO2 || 0,
  })).filter(d => d.spo2 > 0)

  const weightData = (data?.weight || []).map(s => {
    const wl = s.data?.dateWeightList || []; const entry = wl[0] || {}
    let w = entry.weight || s.data?.totalAverage?.weight || 0
    if (w > 1000) w = w / 1000
    return { date: formatDateShort(s.date), weight: parseFloat(w.toFixed(1)) }
  }).filter(d => d.weight > 0)

  const floorsData = (data?.stats || []).map(s => ({
    date: formatDateShort(s.date), floors: Math.round(s.data?.floorsAscended || 0),
  }))

  const activitiesData = (() => {
    const items: any[] = []
    for (const s of (data?.activities || [])) {
      const acts = Array.isArray(s.data) ? s.data : s.data?.ActivitiesForDay?.payload || []
      for (const a of acts) items.push({ ...a, _date: s.date })
    }
    return items.slice(0, 20)
  })()

  const training = (() => {
    if (!data?.activities) return { trainingLoadData: [] as any[], acuteLoad: 0, optimalLow: 0, optimalHigh: 0, highThreshold: 0 }
    let vo2max = 50
    const maxmetEntries = (data as any)?.maxmet as GarminSnapshot[] | undefined
    if (maxmetEntries?.length) for (const s of maxmetEntries) {
      const entries = Array.isArray(s.data) ? s.data : [s.data]
      for (const e of entries) { if (!e) continue; for (const src of [e.generic, e.cycling]) { const v = src?.vo2MaxPreciseValue || src?.vo2MaxValue; if (v && v > vo2max) vo2max = Math.round(v) } }
    }
    const dailyLoads: Record<string, number> = {}
    for (const s of data.activities) {
      const acts = Array.isArray(s.data) ? s.data : s.data?.ActivitiesForDay?.payload || []
      let dayLoad = 0; for (const a of acts) dayLoad += a.activityTrainingLoad || 0
      dailyLoads[s.date] = dayLoad
    }
    const allDates = Object.keys(dailyLoads).sort()
    if (allDates.length === 0) return { trainingLoadData: [], acuteLoad: 0, optimalLow: 0, optimalHigh: 0, highThreshold: 0 }
    const now = new Date()
    const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    const startD = new Date(allDates[0] + 'T00:00:00'); const endD = new Date(todayStr + 'T00:00:00')
    const dates: string[] = []
    for (let d = new Date(startD); d <= endD; d.setDate(d.getDate() + 1)) {
      const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
      dates.push(iso); if (!(iso in dailyLoads)) dailyLoads[iso] = 0
    }
    const optCenter = vo2max * 5
    const oLow = Math.round(optCenter * 0.7); const oHigh = Math.round(optCenter * 1.3); const hThreshold = Math.round(optCenter * 1.7)
    const chartData = dates.map((d, i) => {
      let acute = 0; for (let j = Math.max(0, i - 6); j <= i; j++) acute += dailyLoads[dates[j]] || 0
      return { date: formatDateShort(d), load: Math.round(dailyLoads[d] || 0), acute: Math.round(acute), optLow: oLow, optHigh: oHigh }
    })
    const latest = chartData[chartData.length - 1]
    return { trainingLoadData: chartData, acuteLoad: latest?.acute || 0, optimalLow: oLow, optimalHigh: oHigh, highThreshold: hThreshold }
  })()

  const vo2maxData = (() => {
    const maxmet = (data as any)?.maxmet as GarminSnapshot[] | undefined
    if (!maxmet) return { points: [] as { date: string; running: number | null; cycling: number | null }[], latestRunning: 0, latestCycling: 0 }
    let latestRunning = 0, latestCycling = 0
    const points = maxmet.filter(s => Array.isArray(s.data) && s.data.length > 0).map(s => {
      const entry = s.data[0]
      const running = entry?.generic?.vo2MaxPreciseValue || entry?.generic?.vo2MaxValue || null
      const cycling = entry?.cycling?.vo2MaxPreciseValue || entry?.cycling?.vo2MaxValue || null
      if (running) latestRunning = running; if (cycling) latestCycling = cycling
      return { date: formatDateShort(s.date), running, cycling }
    }).filter(d => d.running || d.cycling)
    return { points, latestRunning, latestCycling }
  })()

  const fitnessAgeData = (() => {
    if (!(data as any)?.fitnessage) return null
    const items = (data as any).fitnessage as GarminSnapshot[]; const latest = items[items.length - 1]
    if (!latest?.data) return null
    return { fitnessAge: Math.round(latest.data.fitnessAge || 0), chronologicalAge: latest.data.chronologicalAge || 0, components: latest.data.components || {} }
  })()

  const intensity = (() => {
    if (!data?.intensity_minutes) return { intensityData: [] as Record<string, any>[], intensityWeekKeys: [] as string[] }
    let weekIdx = 0; const weekKeys: string[] = ['w0']; const result: Record<string, any>[] = []
    for (let i = 0; i < data.intensity_minutes.length; i++) {
      const s = data.intensity_minutes[i]; const d = new Date(s.date + 'T00:00:00')
      if (d.getDay() === 1 && i > 0) { weekIdx++; weekKeys.push(`w${weekIdx}`) }
      const point: Record<string, any> = { date: formatDateShort(s.date), goal: s.data?.weekGoal || 150 }
      point[`w${weekIdx}`] = s.data?.endDayMinutes || 0; result.push(point)
    }
    return { intensityData: result, intensityWeekKeys: weekKeys }
  })()

  return {
    bodyBatteryData, heartRateData, sleepData, stepsData, stressData, sleepStressData,
    hrvData, spo2Data, weightData, floorsData, activitiesData,
    ...training, vo2maxData, fitnessAgeData, ...intensity,
  }
}

const NoData = ({ text = 'No data' }: { text?: string }) =>
  <div className="h-[200px] flex items-center justify-center text-xs text-muted-foreground">{text}</div>

export function HealthChartBody({ id, d }: { id: string; d: ReturnType<typeof deriveHealthData> }) {
  switch (id) {
    case 'body-battery':
      return d.bodyBatteryData.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={d.bodyBatteryData}>
            <defs><linearGradient id="bbGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={CHART_COLORS.green} stopOpacity={0.3} /><stop offset="95%" stopColor={CHART_COLORS.green} stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <YAxis domain={[0, 100]} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <Tooltip content={<ChartTooltip />} />
            <Area type="monotone" dataKey="value" name="Battery" stroke={CHART_COLORS.green} fill="url(#bbGrad)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      ) : <NoData />

    case 'heart-rate':
      return d.heartRateData.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={d.heartRateData}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <Tooltip content={<ChartTooltip />} />
            <Line type="monotone" dataKey="resting" name="Resting HR" stroke={CHART_COLORS.red} strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="max" name="Max HR" stroke={CHART_COLORS.orange} strokeWidth={1.5} dot={false} strokeDasharray="4 4" />
            <Legend wrapperStyle={{ fontSize: 11, color: CHART_COLORS.axis }} />
          </LineChart>
        </ResponsiveContainer>
      ) : <NoData />

    case 'sleep':
      return d.sleepData.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={d.sleepData}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} unit="h" />
            <Tooltip content={<ChartTooltip />} />
            <Bar dataKey="deep" name="Deep" stackId="sleep" fill={CHART_COLORS.indigo} />
            <Bar dataKey="light" name="Light" stackId="sleep" fill={CHART_COLORS.blue} />
            <Bar dataKey="rem" name="REM" stackId="sleep" fill={CHART_COLORS.purple} />
            <Bar dataKey="awake" name="Awake" stackId="sleep" fill={CHART_COLORS.orange} radius={[2, 2, 0, 0]} />
            <Legend wrapperStyle={{ fontSize: 11, color: CHART_COLORS.axis }} />
          </BarChart>
        </ResponsiveContainer>
      ) : <NoData />

    case 'steps':
      return d.stepsData.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={d.stepsData}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <Tooltip content={<ChartTooltip />} />
            <Bar dataKey="steps" name="Steps" fill={CHART_COLORS.blue} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      ) : <NoData />

    case 'stress':
      return d.stressData.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={d.stressData}>
            <defs><linearGradient id="stressGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={CHART_COLORS.orange} stopOpacity={0.3} /><stop offset="95%" stopColor={CHART_COLORS.red} stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <Tooltip content={<ChartTooltip />} />
            <Area type="monotone" dataKey="average" name="Avg Stress" stroke={CHART_COLORS.orange} fill="url(#stressGrad)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      ) : <NoData />

    case 'sleep-stress': {
      const ssMax = d.sleepStressData.reduce((m, x) => Math.max(m, x.sleepStress), 0)
      const ssYMax = Math.round(ssMax * 1.15) || 50
      return d.sleepStressData.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={d.sleepStressData}>
            <defs><linearGradient id="sleepStressGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={CHART_COLORS.purple} stopOpacity={0.3} /><stop offset="95%" stopColor={CHART_COLORS.purple} stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <YAxis domain={[0, ssYMax]} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <Tooltip content={<ChartTooltip />} />
            <Area type="monotone" dataKey="sleepStress" name="Avg Sleep Stress" stroke={CHART_COLORS.purple} fill="url(#sleepStressGrad)" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      ) : <NoData />
    }

    case 'hrv': {
      const latestHrv = d.hrvData.length > 0 ? d.hrvData[d.hrvData.length - 1] : null
      const hrvStatus = latestHrv?.status as string | null
      let hrvMin = Infinity, hrvMax = -Infinity
      for (const x of d.hrvData) { if (x.hrv > 0) { hrvMin = Math.min(hrvMin, x.hrv); hrvMax = Math.max(hrvMax, x.hrv) } if (x.balancedLow) hrvMin = Math.min(hrvMin, x.balancedLow); if (x.balancedUpper) hrvMax = Math.max(hrvMax, x.balancedUpper) }
      const hrvPad = Math.max(3, Math.round((hrvMax - hrvMin) * 0.15))
      const hrvYDomain: [number, number] = hrvMin === Infinity ? [0, 100] : [Math.max(0, hrvMin - hrvPad), hrvMax + hrvPad]
      const statusColors: Record<string, string> = { BALANCED: 'bg-emerald-500/15 text-emerald-400', UNBALANCED: 'bg-orange-500/15 text-orange-400', LOW: 'bg-red-500/15 text-red-400', POOR: 'bg-red-500/15 text-red-400' }
      return d.hrvData.length > 0 ? (
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-2xl font-bold text-foreground">{latestHrv?.hrv || 0}</span><span className="text-xs text-muted-foreground">ms</span>
              {hrvStatus && <span className={`text-xs font-medium px-2 py-0.5 rounded ${statusColors[hrvStatus] || 'bg-gray-500/15 text-gray-400'}`}>{hrvStatus.charAt(0) + hrvStatus.slice(1).toLowerCase()}</span>}
            </div>
            {latestHrv?.balancedLow && latestHrv?.balancedUpper && <span className="text-xs text-muted-foreground">Baseline: {latestHrv.balancedLow}–{latestHrv.balancedUpper} ms</span>}
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <ComposedChart data={d.hrvData}>
              <defs><linearGradient id="hrvBaseline" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={CHART_COLORS.green} stopOpacity={0.2} /><stop offset="100%" stopColor={CHART_COLORS.green} stopOpacity={0.05} /></linearGradient></defs>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 10 }} interval={0} />
              <YAxis domain={hrvYDomain} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
              <Tooltip content={<ChartTooltip />} />
              <Area type="monotone" dataKey="balancedUpper" name="Baseline High" stroke="none" fill="url(#hrvBaseline)" />
              <Area type="monotone" dataKey="balancedLow" name="Baseline Low" stroke="none" fill="hsl(222 47% 8%)" />
              <Line type="monotone" dataKey="hrv" name="HRV" stroke={CHART_COLORS.green} strokeWidth={2} dot={{ fill: CHART_COLORS.green, r: 2 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : <NoData />
    }

    case 'spo2':
      return d.spo2Data.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={d.spo2Data}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <YAxis domain={[90, 100]} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} unit="%" />
            <Tooltip content={<ChartTooltip />} />
            <Line type="monotone" dataKey="spo2" name="SpO2" stroke={CHART_COLORS.cyan} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : <NoData />

    case 'weight':
      return d.weightData.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={d.weightData}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} unit=" kg" />
            <Tooltip content={<ChartTooltip />} />
            <Line type="monotone" dataKey="weight" name="Weight" stroke={CHART_COLORS.gray} strokeWidth={2} dot={{ fill: CHART_COLORS.gray, r: 2 }} />
          </LineChart>
        </ResponsiveContainer>
      ) : <NoData />

    case 'floors':
      return d.floorsData.length > 0 ? (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={d.floorsData}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <YAxis tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
            <Tooltip content={<ChartTooltip />} />
            <Bar dataKey="floors" name="Floors" fill={CHART_COLORS.teal} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      ) : <NoData />

    case 'training-load':
      return d.trainingLoadData.length > 0 ? (
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <span className="text-2xl font-bold text-foreground">{d.acuteLoad}</span>
              <span className={`text-xs font-medium px-2 py-0.5 rounded ${d.acuteLoad < d.optimalLow ? 'bg-blue-500/15 text-blue-400' : d.acuteLoad <= d.optimalHigh ? 'bg-emerald-500/15 text-emerald-400' : d.acuteLoad <= d.highThreshold ? 'bg-orange-500/15 text-orange-400' : 'bg-red-500/15 text-red-400'}`}>
                {d.acuteLoad < d.optimalLow ? 'Low' : d.acuteLoad <= d.optimalHigh ? 'Optimal' : d.acuteLoad <= d.highThreshold ? 'High' : 'Very High'}
              </span>
            </div>
            <span className="text-xs text-muted-foreground">Optimal: {d.optimalLow}–{d.optimalHigh}</span>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <ComposedChart data={d.trainingLoadData}>
              <defs><linearGradient id="optZone" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={CHART_COLORS.green} stopOpacity={0.15} /><stop offset="100%" stopColor={CHART_COLORS.green} stopOpacity={0.05} /></linearGradient></defs>
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
      ) : <NoData text="No activities with training load" />

    case 'fitness-age':
      return d.fitnessAgeData ? (
        <div className="flex flex-col items-center justify-center h-[200px]">
          <div className="text-center mb-4"><span className="text-5xl font-bold text-foreground">{d.fitnessAgeData.fitnessAge}</span><span className="text-lg text-muted-foreground ml-2">Jahre</span></div>
          <div className="text-sm text-muted-foreground">Chronologisch: <span className="text-foreground font-medium">{d.fitnessAgeData.chronologicalAge}</span>
            <span className={`ml-2 font-medium ${d.fitnessAgeData.fitnessAge < d.fitnessAgeData.chronologicalAge ? 'text-emerald-400' : 'text-orange-400'}`}>({d.fitnessAgeData.fitnessAge < d.fitnessAgeData.chronologicalAge ? '-' : '+'}{Math.abs(d.fitnessAgeData.chronologicalAge - d.fitnessAgeData.fitnessAge)} Jahre)</span>
          </div>
          {d.fitnessAgeData.components?.rhr && <div className="text-xs text-muted-foreground mt-2">Ruhe-HR: {d.fitnessAgeData.components.rhr.value} · BMI: {d.fitnessAgeData.components.bmi?.value}</div>}
        </div>
      ) : <NoData />

    case 'vo2max':
      return d.vo2maxData.points.length > 0 ? (
        <div>
          <div className="flex items-center justify-center gap-6 mb-2">
            {d.vo2maxData.latestRunning > 0 && <div className="text-center"><span className="text-2xl font-bold text-foreground">{d.vo2maxData.latestRunning}</span><span className="text-xs text-muted-foreground block">Running</span></div>}
            {d.vo2maxData.latestCycling > 0 && <div className="text-center"><span className="text-2xl font-bold text-foreground">{d.vo2maxData.latestCycling}</span><span className="text-xs text-muted-foreground block">Cycling</span></div>}
          </div>
          <ResponsiveContainer width="100%" height={140}>
            <LineChart data={d.vo2maxData.points}>
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
      ) : <NoData />

    case 'intensity': {
      const latest = d.intensityData.length > 0 ? d.intensityData[d.intensityData.length - 1] : null
      const lastWeekKey = d.intensityWeekKeys[d.intensityWeekKeys.length - 1]
      const goal = latest?.goal || 150; const current = latest?.[lastWeekKey] ?? 0
      const maxCumulative = d.intensityData.reduce((m, x) => { for (const k of d.intensityWeekKeys) { if (x[k] != null) m = Math.max(m, x[k]) } return m }, 0)
      const remaining = Math.max(0, goal - current)
      return d.intensityData.length > 0 ? (
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2"><span className="text-2xl font-bold text-foreground">{current}</span><span className="text-xs text-muted-foreground">/ {goal} min</span>
              {current >= goal && <span className="text-xs font-medium px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400">Reached</span>}
            </div>
            {remaining > 0 && <div className="text-right text-xs text-muted-foreground leading-tight"><span className="block">Noch {remaining} min Moderate</span><span className="block">oder {Math.ceil(remaining / 2)} min Vigorous</span></div>}
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <ComposedChart data={d.intensityData}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="date" tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} />
              <YAxis domain={[0, Math.round(Math.max(goal, maxCumulative) * 1.1)]} tick={{ fill: CHART_COLORS.axis, fontSize: 11 }} unit=" min" />
              <Tooltip content={<ChartTooltip />} />
              {d.intensityWeekKeys.map((wk, i) => <Line key={wk} type="stepAfter" dataKey={wk} name="Total" stroke={CHART_COLORS.yellow} strokeWidth={2.5} dot={{ fill: CHART_COLORS.yellow, r: 2 }} connectNulls={false} legendType={i === 0 ? 'line' : 'none'} />)}
              <Line type="stepAfter" dataKey="goal" name="Goal" stroke={CHART_COLORS.green} strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
              <Legend wrapperStyle={{ fontSize: 11, color: CHART_COLORS.axis }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : <NoData />
    }

    case 'activities':
      return d.activitiesData.length > 0 ? (
        <div className="overflow-auto max-h-[240px]">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-border text-muted-foreground">
              <th className="text-left py-1.5 px-2 font-medium">Type</th><th className="text-left py-1.5 px-2 font-medium">Date</th><th className="text-left py-1.5 px-2 font-medium">Duration</th><th className="text-left py-1.5 px-2 font-medium">Distance</th><th className="text-left py-1.5 px-2 font-medium">Avg HR</th>
            </tr></thead>
            <tbody>{d.activitiesData.map((a, i) => (
              <tr key={i} className="border-b border-border/50">
                <td className="py-1.5 px-2 text-foreground">{a.activityType?.typeKey || a.activityType || a.sportType || 'Activity'}</td>
                <td className="py-1.5 px-2 text-muted-foreground">{formatDateShort(a.startTimeLocal || a._date)}</td>
                <td className="py-1.5 px-2 text-muted-foreground">{a.duration ? formatDuration(a.duration) : a.elapsedDuration ? formatDuration(a.elapsedDuration / 1000) : '-'}</td>
                <td className="py-1.5 px-2 text-muted-foreground">{a.distance ? formatDistance(a.distance) : '-'}</td>
                <td className="py-1.5 px-2 text-muted-foreground">{a.averageHR || a.averageHeartRate || '-'}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <NoData text="No activities" />

    default:
      return null
  }
}
