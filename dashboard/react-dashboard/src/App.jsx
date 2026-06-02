import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ShieldAlert,
  ShoppingCart,
  UserRoundCheck,
  Users,
} from 'lucide-react'
import { WebSocketService } from './services/WebSocketService'

const WS_URL = 'ws://localhost:8000/ws/dashboard'

function toTitle(text) {
  return String(text ?? '')
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function App() {
  const [status, setStatus] = useState('connecting')
  const [metrics, setMetrics] = useState({
    total_footfall: 0,
    active_customers: 0,
    staff_on_floor: 0,
    queue_length: 0,
    zone_occupancy: { CAM_1: 0, CAM_2: 0 },
  })
  const [people, setPeople] = useState([])
  const [securityFeed, setSecurityFeed] = useState([])

  const wsService = useMemo(() => new WebSocketService(WS_URL), [])

  useEffect(() => {
    const unsubscribePayload = wsService.subscribe((payload) => {
      if (payload.metrics) setMetrics(payload.metrics)
      const events = payload.events || []
      if (!events.length) return

      setPeople((previous) => {
        const byVisitor = new Map(previous.map((person) => [person.visitor_id, person]))
        events.forEach((event) => {
          if (typeof event.x !== 'number' || typeof event.y !== 'number') return
          byVisitor.set(event.visitor_id, event)
        })
        return Array.from(byVisitor.values()).slice(-80)
      })

      const alerts = events
        .filter(
          (event) =>
            event.role === 'CUSTOMER' &&
            String(event.zone_id).toLowerCase() === 'cam_4_backroom',
        )
        .map((event) => ({
          id: `${event.event_id}-${Date.now()}`,
          text: `Customer detected in CAM_4_BACKROOM · ${event.visitor_id}`,
          timestamp: new Date().toLocaleTimeString(),
        }))

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

          <section className="grid grid-cols-4 gap-3">
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
              Live Floor Plan
            </h2>
            <svg viewBox="0 0 1000 620" className="h-full w-full rounded-lg bg-slate-950">
              <rect x="35" y="35" width="930" height="550" rx="12" fill="#0f172a" stroke="#334155" />
              <rect x="60" y="60" width="420" height="240" fill="#0b1325" stroke="#334155" />
              <text x="72" y="84" fill="#64748b" fontSize="14">
                CAM_1
              </text>
              <rect x="520" y="60" width="420" height="240" fill="#0b1325" stroke="#334155" />
              <text x="532" y="84" fill="#64748b" fontSize="14">
                CAM_2
              </text>
              <rect x="60" y="335" width="420" height="230" fill="#0b1325" stroke="#334155" />
              <text x="72" y="359" fill="#64748b" fontSize="14">
                CAM_3
              </text>
              <rect x="520" y="335" width="200" height="230" fill="#111827" stroke="#334155" />
              <text x="532" y="359" fill="#64748b" fontSize="14">
                CAM_4_BACKROOM
              </text>
              <rect x="740" y="335" width="200" height="230" fill="#0b1325" stroke="#334155" />
              <text x="752" y="359" fill="#64748b" fontSize="14">
                CAM_5
              </text>

              {people.map((person) => (
                <circle
                  key={person.event_id}
                  cx={person.x * 930 + 35}
                  cy={person.y * 550 + 35}
                  r="6"
                  fill={person.role === 'STAFF' ? '#a855f7' : '#22c55e'}
                  opacity="0.92"
                />
              ))}
            </svg>
          </section>
        </div>

        <aside className="col-span-3 flex min-h-0 flex-col rounded-xl border border-slate-800 bg-slate-900 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium uppercase tracking-wide text-slate-300">
            <ShieldAlert size={16} className="text-red-400" />
            Security Feed
          </div>
          <div className="mb-4 grid grid-cols-2 gap-2 text-xs text-slate-400">
            <div className="rounded-md border border-slate-700 bg-slate-950 p-2">
              CAM_1 Occupancy: {metrics.zone_occupancy?.CAM_1 ?? 0}
            </div>
            <div className="rounded-md border border-slate-700 bg-slate-950 p-2">
              CAM_2 Occupancy: {metrics.zone_occupancy?.CAM_2 ?? 0}
            </div>
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
          </footer>
        </aside>
      </div>
    </div>
  )
}

export default App
