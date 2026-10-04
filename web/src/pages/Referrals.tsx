import { useState } from 'react'
import { getReferral, getStaffing } from '../api/client'
import { Button, Card, Cell, Chip, ErrorNote, Kpi, Loading, PageTitle, Row, Table, TriChip } from '../components/ui'
import { useApi } from '../hooks/useApi'

export default function Referrals() {
  const staffing = useApi(() => getStaffing({}), [])
  const [facility, setFacility] = useState('')
  const [date, setDate] = useState('')
  const [census, setCensus] = useState('')
  const [plusOne, setPlusOne] = useState(true)
  const [query, setQuery] = useState<Record<string, string | number | boolean> | null>(null)
  const result = useApi(
    () => (query ? getReferral(query) : Promise.resolve(null)),
    [JSON.stringify(query)],
  )

  const facilities = Array.from(new Set((staffing.data?.rows ?? []).map((row) => row.facility)))
  const dates = Array.from(new Set((staffing.data?.rows ?? []).map((row) => row.work_date))).sort()
  const chosenFacility = facility || facilities[0] || ''
  const chosenDate = date || dates[0] || ''

  return (
    <div className="space-y-4">
      <PageTitle
        title="Referrals"
        subtitle="Can this site take an admission on this day, and why. A fast indicator — the statutory standard is a quarterly average."
      />

      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[12px]">
            <div className="mb-1 text-ink-soft">Site</div>
            <select
              value={chosenFacility}
              onChange={(event) => setFacility(event.target.value)}
              className="rounded border border-line px-2 py-1 text-[13px]"
            >
              {facilities.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="text-[12px]">
            <div className="mb-1 text-ink-soft">Date</div>
            <select
              value={chosenDate}
              onChange={(event) => setDate(event.target.value)}
              className="rounded border border-line px-2 py-1 text-[13px]"
            >
              {dates.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="text-[12px]">
            <div className="mb-1 text-ink-soft">Census (optional)</div>
            <input
              value={census}
              onChange={(event) => setCensus(event.target.value)}
              placeholder="from file"
              className="w-28 rounded border border-line px-2 py-1 text-[13px]"
            />
          </label>
          <label className="flex items-center gap-1 text-[12px]">
            <input
              type="checkbox"
              checked={plusOne}
              onChange={(event) => setPlusOne(event.target.checked)}
            />
            one more resident
          </label>
          <Button
            tone="primary"
            onClick={() =>
              setQuery({
                facility: chosenFacility,
                work_date: chosenDate,
                plus_one: plusOne,
                ...(census ? { census: Number(census) } : {}),
              })
            }
            disabled={!chosenFacility || !chosenDate}
          >
            Assess
          </Button>
        </div>
      </Card>

      {result.error ? <ErrorNote error={result.error} /> : null}
      {result.loading && query ? <Loading what="Assessing" /> : null}

      {result.data && (
        <>
          <Card
            title={`${result.data.facility} · ${result.data.date}`}
            actions={
              <Chip
                tone={
                  result.data.verdict === 'YES'
                    ? 'ok'
                    : result.data.verdict === 'NO'
                      ? 'bad'
                      : 'unknown'
                }
              >
                {result.data.verdict}
              </Chip>
            }
          >
            <ul className="mb-3 space-y-1 text-[13px]">
              {result.data.reasons.map((reason, index) => (
                <li key={index} className="flex gap-2">
                  <span aria-hidden>·</span>
                  <span>{reason}</span>
                </li>
              ))}
            </ul>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Kpi
                label="RN cover"
                value={`${result.data.rn_longest_run}h`}
                tone={result.data.rn_covered === 'PASS' ? 'ok' : 'bad'}
                hint={`${result.data.rn_required_hours}h required, unbroken`}
              />
              <Kpi label="Licensed hours" value={result.data.licensed_hours} />
              <Kpi label="Aide hours" value={result.data.aide_hours} />
              <Kpi label="Total hours" value={result.data.total_hours} />
            </div>
            {Object.keys(result.data.hprd).length > 0 && (
              <div className="mt-3">
                <h3 className="mb-1 text-[12px] font-semibold">
                  Hours per resident {result.data.census ? `(census ${result.data.census})` : ''}
                </h3>
                <Table head={['Bucket', 'Now', 'With one more', 'Minimum']}>
                  {Object.entries(result.data.hprd_minimums).map(([bucket, minimum]) => (
                    <Row key={bucket}>
                      <Cell>{bucket}</Cell>
                      <Cell className="tabular-nums">{result.data?.hprd[bucket]?.toFixed(2)}</Cell>
                      <Cell className="tabular-nums">
                        {result.data?.hprd_plus_one[bucket]?.toFixed(2) ?? '—'}
                      </Cell>
                      <Cell className="tabular-nums text-ink-soft">{minimum}</Cell>
                    </Row>
                  ))}
                </Table>
              </div>
            )}
            <p className="mt-3 text-[11px] text-ink-soft">{result.data.note}</p>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="On duty">
              <Table head={['Person', 'Role', 'Window', 'Hours', 'Credential']}>
                {result.data.on_duty.map((person) => (
                  <Row key={person.person_id}>
                    <Cell className="font-medium">{person.display_name}</Cell>
                    <Cell>{person.role_code}</Cell>
                    <Cell>{person.window}</Cell>
                    <Cell className="tabular-nums">{person.hours}</Cell>
                    <Cell>
                      <TriChip value={person.credential_status} />
                    </Cell>
                  </Row>
                ))}
              </Table>
            </Card>
            <Card title="Tours">
              <p className="mb-2 text-[12px] text-ink-soft">
                Whether a licensed nurse is on each tour. Operational, not statutory.
              </p>
              <div className="flex flex-wrap gap-1">
                {Object.entries(result.data.tours).map(([name, covered]) => (
                  <Chip key={name} tone={covered ? 'ok' : 'warn'}>
                    {name}: {covered ? 'covered' : 'not covered'}
                  </Chip>
                ))}
              </div>
              {result.data.open_critical.length > 0 && (
                <div className="mt-3">
                  <h3 className="mb-1 text-[12px] font-semibold">Open critical findings</h3>
                  <ul className="space-y-1 text-[12px]">
                    {result.data.open_critical.map((flag, index) => (
                      <li key={index}>{flag.message}</li>
                    ))}
                  </ul>
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
