import { useState } from 'react'
import { getStaffing, type StaffingRow } from '../api/client'
import { Card, Cell, Chip, ErrorNote, Kpi, Loading, PageTitle, Row, Table } from '../components/ui'
import { useApi } from '../hooks/useApi'

const TIER_TONE: Record<string, 'ok' | 'warn' | 'neutral' | 'bad'> = {
  VERIFIED: 'ok',
  CONFLICT: 'warn',
  SCHEDULE_ONLY: 'neutral',
  UNALLOCATED: 'bad',
}

export default function Staffing() {
  const [facility, setFacility] = useState('')
  const { data, error, loading } = useApi(
    () => getStaffing({ facility: facility || undefined }),
    [facility],
  )
  if (error) return <ErrorNote error={error} />
  if (!data) return <Loading what="Loading staffing" />

  const facilities = Array.from(new Set(data.rows.map((row) => row.facility)))
  const byDay = new Map<string, StaffingRow[]>()
  for (const row of data.rows) {
    const key = `${row.facility}|${row.work_date}`
    byDay.set(key, [...(byDay.get(key) ?? []), row])
  }
  const roles = Array.from(new Set(data.rows.map((row) => row.role))).sort()

  return (
    <div className="space-y-4">
      <PageTitle
        title="Staffing"
        subtitle="Reportable hours by calendar day, with meal time excluded and overnight shifts split at midnight. Every figure carries how far it is corroborated."
      />

      <div className="flex flex-wrap gap-2">
        <Chip tone={facility === '' ? 'ok' : 'neutral'} onClick={() => setFacility('')}>
          All sites
        </Chip>
        {facilities.map((item) => (
          <Chip key={item} tone={facility === item ? 'ok' : 'neutral'} onClick={() => setFacility(item)}>
            {item}
          </Chip>
        ))}
        <a
          className="ml-auto rounded border border-line px-2 py-0.5 text-[12px] hover:bg-surface-sunk"
          href="/api/exports/pbj_daily_hours.csv"
        >
          Export CSV
        </a>
      </div>

      {data.summaries.map((summary) => (
        <Card
          key={`${summary.facility}-${summary.period_start}`}
          title={`${summary.facility} · ${summary.period_start} to ${summary.period_end}`}
          actions={<span className="text-[11px] text-ink-soft">{summary.quarter}</span>}
        >
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Kpi label="Reported hours" value={summary.total_hours} />
            <Kpi
              label="Verified"
              value={`${summary.pct_verified}%`}
              tone={summary.pct_verified >= 95 ? 'ok' : 'warn'}
              hint="reconciles with payroll"
            />
            <Kpi
              label="Unallocated"
              value={summary.unallocated_hours}
              tone={summary.unallocated_hours ? 'warn' : 'ok'}
              hint="paid, no rota day"
            />
            <Kpi
              label="Zero-RN days"
              value={summary.zero_rn_days}
              tone={
                summary.zero_rn_days >= summary.zero_rn_critical
                  ? 'bad'
                  : summary.zero_rn_days >= summary.zero_rn_warn
                    ? 'warn'
                    : 'ok'
              }
              hint={`critical at ${summary.zero_rn_critical}`}
            />
            <Kpi
              label="Traceability"
              value={`${summary.traceability_variance_pct}%`}
              tone={
                summary.traceability_variance_pct > summary.traceability_threshold ? 'bad' : 'ok'
              }
              hint={`tolerance ${summary.traceability_threshold}%`}
            />
            <Kpi label="Cap breaches" value={summary.cap_violations} tone={summary.cap_violations ? 'bad' : 'ok'} />
          </div>
        </Card>
      ))}

      <Card title="Assumptions">
        <p className="mb-2 text-[12px] text-ink-soft">
          These change the numbers above. They are configurable in Settings, and shown
          here because a figure whose assumptions are hidden is not auditable.
        </p>
        <div className="flex flex-wrap gap-1">
          {Object.entries(data.assumptions).map(([key, value]) => (
            <Chip key={key}>
              {key.replace(/_/g, ' ')}: {String(value)}
            </Chip>
          ))}
        </div>
      </Card>

      <Card title="Hours by day">
        <div className="mb-2 flex flex-wrap gap-1 text-[11px]">
          {Object.entries(TIER_TONE).map(([tier, tone]) => (
            <Chip key={tier} tone={tone}>
              {tier.toLowerCase().replace('_', ' ')}
            </Chip>
          ))}
        </div>
        <Table head={['Site', 'Date', 'Person', 'Role', ...roles.map(() => ''), 'Hours', 'Tier']} empty={!data.rows.length}>
          {data.rows.map((row, index) => (
            <Row key={index}>
              <Cell>{row.facility}</Cell>
              <Cell>{row.work_date}</Cell>
              <Cell className="font-medium">{row.display_name}</Cell>
              <Cell>
                {row.role}
                {row.pbj_job_code && (
                  <span className="ml-1 text-[10px] text-ink-soft">#{row.pbj_job_code}</span>
                )}
              </Cell>
              {roles.map((role) => (
                <Cell key={role} className="tabular-nums text-ink-soft">
                  {row.role === role ? row.pbj_hours : ''}
                </Cell>
              ))}
              <Cell className="tabular-nums font-medium">
                {row.pbj_hours}
                {row.meal_deduction > 0 && (
                  <span className="ml-1 text-[10px] text-ink-soft">
                    ({row.scheduled_hours} − {row.meal_deduction})
                  </span>
                )}
              </Cell>
              <Cell>
                <Chip tone={TIER_TONE[row.tier] ?? 'neutral'}>{row.tier.toLowerCase()}</Chip>
              </Cell>
            </Row>
          ))}
        </Table>
      </Card>
      {loading && <Loading what="Refreshing" />}
    </div>
  )
}
