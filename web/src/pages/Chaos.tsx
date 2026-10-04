import { api } from '../api/client'
import { Card, Cell, Chip, Kpi, Loading, PageTitle, Row, Table } from '../components/ui'
import { useApi } from '../hooks/useApi'

interface Mutation {
  id: string
  description: string
  expect_codes: string[]
  forbid_codes: string[]
  observed: string[]
  missing: string[]
  forbidden_seen: string[]
  passed: boolean
}

interface Coverage {
  generated_at: string | null
  mutations: Mutation[]
  passed: number
  failed: number
  p0_codes: number
  p0_covered: number
  p0_uncovered: string[]
}

export default function Chaos() {
  const { data, error } = useApi(() => api<Coverage>('/chaos/coverage'), [])

  if (error)
    return (
      <div>
        <PageTitle title="Chaos" subtitle="Mutation coverage" />
        <Card>
          <p className="text-[13px] text-ink-soft">
            No coverage report yet. Run <code className="rounded bg-surface-sunk px-1">make chaos</code>{' '}
            to generate one.
          </p>
        </Card>
      </div>
    )
  if (!data) return <Loading what="Loading coverage" />

  return (
    <div className="space-y-4">
      <PageTitle
        title="Chaos"
        subtitle="Each mutation breaks the clean sample in one specific way and asserts the engine says the right thing about it — and stays quiet about the things it should not say."
      />

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Kpi label="Mutations" value={data.mutations.length} />
        <Kpi label="Passing" value={data.passed} tone={data.failed ? 'warn' : 'ok'} />
        <Kpi label="Failing" value={data.failed} tone={data.failed ? 'bad' : 'ok'} />
        <Kpi
          label="P0 rules covered"
          value={`${data.p0_covered}/${data.p0_codes}`}
          tone={data.p0_uncovered.length ? 'warn' : 'ok'}
        />
      </div>

      {data.p0_uncovered.length > 0 && (
        <Card title="P0 rules with no mutation">
          <div className="flex flex-wrap gap-1">
            {data.p0_uncovered.map((code) => (
              <Chip key={code} tone="warn">
                {code}
              </Chip>
            ))}
          </div>
        </Card>
      )}

      <Card title="Coverage matrix">
        <Table head={['', 'Mutation', 'Expected', 'Must not appear', 'Result']}>
          {data.mutations.map((mutation) => (
            <Row key={mutation.id}>
              <Cell className="font-mono text-[11px]">{mutation.id}</Cell>
              <Cell>{mutation.description}</Cell>
              <Cell>
                <div className="flex flex-wrap gap-1">
                  {mutation.expect_codes.map((code) => (
                    <Chip key={code} tone={mutation.missing.includes(code) ? 'bad' : 'ok'}>
                      {code}
                    </Chip>
                  ))}
                </div>
              </Cell>
              <Cell>
                <div className="flex flex-wrap gap-1">
                  {mutation.forbid_codes.map((code) => (
                    <Chip key={code} tone={mutation.forbidden_seen.includes(code) ? 'bad' : 'neutral'}>
                      {code}
                    </Chip>
                  ))}
                  {!mutation.forbid_codes.length && <span className="text-ink-soft">—</span>}
                </div>
              </Cell>
              <Cell>
                <Chip tone={mutation.passed ? 'ok' : 'bad'}>
                  {mutation.passed ? 'pass' : 'fail'}
                </Chip>
              </Cell>
            </Row>
          ))}
        </Table>
      </Card>
    </div>
  )
}
