import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  createDecision,
  getFlag,
  listFlags,
  type Flag,
  type FlagDetail,
  type Severity,
} from '../api/client'
import { Button, Card, Chip, Drawer, ErrorNote, Loading, PageTitle, SeverityChip } from '../components/ui'
import { useApi } from '../hooks/useApi'
import EvidenceViewer from '../components/EvidenceViewer'

const SEVERITIES: Severity[] = ['BLOCKER', 'CRITICAL', 'WARNING', 'INFO']

export default function Flags() {
  const [severity, setSeverity] = useState<Severity | null>(null)
  const [category, setCategory] = useState<string>('')
  const listing = useApi(
    () => listFlags({ severity: severity ?? undefined, category: category || undefined }),
    [severity, category],
  )
  const [open, setOpen] = useState<string | null>(null)
  const detail = useApi(() => (open ? getFlag(open) : Promise.resolve(null)), [open])

  const counts = listing.data?.counts ?? {}
  const categories = Array.from(new Set((listing.data?.flags ?? []).map((flag) => flag.category)))

  return (
    <div className="space-y-4">
      <PageTitle
        title="Flags"
        subtitle="Everything wrong, inconsistent, or needing a human. Each one carries its evidence, a suggested action, and who owns it."
      />

      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={severity === null ? 'ok' : 'neutral'} onClick={() => setSeverity(null)}>
          All {listing.data?.total ?? 0}
        </Chip>
        {SEVERITIES.map((item) => (
          <button key={item} onClick={() => setSeverity(item)} className={severity === item ? 'ring-2 ring-ink/20 rounded' : ''}>
            <SeverityChip severity={item} count={counts[item] ?? 0} />
          </button>
        ))}
        <select
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          className="ml-auto rounded border border-line px-2 py-1 text-[12px]"
        >
          <option value="">Every category</option>
          {categories.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </div>

      {listing.error ? <ErrorNote error={listing.error} /> : null}
      {listing.loading && !listing.data ? <Loading what="Loading findings" /> : null}

      <div className="space-y-2">
        {(listing.data?.flags ?? []).map((flag) => (
          <FlagCard key={flag.flag_id} flag={flag} onOpen={() => setOpen(flag.flag_id)} />
        ))}
        {listing.data && listing.data.flags.length === 0 && (
          <Card>
            <p className="text-[13px] text-ink-soft">
              Nothing to report at this filter. For the clean sample that is the expected
              answer.
            </p>
          </Card>
        )}
      </div>

      <Drawer open={Boolean(open)} onClose={() => setOpen(null)} title={detail.data?.title ?? ''} width="w-[640px]">
        {detail.data && <FlagDetailView flag={detail.data} onDone={() => { setOpen(null); listing.reload() }} />}
      </Drawer>
    </div>
  )
}

function FlagCard({ flag, onOpen }: { flag: Flag; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="block w-full rounded-lg border border-line bg-surface px-4 py-3 text-left hover:bg-surface-sunk"
    >
      <div className="flex items-center gap-2">
        <SeverityChip severity={flag.severity} />
        <span className="text-[13px] font-semibold">{flag.title}</span>
        <code className="text-[11px] text-ink-soft">{flag.rule_code}</code>
        {flag.occurrence_count > 1 && <Chip>×{flag.occurrence_count}</Chip>}
        <span className="ml-auto text-[11px] text-ink-soft">{flag.owner_role}</span>
      </div>
      <p className="mt-1 text-[13px]">{flag.message}</p>
      {flag.entities.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {flag.entities.map((entity) => (
            <Chip key={`${entity.type}:${entity.id}`}>{entity.display}</Chip>
          ))}
        </div>
      )}
    </button>
  )
}

function FlagDetailView({ flag, onDone }: { flag: FlagDetail; onDone: () => void }) {
  const [reason, setReason] = useState('')
  const [saved, setSaved] = useState(false)

  const dismiss = async () => {
    await createDecision({
      decision_type: 'DISMISS_FLAG',
      key: { flag_id: flag.flag_id },
      value: { reason },
      reason,
    })
    setSaved(true)
  }

  return (
    <div className="space-y-4 text-[13px]">
      <div className="flex items-center gap-2">
        <SeverityChip severity={flag.severity} />
        <code className="text-[11px] text-ink-soft">{flag.rule_code}</code>
        <Chip>{flag.category}</Chip>
        <Chip>{flag.rule.priority}</Chip>
      </div>
      <p>{flag.message}</p>

      <Card title="What to do">
        <p>{flag.suggested_action}</p>
        <p className="mt-1 text-[11px] text-ink-soft">Owner: {flag.owner_role}</p>
      </Card>

      <Card title="What this rule means">
        <p className="text-[12px]">{flag.rule.meaning}</p>
        {flag.rule.severity_note && (
          <p className="mt-1 text-[11px] text-ink-soft">{flag.rule.severity_note}</p>
        )}
        {flag.rule.configured_by.length > 0 && (
          <p className="mt-1 text-[11px] text-ink-soft">
            Configured by {flag.rule.configured_by.join(', ')}
          </p>
        )}
      </Card>

      {flag.entities.length > 0 && (
        <Card title="Who this is about">
          <div className="flex flex-wrap gap-1">
            {flag.entities.map((entity) =>
              entity.type === 'person' ? (
                <Link key={entity.id} to={`/people/${entity.id}`}>
                  <Chip tone="neutral">{entity.display} →</Chip>
                </Link>
              ) : (
                <Chip key={entity.id}>{entity.display}</Chip>
              ),
            )}
          </div>
        </Card>
      )}

      {flag.evidence.length > 0 && (
        <Card title={`Evidence (${flag.evidence.length})`}>
          <EvidenceViewer evidence={flag.evidence} />
        </Card>
      )}

      <Card title="Set aside">
        <p className="text-[12px] text-ink-soft">
          Dismissing records a reason and is remembered on the next run. It is kept in the
          audit log either way.
        </p>
        <div className="mt-2 flex gap-2">
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Why is this not a problem?"
            className="flex-1 rounded border border-line px-2 py-1 text-[13px]"
          />
          <Button onClick={dismiss} disabled={!reason || saved}>
            {saved ? 'Recorded' : 'Dismiss'}
          </Button>
        </div>
        {saved && (
          <p className="mt-2 text-[12px] text-ok">
            Recorded. Re-run from the Pipeline page to see it applied.{' '}
            <button className="underline" onClick={onDone}>
              Close
            </button>
          </p>
        )}
      </Card>
    </div>
  )
}
