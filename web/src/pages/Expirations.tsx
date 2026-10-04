import { useState } from 'react'
import { getExpirations } from '../api/client'
import { Card, Cell, Chip, ErrorNote, Loading, PageTitle, Row, Table } from '../components/ui'
import { useApi } from '../hooks/useApi'

function bandTone(band: string): 'bad' | 'warn' | 'neutral' | 'ok' {
  if (band === 'EXPIRED') return 'bad'
  if (band === '14d' || band === '30d') return 'bad'
  if (band === '60d' || band === '90d') return 'warn'
  return 'ok'
}

export default function Expirations() {
  const [band, setBand] = useState('')
  const { data, error } = useApi(() => getExpirations({ band: band || undefined }), [band])
  if (error) return <ErrorNote error={error} />
  if (!data) return <Loading what="Loading the radar" />

  const bands = ['EXPIRED', ...data.windows.sort((a, b) => a - b).map((w) => `${w}d`), 'OK']

  return (
    <div className="space-y-4">
      <PageTitle
        title="Expirations"
        subtitle={`Every credential and vendor document, most urgent first, as of ${data.as_of}. Finding out late is a reporting problem, not a records problem.`}
      />

      <div className="flex flex-wrap gap-2">
        <Chip tone={band === '' ? 'ok' : 'neutral'} onClick={() => setBand('')}>
          Everything
        </Chip>
        {bands.map((item) => (
          <Chip
            key={item}
            tone={band === item ? 'ok' : bandTone(item)}
            onClick={() => setBand(item)}
          >
            {item} {data.counts[item] ?? 0}
          </Chip>
        ))}
        <a
          className="ml-auto rounded border border-line px-2 py-0.5 text-[12px] hover:bg-surface-sunk"
          href="/api/exports/credentials.csv"
        >
          Export CSV
        </a>
      </div>

      <Card>
        <Table
          head={['Holder', 'Type', 'Number', 'Expires', 'Days', 'Band', 'Verified', 'After expiry', 'Recert']}
          empty={!data.rows.length}
        >
          {data.rows.map((row, index) => (
            <Row key={index}>
              <Cell>
                <span className="font-medium">{row.holder}</span>
                {row.holder_type === 'org' && <Chip>vendor</Chip>}
                {row.facility && <div className="text-[11px] text-ink-soft">{row.facility}</div>}
              </Cell>
              <Cell>{row.credential_type}</Cell>
              <Cell className="font-mono text-[12px]">{row.number || '—'}</Cell>
              <Cell>{row.expires_on ?? '—'}</Cell>
              <Cell className="tabular-nums">{row.days_left ?? '—'}</Cell>
              <Cell>
                <Chip tone={bandTone(row.band)}>{row.band}</Chip>
              </Cell>
              <Cell>
                {row.last_verified ?? '—'}
                {row.verification_stale && (
                  <Chip tone="warn" title={`${row.verified_age_days} days ago`}>
                    stale
                  </Chip>
                )}
              </Cell>
              <Cell>
                {row.shifts_worked_after_expiry > 0 && (
                  <Chip tone="bad">{row.shifts_worked_after_expiry} worked</Chip>
                )}
                {row.next_shift_after_expiry && (
                  <Chip tone="warn">next {row.next_shift_after_expiry}</Chip>
                )}
                {!row.shifts_worked_after_expiry && !row.next_shift_after_expiry && (
                  <span className="text-ink-soft">—</span>
                )}
              </Cell>
              <Cell>
                {row.recert_hours_required === null ? (
                  <span className="text-ink-soft">—</span>
                ) : (
                  <Chip tone={row.recert_ready ? 'ok' : 'warn'}>
                    {row.recert_hours_found}/{row.recert_hours_required} h
                  </Chip>
                )}
              </Cell>
            </Row>
          ))}
        </Table>
      </Card>
    </div>
  )
}
