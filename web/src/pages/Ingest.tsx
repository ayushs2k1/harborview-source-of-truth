import { useEffect, useState } from 'react'
import { getHealth, type Health } from '../api/client'

/**
 * Phase 0 shows the live backend status so a broken install is obvious before a demo.
 * Drag-and-drop ingestion lands in phase 7.
 */
export default function Ingest() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <div className="max-w-3xl">
      <h1 className="text-lg font-semibold tracking-tight">Ingest</h1>
      <p className="mt-1 text-sm text-ink-soft">
        Drop the roster, payroll, credential, and schedule files here. Built in phase 7.
      </p>

      <section className="mt-6 rounded-lg border border-line bg-surface p-4">
        <h2 className="text-[13px] font-semibold">Backend</h2>
        {error && (
          <p className="mt-2 text-sm text-sev-critical">
            Cannot reach the API: {error}. Start it with <code>make dev</code>.
          </p>
        )}
        {health && (
          <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-[13px]">
            <dt className="text-ink-soft">Engine</dt>
            <dd>v{health.engine_version}</dd>
            <dt className="text-ink-soft">Database</dt>
            <dd>
              {health.database.ok ? (
                <span className="text-ok">{health.database.tables} tables</span>
              ) : (
                <span className="text-sev-critical">{health.database.error}</span>
              )}
            </dd>
            <dt className="text-ink-soft">Packs</dt>
            <dd>{health.packs.length ? health.packs.map((p) => p.id).join(', ') : 'none yet'}</dd>
            <dt className="text-ink-soft">Assist</dt>
            <dd>{health.assist_enabled ? 'enabled' : 'off (deterministic only)'}</dd>
          </dl>
        )}
        {!health && !error && <p className="mt-2 text-sm text-ink-soft">Checking…</p>}
      </section>
    </div>
  )
}
