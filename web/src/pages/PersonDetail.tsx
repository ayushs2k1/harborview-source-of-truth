import dagre from '@dagrejs/dagre'
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getPerson, getPersonGraph, type FeatureScore, type PersonGraph } from '../api/client'
import { Card, Cell, Chip, Drawer, ErrorNote, Loading, PageTitle, Row, Table } from '../components/ui'
import { useApi } from '../hooks/useApi'

const W = 180
const H = 60

function EntityCard({ data }: NodeProps) {
  const { label, kind, sub } = data as unknown as { label: string; kind: string; sub?: string }
  const tone =
    kind === 'person'
      ? 'border-ink bg-surface font-semibold'
      : kind === 'credential'
        ? 'border-ok/50 bg-ok-soft'
        : 'border-line bg-surface-sunk'
  return (
    <div style={{ width: W }} className={`rounded-lg border px-3 py-2 text-[12px] ${tone}`}>
      <Handle type="target" position={Position.Left} className="!bg-ink-soft" />
      <div>{label}</div>
      {sub && <div className="text-[10px] text-ink-soft">{sub}</div>}
      <Handle type="source" position={Position.Right} className="!bg-ink-soft" />
    </div>
  )
}

const nodeTypes = { entity: EntityCard }

export default function PersonDetail() {
  const { personId = '' } = useParams()
  const person = useApi(() => getPerson(personId), [personId])
  const graph = useApi(() => getPersonGraph(personId), [personId])
  const [waterfall, setWaterfall] = useState<{ title: string; features: FeatureScore[]; total: number | null } | null>(
    null,
  )

  const flow = useMemo(() => (graph.data ? layout(graph.data) : { nodes: [], edges: [] }), [graph.data])

  if (person.error) return <ErrorNote error={person.error} />
  if (!person.data) return <Loading what="Loading the person" />

  const detail = person.data

  return (
    <div className="space-y-4">
      <PageTitle
        title={detail.person.display_name}
        subtitle={
          <>
            {detail.person.role ?? '—'} · {detail.person.home_facility ?? '—'} ·{' '}
            {detail.person.employee_id ?? 'no employee number'}
            {detail.person.status === 'provisional' && (
              <>
                {' '}
                <Chip tone="warn">provisional</Chip>
              </>
            )}
            {' · '}
            <Link to="/people" className="underline underline-offset-2">
              back to people
            </Link>
          </>
        }
      />

      <Card title="Evidence graph" className="overflow-hidden">
        <p className="mb-2 text-[12px] text-ink-soft">
          Every source record that was attached to this person, and the score that
          attached it. Click an edge label to see the reasoning.
        </p>
        <div className="h-[320px] rounded border border-line">
          <ReactFlow
            nodes={flow.nodes}
            edges={flow.edges}
            nodeTypes={nodeTypes}
            fitView
            proOptions={{ hideAttribution: true }}
            onEdgeClick={(_, edge) => {
              const match = graph.data?.edges.find(
                (item) => `${item.source}->${item.target}` === edge.id,
              )
              if (match?.explanation?.features?.length) {
                setWaterfall({
                  title: `${match.source} → ${match.target}`,
                  features: match.explanation.features,
                  total: match.explanation.total,
                })
              }
            }}
          >
            <Background gap={18} size={1} color="#eee" />
          </ReactFlow>
        </div>
      </Card>

      <Card title="Attributes">
        <p className="mb-2 text-[12px] text-ink-soft">
          Nothing is overwritten. The winning value is shown with the rule that chose it;
          every other claim is still here.
        </p>
        <Table head={['Attribute', 'Value', 'From', 'Chosen because', 'Other claims']}>
          {detail.attributes.map((attribute) => (
            <Row key={attribute.attribute}>
              <Cell className="font-medium">{attribute.attribute}</Cell>
              <Cell>{attribute.value}</Cell>
              <Cell>{attribute.source}</Cell>
              <Cell className="text-[11px] text-ink-soft">{attribute.won_because}</Cell>
              <Cell>
                {attribute.all_claims.length > 1 ? (
                  <div className="flex flex-wrap gap-1">
                    {attribute.all_claims
                      .filter((claim) => claim.value !== attribute.value)
                      .map((claim) => (
                        <Chip key={claim.claim_id} tone={attribute.conflicts ? 'warn' : 'neutral'}>
                          {claim.value} ({claim.source})
                        </Chip>
                      ))}
                  </div>
                ) : (
                  <span className="text-ink-soft">—</span>
                )}
              </Cell>
            </Row>
          ))}
        </Table>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Credentials">
          <Table head={['Type', 'Number', 'Expires', 'Verified']} empty={!detail.credentials.length}>
            {detail.credentials.map((credential, index) => (
              <Row key={index}>
                <Cell>{String(credential.credential_type ?? '')}</Cell>
                <Cell className="font-mono text-[12px]">{String(credential.number_norm ?? '')}</Cell>
                <Cell>{String(credential.expires_on ?? '—')}</Cell>
                <Cell>{String(credential.last_verified ?? '—')}</Cell>
              </Row>
            ))}
          </Table>
        </Card>

        <Card title="Weeks">
          <Table
            head={['Period', 'Site', 'Scheduled', 'Paid', 'Status']}
            empty={!detail.weeks.length}
          >
            {detail.weeks.map((week, index) => (
              <Row key={index}>
                <Cell>{String(week.period_start ?? '')}</Cell>
                <Cell>{String(week.facility_code ?? '')}</Cell>
                <Cell className="tabular-nums">{String(week.scheduled_work_hours ?? 0)}</Cell>
                <Cell className="tabular-nums">{String(week.paid_hours ?? 0)}</Cell>
                <Cell>
                  <Chip tone={week.status === 'MATCHED' ? 'ok' : 'warn'}>
                    {String(week.status ?? '')}
                  </Chip>
                </Cell>
              </Row>
            ))}
          </Table>
        </Card>
      </div>

      <Drawer open={Boolean(waterfall)} onClose={() => setWaterfall(null)} title="Why these matched">
        {waterfall && (
          <div className="space-y-2 text-[13px]">
            <Table head={['Feature', 'Compared', 'Verdict', 'Weight']}>
              {waterfall.features.map((feature) => (
                <Row key={feature.feature}>
                  <Cell className="font-medium">{feature.feature.replace('_', ' ')}</Cell>
                  <Cell className="text-[12px]">
                    {feature.left || '—'} vs {feature.right || '—'}
                    {feature.detail && (
                      <div className="text-[11px] text-ink-soft">{feature.detail}</div>
                    )}
                  </Cell>
                  <Cell>{feature.label}</Cell>
                  <Cell
                    className={`tabular-nums font-medium ${feature.weight > 0 ? 'text-ok' : feature.weight < 0 ? 'text-sev-critical' : 'text-ink-soft'}`}
                  >
                    {feature.weight > 0 ? '+' : ''}
                    {feature.weight.toFixed(1)}
                  </Cell>
                </Row>
              ))}
            </Table>
            <p className="text-right text-[13px] font-semibold tabular-nums">
              Total {waterfall.total?.toFixed(1)}
            </p>
          </div>
        )}
      </Drawer>
    </div>
  )
}

