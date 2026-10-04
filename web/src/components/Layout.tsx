import { NavLink, Outlet } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { getHealth, type Health } from '../api/client'

/** Left nav order follows the demo script: ingest, watch, triage, then the views. */
const NAV = [
  { to: '/', label: 'Ingest', end: true },
  { to: '/pipeline', label: 'Pipeline' },
  { to: '/flags', label: 'Flags' },
  { to: '/people', label: 'People' },
  { to: '/staffing', label: 'Staffing' },
  { to: '/expirations', label: 'Expirations' },
  { to: '/referrals', label: 'Referrals' },
  { to: '/chaos', label: 'Chaos' },
  { to: '/settings', label: 'Settings' },
] as const

function HeaderStrip({ health }: { health: Health | null }) {
  // Data period and PBJ quarter arrive with the first run (phase 6); until then the
  // strip shows what is actually known rather than inventing placeholders.
  return (
    <header className="flex items-center gap-6 border-b border-line bg-surface px-6 py-3">
      <div>
        <div className="text-[13px] font-semibold tracking-tight">Harborview Source of Truth</div>
        <div className="text-[11px] text-ink-soft">Every number has receipts.</div>
      </div>
      <dl className="ml-auto flex items-center gap-6 text-[11px]">
        <Fact label="As of" value={health?.today ?? '—'} />
        <Fact label="Pack" value={health?.default_pack ?? '—'} />
        <Fact label="Engine" value={health ? `v${health.engine_version}` : '—'} />
        <Fact
          label="API"
          value={health ? 'connected' : 'offline'}
          tone={health ? 'ok' : 'critical'}
        />
      </dl>
    </header>
  )
}

function Fact({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'ok' | 'critical'
}) {
  const toneClass =
    tone === 'ok' ? 'text-ok' : tone === 'critical' ? 'text-sev-critical' : 'text-ink'
  return (
    <div className="flex flex-col">
      <dt className="text-[10px] uppercase tracking-wide text-ink-soft">{label}</dt>
      <dd className={`font-medium ${toneClass}`}>{value}</dd>
    </div>
  )
}

export default function Layout() {
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = () => {
      getHealth()
        .then((h) => !cancelled && setHealth(h))
        .catch(() => !cancelled && setHealth(null))
    }
    poll()
    const timer = setInterval(poll, 10_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  return (
    <div className="flex h-full flex-col">
      <HeaderStrip health={health} />
      <div className="flex min-h-0 flex-1">
        <nav className="w-44 shrink-0 border-r border-line bg-surface py-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={'end' in item ? item.end : false}
              className={({ isActive }) =>
                `block border-l-2 px-5 py-1.5 text-[13px] ${
                  isActive
                    ? 'border-ink bg-surface-sunk font-medium text-ink'
                    : 'border-transparent text-ink-soft hover:bg-surface-sunk'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <main className="min-w-0 flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
