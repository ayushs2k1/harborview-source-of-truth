import { useEffect, useState } from 'react'
import { getParams, listDecisions, putParams, resetParams, type Param } from '../api/client'
import { Button, Card, Cell, Chip, ErrorNote, Loading, PageTitle, Row, Table } from '../components/ui'
import { useApi } from '../hooks/useApi'

export default function Settings() {
  const params = useApi(() => getParams(), [])
  const decisions = useApi(() => listDecisions(), [])
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState<string[]>([])
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (params.data) {
      setDraft(
        Object.fromEntries(params.data.params.map((item) => [item.key, String(item.value ?? '')])),
      )
    }
  }, [params.data])

  const save = async () => {
    setError(null)
    try {
      const changed: Record<string, unknown> = {}
      for (const item of params.data?.params ?? []) {
        const next = draft[item.key]
        if (next !== undefined && next !== String(item.value ?? '')) {
          changed[item.key] = item.type === 'bool' ? next === 'true' : Number(next)
        }
      }
      if (Object.keys(changed).length === 0) return
      const result = await putParams(changed)
      setSaved(result.updated)
      params.reload()
    } catch (reason) {
      setError(reason)
    }
  }

  if (!params.data) return <Loading what="Loading settings" />

  return (
    <div className="space-y-4">
      <PageTitle
        title="Settings"
        subtitle="Thresholds live in the pack with their sources cited. Changes are saved as overrides, so the shipped defaults stay visible and one reset undoes everything."
      />

      {error ? <ErrorNote error={error} /> : null}
      {saved.length > 0 && (
        <p className="rounded border border-ok/30 bg-ok-soft px-3 py-2 text-[13px] text-ok">
          Saved {saved.join(', ')}. Re-run from the Pipeline page to apply.
        </p>
      )}

      <Card
        title={`Parameters · ${params.data.pack}`}
        actions={
          <div className="flex gap-2">
            <Button onClick={save}>Save</Button>
            <Button
              onClick={async () => {
                await resetParams()
                params.reload()
                setSaved([])
              }}
            >
              Reset to pack defaults
            </Button>
          </div>
        }
      >
        <Table head={['Setting', 'Value', 'Range', 'Shipped default']}>
          {params.data.params.map((item: Param) => (
            <Row key={item.key}>
              <Cell>
                <div className="font-medium">{item.label}</div>
                <code className="text-[11px] text-ink-soft">{item.key}</code>
              </Cell>
              <Cell>
                {item.type === 'bool' ? (
                  <select
                    value={draft[item.key] ?? ''}
                    onChange={(event) =>
                      setDraft({ ...draft, [item.key]: event.target.value })
                    }
                    className="rounded border border-line px-2 py-0.5 text-[13px]"
                  >
                    <option value="true">yes</option>
                    <option value="false">no</option>
                  </select>
                ) : (
                  <input
                    value={draft[item.key] ?? ''}
                    onChange={(event) =>
                      setDraft({ ...draft, [item.key]: event.target.value })
                    }
                    className="w-24 rounded border border-line px-2 py-0.5 text-[13px] tabular-nums"
                  />
                )}
                {item.unit && <span className="ml-1 text-[11px] text-ink-soft">{item.unit}</span>}
                {item.overridden && <Chip tone="warn">overridden</Chip>}
              </Cell>
              <Cell className="text-[11px] text-ink-soft">
                {item.min !== null ? `${item.min} – ${item.max}` : '—'}
              </Cell>
              <Cell className="text-[11px] text-ink-soft">{String(item.default ?? '—')}</Cell>
            </Row>
          ))}
        </Table>
      </Card>

      <Card title={`Decision log · ${decisions.data?.count ?? 0}`}>
        <p className="mb-2 text-[12px] text-ink-soft">
          Human input is the memory of the system. Decisions are keyed on the content of
          a record, not its position, so a re-export does not undo them.
        </p>
        <Table head={['When', 'Type', 'About', 'Reason', 'Active']} empty={!decisions.data?.decisions.length}>
          {(decisions.data?.decisions ?? []).map((decision) => (
            <Row key={decision.decision_id}>
              <Cell className="text-[11px]">{decision.created_at?.slice(0, 19) ?? '—'}</Cell>
              <Cell>{decision.type}</Cell>
              <Cell className="font-mono text-[11px]">{decision.key}</Cell>
              <Cell>{decision.reason || '—'}</Cell>
              <Cell>
                <Chip tone={decision.active ? 'ok' : 'neutral'}>
                  {decision.active ? 'in force' : 'withdrawn'}
                </Chip>
              </Cell>
            </Row>
          ))}
        </Table>
      </Card>
    </div>
  )
}
