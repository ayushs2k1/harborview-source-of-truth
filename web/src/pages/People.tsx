import { Link } from 'react-router-dom'
import { listPersons, type Severity } from '../api/client'
import { Cell, Chip, ErrorNote, Loading, PageTitle, Row, SeverityChip, Table } from '../components/ui'
import { useApi } from '../hooks/useApi'

export default function People() {
  const { data, error, loading } = useApi(() => listPersons(), [])
  if (error) return <ErrorNote error={error} />
  if (loading && !data) return <Loading what="Loading people" />

  return (
    <div>
      <PageTitle
        title="People"
        subtitle="Everybody the run knows about. Provisional people were found in one system and nowhere else."
      />
      <Table head={['Name', 'Role', 'Site', 'Credentials', 'Findings']} empty={!data?.persons.length}>
        {(data?.persons ?? []).map((person) => (
          <Row key={person.person_id}>
            <Cell>
              <Link
                to={`/people/${person.person_id}`}
                className="font-medium underline-offset-2 hover:underline"
              >
                {person.display_name}
              </Link>
              {person.status === 'provisional' && (
                <Chip tone="warn" title="Found in one system and in no other">
                  provisional
                </Chip>
              )}
              <div className="text-[11px] text-ink-soft">{person.employee_id ?? '—'}</div>
            </Cell>
            <Cell>{person.role ?? '—'}</Cell>
            <Cell>{person.home_facility ?? '—'}</Cell>
            <Cell>
              {person.credentials.length ? (
                <div className="flex flex-wrap gap-1">
                  {person.credentials.map((credential, index) => (
                    <Chip key={index}>
                      {credential.type} · {credential.expires_on ?? 'no expiry'}
                    </Chip>
                  ))}
                </div>
              ) : (
                <Chip tone="warn">none on file</Chip>
              )}
            </Cell>
            <Cell>
              <div className="flex flex-wrap gap-1">
                {(['BLOCKER', 'CRITICAL', 'WARNING', 'INFO'] as Severity[]).map((severity) =>
                  person.flags[severity] ? (
                    <SeverityChip key={severity} severity={severity} count={person.flags[severity]} />
                  ) : null,
                )}
              </div>
            </Cell>
          </Row>
        ))}
      </Table>
    </div>
  )
}
