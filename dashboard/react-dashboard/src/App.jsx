import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  ShieldAlert,
  ShoppingCart,
  Video,
  UserRoundCheck,
  Users,
} from 'lucide-react'
import { WebSocketService } from './services/WebSocketService'

const API_BASE = import.meta.env.VITE_API_BASE || `${window.location.protocol}//${window.location.hostname}:8000`
const STORE_ID = import.meta.env.VITE_STORE_ID || 'STORE_BLR_002'
const WS_URL = import.meta.env.VITE_WS_URL || `${API_BASE.replace(/^http/i, 'ws')}/ws/dashboard`

function normalizeCameraId(value) {
  return String(value ?? '')
    .trim()
    .toUpperCase()
    .replaceAll(' ', '_')
}

function toTitle(text) {
  return String(text ?? '')
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function formatCurrency(value) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(Number(value || 0))
}

function zoneColor(index) {
  const palette = ['#22c55e', '#38bdf8', '#f59e0b', '#a855f7', '#ef4444', '#14b8a6']
  return palette[index % palette.length]
}
const ZONE_FILL_SUFFIX = '1f'

function App() {
  const [status, setStatus] = useState('connecting')
  const [metrics, setMetrics] = useState({
    total_footfall: 0,
    active_customers: 0,
    staff_on_floor: 0,
    queue_length: 0,
    zone_occupancy: { CAM_1: 0, CAM_2: 0 },
  })
  const [revenueSummary, setRevenueSummary] = useState({ total_revenue_inr: 0, transaction_count: 0 })
  const [cameras, setCameras] = useState([])
  const [cameraPolygons, setCameraPolygons] = useState({})
  const [securityFeed, setSecurityFeed] = useState([])
  const alertSequenceRef = useRef(0)

  const wsService = useMemo(() => new WebSocketService(WS_URL), [])

  useEffect(() => {
    const unsubscribePayload = wsService.subscribe((payload) => {
      if (payload.metrics) setMetrics(payload.metrics)
      const events = payload.events || []
      if (!events.length) return

      const alerts = events
        .filter(
          (event) =>
            event.role === 'CUSTOMER' &&
            String(event.zone_id).toLowerCase() === 'cam_4_backroom',
        )
        .map((event) => {
          alertSequenceRef.current += 1
          return {
            id: `${event.event_id}-${event.visitor_id}-${alertSequenceRef.current}`,
            text: `Customer detected in CAM_4_BACKROOM · ${event.visitor_id}`,
            timestamp: new Date().toLocaleTimeString(),
          }
        })

      if (alerts.length) {
        setSecurityFeed((previous) => [...alerts, ...previous].slice(0, 12))
      }
    })

    const unsubscribeStatus = wsService.onStatus(setStatus)
    wsService.connect()

    return () => {
      unsubscribePayload()
      unsubscribeStatus()
      wsService.disconnect()
    }
  }, [wsService])

  useEffect(() => {
    let cancelled = false
    const loadCamerasAndLayout = async () => {
      try {
        const [camerasResponse, layoutResponse] = await Promise.all([
          fetch(`${API_BASE}/cameras`),
          fetch(`${API_BASE}/store-layout`),
        ])

        const camerasPayload = await camerasResponse.json()
        const layoutPayload = await layoutResponse.json()
        if (cancelled) return

        setCameras(camerasPayload.cameras || [])

        const store = layoutPayload?.stores?.[0]
        const polygonsByCamera = {}
        ;(store?.cameras || []).forEach((camera) => {
          const cameraId = normalizeCameraId(camera.camera_id)
          polygonsByCamera[cameraId] = (camera.zones || [])
            .filter((zone) => Array.isArray(zone.polygon) && zone.polygon.length >= 3)
            .map((zone) => ({ zone_id: zone.zone_id, polygon: zone.polygon }))
        })
        setCameraPolygons(polygonsByCamera)
      } catch {
        if (!cancelled) {
          setCameras([])
          setCameraPolygons({})
        }
      }
    }

    loadCamerasAndLayout()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    let timer = null

    const refreshRevenue = async () => {
      try {
        const response = await fetch(`${API_BASE}/stores/${STORE_ID}/revenue-summary`)
        const payload = await response.json()
        if (!cancelled) {
          setRevenueSummary({
            total_revenue_inr: payload.total_revenue_inr || 0,
            transaction_count: payload.transaction_count || 0,
          })
        }
      } catch {
        if (!cancelled) {
          setRevenueSummary({ total_revenue_inr: 0, transaction_count: 0 })
        }
      }
    }

    refreshRevenue()
    timer = setInterval(refreshRevenue, 10000)
    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
  }, [])

  const kpis = [
    {
      label: 'Total Footfall',
      value: metrics.total_footfall ?? 0,
      icon: Users,
      className: 'border-slate-700',
    },
    {
      label: 'Active Customers',
      value: metrics.active_customers ?? 0,
      icon: Activity,
      className: 'border-slate-700',
    },
    {
      label: 'Staff on Floor',
      value: metrics.staff_on_floor ?? 0,
      icon: UserRoundCheck,
      className: 'border-slate-700',
    },
    {
      label: 'Checkout Queue',
      value: metrics.queue_length ?? 0,
      icon: ShoppingCart,
      className:
        (metrics.queue_length ?? 0) > 4
          ? 'border-red-500 animate-pulse-border'
          : 'border-slate-700',
    },
    {
      label: 'Total Revenue',
      value: formatCurrency(revenueSummary.total_revenue_inr ?? 0),
      icon: ShoppingCart,
      className: 'border-emerald-600',
    },
  ]

  return (
    <div className="h-screen overflow-hidden bg-slate-950 text-slate-100">
      <div className="mx-auto grid h-full max-w-[1920px] grid-cols-12 gap-4 p-4">
        <div className="col-span-9 flex min-h-0 flex-col gap-4">
          <header className="rounded-xl border border-slate-800 bg-slate-900 px-5 py-4">
            <div className="flex items-center justify-between">
              <h1 className="text-xl font-semibold tracking-tight">Retail Live Analytics</h1>
              <span className="rounded-md border border-slate-700 px-3 py-1 text-xs uppercase text-slate-400">
                WebSocket: {status}
              </span>
            </div>
          </header>

          <section className="grid grid-cols-5 gap-3">
            {kpis.map(({ label, value, icon: Icon, className }) => (
              <article
                key={label}
                className={`rounded-xl border bg-slate-900 px-4 py-3 ${className}`}
              >
                <div className="mb-2 flex items-center gap-2 text-slate-400">
                  <Icon size={15} />
                  <span className="text-xs uppercase tracking-wide">{label}</span>
                </div>
                <div className="text-3xl font-semibold">{value}</div>
              </article>
            ))}
          </section>

          <section className="min-h-0 flex-1 rounded-xl border border-slate-800 bg-slate-900 p-4">
            <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-slate-400">
              Live Camera Streams
            </h2>
            <div className="grid h-full auto-rows-max grid-cols-2 gap-3 overflow-auto pr-1">
              {cameras.length === 0 && (
                <div className="col-span-2 rounded-lg border border-slate-800 bg-slate-950 p-5 text-sm text-slate-500">
                  No camera stream available.
                </div>
              )}
              {cameras.map((camera) => {
                const normalized = normalizeCameraId(camera)
                const polygons = cameraPolygons[normalized] || []
                return (
                  <article key={camera} className="rounded-lg border border-slate-800 bg-slate-950 p-3">
                    <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
                      <Video size={14} />
                      {toTitle(camera)}
                    </div>
                    <div className="relative overflow-hidden rounded-md border border-slate-800">
                      <img
                        src={`${API_BASE}/cameras/${encodeURIComponent(camera)}/feed`}
                        alt={camera}
                        className="aspect-video w-full object-cover"
                      />
                      <svg
                        className="pointer-events-none absolute inset-0 h-full w-full"
                        viewBox="0 0 1000 560"
                        preserveAspectRatio="none"
                      >
                        {polygons.map((zone, index) => {
                          const color = zoneColor(index)
                          const points = zone.polygon
                            .map(([x, y]) => `${x * 1000},${y * 560}`)
                            .join(' ')
                          const coordinateSum = zone.polygon.reduce(
                            (acc, [x, y]) => [acc[0] + x, acc[1] + y],
                            [0, 0],
                          )
                          const cx = (coordinateSum[0] / zone.polygon.length) * 1000
                          const cy = (coordinateSum[1] / zone.polygon.length) * 560
                          return (
                            <g key={`${camera}-${zone.zone_id}`}>
                              <polygon
                                points={points}
                                fill={`${color}${ZONE_FILL_SUFFIX}`}
                                stroke={color}
                                strokeWidth="2"
                              />
                              <text x={cx} y={cy} fill={color} fontSize="16" textAnchor="middle">
                                {toTitle(zone.zone_id)}
                              </text>
                            </g>
                          )
                        })}
                      </svg>
                    </div>
                  </article>
                )
              })}
            </div>
          </section>
        </div>

        <aside className="col-span-3 flex min-h-0 flex-col rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-slate-300">
            <ShieldAlert size={16} className="text-red-400" />
            Security Feed
          </div>
          <div className="mb-4 grid grid-cols-2 gap-2 text-xs text-slate-400">
            {Object.entries(metrics.zone_occupancy || {}).map(([zone, count]) => (
              <div key={zone} className="rounded-md border border-slate-700 bg-slate-950 p-2">
                {zone} Occupancy: {count}
              </div>
            ))}
          </div>
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
            {securityFeed.length === 0 && (
              <div className="rounded-md border border-slate-800 bg-slate-950 p-3 text-sm text-slate-500">
                No backroom security alerts.
              </div>
            )}
            {securityFeed.map((alert) => (
              <div key={alert.id} className="rounded-md border border-red-900/80 bg-red-950/30 p-3">
                <p className="text-sm text-red-200">{alert.text}</p>
                <p className="mt-1 text-xs text-red-300/80">{alert.timestamp}</p>
              </div>
            ))}
          </div>
          <footer className="mt-4 border-t border-slate-800 pt-3 text-xs text-slate-500">
            Role colors: <span className="text-green-400">Customer</span> ·{' '}
            <span className="text-purple-400">Staff</span>
            <br />
            Zone focus: {toTitle('cam_4_backroom')}
            <br />
            POS Transactions: {revenueSummary.transaction_count ?? 0}
          </footer>
        </aside>
      </div>
    </div>
  )
}

export default App