function layout(graph: PersonGraph) {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'LR', nodesep: 14, ranksep: 110 })
  for (const node of graph.nodes) g.setNode(node.id, { width: W, height: H })
  for (const edge of graph.edges) g.setEdge(edge.source, edge.target)
  dagre.layout(g)

  const nodes: Node[] = graph.nodes.map((node) => {
    const position = g.node(node.id)
    return {
      id: node.id,
      type: 'entity',
      position: { x: position.x - W / 2, y: position.y - H / 2 },
      data: {
        label: node.kind === 'record' ? (node.source ?? node.label) : node.label,
        kind: node.kind,
        sub: node.kind === 'record' ? `row ${node.row ?? '?'}` : node.expires_on ?? undefined,
      } as unknown as Record<string, unknown>,
    }
  })

  const edges: Edge[] = graph.edges.map((edge) => ({
    id: `${edge.source}->${edge.target}`,
    source: edge.source,
    target: edge.target,
    label:
      edge.score !== undefined && edge.score !== null
        ? `${edge.score.toFixed(1)} ${edge.decided_by}`
        : edge.decided_by,
    style: {
      stroke: edge.band === 'auto' || edge.band === 'anchor' ? '#4a9' : '#c66',
      strokeWidth: 1.5,
    },
    labelStyle: { fontSize: 10, cursor: 'pointer' },
  }))
  return { nodes, edges }
}
